#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Backfill existing MongoDB news documents into the shared news.v1 schema."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPIDER_ROOT = PROJECT_ROOT / "spider"
if str(SPIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIDER_ROOT))

from news_schema import normalize_news_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize MongoDB news documents to shared schema.")
    parser.add_argument("--apply", action="store_true", help="write updates to MongoDB; default is dry-run")
    parser.add_argument("--limit", type=int, default=0, help="max documents to inspect; 0 means all")
    parser.add_argument("--show-duplicates", action="store_true", help="print duplicate buckets after normalization")
    args = parser.parse_args()

    _load_env()

    try:
        import pymongo
    except ImportError as exc:
        print(f"missing pymongo: {exc}")
        return 1

    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=8000, socketTimeoutMS=8000)
    try:
        client.admin.command("ping")
        database = os.getenv("MONGODB_DATABASE") or os.getenv("MONGO_DB") or "news"
        collection_name = os.getenv("MONGODB_COLLECTION") or os.getenv("MONGO_COLLECTION") or "articles"
        collection = client[database][collection_name]

        filter_query = {"schema_version": {"$ne": "news.v1"}}
        cursor = collection.find(filter_query)
        if args.limit > 0:
            cursor = cursor.limit(args.limit)

        inspected = 0
        changed = 0
        for row in cursor:
            inspected += 1
            normalized = normalize_news_document(row, publisher_default=row.get("publisher"), source_name=row.get("source_name"))
            normalized.pop("_id", None)
            created_at = normalized.pop("created_at", row.get("created_at", normalized.get("updated_at")))
            if not row.get("created_at") and created_at:
                normalized["created_at"] = created_at
            if args.apply:
                collection.update_one({"_id": row["_id"]}, {"$set": normalized})
            changed += 1

        mode = "applied" if args.apply else "dry-run"
        print(f"{mode}: inspected={inspected} normalized={changed}")

        if args.show_duplicates:
            _print_duplicate_buckets(collection)

        return 0
    finally:
        client.close()


def _load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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


def _print_duplicate_buckets(collection) -> None:
    pipeline = [
        {"$project": {"title": 1, "url": 1, "canonical_url": 1, "content_hash": 1}},
        {
            "$facet": {
                "canonical_url": _duplicate_pipeline("canonical_url"),
                "content_hash": _duplicate_pipeline("content_hash"),
            }
        },
    ]
    result = list(collection.aggregate(pipeline))
    buckets = result[0] if result else {}
    for name, items in buckets.items():
        print(f"duplicate buckets by {name}: {len(items)}")
        for item in items[:10]:
            print(f"  {item['_id']}: {item['count']}")


def _duplicate_pipeline(field: str) -> list[dict]:
    return [
        {"$match": {field: {"$exists": True, "$ne": ""}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]


if __name__ == "__main__":
    raise SystemExit(main())
