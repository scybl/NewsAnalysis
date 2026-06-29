from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

from .config import PROJECT_ROOT
from .crawler_monitor import _issue_category
from .raw_news import raw_news_config


ARCHIVE_COLLECTION = "failed_article_archive"


def retry_failed_article(payload: dict[str, Any], *, actor: str = "admin") -> dict[str, Any]:
    source_name = str(payload.get("source_name") or "").strip()
    article_url = str(payload.get("article_url") or "").strip()
    section = str(payload.get("section") or "").strip()
    code = str(payload.get("code") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not article_url:
        raise ValueError("缺少失败新闻链接。")
    if source_name != "tonghuashun":
        raise ValueError("当前仅支持同花顺失败新闻单条重抓。")

    _ensure_news_crawler_path()
    from news_crawler.dedupe import DedupeService
    from news_crawler.models import ArticleRef
    from news_crawler.mongo_repository import MongoNewsRepository
    from news_crawler.providers.tonghuashun import TonghuashunProvider

    config = raw_news_config()
    repository = MongoNewsRepository(config.uri, config.database, config.collection, os.getenv("MONGODB_RUNS_COLLECTION", "crawl_runs"))
    archive = repository.client[config.database][ARCHIVE_COLLECTION]
    _ensure_archive_indexes(repository.pymongo, archive)
    existing_archive = archive.find_one({"article_url": article_url, "status": "archived"}, {"_id": 0})
    if existing_archive:
        return {"status": "archived", "article_url": article_url, "archived": True, "error": existing_archive.get("last_error", "")}
    try:
        provider = TonghuashunProvider()
        article = provider.fetch(ArticleRef(source_name, article_url, section=section))
        keys = DedupeService().keys_for(article)
        repository.ensure_indexes()
        outcome = repository.upsert_article(article, keys)
        archive.update_one(
            {"article_url": article_url},
            {
                "$set": {
                    "article_url": article_url,
                    "source_name": source_name,
                    "status": "recovered",
                    "recovered_at": _now(),
                    "recovered_by": actor,
                    "article_id": keys.article_id,
                    "last_outcome": outcome,
                },
                "$inc": {"attempts": 1},
                "$setOnInsert": {"created_at": _now(), "code": code, "message": message},
            },
            upsert=True,
        )
        return {"status": "recovered", "article_url": article_url, "outcome": outcome, "article_id": keys.article_id}
    except Exception as exc:  # noqa: BLE001 - admin action must archive after the one retry
        error = str(exc)
        archive.update_one(
            {"article_url": article_url},
            {
                "$set": {
                    "article_url": article_url,
                    "source_name": source_name,
                    "status": "archived",
                    "archived_at": _now(),
                    "archived_by": actor,
                    "code": _issue_category(code, error or message),
                    "message": message,
                    "last_error": error,
                },
                "$inc": {"attempts": 1},
                "$setOnInsert": {"created_at": _now()},
            },
            upsert=True,
        )
        return {"status": "archived", "article_url": article_url, "archived": True, "error": error}
    finally:
        repository.close()


def retry_failure_group(payload: dict[str, Any], *, actor: str = "admin", max_urls: int = 20) -> dict[str, Any]:
    urls = [str(item or "").strip() for item in payload.get("sample_urls") or [] if str(item or "").strip()]
    if not urls and payload.get("article_url"):
        urls = [str(payload.get("article_url") or "").strip()]
    if not urls:
        raise ValueError("这个失败分组没有可重抓链接。")
    results = []
    for url in urls[:max(1, min(50, max_urls))]:
        item_payload = {**payload, "article_url": url}
        results.append(retry_failed_article(item_payload, actor=actor))
    recovered = sum(item.get("status") == "recovered" for item in results)
    archived = sum(item.get("status") == "archived" for item in results)
    return {"retried": len(results), "recovered": recovered, "archived": archived, "items": results}


def _ensure_news_crawler_path() -> None:
    path = PROJECT_ROOT / "NewsCrawler" / "src"
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _ensure_archive_indexes(pymongo, collection) -> None:
    collection.create_index([("article_url", pymongo.ASCENDING)], unique=True, name="uk_failed_article_url")
    collection.create_index([("status", pymongo.ASCENDING), ("archived_at", pymongo.DESCENDING)], name="idx_failed_archive_status")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
