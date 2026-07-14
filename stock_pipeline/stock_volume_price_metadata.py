from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE, STOCK_COLLECTIONS, STOCK_DATABASE
from .ths_minute import _mongo_uri
from .utils import ensure_dir, normalize_ts_code


DEFAULT_MINUTE_SOURCE = "pytdx_history"
DEFAULT_VOLUME_SAMPLE_DAYS = 20
DEFAULT_VOLUME_TOLERANCE = 0.15
DEFAULT_DAILY_SUMMARY_MODE = "coverage"
DEFAULT_MONGO_SOCKET_TIMEOUT_MS = 600000
DAILY_VOLUME_KEYS = ("vol", "volume", "成交量")
MINUTE_VOLUME_KEYS = ("volume", "vol", "成交量")
UNIT_FACTORS = (1.0, 100.0, 0.01)

EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ts_code", "股票代码"),
    ("name", "股票名称"),
    ("industry", "行业"),
    ("market", "市场"),
    ("list_date", "上市日期"),
    ("has_daily_k", "有日K"),
    ("daily_start", "日K开始"),
    ("daily_end", "日K结束"),
    ("daily_days", "日K天数"),
    ("daily_expected_days", "日K预期天数"),
    ("daily_missing_days", "日K缺失天数"),
    ("daily_internal_missing_days", "日K内部缺失"),
    ("daily_tail_missing_days", "日K尾部缺失"),
    ("daily_status", "日K状态"),
    ("has_minute_k", "有分时K"),
    ("minute_start", "分时开始"),
    ("minute_end", "分时结束"),
    ("minute_indexed_days", "分时索引天数"),
    ("minute_complete_days", "分时完整天数"),
    ("minute_partial_days", "分时部分天数"),
    ("minute_uploaded_days", "分时上传天数"),
    ("minute_uploaded_ratio", "分时上传比例"),
    ("minute_rows", "分时行数"),
    ("minute_expected_from_daily_days", "按日K应有分时天数"),
    ("minute_missing_vs_daily_days", "分时较日K缺失"),
    ("minute_extra_vs_daily_days", "分时较日K多出"),
    ("minute_daily_match_status", "分时/日K天数状态"),
    ("volume_checked_days", "成交量抽检天数"),
    ("volume_match_days", "成交量匹配天数"),
    ("volume_mismatch_days", "成交量异常天数"),
    ("volume_unit_factor", "成交量单位因子"),
    ("volume_max_relative_error", "成交量最大误差"),
    ("volume_status", "成交量状态"),
    ("volume_mismatch_samples", "成交量异常样例"),
    ("overall_status", "总体状态"),
    ("notes", "说明"),
)


ProgressFn = Callable[[str], None]


