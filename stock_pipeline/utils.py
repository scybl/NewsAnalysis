from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CN_TZ = timezone(timedelta(hours=8))


def today_yyyymmdd() -> str:
    return datetime.now(CN_TZ).strftime("%Y%m%d")


def timestamp() -> str:
    return datetime.now(CN_TZ).strftime("%Y%m%d_%H%M%S")


def years_ago_yyyymmdd(years: int) -> str:
    now = datetime.now(CN_TZ)
    try:
        return now.replace(year=now.year - years).strftime("%Y%m%d")
    except ValueError:
        return now.replace(month=2, day=28, year=now.year - years).strftime("%Y%m%d")


def normalize_ts_code(code: str) -> str:
    value = code.strip().upper()
    if "." in value:
        return value
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"股票代码格式不正确：{code}")
    if value.startswith(("60", "68", "90", "51", "52", "56", "58")):
        return f"{value}.SH"
    if value.startswith(("00", "30", "20", "15", "16", "18")):
        return f"{value}.SZ"
    if value.startswith(("43", "83", "87", "88", "92")):
        return f"{value}.BJ"
    return f"{value}.SZ"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sorted_records(records: list[dict[str, Any]], date_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> str:
        for field in date_fields:
            value = row.get(field)
            if value:
                return str(value)
        return ""

    return sorted(records, key=key, reverse=True)


def pick(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields if field in row}


def limit_records(records: list[dict[str, Any]], limit: int, fields: list[str] | None = None) -> list[dict[str, Any]]:
    selected = records[:limit]
    if fields:
        return [pick(row, fields) for row in selected]
    return selected
