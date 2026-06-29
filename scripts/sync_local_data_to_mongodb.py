from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pymongo import MongoClient, UpdateOne

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.config import PROJECT_ROOT, load_dotenv
from stock_pipeline.local_data_mongo import collection_names, ensure_indexes, sync_dataset_rows
from stock_pipeline.ths_minute import DEFAULT_DB, _mongo_uri
from stock_pipeline.utils import normalize_ts_code, read_json, timestamp


LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
DEFAULT_PREFIX = "local_data"
SENSITIVE_NAMES = {
    ".DS_Store",
    "master.key",
    "mongo_root_password.txt",
    "secrets.json.enc",
    "web_sessions.json",
    "web_users.json",
}
SKIP_DIRS = {"secure", "mongo", "cache", "__pycache__"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local_data stock packages and safe JSON files into MongoDB.")
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--collection-prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--local-data-dir", default=str(LOCAL_DATA_DIR))
    parser.add_argument("--codes", default="", help="Comma-separated stock codes. Empty means all current stock packages.")
    parser.add_argument("--limit-codes", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--include-app-json", action="store_true", help="Also archive non-sensitive top-level/local app JSON files.")
    parser.add_argument("--include-snapshots", action="store_true", help="Also sync snapshot full_data.json files.")
    parser.add_argument("--skip-dataset-rows", action="store_true", help="Only sync package documents and metadata.")
    parser.add_argument("--apply", action="store_true", help="Write to MongoDB. Without this, only print planned work.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()
    local_data_dir = Path(args.local_data_dir)
    if not local_data_dir.exists():
        raise SystemExit(f"local data dir does not exist: {local_data_dir}")

    client = MongoClient(_mongo_uri(args.database), serverSelectionTimeoutMS=8000)
    try:
        db = client[args.database]
        collections = collection_names(args.collection_prefix)
        if args.apply:
            ensure_indexes(db, collections)

        package_paths = discover_stock_packages(local_data_dir, args.codes, include_snapshots=args.include_snapshots)
        if args.limit_codes > 0:
            package_paths = package_paths[: args.limit_codes]

        totals = {"packages": 0, "metadata": 0, "dataset_rows": 0, "app_json": 0}
        for full_path in package_paths:
            counts = sync_stock_package(
                db,
                collections,
                full_path,
                local_data_dir,
                apply=args.apply,
                skip_dataset_rows=args.skip_dataset_rows,
                batch_size=max(1, int(args.batch_size or 1000)),
            )
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value

        if args.include_app_json:
            totals["app_json"] = sync_app_json_files(
                db,
                collections,
                local_data_dir,
                apply=args.apply,
                batch_size=max(1, int(args.batch_size or 1000)),
            )

        action = "synced" if args.apply else "would sync"
        print(
            f"{action}: packages={totals['packages']} metadata={totals['metadata']} "
            f"dataset_rows={totals['dataset_rows']} app_json={totals['app_json']}"
        )
    finally:
        client.close()
    return 0


def discover_stock_packages(local_data_dir: Path, raw_codes: str, *, include_snapshots: bool) -> list[Path]:
    if raw_codes.strip():
        codes = [normalize_ts_code(item) for item in raw_codes.split(",") if item.strip()]
        paths = [local_data_dir / code / "current" / "full_data.json" for code in codes]
    else:
        paths = sorted(local_data_dir.glob("*/current/full_data.json"))
    if include_snapshots:
        paths.extend(sorted(local_data_dir.glob("*/snapshots/*/full_data.json")))
    return [path for path in paths if path.exists()]


def sync_stock_package(
    db: Any,
    collections: dict[str, str],
    full_path: Path,
    local_data_dir: Path,
    *,
    apply: bool,
    skip_dataset_rows: bool,
    batch_size: int,
) -> dict[str, int]:
    full_data = read_json(full_path)
    ts_code = normalize_ts_code(str(full_data.get("ts_code") or full_path.parents[1].name))
    snapshot = snapshot_name(full_path)
    datasets = full_data.get("datasets") or {}
    dataset_counts = {name: len(rows) for name, rows in datasets.items() if isinstance(rows, list)}
    package_doc = {
        "ts_code": ts_code,
        "snapshot": snapshot,
        "path": relative_path(full_path, local_data_dir),
        "date_range": full_data.get("date_range") or {},
        "fetch_errors": full_data.get("fetch_errors") or [],
        "external_datasets": full_data.get("external_datasets") or {},
        "dataset_counts": dataset_counts,
        "full_data": full_data,
        "synced_at": timestamp(),
    }
    metadata_count = 0
    row_count = 0
    if apply:
        db[collections["packages"]].update_one(
            {"ts_code": ts_code, "snapshot": snapshot},
            {"$set": package_doc},
            upsert=True,
        )
        metadata_count = sync_metadata(db, collections, full_path, local_data_dir, ts_code)
        if not skip_dataset_rows:
            row_count = sync_dataset_rows(db[collections["rows"]], ts_code, snapshot, datasets, batch_size=batch_size)
    else:
        metadata_path = full_path.parents[1] / "metadata.json"
        metadata_count = int(metadata_path.exists())
        row_count = 0 if skip_dataset_rows else sum(dataset_counts.values())
    print(f"{'synced' if apply else 'would sync'} {ts_code} {snapshot}: datasets={len(dataset_counts)} rows={row_count}")
    return {"packages": 1, "metadata": metadata_count, "dataset_rows": row_count}


def sync_metadata(db: Any, collections: dict[str, str], full_path: Path, local_data_dir: Path, ts_code: str) -> int:
    metadata_path = full_path.parents[1] / "metadata.json"
    if not metadata_path.exists():
        return 0
    metadata = read_json(metadata_path)
    db[collections["metadata"]].update_one(
        {"ts_code": ts_code},
        {
            "$set": {
                "ts_code": ts_code,
                "path": relative_path(metadata_path, local_data_dir),
                "metadata": metadata,
                "synced_at": timestamp(),
            }
        },
        upsert=True,
    )
    return 1


def sync_app_json_files(db: Any, collections: dict[str, str], local_data_dir: Path, *, apply: bool, batch_size: int) -> int:
    files = [path for path in sorted(local_data_dir.rglob("*.json")) if should_archive_json(path, local_data_dir)]
    if not apply:
        for path in files[:50]:
            print(f"would archive {relative_path(path, local_data_dir)}")
        if len(files) > 50:
            print(f"would archive ... {len(files) - 50} more json files")
        return len(files)

    operations: list[Any] = []
    collection = db[collections["files"]]
    for path in files:
        rel_path = relative_path(path, local_data_dir)
        operations.append(
            UpdateOne(
                {"path": rel_path},
                {
                    "$set": {
                        "path": rel_path,
                        "data": read_json(path),
                        "synced_at": timestamp(),
                    }
                },
                upsert=True,
            )
        )
        if len(operations) >= batch_size:
            collection.bulk_write(operations, ordered=False)
            operations = []
    if operations:
        collection.bulk_write(operations, ordered=False)
    return len(files)


def should_archive_json(path: Path, local_data_dir: Path) -> bool:
    rel_parts = path.relative_to(local_data_dir).parts
    if any(part in SKIP_DIRS for part in rel_parts):
        return False
    if path.name in SENSITIVE_NAMES:
        return False
    if path.name in {"full_data.json", "metadata.json"}:
        return False
    if "raw" in rel_parts or "snapshots" in rel_parts:
        return False
    return True


def snapshot_name(full_path: Path) -> str:
    parts = full_path.parts
    if "snapshots" in parts:
        index = parts.index("snapshots")
        if index + 1 < len(parts):
            return str(parts[index + 1])
    return "current"


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