def export_stock_volume_price_metadata(
    output_path: str | Path,
    *,
    output_format: str = "csv",
    codes: list[str] | None = None,
    limit: int | None = None,
    minute_source: str = DEFAULT_MINUTE_SOURCE,
    volume_sample_days: int = DEFAULT_VOLUME_SAMPLE_DAYS,
    volume_tolerance: float = DEFAULT_VOLUME_TOLERANCE,
    daily_summary_mode: str = DEFAULT_DAILY_SUMMARY_MODE,
    mongo_socket_timeout_ms: int = DEFAULT_MONGO_SOCKET_TIMEOUT_MS,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    try:
        from pymongo import MongoClient
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise RuntimeError("缺少 pymongo，无法连接 MongoDB。请在项目虚拟环境或 web 容器内运行。") from exc

    with MongoClient(
        _mongo_uri(STOCK_DATABASE),
        serverSelectionTimeoutMS=8000,
        socketTimeoutMS=max(20000, int(mongo_socket_timeout_ms)),
    ) as client:
        rows = collect_stock_volume_price_metadata(
            client[STOCK_DATABASE],
            client[MARKET_DATABASE],
            codes=codes,
            limit=limit,
            minute_source=minute_source,
            volume_sample_days=volume_sample_days,
            volume_tolerance=volume_tolerance,
            daily_summary_mode=daily_summary_mode,
            progress=progress,
        )
    return write_volume_price_metadata_table(rows, output_path, output_format=output_format)


def collect_stock_volume_price_metadata(
    stock_db: Any,
    market_db: Any,
    *,
    codes: list[str] | None = None,
    limit: int | None = None,
    minute_source: str = DEFAULT_MINUTE_SOURCE,
    volume_sample_days: int = DEFAULT_VOLUME_SAMPLE_DAYS,
    volume_tolerance: float = DEFAULT_VOLUME_TOLERANCE,
    daily_summary_mode: str = DEFAULT_DAILY_SUMMARY_MODE,
    progress: ProgressFn | None = None,
) -> list[dict[str, Any]]:
    requested_codes = _normalize_codes(codes or [])
    code_filter = set(requested_codes)
    mode = _normalize_daily_summary_mode(daily_summary_mode)
    _progress(progress, "加载股票资料包索引")
    metadata_by_code = _load_stock_metadata(stock_db[STOCK_COLLECTIONS["metadata"]], code_filter)
    _progress(progress, "加载日K覆盖索引")
    daily_coverage_by_code = _load_daily_coverage(stock_db[STOCK_COLLECTIONS["daily_coverage"]], code_filter)
    daily_by_code: dict[str, dict[str, Any]] = {}
    if mode == "aggregate":
        _progress(progress, "聚合日K明细表；大库可能需要数分钟")
        daily_by_code = _aggregate_daily_summary(stock_db[STOCK_COLLECTIONS["rows"]], code_filter)
    else:
        _progress(progress, "跳过日K明细全量聚合，使用 stock_daily_coverage")
    _progress(progress, "加载分时覆盖索引")
    minute_coverage_by_code = _load_minute_coverage(market_db[MARKET_COLLECTIONS["minute_coverage"]], code_filter, minute_source)
    _progress(progress, "聚合分时冷备份索引")
    minute_upload_by_code = _aggregate_minute_upload(market_db[MARKET_COLLECTIONS["minute_day_index"]], code_filter, minute_source)
    _progress(progress, "聚合服务器热缓存分时")
    hot_minute_by_code = _aggregate_hot_minute_summary(market_db[MARKET_COLLECTIONS["minute_buckets"]], code_filter, minute_source)

    all_codes = set(requested_codes)
    all_codes.update(metadata_by_code)
    all_codes.update(daily_by_code)
    all_codes.update(daily_coverage_by_code)
    all_codes.update(minute_coverage_by_code)
    all_codes.update(minute_upload_by_code)
    all_codes.update(hot_minute_by_code)
    selected_codes = sorted(all_codes)
    if requested_codes:
        selected_codes = [code for code in requested_codes if code in all_codes]
    if limit is not None:
        selected_codes = selected_codes[: max(0, int(limit))]

    rows: list[dict[str, Any]] = []
    total = len(selected_codes)
    for index, ts_code in enumerate(selected_codes, start=1):
        if progress and (index == 1 or index % 50 == 0 or index == total):
            progress(f"[{index}/{total}] 分析 {ts_code}")
        daily = daily_by_code.get(ts_code, {})
        daily_coverage = daily_coverage_by_code.get(ts_code, {})
        minute_coverage = minute_coverage_by_code.get(ts_code, {})
        minute_upload = minute_upload_by_code.get(ts_code, {})
        hot_minute = hot_minute_by_code.get(ts_code, {})
        minute = _merge_minute_summary(minute_coverage, minute_upload, hot_minute)
        expected_minute_days = _daily_days_in_minute_range(stock_db[STOCK_COLLECTIONS["rows"]], ts_code, minute)
        volume_summary = _volume_sample_summary(
            stock_db[STOCK_COLLECTIONS["rows"]],
            market_db[MARKET_COLLECTIONS["minute_buckets"]],
            ts_code,
            source=minute_source,
            sample_days=volume_sample_days,
            tolerance=volume_tolerance,
        )
        rows.append(
            _build_export_row(
                ts_code,
                metadata_by_code.get(ts_code, {}),
                daily,
                daily_coverage,
                minute,
                expected_minute_days,
                volume_summary,
            )
        )
    return rows


def _progress(progress: ProgressFn | None, message: str) -> None:
    if progress:
        progress(message)


def write_volume_price_metadata_table(rows: list[dict[str, Any]], output_path: str | Path, *, output_format: str = "csv") -> dict[str, Any]:
    target = Path(output_path)
    selected_format = _infer_output_format(target, output_format)
    generated_at = datetime.now(timezone.utc).isoformat()
    if str(output_path) != "-":
        ensure_dir(target.parent)
    if selected_format == "csv":
        _write_csv(rows, target)
    elif selected_format in {"md", "markdown"}:
        _write_markdown(rows, target)
    elif selected_format == "json":
        payload = {"generated_at": generated_at, "count": len(rows), "items": rows}
        _write_text(target, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    else:
        raise ValueError(f"不支持的导出格式：{output_format}")
    return {"ok": True, "path": str(output_path), "format": selected_format, "count": len(rows), "generated_at": generated_at}


def _load_stock_metadata(collection: Any, codes: set[str]) -> dict[str, dict[str, Any]]:
    query: dict[str, Any] = {"ts_code": {"$in": sorted(codes)}} if codes else {}
    result: dict[str, dict[str, Any]] = {}
    for doc in collection.find(query, {"_id": 0, "ts_code": 1, "metadata": 1}):
        try:
            ts_code = normalize_ts_code(str(doc.get("ts_code") or ""))
        except ValueError:
            continue
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        result[ts_code] = metadata
    return result


def _aggregate_daily_summary(rows: Any, codes: set[str]) -> dict[str, dict[str, Any]]:
    match: dict[str, Any] = {"snapshot": "current", "dataset": "daily"}
    if codes:
        match["ts_code"] = {"$in": sorted(codes)}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$ts_code",
                "first_trade_date": {"$min": "$trade_date"},
                "last_trade_date": {"$max": "$trade_date"},
                "days": {"$sum": 1},
                "volume_sum": {"$sum": _mongo_number_expr(_coalesce_expr([f"$row.{key}" for key in DAILY_VOLUME_KEYS]))},
            }
        },
    ]
    result: dict[str, dict[str, Any]] = {}
    for doc in rows.aggregate(pipeline, allowDiskUse=True):
        try:
            ts_code = normalize_ts_code(str(doc.get("_id") or ""))
        except ValueError:
            continue
        result[ts_code] = {
            "first_trade_date": str(doc.get("first_trade_date") or ""),
            "last_trade_date": str(doc.get("last_trade_date") or ""),
            "days": int(doc.get("days") or 0),
            "volume_sum": float(doc.get("volume_sum") or 0),
        }
    return result


