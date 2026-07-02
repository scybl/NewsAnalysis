from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, today_yyyymmdd, write_json


KLINE_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
DEFAULT_FREQUENCIES = ("daily",)
SUPPORTED_FREQUENCIES = ("daily", "weekly", "monthly")


@dataclass(frozen=True)
class KlineBackfillConfig:
    output_dir: Path
    start_date: str = "19900101"
    end_date: str = ""
    frequencies: tuple[str, ...] = DEFAULT_FREQUENCIES
    include_delisted: bool = False
    force: bool = False
    limit: int | None = None
    codes: tuple[str, ...] = ()
    progress: bool = False
    workers: int = 1


def fetch_all_stock_klines(client: TushareClient, config: KlineBackfillConfig) -> dict[str, Any]:
    end_date = config.end_date or today_yyyymmdd()
    frequencies = _normalize_frequencies(config.frequencies)
    stock_rows = _stock_rows(client, include_delisted=config.include_delisted, codes=config.codes)
    if config.limit is not None:
        stock_rows = stock_rows[: max(0, config.limit)]

    root = ensure_dir(config.output_dir)
    result: dict[str, Any] = {
        "ok": True,
        "started_at": timestamp(),
        "output_dir": str(root),
        "start_date": config.start_date,
        "end_date": end_date,
        "frequencies": list(frequencies),
        "stock_count": len(stock_rows),
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "rows": 0,
        "items": [],
    }

    workers = max(1, int(config.workers or 1))
    if workers == 1:
        item_iter = (_fetch_stock_klines(client, root, stock, frequencies, config.start_date, end_date, force=config.force) for stock in stock_rows)
        _consume_stock_items(item_iter, result, root, config.progress)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_fetch_stock_klines, client, root, stock, frequencies, config.start_date, end_date, force=config.force)
                for stock in stock_rows
            ]
            _consume_stock_items((future.result() for future in as_completed(futures)), result, root, config.progress)

    result["finished_at"] = timestamp()
    write_json(root / "manifest.json", result)
    return result


def _consume_stock_items(item_iter: Any, result: dict[str, Any], root: Path, progress: bool) -> None:
    for stock_item in item_iter:
        result["updated"] += int(stock_item.pop("_updated", 0))
        result["skipped"] += int(stock_item.pop("_skipped", 0))
        result["failed"] += int(stock_item.pop("_failed", 0))
        result["rows"] += int(stock_item.pop("_rows", 0))
        result["items"].append(stock_item)
        if progress:
            done = len(result["items"])
            print(
                f"[{done}/{result['stock_count']}] {stock_item.get('ts_code')} "
                f"updated={result['updated']} skipped={result['skipped']} failed={result['failed']} rows={result['rows']}",
                flush=True,
            )
        write_json(root / "manifest.json", result)


def _fetch_stock_klines(
    client: TushareClient,
    root: Path,
    stock: dict[str, Any],
    frequencies: tuple[str, ...],
    requested_start_date: str,
    end_date: str,
    *,
    force: bool,
) -> dict[str, Any]:
    ts_code = normalize_ts_code(str(stock.get("ts_code") or ""))
    stock_start_date = _stock_start_date(stock, requested_start_date)
    stock_item: dict[str, Any] = {"ts_code": ts_code, "name": stock.get("name") or "", "frequencies": {}, "_updated": 0, "_skipped": 0, "_failed": 0, "_rows": 0}
    for frequency in frequencies:
        path = _kline_path(root, frequency, ts_code)
        if not force and _existing_file_covers(path, stock_start_date, end_date):
            stock_item["_skipped"] += 1
            stock_item["frequencies"][frequency] = {"status": "skipped", "path": str(path)}
            continue
        try:
            fields, records = _fetch_kline_records(client, frequency, ts_code, stock_start_date, end_date)
            payload = {
                "ts_code": ts_code,
                "name": stock.get("name") or "",
                "frequency": frequency,
                "fields": fields,
                "date_range": _date_range(records, stock_start_date, end_date),
                "complete_fetch": True,
                "fetch_strategy": "date_windows_v2",
                "records": records,
                "updated_at": timestamp(),
                "source": getattr(client, "source_name", "Tushare Pro"),
            }
            write_json(path, payload)
            row_count = len(records)
            stock_item["_updated"] += 1
            stock_item["_rows"] += row_count
            stock_item["frequencies"][frequency] = {"status": "updated", "rows": row_count, "path": str(path)}
        except Exception as exc:  # noqa: BLE001 - keep large backfills resumable.
            stock_item["_failed"] += 1
            stock_item["frequencies"][frequency] = {"status": "failed", "error": str(exc), "path": str(path)}
    return stock_item


