from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .market_dimensions import STOCK_COLLECTIONS
from .utils import normalize_ts_code, today_yyyymmdd


REFERENCE_SOURCE = "market_daily_dates"


def ensure_indexes(coverage: Any, pymongo_module: Any) -> None:
    coverage.create_index([("ts_code", pymongo_module.ASCENDING)], unique=True)
    coverage.create_index([("status", pymongo_module.ASCENDING), ("missing_days", pymongo_module.DESCENDING)])
    coverage.create_index([("last_expected_date", pymongo_module.DESCENDING), ("latest_indexed_date", pymongo_module.DESCENDING)])


def inspect_daily_k_coverage_gaps(
    rows: Any,
    metadata: Any,
    coverage: Any | None = None,
    *,
    codes: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    limit: int | None = None,
    max_samples: int = 20,
    persist: bool = False,
) -> dict[str, Any]:
    normalized_codes = [normalize_ts_code(code) for code in codes or [] if str(code or "").strip()]
    if not normalized_codes:
        normalized_codes = _daily_gap_candidate_codes(metadata, rows)
    if limit is not None:
        normalized_codes = normalized_codes[: max(0, int(limit))]

    start = normalize_trade_date(start_date) if start_date else ""
    end = normalize_trade_date(end_date) if end_date else today_yyyymmdd()
    market_dates = _market_daily_reference_dates(rows, start, end)
    metadata_by_code = _metadata_by_code(metadata, normalized_codes)

    items: list[dict[str, Any]] = []
    summary = {
        "ok": True,
        "reference_source": REFERENCE_SOURCE,
        "start_date": start,
        "end_date": end,
        "market_reference_days": len(market_dates),
        "stocks_checked": 0,
        "stocks_without_reference": 0,
        "stocks_without_daily": 0,
        "stocks_with_missing": 0,
        "missing_days": 0,
        "tail_missing_days": 0,
        "internal_missing_days": 0,
    }

    for ts_code in normalized_codes:
        stock_metadata = metadata_by_code.get(ts_code, {})
        expected_dates = _expected_dates_for_stock(market_dates, stock_metadata, start)
        if not expected_dates:
            item = {
                "ts_code": ts_code,
                "status": "no_reference_dates",
                "reference_source": REFERENCE_SOURCE,
                "expected_days": 0,
                "indexed_days": 0,
                "missing_days": 0,
            }
            items.append(item)
            summary["stocks_without_reference"] += 1
            if persist and coverage is not None:
                _persist_coverage(coverage, item)
            continue

        indexed_dates = _stock_daily_dates(rows, ts_code, expected_dates[0], expected_dates[-1])
        indexed_set = set(indexed_dates)
        missing_dates = [date for date in expected_dates if date not in indexed_set]
        latest_indexed = indexed_dates[-1] if indexed_dates else ""
        first_indexed = indexed_dates[0] if indexed_dates else ""
        tail_missing = [date for date in expected_dates if not latest_indexed or date > latest_indexed]
        internal_missing = [date for date in missing_dates if latest_indexed and date <= latest_indexed]
        latest_complete = _latest_contiguous_date(expected_dates, indexed_set)
        item = {
            "ts_code": ts_code,
            "name": str((stock_metadata.get("stock_basic") or {}).get("name") or stock_metadata.get("name") or ""),
            "status": "ok" if not missing_dates else "needs_backfill",
            "reference_source": REFERENCE_SOURCE,
            "list_date": _stock_list_date(stock_metadata),
            "first_expected_date": expected_dates[0],
            "last_expected_date": expected_dates[-1],
            "first_indexed_date": first_indexed,
            "latest_indexed_date": latest_indexed,
            "latest_complete_date": latest_complete,
            "expected_days": len(expected_dates),
            "indexed_days": len(indexed_dates),
            "missing_days": len(missing_dates),
            "tail_missing_days": len(tail_missing),
            "internal_missing_days": len(internal_missing),
            "missing_samples": missing_dates[:max_samples],
            "tail_missing_samples": tail_missing[:max_samples],
            "internal_missing_samples": internal_missing[:max_samples],
        }
        items.append(item)
        summary["stocks_checked"] += 1
        summary["missing_days"] += len(missing_dates)
        summary["tail_missing_days"] += len(tail_missing)
        summary["internal_missing_days"] += len(internal_missing)
        if not indexed_dates:
            summary["stocks_without_daily"] += 1
        if missing_dates:
            summary["stocks_with_missing"] += 1
        if persist and coverage is not None:
            _persist_coverage(coverage, item)

    summary["items"] = sorted(
        items,
        key=lambda item: (
            item.get("status") == "ok",
            -int(item.get("missing_days") or 0),
            str(item.get("ts_code") or ""),
        ),
    )
    return summary