def _load_daily_coverage(collection: Any, codes: set[str]) -> dict[str, dict[str, Any]]:
    query: dict[str, Any] = {"ts_code": {"$in": sorted(codes)}} if codes else {}
    projection = {
        "_id": 0,
        "ts_code": 1,
        "status": 1,
        "first_expected_date": 1,
        "last_expected_date": 1,
        "first_indexed_date": 1,
        "last_indexed_date": 1,
        "latest_indexed_date": 1,
        "latest_complete_date": 1,
        "list_date": 1,
        "expected_days": 1,
        "indexed_days": 1,
        "missing_days": 1,
        "tail_missing_days": 1,
        "internal_missing_days": 1,
        "partial_days": 1,
        "updated_at": 1,
    }
    result: dict[str, dict[str, Any]] = {}
    for doc in collection.find(query, projection):
        try:
            ts_code = normalize_ts_code(str(doc.get("ts_code") or ""))
        except ValueError:
            continue
        result[ts_code] = dict(doc)
    return result


def _load_minute_coverage(collection: Any, codes: set[str], source: str) -> dict[str, dict[str, Any]]:
    query: dict[str, Any] = {"source": source}
    if codes:
        query["ts_code"] = {"$in": sorted(codes)}
    result: dict[str, dict[str, Any]] = {}
    for doc in collection.find(query, {"_id": 0}):
        try:
            ts_code = normalize_ts_code(str(doc.get("ts_code") or ""))
        except ValueError:
            continue
        result[ts_code] = dict(doc)
    return result


