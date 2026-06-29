from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.config import PROJECT_ROOT, load_dotenv
from stock_pipeline.ths_minute import DEFAULT_COLLECTION, DEFAULT_DB, _mongo_uri, _normalize_source
from stock_pipeline.utils import normalize_ts_code, read_json


OLD_ROW_COLLECTION = "tdx_intraday_minutes"


@dataclass
class CodeSummary:
    ts_code: str
    old_days: int
    new_days: int
    old_rows: int
    new_rows: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify flat minute rows were migrated to day buckets, then optionally delete the old flat data."
    )
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--source-collection", default=OLD_ROW_COLLECTION)
    parser.add_argument("--target-collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--source", default="pytdx_history")
    parser.add_argument("--codes", default="", help="Comma-separated stock codes. Empty means all codes in the source collection.")
    parser.add_argument("--limit-codes", type=int, default=0)
    parser.add_argument("--check-local-refs", action="store_true", help="Also require local full_data.json minute refs to point at day buckets.")
    parser.add_argument("--delete-source", action="store_true", help="Delete old flat minute data only after verification passes.")
    parser.add_argument("--yes", action="store_true", help="Required together with --delete-source.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    source_name = _normalize_source(args.source)
    client = MongoClient(_mongo_uri(args.database), serverSelectionTimeoutMS=8000)
    try:
        old_collection = client[args.database][args.source_collection]
        bucket_collection = client[args.database][args.target_collection]
        codes = list(iter_codes(old_collection, source_name, args.codes))
        if args.limit_codes > 0:
            codes = codes[: args.limit_codes]
        if not codes:
            raise SystemExit(f"no source codes found in {args.database}.{args.source_collection} for source={source_name}")

        summaries, errors = verify_codes(old_collection, bucket_collection, codes, source_name)
        if args.check_local_refs:
            errors.extend(check_local_refs(codes, args.target_collection))

        old_rows = sum(item.old_rows for item in summaries)
        new_rows = sum(item.new_rows for item in summaries)
        old_days = sum(item.old_days for item in summaries)
        new_days = sum(item.new_days for item in summaries)
        print(f"checked: codes={len(codes)} old_days={old_days} new_days={new_days} old_rows={old_rows} new_rows={new_rows}")

        if errors:
            print(f"verification failed: errors={len(errors)}")
            for error in errors[:50]:
                print(f"- {error}")
            if len(errors) > 50:
                print(f"- ... {len(errors) - 50} more")
            raise SystemExit(1)

        print("verification passed")
        if args.delete_source:
            if not args.yes:
                raise SystemExit("refusing to delete old data without --yes")
            delete_old_data(old_collection, source_name)
    finally:
        client.close()


def iter_codes(collection: Any, source: str, raw_codes: str) -> list[str]:
    if raw_codes.strip():
        return [normalize_ts_code(item) for item in raw_codes.split(",") if item.strip()]
    return sorted(str(code) for code in collection.distinct("ts_code", {"source": source}) if code)


def verify_codes(old_collection: Any, bucket_collection: Any, codes: list[str], source: str) -> tuple[list[CodeSummary], list[str]]:
    summaries: list[CodeSummary] = []
    errors: list[str] = []
    for index, ts_code in enumerate(codes, start=1):
        old_days = old_day_stats(old_collection, ts_code, source)
        new_days = new_day_stats(bucket_collection, ts_code, source)
        summary = CodeSummary(
            ts_code=ts_code,
            old_days=len(old_days),
            new_days=len(new_days),
            old_rows=sum(item["row_count"] for item in old_days.values()),
            new_rows=sum(item["row_count"] for item in new_days.values()),
        )
        summaries.append(summary)
        errors.extend(compare_day_stats(ts_code, old_days, new_days))
        print(
            f"{index}/{len(codes)} {ts_code}: "
            f"old_days={summary.old_days} new_days={summary.new_days} "
            f"old_rows={summary.old_rows} new_rows={summary.new_rows}"
        )
    return summaries, errors


def old_day_stats(collection: Any, ts_code: str, source: str) -> dict[str, dict[str, Any]]:
    cursor = collection.aggregate(
        [
            {"$match": {"source": source, "ts_code": normalize_ts_code(ts_code)}},
            {
                "$group": {
                    "_id": "$trade_date",
                    "row_count": {"$sum": 1},
                    "start_minute": {"$min": "$minute"},
                    "end_minute": {"$max": "$minute"},
                }
            },
            {"$sort": {"_id": ASCENDING}},
        ],
        allowDiskUse=True,
    )
    return {
        str(item["_id"]): {
            "row_count": int(item.get("row_count") or 0),
            "start_minute": str(item.get("start_minute") or ""),
            "end_minute": str(item.get("end_minute") or ""),
        }
        for item in cursor
    }


def new_day_stats(collection: Any, ts_code: str, source: str) -> dict[str, dict[str, Any]]:
    cursor = collection.find(
        {"source": source, "ts_code": normalize_ts_code(ts_code)},
        {"_id": 0, "trade_date": 1, "row_count": 1, "start_minute": 1, "end_minute": 1},
    )
    return {
        str(item.get("trade_date") or ""): {
            "row_count": int(item.get("row_count") or 0),
            "start_minute": str(item.get("start_minute") or ""),
            "end_minute": str(item.get("end_minute") or ""),
        }
        for item in cursor
        if item.get("trade_date")
    }


def compare_day_stats(ts_code: str, old_days: dict[str, dict[str, Any]], new_days: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    old_dates = set(old_days)
    new_dates = set(new_days)
    missing = sorted(old_dates - new_dates)
    extra = sorted(new_dates - old_dates)
    if missing:
        errors.append(f"{ts_code}: missing bucket days {missing[:10]} count={len(missing)}")
    if extra:
        errors.append(f"{ts_code}: extra bucket days {extra[:10]} count={len(extra)}")
    for trade_date in sorted(old_dates & new_dates):
        old = old_days[trade_date]
        new = new_days[trade_date]
        for key in ("row_count", "start_minute", "end_minute"):
            if old[key] != new[key]:
                errors.append(f"{ts_code} {trade_date}: {key} old={old[key]!r} new={new[key]!r}")
                break
    return errors


def check_local_refs(codes: list[str], target_collection: str) -> list[str]:
    errors: list[str] = []
    for ts_code in codes:
        full_path = PROJECT_ROOT / "local_data" / normalize_ts_code(ts_code) / "current" / "full_data.json"
        if not full_path.exists():
            continue
        full_data = read_json(full_path)
        refs = full_data.get("external_datasets") or {}
        reference = refs.get("pytdx_history_minutes")
        if not reference:
            continue
        if reference.get("storage") != "mongodb_day_buckets" or reference.get("collection") != target_collection:
            errors.append(f"{ts_code}: local pytdx_history_minutes ref is not day-bucket storage")
    return errors


def delete_old_data(collection: Any, source: str) -> None:
    sources = sorted(str(item) for item in collection.distinct("source") if item)
    total = collection.estimated_document_count()
    source_count = collection.count_documents({"source": source})
    print(f"old collection before delete: total={total} sources={sources} source={source} source_count={source_count}")
    if sources == [source]:
        collection.database.drop_collection(collection.name)
        print(f"dropped old collection: {collection.database.name}.{collection.name}")
        return
    result = collection.delete_many({"source": source})
    print(f"deleted old source documents: {result.deleted_count}")


if __name__ == "__main__":
    main()
