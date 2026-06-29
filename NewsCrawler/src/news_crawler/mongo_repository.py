from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .dedupe import DedupeKeys
from .models import CrawlResult, NewsArticle
from .health import HealthProjector


class MongoNewsRepository:
    def __init__(
        self,
        uri: str,
        database: str,
        raw_collection: str,
        runs_collection: str,
        health_collection: str = "source_health",
        checkpoint_collection: str = "crawler_checkpoints",
    ):
        import pymongo

        self.pymongo = pymongo
        self.client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000, socketTimeoutMS=8000)
        self.client.admin.command("ping")
        db = self.client[database]
        self.articles = db[raw_collection]
        self.runs = db[runs_collection]
        self.health = db[health_collection]
        self.checkpoints = db[checkpoint_collection]

    def ensure_indexes(self) -> None:
        asc = self.pymongo.ASCENDING
        desc = self.pymongo.DESCENDING
        self.articles.create_index([("article_id", asc)], unique=True, name="uk_raw_article_id")
        self.articles.create_index([("source_external_key", asc)], unique=True, sparse=True, name="uk_raw_source_external")
        self.articles.create_index([("canonical_url", asc)], unique=True, sparse=True, name="uk_raw_canonical_url")
        self.articles.create_index([("content_hash", asc)], sparse=True, name="idx_raw_content_hash")
        self.articles.create_index([("title_time_hash", asc)], sparse=True, name="idx_raw_title_time_hash")
        self.articles.create_index([("source_name", asc), ("published_at", desc)], name="idx_raw_source_published")
        self.articles.create_index([("published_at", desc)], name="idx_raw_published")
        self.runs.create_index([("run_id", asc)], unique=True, name="uk_crawl_run_id")
        self.runs.create_index([("source_name", asc), ("started_at", desc)], name="idx_crawl_source_started")
        self.health.create_index([("source_name", asc)], unique=True, name="uk_source_health")
        self.checkpoints.create_index([("source_name", asc), ("key", asc)], unique=True, name="uk_crawler_checkpoint")

    def find_existing_by_keys(self, keys: DedupeKeys) -> dict[str, Any] | None:
        clauses = [{key: value} for key, value in keys.query_keys().items()]
        return self.articles.find_one({"$or": clauses}) if clauses else None

    def upsert_article(self, article: NewsArticle, keys: DedupeKeys) -> str:
        document = _article_document(article, keys)
        existing = self.find_existing_by_keys(keys)
        if existing:
            self.articles.update_one(
                {"_id": existing["_id"]},
                {"$set": {**document, "created_at": existing.get("created_at", article.fetched_at)}},
            )
            return "updated"
        document["created_at"] = article.fetched_at
        self.articles.insert_one(document)
        return "inserted"

    def start(self, result: CrawlResult) -> None:
        self.runs.update_one(
            {"run_id": result.run_id},
            {"$set": {**_result_document(result), "cancel_requested": False}},
            upsert=True,
        )

    def finish(self, result: CrawlResult) -> None:
        self.runs.update_one({"run_id": result.run_id}, {"$set": _result_document(result)}, upsert=True)

    def request_cancel(self, run_id: str) -> bool:
        result = self.runs.update_one(
            {"run_id": run_id, "status": {"$in": ["running", "queued"]}},
            {"$set": {"cancel_requested": True}},
        )
        return bool(result.modified_count)

    def is_cancel_requested(self, run_id: str) -> bool:
        row = self.runs.find_one({"run_id": run_id}, {"cancel_requested": 1})
        return bool(row and row.get("cancel_requested"))

    def recent_runs(self, source_name: str, limit: int = 20) -> list[dict[str, Any]]:
        return list(
            self.runs.find({"source_name": source_name}, {"_id": 0})
            .sort("started_at", self.pymongo.DESCENDING)
            .limit(max(1, limit))
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.find_one({"run_id": run_id}, {"_id": 0})

    def update_health(self, source_name: str) -> dict[str, Any]:
        document = HealthProjector().from_documents(source_name, self.recent_runs(source_name))
        self.health.update_one({"source_name": source_name}, {"$set": document}, upsert=True)
        return document

    def save_checkpoint(self, source_name: str, key: str, value: dict[str, Any]) -> None:
        self.checkpoints.update_one(
            {"source_name": source_name, "key": key},
            {"$set": {"value": value, "updated_at": datetime.utcnow().isoformat() + "Z"}},
            upsert=True,
        )

    def load_checkpoint(self, source_name: str, key: str) -> dict[str, Any] | None:
        row = self.checkpoints.find_one({"source_name": source_name, "key": key}, {"_id": 0, "value": 1})
        return dict(row.get("value") or {}) if row else None

    def close(self) -> None:
        self.client.close()


def _article_document(article: NewsArticle, keys: DedupeKeys) -> dict[str, Any]:
    return {
        "schema_version": "news.v1",
        **keys.query_keys(),
        "external_id": article.external_id,
        "source_name": article.source_name,
        "url": article.url,
        "title": article.title,
        "summary": article.summary,
        "content": article.content,
        "published_at": _iso(article.published_at),
        "fetched_at": _iso(article.fetched_at),
        "section": article.section,
        "language": article.language,
        "author": article.author,
        "tags": article.tags,
        "raw_metadata": article.raw_metadata,
        "updated_at": _iso(article.fetched_at),
    }


def _result_document(result: CrawlResult) -> dict[str, Any]:
    data = asdict(result)
    data["started_at"] = _iso(result.started_at)
    data["finished_at"] = _iso(result.finished_at) if result.finished_at else None
    return data


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
