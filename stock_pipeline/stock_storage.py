from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .collector import StockDataCollector
from .analysis_frameworks import ANALYSIS_FRAMEWORKS, build_all_analysis_dossiers, build_analysis_dossier, get_analysis_framework, list_analysis_frameworks
from .config import PROJECT_ROOT
from .daily_k_coverage import ensure_indexes as ensure_daily_k_coverage_indexes
from .daily_k_coverage import normalize_trade_date
from .daily_k_coverage import refresh_daily_k_coverage
from .dossier import build_dossier
from .field_labels import build_table_datasets
from .local_data_mongo import (
    _client as mongo_client,
    list_mongo_stock_codes,
    list_mongo_stock_metadata,
    read_mongo_analysis_dossier,
    read_mongo_dossier,
    read_mongo_full_data,
    read_mongo_metadata,
    save_stock_package_to_mongo,
    sync_current_stock_to_mongo,
)
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE, STOCK_COLLECTIONS, STOCK_DATABASE
from .minute_storage import minute_reference_row_counts, read_external_minute_datasets
from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, today_yyyymmdd, write_json


LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
MIN_REQUIRED_DATASETS = ("stock_basic", "daily", "daily_basic")
DAILY_MARKET_DATASETS = ("daily", "weekly", "monthly", "daily_basic", "adj_factor", "stk_limit", "suspend_d", "moneyflow", "margin_detail")
DAILY_QUOTE_REQUIRED_FIELDS = ("open", "high", "low", "close", "vol", "amount")
DAILY_BASIC_REQUIRED_ANY_FIELDS = ("turnover_rate", "pe", "pe_ttm", "pb", "total_mv", "circ_mv")
TaskCheckpoint = Callable[[dict[str, Any]], None]


def stock_dir(ts_code: str) -> Path:
    return LOCAL_DATA_DIR / normalize_ts_code(ts_code)


def current_dir(ts_code: str) -> Path:
    return stock_dir(ts_code) / "current"


def snapshots_dir(ts_code: str) -> Path:
    return stock_dir(ts_code) / "snapshots"


def read_current_full_data(ts_code: str) -> dict[str, Any]:
    code = normalize_ts_code(ts_code)
    ensure_current_layout(code)
    full_path = current_dir(code) / "full_data.json"
    if full_path.exists():
        return read_json(full_path)
    full_data = read_mongo_full_data(code)
    if full_data is not None:
        return full_data
    raise FileNotFoundError(f"本地和 MongoDB 都没有 {code} 的数据，请先更新数据。")


def read_current_metadata(ts_code: str) -> dict[str, Any]:
    code = normalize_ts_code(ts_code)
    metadata_path = stock_dir(code) / "metadata.json"
    if metadata_path.exists():
        return read_json(metadata_path)
    return read_mongo_metadata(code) or {}


def read_current_dossier(ts_code: str) -> dict[str, Any]:
    code = normalize_ts_code(ts_code)
    dossier_path = current_dir(code) / "dossier.json"
    if dossier_path.exists():
        return read_json(dossier_path)
    mongo_dossier = read_mongo_dossier(code)
    if mongo_dossier is not None:
        return mongo_dossier
    return build_dossier(read_current_full_data(code))


def read_current_analysis_dossier(ts_code: str, analysis_type: str) -> dict[str, Any]:
    code = normalize_ts_code(ts_code)
    framework = get_analysis_framework(analysis_type)
    path = current_dir(code) / f"{framework.key}_dossier.json"
    if path.exists():
        return read_json(path)
    if framework.key == "value_speculation":
        legacy = current_dir(code) / "value_speculation_dossier.json"
        if legacy.exists():
            return read_json(legacy)
    mongo_dossier = read_mongo_analysis_dossier(code, framework.key)
    if mongo_dossier is not None:
        return mongo_dossier
    return build_analysis_dossier(framework.key, read_current_dossier(code))


def stock_exists(ts_code: str) -> bool:
    ensure_current_layout(ts_code)
    return (current_dir(ts_code) / "full_data.json").exists() or read_mongo_full_data(ts_code) is not None


def list_local_stock_codes() -> list[str]:
    mongo_codes = set(list_mongo_stock_codes())
    return sorted(set(_local_file_stock_codes()) | mongo_codes)


