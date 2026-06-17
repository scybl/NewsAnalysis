from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .analysis_frameworks import build_all_analysis_dossiers
from .config import PROJECT_ROOT, load_dotenv
from .dossier import build_dossier
from .utils import CN_TZ, ensure_dir, normalize_ts_code, read_json, timestamp, write_json


DEFAULT_DB = "stock_market"
DEFAULT_COLLECTION = "tdx_intraday_minutes"
DEFAULT_PAYLOAD_COLLECTION = "market_minute_payloads"
TDX_DATASET = "tdx_intraday_minutes"
THS_DATASET = "ths_intraday_minutes"
THS_TIME_URL_LATEST = "https://d.10jqka.com.cn/v6/time/{market_code}/last.js"
DEFAULT_HEXIN_JS = PROJECT_ROOT / "out_repo" / "spider_reverse" / "2023_09" / "tonghuashun" / "tonghuashun.js"
DEFAULT_MOOTDX_REPO = PROJECT_ROOT / "out_repo" / "mootdx"
DEFAULT_TDX_MAX_PAGES = 1000


@dataclass(frozen=True)
class ThsMinuteConfig:
    mongo_uri: str
    database: str = DEFAULT_DB
    collection: str = DEFAULT_COLLECTION
    timeout: float = 12.0
    payload_collection: str = DEFAULT_PAYLOAD_COLLECTION
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )


def build_config(database: str | None = None, collection: str | None = None, timeout: float = 12.0) -> ThsMinuteConfig:
    load_dotenv()
    target_database = database or os.getenv("MARKET_MINUTE_DATABASE") or os.getenv("THS_MINUTE_DATABASE") or DEFAULT_DB
    return ThsMinuteConfig(
        mongo_uri=_mongo_uri(target_database),
        database=target_database,
        collection=collection or os.getenv("MARKET_MINUTE_COLLECTION") or os.getenv("THS_MINUTE_COLLECTION") or DEFAULT_COLLECTION,
        payload_collection=os.getenv("MARKET_MINUTE_PAYLOAD_COLLECTION") or os.getenv("THS_MARKET_PAYLOAD_COLLECTION") or DEFAULT_PAYLOAD_COLLECTION,
        timeout=timeout,
    )


