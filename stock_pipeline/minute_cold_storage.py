from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import PROJECT_ROOT, load_dotenv
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from .utils import ensure_dir, normalize_ts_code


DEFAULT_REMOTE_ROOT = "NewsAnalysis/cold/stock_minute/v1"
DEFAULT_LOCAL_ROOT = PROJECT_ROOT / "local_data" / "cold_archive" / "stock_minute" / "v1"
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "local_data" / "cache" / "stock_minute" / "v1"
HOT_DAYS = 15
CACHE_MAX_BYTES = 10 * 1024 * 1024 * 1024
EXPECTED_DAY_ROWS = 240


@dataclass(frozen=True)
class MinuteColdConfig:
    local_root: Path = DEFAULT_LOCAL_ROOT
    cache_root: Path = DEFAULT_CACHE_ROOT
    remote_root: str = DEFAULT_REMOTE_ROOT
    hot_days: int = HOT_DAYS
    cache_max_bytes: int = CACHE_MAX_BYTES
    bdpan_bin: str = "bdpan"


def build_config() -> MinuteColdConfig:
    load_dotenv()
    return MinuteColdConfig(
        local_root=Path(os.getenv("STOCK_MINUTE_COLD_LOCAL_ROOT", str(DEFAULT_LOCAL_ROOT))),
        cache_root=Path(os.getenv("STOCK_MINUTE_CACHE_ROOT", str(DEFAULT_CACHE_ROOT))),
        remote_root=os.getenv("STOCK_MINUTE_COLD_REMOTE_ROOT", DEFAULT_REMOTE_ROOT).strip("/"),
        hot_days=int(os.getenv("STOCK_MINUTE_HOT_DAYS", str(HOT_DAYS))),
        cache_max_bytes=int(os.getenv("STOCK_MINUTE_CACHE_MAX_BYTES", str(CACHE_MAX_BYTES))),
        bdpan_bin=os.getenv("BDPAN_BIN", "bdpan"),
    )


def ensure_indexes(day_index: Any, coverage: Any, pymongo_module: Any) -> None:
    day_index.create_index(
        [("source", pymongo_module.ASCENDING), ("ts_code", pymongo_module.ASCENDING), ("trade_date", pymongo_module.ASCENDING)],
        unique=True,
        name="source_ts_code_trade_date_unique",
    )
    day_index.create_index([("ts_code", pymongo_module.ASCENDING), ("trade_date", pymongo_module.DESCENDING)], name="ts_code_trade_date")
    day_index.create_index([("remote_path", pymongo_module.ASCENDING)], name="remote_path")
    day_index.create_index(
        [("source", pymongo_module.ASCENDING), ("ts_code", pymongo_module.ASCENDING), ("object_trade_year", pymongo_module.ASCENDING)],
        name="source_ts_code_object_trade_year",
    )
    day_index.create_index([("cache.last_accessed_at", pymongo_module.ASCENDING)], name="cache_last_accessed_at")
    coverage.create_index(
        [("source", pymongo_module.ASCENDING), ("ts_code", pymongo_module.ASCENDING)],
        unique=True,
        name="source_ts_code_unique",
    )


def bucket_object_relative_path(bucket: dict[str, Any]) -> Path:
    ts_code = normalize_ts_code(str(bucket.get("ts_code") or ""))
    trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
    return Path("objects") / ts_code / trade_date[:4] / trade_date[4:6] / f"{trade_date}.jsonl"


def month_object_relative_path(ts_code: str, trade_month: str) -> Path:
    code = normalize_ts_code(ts_code)
    month = normalize_trade_month(trade_month)
    return Path("objects_month") / code / month[:4] / f"{month}.jsonl"


def stock_object_relative_path(source: str, ts_code: str) -> Path:
    code = normalize_ts_code(ts_code)
    safe_source = str(source or "unknown").replace("/", "_")
    return Path("objects_stock") / safe_source / f"{code}.jsonl"


def stock_year_object_relative_path(source: str, ts_code: str, trade_year: str) -> Path:
    code = normalize_ts_code(ts_code)
    year = normalize_trade_year(trade_year)
    safe_source = str(source or "unknown").replace("/", "_")
    return Path("objects_stock_year") / safe_source / code / f"{year}.jsonl"


def remote_object_path(bucket: dict[str, Any], config: MinuteColdConfig | None = None) -> str:
    cfg = config or build_config()
    return f"{cfg.remote_root}/{bucket_object_relative_path(bucket).as_posix()}"


def write_bucket_object(bucket: dict[str, Any], config: MinuteColdConfig | None = None, *, root: Path | None = None) -> dict[str, Any]:
    cfg = config or build_config()
    relative_path = bucket_object_relative_path(bucket)
    target = (root or cfg.local_root) / relative_path
    ensure_dir(target.parent)
    rows = bucket_rows(bucket)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default))
            handle.write("\n")
    digest = _sha256_file(target)
    return {
        "local_path": str(target),
        "relative_path": relative_path.as_posix(),
        "remote_path": f"{cfg.remote_root}/{relative_path.as_posix()}",
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "row_count": len(rows),
        "start_minute": str(bucket.get("start_minute") or ""),
        "end_minute": str(bucket.get("end_minute") or ""),
    }


