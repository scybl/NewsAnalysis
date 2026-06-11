from __future__ import annotations

import argparse
import datetime
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

from .categories import CATEGORIES
from .storage import Mysql, NewsDatabaseConfig, ensure_schema, initialize_database, insert_article, is_existing


DEFAULT_SINCE = "2019-01-01 00:00:00"


@dataclass
class CrawlOptions:
    types: str = ",".join(CATEGORIES.keys())
    since: str = DEFAULT_SINCE
    max_pages: int = 0
    threads: int = 2
    article_sleep: tuple[float, float] = (2.0, 5.0)
    page_sleep: tuple[float, float] = (5.0, 15.0)
    stale_stop_count: int = 10
    new_only: bool = False
    existing_stop_count: int = 10
    max_page_failures: int = 3
    dry_run: bool = False
    migrate: bool = True


def parse_sleep(value: str) -> tuple[float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 2 or parts[0] < 0 or parts[1] < parts[0]:
        raise argparse.ArgumentTypeError("sleep range must be formatted as min,max")
    return tuple(parts)


def normalize_types(type_names: str) -> list[str]:
    selected = []
    for name in [part.strip() for part in type_names.split(",") if part.strip()]:
        if name not in CATEGORIES:
            raise ValueError("未知分类: " + name)
        selected.append(name)
    if not selected:
        raise ValueError("至少需要选择一个分类")
    return selected


def crawl_news(db_config: NewsDatabaseConfig, options: CrawlOptions) -> dict[str, Any]:
    selected_types = normalize_types(options.types)

    if not options.dry_run and options.migrate:
        initialize_database(db_config)
        with Mysql(db_config) as mysql:
            ensure_schema(mysql)

    semaphore = threading.BoundedSemaphore(max(1, options.threads))
    stats: dict[str, dict[str, int]] = {}
    thread_list = []
    for kind in selected_types:
        thread = threading.Thread(target=_crawl_category, args=(kind, db_config, options, semaphore, stats), name=kind)
        thread_list.append(thread)
        thread.start()

    for thread in thread_list:
        thread.join()

    return {"finished_at": datetime.datetime.now().isoformat(sep=" ", timespec="seconds"), "categories": stats}


def _crawl_category(kind: str, db_config: NewsDatabaseConfig, options: CrawlOptions, semaphore: threading.BoundedSemaphore, stats: dict[str, dict[str, int]]) -> None:
    from .page import Fetcher, Page

    with semaphore:
        mysql = None if options.dry_run else Mysql(db_config)
        fetcher = Fetcher()
        pn = 1
        stale_count = 0
        existing_count = 0
        page_failures = 0
        category_stats = {"parsed": 0, "inserted": 0, "skipped": 0}
        stats[kind] = category_stats

        try:
            while True:
                if options.max_pages and pn > options.max_pages:
                    logging.info("%s finish: reached max pages %s", kind, options.max_pages)
                    break

                try:
                    page = Page(kind, pn, fetcher=fetcher, article_sleep=options.article_sleep)
                    articles = page.get_articles()
                    page_failures = 0
                except Exception as exc:
                    page_failures += 1
                    logging.exception("page failed kind=%s page=%s error=%s", kind, pn, exc)
                    if page_failures >= options.max_page_failures:
                        logging.error("%s finish: reached max page failures %s", kind, options.max_page_failures)
                        break
                    time.sleep(random.uniform(*options.page_sleep))
                    continue

                if not articles:
                    logging.info("%s finish: no articles at page %s", kind, pn)
                    break

                for article in articles:
                    info = article.to_dict()
                    category_stats["parsed"] += 1

                    if info.get("time") < options.since:
                        stale_count += 1
                        if stale_count >= options.stale_stop_count:
                            logging.info("%s finish: %s stale articles since %s", kind, stale_count, options.since)
                            return
                        continue
                    stale_count = 0

                    if options.dry_run:
                        logging.info("dry-run kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                        continue

                    if mysql and is_existing(mysql, info):
                        category_stats["skipped"] += 1
                        existing_count += 1
                        logging.info("skip exists kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                        if options.new_only and existing_count >= options.existing_stop_count:
                            logging.info("%s finish: %s continuous existing articles in new-only mode", kind, existing_count)
                            return
                        continue

                    if mysql:
                        insert_article(mysql, info)
                    category_stats["inserted"] += 1
                    existing_count = 0
                    logging.info("insert kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))

                logging.info("%s page=%s parsed=%s inserted=%s skipped=%s", kind, pn, category_stats["parsed"], category_stats["inserted"], category_stats["skipped"])
                pn += 1
                time.sleep(random.uniform(*options.page_sleep))
        finally:
            if mysql:
                mysql.close()