def _local_file_stock_codes() -> list[str]:
    if not LOCAL_DATA_DIR.exists():
        return []
    codes: list[str] = []
    for path in sorted(LOCAL_DATA_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            ts_code = normalize_ts_code(path.name)
        except ValueError:
            continue
        if (current_dir(ts_code) / "full_data.json").exists() or (path / "full_data.json").exists():
            ensure_current_layout(ts_code)
            codes.append(ts_code)
    return sorted(set(codes))


def list_local_stock_summaries() -> dict[str, Any]:
    mongo_metadata = list_mongo_stock_metadata()
    items: list[dict[str, Any]] = []
    for ts_code in sorted(set(_local_file_stock_codes()) | set(mongo_metadata)):
        base_dir = stock_dir(ts_code)
        metadata_path = base_dir / "metadata.json"
        metadata = read_json(metadata_path) if metadata_path.exists() else (mongo_metadata.get(ts_code) or {})
        stock_basic = metadata.get("stock_basic") or {}
        dataset_rows = metadata.get("dataset_rows") or {}
        date_range = metadata.get("date_range") or {}
        daily_date_range = metadata.get("daily_date_range") or date_range
        minute_rows = sum(
            int(count or 0)
            for name, count in dataset_rows.items()
            if "minute" in str(name).lower()
        )
        items.append(
            {
                "ts_code": ts_code,
                "name": stock_basic.get("name") or stock_basic.get("fullname") or metadata.get("name") or "",
                "industry": stock_basic.get("industry") or "",
                "market": stock_basic.get("market") or stock_basic.get("exchange") or "",
                "updated_at": metadata.get("updated_at") or "",
                "daily_market_updated_at": metadata.get("daily_market_updated_at") or "",
                "latest_daily_date": metadata.get("latest_daily_date") or "",
                "date_range": date_range,
                "daily_date_range": daily_date_range,
                "dataset_count": len(dataset_rows),
                "dataset_rows": dataset_rows,
                "minute_rows": minute_rows,
                "fetch_error_count": len(metadata.get("fetch_errors") or []),
                "snapshot_count": len(metadata.get("snapshots") or []),
                "local_dir": str(current_dir(ts_code)),
            }
        )
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    total_dataset_rows = sum(
        sum(int(count or 0) for count in item.get("dataset_rows", {}).values())
        for item in items
    )
    return {
        "items": items,
        "count": len(items),
        "total_dataset_rows": total_dataset_rows,
        "total_minute_rows": sum(int(item.get("minute_rows") or 0) for item in items),
    }


def stock_storage_status_snapshot(
    limit: int = 500,
    query: str = "",
    *,
    page: int = 1,
    page_size: int | None = None,
    filter_key: str = "all",
    sort_key: str = "health",
    codes: list[str] | None = None,
) -> dict[str, Any]:
    summary = list_local_stock_summaries()
    search = str(query or "").strip().lower()
    code_filter = {normalize_ts_code(code) for code in (codes or []) if str(code or "").strip()} if codes else set()
    items = [
        item for item in summary.get("items", [])
        if not search
        or any(str(item.get(key) or "").lower().find(search) >= 0 for key in ("ts_code", "name", "industry", "market"))
    ]
    if code_filter:
        items = [item for item in items if str(item.get("ts_code") or "") in code_filter]
    daily_coverage = _daily_coverage_by_code()
    minute_coverage = _minute_coverage_by_code()
    minute_upload = _minute_upload_by_code()

    enriched = [
        _stock_storage_status_item(item, daily_coverage.get(str(item.get("ts_code") or "")) or {}, minute_coverage.get(str(item.get("ts_code") or "")) or {}, minute_upload.get(str(item.get("ts_code") or "")) or {})
        for item in items
    ]
    enriched = [item for item in enriched if _stock_storage_matches_filter(item, filter_key)]
    enriched.sort(key=lambda item: _stock_storage_sort_key(item, sort_key))
    selected_page = max(1, int(page or 1))
    selected_page_size = max(1, min(200, int(page_size if page_size is not None else limit or 500)))
    filtered_total = len(enriched)
    page_count = max(1, (filtered_total + selected_page_size - 1) // selected_page_size)
    selected_page = min(selected_page, page_count)
    start = (selected_page - 1) * selected_page_size
    page_items = enriched[start : start + selected_page_size]
    status_counts: dict[str, int] = {}
    for item in enriched:
        status = str(item.get("health_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "items": page_items,
        "count": len(page_items),
        "total": summary.get("count", 0),
        "filtered_total": filtered_total,
        "page": selected_page,
        "page_size": selected_page_size,
        "page_count": page_count,
        "filter": filter_key,
        "sort": sort_key,
        "summary": {
            "stock_count": summary.get("count", 0),
            "visible_count": filtered_total,
            "dataset_rows": summary.get("total_dataset_rows", 0),
            "minute_rows": summary.get("total_minute_rows", 0),
            "cold_uploaded_days": sum(int((item.get("cold_backup") or {}).get("uploaded_days") or 0) for item in enriched),
            "cold_uploaded_bytes": sum(int((item.get("cold_backup") or {}).get("uploaded_bytes") or 0) for item in enriched),
            "health": status_counts,
        },
    }


def _stock_storage_matches_filter(item: dict[str, Any], filter_key: str) -> bool:
    if not filter_key or filter_key == "all":
        return True
    hot = item.get("hot_storage") if isinstance(item.get("hot_storage"), dict) else {}
    cold = item.get("cold_backup") if isinstance(item.get("cold_backup"), dict) else {}
    daily = item.get("daily_coverage") if isinstance(item.get("daily_coverage"), dict) else {}
    minute = item.get("minute_coverage") if isinstance(item.get("minute_coverage"), dict) else {}
    daily_missing = int(daily.get("missing_days") or 0) + int(daily.get("partial_days") or 0)
    minute_missing = (int(minute.get("missing_days") or 0) if minute.get("missing_days") is not None else 0) + int(minute.get("partial_days") or 0)
    cold_indexed_days = int(cold.get("indexed_days") or 0)
    cold_uploaded_days = int(cold.get("uploaded_days") or 0)
    if filter_key == "daily_missing":
        return daily_missing > 0 or int(hot.get("daily_rows") or 0) == 0
    if filter_key == "minute_missing":
        return minute_missing > 0
    if filter_key == "cold_pending":
        return cold_indexed_days > 0 and cold_uploaded_days < cold_indexed_days
    if filter_key == "health_attention":
        return str(item.get("health_status") or "") != "ok"
    return True


def _stock_storage_sort_key(item: dict[str, Any], sort_key: str) -> tuple[Any, ...]:
    if sort_key == "ts_code":
        return (str(item.get("ts_code") or ""),)
    if sort_key == "updated_at":
        return (_invert_text(str(item.get("updated_at") or "")), str(item.get("ts_code") or ""))
    if sort_key == "cold_uploaded_days":
        return (-int((item.get("cold_backup") or {}).get("uploaded_days") or 0), str(item.get("ts_code") or ""))
    if sort_key == "dataset_rows":
        return (-int((item.get("hot_storage") or {}).get("dataset_rows") or 0), str(item.get("ts_code") or ""))
    weight = {"danger": 0, "warning": 1, "unknown": 2, "ok": 3}
    return (weight.get(str(item.get("health_status") or "unknown"), 2), str(item.get("ts_code") or ""))


def _invert_text(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def stock_status(code: str) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    base_dir = stock_dir(ts_code)
    metadata_path = base_dir / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else (read_mongo_metadata(ts_code) or {})
    if not metadata:
        return {
            "ok": True,
            "ts_code": ts_code,
            "exists": False,
            "local_dir": str(current_dir(ts_code)),
            "stock_dir": str(base_dir),
            "updated_at": None,
            "age_seconds": None,
            "age_text": "本地还没有更新过",
            "metadata": {},
        }
    updated_at = metadata.get("updated_at")
    age_seconds = _age_seconds(updated_at)
    return {
        "ok": True,
        "ts_code": ts_code,
        "exists": True,
        "local_dir": str(current_dir(ts_code)),
        "stock_dir": str(base_dir),
        "updated_at": updated_at,
        "age_seconds": age_seconds,
        "age_text": _age_text(age_seconds),
        "metadata": metadata,
    }


def sync_stock_data(
    client: TushareClient,
    code: str,
    years: int | None = None,
    full_history: bool = True,
    force: bool = False,
    max_age_seconds: int | None = None,
    checkpoint: TaskCheckpoint | None = None,
) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    target_dir = current_dir(ts_code)
    if not force and max_age_seconds is not None and stock_exists(ts_code):
        status = stock_status(ts_code)
        age = status.get("age_seconds")
        if isinstance(age, int) and age <= max_age_seconds:
            payload = build_local_stock_payload(ts_code)
            payload["cache_hit"] = True
            payload["cache_age_seconds"] = age
            payload["cache_max_age_seconds"] = max_age_seconds
            return payload

    existing_external_datasets: dict[str, Any] = (read_mongo_full_data(ts_code) or {}).get("external_datasets") or {}
    if not existing_external_datasets and (target_dir / "full_data.json").exists():
        existing_external_datasets = read_json(target_dir / "full_data.json").get("external_datasets") or {}
    with tempfile.TemporaryDirectory(prefix=f"{ts_code}.", suffix=".stock_collect") as temp_name:
        temp_dir = Path(temp_name)
        _run_checkpoint(checkpoint, stage="before_collect", ts_code=ts_code)
        full_data = StockDataCollector(client).collect(ts_code, temp_dir, years=years, full_history=full_history)
        _run_checkpoint(checkpoint, stage="before_validate", ts_code=ts_code)
        if existing_external_datasets:
            full_data["external_datasets"] = existing_external_datasets
        _validate_full_data(full_data)
        dossier = build_dossier(full_data)
        analysis_dossiers = _build_optional_analysis_dossiers(dossier)

        updated_at = timestamp()
        metadata = {
            "ts_code": ts_code,
            "years": years,
            "full_history": full_history,
            "updated_at": updated_at,
            "current_dir": _stock_package_uri(ts_code),
            "latest_snapshot": "",
            "snapshots": [],
            "date_range": full_data.get("date_range", {}),
            "daily_date_range": _daily_date_range(full_data),
            "stock_basic": _stock_identity(full_data),
            "dataset_rows": {
                **{name: len(rows) for name, rows in full_data.get("datasets", {}).items()},
                **minute_reference_row_counts(full_data),
            },
            "fetch_errors": full_data.get("fetch_errors", []),
        }
        _run_checkpoint(checkpoint, stage="before_save", ts_code=ts_code)
        mongo_sync = _save_stock_package_safe(ts_code, full_data, metadata, dossier=dossier, analysis_dossiers=analysis_dossiers)
    payload = build_local_stock_payload(ts_code)
    payload["cache_hit"] = False
    payload["cache_max_age_seconds"] = max_age_seconds
    payload["mongo_sync"] = mongo_sync
    return payload


def sync_daily_market_for_existing_stocks(
    client: TushareClient,
    target_date: str | None = None,
    codes: list[str] | None = None,
    checkpoint: TaskCheckpoint | None = None,
    resume_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    date = target_date or today_yyyymmdd()
    selected = [normalize_ts_code(code) for code in (codes or list_local_stock_codes())]
    resume_details = resume_checkpoint.get("details") if isinstance(resume_checkpoint, dict) else {}
    resume_stage = str(resume_details.get("stage") or "")
    start_index = 1
    skip_stock_loop = False
    if resume_stage == "before_stock":
        try:
            start_index = max(1, int(resume_details.get("current") or 1))
        except (TypeError, ValueError):
            start_index = 1
    elif resume_stage == "before_coverage_refresh":
        start_index = len(selected) + 1
        skip_stock_loop = True
    result = {
        "ok": True,
        "target_date": date,
        "total": len(selected),
        "updated": 0,
        "skipped": 0,
        "no_data": 0,
        "failed": 0,
        "items": [],
    }
    if resume_checkpoint:
        result["resumed"] = True
        result["resume_stage"] = resume_stage or str(resume_checkpoint.get("stage") or "")
        result["resume_start_index"] = start_index
    for index, ts_code in enumerate(selected, start=1):
        if index < start_index or skip_stock_loop:
            continue
        _run_checkpoint(checkpoint, stage="before_stock", ts_code=ts_code, current=index, total=len(selected), target_date=date)
        try:
            item = sync_daily_market_for_stock(client, ts_code, date)
        except Exception as exc:  # noqa: BLE001 - keep batch going
            item = {"ok": False, "ts_code": ts_code, "status": "failed", "error": str(exc)}
        status = item.get("status")
        if status == "updated":
            result["updated"] += 1
        elif status == "skipped":
            result["skipped"] += 1
        elif status == "no_data":
            result["no_data"] += 1
        else:
            result["failed"] += 1
        result["items"].append(item)
    _run_checkpoint(checkpoint, stage="before_coverage_refresh", current=len(selected), total=len(selected), target_date=date)
    result["daily_coverage"] = _refresh_daily_k_coverage_safe(selected, date)
    return result


def choose_daily_market_target(
    codes: list[str] | None = None,
    *,
    end_date: str | None = None,
    lookback_dates: int = 20,
    min_complete_ratio: float = 0.95,
) -> dict[str, Any]:
    """Pick the newest recent trade date that still needs daily K backfill."""
    target_limit = normalize_trade_date(str(end_date or "")) or today_yyyymmdd()
    selected = [normalize_ts_code(code) for code in (codes or list_local_stock_codes())]
    try:
        with mongo_client(STOCK_DATABASE) as client:
            rows = client[STOCK_DATABASE][STOCK_COLLECTIONS["rows"]]
            recent_dates = _recent_daily_trade_dates(rows, target_limit, lookback_dates)
            if not recent_dates:
                return {
                    "target_date": target_limit,
                    "reason": "no_recent_trade_reference",
                    "expected_stocks": len(selected),
                    "threshold": 0,
                    "date_counts": {},
                }
            counts = _daily_stock_counts_by_date(rows, recent_dates, selected)
    except Exception as exc:  # noqa: BLE001 - scheduler should keep running with a safe fallback
        return {
            "target_date": target_limit,
            "reason": "fallback_after_target_selection_error",
            "error": str(exc),
            "expected_stocks": len(selected),
            "threshold": 0,
            "date_counts": {},
        }

    expected = len(selected) or max(counts.values(), default=0)
    threshold = max(1, int(expected * min(1.0, max(0.0, min_complete_ratio)))) if expected else 0
    for trade_date in recent_dates:
        if threshold and int(counts.get(trade_date) or 0) < threshold:
            return {
                "target_date": trade_date,
                "reason": "incomplete_recent_trade_date",
                "expected_stocks": expected,
                "threshold": threshold,
                "date_counts": counts,
            }
    return {
        "target_date": recent_dates[0],
        "reason": "latest_recent_trade_date_complete_enough",
        "expected_stocks": expected,
        "threshold": threshold,
        "date_counts": counts,
    }


def _recent_daily_trade_dates(rows: Any, end_date: str, limit: int) -> list[str]:
    query = {"snapshot": "current", "dataset": "daily", "trade_date": {"$lte": end_date}}
    scan_limit = max(1000, max(1, int(limit)) * 2000)
    dates: list[str] = []
    seen: set[str] = set()
    cursor = rows.find(query, {"_id": 0, "trade_date": 1}).sort([("trade_date", -1)]).limit(scan_limit)
    for doc in cursor:
        trade_date = normalize_trade_date(str(doc.get("trade_date") or ""))
        if not trade_date or trade_date in seen:
            continue
        seen.add(trade_date)
        dates.append(trade_date)
        if len(dates) >= limit:
            break
    return dates


def _daily_stock_counts_by_date(rows: Any, dates: list[str], codes: list[str]) -> dict[str, int]:
    if not dates:
        return {}
    match: dict[str, Any] = {"snapshot": "current", "dataset": "daily", "trade_date": {"$in": dates}}
    if codes:
        match["ts_code"] = {"$in": codes}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"trade_date": "$trade_date", "ts_code": "$ts_code"}}},
        {"$group": {"_id": "$_id.trade_date", "stocks": {"$sum": 1}}},
    ]
    result = {date: 0 for date in dates}
    for doc in rows.aggregate(pipeline, allowDiskUse=True):
        trade_date = normalize_trade_date(str(doc.get("_id") or ""))
        if trade_date:
            result[trade_date] = int(doc.get("stocks") or 0)
    return result


def _run_checkpoint(checkpoint: TaskCheckpoint | None, **details: Any) -> None:
    if checkpoint is not None:
        checkpoint(details)


def sync_daily_market_for_stock(client: TushareClient, code: str, target_date: str | None = None) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    date = target_date or today_yyyymmdd()
    try:
        full_data = read_current_full_data(ts_code)
    except FileNotFoundError:
        return {"ok": False, "ts_code": ts_code, "target_date": date, "status": "failed", "error": "本地和 MongoDB 都不存在资料包，请先全量更新。"}
    datasets = full_data.setdefault("datasets", {})
    current_daily = datasets.get("daily", [])
    latest_daily_date = _latest_trade_date(current_daily)
    quality_reasons = _daily_market_refresh_reasons(datasets, date)
    if _has_trade_date(current_daily, date) and not quality_reasons:
        return {
            "ok": True,
            "ts_code": ts_code,
            "target_date": date,
            "status": "skipped",
            "reason": "target_date_exists",
            "latest_daily_date": latest_daily_date,
        }

    raw_updates: dict[str, list[dict[str, Any]]] = {}
    fetch_errors: list[dict[str, str]] = []
    for dataset in DAILY_MARKET_DATASETS:
        try:
            query = client.query(dataset, {"ts_code": ts_code, "start_date": date, "end_date": date})
            raw_updates[dataset] = query.records
        except Exception as exc:  # noqa: BLE001 - one endpoint should not kill whole stock
            fetch_errors.append({"api_name": dataset, "error": str(exc)})

    daily_rows = raw_updates.get("daily", [])
    if not daily_rows:
        if _has_trade_date(current_daily, date):
            return {
                "ok": True,
                "ts_code": ts_code,
                "target_date": date,
                "status": "skipped",
                "reason": "target_date_exists_refresh_no_data",
                "quality_reasons": quality_reasons,
                "latest_daily_date": latest_daily_date,
                "fetch_errors": fetch_errors,
            }
        return {
            "ok": True,
            "ts_code": ts_code,
            "target_date": date,
            "status": "no_data",
            "reason": "daily_empty",
            "latest_daily_date": latest_daily_date,
            "fetch_errors": fetch_errors,
        }

    changed: dict[str, int] = {}
    for dataset, rows in raw_updates.items():
        if not rows:
            continue
        merged = _merge_trade_date_rows(datasets.get(dataset, []), rows)
        datasets[dataset] = merged
        changed[dataset] = len(rows)

    full_data["date_range"] = {
        **(full_data.get("date_range") or {}),
        "end_date": max(str((full_data.get("date_range") or {}).get("end_date") or ""), date),
        "full_history": bool((full_data.get("date_range") or {}).get("full_history", True)),
    }
    full_data["fetch_errors"] = fetch_errors
    dossier = build_dossier(full_data)
    analysis_dossiers = _build_optional_analysis_dossiers(dossier)
    metadata = read_current_metadata(ts_code) or {"ts_code": ts_code}
    metadata.update(
        {
            "ts_code": ts_code,
            "updated_at": timestamp(),
            "current_dir": _stock_package_uri(ts_code),
            "snapshots": [],
            "date_range": full_data.get("date_range", {}),
            "daily_date_range": _daily_date_range(full_data),
            "stock_basic": _stock_identity(full_data),
            "dataset_rows": {
                **{name: len(rows) for name, rows in datasets.items()},
                **minute_reference_row_counts(full_data),
            },
            "fetch_errors": fetch_errors,
            "daily_market_updated_at": timestamp(),
            "daily_market_target_date": date,
            "latest_daily_date": _latest_trade_date(datasets.get("daily", [])),
        }
    )
    mongo_sync = _save_stock_package_safe(ts_code, full_data, metadata, dossier=dossier, analysis_dossiers=analysis_dossiers)
    return {
        "ok": True,
        "ts_code": ts_code,
        "target_date": date,
        "status": "updated",
        "latest_daily_date": metadata["latest_daily_date"],
        "changed": changed,
        "quality_reasons": quality_reasons,
        "fetch_errors": fetch_errors,
        "mongo_sync": mongo_sync,
    }


def build_local_stock_payload(code: str) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    base_dir = stock_dir(ts_code)
    target_dir = current_dir(ts_code)
    full_path = target_dir / "full_data.json"
    full_data = read_current_full_data(ts_code)
    metadata = read_current_metadata(ts_code)
    table_datasets = build_table_datasets(full_data.get("datasets", {}))
    external_rows = read_external_minute_datasets(full_data, limit=4000)
    external_counts = minute_reference_row_counts(full_data)
    for item in build_table_datasets(external_rows):
        reference = (full_data.get("external_datasets") or {}).get(item["key"]) or {}
        item["row_count"] = external_counts.get(item["key"], len(item["records"]))
        item["loaded_row_count"] = len(item["records"])
        item["storage"] = "baidu_netdisk_cold_archive"
        item["hot_row_count"] = int(reference.get("hot_row_count") or 0)
        item["archived_row_count"] = int(reference.get("archived_row_count") or 0)
        item["archived_days"] = int(reference.get("archived_days") or 0)
        item["hot_days"] = int(reference.get("hot_days") or 15)
        table_datasets.append(item)
    table_datasets.sort(key=lambda item: (item["row_count"] == 0, item["label"]))
    return {
        "ok": True,
        "ts_code": ts_code,
        "local_dir": str(target_dir),
        "stock_dir": str(base_dir),
        "full_data_path": str(target_dir / "full_data.json"),
        "dossier_path": str(target_dir / "dossier.json"),
        "value_dossier_path": str(target_dir / "value_speculation_dossier.json"),
        "analysis_frameworks": list_analysis_frameworks(),
        "analysis_results": list_analysis_results(ts_code),
        "metadata": metadata,
        "storage_source": "local_file" if full_path.exists() else "mongodb",
        "date_range": full_data.get("date_range", {}),
        "datasets": table_datasets,
        "fetch_errors": full_data.get("fetch_errors", []),
    }


def _write_stock_outputs(ts_code: str, full_data: dict[str, Any]) -> None:
    dossier = build_dossier(full_data)
    analysis_dossiers = _build_optional_analysis_dossiers(dossier)
    metadata = read_current_metadata(ts_code) or {"ts_code": normalize_ts_code(ts_code)}
    _save_stock_package_safe(ts_code, full_data, metadata, dossier=dossier, analysis_dossiers=analysis_dossiers)


def _stock_package_uri(ts_code: str) -> str:
    return f"mongodb://{STOCK_DATABASE}/{STOCK_COLLECTIONS['packages']}/{normalize_ts_code(ts_code)}/current"


def _build_optional_analysis_dossiers(dossier: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        return build_all_analysis_dossiers(dossier)
    except (ImportError, RuntimeError, ModuleNotFoundError):
        return {}


def _sync_current_stock_to_mongo_safe(ts_code: str) -> dict[str, Any]:
    try:
        return {"ok": True, **sync_current_stock_to_mongo(ts_code)}
    except Exception as exc:  # noqa: BLE001 - local files remain the source of truth if MongoDB is unavailable.
        return {"ok": False, "error": str(exc)}


def _save_stock_package_safe(
    ts_code: str,
    full_data: dict[str, Any],
    metadata: dict[str, Any],
    *,
    dossier: dict[str, Any] | None = None,
    analysis_dossiers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            **save_stock_package_to_mongo(
                ts_code,
                full_data,
                metadata,
                dossier=dossier,
                analysis_dossiers=analysis_dossiers,
            ),
        }
    except Exception as exc:  # noqa: BLE001 - surface Mongo failures without losing the main error context.
        return {"ok": False, "error": str(exc)}


def _refresh_daily_k_coverage_safe(codes: list[str], target_date: str) -> dict[str, Any]:
    if not codes:
        return {"ok": True, "stocks_checked": 0, "missing_days": 0}
    try:
        import pymongo
    except ImportError as exc:
        return {"ok": False, "error": f"缺少 pymongo，无法刷新日K覆盖：{exc}"}
    try:
        with mongo_client(STOCK_DATABASE) as client:
            db = client[STOCK_DATABASE]
            coverage = db[STOCK_COLLECTIONS["daily_coverage"]]
            ensure_daily_k_coverage_indexes(coverage, pymongo)
            result = refresh_daily_k_coverage(
                db[STOCK_COLLECTIONS["rows"]],
                db[STOCK_COLLECTIONS["metadata"]],
                coverage,
                codes=codes,
                end_date=target_date,
            )
            return {key: value for key, value in result.items() if key != "items"} | {"item_count": len(result.get("items") or [])}
    except Exception as exc:  # noqa: BLE001 - daily quotes should survive coverage bookkeeping failures.
        return {"ok": False, "error": str(exc)}


def _daily_date_range(full_data: dict[str, Any]) -> dict[str, str]:
    datasets = full_data.get("datasets") if isinstance(full_data.get("datasets"), dict) else {}
    rows = datasets.get("daily") if isinstance(datasets, dict) else []
    dates = sorted(str(row.get("trade_date") or "") for row in rows if isinstance(row, dict) and row.get("trade_date"))
    return {"start_date": dates[0], "end_date": dates[-1]} if dates else {}


def _latest_trade_date(records: list[dict[str, Any]]) -> str:
    dates = [str(row.get("trade_date") or "") for row in records if row.get("trade_date")]
    return max(dates) if dates else ""


def _has_trade_date(records: list[dict[str, Any]], trade_date: str) -> bool:
    return any(str(row.get("trade_date") or "") == trade_date for row in records if isinstance(row, dict))


def _daily_market_refresh_reasons(datasets: dict[str, Any], trade_date: str) -> list[str]:
    reasons: list[str] = []
    daily_row = _trade_date_row(datasets.get("daily", []), trade_date)
    if not daily_row:
        reasons.append("daily_missing")
    elif _daily_quote_row_needs_refresh(daily_row):
        reasons.append("daily_low_quality")

    daily_basic = _trade_date_row(datasets.get("daily_basic", []), trade_date)
    if not daily_basic:
        reasons.append("daily_basic_missing")
    elif _daily_basic_row_needs_refresh(daily_basic):
        reasons.append("daily_basic_low_quality")

    for dataset in ("adj_factor", "stk_limit"):
        if not _trade_date_row(datasets.get(dataset, []), trade_date):
            reasons.append(f"{dataset}_missing")
    return reasons


def _trade_date_row(records: Any, trade_date: str) -> dict[str, Any]:
    if not isinstance(records, list):
        return {}
    for row in records:
        if isinstance(row, dict) and str(row.get("trade_date") or "") == trade_date:
            return row
    return {}


def _daily_quote_row_needs_refresh(row: dict[str, Any]) -> bool:
    if _fallback_source(row):
        return True
    return any(row.get(field) in (None, "") for field in DAILY_QUOTE_REQUIRED_FIELDS)


def _daily_basic_row_needs_refresh(row: dict[str, Any]) -> bool:
    if _fallback_source(row):
        return True
    return not any(row.get(field) not in (None, "") for field in DAILY_BASIC_REQUIRED_ANY_FIELDS)


def _fallback_source(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "").lower()
    return "fallback" in source or source.startswith("tencent_")


def _first_record(records: Any) -> dict[str, Any]:
    if isinstance(records, list) and records and isinstance(records[0], dict):
        return records[0]
    return {}


def _merge_trade_date_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in existing:
        date = str(row.get("trade_date") or "")
        if date:
            merged[date] = row
        else:
            passthrough.append(row)
    for row in incoming:
        date = str(row.get("trade_date") or "")
        if date:
            current = merged.get(date)
            merged[date] = _prefer_market_row(current, row) if current else row
        else:
            passthrough.append(row)
    return sorted(merged.values(), key=lambda row: str(row.get("trade_date") or ""), reverse=True) + passthrough


def _prefer_market_row(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return incoming
    return incoming if _market_row_quality_score(incoming) >= _market_row_quality_score(existing) else existing


def _market_row_quality_score(row: dict[str, Any]) -> tuple[int, int, int]:
    non_empty = sum(1 for value in row.values() if value not in (None, ""))
    source = str(row.get("source") or "").lower()
    source_score = 0
    if "akshare" in source:
        source_score = 3
    elif "eastmoney" in source:
        source_score = 2
    elif "tushare" in source:
        source_score = 1
    elif "fallback" in source or source.startswith("tencent_"):
        source_score = -1
    key_fields = sum(
        1
        for field in ("amount", "turnover_rate", "pe", "pe_ttm", "pb", "total_mv", "circ_mv", "adj_factor", "up_limit", "down_limit")
        if row.get(field) not in (None, "")
    )
    return source_score, key_fields, non_empty


def ensure_current_layout(code: str) -> None:
    ts_code = normalize_ts_code(code)
    base_dir = stock_dir(ts_code)
    if not base_dir.exists():
        return
    cur_dir = current_dir(ts_code)
    legacy_full = base_dir / "full_data.json"
    if cur_dir.exists() or not legacy_full.exists():
        return

    ensure_dir(cur_dir)
    legacy_names = ["raw", "full_data.json", "dossier.json", "value_speculation_dossier.json", "value_speculation.md"]
    legacy_names.extend(f"{key}_dossier.json" for key in ANALYSIS_FRAMEWORKS)
    legacy_names.extend(f"{key}.md" for key in ANALYSIS_FRAMEWORKS)
    for name in dict.fromkeys(legacy_names):
        src = base_dir / name
        if src.exists():
            shutil.move(str(src), str(cur_dir / name))

    metadata_path = base_dir / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {"ts_code": ts_code}
    metadata["current_dir"] = str(cur_dir)
    metadata["snapshots"] = list_snapshots(ts_code)
    write_json(metadata_path, metadata)


def archive_current(code: str, updated_at: str | None = None) -> Path | None:
    ts_code = normalize_ts_code(code)
    cur_dir = current_dir(ts_code)
    if not (cur_dir / "full_data.json").exists():
        return None
    snapshot_name = updated_at or timestamp()
    target = snapshots_dir(ts_code) / snapshot_name
    suffix = 1
    while target.exists():
        suffix += 1
        target = snapshots_dir(ts_code) / f"{snapshot_name}_{suffix}"
    ensure_dir(target.parent)
    shutil.copytree(cur_dir, target)
    return target


def restore_snapshot(code: str, snapshot_name: str) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    source = snapshots_dir(ts_code) / snapshot_name
    if not source.exists():
        raise FileNotFoundError(f"找不到快照：{snapshot_name}")
    cur_dir = current_dir(ts_code)
    if cur_dir.exists():
        shutil.rmtree(cur_dir)
    shutil.copytree(source, cur_dir)

    full_data = read_json(cur_dir / "full_data.json")
    metadata = {
        "ts_code": ts_code,
        "years": None,
        "updated_at": snapshot_name.split("_", 2)[0] + "_" + snapshot_name.split("_", 2)[1] if len(snapshot_name.split("_")) >= 2 else snapshot_name,
        "current_dir": str(cur_dir),
        "restored_from_snapshot": snapshot_name,
        "snapshots": list_snapshots(ts_code),
        "date_range": full_data.get("date_range", {}),
        "stock_basic": _stock_identity(full_data),
        "dataset_rows": {
            **{name: len(rows) for name, rows in full_data.get("datasets", {}).items()},
            **minute_reference_row_counts(full_data),
        },
        "fetch_errors": full_data.get("fetch_errors", []),
    }
    write_json(stock_dir(ts_code) / "metadata.json", metadata)
    payload = build_local_stock_payload(ts_code)
    payload["mongo_sync"] = _sync_current_stock_to_mongo_safe(ts_code)
    return payload


def list_snapshots(code: str) -> list[dict[str, str]]:
    ts_code = normalize_ts_code(code)
    root = snapshots_dir(ts_code)
    if not root.exists():
        return []
    snapshots = []
    for path in sorted(root.iterdir(), reverse=True):
        if path.is_dir():
            snapshots.append({"name": path.name, "path": str(path)})
    return snapshots


def analysis_dossier_path(code: str, analysis_type: str) -> Path:
    ts_code = normalize_ts_code(code)
    framework = get_analysis_framework(analysis_type)
    path = current_dir(ts_code) / f"{framework.key}_dossier.json"
    if path.exists():
        return path
    if framework.key == "value_speculation":
        legacy = current_dir(ts_code) / "value_speculation_dossier.json"
        if legacy.exists():
            return legacy
    dossier_path = current_dir(ts_code) / "dossier.json"
    if dossier_path.exists():
        try:
            write_json(path, build_analysis_dossier(framework.key, read_json(dossier_path)))
            return path
        except (ImportError, RuntimeError, ModuleNotFoundError) as exc:
            raise FileNotFoundError(f"分析项目不可用，无法生成 {framework.label} 资料包。") from exc
    raise FileNotFoundError(f"本地还没有 {framework.label} 资料包，请先更新本地数据。")


def analysis_output_path(code: str, analysis_type: str) -> Path:
    ts_code = normalize_ts_code(code)
    framework = get_analysis_framework(analysis_type)
    return current_dir(ts_code) / f"{framework.key}.md"


def list_analysis_results(code: str, analysis_type: str | None = None) -> list[dict[str, str]]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    frameworks = [get_analysis_framework(analysis_type)] if analysis_type else list(ANALYSIS_FRAMEWORKS.values())
    items: list[dict[str, str]] = []

    current_metadata = read_json(stock_dir(ts_code) / "metadata.json") if (stock_dir(ts_code) / "metadata.json").exists() else {}
    _append_analysis_results(items, current_dir(ts_code), "current", "", current_metadata.get("updated_at", ""), frameworks)

    root = snapshots_dir(ts_code)
    if root.exists():
        for snapshot in sorted(root.iterdir(), reverse=True):
            if snapshot.is_dir():
                _append_analysis_results(items, snapshot, "snapshot", snapshot.name, snapshot.name, frameworks)
    return items


def read_analysis_result(code: str, analysis_type: str, snapshot_name: str = "") -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    framework = get_analysis_framework(analysis_type)
    ensure_current_layout(ts_code)
    source_dir = snapshots_dir(ts_code) / snapshot_name if snapshot_name else current_dir(ts_code)
    if snapshot_name and not source_dir.exists():
        raise FileNotFoundError(f"找不到快照：{snapshot_name}")

    path = source_dir / f"{framework.key}.md"
    if not path.exists() and framework.key == "value_speculation":
        path = source_dir / "value_speculation.md"
    if not path.exists():
        raise FileNotFoundError(f"还没有 {framework.label} 的历史分析结果，请先生成分析。")

    return {
        "ok": True,
        "ts_code": ts_code,
        "analysis_type": framework.key,
        "analysis_label": framework.label,
        "snapshot_name": snapshot_name,
        "analysis_path": str(path),
        "answer": path.read_text(encoding="utf-8"),
        "items": list_analysis_results(ts_code, framework.key),
    }


def analysis_review_context(code: str, analysis_type: str, limit: int = 3, max_chars: int = 9000) -> str:
    ts_code = normalize_ts_code(code)
    if limit <= 0:
        return ""
    pieces: list[str] = []
    used = 0
    for item in list_analysis_results(ts_code, analysis_type)[:limit]:
        raw_path = item.get("analysis_path", "")
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        clipped = text[:remaining]
        used += len(clipped)
        label = "当前旧分析" if item.get("location") == "current" else f"历史快照 {item.get('snapshot_name', '')}"
        pieces.append(
            f"### {label}\n"
            f"- 更新时间：{item.get('updated_at') or '未知'}\n"
            f"- 分析文件：{item.get('analysis_path')}\n\n"
            f"{clipped}"
        )
    if not pieces:
        return ""
    return "\n\n".join(pieces)


def _append_analysis_results(
    items: list[dict[str, str]],
    source_dir: Path,
    location: str,
    snapshot_name: str,
    updated_at: str,
    frameworks: list[Any],
) -> None:
    for framework in frameworks:
        path = source_dir / f"{framework.key}.md"
        if not path.exists() and framework.key == "value_speculation":
            path = source_dir / "value_speculation.md"
        if not path.exists():
            continue
        items.append(
            {
                "analysis_type": framework.key,
                "analysis_label": framework.label,
                "location": location,
                "snapshot_name": snapshot_name,
                "updated_at": updated_at,
                "analysis_path": str(path),
            }
        )


def _metadata_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    return read_json(path).get("updated_at")


def _stock_identity(full_data: dict[str, Any]) -> dict[str, Any]:
    stock_basic = _first_record((full_data.get("datasets") or {}).get("stock_basic", []))
    return {
        "ts_code": stock_basic.get("ts_code") or full_data.get("ts_code") or "",
        "symbol": stock_basic.get("symbol") or "",
        "name": stock_basic.get("name") or "",
        "fullname": stock_basic.get("fullname") or "",
        "industry": stock_basic.get("industry") or "",
        "area": stock_basic.get("area") or "",
        "market": stock_basic.get("market") or stock_basic.get("exchange") or "",
        "list_date": stock_basic.get("list_date") or "",
    }


def _validate_full_data(full_data: dict[str, Any]) -> None:
    datasets = full_data.get("datasets", {})
    if not datasets:
        raise RuntimeError("本次更新没有抓到任何有效数据，已保留原 current。")
    missing = [name for name in MIN_REQUIRED_DATASETS if not datasets.get(name)]
    if missing:
        joined = "、".join(missing)
        raise RuntimeError(f"本次更新缺少关键数据集：{joined}，已保留原 current。")


def _daily_coverage_by_code() -> dict[str, dict[str, Any]]:
    try:
        with mongo_client(STOCK_DATABASE) as client:
            cursor = client[STOCK_DATABASE][STOCK_COLLECTIONS["daily_coverage"]].find(
                {},
                {
                    "_id": 0,
                    "ts_code": 1,
                    "status": 1,
                    "updated_at": 1,
                    "first_expected_date": 1,
                    "last_expected_date": 1,
                    "first_indexed_date": 1,
                    "last_indexed_date": 1,
                    "expected_days": 1,
                    "indexed_days": 1,
                    "missing_days": 1,
                    "tail_missing_days": 1,
                    "internal_missing_days": 1,
                    "missing_samples": 1,
                    "tail_missing_samples": 1,
                    "internal_missing_samples": 1,
                    "partial_days": 1,
                },
            )
            items: dict[str, dict[str, Any]] = {}
            for doc in cursor:
                try:
                    code = normalize_ts_code(str(doc.get("ts_code") or ""))
                except ValueError:
                    continue
                items[code] = _jsonable_doc(doc)
            return items
    except Exception:
        return {}


def _minute_coverage_by_code() -> dict[str, dict[str, Any]]:
    try:
        with mongo_client(MARKET_DATABASE) as client:
            cursor = client[MARKET_DATABASE][MARKET_COLLECTIONS["minute_coverage"]].find(
                {"source": "pytdx_history"},
                {
                    "_id": 0,
                    "ts_code": 1,
                    "source": 1,
                    "has_minute_data": 1,
                    "first_trade_date": 1,
                    "last_trade_date": 1,
                    "archived_days": 1,
                    "archived_rows": 1,
                    "complete_days": 1,
                    "partial_days": 1,
                    "missing_days": 1,
                    "hot_days": 1,
                    "cache_max_bytes": 1,
                    "updated_at": 1,
                },
            )
            items: dict[str, dict[str, Any]] = {}
            for doc in cursor:
                try:
                    code = normalize_ts_code(str(doc.get("ts_code") or ""))
                except ValueError:
                    continue
                items[code] = _jsonable_doc(doc)
            return items
    except Exception:
        return {}


def _minute_upload_by_code() -> dict[str, dict[str, Any]]:
    try:
        with mongo_client(MARKET_DATABASE) as client:
            cursor = client[MARKET_DATABASE][MARKET_COLLECTIONS["minute_day_index"]].aggregate(
                [
                    {"$match": {"source": "pytdx_history"}},
                    {
                        "$group": {
                            "_id": "$ts_code",
                            "indexed_days": {"$sum": 1},
                            "uploaded_days": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, 1, 0]}},
                            "uploaded_rows": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, "$row_count", 0]}},
                            "uploaded_bytes": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, "$size_bytes", 0]}},
                            "last_uploaded_date": {"$max": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, "$trade_date", ""]}},
                        }
                    },
                ],
                allowDiskUse=True,
            )
            items: dict[str, dict[str, Any]] = {}
            for doc in cursor:
                try:
                    code = normalize_ts_code(str(doc.get("_id") or ""))
                except ValueError:
                    continue
                items[code] = {
                    "indexed_days": int(doc.get("indexed_days") or 0),
                    "uploaded_days": int(doc.get("uploaded_days") or 0),
                    "uploaded_rows": int(doc.get("uploaded_rows") or 0),
                    "uploaded_bytes": int(doc.get("uploaded_bytes") or 0),
                    "last_uploaded_date": str(doc.get("last_uploaded_date") or ""),
                }
            return items
    except Exception:
        return {}