def _aggregate_minute_upload(day_index: Any, codes: set[str], source: str) -> dict[str, dict[str, Any]]:
    match: dict[str, Any] = {"source": source}
    if codes:
        match["ts_code"] = {"$in": sorted(codes)}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$ts_code",
                "first_trade_date": {"$min": "$trade_date"},
                "last_trade_date": {"$max": "$trade_date"},
                "indexed_days": {"$sum": 1},
                "complete_days": {"$sum": {"$cond": [{"$eq": ["$status", "complete"]}, 1, 0]}},
                "partial_days": {"$sum": {"$cond": [{"$ne": ["$status", "complete"]}, 1, 0]}},
                "rows": {"$sum": "$row_count"},
                "uploaded_days": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, 1, 0]}},
                "uploaded_rows": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, "$row_count", 0]}},
                "uploaded_bytes": {"$sum": {"$cond": [{"$eq": ["$upload_status", "uploaded"]}, "$size_bytes", 0]}},
            }
        },
    ]
    result: dict[str, dict[str, Any]] = {}
    for doc in day_index.aggregate(pipeline, allowDiskUse=True):
        try:
            ts_code = normalize_ts_code(str(doc.get("_id") or ""))
        except ValueError:
            continue
        result[ts_code] = {
            "first_trade_date": str(doc.get("first_trade_date") or ""),
            "last_trade_date": str(doc.get("last_trade_date") or ""),
            "indexed_days": int(doc.get("indexed_days") or 0),
            "complete_days": int(doc.get("complete_days") or 0),
            "partial_days": int(doc.get("partial_days") or 0),
            "rows": int(doc.get("rows") or 0),
            "uploaded_days": int(doc.get("uploaded_days") or 0),
            "uploaded_rows": int(doc.get("uploaded_rows") or 0),
            "uploaded_bytes": int(doc.get("uploaded_bytes") or 0),
        }
    return result


def _aggregate_hot_minute_summary(collection: Any, codes: set[str], source: str) -> dict[str, dict[str, Any]]:
    match: dict[str, Any] = {"source": source}
    if codes:
        match["ts_code"] = {"$in": sorted(codes)}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$ts_code",
                "first_trade_date": {"$min": "$trade_date"},
                "last_trade_date": {"$max": "$trade_date"},
                "days": {"$sum": 1},
                "rows": {"$sum": "$row_count"},
                "complete_days": {"$sum": {"$cond": [{"$gte": ["$row_count", 240]}, 1, 0]}},
                "partial_days": {"$sum": {"$cond": [{"$lt": ["$row_count", 240]}, 1, 0]}},
            }
        },
    ]
    result: dict[str, dict[str, Any]] = {}
    for doc in collection.aggregate(pipeline, allowDiskUse=True):
        try:
            ts_code = normalize_ts_code(str(doc.get("_id") or ""))
        except ValueError:
            continue
        result[ts_code] = {
            "first_trade_date": str(doc.get("first_trade_date") or ""),
            "last_trade_date": str(doc.get("last_trade_date") or ""),
            "days": int(doc.get("days") or 0),
            "rows": int(doc.get("rows") or 0),
            "complete_days": int(doc.get("complete_days") or 0),
            "partial_days": int(doc.get("partial_days") or 0),
        }
    return result


def _merge_minute_summary(coverage: dict[str, Any], upload: dict[str, Any], hot: dict[str, Any]) -> dict[str, Any]:
    indexed_days = int(upload.get("indexed_days") or coverage.get("archived_days") or hot.get("days") or 0)
    first_date = str(upload.get("first_trade_date") or coverage.get("first_trade_date") or hot.get("first_trade_date") or "")
    last_date = str(upload.get("last_trade_date") or coverage.get("last_trade_date") or hot.get("last_trade_date") or "")
    complete_days = int(upload.get("complete_days") or coverage.get("complete_days") or hot.get("complete_days") or 0)
    partial_days = int(upload.get("partial_days") or coverage.get("partial_days") or hot.get("partial_days") or 0)
    rows = int(upload.get("rows") or coverage.get("archived_rows") or hot.get("rows") or 0)
    return {
        "has_minute_data": bool(indexed_days or coverage.get("has_minute_data") or hot.get("days")),
        "first_trade_date": first_date,
        "last_trade_date": last_date,
        "indexed_days": indexed_days,
        "complete_days": complete_days,
        "partial_days": partial_days,
        "rows": rows,
        "uploaded_days": int(upload.get("uploaded_days") or 0),
        "uploaded_rows": int(upload.get("uploaded_rows") or 0),
        "uploaded_bytes": int(upload.get("uploaded_bytes") or 0),
    }


def _daily_days_in_minute_range(rows: Any, ts_code: str, minute: dict[str, Any]) -> int:
    start = str(minute.get("first_trade_date") or "")
    end = str(minute.get("last_trade_date") or "")
    if not start or not end:
        return 0
    return int(
        rows.count_documents(
            {
                "ts_code": ts_code,
                "snapshot": "current",
                "dataset": "daily",
                "trade_date": {"$gte": start, "$lte": end},
            }
        )
    )


