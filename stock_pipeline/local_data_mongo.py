from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient, UpdateOne

from .config import PROJECT_ROOT, load_dotenv
from .market_dimensions import STOCK_COLLECTIONS, STOCK_DATABASE
from .ths_minute import _mongo_uri
from .utils import normalize_ts_code, read_json, timestamp


LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
DEFAULT_DB = STOCK_DATABASE
DEFAULT_PREFIX = "stock"
ROW_KEY_FIELDS = (
    "trade_date",
    "ann_date",
    "end_date",
    "report_date",
    "date",
    "cal_date",
    "f_ann_date",
    "period",
    "publish_date",
    "notice_date",
    "datetime",
    "time",
    "name",
    "index_code",
    "concept_name",
    "holder_name",
    "shareholder_name",
)


def collection_names(prefix: str = DEFAULT_PREFIX) -> dict[str, str]:
    cleaned = prefix.strip().strip("_") or DEFAULT_PREFIX
    if cleaned == "stock":
        return dict(STOCK_COLLECTIONS)
    return {
        "packages": f"{cleaned}_stock_packages",
        "metadata": f"{cleaned}_stock_metadata",
        "rows": f"{cleaned}_stock_dataset_rows",
        "files": f"{cleaned}_json_files",
    }


def mongo_available(database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> bool:
    try:
        with _client(database) as client:
            return collection_names(prefix)["packages"] in client[database].list_collection_names()
    except Exception:
        return False


def list_mongo_stock_codes(database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> list[str]:
    try:
        with _client(database) as client:
            return sorted(
                str(code)
                for code in client[database][collection_names(prefix)["packages"]].distinct("ts_code", {"snapshot": "current"})
                if code
            )
    except Exception:
        return []


def read_mongo_full_data(ts_code: str, database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> dict[str, Any] | None:
    try:
        with _client(database) as client:
            doc = client[database][collection_names(prefix)["packages"]].find_one(
                {"ts_code": normalize_ts_code(ts_code), "snapshot": "current"},
                {"_id": 0, "full_data": 1},
            )
    except Exception:
        return None
    full_data = (doc or {}).get("full_data")
    return full_data if isinstance(full_data, dict) else None


def read_mongo_dossier(ts_code: str, database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> dict[str, Any] | None:
    try:
        with _client(database) as client:
            doc = client[database][collection_names(prefix)["packages"]].find_one(
                {"ts_code": normalize_ts_code(ts_code), "snapshot": "current"},
                {"_id": 0, "dossier": 1},
            )
    except Exception:
        return None
    dossier = (doc or {}).get("dossier")
    return dossier if isinstance(dossier, dict) else None


def read_mongo_analysis_dossier(ts_code: str, analysis_type: str, database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> dict[str, Any] | None:
    try:
        with _client(database) as client:
            doc = client[database][collection_names(prefix)["packages"]].find_one(
                {"ts_code": normalize_ts_code(ts_code), "snapshot": "current"},
                {"_id": 0, f"analysis_dossiers.{analysis_type}": 1},
            )
    except Exception:
        return None
    value = ((doc or {}).get("analysis_dossiers") or {}).get(analysis_type)
    return value if isinstance(value, dict) else None


def read_mongo_metadata(ts_code: str, database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX) -> dict[str, Any] | None:
    try:
        with _client(database) as client:
            doc = client[database][collection_names(prefix)["metadata"]].find_one(
                {"ts_code": normalize_ts_code(ts_code)},
                {"_id": 0, "metadata": 1},
            )
    except Exception:
        return None
    metadata = (doc or {}).get("metadata")
    return metadata if isinstance(metadata, dict) else None


def save_stock_package_to_mongo(
    ts_code: str,
    full_data: dict[str, Any],
    metadata: dict[str, Any],
    *,
    dossier: dict[str, Any] | None = None,
    analysis_dossiers: dict[str, dict[str, Any]] | None = None,
    database: str = DEFAULT_DB,
    prefix: str = DEFAULT_PREFIX,
    snapshot: str = "current",
    batch_size: int = 1000,
) -> dict[str, int]:
    code = normalize_ts_code(ts_code)
    datasets = full_data.get("datasets") or {}
    dataset_counts = {name: len(rows) for name, rows in datasets.items() if isinstance(rows, list)}
    names = collection_names(prefix)
    now = timestamp()
    package_doc = {
        "ts_code": code,
        "snapshot": snapshot,
        "path": f"mongodb://{database}/{names['packages']}/{code}/{snapshot}",
        "date_range": full_data.get("date_range") or {},
        "fetch_errors": full_data.get("fetch_errors") or [],
        "external_datasets": full_data.get("external_datasets") or {},
        "dataset_counts": dataset_counts,
        "full_data": full_data,
        "dossier": dossier or {},
        "analysis_dossiers": analysis_dossiers or {},
        "storage": "mongodb",
        "synced_at": now,
    }
    metadata_doc = {
        "ts_code": code,
        "path": f"mongodb://{database}/{names['metadata']}/{code}",
        "metadata": metadata,
        "storage": "mongodb",
        "synced_at": now,
    }
    with _client(database) as client:
        db = client[database]
        ensure_indexes(db, names)
        db[names["packages"]].update_one({"ts_code": code, "snapshot": snapshot}, {"$set": package_doc}, upsert=True)
        db[names["metadata"]].update_one({"ts_code": code}, {"$set": metadata_doc}, upsert=True)
        row_count = sync_dataset_rows(db[names["rows"]], code, snapshot, datasets, batch_size=batch_size)
    return {"packages": 1, "metadata": 1, "dataset_rows": row_count}


def sync_current_stock_to_mongo(ts_code: str, database: str = DEFAULT_DB, prefix: str = DEFAULT_PREFIX, batch_size: int = 1000) -> dict[str, int]:
    code = normalize_ts_code(ts_code)
    full_path = LOCAL_DATA_DIR / code / "current" / "full_data.json"
    if not full_path.exists():
        return {"packages": 0, "metadata": 0, "dataset_rows": 0}
    full_data = read_json(full_path)
    metadata_path = LOCAL_DATA_DIR / code / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    dossier_path = LOCAL_DATA_DIR / code / "current" / "dossier.json"
    dossier = read_json(dossier_path) if dossier_path.exists() else {}
    analysis_dossiers = {}
    current_dir = LOCAL_DATA_DIR / code / "current"
    if current_dir.exists():
        for path in current_dir.glob("*_dossier.json"):
            if path.name != "dossier.json":
                analysis_dossiers[path.stem.removesuffix("_dossier")] = read_json(path)
    return save_stock_package_to_mongo(
        code,
        full_data,
        metadata,
        dossier=dossier,
        analysis_dossiers=analysis_dossiers,
        database=database,
        prefix=prefix,
        batch_size=batch_size,
    )


def ensure_indexes(db: Any, names: dict[str, str]) -> None:
    db[names["packages"]].create_index([("ts_code", ASCENDING), ("snapshot", ASCENDING)], unique=True)
    db[names["packages"]].create_index([("updated_at", ASCENDING)])
    db[names["metadata"]].create_index([("ts_code", ASCENDING)], unique=True)
    db[names["rows"]].create_index([("ts_code", ASCENDING), ("snapshot", ASCENDING), ("dataset", ASCENDING), ("row_key", ASCENDING)], unique=True)
    db[names["rows"]].create_index([("dataset", ASCENDING), ("trade_date", ASCENDING)])
    db[names["rows"]].create_index([("ts_code", ASCENDING), ("dataset", ASCENDING), ("trade_date", ASCENDING)])
    db[names["files"]].create_index([("path", ASCENDING)], unique=True)


def sync_dataset_rows(collection: Any, ts_code: str, snapshot: str, datasets: dict[str, Any], *, batch_size: int = 1000) -> int:
    operations: list[Any] = []
    total = 0
    collection.delete_many({"ts_code": ts_code, "snapshot": snapshot})
    for dataset, rows in datasets.items():
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_key = stable_row_key(row, index)
            operations.append(
                UpdateOne(
                    {"ts_code": ts_code, "snapshot": snapshot, "dataset": str(dataset), "row_key": row_key},
                    {
                        "$set": {
                            "ts_code": ts_code,
                            "snapshot": snapshot,
                            "dataset": str(dataset),
                            "row_key": row_key,
                            "trade_date": first_present(row, ("trade_date", "date", "cal_date", "ann_date", "end_date", "report_date")),
                            "row": row,
                            "synced_at": timestamp(),
                        }
                    },
                    upsert=True,
                )
            )
            if len(operations) >= batch_size:
                collection.bulk_write(operations, ordered=False)
                total += len(operations)
                operations = []
    if operations:
        collection.bulk_write(operations, ordered=False)
        total += len(operations)
    return total


def stable_row_key(row: dict[str, Any], index: int) -> str:
    parts = [str(row.get(field)) for field in ROW_KEY_FIELDS if row.get(field) not in (None, "")]
    base = "|".join(parts) if parts else f"row_index:{index}"
    digest = hashlib.sha1(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return f"{base}|{digest}"


def first_present(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def _client(database: str) -> MongoClient:
    load_dotenv()
    return MongoClient(_mongo_uri(database), serverSelectionTimeoutMS=5000)


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(LOCAL_DATA_DIR))
    except ValueError:
        return str(path)