def refresh_daily_k_coverage(
    rows: Any,
    metadata: Any,
    coverage: Any,
    *,
    codes: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    limit: int | None = None,
    max_samples: int = 20,
) -> dict[str, Any]:
    return inspect_daily_k_coverage_gaps(
        rows,
        metadata,
        coverage,
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        max_samples=max_samples,
        persist=True,
    )


def _daily_gap_candidate_codes(metadata: Any, rows: Any) -> list[str]:
    codes: set[str] = set()
    try:
        for value in metadata.distinct("ts_code"):
            try:
                codes.add(normalize_ts_code(str(value)))
            except ValueError:
                continue
    except Exception:
        pass
    if not codes:
        try:
            for value in rows.distinct("ts_code", {"snapshot": "current", "dataset": "daily"}):
                try:
                    codes.add(normalize_ts_code(str(value)))
                except ValueError:
                    continue
        except Exception:
            pass
    return sorted(codes)


def _metadata_by_code(metadata: Any, codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        cursor = metadata.find(
            {"ts_code": {"$in": codes}},
            {"_id": 0, "ts_code": 1, "metadata": 1},
        )
    except Exception:
        return result
    for doc in cursor:
        item = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        try:
            ts_code = normalize_ts_code(str(item.get("ts_code") or doc.get("ts_code") or ""))
        except ValueError:
            continue
        result[ts_code] = item
    return result


def _market_daily_reference_dates(rows: Any, start_date: str, end_date: str) -> list[str]:
    trade_date_filter: dict[str, str] = {"$lte": end_date}
    if start_date:
        trade_date_filter["$gte"] = start_date
    query = {"snapshot": "current", "dataset": "daily", "trade_date": trade_date_filter}
    try:
        raw_dates = rows.distinct("trade_date", query)
    except Exception:
        raw_dates = []
    return sorted({date for value in raw_dates if (date := normalize_trade_date(str(value or ""))) and _date_in_range(date, start_date, end_date)})


def _expected_dates_for_stock(market_dates: list[str], metadata: dict[str, Any], start_date: str) -> list[str]:
    lower_bound = start_date
    list_date = _stock_list_date(metadata)
    if list_date and (not lower_bound or list_date > lower_bound):
        lower_bound = list_date
    daily_range = metadata.get("daily_date_range") if isinstance(metadata.get("daily_date_range"), dict) else {}
    range_start = normalize_trade_date(str(daily_range.get("start_date") or ""))
    if range_start and (not lower_bound or range_start < lower_bound):
        # Historical packages may start before list_date metadata was populated.
        lower_bound = range_start
    return [date for date in market_dates if not lower_bound or date >= lower_bound]


def _stock_daily_dates(rows: Any, ts_code: str, start_date: str, end_date: str) -> list[str]:
    query = {
        "ts_code": ts_code,
        "snapshot": "current",
        "dataset": "daily",
        "trade_date": {"$gte": start_date, "$lte": end_date},
    }
    try:
        raw_dates = rows.distinct("trade_date", query)
    except Exception:
        raw_dates = []
    return sorted({date for value in raw_dates if (date := normalize_trade_date(str(value or ""))) and start_date <= date <= end_date})


def _stock_list_date(metadata: dict[str, Any]) -> str:
    stock_basic = metadata.get("stock_basic") if isinstance(metadata.get("stock_basic"), dict) else {}
    return normalize_trade_date(str(stock_basic.get("list_date") or metadata.get("list_date") or ""))


def _latest_contiguous_date(expected_dates: list[str], indexed_dates: set[str]) -> str:
    latest = ""
    for date in expected_dates:
        if date not in indexed_dates:
            break
        latest = date
    return latest


def _persist_coverage(coverage: Any, item: dict[str, Any]) -> None:
    payload = {**item, "updated_at": datetime.now(timezone.utc), "collection": STOCK_COLLECTIONS["daily_coverage"]}
    coverage.update_one({"ts_code": item["ts_code"]}, {"$set": payload, "$setOnInsert": {"created_at": payload["updated_at"]}}, upsert=True)


def normalize_trade_date(value: str) -> str:
    cleaned = value.strip().replace("-", "")
    return cleaned if len(cleaned) == 8 and cleaned.isdigit() else ""


def _date_in_range(value: str, start: str, end: str) -> bool:
    return bool(value) and (not start or value >= start) and (not end or value <= end)