def _volume_sample_summary(
    rows: Any,
    minute_buckets: Any,
    ts_code: str,
    *,
    source: str,
    sample_days: int,
    tolerance: float,
) -> dict[str, Any]:
    if sample_days <= 0:
        return _empty_volume_summary("disabled")
    cursor = minute_buckets.find(
        {"source": source, "ts_code": ts_code},
        {"_id": 0, "trade_date": 1, "minutes.volume": 1, "minutes.vol": 1, "minutes.成交量": 1},
    ).sort([("trade_date", -1)]).limit(max(1, int(sample_days)))
    buckets = list(cursor)
    if not buckets:
        return _empty_volume_summary("no_hot_minute_sample")
    dates = [str(item.get("trade_date") or "") for item in buckets if item.get("trade_date")]
    daily_by_date: dict[str, float] = {}
    daily_cursor = rows.find(
        {"ts_code": ts_code, "snapshot": "current", "dataset": "daily", "trade_date": {"$in": dates}},
        {"_id": 0, "trade_date": 1, "row.vol": 1, "row.volume": 1, "row.成交量": 1},
    )
    for doc in daily_cursor:
        value = _first_number(doc.get("row") if isinstance(doc.get("row"), dict) else {}, DAILY_VOLUME_KEYS)
        if value is not None:
            daily_by_date[str(doc.get("trade_date") or "")] = value

    samples = []
    for bucket in buckets:
        trade_date = str(bucket.get("trade_date") or "")
        minute_volume = _minute_bucket_volume(bucket)
        daily_volume = daily_by_date.get(trade_date)
        if daily_volume is None or minute_volume is None:
            continue
        samples.append({"trade_date": trade_date, "daily_volume": daily_volume, "minute_volume": minute_volume})
    return _volume_match_summary(samples, tolerance=tolerance)


def _volume_match_summary(samples: list[dict[str, Any]], *, tolerance: float = DEFAULT_VOLUME_TOLERANCE) -> dict[str, Any]:
    usable = [
        {
            "trade_date": str(item.get("trade_date") or ""),
            "daily_volume": float(item.get("daily_volume") or 0),
            "minute_volume": float(item.get("minute_volume") or 0),
        }
        for item in samples
        if _positive_number(item.get("daily_volume")) and _positive_number(item.get("minute_volume"))
    ]
    if not usable:
        return _empty_volume_summary("no_comparable_days")
    factor_errors = {
        factor: median(_relative_error(item["minute_volume"], item["daily_volume"] * factor) for item in usable)
        for factor in UNIT_FACTORS
    }
    factor = min(factor_errors, key=lambda item: (factor_errors[item], abs(item - 1)))
    checked = []
    for item in usable:
        expected = item["daily_volume"] * factor
        error = _relative_error(item["minute_volume"], expected)
        checked.append({**item, "expected_volume": expected, "relative_error": error})
    mismatches = [item for item in checked if item["relative_error"] > tolerance]
    status = "ok" if not mismatches else "warning"
    return {
        "volume_status": status,
        "volume_checked_days": len(checked),
        "volume_match_days": len(checked) - len(mismatches),
        "volume_mismatch_days": len(mismatches),
        "volume_unit_factor": _format_float(factor),
        "volume_max_relative_error": _format_float(max((item["relative_error"] for item in checked), default=0)),
        "volume_mismatch_samples": "; ".join(_volume_sample_label(item) for item in mismatches[:5]),
    }


