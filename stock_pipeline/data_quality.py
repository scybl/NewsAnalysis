from __future__ import annotations

from typing import Any


DATE_KEYS = ("trade_date", "end_date", "ann_date", "f_ann_date", "float_date", "record_date", "suspend_date", "resume_date")
DATASET_DATE_KEYS = {
    "pledge_detail": ("ann_date", "start_date", "release_date", "end_date"),
    "suspend_d": ("suspend_date", "resume_date"),
}
FINANCIAL_DATASETS = ("income", "balancesheet", "cashflow", "fina_indicator")
FINANCIAL_QUARTERS = ("0331", "0630", "0930", "1231")
KEY_HISTORY_DATASETS = (
    "daily",
    "daily_basic",
    "adj_factor",
    "suspend_d",
    "moneyflow",
    "margin_detail",
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "express",
    "forecast",
    "fina_mainbz",
    "fina_audit",
    "anns_d",
    "dividend",
    "stk_rewards",
    "top10_holders",
    "top10_floatholders",
    "stk_holdernumber",
    "stk_holdertrade",
    "pledge_stat",
    "pledge_detail",
    "share_float",
    "block_trade",
    "namechange",
    "stk_managers",
)
MIN_RECENT_ROWS = {
    "daily": 700,
    "daily_basic": 700,
    "adj_factor": 700,
    "income": 12,
    "balancesheet": 12,
    "cashflow": 12,
    "fina_indicator": 12,
    "margin_detail": 250,
    "moneyflow": 60,
}
EVENT_DATASETS = {"suspend_d", "stk_rewards", "pledge_stat", "pledge_detail", "share_float", "block_trade", "namechange", "stk_managers"}


def audit_collection_completeness(full_data: dict[str, Any]) -> dict[str, Any]:
    datasets = full_data.get("datasets") or {}
    date_range = full_data.get("date_range") or {}
    end_year = _year(str(date_range.get("end_date") or ""))
    audit_until_year = min(end_year or 2024, 2024)
    listing_year = _listing_year(datasets)
    dataset_ranges = {name: _dataset_range(rows, DATASET_DATE_KEYS.get(name, DATE_KEYS)) for name, rows in datasets.items()}
    warnings = []

    financial_coverage = {}
    for name in FINANCIAL_DATASETS:
        rows = datasets.get(name) or []
        coverage = _financial_coverage(rows, audit_until_year, listing_year=listing_year)
        financial_coverage[name] = coverage
        if rows and coverage["missing_recent_quarters"]:
            warnings.append(
                {
                    "dataset": name,
                    "severity": "high",
                    "message": f"{name} 在近年财报季度存在缺口",
                    "missing_recent_quarters": coverage["missing_recent_quarters"],
                }
            )

    for name in KEY_HISTORY_DATASETS:
        info = dataset_ranges.get(name) or {"rows": 0, "first_date": "", "last_date": ""}
        if info["rows"] == 0:
            severity = "low" if name in EVENT_DATASETS else "medium"
            warnings.append({"dataset": name, "severity": severity, "message": f"{name} 未抓到数据或当前无公开记录"})
        elif name in MIN_RECENT_ROWS and info["rows"] < MIN_RECENT_ROWS[name]:
            warnings.append(
                {
                    "dataset": name,
                    "severity": "medium",
                    "message": f"{name} 行数低于近三年最小覆盖要求",
                    "rows": info["rows"],
                    "min_recent_rows": MIN_RECENT_ROWS[name],
                }
            )

    daily = dataset_ranges.get("daily") or {}
    monthly = dataset_ranges.get("monthly") or {}
    if daily.get("first_date") and monthly.get("first_date") and daily["first_date"][:4] > monthly["first_date"][:4]:
        warnings.append(
            {
                "dataset": "daily",
                "severity": "high",
                "message": "日线起始年份晚于月线，疑似只抓到近期行情",
                "daily_first_date": daily["first_date"],
                "monthly_first_date": monthly["first_date"],
            }
        )

    anns = dataset_ranges.get("anns_d") or {}
    if anns.get("rows", 0) and anns.get("rows", 0) % 100 == 0:
        warnings.append(
            {
                "dataset": "anns_d",
                "severity": "medium",
                "message": "公告条数刚好落在分页整数边界，需确认是否还有更早公告",
                "rows": anns.get("rows"),
                "first_date": anns.get("first_date"),
            }
        )

    return {
        "audit_until_year": audit_until_year,
        "dataset_ranges": dataset_ranges,
        "financial_coverage": financial_coverage,
        "warnings": warnings,
        "status": "complete" if not warnings else "partial",
    }


def _dataset_range(rows: list[dict[str, Any]], date_keys: tuple[str, ...]) -> dict[str, Any]:
    dates = []
    for row in rows:
        date = _row_date(row, date_keys)
        if date:
            dates.append(date)
    return {
        "rows": len(rows),
        "first_date": min(dates) if dates else "",
        "last_date": max(dates) if dates else "",
        "years": sorted({date[:4] for date in dates if len(date) >= 4}),
    }


def _financial_coverage(rows: list[dict[str, Any]], audit_until_year: int, *, listing_year: int | None = None) -> dict[str, Any]:
    by_year: dict[str, set[str]] = {}
    for row in rows:
        date = str(row.get("end_date") or "")
        if len(date) >= 8:
            by_year.setdefault(date[:4], set()).add(date[4:8])
    years = sorted(by_year)
    first_year = int(years[0]) if years else None
    last_year = int(years[-1]) if years else None
    missing_years = []
    missing_recent_quarters = []
    audit_from_year = max(first_year or audit_until_year, listing_year or first_year or audit_until_year)
    if first_year is not None:
        for year in range(audit_from_year, audit_until_year + 1):
            key = str(year)
            quarters = by_year.get(key, set())
            if not quarters:
                missing_years.append(key)
                continue
            if year >= max(audit_from_year, audit_until_year - 5):
                missing = [quarter for quarter in FINANCIAL_QUARTERS if quarter not in quarters]
                if missing:
                    missing_recent_quarters.append({"year": key, "missing": missing})
    return {
        "first_year": first_year,
        "last_year": last_year,
        "audit_from_year": audit_from_year,
        "years": years,
        "missing_years_until_audit_year": missing_years,
        "missing_recent_quarters": missing_recent_quarters,
    }


def _listing_year(datasets: dict[str, list[dict[str, Any]]]) -> int | None:
    for row in datasets.get("stock_basic") or []:
        year = _year(str(row.get("list_date") or ""))
        if year:
            return year
    return None


def _row_date(row: dict[str, Any], date_keys: tuple[str, ...]) -> str:
    for key in date_keys:
        date = _date8(row.get(key))
        if date:
            return date
    return ""


def _date8(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = text[:10].replace("-", "").replace("/", "")
    return cleaned[:8] if len(cleaned) >= 8 and cleaned[:8].isdigit() else ""


def _year(value: str) -> int | None:
    text = value.strip().replace("-", "")
    if len(text) < 4:
        return None
    try:
        return int(text[:4])
    except ValueError:
        return None
