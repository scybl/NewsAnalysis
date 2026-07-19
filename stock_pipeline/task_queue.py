from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .utils import ensure_dir, timestamp, write_json


HEAVY_IO = "heavy_io"
LIGHT_IO = "light_io"
NORMAL_IO = "normal"
QUEUE_OWNER = "resource_queue"
QUEUE_SCHEMA_VERSION = 2
CHECKPOINT_VERSION = 1
DEFAULT_PAYLOAD_VERSION = 1
DEFAULT_HANDLER_VERSION = 1
MAX_CANCELLED_ATTEMPTS = 20
DEFAULT_STUCK_SECONDS_BY_RESOURCE = {
    HEAVY_IO: 2 * 60 * 60,
    NORMAL_IO: 45 * 60,
    LIGHT_IO: 30 * 60,
}
DEFAULT_MAX_STUCK_RETRIES = 2
DEFAULT_WATCHDOG_POLL_SECONDS = 5.0

TaskHandler = Callable[[str, dict[str, Any]], Any]
PressureReader = Callable[[], dict[str, Any]]
ExternalBlockers = Callable[[str], list[dict[str, Any]]]
SleepFunc = Callable[[float], None]


class QueueTaskDeferred(RuntimeError):
    def __init__(self, task_id: str, reason: str):
        super().__init__(reason)
        self.task_id = task_id
        self.reason = reason


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
    level = str(resource_level or NORMAL_IO)
    heavy = level == HEAVY_IO
    light = level == LIGHT_IO
    min_available_mb = min_available_mb if min_available_mb is not None else (1200 if heavy else (250 if light else 700))
    max_swap_used_percent = max_swap_used_percent if max_swap_used_percent is not None else (35.0 if heavy else (95.0 if light else 60.0))
    max_load_1m = max_load_1m if max_load_1m is not None else (6.0 if heavy else (16.0 if light else 12.0))
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
    level = str(resource_level or NORMAL_IO)
    heavy = level == HEAVY_IO
    light = level == LIGHT_IO
    min_available_mb = min_available_mb if min_available_mb is not None else (700 if heavy else (200 if light else 350))
    max_swap_used_percent = max_swap_used_percent if max_swap_used_percent is not None else (85.0 if heavy else (97.0 if light else 92.0))
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
        stuck_seconds_by_resource: dict[str, int | float] | None = None,
        max_stuck_retries: int = DEFAULT_MAX_STUCK_RETRIES,
        watchdog_poll_seconds: float = DEFAULT_WATCHDOG_POLL_SECONDS,
        autostart: bool = False,
    ):
        self.path = path
        self.task_registry = task_registry
        self.pressure_reader = pressure_reader or read_system_pressure
        self.external_blockers = external_blockers or (lambda _task_id: [])
        self.sleep_func = sleep_func or time.sleep
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.stuck_seconds_by_resource = {
            **DEFAULT_STUCK_SECONDS_BY_RESOURCE,
            **{str(key): float(value) for key, value in (stuck_seconds_by_resource or {}).items()},
        }
        self.max_stuck_retries = max(0, int(max_stuck_retries))
        self.watchdog_poll_seconds = max(0.1, float(watchdog_poll_seconds))
        self.lock = threading.Lock()
        self.handlers: dict[str, TaskHandler] = {}
        self.handler_versions: dict[str, int] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.items = self._load_items()
        self._abandon_orphaned_recovering_tasks()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        if autostart:
            self.start()

    def register(self, handler_key: str, handler: TaskHandler, *, handler_version: int = DEFAULT_HANDLER_VERSION) -> None:
        key = str(handler_key)
        self.handlers[key] = handler
        self.handler_versions[key] = max(1, int(handler_version))

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
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "task_id": task_id,
            "handler_key": handler_key,
            "handler_version": self.handler_versions.get(str(handler_key), DEFAULT_HANDLER_VERSION),
            "kind": kind,
            "title": title,
            "payload_version": DEFAULT_PAYLOAD_VERSION,
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
            "checkpoint_version": CHECKPOINT_VERSION,
            "checkpoint": {},
            "attempt_count": 0,
            "active_attempt_id": "",
            "started_epoch": 0.0,
            "stuck_retry_count": 0,
            "cancelled_attempt_ids": [],
            "last_cancelled_attempt_id": "",
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
            metadata={
                "queued_by": QUEUE_OWNER,
                "queue_status": "queued",
                "resource_level": resource_level,
                "queue_schema_version": QUEUE_SCHEMA_VERSION,
                "queue_handler_version": item["handler_version"],
                "queue_payload_version": DEFAULT_PAYLOAD_VERSION,
            },
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
            self.force_retry_stuck_tasks()
            item = self._next_ready_item()
            if not item:
                continue
            self._run_or_defer(item)

    def force_retry_stuck_tasks(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now_value = time.time() if now is None else float(now)
        stale: list[tuple[str, str, str]] = []
        with self.lock:
            for item in self.items.values():
                reason = self._stuck_reason(item, now=now_value)
                if reason:
                    stale.append((str(item.get("task_id") or ""), str(item.get("active_attempt_id") or ""), reason))
        actions: list[dict[str, Any]] = []
        for task_id, attempt_id, reason in stale:
            action = self._force_retry_stuck_item(task_id, attempt_id=attempt_id, reason=reason, now=now_value)
            if action:
                actions.append(action)
        return actions

    def _next_ready_item(self) -> dict[str, Any] | None:
        now = time.time()
        with self.lock:
            pending = [
                item
                for item in self.items.values()
                if item.get("status") in {"queued", "deferred"}
            ]
            ready = [
                item
                for item in pending
                if float(item.get("run_after_epoch") or 0) <= now
            ]
            if not ready:
                return None
            scheduled = sorted(
                [item for item in ready if _is_scheduled_item(item)],
                key=_queue_order_key,
            )
            if scheduled:
                item = scheduled[0]
                return json.loads(json.dumps(item, ensure_ascii=False, default=str))
            ordered = sorted(
                ready,
                key=_queue_order_key,
            )
            if not ordered:
                return None
            item = ordered[0]
            return json.loads(json.dumps(item, ensure_ascii=False, default=str))

    def _run_or_defer(self, item: dict[str, Any]) -> None:
        task_id = str(item.get("task_id") or "")
        handler_key = str(item.get("handler_key") or "")
        version_error = self._handler_version_error(item)
        if version_error:
            self._abandon_item(task_id, version_error, item=item)
            return
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
        attempt_id = self._mark_running(item, pressure)
        if not attempt_id:
            return
        payload = dict(item.get("payload") or {})
        payload["_queue_attempt_id"] = attempt_id
        outcome = self._run_handler_with_watchdog(task_id, handler, payload, attempt_id)
        if not self._attempt_is_active(task_id, attempt_id):
            return
        if isinstance(outcome, QueueTaskDeferred):
            return
        if isinstance(outcome, Exception):
            self._mark_failed(task_id, attempt_id, str(outcome), event_message="队列任务执行失败。")
            return
        final_status = self._task_status(task_id)
        with self.lock:
            current = self.items.get(task_id)
            if current and str(current.get("active_attempt_id") or "") == attempt_id:
                current["status"] = "failed" if final_status == "failed" else "succeeded"
                current["active_attempt_id"] = ""
                current["finished_at"] = timestamp()
                current["updated_at"] = timestamp()
                current["updated_epoch"] = time.time()
                self._write_locked()

    def _run_handler_with_watchdog(
        self,
        task_id: str,
        handler: TaskHandler,
        payload: dict[str, Any],
        attempt_id: str,
    ) -> Exception | None:
        outcome: dict[str, Exception | None] = {"exception": None}

        def run_handler() -> None:
            try:
                handler(task_id, payload)
            except Exception as exc:  # noqa: BLE001 - parent thread decides final queue state
                outcome["exception"] = exc

        thread = threading.Thread(target=run_handler, name=f"resource-task-{task_id}", daemon=True)
        thread.start()
        while thread.is_alive() and not self.stop_event.is_set():
            thread.join(timeout=self.watchdog_poll_seconds)
            if not thread.is_alive():
                break
            action = self._force_retry_stuck_item(task_id, attempt_id=attempt_id)
            if action:
                return QueueTaskDeferred(task_id, str(action.get("reason") or "stuck task retried"))
        if thread.is_alive():
            return QueueTaskDeferred(task_id, "队列正在停止，当前尝试保持运行态等待重启恢复。")
        thread.join(timeout=0)
        return outcome["exception"]

    def _mark_failed(self, task_id: str, attempt_id: str, error: str, *, event_message: str) -> None:
        if not self._attempt_is_active(task_id, attempt_id):
            return
        self.task_registry.update_task(task_id, status="failed", error=error)
        self.task_registry.add_event(task_id, "failed", event_message, {"error": error})
        with self.lock:
            current = self.items.get(task_id)
            if current and str(current.get("active_attempt_id") or "") == attempt_id:
                current["status"] = "failed"
                current["active_attempt_id"] = ""
                current["error"] = error
                current["finished_at"] = timestamp()
                current["updated_at"] = timestamp()
                current["updated_epoch"] = time.time()
                self._write_locked()

    def _attempt_is_active(self, task_id: str, attempt_id: str) -> bool:
        with self.lock:
            current = self.items.get(task_id)
            return bool(current and current.get("status") == "running" and str(current.get("active_attempt_id") or "") == attempt_id)

    def is_attempt_active(self, task_id: str, attempt_id: str) -> bool:
        if not attempt_id:
            return True
        return self._attempt_is_active(task_id, attempt_id)

    def _stuck_reason(self, item: dict[str, Any], *, now: float) -> str:
        if item.get("status") != "running":
            return ""
        threshold = self._stuck_seconds(item)
        if threshold <= 0:
            return ""
        try:
            heartbeat_epoch = float(item.get("updated_epoch") or item.get("started_epoch") or 0)
        except (TypeError, ValueError):
            heartbeat_epoch = 0.0
        if heartbeat_epoch <= 0:
            return ""
        silent_seconds = max(0.0, now - heartbeat_epoch)
        if silent_seconds <= threshold:
            return ""
        return f"运行中任务 {silent_seconds:g} 秒没有 heartbeat，超过阈值 {threshold:g} 秒"

    def _stuck_seconds(self, item: dict[str, Any]) -> float:
        level = str(item.get("resource_level") or NORMAL_IO)
        return float(self.stuck_seconds_by_resource.get(level, self.stuck_seconds_by_resource.get(NORMAL_IO, 0)))

    def _force_retry_stuck_item(
        self,
        task_id: str,
        *,
        attempt_id: str = "",
        reason: str = "",
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now_value = time.time() if now is None else float(now)
        now_text = timestamp()
        with self.lock:
            current = self.items.get(task_id)
            if not current or current.get("status") != "running":
                return None
            current_attempt_id = str(current.get("active_attempt_id") or "")
            if attempt_id and current_attempt_id and current_attempt_id != attempt_id:
                return None
            reason = reason or self._stuck_reason(current, now=now_value)
            if not reason:
                return None
            retry_count = int(current.get("stuck_retry_count") or 0)
            if current_attempt_id:
                current["cancelled_attempt_ids"] = _remember_cancelled_attempt(current.get("cancelled_attempt_ids"), current_attempt_id)
                current["last_cancelled_attempt_id"] = current_attempt_id
            if retry_count >= self.max_stuck_retries:
                error = f"{reason}；已达到最大强制重试次数 {self.max_stuck_retries}。"
                current["status"] = "failed"
                current["active_attempt_id"] = ""
                current["error"] = error
                current["finished_at"] = now_text
                current["updated_at"] = now_text
                current["updated_epoch"] = now_value
                self._write_locked()
                action = {"task_id": task_id, "action": "failed", "reason": error, "retry_count": retry_count}
            else:
                retry_count += 1
                payload = dict(current.get("payload") or {})
                payload.pop("resume_checkpoint", None)
                current["payload"] = payload
                current["status"] = "queued"
                current["active_attempt_id"] = ""
                current["started_at"] = ""
                current["started_epoch"] = 0.0
                current["finished_at"] = ""
                current["checkpoint"] = {}
                current["stuck_retry_count"] = retry_count
                current["run_after_epoch"] = now_value
                current["last_defer_reason"] = reason
                current["error"] = ""
                current["updated_at"] = now_text
                current["updated_epoch"] = now_value
                self._write_locked()
                action = {"task_id": task_id, "action": "requeued", "reason": reason, "retry_count": retry_count}
        if action["action"] == "failed":
            self.task_registry.update_task(
                task_id,
                status="failed",
                error=str(action["reason"]),
                metadata={
                    "queue_status": "timed_out_failed",
                    "queue_force_retry_count": action["retry_count"],
                    "queue_stuck_reason": action["reason"],
                    "queue_cancelled_attempt_id": current_attempt_id,
                },
            )
            self.task_registry.add_event(
                task_id,
                "failed",
                "任务运行超时且强制重试次数已用完，已停止继续重抓。",
                {"reason": action["reason"], "retry_count": action["retry_count"]},
            )
        else:
            self.task_registry.update_task(
                task_id,
                status="queued",
                error="",
                metadata={
                    "queue_status": "forced_retry",
                    "queue_resume_pending": False,
                    "queue_force_retry_count": action["retry_count"],
                    "queue_stuck_reason": action["reason"],
                    "queue_cancelled_attempt_id": current_attempt_id,
                },
            )
            self.task_registry.add_event(
                task_id,
                "queued",
                "任务运行超过 watchdog 阈值未更新，已强制结束本次尝试并重新入队全量重抓。",
                {"reason": action["reason"], "retry_count": action["retry_count"]},
            )
        return action

    def _mark_running(self, item: dict[str, Any], pressure: dict[str, Any]) -> str:
        task_id = str(item.get("task_id") or "")
        attempt_id = ""
        with self.lock:
            current = self.items.get(task_id)
            if not current or current.get("status") not in {"queued", "deferred"}:
                return ""
            attempt_count = int(current.get("attempt_count") or 0) + 1
            attempt_id = f"{task_id}:{attempt_count}:{timestamp()}"
            current["status"] = "running"
            current["attempt_count"] = attempt_count
            current["active_attempt_id"] = attempt_id
            current["started_at"] = timestamp()
            current["started_epoch"] = time.time()
            current["updated_at"] = timestamp()
            current["updated_epoch"] = time.time()
            current["last_pressure"] = pressure
            self._write_locked()
        self.task_registry.update_task(task_id, status="running", metadata={"queue_status": "running", "queue_resume_pending": False})
        self.task_registry.add_event(task_id, "running", "资源队列开始执行任务。", {"pressure": pressure})
        return attempt_id

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
        attempt_id: str = "",
        resource_level: str | None = None,
        stage: str = "",
        details: dict[str, Any] | None = None,
        min_available_mb: int | None = None,
        max_swap_used_percent: float | None = None,
        yield_on_pressure: bool = False,
        defer_seconds: int | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        paused = False
        pause_count = 0
        last_event_epoch = 0.0
        level = resource_level or self._item_resource_level(task_id)
        self._raise_if_attempt_inactive(task_id, attempt_id)
        checkpoint = self._record_checkpoint(task_id, stage=stage, details=details or {}, resource_level=level, attempt_id=attempt_id)
        while not self.stop_event.is_set():
            self._raise_if_attempt_inactive(task_id, attempt_id)
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
                    self._raise_if_attempt_inactive(task_id, attempt_id)
                    self._mark_throttle_resumed(task_id, stage=stage, pause_seconds=pause_seconds, pressure=pressure)
                return {"paused": paused, "pause_seconds": pause_seconds, "pressure": pressure, "checkpoint": checkpoint}
            pause_count += 1
            delay = min(30.0, 5.0 * (2 ** min(pause_count - 1, 3)))
            reason = "；".join(reasons)
            if yield_on_pressure:
                self._yield_running_item(
                    task_id,
                    reason=reason,
                    pressure=pressure,
                    checkpoint=checkpoint,
                    stage=stage,
                    details=details or {},
                    defer_seconds=defer_seconds,
                )
            now = time.time()
            if not paused or now - last_event_epoch >= 60:
                self._raise_if_attempt_inactive(task_id, attempt_id)
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
            self._raise_if_attempt_inactive(task_id, attempt_id)
        return {"paused": paused, "pause_seconds": int(time.time() - started), "pressure": {}, "checkpoint": checkpoint}

    def _raise_if_attempt_inactive(self, task_id: str, attempt_id: str) -> None:
        if not attempt_id:
            return
        with self.lock:
            current = self.items.get(task_id)
            if not current:
                raise QueueTaskDeferred(task_id, "队列任务不存在，当前执行尝试停止。")
            cancelled = {str(item) for item in current.get("cancelled_attempt_ids") or []}
            if attempt_id in cancelled:
                raise QueueTaskDeferred(task_id, "当前执行尝试已被 watchdog 取消，旧线程停止。")
            if current.get("status") != "running" or str(current.get("active_attempt_id") or "") != attempt_id:
                raise QueueTaskDeferred(task_id, "当前执行尝试已失效，旧线程停止。")

    def _yield_running_item(
        self,
        task_id: str,
        *,
        reason: str,
        pressure: dict[str, Any],
        checkpoint: dict[str, Any],
        stage: str,
        details: dict[str, Any],
        defer_seconds: int | None = None,
    ) -> None:
        with self.lock:
            current = self.items.get(task_id)
            if not current or current.get("status") != "running":
                raise QueueTaskDeferred(task_id, reason)
            defer_count = int(current.get("defer_count") or 0) + 1
            delay = int(defer_seconds if defer_seconds is not None else min(1800, 60 * (2 ** min(defer_count - 1, 5))))
            payload = dict(current.get("payload") or {})
            payload["resume_checkpoint"] = checkpoint
            current["payload"] = payload
            current["status"] = "deferred"
            current["defer_count"] = defer_count
            current["active_attempt_id"] = ""
            current["run_after_epoch"] = time.time() + delay
            current["last_defer_reason"] = reason
            current["last_throttle_reason"] = reason
            current["last_pressure"] = pressure
            current["throttle_count"] = int(current.get("throttle_count") or 0) + 1
            current["updated_at"] = timestamp()
            current["updated_epoch"] = time.time()
            self._write_locked()
        self.task_registry.update_task(
            task_id,
            status="queued",
            metadata={
                "queue_status": "deferred",
                "queue_resume_pending": True,
                "queue_throttle_reason": reason,
                "queue_throttle_stage": stage,
                "queue_delay_seconds": delay,
                "queue_defer_count": defer_count,
            },
        )
        self.task_registry.add_event(
            task_id,
            "queued",
            f"资源承压，当前任务让出队列，延后 {delay} 秒后从 checkpoint 恢复：{reason}",
            {"stage": stage, "pressure": pressure, "details": details, "checkpoint": checkpoint, "delay_seconds": delay},
        )
        raise QueueTaskDeferred(task_id, reason)

    def _record_checkpoint(
        self,
        task_id: str,
        *,
        stage: str,
        details: dict[str, Any],
        resource_level: str,
        attempt_id: str = "",
    ) -> dict[str, Any]:
        now_text = timestamp()
        checkpoint = {
            "version": CHECKPOINT_VERSION,
            "stage": stage or "checkpoint",
            "details": details or {},
            "resource_level": resource_level,
            "updated_at": now_text,
            "updated_epoch": time.time(),
        }
        with self.lock:
            current = self.items.get(task_id)
            if current:
                if attempt_id and (current.get("status") != "running" or str(current.get("active_attempt_id") or "") != attempt_id):
                    raise QueueTaskDeferred(task_id, "当前执行尝试已失效，旧线程停止。")
                checkpoint["handler_version"] = int(current.get("handler_version") or DEFAULT_HANDLER_VERSION)
                checkpoint["payload_version"] = int(current.get("payload_version") or DEFAULT_PAYLOAD_VERSION)
                current["checkpoint_version"] = CHECKPOINT_VERSION
                current["checkpoint"] = checkpoint
                current["updated_at"] = now_text
                current["updated_epoch"] = checkpoint["updated_epoch"]
                self._write_locked()
        self.task_registry.update_task(
            task_id,
            metadata={"queue_checkpoint_stage": checkpoint["stage"], "queue_checkpoint_at": now_text},
        )
        return checkpoint

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
            queue_version = int(payload.get("version") or 1) if isinstance(payload, dict) else 1
            items = payload.get("items", []) if isinstance(payload, dict) else payload
            if queue_version > QUEUE_SCHEMA_VERSION:
                self._abandon_queue_file(items, f"队列文件版本 {queue_version} 高于当前支持版本 {QUEUE_SCHEMA_VERSION}，已放弃。")
                return {}
            loaded: dict[str, dict[str, Any]] = {}
            changed = queue_version != QUEUE_SCHEMA_VERSION
            for item in items:
                if not isinstance(item, dict) or not item.get("task_id"):
                    continue
                normalized, item_changed = self._normalize_loaded_item(item)
                loaded[str(normalized["task_id"])] = normalized
                changed = changed or item_changed
            if changed:
                self._write_items(loaded.values())
            return loaded
        except Exception as exc:  # noqa: BLE001 - keep corrupt queue files visible for ops
            self._abandon_queue_file([], f"队列文件无法解析，已隔离：{exc}")
            return {}

    def _normalize_loaded_item(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        normalized = dict(item)
        changed = False
        task_id = str(normalized.get("task_id") or "")
        for key, default in {
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "handler_version": DEFAULT_HANDLER_VERSION,
            "payload_version": DEFAULT_PAYLOAD_VERSION,
            "checkpoint_version": CHECKPOINT_VERSION,
        }.items():
            if key not in normalized:
                normalized[key] = default
                changed = True
        for key, default in {
            "attempt_count": 0,
            "active_attempt_id": "",
            "started_epoch": 0.0,
            "stuck_retry_count": 0,
            "cancelled_attempt_ids": [],
            "last_cancelled_attempt_id": "",
        }.items():
            if key not in normalized:
                normalized[key] = default
                changed = True
        version_error = _item_version_error(normalized)
        if version_error:
            self._abandon_item(task_id, version_error, item=normalized)
            normalized = dict(self.items.get(task_id) or normalized)
            return normalized, True
        if str(normalized.get("kind") or "") == "kaipanla":
            if str(normalized.get("resource_level") or "") != LIGHT_IO:
                normalized["resource_level"] = LIGHT_IO
                changed = True
            payload = normalized.get("payload") if isinstance(normalized.get("payload"), dict) else {}
            if "trade_date" not in payload:
                inferred_trade_date = _compact_date_from_task_id(task_id)
                if inferred_trade_date:
                    payload = dict(payload)
                    payload["trade_date"] = inferred_trade_date
                    normalized["payload"] = payload
                    changed = True
        if normalized.get("status") == "running":
            if _can_resume_running_item(normalized):
                normalized = _resume_running_item(normalized)
                self.task_registry.update_task(
                    task_id,
                    status="queued",
                    metadata={"queue_status": "queued", "queue_resume_pending": True},
                )
                self.task_registry.add_event(
                    task_id,
                    "queued",
                    "服务重启，队列任务从 checkpoint 恢复，等待重新调度。",
                    {"checkpoint": normalized.get("checkpoint") or {}},
                )
                changed = True
            else:
                self._abandon_item(task_id, "服务重启，运行中的队列任务缺少可恢复 checkpoint，已放弃。", item=normalized)
                normalized = dict(self.items.get(task_id) or normalized)
                changed = True
        return normalized, changed

    def _trim_locked(self) -> None:
        if len(self.items) <= 300:
            return
        ordered = sorted(self.items.values(), key=lambda item: float(item.get("updated_epoch") or 0), reverse=True)
        keep = {str(item.get("task_id")) for item in ordered[:300]}
        for task_id in list(self.items):
            if task_id not in keep:
                self.items.pop(task_id, None)

    def _write_locked(self) -> None:
        self._write_items(self.items.values())

    def _write_items(self, items) -> None:
        ensure_dir(self.path.parent)
        write_json(self.path, {"version": QUEUE_SCHEMA_VERSION, "items": list(items)})
        os.chmod(self.path, 0o600)

    def _handler_version_error(self, item: dict[str, Any]) -> str:
        error = _item_version_error(item)
        if error:
            return error
        handler_key = str(item.get("handler_key") or "")
        current_handler_version = self.handler_versions.get(handler_key, DEFAULT_HANDLER_VERSION)
        try:
            item_handler_version = int(item.get("handler_version") or DEFAULT_HANDLER_VERSION)
        except (TypeError, ValueError):
            return "任务处理器版本字段不合法，已放弃。"
        if item_handler_version != current_handler_version:
            return f"任务处理器 {handler_key} 版本 {item_handler_version} 与当前版本 {current_handler_version} 不兼容，已放弃。"
        return ""

    def _abandon_item(self, task_id: str, reason: str, *, item: dict[str, Any] | None = None) -> None:
        now_text = timestamp()
        with self.lock:
            current = self.items.get(task_id) or dict(item or {})
            if not current:
                current = {"task_id": task_id}
            current["status"] = "abandoned"
            current["error"] = reason
            current["finished_at"] = current.get("finished_at") or now_text
            current["updated_at"] = now_text
            current["updated_epoch"] = time.time()
            if task_id:
                self.items[task_id] = current
            self._write_locked()
        self.task_registry.update_task(
            task_id,
            status="failed",
            error=reason,
            metadata={"queue_status": "abandoned_incompatible", "queue_abandoned_reason": reason},
        )
        self.task_registry.add_event(task_id, "failed", reason, {"queue_status": "abandoned_incompatible"})

    def _abandon_queue_file(self, items, reason: str) -> None:
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("task_id"):
                task_id = str(item.get("task_id") or "")
                self.task_registry.update_task(
                    task_id,
                    status="failed",
                    error=reason,
                    metadata={"queue_status": "abandoned_incompatible", "queue_abandoned_reason": reason},
                )
                self.task_registry.add_event(task_id, "failed", reason, {"queue_status": "abandoned_incompatible"})
        abandoned_path = _abandoned_queue_path(self.path)
        try:
            self.path.rename(abandoned_path)
        except OSError:
            pass

    def _abandon_orphaned_recovering_tasks(self) -> None:
        lister = getattr(self.task_registry, "list_tasks", None)
        if not callable(lister):
            return
        try:
            tasks = lister(limit=500)
        except Exception:
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "")
            metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
            if (
                task_id
                and task_id not in self.items
                and task.get("status") == "queued"
                and metadata.get("queued_by") == QUEUE_OWNER
                and metadata.get("queue_status") == "recovering"
            ):
                reason = "服务重启后未找到对应队列项，无法从 checkpoint 恢复，已放弃。"
                self.task_registry.update_task(
                    task_id,
                    status="failed",
                    error=reason,
                    metadata={"queue_status": "abandoned_incompatible", "queue_abandoned_reason": reason},
                )
                self.task_registry.add_event(task_id, "failed", reason, {"queue_status": "abandoned_incompatible"})


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


def _is_scheduled_item(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    if isinstance(payload, dict) and str(payload.get("trigger") or "") == "scheduled":
        return True
    return str(item.get("trigger") or "") == "scheduled"


def _queue_order_key(item: dict[str, Any]) -> tuple[float, str]:
    try:
        enqueued_epoch = float(item.get("enqueued_epoch") or 0)
    except (TypeError, ValueError):
        enqueued_epoch = 0.0
    return enqueued_epoch, str(item.get("task_id") or "")


def _remember_cancelled_attempt(values: Any, attempt_id: str) -> list[str]:
    existing = [str(item) for item in (values or []) if str(item)]
    if attempt_id and attempt_id not in existing:
        existing.append(attempt_id)
    return existing[-MAX_CANCELLED_ATTEMPTS:]


def _compact_date_from_task_id(task_id: str) -> str:
    prefix = str(task_id or "")[:8]
    return prefix if prefix.isdigit() else ""


def _item_version_error(item: dict[str, Any]) -> str:
    versions = {
        "queue_schema_version": (QUEUE_SCHEMA_VERSION, "队列项结构"),
        "payload_version": (DEFAULT_PAYLOAD_VERSION, "任务参数"),
        "checkpoint_version": (CHECKPOINT_VERSION, "checkpoint"),
    }
    for key, (current, label) in versions.items():
        try:
            value = int(item.get(key) or current)
        except (TypeError, ValueError):
            return f"{label}版本字段不合法，已放弃。"
        if value > current:
            return f"{label}版本 {value} 高于当前支持版本 {current}，已放弃。"
    return ""


def _can_resume_running_item(item: dict[str, Any]) -> bool:
    checkpoint = item.get("checkpoint")
    if not isinstance(checkpoint, dict) or not checkpoint:
        return False
    try:
        checkpoint_version = int(checkpoint.get("version") or item.get("checkpoint_version") or 0)
    except (TypeError, ValueError):
        return False
    return 0 < checkpoint_version <= CHECKPOINT_VERSION


def _resume_running_item(item: dict[str, Any]) -> dict[str, Any]:
    resumed = dict(item)
    checkpoint = dict(resumed.get("checkpoint") or {})
    payload = dict(resumed.get("payload") or {})
    payload["resume_checkpoint"] = checkpoint
    resumed["payload"] = payload
    resumed["status"] = "queued"
    resumed["active_attempt_id"] = ""
    resumed["started_epoch"] = 0.0
    resumed["run_after_epoch"] = time.time()
    resumed["last_defer_reason"] = ""
    resumed["error"] = ""
    resumed["finished_at"] = ""
    resumed["resume_count"] = int(resumed.get("resume_count") or 0) + 1
    resumed["resumed_at"] = timestamp()
    resumed["updated_at"] = resumed["resumed_at"]
    resumed["updated_epoch"] = time.time()
    return resumed


def _abandoned_queue_path(path: Path) -> Path:
    stamp = timestamp()
    candidate = path.with_name(f"{path.name}.abandoned.{stamp}.json")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.abandoned.{stamp}.{index}.json")
        index += 1
    return candidate
