from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Any

from .config import PROJECT_ROOT, load_dotenv


load_dotenv(PROJECT_ROOT / ".env")


def query_news_library(params: dict[str, list[str]]) -> dict[str, Any]:
    try:
        import pymongo
    except ImportError as exc:
        return {"enabled": False, "items": [], "error": f"缺少 pymongo：{exc}"}

    page = _bounded_int(_first(params, "page"), 1, 1, 500)
    page_size = _bounded_int(_first(params, "page_size"), 20, 5, 80)
    query_text = _first(params, "q").strip()
    publisher = _first(params, "publisher").strip()
    kind = _first(params, "type").strip()
    days = _bounded_int(_first(params, "days"), 30, 0, 3650)

    database = os.getenv("MONGODB_DATABASE") or os.getenv("MONGO_DB") or "news"
    collection_name = os.getenv("MONGODB_COLLECTION") or os.getenv("MONGO_COLLECTION") or "articles"
    client = None
    try:
        client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=1800, socketTimeoutMS=2500)
        collection = client[database][collection_name]
        filter_query = _build_filter(query_text=query_text, publisher=publisher, kind=kind, days=days)
        projection = {
            "_id": 0,
            "publisher": 1,
            "type": 1,
            "seq": 1,
            "url": 1,
            "title": 1,
            "summary": 1,
            "content": 1,
            "time": 1,
            "source": 1,
            "created_at": 1,
        }
        total = collection.count_documents(filter_query)
        cursor = (
            collection.find(filter_query, projection)
            .sort([("time", pymongo.DESCENDING), ("created_at", pymongo.DESCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = [_public_news_item(row) for row in cursor]
        publishers = sorted(item for item in collection.distinct("publisher") if item)
        types = sorted(item for item in collection.distinct("type") if item)
        return {
            "enabled": True,
            "database": database,
            "collection": collection_name,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
            "items": items,
            "filters": {"publishers": publishers, "types": types},
            "stats": _stats(collection),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - keep admin page readable
        return {"enabled": False, "items": [], "error": str(exc)}
    finally:
        if client:
            client.close()


def _mongo_uri() -> str:
    if os.getenv("MONGODB_URI"):
        return os.getenv("MONGODB_URI", "")
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    username = os.getenv("MONGO_USER", "")
    password = os.getenv("MONGO_PASSWORD", "")
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if username and password:
        user = urllib.parse.quote_plus(username)
        passwd = urllib.parse.quote_plus(password)
        return f"mongodb://{user}:{passwd}@{host}:{port}/?authSource={auth_source}"
    return f"mongodb://{host}:{port}/"


def _build_filter(query_text: str, publisher: str, kind: str, days: int) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if query_text:
        pattern = re.escape(query_text)
        clauses.append(
            {
                "$or": [
                    {"title": {"$regex": pattern, "$options": "i"}},
                    {"summary": {"$regex": pattern, "$options": "i"}},
                    {"content": {"$regex": pattern, "$options": "i"}},
                    {"source": {"$regex": pattern, "$options": "i"}},
                ]
            }
        )
    if publisher:
        clauses.append({"publisher": publisher})
    if kind:
        clauses.append({"type": kind})
    if days > 0:
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
        clauses.append({"time": {"$gte": cutoff}})
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _stats(collection) -> dict[str, Any]:
    total = collection.estimated_document_count()
    today = time.strftime("%Y-%m-%d 00:00:00", time.localtime())
    today_count = collection.count_documents({"time": {"$gte": today}})
    latest = collection.find_one({}, {"_id": 0, "time": 1}, sort=[("time", -1)])
    by_publisher = list(
        collection.aggregate(
            [
                {"$match": {"publisher": {"$exists": True, "$ne": ""}}},
                {"$group": {"_id": "$publisher", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 8},
            ]
        )
    )
    by_type = list(
        collection.aggregate(
            [
                {"$match": {"type": {"$exists": True, "$ne": ""}}},
                {"$group": {"_id": "$type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 12},
            ]
        )
    )
    return {
        "total": total,
        "today": today_count,
        "latest_time": (latest or {}).get("time", ""),
        "by_publisher": [{"publisher": item.get("_id", ""), "count": item.get("count", 0)} for item in by_publisher],
        "by_type": [{"type": item.get("_id", ""), "count": item.get("count", 0)} for item in by_type],
    }


def _public_news_item(row: dict[str, Any]) -> dict[str, Any]:
    content = str(row.get("content") or "")
    summary = str(row.get("summary") or "")
    excerpt = summary or content
    return {
        "publisher": row.get("publisher", ""),
        "type": row.get("type", ""),
        "seq": row.get("seq", ""),
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "summary": summary,
        "excerpt": _trim(excerpt, 220),
        "content": _trim(content, 3200),
        "time": row.get("time", ""),
        "source": row.get("source", ""),
    }


def _trim(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _first(params: dict[str, list[str]], key: str) -> str:
    return str(params.get(key, [""])[0] or "")


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
