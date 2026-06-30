from __future__ import annotations

import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from .secret_store import secret_value


SUPPORTED_SCHEMA_MAJOR = "news.v1"


@dataclass(frozen=True)
class RawNewsConfig:
    uri: str
    database: str
    collection: str
    ingestion_collection: str = "analysis_ingestion_state"


class MongoRawNewsRepository:
    """Read-only boundary for NewsCrawler-owned raw articles."""

    def __init__(self, config: RawNewsConfig | None = None, *, timeout_ms: int = 1800):
        import pymongo

        self.pymongo = pymongo
        self.config = config or raw_news_config()
        self.client = pymongo.MongoClient(
            self.config.uri,
            serverSelectionTimeoutMS=timeout_ms,
            socketTimeoutMS=max(timeout_ms, 2500),
        )
        self.collection = self.client[self.config.database][self.config.collection]

    def close(self) -> None:
        self.client.close()

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        rows, _ = self.search(keywords=[], limit=limit)
        return rows

    def get_by_article_id(self, article_id: str) -> dict[str, Any] | None:
        row = self.collection.find_one({"article_id": article_id}, {"_id": 0})
        return self._validate(row) if row else None

    def set_translation(self, article_id: str, language: str, translation: dict[str, Any]) -> None:
        self.collection.update_one(
            {"article_id": article_id},
            {"$set": {f"translations.{language}": translation}},
        )

    def list_unprocessed(self, consumer: str, limit: int = 100) -> list[dict[str, Any]]:
        state = self.client[self.config.database][self.config.ingestion_collection]
        processed = [
            row["article_id"]
            for row in state.find({"consumer": consumer}, {"_id": 0, "article_id": 1}).limit(10000)
            if row.get("article_id")
        ]
        query = {"schema_version": {"$regex": r"^news\.v1(?:$|\.)"}}
        if processed:
            query["article_id"] = {"$nin": processed}
        rows = self.collection.find(query, {"_id": 0}).sort("published_at", self.pymongo.ASCENDING).limit(max(1, limit))
        return [self._validate(row) for row in rows]

    def mark_processed(self, consumer: str, article_id: str, metadata: dict[str, Any] | None = None) -> None:
        state = self.client[self.config.database][self.config.ingestion_collection]
        state.update_one(
            {"consumer": consumer, "article_id": article_id},
            {"$set": {"consumer": consumer, "article_id": article_id, "processed_at": time.time(), "metadata": metadata or {}}},
            upsert=True,
        )

    def search(
        self,
        *,
        keywords: list[str],
        start_date: str = "",
        end_date: str = "",
        limit: int = 20,
        source_name: str = "",
        section: str = "",
        skip: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        query = self._query(keywords, start_date, end_date, source_name, section)
        projection = {
            "_id": 0,
            "schema_version": 1,
            "article_id": 1,
            "source_name": 1,
            "external_id": 1,
            "url": 1,
            "title": 1,
            "summary": 1,
            "content": 1,
            "published_at": 1,
            "section": 1,
            "author": 1,
        }
        total = self.collection.count_documents(query)
        cursor = (
            self.collection.find(query, projection)
            .sort("published_at", self.pymongo.DESCENDING)
            .skip(max(0, skip))
            .limit(max(1, min(200, limit)))
        )
        return [self._validate(row) for row in cursor], total

    def page(
        self,
        *,
        query_text: str = "",
        source_name: str = "",
        section: str = "",
        days: int = 30,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        start_date = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400)) if days > 0 else ""
        items, total = self.search(
            keywords=[item for item in query_text.split() if item],
            start_date=start_date,
            limit=page_size,
            skip=(page - 1) * page_size,
            source_name=source_name,
            section=section,
        )
        return {
            "database": self.config.database,
            "collection": self.config.collection,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
            "items": items,
            "filters": {
                "publishers": sorted(item for item in self.collection.distinct("source_name") if item),
                "types": sorted(item for item in self.collection.distinct("section") if item),
            },
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        total = self.collection.estimated_document_count()
        today = time.strftime("%Y-%m-%d", time.localtime())
        latest = self.collection.find_one({}, {"_id": 0, "published_at": 1}, sort=[("published_at", -1)])
        return {
            "total": total,
            "today": self.collection.count_documents({"published_at": {"$gte": today}}),
            "latest_time": (latest or {}).get("published_at", ""),
            "by_publisher": self._group_counts("source_name", "publisher"),
            "by_type": self._group_counts("section", "type"),
        }

    def _query(self, keywords, start_date, end_date, source_name, section):
        clauses: list[dict[str, Any]] = [{"schema_version": {"$regex": r"^news\.v1(?:$|\.)"}}]
        if keywords:
            pattern = "|".join(re.escape(item) for item in keywords[:24])
            clauses.append({"$or": [{field: {"$regex": pattern, "$options": "i"}} for field in ("title", "summary", "content")]})
        if source_name:
            clauses.append({"source_name": source_name})
        if section:
            clauses.append({"section": section})
        time_range = {}
        if start_date:
            time_range["$gte"] = f"{start_date[:10]}T00:00:00"
        if end_date:
            time_range["$lte"] = f"{end_date[:10]}T23:59:59Z"
        if time_range:
            clauses.append({"published_at": time_range})
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def _validate(self, row):
        version = str(row.get("schema_version") or "")
        if version != SUPPORTED_SCHEMA_MAJOR and not version.startswith(SUPPORTED_SCHEMA_MAJOR + "."):
            raise ValueError(f"不支持的新闻文档版本：{version or 'missing'}")
        return row

    def _group_counts(self, field: str, output_key: str) -> list[dict[str, Any]]:
        rows = self.collection.aggregate(
            [
                {"$match": {field: {"$exists": True, "$ne": ""}}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 12},
            ]
        )
        return [{output_key: item.get("_id", ""), "count": item.get("count", 0)} for item in rows]


def raw_news_config() -> RawNewsConfig:
    return RawNewsConfig(
        uri=_mongo_uri(),
        database=os.getenv("MONGODB_DATABASE", "news"),
        collection=os.getenv("MONGODB_RAW_COLLECTION", "raw_articles"),
        ingestion_collection=os.getenv("MONGODB_ANALYSIS_INGESTION_COLLECTION", "analysis_ingestion_state"),
    )


def _mongo_uri() -> str:
    direct = secret_value("mongo.uri", ("MONGODB_URI", "MONGO_URI"))
    if direct:
        return direct
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    username = secret_value("mongo.user", ("MONGO_USER",))
    password = secret_value("mongo.password", ("MONGO_PASSWORD",))
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if username and password:
        return (
            f"mongodb://{urllib.parse.quote_plus(username)}:"
            f"{urllib.parse.quote_plus(password)}@{host}:{port}/?authSource={auth_source}"
        )
    return f"mongodb://{host}:{port}/"
