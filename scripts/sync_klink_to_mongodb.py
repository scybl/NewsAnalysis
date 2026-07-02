from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient, UpdateOne

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.config import PROJECT_ROOT, load_dotenv
from stock_pipeline.market_dimensions import STOCK_DATABASE
from stock_pipeline.ths_minute import _mongo_uri
from stock_pipeline.utils import normalize_ts_code, read_json, timestamp


DEFAULT_KLINK_DIR = PROJECT_ROOT / "local_data" / "klink" / "data"
SUPPORTED_FREQUENCIES = ("daily", "weekly", "monthly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local K-line JSON files into MongoDB.")
    parser.add_argument("--database", default=STOCK_DATABASE)
    parser.add_argument("--klink-dir", default=str(DEFAULT_KLINK_DIR))
    parser.add_argument("--collection", default="stock_kline_rows")
    parser.add_argument("--files-collection", default="stock_kline_files")
    parser.add_argument("--manifest-collection", default="stock_kline_manifests")
    parser.add_argument("--freq", default=",".join(SUPPORTED_FREQUENCIES), help="Comma-separated frequencies to sync.")
    parser.add_argument("--codes", default="", help="Comma-separated stock codes. Empty means all files.")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--delete-after-sync", action="store_true", help="Delete each source JSON after it is synced successfully.")
    parser.add_argument("--apply", action="store_true", help="Write to MongoDB. Without this, only print planned work.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()
    root = Path(args.klink_dir)
    if not root.exists():
        raise SystemExit(f"klink data dir does not exist: {root}")

    frequencies = normalize_frequencies(args.freq)
    codes = normalize_codes(args.codes)
    files = discover_files(root, frequencies, codes)
    if args.limit_files > 0:
        files = files[: args.limit_files]

    if not args.apply:
        row_count = planned_row_count(files)
        print(f"would sync files={len(files)} rows={row_count} frequencies={','.join(frequencies)}")
        return 0

    client = MongoClient(_mongo_uri(args.database), serverSelectionTimeoutMS=8000)
    try:
        db = client[args.database]
        ensure_indexes(db, args.collection, args.files_collection, args.manifest_collection)
        totals = sync_files(
            db,
            root,
            files,
            rows_collection=args.collection,
            files_collection=args.files_collection,
            batch_size=max(1, int(args.batch_size or 1000)),
            delete_after_sync=args.delete_after_sync,
        )
        manifest_count = sync_manifest(db, root, args.manifest_collection)
        print(
            "synced: "
            f"files={totals['files']} rows={totals['rows']} "
            f"empty_files={totals['empty_files']} failed_files={totals['failed_files']} "
            f"manifest={manifest_count}"
        )
    finally:
        client.close()
    return 0


def normalize_frequencies(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for item in raw.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value not in SUPPORTED_FREQUENCIES:
            raise SystemExit(f"unsupported frequency: {value}")
        if value not in values:
            values.append(value)
    return tuple(values or SUPPORTED_FREQUENCIES)


def normalize_codes(raw: str) -> set[str]:
    return {normalize_ts_code(item) for item in raw.split(",") if item.strip()}


def discover_files(root: Path, frequencies: tuple[str, ...], codes: set[str]) -> list[Path]:
    files: list[Path] = []
    for frequency in frequencies:
        freq_dir = root / frequency
        if not freq_dir.exists():
            continue
        if codes:
            files.extend(path for code in sorted(codes) if (path := freq_dir / f"{code}.json").exists())
        else:
            files.extend(sorted(freq_dir.glob("*.json")))
    return files


def planned_row_count(files: list[Path]) -> int:
    total = 0
    for path in files:
        payload = read_json(path)
        records = payload.get("records") or []
        if isinstance(records, list):
            total += len(records)
    return total


def ensure_indexes(db: Any, rows_collection: str, files_collection: str, manifest_collection: str) -> None:
    db[rows_collection].create_index(
        [("ts_code", ASCENDING), ("frequency", ASCENDING), ("trade_date", ASCENDING)],
        unique=True,
    )
    db[rows_collection].create_index([("frequency", ASCENDING), ("trade_date", ASCENDING)])
    db[rows_collection].create_index([("ts_code", ASCENDING), ("frequency", ASCENDING)])
    db[files_collection].create_index([("ts_code", ASCENDING), ("frequency", ASCENDING)], unique=True)
    db[manifest_collection].create_index([("path", ASCENDING)], unique=True)


def sync_files(
    db: Any,
    root: Path,
    files: list[Path],
    *,
    rows_collection: str,
    files_collection: str,
    batch_size: int,
    delete_after_sync: bool,
) -> dict[str, int]:
    totals = {"files": 0, "rows": 0, "empty_files": 0, "failed_files": 0}
    for index, path in enumerate(files, start=1):
        try:
            count = sync_file(db, root, path, rows_collection=rows_collection, files_collection=files_collection, batch_size=batch_size)
            if delete_after_sync:
                path.unlink(missing_ok=True)
            totals["files"] += 1
            totals["rows"] += count
            if count == 0:
                totals["empty_files"] += 1
            if index % 100 == 0:
                print(f"progress files={index}/{len(files)} rows={totals['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep long imports resumable.
            totals["failed_files"] += 1
            print(f"failed {relative_path(path, root)}: {exc}", flush=True)
    return totals


def sync_file(db: Any, root: Path, path: Path, *, rows_collection: str, files_collection: str, batch_size: int) -> int:
    payload = read_json(path)
    ts_code = normalize_ts_code(str(payload.get("ts_code") or path.stem))
    frequency = str(payload.get("frequency") or path.parent.name).strip().lower()
    records = payload.get("records") or []
    if not isinstance(records, list):
        records = []

    now = timestamp()
    file_doc = {
        "ts_code": ts_code,
        "frequency": frequency,
        "path": relative_path(path, root),
        "name": payload.get("name") or "",
        "fields": payload.get("fields") or [],
        "date_range": payload.get("date_range") or {},
        "complete_fetch": payload.get("complete_fetch") is True,
        "fetch_strategy": payload.get("fetch_strategy") or "",
        "source": payload.get("source") or "",
        "record_count": len(records),
        "source_updated_at": payload.get("updated_at") or "",
        "synced_at": now,
    }
    db[files_collection].update_one({"ts_code": ts_code, "frequency": frequency}, {"$set": file_doc}, upsert=True)

    operations: list[Any] = []
    total = 0
    for row in records:
        if not isinstance(row, dict):
            continue
        trade_date = str(row.get("trade_date") or "")
        if not trade_date:
            continue
        operations.append(
            UpdateOne(
                {"ts_code": ts_code, "frequency": frequency, "trade_date": trade_date},
                {
                    "$set": {
                        "ts_code": ts_code,
                        "frequency": frequency,
                        "trade_date": trade_date,
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "close": row.get("close"),
                        "pre_close": row.get("pre_close"),
                        "change": row.get("change"),
                        "pct_chg": row.get("pct_chg"),
                        "vol": row.get("vol"),
                        "amount": row.get("amount"),
                        "source_file": relative_path(path, root),
                        "synced_at": now,
                    }
                },
                upsert=True,
            )
        )
        if len(operations) >= batch_size:
            db[rows_collection].bulk_write(operations, ordered=False)
            total += len(operations)
            operations = []
    if operations:
        db[rows_collection].bulk_write(operations, ordered=False)
        total += len(operations)
    return total


def sync_manifest(db: Any, root: Path, manifest_collection: str) -> int:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return 0
    manifest = read_json(manifest_path)
    db[manifest_collection].update_one(
        {"path": "manifest.json"},
        {"$set": {"path": "manifest.json", "manifest": manifest, "synced_at": timestamp()}},
        upsert=True,
    )
    return 1


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
