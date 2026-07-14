from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any, Callable

from .config import PROJECT_ROOT
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from .minute_cold_storage import read_cached_or_downloaded_day
from .stock_storage import (
    _refresh_daily_k_coverage_safe,
    list_local_stock_summaries,
    stock_storage_status_snapshot,
    sync_daily_market_for_stock,
)
from .ths_minute import _mongo_uri, fetch_pytdx_history_minutes
from .utils import ensure_dir, normalize_ts_code, timestamp, today_yyyymmdd


REPORT_PATH = PROJECT_ROOT / "local_data" / "stock_storage_issue_reports.jsonl"
HEALTH_CHECKS = (
    "资料包是否存在",
    "热数据 daily 行数是否为空",
    "日K覆盖是否存在缺口或部分异常",
    "分时覆盖是否存在缺口或部分异常",
    "冷备份上传天数是否追平索引天数",
    "冷备份取回后与新抓同日分时数据是否一致",
)
PRICE_TOLERANCE = 1e-5
VOLUME_TOLERANCE = 1e-3
ColdReader = Callable[[Any, str, str, str], list[dict[str, Any]]]
FreshFetcher = Callable[[str, str], dict[str, Any]]


def run_stock_storage_health_check(
    *,
    sample_size: int = 30,
    codes: list[str] | None = None,
    seed: int | None = None,
    cold_compare_samples: int = 1,
    cold_reader: ColdReader | None = None,
    fresh_fetcher: FreshFetcher | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    selected_codes, total_candidates, actual_seed = _select_health_check_codes(sample_size=sample_size, codes=codes, seed=seed)
    _run_checkpoint(checkpoint, stage="before_coverage_refresh", sample_size=sample_size, selected_count=len(selected_codes))
    coverage_refresh = _refresh_daily_k_coverage_safe(selected_codes, today_yyyymmdd()) if selected_codes else {"ok": True, "stocks_checked": 0}
    _run_checkpoint(checkpoint, stage="before_status_snapshot", sample_size=sample_size, selected_count=len(selected_codes))
    snapshot = stock_storage_status_snapshot(
        limit=max(1, len(selected_codes) or 1),
        page=1,
        page_size=max(1, min(200, len(selected_codes) or 1)),
        filter_key="all",
        sort_key="health",
        codes=selected_codes,
    )
    items = snapshot.get("items") or []
    abnormal = [item for item in items if str(item.get("health_status") or "") != "ok"]
    _run_checkpoint(checkpoint, stage="before_cold_compare", sample_size=sample_size, selected_count=len(selected_codes))
    cold_compare = compare_minute_cold_backup_samples(
        sample_size=cold_compare_samples,
        seed=actual_seed,
        cold_reader=cold_reader,
        fresh_fetcher=fresh_fetcher,
    )
    cold_compare_attention = cold_compare.get("status") not in {"ok", "skipped"}
    return {
        "ok": True,
        "status": "ok" if not abnormal and not cold_compare_attention else "warning",
        "generated_at": timestamp(),
        "seed": actual_seed,
        "sample_size": max(1, int(sample_size or 1)),
        "cold_compare_samples": max(0, min(10, int(cold_compare_samples or 0))),
        "candidate_count": total_candidates,
        "checked_count": len(items),
        "abnormal_count": len(abnormal),
        "checks": list(HEALTH_CHECKS),
        "coverage_refresh": coverage_refresh,
        "cold_compare": cold_compare,
        "items": [
            {
                "ts_code": item.get("ts_code") or "",
                "name": item.get("name") or "",
                "health_status": item.get("health_status") or "",
                "health_message": item.get("health_message") or "",
            }
            for item in abnormal[:20]
        ],
    }


def _run_checkpoint(checkpoint: Callable[[dict[str, Any]], None] | None, **details: Any) -> None:
    if checkpoint is not None:
        checkpoint(details)


def compare_minute_cold_backup_samples(
    *,
    sample_size: int = 1,
    seed: int | None = None,
    source: str = "pytdx_history",
    cold_reader: ColdReader | None = None,
    fresh_fetcher: FreshFetcher | None = None,
    day_index: Any | None = None,
    sample_docs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    limit = max(0, min(10, int(sample_size or 0)))
    if limit <= 0:
        return {"ok": True, "status": "skipped", "sample_size": 0, "checked_count": 0, "differences": 0, "samples": []}
    reader = cold_reader or _read_minute_cold_rows
    fetcher = fresh_fetcher or _fetch_fresh_pytdx_rows
    try:
        if day_index is not None:
            docs = sample_docs if sample_docs is not None else _sample_uploaded_minute_docs(day_index, source=source, sample_size=limit, seed=seed)
            return _compare_minute_docs(day_index, docs[:limit], source=source, cold_reader=reader, fresh_fetcher=fetcher)
        from pymongo import MongoClient

        with MongoClient(_mongo_uri(MARKET_DATABASE), serverSelectionTimeoutMS=8000) as client:
            collection = client[MARKET_DATABASE][MARKET_COLLECTIONS["minute_day_index"]]
            docs = sample_docs if sample_docs is not None else _sample_uploaded_minute_docs(collection, source=source, sample_size=limit, seed=seed)
            return _compare_minute_docs(collection, docs[:limit], source=source, cold_reader=reader, fresh_fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001 - health checks should explain failures instead of hiding them.
        return {
            "ok": False,
            "status": "failed",
            "sample_size": limit,
            "checked_count": 0,
            "differences": 1,
            "error": str(exc),
            "reason": "无法读取冷备份索引或执行冷备份对照检查。",
            "samples": [],
        }


def _sample_uploaded_minute_docs(day_index: Any, *, source: str, sample_size: int, seed: int | None) -> list[dict[str, Any]]:
    match = {
        "source": source,
        "upload_status": "uploaded",
        "row_count": {"$gt": 0},
        "$or": [
            {"remote_path": {"$exists": True, "$ne": ""}},
            {"relative_path": {"$exists": True, "$ne": ""}},
        ],
    }
    try:
        return list(day_index.aggregate([{"$match": match}, {"$sample": {"size": sample_size}}, {"$project": {"_id": 0}}]))
    except Exception:
        docs = list(day_index.find(match, {"_id": 0}).limit(max(sample_size * 20, sample_size)))
        rng = random.Random(seed if seed is not None else 0)
        rng.shuffle(docs)
        return docs[:sample_size]


def _compare_minute_docs(
    day_index: Any,
    docs: list[dict[str, Any]],
    *,
    source: str,
    cold_reader: ColdReader,
    fresh_fetcher: FreshFetcher,
) -> dict[str, Any]:
    samples = [_compare_minute_doc(day_index, doc, source=source, cold_reader=cold_reader, fresh_fetcher=fresh_fetcher) for doc in docs]
    differences = [item for item in samples if item.get("result") != "matched"]
    failed = [item for item in differences if item.get("severity") == "failed"]
    status = "ok" if not differences else ("failed" if failed else "warning")
    return {
        "ok": not failed,
        "status": status,
        "sample_size": len(docs),
        "checked_count": len(samples),
        "differences": len(differences),
        "failed": len(failed),
        "samples": samples,
    }


def _compare_minute_doc(
    day_index: Any,
    doc: dict[str, Any],
    *,
    source: str,
    cold_reader: ColdReader,
    fresh_fetcher: FreshFetcher,
) -> dict[str, Any]:
    ts_code = normalize_ts_code(str(doc.get("ts_code") or ""))
    trade_date = _normalize_trade_date(str(doc.get("trade_date") or ""))
    indexed_rows = int(doc.get("row_count") or 0)
    sample = {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "indexed_rows": indexed_rows,
        "cold_rows": None,
        "fresh_rows": None,
        "result": "matched",
        "severity": "ok",
        "difference_type": "",
        "reason": "",
    }
    try:
        cold_rows = cold_reader(day_index, ts_code, trade_date, source)
        sample["cold_rows"] = len(cold_rows)
    except Exception as exc:  # noqa: BLE001
        sample.update(
            {
                "result": "cold_read_failed",
                "severity": "failed",
                "difference_type": "cold_read_failed",
                "reason": "冷备份对象无法取回或校验失败，优先检查百度网盘文件、remote_path、sha256 和 access token。",
                "error": str(exc),
            }
        )
        return sample

    fresh: dict[str, Any]
    try:
        fresh = fresh_fetcher(ts_code, trade_date)
        fresh_rows = fresh.get("rows") if isinstance(fresh.get("rows"), list) else []
        sample["fresh_rows"] = len(fresh_rows)
    except Exception as exc:  # noqa: BLE001
        sample.update(
            {
                "result": "fresh_fetch_failed",
                "severity": "warning",
                "difference_type": "fresh_fetch_failed",
                "reason": "实时重抓失败，本轮不能证明冷备份错误；通常是 pytdx 行情源、网络或依赖不可用。",
                "error": str(exc),
            }
        )
        return sample

    if indexed_rows and len(cold_rows) != indexed_rows:
        sample.update(
            {
                "result": "index_cold_count_mismatch",
                "severity": "failed",
                "difference_type": "index_cold_count_mismatch",
                "reason": "冷备份实际取回行数与索引记录不一致，说明归档文件或索引至少有一方不可信。",
            }
        )
        return sample
    if not fresh_rows:
        failures = fresh.get("failures") if isinstance(fresh.get("failures"), list) else []
        sample.update(
            {
                "result": "fresh_no_data",
                "severity": "warning",
                "difference_type": "fresh_no_data",
                "reason": "新抓源没有返回同日分时，可能是历史源已取不到、停牌/非交易日或数据源临时为空；冷备份暂不能判错。",
                "fresh_failures": failures[:3],
            }
        )
        return sample
    comparison = _compare_minute_rows(cold_rows, fresh_rows)
    if comparison["matched"]:
        sample.update({"reason": "冷备份与新抓同日分时数据一致。"})
        return sample
    severity = "failed" if comparison["difference_type"] in {"cold_missing_minutes", "value_mismatch", "row_count_mismatch"} else "warning"
    sample.update(
        {
            "result": comparison["difference_type"],
            "severity": severity,
            "difference_type": comparison["difference_type"],
            "reason": _difference_reason(comparison["difference_type"]),
            "missing_in_cold": comparison["missing_in_cold"],
            "extra_in_cold": comparison["extra_in_cold"],
            "value_mismatches": comparison["value_mismatches"],
        }
    )
    return sample


def _read_minute_cold_rows(day_index: Any, ts_code: str, trade_date: str, source: str) -> list[dict[str, Any]]:
    return read_cached_or_downloaded_day(day_index, ts_code=ts_code, trade_date=trade_date, source=source)


def _fetch_fresh_pytdx_rows(ts_code: str, trade_date: str) -> dict[str, Any]:
    result = fetch_pytdx_history_minutes(ts_code, [_normalize_trade_date(trade_date)])
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    return {
        "ok": bool(result.get("succeeded_days")),
        "rows": rows,
        "succeeded_days": int(result.get("succeeded_days") or 0),
        "failed_days": int(result.get("failed_days") or 0),
        "failures": result.get("failures") or [],
    }


def _compare_minute_rows(cold_rows: list[dict[str, Any]], fresh_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cold_by_minute = _minute_row_map(cold_rows)
    fresh_by_minute = _minute_row_map(fresh_rows)
    missing_in_cold = sorted(set(fresh_by_minute) - set(cold_by_minute))
    extra_in_cold = sorted(set(cold_by_minute) - set(fresh_by_minute))
    value_mismatches = _minute_value_mismatches(cold_by_minute, fresh_by_minute)
    if missing_in_cold:
        difference_type = "cold_missing_minutes"
    elif value_mismatches:
        difference_type = "value_mismatch"
    elif extra_in_cold:
        difference_type = "cold_extra_minutes"
    elif len(cold_rows) != len(fresh_rows):
        difference_type = "row_count_mismatch"
    else:
        difference_type = ""
    return {
        "matched": not difference_type,
        "difference_type": difference_type,
        "missing_in_cold": missing_in_cold[:20],
        "extra_in_cold": extra_in_cold[:20],
        "value_mismatches": value_mismatches[:20],
    }


def _minute_row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _minute_key(row)
        if key and key not in mapped:
            mapped[key] = row
    return mapped


def _minute_key(row: dict[str, Any]) -> str:
    minute = str(row.get("minute") or row.get("time") or "").strip()
    if minute:
        if len(minute) == 4 and minute.isdigit():
            return f"{minute[:2]}:{minute[2:]}"
        return minute[-5:] if ":" in minute else minute
    value = row.get("datetime") or row.get("date_time")
    if value is None:
        return ""
    text = str(value)
    return text[11:16] if len(text) >= 16 and ":" in text[11:16] else text


def _minute_value_mismatches(cold_by_minute: dict[str, dict[str, Any]], fresh_by_minute: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for minute in sorted(set(cold_by_minute) & set(fresh_by_minute)):
        cold = cold_by_minute[minute]
        fresh = fresh_by_minute[minute]
        cold_price = _row_number(cold, "price", "close")
        fresh_price = _row_number(fresh, "price", "close")
        cold_volume = _row_number(cold, "volume", "vol")
        fresh_volume = _row_number(fresh, "volume", "vol")
        fields: dict[str, dict[str, float]] = {}
        if cold_price is not None and fresh_price is not None and abs(cold_price - fresh_price) > PRICE_TOLERANCE:
            fields["price"] = {"cold": cold_price, "fresh": fresh_price}
        if cold_volume is not None and fresh_volume is not None and abs(cold_volume - fresh_volume) > VOLUME_TOLERANCE:
            fields["volume"] = {"cold": cold_volume, "fresh": fresh_volume}
        if fields:
            mismatches.append({"minute": minute, "fields": fields})
    return mismatches


def _row_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _difference_reason(difference_type: str) -> str:
    return {
        "cold_missing_minutes": "新抓数据包含冷备份缺失的分钟，说明最初抓取或归档时可能漏了这些分钟。",
        "cold_extra_minutes": "冷备份包含新抓源当前没有返回的分钟，可能是历史源回溯能力变化或新抓源临时缺行。",
        "value_mismatch": "同一分钟的价格或成交量不同，通常是原始源修正、最初抓取异常或字段标准化逻辑变化。",
        "row_count_mismatch": "冷备份和新抓行数不同，但分钟键差异不明显，需要进一步检查重复行或无时间键记录。",
    }.get(difference_type, "冷备份与新抓数据存在差异，需要人工复核。")


def _normalize_trade_date(value: str) -> str:
    cleaned = str(value or "").strip().replace("-", "")
    return cleaned[:8]


def repair_stock_storage_issue(
    client: Any,
    code: str,
    *,
    max_daily_days: int = 5,
    report_path: Path | None = None,
) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    before = _storage_item(ts_code)
    if not before:
        report = report_stock_storage_issue(
            {
                "source": "repair",
                "ts_code": ts_code,
                "issues": [{"code": "stock_storage_item_missing", "label": "股票存储状态不存在", "repairable": False}],
            },
            report_path=report_path,
        )
        return {"ok": True, "resolved": False, "status": "reported", "ts_code": ts_code, "daily_repairs": [], "report": report}

    issues_before = _storage_issues(before)
    if not issues_before:
        return {
            "ok": True,
            "resolved": True,
            "status": "ok",
            "ts_code": ts_code,
            "message": "该股票存储状态正常，无需补齐。",
            "before": _status_summary(before),
            "after": _status_summary(before),
            "daily_repairs": [],
        }

    daily_dates = _daily_repair_dates(before.get("daily_coverage") or {}, max_daily_days=max_daily_days)
    daily_repairs: list[dict[str, Any]] = []
    for trade_date in daily_dates:
        try:
            result = sync_daily_market_for_stock(client, ts_code, trade_date)
        except Exception as exc:  # noqa: BLE001 - keep a full repair attempt reportable.
            result = {"ok": False, "ts_code": ts_code, "target_date": trade_date, "status": "failed", "error": str(exc)}
        daily_repairs.append(_compact_daily_repair(result))

    coverage_refresh: dict[str, Any] | None = None
    if daily_repairs:
        coverage_refresh = _refresh_daily_k_coverage_safe([ts_code], today_yyyymmdd())

    after = _storage_item(ts_code) or before
    issues_after = _storage_issues(after)
    report: dict[str, Any] | None = None
    if issues_after:
        report = report_stock_storage_issue(
            {
                "source": "repair",
                "ts_code": ts_code,
                "name": after.get("name") or before.get("name") or "",
                "before": _status_summary(before),
                "after": _status_summary(after),
                "issues_before": issues_before,
                "issues_after": issues_after,
                "daily_repairs": daily_repairs,
                "coverage_refresh": coverage_refresh,
            },
            report_path=report_path,
        )

    resolved = not issues_after
    return {
        "ok": True,
        "resolved": resolved,
        "status": "repaired" if resolved else ("partially_repaired" if daily_repairs else "reported"),
        "ts_code": ts_code,
        "before": _status_summary(before),
        "after": _status_summary(after),
        "issues_before": issues_before,
        "issues_after": issues_after,
        "daily_repairs": daily_repairs,
        "coverage_refresh": coverage_refresh,
        "report": report,
    }


def _select_health_check_codes(*, sample_size: int, codes: list[str] | None, seed: int | None) -> tuple[list[str], int, int]:
    if codes:
        normalized = []
        for code in codes:
            try:
                value = normalize_ts_code(str(code or ""))
            except ValueError:
                continue
            if value not in normalized:
                normalized.append(value)
        return normalized[: max(1, min(200, int(sample_size or len(normalized) or 1)))], len(normalized), int(seed or 0)
    summary = list_local_stock_summaries()
    candidates = [str(item.get("ts_code") or "") for item in summary.get("items") or [] if item.get("ts_code")]
    candidates = sorted({normalize_ts_code(code) for code in candidates})
    actual_seed = int(seed if seed is not None else random.SystemRandom().randint(1, 2_147_483_647))
    rng = random.Random(actual_seed)
    count = min(len(candidates), max(1, min(200, int(sample_size or 30))))
    return sorted(rng.sample(candidates, count)) if count else [], len(candidates), actual_seed


def report_stock_storage_issue(payload: dict[str, Any], *, report_path: Path | None = None) -> dict[str, Any]:
    path = report_path or REPORT_PATH
    report_id = f"stock_storage_{timestamp()}_{uuid.uuid4().hex[:8]}"
    record = {
        "report_id": report_id,
        "created_at": timestamp(),
        "status": "pending",
        "target": "stock_storage",
        "payload": payload,
    }
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    try:
        storage = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        storage = str(path)
    return {"ok": True, "report_id": report_id, "status": "pending", "storage": storage}


def _storage_item(ts_code: str) -> dict[str, Any] | None:
    snapshot = stock_storage_status_snapshot(limit=2000, query=ts_code)
    for item in snapshot.get("items") or []:
        if str(item.get("ts_code") or "") == ts_code:
            return item
    return None


def _storage_issues(item: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    daily = item.get("daily_coverage") if isinstance(item.get("daily_coverage"), dict) else {}
    minute = item.get("minute_coverage") if isinstance(item.get("minute_coverage"), dict) else {}
    cold = item.get("cold_backup") if isinstance(item.get("cold_backup"), dict) else {}

    daily_missing = int(daily.get("missing_days") or 0)
    daily_partial = int(daily.get("partial_days") or 0)
    minute_missing = int(minute.get("missing_days") or 0) if minute.get("missing_days") is not None else 0
    minute_partial = int(minute.get("partial_days") or 0)
    cold_indexed_days = int(cold.get("indexed_days") or 0)
    cold_uploaded_days = int(cold.get("uploaded_days") or 0)

    if daily_missing:
        issues.append({"code": "daily_missing", "label": "日K缺口", "count": daily_missing, "repairable": bool(_daily_repair_dates(daily, max_daily_days=1))})
    if daily_partial:
        issues.append({"code": "daily_partial", "label": "日K部分异常", "count": daily_partial, "repairable": False})
    if minute_missing:
        issues.append({"code": "minute_missing", "label": "分时缺口", "count": minute_missing, "repairable": False})
    if minute_partial:
        issues.append({"code": "minute_partial", "label": "分时部分异常", "count": minute_partial, "repairable": False})
    if cold_indexed_days and cold_uploaded_days < cold_indexed_days:
        issues.append(
            {
                "code": "cold_backup_pending",
                "label": "冷备份未追平",
                "count": cold_indexed_days - cold_uploaded_days,
                "repairable": False,
                "uploaded_days": cold_uploaded_days,
                "indexed_days": cold_indexed_days,
            }
        )
    if not issues and str(item.get("health_status") or "") not in {"ok", ""}:
        issues.append({"code": "storage_health_unknown", "label": item.get("health_message") or "存储状态异常", "repairable": False})
    return issues


def _daily_repair_dates(daily: dict[str, Any], *, max_daily_days: int) -> list[str]:
    limit = max(0, min(30, int(max_daily_days or 0)))
    dates: list[str] = []
    for key in ("internal_missing_samples", "tail_missing_samples", "missing_samples"):
        values = daily.get(key) if isinstance(daily.get(key), list) else []
        for value in values:
            cleaned = str(value or "").strip().replace("-", "")
            if len(cleaned) == 8 and cleaned.isdigit() and cleaned not in dates:
                dates.append(cleaned)
            if len(dates) >= limit:
                return dates
    return dates


def _compact_daily_repair(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "ts_code": result.get("ts_code") or "",
        "target_date": result.get("target_date") or "",
        "status": result.get("status") or "",
        "reason": result.get("reason") or "",
        "error": result.get("error") or "",
        "latest_daily_date": result.get("latest_daily_date") or "",
        "changed": result.get("changed") or {},
    }


def _status_summary(item: dict[str, Any]) -> dict[str, Any]:
    daily = item.get("daily_coverage") if isinstance(item.get("daily_coverage"), dict) else {}
    minute = item.get("minute_coverage") if isinstance(item.get("minute_coverage"), dict) else {}
    cold = item.get("cold_backup") if isinstance(item.get("cold_backup"), dict) else {}
    return {
        "ts_code": item.get("ts_code") or "",
        "name": item.get("name") or "",
        "health_status": item.get("health_status") or "",
        "health_message": item.get("health_message") or "",
        "daily_missing_days": int(daily.get("missing_days") or 0),
        "daily_partial_days": int(daily.get("partial_days") or 0),
        "minute_missing_days": int(minute.get("missing_days") or 0) if minute.get("missing_days") is not None else 0,
        "minute_partial_days": int(minute.get("partial_days") or 0),
        "cold_uploaded_days": int(cold.get("uploaded_days") or 0),
        "cold_indexed_days": int(cold.get("indexed_days") or 0),
    }
