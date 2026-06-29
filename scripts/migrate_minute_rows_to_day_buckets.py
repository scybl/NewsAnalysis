from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.config import PROJECT_ROOT, load_dotenv
from stock_pipeline.minute_storage import build_minute_reference
from stock_pipeline.ths_minute import DEFAULT_COLLECTION, DEFAULT_DB, PYTDX_HISTORY_DATASET, TDX_DATASET, THS_DATASET
from stock_pipeline.ths_minute import _minute_day_buckets, _mongo_uri, _normalize_source
from stock_pipeline.utils import normalize_ts_code, read_json, timestamp, write_json


OLD_ROW_COLLECTION = "tdx_intraday_minutes"
SOURCE_DATASETS = {
    "tdx": TDX_DATASET,
    "pytdx_history": PYTDX_HISTORY_DATASET,
    "10jqka": THS_DATASET,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate flat minute rows into one document per stock/day.")
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--source-collection", default=OLD_ROW_COLLECTION)
    parser.add_argument("--target-collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--source", default="pytdx_history")
    parser.add_argument("--codes", default="", help="Comma-separated stock codes. Empty means discover from source collection.")
    parser.add_argument("--limit-codes", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    source_name = _normalize_source(args.source)
    client = MongoClient(_mongo_uri(args.database), serverSelectionTimeoutMS=8000)
    try:
        source = client[args.database][args.source_collection]
        target = client[args.database][args.target_collection]
        ensure_bucket_indexes(target)
        codes = list(iter_codes(source, source_name, args.codes))
        if args.limit_codes > 0:
            codes = codes[: args.limit_codes]
        moved_days = 0
        moved_rows = 0
        for code in codes:
            days, rows = migrate_code(source, target, code, source_name, skip_existing=args.skip_existing, dry_run=args.dry_run)
            if not args.dry_run and has_bucket_data(target, code, source_name):
                update_local_reference(target, code, source_name)
            moved_days += days
            moved_rows += rows
            print(f"{code}: days={days} rows={rows}")
        action = "would migrate" if args.dry_run else "migrated"
        print(f"{action}: codes={len(codes)} days={moved_days} rows={moved_rows}")
    finally:
        client.close()


def iter_codes(collection: Any, source: str, raw_codes: str) -> Iterable[str]:
    if raw_codes.strip():
        for item in raw_codes.split(","):
            if item.strip():
                yield normalize_ts_code(item)
        return
    for code in collection.distinct("ts_code", {"source": source}):
        if code:
            yield str(code)


def migrate_code(collection: Any, target: Any, ts_code: str, source: str, *, skip_existing: bool, dry_run: bool) -> tuple[int, int]:
    query = {"source": source, "ts_code": normalize_ts_code(ts_code)}
    cursor = collection.find(query, {"_id": 0}).sort([("trade_date", ASCENDING), ("minute", ASCENDING)])
    current_date = ""
    rows: list[dict[str, Any]] = []
    moved_days = 0
    moved_rows = 0
    for row in cursor:
        trade_date = str(row.get("trade_date") or "")
        if current_date and trade_date != current_date:
            days, count = write_day(target, rows, skip_existing=skip_existing, dry_run=dry_run)
            moved_days += days
            moved_rows += count
            rows = []
        current_date = trade_date
        rows.append(row)
    days, count = write_day(target, rows, skip_existing=skip_existing, dry_run=dry_run)
    return moved_days + days, moved_rows + count


def write_day(target: Any, rows: list[dict[str, Any]], *, skip_existing: bool, dry_run: bool) -> tuple[int, int]:
    buckets = _minute_day_buckets(rows)
    if not buckets:
        return 0, 0
    bucket = buckets[0]
    query = {"source": bucket["source"], "ts_code": bucket["ts_code"], "trade_date": bucket["trade_date"]}
    if skip_existing and target.find_one(query, {"_id": 1}):
        return 0, 0
    if not dry_run:
        target.update_one(query, {"$set": bucket}, upsert=True)
    return 1, int(bucket.get("row_count") or 0)


def ensure_bucket_indexes(collection: Any) -> None:
    collection.create_index([("source", ASCENDING), ("ts_code", ASCENDING), ("trade_date", ASCENDING)], unique=True)
    collection.create_index([("ts_code", ASCENDING), ("source", ASCENDING), ("trade_date", ASCENDING)])


def update_local_reference(collection: Any, ts_code: str, source: str) -> None:
    dataset = SOURCE_DATASETS.get(source)
    if not dataset:
        return
    stock_dir = PROJECT_ROOT / "local_data" / normalize_ts_code(ts_code)
    full_path = stock_dir / "current" / "full_data.json"
    if not full_path.exists():
        return
    full_data = read_json(full_path)
    reference = build_minute_reference(collection, ts_code, dataset=dataset, source=source)
    full_data.setdefault("external_datasets", {})[dataset] = reference
    write_json(full_path, full_data)

    metadata_path = stock_dir / "metadata.json"
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        metadata.setdefault("dataset_rows", {})[dataset] = reference["row_count"]
        metadata["market_minute_updated_at"] = timestamp()
        write_json(metadata_path, metadata)


def has_bucket_data(collection: Any, ts_code: str, source: str) -> bool:
    return bool(collection.find_one({"source": source, "ts_code": normalize_ts_code(ts_code)}, {"_id": 1}))


if __name__ == "__main__":
    main()