def _build_export_row(
    ts_code: str,
    metadata: dict[str, Any],
    daily: dict[str, Any],
    daily_coverage: dict[str, Any],
    minute: dict[str, Any],
    expected_minute_days: int,
    volume: dict[str, Any],
) -> dict[str, Any]:
    stock_basic = metadata.get("stock_basic") if isinstance(metadata.get("stock_basic"), dict) else {}
    daily_days = int(daily.get("days") or daily_coverage.get("indexed_days") or 0)
    daily_expected_days = int(daily_coverage.get("expected_days") or daily_days)
    daily_missing_days = int(daily_coverage.get("missing_days") or 0)
    daily_internal_missing_days = int(daily_coverage.get("internal_missing_days") or 0)
    daily_tail_missing_days = int(daily_coverage.get("tail_missing_days") or 0)
    minute_days = int(minute.get("indexed_days") or 0)
    minute_partial_days = int(minute.get("partial_days") or 0)
    minute_uploaded_days = int(minute.get("uploaded_days") or 0)
    missing_vs_daily = max(0, expected_minute_days - minute_days) if expected_minute_days else 0
    extra_vs_daily = max(0, minute_days - expected_minute_days) if expected_minute_days else 0
    daily_status = _daily_status(daily_days, daily_missing_days, daily_internal_missing_days, daily_tail_missing_days)
    minute_match_status = _minute_match_status(bool(daily_days), bool(minute_days), expected_minute_days, missing_vs_daily, extra_vs_daily, minute_partial_days)
    overall_status, notes = _overall_status(daily_status, minute_match_status, str(volume.get("volume_status") or ""), bool(minute_days))
    return {
        "ts_code": ts_code,
        "name": stock_basic.get("name") or metadata.get("name") or "",
        "industry": stock_basic.get("industry") or "",
        "market": stock_basic.get("market") or stock_basic.get("exchange") or "",
        "list_date": _stock_list_date(metadata, daily_coverage),
        "has_daily_k": _yes_no(bool(daily_days)),
        "daily_start": daily.get("first_trade_date") or daily_coverage.get("first_indexed_date") or "",
        "daily_end": daily.get("last_trade_date") or daily_coverage.get("latest_indexed_date") or daily_coverage.get("last_indexed_date") or "",
        "daily_days": daily_days,
        "daily_expected_days": daily_expected_days,
        "daily_missing_days": daily_missing_days,
        "daily_internal_missing_days": daily_internal_missing_days,
        "daily_tail_missing_days": daily_tail_missing_days,
        "daily_status": daily_status,
        "has_minute_k": _yes_no(bool(minute_days)),
        "minute_start": minute.get("first_trade_date") or "",
        "minute_end": minute.get("last_trade_date") or "",
        "minute_indexed_days": minute_days,
        "minute_complete_days": int(minute.get("complete_days") or 0),
        "minute_partial_days": minute_partial_days,
        "minute_uploaded_days": minute_uploaded_days,
        "minute_uploaded_ratio": _ratio_text(minute_uploaded_days, minute_days),
        "minute_rows": int(minute.get("rows") or 0),
        "minute_expected_from_daily_days": expected_minute_days,
        "minute_missing_vs_daily_days": missing_vs_daily,
        "minute_extra_vs_daily_days": extra_vs_daily,
        "minute_daily_match_status": minute_match_status,
        "volume_checked_days": int(volume.get("volume_checked_days") or 0),
        "volume_match_days": int(volume.get("volume_match_days") or 0),
        "volume_mismatch_days": int(volume.get("volume_mismatch_days") or 0),
        "volume_unit_factor": volume.get("volume_unit_factor") or "",
        "volume_max_relative_error": volume.get("volume_max_relative_error") or "",
        "volume_status": volume.get("volume_status") or "unchecked",
        "volume_mismatch_samples": volume.get("volume_mismatch_samples") or "",
        "overall_status": overall_status,
        "notes": "; ".join(notes),
    }


def _daily_status(daily_days: int, missing_days: int, internal_missing_days: int, tail_missing_days: int) -> str:
    if daily_days <= 0:
        return "missing"
    if internal_missing_days:
        return "warning_internal_gap"
    if missing_days or tail_missing_days:
        return "warning_tail_gap"
    return "ok"


def _minute_match_status(
    has_daily: bool,
    has_minute: bool,
    expected_days: int,
    missing_vs_daily: int,
    extra_vs_daily: int,
    partial_days: int,
) -> str:
    if not has_daily:
        return "unchecked_no_daily"
    if not has_minute:
        return "missing"
    if not expected_days:
        return "unchecked_no_overlap"
    if missing_vs_daily or extra_vs_daily or partial_days:
        return "warning"
    return "ok"


def _stock_list_date(metadata: dict[str, Any], daily_coverage: dict[str, Any]) -> str:
    stock_basic = metadata.get("stock_basic") if isinstance(metadata.get("stock_basic"), dict) else {}
    return str(
        stock_basic.get("list_date")
        or stock_basic.get("上市日期")
        or metadata.get("list_date")
        or metadata.get("上市日期")
        or daily_coverage.get("list_date")
        or ""
    )