def bucket_rows(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        "source": bucket.get("source", ""),
        "dataset": bucket.get("dataset", ""),
        "ts_code": bucket.get("ts_code", ""),
        "symbol": bucket.get("symbol", ""),
        "trade_date": bucket.get("trade_date", ""),
    }
    rows = []
    for item in bucket.get("minutes") or []:
        if isinstance(item, dict):
            rows.append({**base, **item})
    return rows


def upsert_day_index(day_index: Any, bucket: dict[str, Any], object_info: dict[str, Any], *, upload_status: str = "local") -> None:
    source = str(bucket.get("source") or "")
    ts_code = normalize_ts_code(str(bucket.get("ts_code") or ""))
    trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
    now = datetime.now(timezone.utc)
    row_count = int(bucket.get("row_count") or object_info.get("row_count") or 0)
    status = "complete" if row_count >= EXPECTED_DAY_ROWS else "partial"
    day_index.update_one(
        {"source": source, "ts_code": ts_code, "trade_date": trade_date},
        {
            "$set": {
                "source": source,
                "dataset": str(bucket.get("dataset") or ""),
                "ts_code": ts_code,
                "symbol": str(bucket.get("symbol") or ts_code[:6]),
                "trade_date": trade_date,
                "status": status,
                "expected_rows": EXPECTED_DAY_ROWS,
                "row_count": row_count,
                "start_minute": str(bucket.get("start_minute") or object_info.get("start_minute") or ""),
                "end_minute": str(bucket.get("end_minute") or object_info.get("end_minute") or ""),
                "remote_path": str(object_info.get("remote_path") or ""),
                "relative_path": str(object_info.get("relative_path") or ""),
                "sha256": str(object_info.get("sha256") or ""),
                "size_bytes": int(object_info.get("size_bytes") or 0),
                "storage_object": str(object_info.get("storage_object") or "day_jsonl"),
                "object_trade_month": str(object_info.get("object_trade_month") or trade_date[:6]),
                "object_trade_year": str(object_info.get("object_trade_year") or trade_date[:4]),
                "upload_status": upload_status,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def refresh_coverage(day_index: Any, coverage: Any, *, source: str, ts_code: str) -> dict[str, Any]:
    query = {"source": source, "ts_code": normalize_ts_code(ts_code)}
    rows = list(
        day_index.aggregate(
            [
                {"$match": query},
                {
                    "$group": {
                        "_id": None,
                        "first_trade_date": {"$min": "$trade_date"},
                        "last_trade_date": {"$max": "$trade_date"},
                        "days": {"$sum": 1},
                        "rows": {"$sum": "$row_count"},
                        "complete_days": {"$sum": {"$cond": [{"$eq": ["$status", "complete"]}, 1, 0]}},
                        "partial_days": {"$sum": {"$cond": [{"$ne": ["$status", "complete"]}, 1, 0]}},
                        "bytes": {"$sum": "$size_bytes"},
                    }
                },
            ]
        )
    )
    summary = rows[0] if rows else {}
    payload = {
        "source": source,
        "ts_code": normalize_ts_code(ts_code),
        "has_minute_data": bool(summary),
        "first_trade_date": str(summary.get("first_trade_date") or ""),
        "last_trade_date": str(summary.get("last_trade_date") or ""),
        "archived_days": int(summary.get("days") or 0),
        "archived_rows": int(summary.get("rows") or 0),
        "complete_days": int(summary.get("complete_days") or 0),
        "partial_days": int(summary.get("partial_days") or 0),
        "missing_days": None,
        "storage": "baidu_netdisk_day_objects",
        "hot_days": HOT_DAYS,
        "cache_max_bytes": CACHE_MAX_BYTES,
        "remote_root": DEFAULT_REMOTE_ROOT,
        "updated_at": datetime.now(timezone.utc),
    }
    coverage.update_one(query, {"$set": payload}, upsert=True)
    return payload


def archive_buckets(
    bucket_collection: Any,
    day_index: Any,
    coverage: Any,
    *,
    query: dict[str, Any],
    config: MinuteColdConfig | None = None,
    limit: int | None = None,
    upload: bool = False,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    cursor = bucket_collection.find(query, {"_id": 0}).sort([("ts_code", 1), ("trade_date", 1)])
    if limit:
        cursor = cursor.limit(int(limit))
    exported = 0
    uploaded = 0
    failed: list[dict[str, str]] = []
    touched: set[tuple[str, str]] = set()
    for bucket in cursor:
        try:
            object_info = write_bucket_object(bucket, cfg)
            status = "local"
            if upload:
                upload_one(object_info["local_path"], object_info["remote_path"], cfg, runner=runner)
                status = "uploaded"
                uploaded += 1
            upsert_day_index(day_index, bucket, object_info, upload_status=status)
            exported += 1
            touched.add((str(bucket.get("source") or ""), normalize_ts_code(str(bucket.get("ts_code") or ""))))
        except Exception as exc:  # noqa: BLE001 - keep archival resumable
            failed.append(
                {
                    "ts_code": str(bucket.get("ts_code") or ""),
                    "trade_date": str(bucket.get("trade_date") or ""),
                    "error": str(exc),
                }
            )
    coverage_rows = [refresh_coverage(day_index, coverage, source=source, ts_code=ts_code) for source, ts_code in sorted(touched)]
    return {"ok": not failed, "exported": exported, "uploaded": uploaded, "failed": failed[:20], "coverage_updated": len(coverage_rows)}


def archive_month_shards(
    bucket_collection: Any,
    day_index: Any,
    coverage: Any,
    *,
    query: dict[str, Any],
    config: MinuteColdConfig | None = None,
    limit: int | None = None,
    upload: bool = False,
    workers: int = 1,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    cursor = bucket_collection.find(query, {"_id": 0}).sort([("source", 1), ("ts_code", 1), ("trade_date", 1)])
    worker_count = max(1, int(workers or 1))
    exported_days = 0
    skipped_days = 0
    uploaded_files = 0
    failed: list[dict[str, str]] = []
    touched: set[tuple[str, str]] = set()
    current_key: tuple[str, str, str] | None = None
    current_buckets: list[dict[str, Any]] = []

    def process_month(key: tuple[str, str, str], buckets: list[dict[str, Any]]) -> dict[str, Any]:
        source, ts_code, month = key
        try:
            expected_relative_path = month_object_relative_path(ts_code, month).as_posix()
            trade_dates = [normalize_trade_date(str(bucket.get("trade_date") or "")) for bucket in buckets]
            already_uploaded = day_index.count_documents(
                {
                    "source": source,
                    "ts_code": ts_code,
                    "trade_date": {"$in": trade_dates},
                    "relative_path": expected_relative_path,
                    "storage_object": "month_jsonl",
                    "upload_status": "uploaded",
                }
            )
            if already_uploaded == len(buckets):
                return {"ok": True, "skipped_days": len(buckets), "exported_days": 0, "uploaded_files": 0, "touched": (source, ts_code)}
            object_info = write_month_object(buckets, cfg, ts_code=ts_code, trade_month=month)
            status = "local"
            if upload:
                upload_one(object_info["local_path"], object_info["remote_path"], cfg, runner=runner)
                status = "uploaded"
            for bucket in buckets:
                upsert_day_index(day_index, bucket, object_info, upload_status=status)
            return {
                "ok": True,
                "skipped_days": 0,
                "exported_days": len(buckets),
                "uploaded_files": 1 if upload else 0,
                "touched": (source, ts_code),
            }
        except Exception as exc:  # noqa: BLE001 - keep archival resumable
            return {"ok": False, "failed": {"source": source, "ts_code": ts_code, "trade_month": month, "error": str(exc)}}

    def collect_result(result: dict[str, Any]) -> None:
        nonlocal exported_days, skipped_days, uploaded_files
        if not result.get("ok"):
            failed.append(result.get("failed") or {"error": "unknown"})
            return
        exported_days += int(result.get("exported_days") or 0)
        skipped_days += int(result.get("skipped_days") or 0)
        uploaded_files += int(result.get("uploaded_files") or 0)
        touched_item = result.get("touched")
        if isinstance(touched_item, tuple) and len(touched_item) == 2:
            touched.add(touched_item)

    def flush() -> None:
        nonlocal current_key, current_buckets
        if not current_key or not current_buckets:
            return
        result = process_month(current_key, list(current_buckets))
        collect_result(result)
        current_key = None
        current_buckets = []

    if worker_count <= 1:
        for bucket in cursor:
            ts_code = normalize_ts_code(str(bucket.get("ts_code") or ""))
            trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
            key = (str(bucket.get("source") or ""), ts_code, trade_date[:6])
            if current_key is not None and key != current_key:
                flush()
                if limit and exported_days >= int(limit):
                    break
            current_key = key
            current_buckets.append(bucket)
        flush()
    else:
        pending: set[Future] = set()
        max_pending = worker_count * 3

        def submit_current(executor: ThreadPoolExecutor) -> None:
            nonlocal current_key, current_buckets, pending
            if not current_key or not current_buckets:
                return
            pending.add(executor.submit(process_month, current_key, list(current_buckets)))
            current_key = None
            current_buckets = []
            if len(pending) >= max_pending:
                done, remaining = wait(pending, return_when=FIRST_COMPLETED)
                pending = remaining
                for future in done:
                    collect_result(future.result())

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for bucket in cursor:
                ts_code = normalize_ts_code(str(bucket.get("ts_code") or ""))
                trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
                key = (str(bucket.get("source") or ""), ts_code, trade_date[:6])
                if current_key is not None and key != current_key:
                    submit_current(executor)
                    if limit and exported_days >= int(limit):
                        break
                current_key = key
                current_buckets.append(bucket)
            submit_current(executor)
            for future in pending:
                collect_result(future.result())
    coverage_rows = [refresh_coverage(day_index, coverage, source=source, ts_code=ts_code) for source, ts_code in sorted(touched)]
    return {
        "ok": not failed,
        "exported_days": exported_days,
        "skipped_days": skipped_days,
        "uploaded_files": uploaded_files,
        "failed": failed[:20],
        "coverage_updated": len(coverage_rows),
        "storage_object": "month_jsonl",
    }


def archive_stock_shards(
    bucket_collection: Any,
    day_index: Any,
    coverage: Any,
    *,
    query: dict[str, Any],
    config: MinuteColdConfig | None = None,
    limit: int | None = None,
    upload: bool = False,
    remove_local_after_upload: bool = True,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    stock_keys = _stock_keys_for_query(bucket_collection, query)
    exported_days = 0
    skipped_days = 0
    uploaded_files = 0
    failed: list[dict[str, str]] = []
    touched: set[tuple[str, str]] = set()

    def process_stock(key: tuple[str, str], buckets: list[dict[str, Any]]) -> dict[str, Any]:
        source, ts_code = key
        try:
            expected_relative_path = stock_object_relative_path(source, ts_code).as_posix()
            trade_dates = [normalize_trade_date(str(bucket.get("trade_date") or "")) for bucket in buckets]
            already_uploaded = day_index.count_documents(
                {
                    "source": source,
                    "ts_code": ts_code,
                    "trade_date": {"$in": trade_dates},
                    "relative_path": expected_relative_path,
                    "storage_object": "stock_jsonl",
                    "upload_status": "uploaded",
                }
            )
            if already_uploaded == len(buckets):
                return {"ok": True, "skipped_days": len(buckets), "exported_days": 0, "uploaded_files": 0, "touched": key}
            object_info = write_stock_object(buckets, cfg, source=source, ts_code=ts_code)
            status = "local"
            if upload:
                upload_one(object_info["local_path"], object_info["remote_path"], cfg, runner=runner)
                status = "uploaded"
                if remove_local_after_upload:
                    Path(object_info["local_path"]).unlink(missing_ok=True)
            for bucket in buckets:
                upsert_day_index(day_index, bucket, object_info, upload_status=status)
            return {"ok": True, "skipped_days": 0, "exported_days": len(buckets), "uploaded_files": 1 if upload else 0, "touched": key}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "failed": {"source": source, "ts_code": ts_code, "error": str(exc)}}

    def collect(result: dict[str, Any]) -> None:
        nonlocal exported_days, skipped_days, uploaded_files
        if not result.get("ok"):
            failed.append(result.get("failed") or {"error": "unknown"})
            return
        exported_days += int(result.get("exported_days") or 0)
        skipped_days += int(result.get("skipped_days") or 0)
        uploaded_files += int(result.get("uploaded_files") or 0)
        touched_item = result.get("touched")
        if isinstance(touched_item, tuple) and len(touched_item) == 2:
            touched.add(touched_item)

    for source, ts_code in stock_keys:
        if limit and exported_days >= int(limit):
            break
        stock_query = {**query, "source": source, "ts_code": ts_code}
        buckets = list(bucket_collection.find(stock_query, {"_id": 0}).sort([("trade_date", 1)]))
        if not buckets:
            continue
        collect(process_stock((source, ts_code), buckets))
    coverage_rows = [refresh_coverage(day_index, coverage, source=source, ts_code=ts_code) for source, ts_code in sorted(touched)]
    return {
        "ok": not failed,
        "exported_days": exported_days,
        "skipped_days": skipped_days,
        "uploaded_files": uploaded_files,
        "failed": failed[:20],
        "coverage_updated": len(coverage_rows),
        "storage_object": "stock_jsonl",
    }


def archive_stock_year_shards(
    bucket_collection: Any,
    day_index: Any,
    coverage: Any,
    *,
    query: dict[str, Any],
    config: MinuteColdConfig | None = None,
    limit: int | None = None,
    upload: bool = False,
    remove_local_after_upload: bool = True,
    progress: bool = False,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    stock_keys = _stock_keys_for_query(bucket_collection, query)
    stock_years = [
        (source, ts_code, year)
        for source, ts_code in stock_keys
        for year in _stock_years_for_query(bucket_collection, {**query, "source": source, "ts_code": ts_code})
    ]
    total_files = len(stock_years)
    exported_days = 0
    skipped_days = 0
    uploaded_files = 0
    failed: list[dict[str, str]] = []
    touched: set[tuple[str, str]] = set()

    def log(event: str, **fields: Any) -> None:
        if not progress:
            return
        payload = " ".join(f"{name}={value}" for name, value in fields.items() if value is not None)
        print(f"[minute-cold][{_utc_now_text()}] {event} {payload}".rstrip(), flush=True)

    log("plan", stocks=len(stock_keys), year_files=total_files, upload=upload, storage_object="stock_year_jsonl")

    def process_year(key: tuple[str, str, str], buckets: list[dict[str, Any]], position: int) -> dict[str, Any]:
        source, ts_code, year = key
        percent = _percent(position, total_files)
        try:
            expected_relative_path = stock_year_object_relative_path(source, ts_code, year).as_posix()
            trade_dates = [normalize_trade_date(str(bucket.get("trade_date") or "")) for bucket in buckets]
            log("check", current=f"{position}/{total_files}", percent=percent, source=source, ts_code=ts_code, year=year, days=len(buckets))
            already_uploaded = day_index.count_documents(
                {
                    "source": source,
                    "ts_code": ts_code,
                    "trade_date": {"$in": trade_dates},
                    "relative_path": expected_relative_path,
                    "storage_object": "stock_year_jsonl",
                    "upload_status": "uploaded",
                }
            )
            if already_uploaded == len(buckets):
                log(
                    "skip",
                    current=f"{position}/{total_files}",
                    percent=percent,
                    source=source,
                    ts_code=ts_code,
                    year=year,
                    days=len(buckets),
                    reason="already_uploaded",
                )
                return {
                    "ok": True,
                    "skipped_days": len(buckets),
                    "exported_days": 0,
                    "uploaded_files": 0,
                    "touched": (source, ts_code),
                }
            log(
                "write_start",
                current=f"{position}/{total_files}",
                percent=percent,
                source=source,
                ts_code=ts_code,
                year=year,
                days=len(buckets),
            )
            object_info = write_stock_year_object(buckets, cfg, source=source, ts_code=ts_code, trade_year=year)
            log(
                "write_done",
                current=f"{position}/{total_files}",
                percent=percent,
                source=source,
                ts_code=ts_code,
                year=year,
                size=_format_bytes(int(object_info.get("size_bytes") or 0)),
                rows=object_info.get("row_count"),
                path=object_info.get("relative_path"),
            )
            status = "local"
            if upload:
                log(
                    "upload_start",
                    current=f"{position}/{total_files}",
                    percent=percent,
                    source=source,
                    ts_code=ts_code,
                    year=year,
                    size=_format_bytes(int(object_info.get("size_bytes") or 0)),
                    remote=object_info.get("remote_path"),
                )
                upload_one(object_info["local_path"], object_info["remote_path"], cfg, runner=runner)
                status = "uploaded"
                log("upload_done", current=f"{position}/{total_files}", percent=percent, source=source, ts_code=ts_code, year=year)
                if remove_local_after_upload:
                    Path(object_info["local_path"]).unlink(missing_ok=True)
                    log("local_removed", current=f"{position}/{total_files}", percent=percent, source=source, ts_code=ts_code, year=year)
            for bucket in buckets:
                upsert_day_index(day_index, bucket, object_info, upload_status=status)
            log(
                "index_done",
                current=f"{position}/{total_files}",
                percent=percent,
                source=source,
                ts_code=ts_code,
                year=year,
                days=len(buckets),
                status=status,
            )
            return {
                "ok": True,
                "skipped_days": 0,
                "exported_days": len(buckets),
                "uploaded_files": 1 if upload else 0,
                "touched": (source, ts_code),
            }
        except Exception as exc:  # noqa: BLE001
            source, ts_code, year = key
            log("failed", current=f"{position}/{total_files}", percent=percent, source=source, ts_code=ts_code, year=year, error=str(exc))
            return {"ok": False, "failed": {"source": source, "ts_code": ts_code, "trade_year": year, "error": str(exc)}}

    def collect(result: dict[str, Any]) -> None:
        nonlocal exported_days, skipped_days, uploaded_files
        if not result.get("ok"):
            failed.append(result.get("failed") or {"error": "unknown"})
            return
        exported_days += int(result.get("exported_days") or 0)
        skipped_days += int(result.get("skipped_days") or 0)
        uploaded_files += int(result.get("uploaded_files") or 0)
        touched_item = result.get("touched")
        if isinstance(touched_item, tuple) and len(touched_item) == 2:
            touched.add(touched_item)

    for position, (source, ts_code, year) in enumerate(stock_years, start=1):
        if limit and exported_days >= int(limit):
            break
        stock_query = {**query, "source": source, "ts_code": ts_code}
        year_query = _year_limited_query(stock_query, year)
        buckets = list(bucket_collection.find(year_query, {"_id": 0}).sort([("trade_date", 1)]))
        if not buckets:
            log(
                "empty",
                current=f"{position}/{total_files}",
                percent=_percent(position, total_files),
                source=source,
                ts_code=ts_code,
                year=year,
            )
            continue
        collect(process_year((source, ts_code, year), buckets, position))
    coverage_rows = [refresh_coverage(day_index, coverage, source=source, ts_code=ts_code) for source, ts_code in sorted(touched)]
    log(
        "summary",
        ok=not failed,
        exported_days=exported_days,
        skipped_days=skipped_days,
        uploaded_files=uploaded_files,
        failed=len(failed),
        coverage_updated=len(coverage_rows),
    )
    return {
        "ok": not failed,
        "exported_days": exported_days,
        "skipped_days": skipped_days,
        "uploaded_files": uploaded_files,
        "failed": failed[:20],
        "coverage_updated": len(coverage_rows),
        "storage_object": "stock_year_jsonl",
    }


def _stock_keys_for_query(bucket_collection: Any, query: dict[str, Any]) -> list[tuple[str, str]]:
    pipeline = [
        {"$match": query},
        {"$group": {"_id": {"source": "$source", "ts_code": "$ts_code"}}},
        {"$sort": {"_id.source": 1, "_id.ts_code": 1}},
    ]
    if hasattr(bucket_collection, "aggregate"):
        rows = bucket_collection.aggregate(pipeline, allowDiskUse=True)
        return [
            (str((row.get("_id") or {}).get("source") or ""), normalize_ts_code(str((row.get("_id") or {}).get("ts_code") or "")))
            for row in rows
            if (row.get("_id") or {}).get("ts_code")
        ]

    keys = set()
    for bucket in bucket_collection.find(query, {"_id": 0, "source": 1, "ts_code": 1}):
        ts_code = normalize_ts_code(str(bucket.get("ts_code") or ""))
        if ts_code:
            keys.add((str(bucket.get("source") or ""), ts_code))
    return sorted(keys)


def _stock_years_for_query(bucket_collection: Any, query: dict[str, Any]) -> list[str]:
    pipeline = [
        {"$match": query},
        {"$group": {"_id": {"$substr": ["$trade_date", 0, 4]}}},
        {"$sort": {"_id": 1}},
    ]
    if hasattr(bucket_collection, "aggregate"):
        rows = bucket_collection.aggregate(pipeline, allowDiskUse=True)
        return [normalize_trade_year(str(row.get("_id") or "")) for row in rows if row.get("_id")]

    years = set()
    for bucket in bucket_collection.find(query, {"_id": 0, "trade_date": 1}):
        trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
        years.add(trade_date[:4])
    return sorted(years)


def _year_limited_query(query: dict[str, Any], trade_year: str) -> dict[str, Any]:
    year = normalize_trade_year(trade_year)
    existing = query.get("trade_date")
    if isinstance(existing, str):
        return dict(query) if existing.startswith(year) else {**query, "trade_date": "__never__"}
    if isinstance(existing, dict):
        return dict(query)
    return {**query, "trade_date": {"$gte": f"{year}0101", "$lte": f"{year}1231"}}


def cleanup_archived_buckets(
    bucket_collection: Any,
    day_index: Any,
    coverage: Any,
    *,
    source: str,
    hot_days: int = HOT_DAYS,
    codes: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    archived_objects = ["stock_jsonl", "stock_year_jsonl"]
    query: dict[str, Any] = {"source": source, "storage_object": {"$in": archived_objects}, "upload_status": "uploaded"}
    if codes:
        query["ts_code"] = {"$in": [normalize_ts_code(code) for code in codes]}
    ts_codes = sorted(day_index.distinct("ts_code", query))
    removed_docs = 0
    planned_docs = 0
    touched: set[tuple[str, str]] = set()
    samples: list[dict[str, Any]] = []
    for ts_code in ts_codes:
        uploaded_dates = [
            str(item.get("trade_date") or "")
            for item in day_index.find(
                {"source": source, "ts_code": ts_code, "storage_object": {"$in": archived_objects}, "upload_status": "uploaded"},
                {"_id": 0, "trade_date": 1},
            ).sort([("trade_date", -1)])
        ]
        delete_dates = uploaded_dates[max(0, int(hot_days)) :]
        if not delete_dates:
            continue
        delete_query = {"source": source, "ts_code": ts_code, "trade_date": {"$in": delete_dates}}
        count = bucket_collection.count_documents(delete_query)
        planned_docs += count
        if len(samples) < 10:
            samples.append({"ts_code": ts_code, "delete_days": len(delete_dates), "matching_bucket_docs": count})
        if count and not dry_run:
            result = bucket_collection.delete_many(delete_query)
            removed_docs += int(result.deleted_count or 0)
            touched.add((source, ts_code))
    coverage_rows = []
    if not dry_run:
        coverage_rows = [refresh_coverage(day_index, coverage, source=item_source, ts_code=ts_code) for item_source, ts_code in sorted(touched)]
    return {
        "ok": True,
        "dry_run": dry_run,
        "source": source,
        "hot_days": int(hot_days),
        "stocks_considered": len(ts_codes),
        "planned_bucket_docs": planned_docs,
        "deleted_bucket_docs": removed_docs,
        "coverage_updated": len(coverage_rows),
        "samples": samples,
    }


def write_month_object(
    buckets: list[dict[str, Any]],
    config: MinuteColdConfig | None = None,
    *,
    ts_code: str,
    trade_month: str,
    root: Path | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    relative_path = month_object_relative_path(ts_code, trade_month)
    target = (root or cfg.local_root) / relative_path
    ensure_dir(target.parent)
    total_rows = 0
    start_minute = ""
    end_minute = ""
    with target.open("w", encoding="utf-8") as handle:
        for bucket in sorted(buckets, key=lambda item: str(item.get("trade_date") or "")):
            rows = bucket_rows(bucket)
            total_rows += len(rows)
            if not start_minute:
                start_minute = str(bucket.get("start_minute") or "")
            end_minute = str(bucket.get("end_minute") or end_minute)
            handle.write(
                json.dumps(
                    {
                        "source": bucket.get("source", ""),
                        "dataset": bucket.get("dataset", ""),
                        "ts_code": normalize_ts_code(str(bucket.get("ts_code") or ts_code)),
                        "symbol": bucket.get("symbol", ""),
                        "trade_date": normalize_trade_date(str(bucket.get("trade_date") or "")),
                        "row_count": len(rows),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                )
            )
            handle.write("\n")
    digest = _sha256_file(target)
    return {
        "local_path": str(target),
        "relative_path": relative_path.as_posix(),
        "remote_path": f"{cfg.remote_root}/{relative_path.as_posix()}",
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "row_count": total_rows,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "storage_object": "month_jsonl",
        "object_trade_month": normalize_trade_month(trade_month),
    }


def write_stock_object(
    buckets: list[dict[str, Any]],
    config: MinuteColdConfig | None = None,
    *,
    source: str,
    ts_code: str,
    root: Path | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    relative_path = stock_object_relative_path(source, ts_code)
    target = (root or cfg.local_root) / relative_path
    ensure_dir(target.parent)
    total_rows = 0
    first_date = ""
    last_date = ""
    start_minute = ""
    end_minute = ""
    with target.open("w", encoding="utf-8") as handle:
        for bucket in sorted(buckets, key=lambda item: str(item.get("trade_date") or "")):
            trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
            rows = bucket_rows(bucket)
            total_rows += len(rows)
            first_date = first_date or trade_date
            last_date = trade_date
            if not start_minute:
                start_minute = str(bucket.get("start_minute") or "")
            end_minute = str(bucket.get("end_minute") or end_minute)
            handle.write(
                json.dumps(
                    {
                        "source": bucket.get("source", source),
                        "dataset": bucket.get("dataset", ""),
                        "ts_code": normalize_ts_code(str(bucket.get("ts_code") or ts_code)),
                        "symbol": bucket.get("symbol", ""),
                        "trade_date": trade_date,
                        "row_count": len(rows),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                )
            )
            handle.write("\n")
    digest = _sha256_file(target)
    return {
        "local_path": str(target),
        "relative_path": relative_path.as_posix(),
        "remote_path": f"{cfg.remote_root}/{relative_path.as_posix()}",
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "row_count": total_rows,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "storage_object": "stock_jsonl",
        "object_trade_month": "",
        "first_trade_date": first_date,
        "last_trade_date": last_date,
    }


def write_stock_year_object(
    buckets: list[dict[str, Any]],
    config: MinuteColdConfig | None = None,
    *,
    source: str,
    ts_code: str,
    trade_year: str,
    root: Path | None = None,
) -> dict[str, Any]:
    cfg = config or build_config()
    year = normalize_trade_year(trade_year)
    relative_path = stock_year_object_relative_path(source, ts_code, year)
    target = (root or cfg.local_root) / relative_path
    ensure_dir(target.parent)
    total_rows = 0
    first_date = ""
    last_date = ""
    start_minute = ""
    end_minute = ""
    with target.open("w", encoding="utf-8") as handle:
        for bucket in sorted(buckets, key=lambda item: str(item.get("trade_date") or "")):
            trade_date = normalize_trade_date(str(bucket.get("trade_date") or ""))
            rows = bucket_rows(bucket)
            total_rows += len(rows)
            first_date = first_date or trade_date
            last_date = trade_date
            if not start_minute:
                start_minute = str(bucket.get("start_minute") or "")
            end_minute = str(bucket.get("end_minute") or end_minute)
            handle.write(
                json.dumps(
                    {
                        "source": bucket.get("source", source),
                        "dataset": bucket.get("dataset", ""),
                        "ts_code": normalize_ts_code(str(bucket.get("ts_code") or ts_code)),
                        "symbol": bucket.get("symbol", ""),
                        "trade_date": trade_date,
                        "row_count": len(rows),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                )
            )
            handle.write("\n")
    digest = _sha256_file(target)
    return {
        "local_path": str(target),
        "relative_path": relative_path.as_posix(),
        "remote_path": f"{cfg.remote_root}/{relative_path.as_posix()}",
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "row_count": total_rows,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "storage_object": "stock_year_jsonl",
        "object_trade_month": "",
        "object_trade_year": year,
        "first_trade_date": first_date,
        "last_trade_date": last_date,
    }


def upload_one(
    local_path: str | Path,
    remote_path: str,
    config: MinuteColdConfig | None = None,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    cfg = config or build_config()
    command = [cfg.bdpan_bin, "--no-check-update", "upload", str(local_path), remote_path]
    run = runner or (lambda args: subprocess.run(args, check=False, text=True, capture_output=True))
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"bdpan upload failed for {remote_path}: {detail}")


def read_cached_or_downloaded_day(
    day_index: Any,
    *,
    ts_code: str,
    trade_date: str,
    source: str,
    config: MinuteColdConfig | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> list[dict[str, Any]]:
    cfg = config or build_config()
    query = {"source": source, "ts_code": normalize_ts_code(ts_code), "trade_date": normalize_trade_date(trade_date)}
    doc = day_index.find_one(query, {"_id": 0}) or {}
    if not doc:
        return []
    cache_path = cfg.cache_root / str(doc.get("relative_path") or bucket_object_relative_path(doc))
    if not cache_path.exists() or not _file_matches(cache_path, str(doc.get("sha256") or "")):
        ensure_dir(cache_path.parent)
        remote_path = str(doc.get("remote_path") or "")
        if not remote_path:
            return []
        download_one(remote_path, cache_path, cfg, runner=runner)
        if not _file_matches(cache_path, str(doc.get("sha256") or "")):
            cache_path.unlink(missing_ok=True)
            raise RuntimeError(f"分时冷数据校验失败：{remote_path}")
    now = datetime.now(timezone.utc)
    cache_path.touch()
    day_index.update_one(query, {"$set": {"cache.local_path": str(cache_path), "cache.last_accessed_at": now}})
    prune_cache(cfg.cache_root, cfg.cache_max_bytes)
    if doc.get("storage_object") in {"month_jsonl", "stock_jsonl", "stock_year_jsonl"}:
        return read_object_day_rows(cache_path, query["trade_date"])
    return read_jsonl_rows(cache_path)


def download_one(
    remote_path: str,
    local_path: str | Path,
    config: MinuteColdConfig | None = None,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    cfg = config or build_config()
    command = [cfg.bdpan_bin, "--no-check-update", "download", remote_path, str(local_path)]
    run = runner or (lambda args: subprocess.run(args, check=False, text=True, capture_output=True))
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"bdpan download failed for {remote_path}: {detail}")


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_month_day_rows(path: Path, trade_date: str) -> list[dict[str, Any]]:
    return read_object_day_rows(path, trade_date)


def read_object_day_rows(path: Path, trade_date: str) -> list[dict[str, Any]]:
    target = normalize_trade_date(trade_date)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if str(item.get("trade_date") or "") == target:
                rows = item.get("rows")
                return rows if isinstance(rows, list) else []
    return []


def latest_indexed_days(day_index: Any, *, ts_code: str, source: str, limit: int) -> list[dict[str, Any]]:
    return list(
        day_index.find({"source": source, "ts_code": normalize_ts_code(ts_code)}, {"_id": 0})
        .sort([("trade_date", -1)])
        .limit(max(1, int(limit)))
    )


def prune_cache(root: Path, max_bytes: int) -> dict[str, Any]:
    if max_bytes <= 0 or not root.exists():
        return {"removed": 0, "bytes_removed": 0, "bytes_remaining": 0}
    files = [path for path in root.rglob("*.jsonl") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    removed = 0
    bytes_removed = 0
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
        bytes_removed += size
        total -= size
    _remove_empty_dirs(root)
    return {"removed": removed, "bytes_removed": bytes_removed, "bytes_remaining": total}


def normalize_trade_date(value: str) -> str:
    text = str(value or "").replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"交易日格式应为 YYYYMMDD：{value}")
    return text


def normalize_trade_month(value: str) -> str:
    text = str(value or "").replace("-", "").strip()
    if len(text) != 6 or not text.isdigit():
        raise ValueError(f"交易月份格式应为 YYYYMM：{value}")
    return text


def normalize_trade_year(value: str) -> str:
    text = str(value or "").strip()
    if len(text) != 4 or not text.isdigit():
        raise ValueError(f"交易年份格式应为 YYYY：{value}")
    return text


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percent(position: int, total: int) -> str:
    if total <= 0:
        return "100.0%"
    return f"{min(100.0, position / total * 100):.1f}%"


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_matches(path: Path, digest: str) -> bool:
    return path.exists() and (not digest or _sha256_file(path) == digest)


def _remove_empty_dirs(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