def fetch_and_store_minutes(
    codes: list[str],
    *,
    config: ThsMinuteConfig | None = None,
    sleep_range: tuple[float, float] = (0.8, 1.8),
    source: str = "tdx",
    pages: int | str = 5,
    page_size: int = 800,
) -> dict[str, Any]:
    try:
        import pymongo
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("缺少 pymongo，无法写入 MongoDB。") from exc

    cfg = config or build_config()
    client = pymongo.MongoClient(cfg.mongo_uri, serverSelectionTimeoutMS=8000)
    collection = client[cfg.database][cfg.collection]
    payload_collection = client[cfg.database][cfg.payload_collection]
    _ensure_indexes(collection, pymongo)
    _ensure_payload_indexes(payload_collection, pymongo)

    results: list[dict[str, Any]] = []
    try:
        client.admin.command("ping")
        for index, raw_code in enumerate(codes):
            ts_code = normalize_ts_code(raw_code)
            try:
                results.append(
                    fetch_store_one_stock(
                        ts_code,
                        cfg,
                        collection,
                        payload_collection,
                        source=source,
                        pages=pages,
                        page_size=page_size,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep other symbols running
                results.append({"ts_code": ts_code, "ok": False, "error": str(exc)})
            if index < len(codes) - 1:
                time.sleep(random.uniform(*sleep_range))
    finally:
        client.close()

    return {
        "ok": bool(results) and all(item.get("ok") for item in results),
        "database": cfg.database,
        "collection": cfg.collection,
        "payload_collection": cfg.payload_collection,
        "source": source,
        "results": results,
    }


def fetch_store_one_stock(
    ts_code: str,
    cfg: ThsMinuteConfig,
    collection: Any,
    payload_collection: Any,
    *,
    source: str = "tdx",
    pages: int | str = 5,
    page_size: int = 800,
) -> dict[str, Any]:
    normalized_source = _normalize_source(source)
    if normalized_source == "auto":
        try:
            return fetch_store_one_stock(ts_code, cfg, collection, payload_collection, source="tdx", pages=pages, page_size=page_size)
        except Exception as tdx_exc:  # noqa: BLE001 - fall back to latest THS snapshot
            result = fetch_store_one_stock(ts_code, cfg, collection, payload_collection, source="ths", pages=1, page_size=page_size)
            result["fallback_from"] = "tdx"
            result["fallback_error"] = str(tdx_exc)
            return result
    if normalized_source == "tdx":
        return fetch_store_tdx_stock(ts_code, collection, pages=pages, page_size=page_size)
    if normalized_source != "ths":
        raise ValueError(f"未知分钟行情数据源：{source}")
    return fetch_store_ths_stock(ts_code, cfg, collection, payload_collection)


def fetch_store_tdx_stock(ts_code: str, collection: Any, *, pages: int | str = 5, page_size: int = 800) -> dict[str, Any]:
    all_pages, page_limit = _parse_tdx_pages(pages)
    page_size = max(1, min(800, int(page_size or 800)))
    fetched = fetch_tdx_minute_bars(ts_code, pages=page_limit, page_size=page_size, stop_when_exhausted=True)
    rows = fetched["rows"]
    if not rows:
        raise RuntimeError("通达信分钟 K 未返回数据。")
    inserted, updated = upsert_minute_rows(collection, rows)
    local = merge_local_dataset(ts_code, _read_stock_rows(collection, ts_code, source="tdx"), {"source": "tdx"}, dataset=TDX_DATASET)
    dates = sorted({str(row.get("trade_date") or "") for row in rows if row.get("trade_date")})
    return {
        "ts_code": ts_code,
        "name": "",
        "source": "tdx",
        "dataset": TDX_DATASET,
        "trade_date": dates[-1] if dates else "",
        "scope": "historical_minute_k",
        "history_supported": True,
        "requested_pages": "all" if all_pages else page_limit,
        "page_limit": page_limit,
        "pages_fetched": fetched["pages_fetched"],
        "source_exhausted": fetched["source_exhausted"],
        "page_size": page_size,
        "requested_days": len(dates),
        "succeeded_days": len(dates),
        "failed_days": 0,
        "rows": len(rows),
        "stored_rows": local.get("rows", len(rows)),
        "inserted": inserted,
        "updated": updated,
        "payload_inserted": 0,
        "local_merged": local["merged"],
        "local_path": local["path"],
        "date_range": {"start": dates[0] if dates else "", "end": dates[-1] if dates else ""},
        "message": "通达信分钟 K 已连续分页补抓到数据源尽头。" if fetched["source_exhausted"] else "通达信分钟 K 已分页补抓，包含开高低收、成交量和成交额。",
        "ok": True,
        "error": "",
    }


def fetch_store_ths_stock(ts_code: str, cfg: ThsMinuteConfig, collection: Any, payload_collection: Any) -> dict[str, Any]:
    payload = fetch_ths_minutes(ts_code, cfg)
    rows = normalize_minute_rows(ts_code, payload)
    inserted, updated = upsert_minute_rows(collection, rows)
    payload_inserted = upsert_payload(payload_collection, ts_code, payload)
    local = merge_local_dataset(ts_code, _read_stock_rows(collection, ts_code, source="10jqka"), payload, dataset=THS_DATASET)
    return {
        "ts_code": ts_code,
        "name": payload.get("name", ""),
        "source": "10jqka",
        "dataset": THS_DATASET,
        "trade_date": payload.get("date", ""),
        "scope": "latest_trade_date",
        "history_supported": False,
        "message": "当前同花顺分时接口只返回最新交易日 last.js，不包含历史交易日分钟数据。",
        "requested_days": 1,
        "succeeded_days": 1,
        "failed_days": 0,
        "rows": len(rows),
        "inserted": inserted,
        "updated": updated,
        "payload_inserted": 1 if payload_inserted else 0,
        "local_merged": local["merged"],
        "local_path": local["path"],
        "ok": True,
        "error": "",
    }


def fetch_tdx_minute_bars(ts_code: str, *, pages: int = 5, page_size: int = 800, stop_when_exhausted: bool = True) -> dict[str, Any]:
    _ensure_mootdx_importable()
    from mootdx.quotes import Quotes  # type: ignore

    symbol = normalize_ts_code(ts_code).split(".", 1)[0]
    client = Quotes.factory(market="std")
    rows: list[dict[str, Any]] = []
    fetched_at = datetime.now(timezone.utc)
    pages_fetched = 0
    source_exhausted = False
    for page in range(pages):
        frame = client.bars(symbol=symbol, frequency=7, start=page * page_size, offset=page_size)
        if frame is None or getattr(frame, "empty", True):
            source_exhausted = True
            break
        records = frame.to_dict("records")
        pages_fetched += 1
        rows.extend(_normalize_tdx_rows(ts_code, records, fetched_at))
        if stop_when_exhausted and len(records) < page_size:
            source_exhausted = True
            break
        time.sleep(float(os.getenv("MARKET_MINUTE_PAGE_SLEEP_SECONDS", "0.08")))
    return {"rows": _dedupe_rows(rows), "pages_fetched": pages_fetched, "source_exhausted": source_exhausted}


def _parse_tdx_pages(pages: int | str) -> tuple[bool, int]:
    raw = str(pages or "").strip().lower()
    if raw in {"", "all", "max", "0", "-1"}:
        limit = int(os.getenv("MARKET_MINUTE_MAX_PAGES", str(DEFAULT_TDX_MAX_PAGES)))
        return True, max(1, min(5000, limit))
    parsed = int(raw)
    return False, max(1, min(5000, parsed))


def _ensure_mootdx_importable() -> None:
    try:
        import mootdx  # noqa: F401
        return
    except ImportError:
        pass
    if DEFAULT_MOOTDX_REPO.exists():
        import sys

        sys.path.insert(0, str(DEFAULT_MOOTDX_REPO))
        try:
            import mootdx  # noqa: F401
            return
        except ImportError as exc:
            raise RuntimeError("mootdx 依赖未安装完整，请安装 pandas、tdxpy、prettytable、httpx。") from exc
    raise RuntimeError("缺少 mootdx，无法抓取通达信分钟 K。请先安装 mootdx 或同步 out_repo/mootdx。")


def _normalize_tdx_rows(ts_code: str, records: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    normalized = normalize_ts_code(ts_code)
    for record in records:
        dt = _parse_tdx_datetime(record)
        if not dt:
            continue
        trade_date = dt.strftime("%Y%m%d")
        minute = dt.strftime("%H%M")
        volume = _float(record.get("volume") if record.get("volume") is not None else record.get("vol"))
        amount = _float(record.get("amount"))
        if _near_zero(volume):
            volume = 0.0
        if _near_zero(amount):
            amount = 0.0
        result.append(
            {
                "source": "tdx",
                "dataset": TDX_DATASET,
                "ts_code": normalized,
                "symbol": normalized[:6],
                "trade_date": trade_date,
                "minute": minute,
                "datetime": dt.replace(tzinfo=CN_TZ),
                "open": _float(record.get("open")),
                "high": _float(record.get("high")),
                "low": _float(record.get("low")),
                "close": _float(record.get("close")),
                "price": _float(record.get("close")),
                "volume": volume,
                "vol": volume,
                "amount": amount,
                "fetched_at": fetched_at,
            }
        )
    return result


def fetch_ths_minutes(ts_code: str, config: ThsMinuteConfig | None = None) -> dict[str, Any]:
    cfg = config or build_config()
    market_code = ths_market_code(ts_code)
    url = _time_url(ts_code)
    last_error: Exception | None = None
    for use_hexin in (False, True):
        try:
            body = _fetch_text(url, ts_code, cfg, use_hexin=use_hexin)
            payload = parse_jsonp(body)
            key = market_code
            if key not in payload:
                raise ValueError(f"同花顺响应缺少 {key} 数据。")
            return payload[key]
        except Exception as exc:  # noqa: BLE001 - retry with anti-spider token
            last_error = exc
            if use_hexin:
                break
            time.sleep(0.6)
    if last_error:
        raise last_error
    raise RuntimeError("同花顺行情请求没有返回结果。")


def _fetch_text(url: str, ts_code: str, cfg: ThsMinuteConfig, *, use_hexin: bool) -> str:
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": f"https://stockpage.10jqka.com.cn/{ts_code[:6]}/",
        "User-Agent": cfg.user_agent,
    }
    if use_hexin:
        v = _hexin_v()
        if v:
            headers["hexin-v"] = v
            headers["Cookie"] = f"v={v}"
    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
        return response.read().decode("utf-8", errors="replace")


@lru_cache(maxsize=1)
def _hexin_v() -> str:
    js_path = os.getenv("THS_HEXIN_JS_PATH")
    path = Path(js_path) if js_path else DEFAULT_HEXIN_JS
    if not path.exists():
        return ""
    try:
        result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=8, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"生成同花顺 hexin-v 失败：{exc}") from exc
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def parse_jsonp(body: str) -> dict[str, Any]:
    text = body.strip()
    match = re.match(r"^[\w$]+\((.*)\)\s*;?\s*$", text, re.S)
    if not match:
        raise ValueError("同花顺返回不是预期 JSONP 格式。")
    return json.loads(match.group(1))


def normalize_minute_rows(ts_code: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    trade_date = str(payload.get("date") or "")
    if not re.fullmatch(r"\d{8}", trade_date):
        raise ValueError(f"同花顺返回的交易日期异常：{trade_date}")
    data = str(payload.get("data") or "")
    if not data:
        return []

    fetched_at = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for raw in data.split(";"):
        if not raw.strip():
            continue
        parts = raw.split(",")
        if len(parts) < 5:
            raise ValueError(f"同花顺分时行字段不足：{raw}")
        minute = parts[0].strip()
        if not re.fullmatch(r"\d{4}", minute):
            raise ValueError(f"同花顺分时分钟格式异常：{raw}")
        rows.append(
            {
                "source": "10jqka",
                "dataset": "ths_intraday_minutes",
                "ts_code": ts_code,
                "symbol": ts_code[:6],
                "market_code": ths_market_code(ts_code),
                "name": payload.get("name", ""),
                "trade_date": trade_date,
                "minute": minute,
                "datetime": _minute_datetime(trade_date, minute),
                "price": _float(parts[1]),
                "amount": _float(parts[2]),
                "avg_price": _float(parts[3]),
                "volume": _float(parts[4]),
                "pre_close": _float(payload.get("pre")),
                "market_type": payload.get("marketType", ""),
                "fetched_at": fetched_at,
            }
        )
    return rows


def upsert_minute_rows(collection: Any, rows: list[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for row in rows:
        result = collection.update_one(
            {"source": row.get("source", ""), "ts_code": row["ts_code"], "trade_date": row["trade_date"], "minute": row["minute"]},
            {"$set": row},
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
        elif result.modified_count:
            updated += 1
    return inserted, updated


def upsert_payload(collection: Any, ts_code: str, payload: dict[str, Any]) -> bool:
    trade_date = str(payload.get("date") or "")
    market_code = ths_market_code(ts_code)
    result = collection.update_one(
        {"ts_code": ts_code, "source": "10jqka", "payload_type": "time", "trade_date": trade_date},
        {
            "$set": {
                "source": "10jqka",
                "payload_type": "time",
                "ts_code": ts_code,
                "symbol": ts_code[:6],
                "market_code": market_code,
                "trade_date": trade_date,
                "name": payload.get("name", ""),
                "url": _time_url(ts_code),
                "payload": payload,
                "fetched_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    return result.upserted_id is not None


def merge_local_dataset(ts_code: str, rows: list[dict[str, Any]], payload: dict[str, Any], *, dataset: str) -> dict[str, Any]:
    current_dir = PROJECT_ROOT / "local_data" / normalize_ts_code(ts_code) / "current"
    full_path = current_dir / "full_data.json"
    if not full_path.exists():
        return {"merged": False, "path": "", "reason": "本地 Tushare 资料包不存在"}

    full_data = read_json(full_path)
    serializable_rows = _merge_rows(full_data.get("datasets", {}).get(dataset, []), [_local_row(row) for row in rows])
    datasets = full_data.setdefault("datasets", {})
    datasets[dataset] = serializable_rows
    source_key = "tdx" if dataset == TDX_DATASET else "10jqka"
    full_data.setdefault("external_sources", {})[source_key] = {
        "datasets": [dataset],
        "updated_at": timestamp(),
        "trade_date": payload.get("date", ""),
        "note": "通达信历史分钟 K，补充 Tushare 分钟权限缺口。" if dataset == TDX_DATASET else "同花顺日内分钟分时行情，补充 Tushare 分钟权限缺口。",
    }
    write_json(full_path, full_data)
    raw_dir = ensure_dir(current_dir / "raw")
    write_json(raw_dir / f"{dataset}.json", {"fields": list(serializable_rows[0].keys()) if serializable_rows else [], "records": serializable_rows})
    if dataset == THS_DATASET:
        write_json(raw_dir / "ths_market_time_payload.json", payload)
    dossier = build_dossier(full_data)
    write_json(current_dir / "dossier.json", dossier)
    for key, analysis_dossier in build_all_analysis_dossiers(dossier).items():
        write_json(current_dir / f"{key}_dossier.json", analysis_dossier)

    metadata_path = current_dir.parent / "metadata.json"
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        rows_map = metadata.setdefault("dataset_rows", {})
        rows_map[dataset] = len(serializable_rows)
        metadata["market_minute_updated_at"] = timestamp()
        write_json(metadata_path, metadata)
    return {"merged": True, "path": str(full_path), "rows": len(serializable_rows)}


def ths_market_code(code: str) -> str:
    ts_code = normalize_ts_code(code)
    symbol, exchange = ts_code.split(".", 1)
    if exchange in {"SH", "SZ"}:
        return f"hs_{symbol}"
    raise ValueError(f"同花顺分钟行情暂只支持沪深 A 股：{ts_code}")


def _time_url(ts_code: str) -> str:
    market_code = ths_market_code(ts_code)
    return THS_TIME_URL_LATEST.format(market_code=market_code)


def _read_stock_rows(collection: Any, ts_code: str, *, source: str) -> list[dict[str, Any]]:
    rows = list(collection.find({"source": source, "ts_code": ts_code}, {"_id": 0}).sort([("trade_date", 1), ("minute", 1)]))
    return rows


def _merge_rows(existing_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in existing_rows + new_rows:
        trade_date = str(row.get("trade_date") or "")
        minute = str(row.get("minute") or "")
        if trade_date and minute:
            merged[(trade_date, minute)] = row
    return [merged[key] for key in sorted(merged)]


def _ensure_indexes(collection: Any, pymongo: Any) -> None:
    collection.create_index([("source", pymongo.ASCENDING), ("ts_code", pymongo.ASCENDING), ("trade_date", pymongo.ASCENDING), ("minute", pymongo.ASCENDING)], unique=True)
    collection.create_index([("trade_date", pymongo.DESCENDING), ("ts_code", pymongo.ASCENDING)])
    collection.create_index([("datetime", pymongo.DESCENDING)])


def _ensure_payload_indexes(collection: Any, pymongo: Any) -> None:
    collection.create_index(
        [("ts_code", pymongo.ASCENDING), ("payload_type", pymongo.ASCENDING), ("trade_date", pymongo.ASCENDING)],
        unique=True,
    )
    collection.create_index([("fetched_at", pymongo.DESCENDING)])


def _mongo_uri(database: str) -> str:
    direct_uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    if direct_uri:
        return direct_uri
    host = os.getenv("MONGO_HOST", "127.0.0.1")
    port = int(os.getenv("MONGO_PORT", "27017"))
    user = os.getenv("MONGO_USER", "")
    password = os.getenv("MONGO_PASSWORD", "")
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if user and password:
        encoded_user = urllib.parse.quote_plus(user)
        encoded_password = urllib.parse.quote_plus(password)
        return f"mongodb://{encoded_user}:{encoded_password}@{host}:{port}/{database}?authSource={auth_source}"
    return f"mongodb://{host}:{port}/{database}"


def _normalize_source(source: str) -> str:
    value = str(source or "tdx").strip().lower()
    aliases = {
        "mootdx": "tdx",
        "tongdaxin": "tdx",
        "通达信": "tdx",
        "10jqka": "ths",
        "tonghuashun": "ths",
        "同花顺": "ths",
    }
    return aliases.get(value, value)


def _parse_tdx_datetime(record: dict[str, Any]) -> datetime | None:
    raw = record.get("datetime")
    if raw:
        text = str(raw)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
    try:
        return datetime(
            int(record.get("year")),
            int(record.get("month")),
            int(record.get("day")),
            int(record.get("hour")),
            int(record.get("minute")),
        )
    except (TypeError, ValueError):
        return None


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_text(row.get("source")), _text(row.get("trade_date")), _text(row.get("minute")))
        if all(key):
            merged[key] = row
    return [merged[key] for key in sorted(merged)]


def _minute_datetime(trade_date: str, minute: str) -> datetime:
    return datetime.strptime(f"{trade_date}{minute}", "%Y%m%d%H%M").replace(tzinfo=CN_TZ)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _near_zero(value: float | None) -> bool:
    return value is not None and abs(value) < 1e-20


def _text(value: Any) -> str:
    return str(value or "").strip()


def _local_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for key in ("datetime", "fetched_at"):
        value = item.get(key)
        if isinstance(value, datetime):
            if key == "datetime":
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                value = value.astimezone(CN_TZ)
                item[key] = value.replace(tzinfo=None).isoformat()
            else:
                item[key] = value.isoformat()
    return item