def _stock_storage_status_item(
    item: dict[str, Any],
    daily_coverage: dict[str, Any],
    minute_coverage: dict[str, Any],
    minute_upload: dict[str, Any],
) -> dict[str, Any]:
    dataset_rows = item.get("dataset_rows") if isinstance(item.get("dataset_rows"), dict) else {}
    ts_code = str(item.get("ts_code") or "")
    package_age = _age_seconds(str(item.get("updated_at") or ""))
    daily_missing = int(daily_coverage.get("missing_days") or 0)
    daily_partial = int(daily_coverage.get("partial_days") or 0)
    cold_indexed_days = int(minute_upload.get("indexed_days") or minute_coverage.get("archived_days") or 0)
    cold_uploaded_days = int(minute_upload.get("uploaded_days") or 0)
    minute_partial = int(minute_coverage.get("partial_days") or 0)
    minute_missing = int(minute_coverage.get("missing_days") or 0) if minute_coverage.get("missing_days") is not None else 0
    health_status = _storage_health_status(
        package_exists=True,
        daily_missing=daily_missing,
        daily_partial=daily_partial,
        minute_partial=minute_partial,
        minute_missing=minute_missing,
        cold_indexed_days=cold_indexed_days,
        cold_uploaded_days=cold_uploaded_days,
    )
    latest_check = max(
        str(daily_coverage.get("updated_at") or ""),
        str(minute_coverage.get("updated_at") or ""),
    )
    return {
        "ts_code": ts_code,
        "name": item.get("name") or "",
        "industry": item.get("industry") or "",
        "market": item.get("market") or "",
        "updated_at": item.get("updated_at") or "",
        "package_age_seconds": package_age,
        "date_range": item.get("date_range") or {},
        "daily_date_range": item.get("daily_date_range") or {},
        "hot_storage": {
            "package": True,
            "dataset_count": int(item.get("dataset_count") or 0),
            "dataset_rows": sum(int(count or 0) for count in dataset_rows.values()),
            "daily_rows": int(dataset_rows.get("daily") or 0),
            "latest_daily_date": item.get("latest_daily_date") or (item.get("daily_date_range") or {}).get("end_date") or "",
        },
        "cold_backup": {
            "has_minute_data": bool(minute_coverage.get("has_minute_data") or cold_indexed_days),
            "indexed_days": cold_indexed_days,
            "uploaded_days": cold_uploaded_days,
            "uploaded_rows": int(minute_upload.get("uploaded_rows") or minute_coverage.get("archived_rows") or 0),
            "uploaded_bytes": int(minute_upload.get("uploaded_bytes") or 0),
            "last_uploaded_date": minute_upload.get("last_uploaded_date") or minute_coverage.get("last_trade_date") or "",
            "first_trade_date": minute_coverage.get("first_trade_date") or "",
            "last_trade_date": minute_coverage.get("last_trade_date") or "",
        },
        "daily_coverage": daily_coverage,
        "minute_coverage": minute_coverage,
        "last_health_check_at": latest_check,
        "health_status": health_status,
        "health_message": _storage_health_message(health_status, daily_missing, daily_partial, minute_missing, minute_partial, cold_indexed_days, cold_uploaded_days),
    }