def _overall_status(daily_status: str, minute_status: str, volume_status: str, has_minute: bool) -> tuple[str, list[str]]:
    notes: list[str] = []
    if daily_status == "missing":
        notes.append("没有日K")
        return "danger", notes
    if daily_status != "ok":
        notes.append("日K存在缺口")
    if not has_minute:
        notes.append("没有分时K")
    elif minute_status != "ok":
        notes.append("分时天数与日K不完全匹配")
    if volume_status == "warning":
        notes.append("热缓存分时成交量与日K成交量抽检不一致")
    elif volume_status != "ok":
        notes.append("成交量只做了有限抽检或没有可比样本")
    if notes:
        return "warning", notes
    return "ok", ["日K、分时天数和成交量抽检均正常"]


def _empty_volume_summary(reason: str) -> dict[str, Any]:
    return {
        "volume_status": "unchecked",
        "volume_checked_days": 0,
        "volume_match_days": 0,
        "volume_mismatch_days": 0,
        "volume_unit_factor": "",
        "volume_max_relative_error": "",
        "volume_mismatch_samples": "",
        "reason": reason,
    }


def _minute_bucket_volume(bucket: dict[str, Any]) -> float | None:
    total = 0.0
    seen = False
    for item in bucket.get("minutes") or []:
        if not isinstance(item, dict):
            continue
        value = _first_number(item, MINUTE_VOLUME_KEYS)
        if value is not None:
            total += value
            seen = True
    return total if seen else None


def _first_number(mapping: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = _to_number(mapping.get(key))
        if value is not None:
            return value
    return None


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _positive_number(value: Any) -> bool:
    number = _to_number(value)
    return number is not None and number > 0


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(abs(expected), 1.0)


def _volume_sample_label(item: dict[str, Any]) -> str:
    return (
        f"{item['trade_date']}: 日K={_format_float(item['expected_volume'])}, "
        f"分时={_format_float(item['minute_volume'])}, 误差={_format_float(item['relative_error'])}"
    )


def _mongo_number_expr(input_expr: Any) -> dict[str, Any]:
    return {"$convert": {"input": input_expr, "to": "double", "onError": 0, "onNull": 0}}


def _coalesce_expr(expressions: list[Any]) -> Any:
    if not expressions:
        return None
    expr = expressions[-1]
    for value in reversed(expressions[:-1]):
        expr = {"$ifNull": [value, expr]}
    return expr


def _normalize_codes(codes: list[str]) -> list[str]:
    result = []
    for code in codes:
        try:
            normalized = normalize_ts_code(str(code or ""))
        except ValueError:
            continue
        if normalized not in result:
            result.append(normalized)
    return result


def _normalize_daily_summary_mode(mode: str) -> str:
    value = str(mode or DEFAULT_DAILY_SUMMARY_MODE).strip().lower()
    if value not in {"coverage", "aggregate"}:
        raise ValueError("daily_summary_mode 只能是 coverage 或 aggregate")
    return value


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _ratio_text(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return ""
    return f"{numerator / denominator:.2%}"


def _format_float(value: Any) -> str:
    number = _to_number(value)
    if number is None:
        return ""
    if abs(number) >= 1000:
        return f"{number:.2f}"
    return f"{number:.6g}"


def _infer_output_format(path: Path, output_format: str) -> str:
    selected = str(output_format or "").strip().lower()
    if selected and selected != "auto":
        return selected
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix == ".json":
        return "json"
    return "csv"


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    handle = sys.stdout if str(path) == "-" else path.open("w", encoding="utf-8-sig", newline="")
    try:
        writer = csv.DictWriter(handle, fieldnames=[label for _, label in EXPORT_COLUMNS], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_label_row(row))
    finally:
        if handle is not sys.stdout:
            handle.close()


def _write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    labels = [label for _, label in EXPORT_COLUMNS]
    lines = [
        "| " + " | ".join(labels) + " |",
        "| " + " | ".join("---" for _ in labels) + " |",
    ]
    for row in rows:
        labelled = _label_row(row)
        lines.append("| " + " | ".join(_markdown_cell(labelled.get(label, "")) for label in labels) + " |")
    _write_text(path, "\n".join(lines) + "\n")


def _write_text(path: Path, text: str) -> None:
    if str(path) == "-":
        sys.stdout.write(text)
        return
    path.write_text(text, encoding="utf-8")


def _label_row(row: dict[str, Any]) -> dict[str, Any]:
    return {label: row.get(key, "") for key, label in EXPORT_COLUMNS}


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def summarize_status(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("overall_status") or "unknown") for row in rows))
