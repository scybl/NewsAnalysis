#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime
import logging
import os
import random
import threading
import time

from config import config
from mongodb import MongoNewsStore
from page import Fetcher, Page, types as available_types


DEFAULT_SINCE = "2019-01-01 00:00:00"


def parse_sleep(value):
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 2 or parts[0] < 0 or parts[1] < parts[0]:
        raise argparse.ArgumentTypeError("sleep range must be formatted as min,max")
    return tuple(parts)


def parse_args():
    parser = argparse.ArgumentParser(description="同花顺财经新闻爬虫")
    parser.add_argument("--types", default=",".join(available_types.keys()), help="逗号分隔的分类名称")
    parser.add_argument("--since", default=DEFAULT_SINCE, help="抓取到该发布时间后停止，格式: YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--max-pages", type=int, default=0, help="每个分类最多抓取页数，0 表示不限制")
    parser.add_argument("--threads", type=int, default=2, help="最大并发分类数")
    parser.add_argument("--article-sleep", type=parse_sleep, default=(2.0, 5.0), help="单篇文章请求间隔，格式: min,max")
    parser.add_argument("--page-sleep", type=parse_sleep, default=(5.0, 15.0), help="分页请求间隔，格式: min,max")
    parser.add_argument("--stale-stop-count", type=int, default=10, help="连续多少篇早于 since 后停止该分类")
    parser.add_argument("--new-only", action="store_true", help="只抓新增文章，连续遇到已存在文章后停止该分类")
    parser.add_argument("--existing-stop-count", type=int, default=10, help="new-only 模式下连续多少篇已存在后停止")
    parser.add_argument("--max-page-failures", type=int, default=3, help="同一分类连续列表页失败多少次后停止")
    parser.add_argument("--log-file", default="logs/spider.log", help="日志文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只抓取解析，不写入数据库")
    parser.add_argument("--no-migrate", action="store_true", help="不自动创建 MongoDB 索引")
    return parser.parse_args()


def setup_logging(log_file):
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )


def normalize_types(type_names):
    selected = []
    for name in [part.strip() for part in type_names.split(",") if part.strip()]:
        if name not in available_types:
            raise ValueError("未知分类: " + name)
        selected.append(name)
    if not selected:
        raise ValueError("至少需要选择一个分类")
    return selected


def ensure_schema(store):
    store.ensure_schema()


def is_exist(store, info):
    return store.is_exist(info)


def insert(store, info):
    return store.insert(info)


def spider(kind, args, semaphore):
    with semaphore:
        store = None if args.dry_run else MongoNewsStore(config)
        fetcher = Fetcher()
        pn = 1
        stale_count = 0
        existing_count = 0
        inserted = 0
        skipped = 0
        parsed = 0
        page_failures = 0

        try:
            while True:
                if args.max_pages and pn > args.max_pages:
                    logging.info("%s finish: reached max pages %s", kind, args.max_pages)
                    break

                try:
                    page = Page(kind, pn, fetcher=fetcher, article_sleep=args.article_sleep)
                    articles = page.get_articles()
                    page_failures = 0
                except Exception as exc:
                    page_failures += 1
                    logging.exception("page failed kind=%s page=%s error=%s", kind, pn, exc)
                    if page_failures >= args.max_page_failures:
                        logging.error("%s finish: reached max page failures %s", kind, args.max_page_failures)
                        raise RuntimeError(f"{kind} reached max page failures {args.max_page_failures}")
                    time.sleep(random.uniform(*args.page_sleep))
                    continue

                if not articles:
                    logging.info("%s finish: no articles at page %s", kind, pn)
                    break

                for article in articles:
                    info = article.get_info_dict()
                    parsed += 1

                    if info.get("time") < args.since:
                        stale_count += 1
                        if stale_count >= args.stale_stop_count:
                            logging.info("%s finish: %s stale articles since %s", kind, stale_count, args.since)
                            return
                        continue
                    stale_count = 0

                    if args.dry_run:
                        logging.info("dry-run kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                        continue

                    if is_exist(store, info):
                        skipped += 1
                        existing_count += 1
                        logging.info("skip exists kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                        if args.new_only and existing_count >= args.existing_stop_count:
                            logging.info(
                                "%s finish: %s continuous existing articles in new-only mode",
                                kind,
                                existing_count,
                            )
                            return
                        continue

                    if insert(store, info):
                        inserted += 1
                        existing_count = 0
                        logging.info("insert kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))
                    else:
                        skipped += 1
                        existing_count += 1
                        logging.info("skip duplicate kind=%s page=%s seq=%s title=%s", kind, pn, info.get("seq"), info.get("title"))

                logging.info("%s page=%s parsed=%s inserted=%s skipped=%s", kind, pn, parsed, inserted, skipped)
                pn += 1
                time.sleep(random.uniform(*args.page_sleep))
        finally:
            if store:
                store.close()


def main():
    args = parse_args()
    setup_logging(args.log_file)
    selected_types = normalize_types(args.types)

    if not args.dry_run and not args.no_migrate:
        store = MongoNewsStore(config)
        ensure_schema(store)
        store.close()

    semaphore = threading.BoundedSemaphore(max(1, args.threads))
    thread_list = []
    thread_errors = []
    thread_errors_lock = threading.Lock()

    def run_spider(kind):
        try:
            spider(kind, args, semaphore)
        except Exception as exc:
            logging.exception("%s failed: %s", kind, exc)
            with thread_errors_lock:
                thread_errors.append((kind, exc))

    for kind in selected_types:
        thread = threading.Thread(target=run_spider, args=(kind,), name=kind)
        thread_list.append(thread)
        thread.start()

    for thread in thread_list:
        thread.join()

    if thread_errors:
        failed = ", ".join(kind for kind, _ in thread_errors)
        raise SystemExit("spider failed for categories: " + failed)

    logging.info("all done at %s", datetime.datetime.now())


if __name__ == "__main__":
    main()
