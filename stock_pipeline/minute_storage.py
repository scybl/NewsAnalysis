from __future__ import annotations

import os
import urllib.parse
from typing import Any

from .config import load_dotenv
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from .minute_cold_storage import latest_indexed_days, read_cached_or_downloaded_day
from .secret_store import secret_value
from .utils import normalize_ts_code


DEFAULT_DATABASE = MARKET_DATABASE
DEFAULT_COLLECTION = MARKET_COLLECTIONS["minute_buckets"]
DEFAULT_DAY_INDEX_COLLECTION = MARKET_COLLECTIONS["minute_day_index"]
DEFAULT_COVERAGE_COLLECTION = MARKET_COLLECTIONS["minute_coverage"]
MINUTE_DATASET_SOURCES = {
    "tdx_intraday_minutes": "tdx",
    "pytdx_history_minutes": "pytdx_history",
    "ths_intraday_minutes": "10jqka",
}


def build_minute_reference(
    collection: Any,
    ts_code: str,
    *,
    dataset: str,
    source: str,
) -> dict[str, Any]:
    query = {"ts_code": normalize_ts_code(ts_code), "source": source}
    row_count = _bucket_row_count(collection, query)
    first = collection.find_one(query, {"_id": 0, "trade_date": 1, "start_minute": 1}, sort=[("trade_date", 1)]) or {}
    last = collection.find_one(query, {"_id": 0, "trade_date": 1, "end_minute": 1}, sort=[("trade_date", -1)]) or {}
    cold = _coverage_snapshot(collection.database[DEFAULT_COVERAGE_COLLECTION], query)
    return {
        "storage": "mongodb_day_buckets",
        "cold_storage": "baidu_netdisk_day_objects",
        "database": collection.database.name,
        "collection": collection.name,
        "day_index_collection": DEFAULT_DAY_INDEX_COLLECTION,
        "dataset": dataset,
        "source": source,
        "ts_code": normalize_ts_code(ts_code),
        "row_count": row_count or int(cold.get("archived_rows") or 0),
        "hot_row_count": row_count,
        "archived_row_count": int(cold.get("archived_rows") or 0),
        "archived_days": int(cold.get("archived_days") or 0),
        "hot_days": int(cold.get("hot_days") or 15),
        "cache_max_bytes": int(cold.get("cache_max_bytes") or 10 * 1024 * 1024 * 1024),
        "start_date": str(first.get("trade_date") or cold.get("first_trade_date") or ""),
        "end_date": str(last.get("trade_date") or cold.get("last_trade_date") or ""),
        "start_minute": str(first.get("start_minute") or ""),
        "end_minute": str(last.get("end_minute") or ""),
    }


def read_minute_rows(reference: dict[str, Any], limit: int = 80) -> list[dict[str, Any]]:
    if not reference or reference.get("storage") != "mongodb_day_buckets":
        return []
    try:
        import pymongo
    except ImportError:
        return []

    database = str(reference.get("database") or DEFAULT_DATABASE)
    collection_name = str(reference.get("collection") or DEFAULT_COLLECTION)
    query = {
        "ts_code": normalize_ts_code(str(reference.get("ts_code") or "")),
        "source": str(reference.get("source") or ""),
    }
    client = pymongo.MongoClient(_mongo_uri(database), serverSelectionTimeoutMS=2000, socketTimeoutMS=3000)
    try:
        rows = _read_bucket_minute_rows(client[database][collection_name], query, limit)
        if rows:
            return rows
        return _read_cold_minute_rows(client[database][str(reference.get("day_index_collection") or DEFAULT_DAY_INDEX_COLLECTION)], query, limit)
    except Exception:  # MongoDB downtime must not block daily-data reads or analysis.
        return []
    finally:
        client.close()


def _read_bucket_minute_rows(collection: Any, query: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    target = max(1, min(int(limit), 10000))
    rows: list[dict[str, Any]] = []
    # A trading day usually has about 240 minute rows. Read enough day buckets
    # to satisfy the requested row limit without scanning a stock's full history.
    day_limit = max(1, min((target // 200) + 2, 60))
    buckets = collection.find(query, {"_id": 0}).sort([("trade_date", -1)]).limit(day_limit)
    for bucket in buckets:
        base = {
            "source": bucket.get("source", ""),
            "dataset": bucket.get("dataset", ""),
            "ts_code": bucket.get("ts_code", ""),
            "symbol": bucket.get("symbol", ""),
            "trade_date": bucket.get("trade_date", ""),
        }
        for item in reversed(bucket.get("minutes") or []):
            if isinstance(item, dict):
                rows.append({**base, **item})
                if len(rows) >= target:
                    rows.reverse()
                    return rows
    rows.reverse()
    return rows


def _read_cold_minute_rows(day_index: Any, query: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    target = max(1, min(int(limit), 10000))
    day_limit = max(1, min((target // 200) + 2, 60))
    rows: list[dict[str, Any]] = []
    for day in latest_indexed_days(day_index, ts_code=query["ts_code"], source=query["source"], limit=day_limit):
        day_rows = read_cached_or_downloaded_day(
            day_index,
            ts_code=query["ts_code"],
            trade_date=str(day.get("trade_date") or ""),
            source=query["source"],
        )
        for item in reversed(day_rows):
            rows.append(item)
            if len(rows) >= target:
                rows.reverse()
                return rows
    rows.reverse()
    return rows


def read_external_minute_datasets(full_data: dict[str, Any], limit: int = 80) -> dict[str, list[dict[str, Any]]]:
    references = full_data.get("external_datasets") or {}
    result: dict[str, list[dict[str, Any]]] = {}
    for dataset in MINUTE_DATASET_SOURCES:
        reference = references.get(dataset)
        if isinstance(reference, dict):
            result[dataset] = read_minute_rows(reference, limit=limit)
    return result


def minute_reference_row_counts(full_data: dict[str, Any]) -> dict[str, int]:
    references = full_data.get("external_datasets") or {}
    return {
        dataset: int(reference.get("row_count") or 0)
        for dataset, reference in references.items()
        if dataset in MINUTE_DATASET_SOURCES and isinstance(reference, dict)
    }


def _bucket_row_count(collection: Any, query: dict[str, Any]) -> int:
    result = list(
        collection.aggregate(
            [
                {"$match": query},
                {"$group": {"_id": None, "rows": {"$sum": "$row_count"}}},
            ]
        )
    )
    return int((result[0] if result else {}).get("rows") or 0)


def _coverage_snapshot(collection: Any, query: dict[str, Any]) -> dict[str, Any]:
    try:
        return collection.find_one(query, {"_id": 0}) or {}
    except Exception:
        return {}


def _mongo_uri(database: str) -> str:
    load_dotenv()
    direct_uri = secret_value("mongo.uri", ("MONGODB_URI", "MONGO_URI"))
    if direct_uri:
        return direct_uri
    host = os.getenv("MONGO_HOST", "127.0.0.1")
    port = int(os.getenv("MONGO_PORT", "27017"))
    user = secret_value("mongo.user", ("MONGO_USER",))
    password = secret_value("mongo.password", ("MONGO_PASSWORD",))
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if user and password:
        encoded_user = urllib.parse.quote_plus(user)
        encoded_password = urllib.parse.quote_plus(password)
        return f"mongodb://{encoded_user}:{encoded_password}@{host}:{port}/{database}?authSource={auth_source}"
    return f"mongodb://{host}:{port}/{database}"
