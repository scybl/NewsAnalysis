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
from .article import extract_seq_from_url
from .storage import Mysql, NewsDatabaseConfig, ensure_schema, initialize_database, insert_article, is_existing, is_existing_identity


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
    claim_registry = CrawlClaimRegistry()
    stats: dict[str, dict[str, int]] = {}
    thread_list = []
    for kind in selected_types:
        thread = threading.Thread(target=_crawl_category, args=(kind, db_config, options, semaphore, claim_registry, stats), name=kind)
        thread_list.append(thread)
        thread.start()

    for thread in thread_list:
        thread.join()

    return {"finished_at": datetime.datetime.now().isoformat(sep=" ", timespec="seconds"), "categories": stats}


class CrawlClaimRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._claimed = set()

    def _keys(self, seq: str | None = None, url: str | None = None) -> list[tuple[str, str]]:
        keys = []
        if seq:
            keys.append(("seq", str(seq)))
        if url:
            keys.append(("url", url))
        return keys

    def claim(self, seq: str | None = None, url: str | None = None) -> bool:
        keys = self._keys(seq=seq, url=url)
        if not keys:
            return True
        with self._lock:
            if any(key in self._claimed for key in keys):
                return False
            self._claimed.update(keys)
            return True

    def release(self, seq: str | None = None, url: str | None = None) -> None:
        with self._lock:
            for key in self._keys(seq=seq, url=url):
                self._claimed.discard(key)


def _crawl_category(kind: str, db_config: NewsDatabaseConfig, options: CrawlOptions, semaphore: threading.BoundedSemaphore, claim_registry: CrawlClaimRegistry, stats: dict[str, dict[str, int]]) -> None:
    from .page import Fetcher, Page

    with semaphore:
        mysql = None if options.dry_run else Mysql(db_config)
        fetcher = Fetcher()
        pn = 1
        stale_count = 0
        existing_count = 0
        page_failures = 0
        category_stats = {"links": 0, "fetched": 0, "parsed": 0, "inserted": 0, "skipped": 0, "existing_prefetch": 0}
        stats[kind] = category_stats

        try:
            while True:
                if options.max_pages and pn > options.max_pages:
                    logging.info("%s finish: reached max pages %s", kind, options.max_pages)
                    break

                try:
                    page = Page(kind, pn, fetcher=fetcher, article_sleep=options.article_sleep)
                    article_links = page.get_article_links()
                    page_failures = 0
                except Exception as exc:
                    page_failures += 1
                    logging.exception("page failed kind=%s page=%s error=%s", kind, pn, exc)
                    if page_failures >= options.max_page_failures:
                        logging.error("%s finish: reached max page failures %s", kind, options.max_page_failures)
                        break
                    time.sleep(random.uniform(*options.page_sleep))
                    continue

                if not article_links:
                    logging.info("%s finish: no articles at page %s", kind, pn)
                    break

                category_stats["links"] += len(article_links)
                for link in article_links:
                    seq = extract_seq_from_url(link)
                    if not claim_registry.claim(seq=seq, url=link):
                        category_stats["skipped"] += 1
                        logging.info("skip in-run duplicate link kind=%s page=%s seq=%s url=%s", kind, pn, seq, link)
                        continue

                    if mysql and is_existing_identity(mysql, seq=seq, url=link):
                        category_stats["skipped"] += 1
                        category_stats["existing_prefetch"] += 1
                        existing_count += 1
                        logging.info("skip existing link kind=%s page=%s seq=%s url=%s", kind, pn, seq, link)
                        if options.new_only and existing_count >= options.existing_stop_count:
                            logging.info("%s finish: %s continuous existing links in new-only mode", kind, existing_count)
                            return
                        continue

                    try:
                        article = page.fetch_article(link)
                        category_stats["fetched"] += 1
                        info = article.to_dict()
                    except Exception as exc:
                        claim_registry.release(seq=seq, url=link)
                        category_stats["skipped"] += 1
                        logging.warning("parse article failed kind=%s page=%s seq=%s url=%s error=%s", kind, pn, seq, link, exc)
                        continue
                    finally:
                        time.sleep(random.uniform(*options.article_sleep))

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

                    inserted = insert_article(mysql, info) if mysql else 1
                    if inserted:
                        category_stats["inserted"] += 1
                        existing_count = 0
                        logging.info("insert kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                    else:
                        category_stats["skipped"] += 1
                        existing_count += 1
                        logging.info("skip duplicate kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))

                logging.info(
                    "%s page=%s links=%s fetched=%s parsed=%s inserted=%s skipped=%s existing_prefetch=%s",
                    kind,
                    pn,
                    category_stats["links"],
                    category_stats["fetched"],
                    category_stats["parsed"],
                    category_stats["inserted"],
                    category_stats["skipped"],
                    category_stats["existing_prefetch"],
                )
                pn += 1
                time.sleep(random.uniform(*options.page_sleep))
        finally:
            logging.info(
                "%s summary links=%s fetched=%s parsed=%s inserted=%s skipped=%s existing_prefetch=%s saved_article_requests=%s",
                kind,
                category_stats["links"],
                category_stats["fetched"],
                category_stats["parsed"],
                category_stats["inserted"],
                category_stats["skipped"],
                category_stats["existing_prefetch"],
                category_stats["existing_prefetch"],
            )
            if mysql:
                mysql.close()
