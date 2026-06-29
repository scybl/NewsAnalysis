from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import StockDataCollector
from .analysis_frameworks import ANALYSIS_FRAMEWORKS, build_all_analysis_dossiers, build_analysis_dossier, get_analysis_framework, list_analysis_frameworks
from .config import PROJECT_ROOT
from .dossier import build_dossier
from .field_labels import build_table_datasets
from .local_data_mongo import (
    list_mongo_stock_codes,
    read_mongo_analysis_dossier,
    read_mongo_dossier,
    read_mongo_full_data,
    read_mongo_metadata,
    save_stock_package_to_mongo,
    sync_current_stock_to_mongo,
)
from .market_dimensions import STOCK_COLLECTIONS, STOCK_DATABASE
from .minute_storage import minute_reference_row_counts, read_external_minute_datasets
from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, today_yyyymmdd, write_json


LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
MIN_REQUIRED_DATASETS = ("stock_basic", "daily", "daily_basic")
DAILY_MARKET_DATASETS = ("daily", "weekly", "monthly", "daily_basic", "adj_factor", "stk_limit", "suspend_d", "moneyflow", "margin_detail")


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
    if not LOCAL_DATA_DIR.exists():
        return sorted(mongo_codes)
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
    return sorted(set(codes) | mongo_codes)


def list_local_stock_summaries() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for ts_code in list_local_stock_codes():
        base_dir = stock_dir(ts_code)
        metadata_path = base_dir / "metadata.json"
        metadata = read_json(metadata_path) if metadata_path.exists() else (read_mongo_metadata(ts_code) or {})
        stock_basic = metadata.get("stock_basic") or {}
        dataset_rows = metadata.get("dataset_rows") or {}
        date_range = metadata.get("date_range") or {}
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
        full_data = StockDataCollector(client).collect(ts_code, temp_dir, years=years, full_history=full_history)
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
            "stock_basic": _stock_identity(full_data),
            "dataset_rows": {
                **{name: len(rows) for name, rows in full_data.get("datasets", {}).items()},
                **minute_reference_row_counts(full_data),
            },
            "fetch_errors": full_data.get("fetch_errors", []),
        }
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
) -> dict[str, Any]:
    date = target_date or today_yyyymmdd()
    selected = [normalize_ts_code(code) for code in (codes or list_local_stock_codes())]
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
    for ts_code in selected:
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
    return result


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
    if latest_daily_date and latest_daily_date >= date:
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
        item["row_count"] = external_counts.get(item["key"], len(item["records"]))
        item["loaded_row_count"] = len(item["records"])
        item["storage"] = "mongodb"
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


def _latest_trade_date(records: list[dict[str, Any]]) -> str:
    dates = [str(row.get("trade_date") or "") for row in records if row.get("trade_date")]
    return max(dates) if dates else ""


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
            merged[date] = row
        else:
            passthrough.append(row)
    return sorted(merged.values(), key=lambda row: str(row.get("trade_date") or ""), reverse=True) + passthrough


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