def _stock_rows(client: TushareClient, *, include_delisted: bool, codes: tuple[str, ...]) -> list[dict[str, Any]]:
    if codes:
        selected = {normalize_ts_code(code) for code in codes}
        statuses = ("L", "D", "P") if include_delisted else ("L",)
    else:
        selected = set()
        statuses = ("L", "D", "P") if include_delisted else ("L",)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in statuses:
        result = client.query(
            "stock_basic",
            {"list_status": status},
            "ts_code,symbol,name,area,industry,market,list_date,exchange,list_status",
        )
        for row in result.records:
            ts_code = normalize_ts_code(str(row.get("ts_code") or ""))
            if selected and ts_code not in selected:
                continue
            if ts_code in seen:
                continue
            seen.add(ts_code)
            rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("ts_code") or ""))


def _fetch_kline_records(client: TushareClient, frequency: str, ts_code: str, start_date: str, end_date: str) -> tuple[list[str], list[dict[str, Any]]]:
    records_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    fields: list[str] = []
    for window_start, window_end in _date_windows(start_date, end_date, years=10 if frequency == "daily" else 80):
        query = client.query(
            frequency,
            {"ts_code": ts_code, "start_date": window_start, "end_date": window_end},
            KLINE_FIELDS,
        )
        fields = query.fields or fields or KLINE_FIELDS.split(",")
        for row in query.records:
            key = (str(row.get("ts_code") or ts_code), str(row.get("trade_date") or ""))
            if key[1]:
                records_by_key[key] = row
    return fields or KLINE_FIELDS.split(","), _sort_kline_records(list(records_by_key.values()))


def _stock_start_date(stock: dict[str, Any], requested_start: str) -> str:
    list_date = str(stock.get("list_date") or "")
    if len(list_date) == 8 and list_date.isdigit() and list_date > requested_start:
        return list_date
    return requested_start


def _date_windows(start_date: str, end_date: str, *, years: int) -> list[tuple[str, str]]:
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        next_year = min(cursor.year + years, 9999)
        try:
            window_end = cursor.replace(year=next_year)
        except ValueError:
            window_end = cursor.replace(year=next_year, day=28)
        window_end = window_end.replace(month=12, day=31)
        if window_end > end:
            window_end = end
        windows.append((cursor.strftime("%Y%m%d"), window_end.strftime("%Y%m%d")))
        cursor = window_end.replace(year=window_end.year + 1, month=1, day=1)
    return windows


def _normalize_frequencies(frequencies: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    for value in frequencies:
        frequency = str(value).strip().lower()
        if not frequency:
            continue
        if frequency not in SUPPORTED_FREQUENCIES:
            raise ValueError(f"不支持的 K 线频率：{value}，可选：{', '.join(SUPPORTED_FREQUENCIES)}")
        if frequency not in selected:
            selected.append(frequency)
    return tuple(selected or DEFAULT_FREQUENCIES)


def _kline_path(root: Path, frequency: str, ts_code: str) -> Path:
    return root / frequency / f"{normalize_ts_code(ts_code)}.json"


def _existing_file_covers(path: Path, start_date: str, end_date: str) -> bool:
    if not path.exists():
        return False
    try:
        payload = read_json(path)
    except Exception:
        return False
    date_range = payload.get("date_range") or {}
    records = payload.get("records") or []
    return (
        bool(records)
        and payload.get("complete_fetch") is True
        and str(date_range.get("start_date") or "") <= start_date
        and str(date_range.get("end_date") or "") >= end_date
    )


def _sort_kline_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda row: str(row.get("trade_date") or ""), reverse=True)


def _date_range(records: list[dict[str, Any]], requested_start: str, requested_end: str) -> dict[str, str]:
    dates = sorted(str(row.get("trade_date") or "") for row in records if row.get("trade_date"))
    if not dates:
        return {"start_date": requested_start, "end_date": requested_end, "actual_start_date": "", "actual_end_date": ""}
    return {"start_date": requested_start, "end_date": requested_end, "actual_start_date": dates[0], "actual_end_date": dates[-1]}
