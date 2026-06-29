from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pymongo import MongoClient

from stock_pipeline.market_dimensions import (
    LEGACY_STOCK_COLLECTIONS,
    LEGACY_STOCK_MARKET_DATABASE,
    MARKET_COLLECTIONS,
    MARKET_DATABASE,
    STOCK_COLLECTIONS,
    STOCK_DATABASE,
)
from stock_pipeline.ths_minute import _mongo_uri


RENAMES = [
    (LEGACY_STOCK_MARKET_DATABASE, LEGACY_STOCK_COLLECTIONS["packages"], STOCK_DATABASE, STOCK_COLLECTIONS["packages"]),
    (LEGACY_STOCK_MARKET_DATABASE, LEGACY_STOCK_COLLECTIONS["metadata"], STOCK_DATABASE, STOCK_COLLECTIONS["metadata"]),
    (LEGACY_STOCK_MARKET_DATABASE, LEGACY_STOCK_COLLECTIONS["rows"], STOCK_DATABASE, STOCK_COLLECTIONS["rows"]),
    (LEGACY_STOCK_MARKET_DATABASE, LEGACY_STOCK_COLLECTIONS["files"], STOCK_DATABASE, STOCK_COLLECTIONS["files"]),
    (LEGACY_STOCK_MARKET_DATABASE, "minute_day_buckets", MARKET_DATABASE, MARKET_COLLECTIONS["minute_buckets"]),
    (LEGACY_STOCK_MARKET_DATABASE, "market_minute_payloads", MARKET_DATABASE, MARKET_COLLECTIONS["minute_payloads"]),
    (LEGACY_STOCK_MARKET_DATABASE, "kaipanla_results", MARKET_DATABASE, MARKET_COLLECTIONS["kaipanla_results"]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reallocate MongoDB collections into stock, market, and news dimensions.")
    parser.add_argument("--apply", action="store_true", help="Actually rename collections. Without this, only report the plan.")
    parser.add_argument("--drop-empty-legacy-db", action="store_true", help="Drop old stock_market database if it is empty after migration.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = MongoClient(
        _mongo_uri(LEGACY_STOCK_MARKET_DATABASE),
        serverSelectionTimeoutMS=8000,
        socketTimeoutMS=300000,
    )
    try:
        result: dict[str, Any] = {"ok": True, "applied": args.apply, "renames": [], "post_updates": {}}
        for source_db, source_collection, target_db, target_collection in RENAMES:
            item = _rename_collection(client, source_db, source_collection, target_db, target_collection, apply=args.apply)
            result["renames"].append(item)
        if args.apply:
            result["post_updates"] = _repair_document_references(client)
            if args.drop_empty_legacy_db:
                remaining = client[LEGACY_STOCK_MARKET_DATABASE].list_collection_names()
                if not remaining:
                    client.drop_database(LEGACY_STOCK_MARKET_DATABASE)
                    result["dropped_legacy_database"] = LEGACY_STOCK_MARKET_DATABASE
                else:
                    result["legacy_remaining_collections"] = remaining
        result["counts"] = _counts(client)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1
    finally:
        client.close()


def _rename_collection(
    client: MongoClient,
    source_db: str,
    source_collection: str,
    target_db: str,
    target_collection: str,
    *,
    apply: bool,
) -> dict[str, Any]:
    source_ns = f"{source_db}.{source_collection}"
    target_ns = f"{target_db}.{target_collection}"
    source_exists = source_collection in client[source_db].list_collection_names()
    target_exists = target_collection in client[target_db].list_collection_names()
    source_count = client[source_db][source_collection].estimated_document_count() if source_exists else 0
    target_count = client[target_db][target_collection].estimated_document_count() if target_exists else 0
    item = {
        "from": source_ns,
        "to": target_ns,
        "source_exists": source_exists,
        "target_exists": target_exists,
        "source_count": source_count,
        "target_count": target_count,
        "action": "skip",
    }
    if not source_exists:
        item["reason"] = "source_missing"
        return item
    if target_exists and target_count > 0:
        item["reason"] = "target_exists"
        return item
    item["action"] = "rename"
    if apply:
        client.admin.command("renameCollection", source_ns, to=target_ns, dropTarget=True)
    return item


def _repair_document_references(client: MongoClient) -> dict[str, int]:
    packages = client[STOCK_DATABASE][STOCK_COLLECTIONS["packages"]]
    metadata = client[STOCK_DATABASE][STOCK_COLLECTIONS["metadata"]]
    kaipanla = client[MARKET_DATABASE][MARKET_COLLECTIONS["kaipanla_results"]]
    package_updates = 0
    for doc in packages.find({}, {"_id": 1, "ts_code": 1, "snapshot": 1, "full_data": 1}):
        ts_code = str(doc.get("ts_code") or "")
        snapshot = str(doc.get("snapshot") or "current")
        full_data = doc.get("full_data") if isinstance(doc.get("full_data"), dict) else {}
        _repair_external_dataset_refs(full_data)
        packages.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "path": f"mongodb://{STOCK_DATABASE}/{STOCK_COLLECTIONS['packages']}/{ts_code}/{snapshot}",
                    "full_data": full_data,
                }
            },
        )
        package_updates += 1
    metadata_updates = 0
    for doc in metadata.find({}, {"_id": 1, "ts_code": 1, "metadata": 1}):
        ts_code = str(doc.get("ts_code") or "")
        body = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        body["current_dir"] = f"mongodb://{STOCK_DATABASE}/{STOCK_COLLECTIONS['packages']}/{ts_code}/current"
        metadata.update_one(
            {"_id": doc["_id"]},
            {"$set": {"path": f"mongodb://{STOCK_DATABASE}/{STOCK_COLLECTIONS['metadata']}/{ts_code}", "metadata": body}},
        )
        metadata_updates += 1
    kaipanla_updates = kaipanla.update_many(
        {"path": {"$regex": r"^mongodb://stock_market/kaipanla_results/"}},
        [{"$set": {"path": {"$replaceOne": {"input": "$path", "find": "mongodb://stock_market/kaipanla_results/", "replacement": f"mongodb://{MARKET_DATABASE}/{MARKET_COLLECTIONS['kaipanla_results']}/"}}}}],
    ).modified_count
    return {"stock_packages": package_updates, "stock_metadata": metadata_updates, "kaipanla_paths": kaipanla_updates}


def _repair_external_dataset_refs(full_data: dict[str, Any]) -> None:
    refs = full_data.get("external_datasets")
    if not isinstance(refs, dict):
        return
    for value in refs.values():
        if not isinstance(value, dict):
            continue
        if value.get("storage") == "mongodb_day_buckets":
            value["database"] = MARKET_DATABASE
            value["collection"] = MARKET_COLLECTIONS["minute_buckets"]


def _counts(client: MongoClient) -> dict[str, dict[str, int]]:
    payload: dict[str, dict[str, int]] = {}
    for database, collections in {
        STOCK_DATABASE: STOCK_COLLECTIONS,
        MARKET_DATABASE: MARKET_COLLECTIONS,
        LEGACY_STOCK_MARKET_DATABASE: {
            **LEGACY_STOCK_COLLECTIONS,
            "minute_buckets": "minute_day_buckets",
            "minute_payloads": "market_minute_payloads",
            "kaipanla_results": "kaipanla_results",
        },
    }.items():
        payload[database] = {}
        existing = set(client[database].list_collection_names())
        for name in collections.values():
            payload[database][name] = client[database][name].estimated_document_count() if name in existing else 0
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
