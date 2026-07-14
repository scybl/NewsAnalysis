from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .utils import ensure_dir, timestamp, write_json


HEAVY_IO = "heavy_io"
NORMAL_IO = "normal"
QUEUE_OWNER = "resource_queue"

TaskHandler = Callable[[str, dict[str, Any]], Any]
PressureReader = Callable[[], dict[str, Any]]
ExternalBlockers = Callable[[str], list[dict[str, Any]]]
SleepFunc = Callable[[float], None]


def read_system_pressure() -> dict[str, Any]:
    meminfo = _read_meminfo()
    mem_available_mb = int(meminfo.get("MemAvailable", 0) / 1024)
    swap_total = int(meminfo.get("SwapTotal", 0))
    swap_free = int(meminfo.get("SwapFree", 0))
    swap_used_percent = 0.0
    if swap_total > 0:
        swap_used_percent = round((swap_total - swap_free) * 100 / swap_total, 1)
    load_1m = load_5m = load_15m = 0.0
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        pass
    return {
        "mem_available_mb": mem_available_mb,
        "swap_used_percent": swap_used_percent,
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
    }


def pressure_reasons(
    pressure: dict[str, Any],
    *,
    resource_level: str,
    min_available_mb: int | None = None,
    max_swap_used_percent: float | None = None,
    max_load_1m: float | None = None,
) -> list[str]:
    heavy = resource_level == HEAVY_IO
    min_available_mb = min_available_mb if min_available_mb is not None else (1200 if heavy else 700)
    max_swap_used_percent = max_swap_used_percent if max_swap_used_percent is not None else (35.0 if heavy else 60.0)
    max_load_1m = max_load_1m if max_load_1m is not None else (6.0 if heavy else 12.0)
    reasons: list[str] = []
    mem_available = int(pressure.get("mem_available_mb") or 0)
    swap_used = float(pressure.get("swap_used_percent") or 0)
    load_1m = float(pressure.get("load_1m") or 0)
    if mem_available and mem_available < min_available_mb:
        reasons.append(f"可用内存 {mem_available}MB 低于 {min_available_mb}MB")
    if swap_used > max_swap_used_percent:
        reasons.append(f"swap 使用率 {swap_used:g}% 高于 {max_swap_used_percent:g}%")
    if load_1m > max_load_1m:
        reasons.append(f"1 分钟负载 {load_1m:g} 高于 {max_load_1m:g}")
    return reasons


def throttle_reasons(
    pressure: dict[str, Any],
    *,
    resource_level: str,
    min_available_mb: int | None = None,
    max_swap_used_percent: float | None = None,
) -> list[str]:
    heavy = resource_level == HEAVY_IO
    min_available_mb = min_available_mb if min_available_mb is not None else (700 if heavy else 350)
    max_swap_used_percent = max_swap_used_percent if max_swap_used_percent is not None else (85.0 if heavy else 92.0)
    reasons: list[str] = []
    mem_available = int(pressure.get("mem_available_mb") or 0)
    swap_used = float(pressure.get("swap_used_percent") or 0)
    if mem_available and mem_available < min_available_mb:
        reasons.append(f"可用内存 {mem_available}MB 低于运行阈值 {min_available_mb}MB")
    if swap_used > max_swap_used_percent:
        reasons.append(f"swap 使用率 {swap_used:g}% 高于运行阈值 {max_swap_used_percent:g}%")
    return reasons


