from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from .config import get_settings
from .dedupe import DedupeService
from .executor import TaskExecutor, _issue_code
from .models import NewsCrawlRequest
from .migration import migrate_legacy_collection
from .mongo_repository import MongoNewsRepository
from .observer import CompositeRunObserver, LoggingRunObserver
from .pipeline import CrawlPipeline
from .providers.guardian import GuardianProvider
from .providers.bloomberg import BloombergProvider
from .providers.politico import DEFAULT_FEEDS as POLITICO_DEFAULT_FEEDS
from .providers.politico import PoliticoProvider
from .providers.politico_browser import PoliticoBrowserProvider as PoliticoChromeProvider
from .providers.tonghuashun import CATEGORIES, TonghuashunProvider
from .registry import ProviderRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent news collection service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources", help="列出可用新闻源")
    migrate = sub.add_parser("migrate-legacy", help="把旧 articles collection 迁移到 raw_articles")
    migrate.add_argument("--source-collection", default="articles")
    migrate.add_argument("--limit", type=int, default=0)
    crawl = sub.add_parser("crawl", help="抓取新闻")
    crawl.add_argument(
        "--source",
        default="all",
        choices=["all", "tonghuashun", "guardian", "bloomberg", "politico_rss", "politico_browser", "politico_chrome"],
    )
    crawl.add_argument("--latest", action="store_true", help="抓取最新新闻")
    crawl.add_argument("--since", default="", help="历史补采开始时间，ISO 8601")
    crawl.add_argument("--until", default="", help="历史补采结束时间，ISO 8601")
    crawl.add_argument("--max-pages", type=int, default=1)
    crawl.add_argument("--max-articles", type=int, default=0)
    crawl.add_argument("--categories", default="")
    crawl.add_argument("--category-pages", default="", help="按分类覆盖最大页数，例如：产经新闻=3,财经要闻=10")
    crawl.add_argument("--dry-run", action="store_true")
    crawl.add_argument("--request-delay", type=float, default=0)
    crawl.add_argument("--max-runtime-seconds", type=float, default=None, help="单个来源本次采集最大运行秒数，0 表示不限制")
    crawl.add_argument("--stop-after-existing-page", action="store_true", help="最新采集时某页出现已入库文章后停止该分组后续页")
    cancel = sub.add_parser("cancel", help="请求取消一个运行中的采集任务")
    cancel.add_argument("run_id")
    sub.add_parser("health", help="输出来源健康状态")
    runs = sub.add_parser("runs", help="查询采集运行记录")
    runs.add_argument("--source", default="")
    runs.add_argument("--run-id", default="")
    runs.add_argument("--limit", type=int, default=20)
    failures = sub.add_parser("failure-stats", help="统计最近采集失败原因")
    failures.add_argument("--source", default="")
    failures.add_argument("--limit", type=int, default=50)
    schedule = sub.add_parser("schedule", help="常驻循环执行采集任务")
    schedule.add_argument(
        "--source",
        default="all",
        choices=["all", "tonghuashun", "guardian", "bloomberg", "politico_rss", "politico_browser", "politico_chrome"],
    )
    schedule.add_argument("--interval", type=int, default=1800)
    schedule.add_argument("--max-pages", type=int, default=10)
    schedule.add_argument("--category-pages", default="")
    schedule.add_argument("--request-delay", type=float, default=0)
    schedule.add_argument("--max-runtime-seconds", type=float, default=None, help="单个来源本次采集最大运行秒数，0 表示不限制")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    registry = _registry(settings)
    if args.command == "sources":
        print("\n".join(registry.names()))
        return

    if args.command == "migrate-legacy":
        repository = MongoNewsRepository(
            settings.mongodb_uri,
            settings.mongodb_database,
            settings.raw_collection,
            settings.runs_collection,
            settings.cold_index_collection,
        )
        try:
            repository.ensure_indexes()
            print(
                json.dumps(
                    migrate_legacy_collection(repository, args.source_collection, max(0, args.limit)),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            repository.close()
        return

    if args.command in {"cancel", "health", "runs", "failure-stats"}:
        repository = _repository(settings, ensure_indexes=False)
        try:
            if args.command == "cancel":
                print(json.dumps({"run_id": args.run_id, "cancel_requested": repository.request_cancel(args.run_id)}))
            elif args.command == "health":
                rows = list(repository.health.find({}, {"_id": 0}).sort("source_name", 1))
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            elif args.command == "failure-stats":
                print(json.dumps(_failure_stats(repository, args.source, args.limit), ensure_ascii=False, indent=2, default=str))
            elif args.run_id:
                print(json.dumps(repository.get_run(args.run_id) or {}, ensure_ascii=False, indent=2, default=str))
            else:
                query = {"source_name": args.source} if args.source else {}
                rows = list(repository.runs.find(query, {"_id": 0}).sort("started_at", -1).limit(max(1, args.limit)))
                print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        finally:
            repository.close()
        return

    if args.command == "schedule":
        args.dry_run = False
        args.categories = ""
        if not args.category_pages:
            args.category_pages = os.getenv("NEWS_CRAWLER_TONGHUASHUN_CATEGORY_PAGES", "")
        args.max_articles = 0
        args.since = ""
        args.until = ""
        args.stop_after_existing_page = True
        stop = False

        def request_stop(*_args):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        while not stop:
            try:
                _run_crawl(args, get_settings(), fail_on_error=False)
            except Exception:
                logging.exception("scheduled crawl failed")
            deadline = time.monotonic() + max(1, args.interval)
            while not stop and time.monotonic() < deadline:
                time.sleep(min(1, deadline - time.monotonic()))
        return

    _run_crawl(args, settings)


def _run_crawl(args, settings, *, fail_on_error: bool = True):
    repository = None
    if not args.dry_run:
        repository = MongoNewsRepository(
            settings.mongodb_uri,
            settings.mongodb_database,
            settings.raw_collection,
            settings.runs_collection,
            settings.cold_index_collection,
        )
        repository.ensure_indexes()
    try:
        registry = _registry(settings, repository)
        if args.source != "all" and args.source not in registry.names():
            print(json.dumps([], ensure_ascii=False, indent=2))
            return []
        executor = TaskExecutor(repository, repository, DedupeService(), CompositeRunObserver([LoggingRunObserver()]))
        sources = tuple(registry.names()) if args.source == "all" else (args.source,)
        categories = tuple(part.strip() for part in args.categories.split(",") if part.strip()) or None
        category_pages = _parse_category_pages(getattr(args, "category_pages", ""))
        request = NewsCrawlRequest(
            mode="backfill" if args.since or args.until else "latest",
            sources=sources,
            since=_parse_datetime(args.since),
            until=_parse_datetime(args.until),
            categories=categories,
            category_pages=category_pages,
            max_pages=max(1, args.max_pages),
            max_articles=max(0, args.max_articles),
            dry_run=args.dry_run,
            request_delay_seconds=max(0, args.request_delay),
            stop_after_existing_page=bool(getattr(args, "stop_after_existing_page", False)),
            max_runtime_seconds=max(
                0.0,
                settings.max_runtime_seconds
                if getattr(args, "max_runtime_seconds", None) is None
                else args.max_runtime_seconds,
            ),
        )
        results = CrawlPipeline(registry, executor).run(request)
        print(json.dumps([_public_result(item) for item in results], ensure_ascii=False, indent=2))
        if fail_on_error and any(item.status == "failed" for item in results):
            raise SystemExit(1)
        return results
    finally:
        if repository:
            repository.close()


def _registry(settings, checkpoint_repository=None):
    registry = ProviderRegistry()
    paused_sources = _paused_sources(checkpoint_repository)
    disabled_sources = set(settings.disabled_sources) | paused_sources
    if "tonghuashun" not in disabled_sources:
        registry.register("tonghuashun", TonghuashunProvider)
    if settings.guardian_api_key and "guardian" not in disabled_sources:
        registry.register(
            "guardian",
            lambda: GuardianProvider(settings.guardian_api_key, settings.guardian_base_url),
        )
    if "bloomberg" not in disabled_sources:
        registry.register(
            "bloomberg",
            lambda: BloombergProvider(
                settings.bloomberg_latest_url,
                settings.bloomberg_cookie,
                checkpoint_repository,
                api_url=settings.bloomberg_api_url,
                proxy=settings.bloomberg_proxy,
                use_api=settings.bloomberg_use_api,
                cookies_json=settings.bloomberg_cookies_json,
                require_login_cookie=settings.bloomberg_require_login_cookie,
            ),
        )
    if "politico_rss" not in disabled_sources:
        registry.register(
            "politico_rss",
            lambda: PoliticoProvider(
                _parse_politico_feed_urls(settings.politico_feed_urls),
                fetch_article_pages=settings.politico_fetch_article_pages,
                discovery_mode="rss",
                news_url=settings.politico_browser_news_url,
                source_name="politico_rss",
                proxy=settings.politico_browser_proxy,
                cookies_json=settings.politico_browser_cookies_json,
            ),
        )
    if "politico_browser" not in disabled_sources:
        registry.register(
            "politico_browser",
            lambda: PoliticoProvider(
                _parse_politico_feed_urls(settings.politico_feed_urls),
                fetch_article_pages=True,
                discovery_mode="site",
                news_url=settings.politico_browser_news_url,
                source_name="politico_browser",
                proxy=settings.politico_browser_proxy,
                cookies_json=settings.politico_browser_cookies_json,
            ),
        )
    if "politico_chrome" not in disabled_sources:
        registry.register(
            "politico_chrome",
            lambda: PoliticoChromeProvider(
                settings.politico_browser_news_url,
                headless=settings.politico_browser_headless,
                wait_seconds=settings.politico_browser_wait_seconds,
                profile_dir=settings.politico_browser_profile_dir,
                proxy=settings.politico_browser_proxy,
                cookies_json=settings.politico_browser_cookies_json,
                source_name="politico_chrome",
            ),
        )
    return registry


def _paused_sources(repository) -> set[str]:
    if not repository or not hasattr(repository, "active_pauses"):
        return set()
    try:
        return {str(item.get("source_name") or "") for item in repository.active_pauses() if item.get("source_name")}
    except Exception:
        logging.exception("failed to read source pause state")
        return set()


def _repository(settings, *, ensure_indexes: bool = True):
    repository = MongoNewsRepository(
        settings.mongodb_uri,
        settings.mongodb_database,
        settings.raw_collection,
        settings.runs_collection,
        settings.cold_index_collection,
    )
    if ensure_indexes:
        repository.ensure_indexes()
    return repository


def _public_result(result):
    data = asdict(result)
    for key in ("started_at", "finished_at"):
        value = data.get(key)
        data[key] = value.isoformat() if value else None
    return data


def _failure_stats(repository, source_name: str = "", limit: int = 50) -> dict:
    query = {"source_name": source_name} if source_name else {}
    rows = list(
        repository.runs.find(query, {"_id": 0})
        .sort("started_at", -1)
        .limit(max(1, limit))
    )
    code_counts = Counter()
    by_source = defaultdict(Counter)
    message_counts = Counter()
    failed_runs = 0
    failed_articles = 0
    warning_articles = 0
    for row in rows:
        source = row.get("source_name") or "unknown"
        errors = row.get("errors") or []
        warnings = row.get("warnings") or []
        if errors or row.get("failed", 0):
            failed_runs += 1
        failed_articles += int(row.get("failed") or len(errors) or 0)
        warning_articles += len(warnings)
        for issue in errors:
            code = _normalized_issue_code(issue)
            code_counts[code] += 1
            by_source[source][code] += 1
            message = str(issue.get("message") or "").strip()
            if message:
                message_counts[(code, message[:180])] += 1
        for issue in warnings:
            code = "warning:" + _normalized_issue_code(issue)
            code_counts[code] += 1
            by_source[source][code] += 1
            message = str(issue.get("message") or "").strip()
            if message:
                message_counts[(code, message[:180])] += 1
    return {
        "source": source_name or "all",
        "runs_scanned": len(rows),
        "failed_runs": failed_runs,
        "failed_articles": failed_articles,
        "warning_articles": warning_articles,
        "codes": dict(code_counts),
        "by_source": {source: dict(counts) for source, counts in sorted(by_source.items())},
        "top_messages": [
            {"code": code, "message": message, "count": count}
            for (code, message), count in message_counts.most_common(20)
        ],
    }


def _normalized_issue_code(issue: dict) -> str:
    code = str(issue.get("code") or "unknown")
    message = str(issue.get("message") or "")
    if code in {"parser_error", "unknown"} and message:
        return _issue_code(RuntimeError(message))
    return code


def _parse_datetime(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_category_pages(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw_item in str(value or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"分类页数配置格式错误：{item}")
        category, raw_pages = item.split("=", 1)
        category = category.strip()
        if not category:
            raise ValueError(f"分类页数配置缺少分类名：{item}")
        try:
            pages = int(raw_pages.strip())
        except ValueError as exc:
            raise ValueError(f"分类页数必须是整数：{item}") from exc
        result[category] = max(1, pages)
    unknown = sorted(set(result) - set(CATEGORIES))
    if unknown:
        raise ValueError("未知同花顺分类：" + ",".join(unknown))
    return result


def _parse_politico_feed_urls(value: str) -> dict[str, str]:
    result = dict(POLITICO_DEFAULT_FEEDS)
    for raw_item in str(value or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Politico feed 配置格式错误：{item}")
        category, url = item.split("=", 1)
        category = category.strip()
        url = url.strip()
        if not category or not url:
            raise ValueError(f"Politico feed 配置缺少分类或 URL：{item}")
        result[category] = url
    return result


if __name__ == "__main__":
    main()