def _storage_health_status(
    *,
    package_exists: bool,
    daily_missing: int,
    daily_partial: int,
    minute_partial: int,
    minute_missing: int,
    cold_indexed_days: int,
    cold_uploaded_days: int,
) -> str:
    if not package_exists:
        return "danger"
    if daily_missing or daily_partial or minute_partial or minute_missing:
        return "warning"
    if cold_indexed_days and cold_uploaded_days < cold_indexed_days:
        return "warning"
    return "ok"


def _storage_health_message(
    status: str,
    daily_missing: int,
    daily_partial: int,
    minute_missing: int,
    minute_partial: int,
    cold_indexed_days: int,
    cold_uploaded_days: int,
) -> str:
    if status == "ok":
        return "资料包、日K覆盖和冷备份索引未发现异常。"
    messages = []
    if daily_missing:
        messages.append(f"日K缺口 {daily_missing} 天")
    if daily_partial:
        messages.append(f"日K部分异常 {daily_partial} 天")
    if minute_missing:
        messages.append(f"分时缺口 {minute_missing} 天")
    if minute_partial:
        messages.append(f"分时部分异常 {minute_partial} 天")
    if cold_indexed_days and cold_uploaded_days < cold_indexed_days:
        messages.append(f"冷备份 {cold_uploaded_days}/{cold_indexed_days} 天")
    return "；".join(messages) or "覆盖索引不足，建议执行数据抽检。"


def _jsonable_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable_value(value) for key, value in doc.items()}


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return _jsonable_doc(value)
    if isinstance(value, list):
        return [_jsonable_value(item) for item in value]
    return value


def _age_seconds(updated_at: str | None) -> int | None:
    if not updated_at:
        return None
    try:
        value = datetime.strptime(updated_at, "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return max(0, int((datetime.now() - value).total_seconds()))


def _age_text(seconds: int | None) -> str:
    if seconds is None:
        return "更新时间未知"
    if seconds < 60:
        return f"{seconds} 秒前更新"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前更新"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前更新"
    days = hours // 24
    return f"{days} 天前更新"