class ResourceAwareTaskQueue:
    def __init__(
        self,
        path: Path,
        task_registry: Any,
        *,
        pressure_reader: PressureReader | None = None,
        external_blockers: ExternalBlockers | None = None,
        sleep_func: SleepFunc | None = None,
        poll_seconds: float = 5.0,
        autostart: bool = False,
    ):
        self.path = path
        self.task_registry = task_registry
        self.pressure_reader = pressure_reader or read_system_pressure
        self.external_blockers = external_blockers or (lambda _task_id: [])
        self.sleep_func = sleep_func or time.sleep
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.lock = threading.Lock()
        self.handlers: dict[str, TaskHandler] = {}
        self.items: dict[str, dict[str, Any]] = self._load_items()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        if autostart:
            self.start()

    def register(self, handler_key: str, handler: TaskHandler) -> None:
        self.handlers[str(handler_key)] = handler

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="resource-aware-task-queue", daemon=True)
        self.thread.start()

    def enqueue(
        self,
        *,
        task_id: str,
        handler_key: str,
        kind: str,
        title: str,
        payload: dict[str, Any] | None = None,
        resource_level: str = NORMAL_IO,
    ) -> dict[str, Any]:
        now = time.time()
        item = {
            "task_id": task_id,
            "handler_key": handler_key,
            "kind": kind,
            "title": title,
            "payload": payload or {},
            "resource_level": resource_level,
            "status": "queued",
            "enqueued_at": timestamp(),
            "enqueued_epoch": now,
            "updated_at": timestamp(),
            "updated_epoch": now,
            "run_after_epoch": now,
            "defer_count": 0,
            "last_pressure": {},
            "last_defer_reason": "",
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        with self.lock:
            existing = self.items.get(task_id)
            if existing and existing.get("status") in {"queued", "deferred", "running"}:
                return json.loads(json.dumps(existing, ensure_ascii=False, default=str))
            self.items[task_id] = item
            self._trim_locked()
            self._write_locked()
        self.task_registry.update_task(
            task_id,
            metadata={"queued_by": QUEUE_OWNER, "queue_status": "queued", "resource_level": resource_level},
        )
        self.task_registry.add_event(
            task_id,
            "queued",
            "任务已进入资源队列，等待内存和 IO 压力允许后执行。",
            {"resource_level": resource_level},
        )
        return json.loads(json.dumps(item, ensure_ascii=False, default=str))

    def snapshot(self, limit: int = 80) -> dict[str, Any]:
        with self.lock:
            items = sorted(self.items.values(), key=lambda item: float(item.get("enqueued_epoch") or 0))[:limit]
            counts: dict[str, int] = {}
            for item in self.items.values():
                status = str(item.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
        return {"items": json.loads(json.dumps(items, ensure_ascii=False, default=str)), "counts": counts}

    def _loop(self) -> None:
        while not self.stop_event.wait(self.poll_seconds):
            item = self._next_ready_item()
            if not item:
                continue
            self._run_or_defer(item)

    def _next_ready_item(self) -> dict[str, Any] | None:
        now = time.time()
        with self.lock:
            ordered = sorted(
                [
                    item
                    for item in self.items.values()
                    if item.get("status") in {"queued", "deferred"}
                ],
                key=lambda row: float(row.get("enqueued_epoch") or 0),
            )
            if not ordered:
                return None
            item = ordered[0]
            if float(item.get("run_after_epoch") or 0) > now:
                return None
            return json.loads(json.dumps(item, ensure_ascii=False, default=str))

    def _run_or_defer(self, item: dict[str, Any]) -> None:
        task_id = str(item.get("task_id") or "")
        handler_key = str(item.get("handler_key") or "")
        handler = self.handlers.get(handler_key)
        if handler is None:
            self._defer(item, "任务处理器尚未注册，等待服务完成初始化。", {})
            return
        blockers = self.external_blockers(task_id)
        if blockers:
            title = blockers[0].get("title") or blockers[0].get("id") or "其他重任务"
            self._defer(item, f"已有任务正在运行：{title}", {"blocking_tasks": blockers[:5]})
            return
        pressure = self.pressure_reader()
        reasons = pressure_reasons(pressure, resource_level=str(item.get("resource_level") or NORMAL_IO))
        if reasons:
            self._defer(item, "；".join(reasons), pressure)
            return
        self._mark_running(item, pressure)
        try:
            handler(task_id, dict(item.get("payload") or {}))
            final_status = self._task_status(task_id)
            with self.lock:
                current = self.items.get(task_id)
                if current:
                    current["status"] = "failed" if final_status == "failed" else "succeeded"
                    current["finished_at"] = timestamp()
                    current["updated_at"] = timestamp()
                    current["updated_epoch"] = time.time()
                    self._write_locked()
        except Exception as exc:  # noqa: BLE001 - queue must keep serving later tasks
            self.task_registry.update_task(task_id, status="failed", error=str(exc))
            self.task_registry.add_event(task_id, "failed", "队列任务执行失败。", {"error": str(exc)})
            with self.lock:
                current = self.items.get(task_id)
                if current:
                    current["status"] = "failed"
                    current["error"] = str(exc)
                    current["finished_at"] = timestamp()
                    current["updated_at"] = timestamp()
                    current["updated_epoch"] = time.time()
                    self._write_locked()

    def _mark_running(self, item: dict[str, Any], pressure: dict[str, Any]) -> None:
        task_id = str(item.get("task_id") or "")
        with self.lock:
            current = self.items.get(task_id)
            if not current or current.get("status") not in {"queued", "deferred"}:
                return
            current["status"] = "running"
            current["started_at"] = current.get("started_at") or timestamp()
            current["updated_at"] = timestamp()
            current["updated_epoch"] = time.time()
            current["last_pressure"] = pressure
            self._write_locked()
        self.task_registry.update_task(task_id, status="running", metadata={"queue_status": "running"})
        self.task_registry.add_event(task_id, "running", "资源队列开始执行任务。", {"pressure": pressure})

    def _defer(self, item: dict[str, Any], reason: str, pressure: dict[str, Any]) -> None:
        task_id = str(item.get("task_id") or "")
        with self.lock:
            current = self.items.get(task_id)
            if not current or current.get("status") not in {"queued", "deferred"}:
                return
            defer_count = int(current.get("defer_count") or 0) + 1
            delay = min(1800, 60 * (2 ** min(defer_count - 1, 5)))
            current["status"] = "deferred"
            current["defer_count"] = defer_count
            current["run_after_epoch"] = time.time() + delay
            current["last_defer_reason"] = reason
            current["last_pressure"] = pressure
            current["updated_at"] = timestamp()
            current["updated_epoch"] = time.time()
            self._write_locked()
        self.task_registry.update_task(
            task_id,
            metadata={"queue_status": "deferred", "queue_delay_seconds": delay, "queue_defer_count": defer_count},
        )
        self.task_registry.add_event(
            task_id,
            "queued",
            f"资源承压，任务延后 {delay} 秒后重试：{reason}",
            {"delay_seconds": delay, "defer_count": defer_count, "pressure": pressure},
        )

    def checkpoint(
        self,
        task_id: str,
        *,
        resource_level: str | None = None,
        stage: str = "",
        details: dict[str, Any] | None = None,
        min_available_mb: int | None = None,
        max_swap_used_percent: float | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        paused = False
        pause_count = 0
        last_event_epoch = 0.0
        level = resource_level or self._item_resource_level(task_id)
        while not self.stop_event.is_set():
            pressure = self.pressure_reader()
            reasons = throttle_reasons(
                pressure,
                resource_level=level,
                min_available_mb=min_available_mb,
                max_swap_used_percent=max_swap_used_percent,
            )
            if not reasons:
                pause_seconds = int(time.time() - started)
                if paused:
                    self._mark_throttle_resumed(task_id, stage=stage, pause_seconds=pause_seconds, pressure=pressure)
                return {"paused": paused, "pause_seconds": pause_seconds, "pressure": pressure}
            pause_count += 1
            delay = min(30.0, 5.0 * (2 ** min(pause_count - 1, 3)))
            reason = "；".join(reasons)
            now = time.time()
            if not paused or now - last_event_epoch >= 60:
                self._mark_throttled(
                    task_id,
                    reason=reason,
                    pressure=pressure,
                    delay_seconds=delay,
                    stage=stage,
                    details=details or {},
                    pause_count=pause_count,
                )
                last_event_epoch = now
            paused = True
            self.sleep_func(delay)
        return {"paused": paused, "pause_seconds": int(time.time() - started), "pressure": {}}

    def _item_resource_level(self, task_id: str) -> str:
        with self.lock:
            item = self.items.get(task_id) or {}
            return str(item.get("resource_level") or NORMAL_IO)

    def _mark_throttled(
        self,
        task_id: str,
        *,
        reason: str,
        pressure: dict[str, Any],
        delay_seconds: float,
        stage: str,
        details: dict[str, Any],
        pause_count: int,
    ) -> None:
        with self.lock:
            current = self.items.get(task_id)
            if current:
                current["last_throttle_reason"] = reason
                current["last_pressure"] = pressure
                current["throttle_count"] = int(current.get("throttle_count") or 0) + 1
                current["updated_at"] = timestamp()
                current["updated_epoch"] = time.time()
                self._write_locked()
        self.task_registry.update_task(
            task_id,
            metadata={"queue_status": "throttled", "queue_throttle_reason": reason, "queue_throttle_stage": stage},
        )
        self.task_registry.add_event(
            task_id,
            "throttled",
            f"资源承压，当前任务暂停 {int(delay_seconds)} 秒后重试：{reason}",
            {"stage": stage, "pressure": pressure, "details": details, "pause_count": pause_count},
        )

    def _mark_throttle_resumed(self, task_id: str, *, stage: str, pause_seconds: int, pressure: dict[str, Any]) -> None:
        with self.lock:
            current = self.items.get(task_id)
            if current:
                current["last_throttle_reason"] = ""
                current["last_pressure"] = pressure
                current["updated_at"] = timestamp()
                current["updated_epoch"] = time.time()
                self._write_locked()
        self.task_registry.update_task(task_id, metadata={"queue_status": "running", "queue_throttle_reason": "", "queue_throttle_stage": ""})
        self.task_registry.add_event(
            task_id,
            "resumed",
            f"资源恢复，任务继续执行；本次暂停约 {pause_seconds} 秒。",
            {"stage": stage, "pause_seconds": pause_seconds, "pressure": pressure},
        )

    def _task_status(self, task_id: str) -> str:
        getter = getattr(self.task_registry, "get_task", None)
        if not callable(getter):
            return ""
        task = getter(task_id) or {}
        return str(task.get("status") or "")

    def _load_items(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            items = payload.get("items", []) if isinstance(payload, dict) else payload
            loaded = {
                str(item.get("task_id")): item
                for item in items
                if isinstance(item, dict) and item.get("task_id")
            }
            for item in loaded.values():
                if item.get("status") == "running":
                    item["status"] = "failed"
                    item["error"] = item.get("error") or "服务重启，运行中的队列任务已中断。"
                    item["finished_at"] = item.get("finished_at") or timestamp()
            return loaded
        except Exception:
            return {}

    def _trim_locked(self) -> None:
        if len(self.items) <= 300:
            return
        ordered = sorted(self.items.values(), key=lambda item: float(item.get("updated_epoch") or 0), reverse=True)
        keep = {str(item.get("task_id")) for item in ordered[:300]}
        for task_id in list(self.items):
            if task_id not in keep:
                self.items.pop(task_id, None)

    def _write_locked(self) -> None:
        ensure_dir(self.path.parent)
        write_json(self.path, {"version": 1, "items": list(self.items.values())})
        os.chmod(self.path, 0o600)


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw_value = line.partition(":")
            parts = raw_value.strip().split()
            if parts:
                values[key] = int(parts[0])
    except OSError:
        return values
    return values
