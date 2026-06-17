from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import StockDataCollector
from .analysis_frameworks import ANALYSIS_FRAMEWORKS, build_all_analysis_dossiers, build_analysis_dossier, get_analysis_framework, list_analysis_frameworks
from .config import PROJECT_ROOT
from .dossier import build_dossier
from .field_labels import build_table_datasets
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


def stock_exists(ts_code: str) -> bool:
    ensure_current_layout(ts_code)
    return (current_dir(ts_code) / "full_data.json").exists()


def list_local_stock_codes() -> list[str]:
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
    return codes


def stock_status(code: str) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    base_dir = stock_dir(ts_code)
    metadata_path = base_dir / "metadata.json"
    if not metadata_path.exists():
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
    metadata = read_json(metadata_path)
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
    ensure_current_layout(ts_code)
    base_dir = stock_dir(ts_code)
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

    temp_dir = LOCAL_DATA_DIR / f".{ts_code}.tmp_{timestamp()}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    ensure_dir(temp_dir)

    try:
        full_data = StockDataCollector(client).collect(ts_code, temp_dir, years=years, full_history=full_history)
        _validate_full_data(full_data)
        dossier = build_dossier(full_data)
        analysis_dossiers = build_all_analysis_dossiers(dossier)

        previous_updated_at = _metadata_updated_at(base_dir / "metadata.json")
        snapshot_path = archive_current(ts_code, previous_updated_at)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        ensure_dir(target_dir)

        shutil.move(str(temp_dir / "raw"), str(target_dir / "raw"))
        write_json(target_dir / "full_data.json", full_data)
        write_json(target_dir / "dossier.json", dossier)
        for key, analysis_dossier in analysis_dossiers.items():
            write_json(target_dir / f"{key}_dossier.json", analysis_dossier)
        updated_at = timestamp()
        metadata = {
            "ts_code": ts_code,
            "years": years,
            "full_history": full_history,
            "updated_at": updated_at,
            "current_dir": str(target_dir),
            "latest_snapshot": str(snapshot_path) if snapshot_path else "",
            "snapshots": list_snapshots(ts_code),
            "date_range": full_data.get("date_range", {}),
            "dataset_rows": {name: len(rows) for name, rows in full_data.get("datasets", {}).items()},
            "fetch_errors": full_data.get("fetch_errors", []),
        }
        write_json(base_dir / "metadata.json", metadata)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    payload = build_local_stock_payload(ts_code)
    payload["cache_hit"] = False
    payload["cache_max_age_seconds"] = max_age_seconds
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
    full_path = current_dir(ts_code) / "full_data.json"
    if not full_path.exists():
        return {"ok": False, "ts_code": ts_code, "target_date": date, "status": "failed", "error": "本地资料包不存在，请先全量更新。"}

    full_data = read_json(full_path)
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
        write_json(current_dir(ts_code) / "raw" / f"{dataset}.json", {"fields": list(merged[0].keys()) if merged else [], "records": merged})

    full_data["date_range"] = {
        **(full_data.get("date_range") or {}),
        "end_date": max(str((full_data.get("date_range") or {}).get("end_date") or ""), date),
        "full_history": bool((full_data.get("date_range") or {}).get("full_history", True)),
    }
    full_data["fetch_errors"] = fetch_errors
    _write_stock_outputs(ts_code, full_data)

    metadata_path = stock_dir(ts_code) / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {"ts_code": ts_code}
    metadata.update(
        {
            "ts_code": ts_code,
            "updated_at": timestamp(),
            "current_dir": str(current_dir(ts_code)),
            "snapshots": list_snapshots(ts_code),
            "date_range": full_data.get("date_range", {}),
            "dataset_rows": {name: len(rows) for name, rows in datasets.items()},
            "fetch_errors": fetch_errors,
            "daily_market_updated_at": timestamp(),
            "daily_market_target_date": date,
            "latest_daily_date": _latest_trade_date(datasets.get("daily", [])),
        }
    )
    write_json(metadata_path, metadata)
    return {
        "ok": True,
        "ts_code": ts_code,
        "target_date": date,
        "status": "updated",
        "latest_daily_date": metadata["latest_daily_date"],
        "changed": changed,
        "fetch_errors": fetch_errors,
    }


def build_local_stock_payload(code: str) -> dict[str, Any]:
    ts_code = normalize_ts_code(code)
    ensure_current_layout(ts_code)
    base_dir = stock_dir(ts_code)
    target_dir = current_dir(ts_code)
    full_path = target_dir / "full_data.json"
    if not full_path.exists():
        raise FileNotFoundError(f"本地还没有 {ts_code} 的数据，请先更新本地数据。")

    full_data = read_json(full_path)
    metadata_path = base_dir / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
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
        "date_range": full_data.get("date_range", {}),
        "datasets": build_table_datasets(full_data.get("datasets", {})),
        "fetch_errors": full_data.get("fetch_errors", []),
    }


def _write_stock_outputs(ts_code: str, full_data: dict[str, Any]) -> None:
    target_dir = current_dir(ts_code)
    dossier = build_dossier(full_data)
    analysis_dossiers = build_all_analysis_dossiers(dossier)
    write_json(target_dir / "full_data.json", full_data)
    write_json(target_dir / "dossier.json", dossier)
    for key, analysis_dossier in analysis_dossiers.items():
        write_json(target_dir / f"{key}_dossier.json", analysis_dossier)


def _latest_trade_date(records: list[dict[str, Any]]) -> str:
    dates = [str(row.get("trade_date") or "") for row in records if row.get("trade_date")]
    return max(dates) if dates else ""


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
        "dataset_rows": {name: len(rows) for name, rows in full_data.get("datasets", {}).items()},
        "fetch_errors": full_data.get("fetch_errors", []),
    }
    write_json(stock_dir(ts_code) / "metadata.json", metadata)
    return build_local_stock_payload(ts_code)


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
        write_json(path, build_analysis_dossier(framework.key, read_json(dossier_path)))
        return path
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
