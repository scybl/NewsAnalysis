from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


MINUTE_UPLOAD_LOG = "minute-cold-stock-year-upload.log"
MINUTE_UPLOAD_PID = "minute-cold-stock-year-upload.pid"
HEAVY_IO = "heavy_io"
NORMAL_IO = "normal"

_LOG_LINE = re.compile(r"^\[(?P<prefix>[^\]]+)\]\[(?P<ts>[^\]]+)\]\s*(?P<body>.*)$")
_RUNNING_STATUSES = {"queued", "running", "stopping", "running_unknown_pid"}
_FAILED_STATUSES = {"failed", "failed_or_stopped"}
_WARNING_STATUSES = {"warning", "running_unknown_pid"}
_SCHEDULER_TASK_KINDS = {"daily_market", "idle_stock_prefetch", "kaipanla", "data_random_audit", "stock_storage_health"}


def build_ops_snapshot(
    project_root: Path,
    *,
    crawler_snapshot_fn: Callable[[], dict[str, Any]] | None = None,
    pid_checker: Callable[[int], bool] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    local_data = root / "local_data"
    logs_dir = root / "logs"
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    resources: dict[str, Any] = {"files": {}}
    admin_tasks = _read_admin_tasks(local_data / "admin_tasks.json", resources)

    tasks = [
        _minute_cold_upload_task(logs_dir, pid_checker=pid_checker or _pid_exists, now=now_utc),
        _scheduler_task(
            "daily_market_scheduler",
            "每日股票数据更新",
            "daily_market",
            local_data / "daily_market_scheduler.json",
            admin_tasks,
            resource_level=HEAVY_IO,
            resources=resources,
        ),
        _scheduler_task(
            "idle_stock_prefetch",
            "空闲股票资料包预抓",
            "idle_stock_prefetch",
            local_data / "idle_stock_prefetch_scheduler.json",
            admin_tasks,
            resource_level=None,
            resources=resources,
        ),
        _scheduler_task(
            "kaipanla_scheduler",
            "开盘啦数据抓取",
            "kaipanla",
            local_data / "kaipanla_scheduler.json",
            admin_tasks,
            resource_level=NORMAL_IO,
            resources=resources,
        ),
        _scheduler_task(
            "data_random_audit_scheduler",
            "空闲数据随机抽检",
            "data_random_audit",
            local_data / "data_random_audit_scheduler.json",
            admin_tasks,
            resource_level=NORMAL_IO,
            resources=resources,
        ),
        _scheduler_task(
            "stock_storage_health_scheduler",
            "股票存储健康检查",
            "stock_storage_health",
            local_data / "stock_storage_health_scheduler.json",
            admin_tasks,
            resource_level=NORMAL_IO,
            resources=resources,
        ),
    ]
    tasks.extend(_active_admin_task_snapshots(admin_tasks))
    tasks.append(_news_crawler_task(crawler_snapshot_fn, resources))

    return {
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "overall": _overall(tasks),
        "tasks": tasks,
        "data": {},
        "resources": resources,
    }


def active_heavy_io_tasks(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = snapshot.get("tasks") or []
    if not isinstance(tasks, list):
        return []
    return [
        task
        for task in tasks
        if isinstance(task, dict)
        and task.get("resource_level") == HEAVY_IO
        and (task.get("running") or task.get("status") in _RUNNING_STATUSES)
    ]


def _minute_cold_upload_task(
    logs_dir: Path,
    *,
    pid_checker: Callable[[int], bool],
    now: datetime,
) -> dict[str, Any]:
    log_file = logs_dir / MINUTE_UPLOAD_LOG
    pid_file = logs_dir / MINUTE_UPLOAD_PID
    task = _base_task(
        "minute_cold_stock_year_upload",
        "分时冷数据上传",
        "stock_minute_cold_upload",
        resource_level=HEAVY_IO,
        enabled=True,
        log_file=log_file,
        pid_file=pid_file,
    )
    pid, pid_error = _read_pid(pid_file)
    parsed = _parse_minute_log(log_file, now)
    task["last_error"] = parsed.get("last_error") or pid_error
    task["last_event"] = parsed.get("event") or ""
    task["last_event_at"] = parsed.get("event_at") or ""
    task["last_event_age_seconds"] = parsed.get("age_seconds")
    task["progress"] = parsed.get("progress") or {}
    task["details"] = parsed.get("details") or {}
    if pid is not None:
        task["pid"] = pid

    event = str(parsed.get("event") or "")
    event_age = parsed.get("age_seconds")
    pid_alive = bool(pid and pid_checker(pid))
    recent_without_pid = event_age is not None and event_age <= 600

    if not log_file.exists() and pid is None:
        task["status"] = "unknown"
    elif event == "summary":
        task["status"] = "succeeded"
    elif event == "upload_start" and event_age is not None and event_age > 900:
        task["status"] = "warning"
        task["running"] = pid_alive
        task["last_error"] = task["last_error"] or "upload_start 后超过 15 分钟没有 upload_done。"
    elif pid_alive:
        task["status"] = "running"
        task["running"] = True
    elif pid is None and recent_without_pid:
        task["status"] = "running_unknown_pid"
        task["running"] = True
    elif event:
        task["status"] = "failed_or_stopped"
        task["last_error"] = task["last_error"] or "进程不存在，且日志中没有 summary。"
    return task


def _active_admin_task_snapshots(admin_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots = []
    for item in sorted(admin_tasks, key=lambda task: float(task.get("updated_epoch") or task.get("created_epoch") or 0), reverse=True):
        status = str(item.get("status") or "")
        kind = str(item.get("kind") or "admin_task")
        if kind in _SCHEDULER_TASK_KINDS or status not in _RUNNING_STATUSES:
            continue
        task_id = str(item.get("task_id") or "")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        resource_level = HEAVY_IO if kind == "spider" and str(metadata.get("source") or "") == "ths_market" else NORMAL_IO
        task = _base_task(
            f"admin_task:{task_id or kind}",
            str(item.get("title") or kind),
            kind,
            resource_level=resource_level,
            enabled=True,
        )
        task["task_id"] = task_id
        task["status"] = "running"
        task["running"] = True
        task["last_event"] = _last_event(item)
        task["last_error"] = str(item.get("error") or "")
        task["updated_at"] = str(item.get("updated_at") or "")
        task["details"] = {"metadata": metadata}
        snapshots.append(task)
    return snapshots[:20]


def _scheduler_task(
    task_id: str,
    title: str,
    kind: str,
    config_path: Path,
    admin_tasks: list[dict[str, Any]],
    *,
    resource_level: str | None,
    resources: dict[str, Any],
) -> dict[str, Any]:
    config, config_error = _read_json_file(config_path, resources)
    latest = _latest_task(admin_tasks, kind, str((config or {}).get("last_task_id") or ""))
    enabled = bool((config or {}).get("enabled")) if isinstance(config, dict) else False
    if kind == "idle_stock_prefetch" and resource_level is None:
        resource_level = HEAVY_IO if bool((config or {}).get("minutes_enabled", True)) else NORMAL_IO
    task = _base_task(task_id, title, kind, resource_level=resource_level or NORMAL_IO, enabled=enabled)
    task["config_file"] = str(config_path)
    task["status"] = "unknown" if config is None else ("paused" if not enabled else "idle")
    task["last_error"] = config_error or str((config or {}).get("last_error") or "")
    task["details"] = {"scheduler": _public_scheduler_config(config or {})}
    task["last_run_at"] = str((config or {}).get("last_run_at") or "")
    task["task_id"] = str((latest or {}).get("task_id") or (config or {}).get("last_task_id") or "")

    if latest:
        latest_status = str(latest.get("status") or "")
        task["last_event"] = _last_event(latest)
        task["last_error"] = task["last_error"] or str(latest.get("error") or "")
        task["updated_at"] = str(latest.get("updated_at") or "")
        if latest_status in _RUNNING_STATUSES:
            task["status"] = "running"
            task["running"] = True
        elif latest_status in _FAILED_STATUSES:
            task["status"] = "failed"
        elif task["status"] != "paused" and latest_status in {"succeeded", "stopped", "cancelled"}:
            task["status"] = "idle"
    if task["last_error"] and task["status"] == "idle":
        task["status"] = "failed"
    return task


def _news_crawler_task(
    crawler_snapshot_fn: Callable[[], dict[str, Any]] | None,
    resources: dict[str, Any],
) -> dict[str, Any]:
    task = _base_task("news_crawler", "NewsCrawler 采集状态", "news_crawler", resource_level=NORMAL_IO, enabled=True)
    if crawler_snapshot_fn is None:
        task["status"] = "unknown"
        resources["news_crawler"] = {"status": "not_configured", "error": ""}
        return task
    try:
        snapshot = crawler_snapshot_fn() or {}
        summary = snapshot.get("summary") or {}
        alerts = snapshot.get("alerts") or []
        running_count = _int(summary.get("running_count"))
        expired_count = _int(summary.get("expired_running_count"))
        task["running"] = running_count > 0
        task["status"] = "warning" if alerts or expired_count else ("running" if running_count else "idle")
        task["last_event"] = "crawler_status_snapshot"
        task["details"] = {"summary": summary, "alerts": alerts[:5]}
        task["last_error"] = "; ".join(_alert_message(item) for item in alerts[:3] if item)
        resources["news_crawler"] = {"status": "ok", "error": ""}
    except Exception as exc:  # noqa: BLE001 - ops status must stay readable
        task["status"] = "unknown"
        task["last_error"] = str(exc)
        resources["news_crawler"] = {"status": "error", "error": str(exc)}
    return task


def _alert_message(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("message") or item.get("title") or item)
    return str(item)


def _base_task(
    task_id: str,
    title: str,
    kind: str,
    *,
    resource_level: str,
    enabled: bool,
    log_file: Path | None = None,
    pid_file: Path | None = None,
) -> dict[str, Any]:
    task = {
        "id": task_id,
        "title": title,
        "kind": kind,
        "status": "idle",
        "enabled": bool(enabled),
        "running": False,
        "resource_level": resource_level,
        "progress": {},
        "last_event": "",
        "last_error": "",
    }
    if log_file is not None:
        task["log_file"] = str(log_file)
    if pid_file is not None:
        task["pid_file"] = str(pid_file)
    return task


def _read_admin_tasks(path: Path, resources: dict[str, Any]) -> list[dict[str, Any]]:
    payload, _error = _read_json_file(path, resources)
    if isinstance(payload, dict):
        items = payload.get("tasks") or []
    else:
        items = payload or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _read_json_file(path: Path, resources: dict[str, Any]) -> tuple[Any | None, str]:
    key = path.stem
    files = resources.setdefault("files", {})
    if not path.exists():
        files[key] = {"path": str(path), "status": "missing", "error": ""}
        return None, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        files[key] = {"path": str(path), "status": "ok", "error": ""}
        return payload, ""
    except Exception as exc:  # noqa: BLE001 - one bad file must not break the whole snapshot
        files[key] = {"path": str(path), "status": "error", "error": str(exc)}
        return None, str(exc)


def _latest_task(admin_tasks: list[dict[str, Any]], kind: str, task_id: str = "") -> dict[str, Any] | None:
    if task_id:
        for item in admin_tasks:
            if str(item.get("task_id") or "") == task_id:
                return item
    candidates = [item for item in admin_tasks if str(item.get("kind") or "") == kind]
    if not candidates:
        return None
    return max(candidates, key=lambda item: float(item.get("updated_epoch") or item.get("created_epoch") or 0))


def _last_event(task: dict[str, Any]) -> str:
    events = task.get("events") or []
    if isinstance(events, list) and events:
        event = events[-1] if isinstance(events[-1], dict) else {}
        return str(event.get("stage") or event.get("message") or "")
    return str(task.get("status") or "")


def _public_scheduler_config(config: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "enabled",
        "time",
        "idle_seconds",
        "interval_seconds",
        "minutes_enabled",
        "sample_size",
        "cold_read_samples",
        "cold_compare_samples",
        "full_history",
        "features",
        "last_run_date",
        "last_run_at",
        "last_task_id",
        "last_result",
        "last_error",
    }
    return {key: config.get(key) for key in allowed if key in config}


def _parse_minute_log(log_file: Path, now: datetime) -> dict[str, Any]:
    if not log_file.exists():
        return {}
    last: dict[str, Any] = {}
    parse_errors: list[str] = []
    for line in _tail_lines(log_file, lines=2000):
        try:
            event = _parse_log_line(line)
        except Exception as exc:  # noqa: BLE001
            parse_errors.append(str(exc))
            continue
        if event:
            last = event
    if not last:
        return {"last_error": parse_errors[-1] if parse_errors else "没有可解析的 minute-cold 日志事件。"}

    event_at = _parse_datetime(str(last.get("ts") or ""))
    age_seconds = int((now - event_at).total_seconds()) if event_at else None
    fields = dict(last.get("fields") or {})
    current, total = _current_total(fields)
    percent = _float(fields.get("percent"))
    if percent is None and current is not None and total:
        percent = round(current * 100 / total, 2)
    details = {
        key: _coerce_value(value)
        for key, value in fields.items()
        if key
        in {
            "source",
            "ts_code",
            "year",
            "days",
            "size",
            "rows",
            "remote",
            "reason",
            "status",
            "path",
            "error",
            "task",
        }
    }
    progress = {}
    if current is not None:
        progress["current"] = current
    if total is not None:
        progress["total"] = total
    if percent is not None:
        progress["percent"] = percent
    return {
        "event": str(last.get("event") or ""),
        "event_at": event_at.isoformat().replace("+00:00", "Z") if event_at else "",
        "age_seconds": max(0, age_seconds) if age_seconds is not None else None,
        "progress": progress,
        "details": details,
        "last_error": str(fields.get("error") or (parse_errors[-1] if parse_errors else "")),
    }


def _parse_log_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    match = _LOG_LINE.match(text)
    if not match:
        raise ValueError(f"无法解析日志行：{text[:120]}")
    body = match.group("body").strip()
    if not body:
        return None
    tokens = shlex.split(body)
    if not tokens:
        return None
    fields: dict[str, str] = {}
    event = ""
    start = 0
    if "=" not in tokens[0]:
        event = tokens[0]
        start = 1
    for token in tokens[start:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key.strip()] = value.strip()
    event = event or fields.get("event", "")
    return {"prefix": match.group("prefix"), "ts": match.group("ts"), "event": event, "fields": fields}


def _tail_lines(path: Path, *, lines: int, max_bytes: int = 256 * 1024) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read().decode("utf-8", errors="replace")
    if start:
        data = data.split("\n", 1)[-1]
    return data.splitlines()[-lines:]


def _read_pid(pid_file: Path) -> tuple[int | None, str]:
    if not pid_file.exists():
        return None, ""
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        return int(text), "" if text else "pid 文件为空。"
    except Exception as exc:  # noqa: BLE001
        return None, f"pid 文件解析失败：{exc}"


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _current_total(fields: dict[str, Any]) -> tuple[int | None, int | None]:
    current_value = str(fields.get("current") or "")
    if "/" in current_value:
        left, right = current_value.split("/", 1)
        return _int_or_none(left), _int_or_none(right)
    return _int_or_none(current_value), _int_or_none(fields.get("total"))


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _overall(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    running = [task for task in tasks if task.get("running")]
    heavy_running = [task for task in running if task.get("resource_level") == HEAVY_IO]
    warnings = []
    for task in tasks:
        if task.get("last_error"):
            warnings.append(f"{task.get('title')}: {task.get('last_error')}")
    if any(task.get("status") in _FAILED_STATUSES for task in tasks):
        status = "danger"
    elif any(task.get("status") in _WARNING_STATUSES for task in tasks) or warnings:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "running_count": len(running),
        "heavy_io_running": bool(heavy_running),
        "warnings": warnings[:12],
    }


def _coerce_value(value: Any) -> Any:
    text = str(value)
    parsed_int = _int_or_none(text)
    if parsed_int is not None and text == str(parsed_int):
        return parsed_int
    parsed_float = _float(text)
    if parsed_float is not None and "." in text:
        return parsed_float
    return value


def _int(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _int_or_none(value: Any) -> int | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None
