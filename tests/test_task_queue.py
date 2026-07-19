import json
import threading
import time

from stock_pipeline.task_queue import HEAVY_IO, LIGHT_IO, NORMAL_IO, QUEUE_OWNER, QUEUE_SCHEMA_VERSION, QueueTaskDeferred, ResourceAwareTaskQueue
from stock_pipeline.web import TaskRegistry


class FakeTaskRegistry:
    def __init__(self):
        self.tasks = {}
        self.events = []

    def create_task(self, task_id, kind="test", title="test", metadata=None):
        self.tasks[task_id] = {"task_id": task_id, "kind": kind, "title": title, "status": "queued", "metadata": metadata or {}}
        return self.tasks[task_id]

    def update_task(self, task_id, status=None, error=None, result=None, metadata=None):
        task = self.tasks.setdefault(task_id, {"task_id": task_id, "status": "queued", "metadata": {}})
        if status:
            task["status"] = status
        if error is not None:
            task["error"] = error
        if result is not None:
            task["result"] = result
        if metadata:
            task.setdefault("metadata", {}).update(metadata)

    def add_event(self, task_id, stage, message, details=None):
        self.events.append({"task_id": task_id, "stage": stage, "message": message, "details": details or {}})

    def get_task(self, task_id):
        return self.tasks.get(task_id)


def test_resource_queue_runs_fifo_when_pressure_is_ok(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("a")
    registry.create_task("b")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )
    seen = []

    def handler(task_id, _payload):
        seen.append(task_id)
        registry.update_task(task_id, status="succeeded")

    queue.register("handler", handler)
    queue.enqueue(task_id="a", handler_key="handler", kind="test", title="A", resource_level=NORMAL_IO)
    queue.enqueue(task_id="b", handler_key="handler", kind="test", title="B", resource_level=NORMAL_IO)

    queue._run_or_defer(queue._next_ready_item())
    queue._run_or_defer(queue._next_ready_item())

    assert seen == ["a", "b"]
    assert queue.snapshot()["counts"]["succeeded"] == 2


def test_resource_queue_prioritizes_earliest_scheduled_task_when_switching(tmp_path):
    registry = FakeTaskRegistry()
    for task_id in ["manual", "scheduled-a", "scheduled-b"]:
        registry.create_task(task_id)
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )
    seen = []

    def handler(task_id, _payload):
        seen.append(task_id)
        registry.update_task(task_id, status="succeeded")

    queue.register("handler", handler)
    queue.enqueue(
        task_id="manual",
        handler_key="handler",
        kind="manual",
        title="Manual",
        payload={"trigger": "manual"},
        resource_level=NORMAL_IO,
    )
    queue.enqueue(
        task_id="scheduled-a",
        handler_key="handler",
        kind="scheduled",
        title="Scheduled A",
        payload={"trigger": "scheduled"},
        resource_level=NORMAL_IO,
    )
    queue.enqueue(
        task_id="scheduled-b",
        handler_key="handler",
        kind="scheduled",
        title="Scheduled B",
        payload={"trigger": "scheduled"},
        resource_level=NORMAL_IO,
    )

    queue._run_or_defer(queue._next_ready_item())
    queue._run_or_defer(queue._next_ready_item())
    queue._run_or_defer(queue._next_ready_item())

    assert seen == ["scheduled-a", "scheduled-b", "manual"]


def test_resource_queue_manual_promote_overrides_scheduled_priority(tmp_path):
    registry = FakeTaskRegistry()
    for task_id in ["manual", "scheduled"]:
        registry.create_task(task_id)
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )
    queue.register("handler", lambda task_id, _payload: registry.update_task(task_id, status="succeeded"))
    queue.enqueue(
        task_id="manual",
        handler_key="handler",
        kind="manual",
        title="Manual",
        payload={"trigger": "manual"},
        resource_level=NORMAL_IO,
    )
    queue.enqueue(
        task_id="scheduled",
        handler_key="handler",
        kind="scheduled",
        title="Scheduled",
        payload={"trigger": "scheduled"},
        resource_level=NORMAL_IO,
    )

    result = queue.manual_adjust("manual", "promote")

    assert result["action"] == "promoted"
    assert queue._next_ready_item()["task_id"] == "manual"
    assert registry.tasks["manual"]["metadata"]["queue_status"] == "manual_promoted"


def test_resource_queue_manual_reorder_controls_ready_order(tmp_path):
    registry = FakeTaskRegistry()
    for task_id in ["a", "b", "c"]:
        registry.create_task(task_id)
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )
    seen = []

    def handler(task_id, _payload):
        seen.append(task_id)
        registry.update_task(task_id, status="succeeded")

    queue.register("handler", handler)
    queue.enqueue(task_id="a", handler_key="handler", kind="test", title="A", payload={"trigger": "scheduled"}, resource_level=NORMAL_IO)
    queue.enqueue(task_id="b", handler_key="handler", kind="test", title="B", payload={"trigger": "scheduled"}, resource_level=NORMAL_IO)
    queue.enqueue(task_id="c", handler_key="handler", kind="test", title="C", payload={"trigger": "manual"}, resource_level=NORMAL_IO)

    result = queue.manual_adjust("", "reorder", task_ids=["c", "b", "a"])
    assert result["action"] == "reordered"
    assert registry.tasks["c"]["metadata"]["queue_status"] == "manual_reordered"
    assert registry.tasks["c"]["metadata"]["queue_manual_order_index"] == 0
    while True:
        item = queue._next_ready_item()
        if not item:
            break
        queue._run_or_defer(item)

    assert seen == ["c", "b", "a"]


def test_resource_queue_manual_delay_and_cancel_update_registry(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("a")
    queue = ResourceAwareTaskQueue(tmp_path / "task_queue.json", registry, poll_seconds=0.1)
    queue.enqueue(task_id="a", handler_key="handler", kind="test", title="A", resource_level=NORMAL_IO)

    delayed = queue.manual_adjust("a", "delay", delay_seconds=600)
    item = delayed["item"]

    assert delayed["action"] == "delayed"
    assert item["status"] == "deferred"
    assert item["last_defer_reason"]
    assert registry.tasks["a"]["metadata"]["queue_status"] == "manual_delayed"

    cancelled = queue.manual_adjust("a", "cancel")

    assert cancelled["action"] == "cancelled"
    assert cancelled["item"]["status"] == "cancelled"
    assert registry.tasks["a"]["status"] == "cancelled"
    assert registry.tasks["a"]["metadata"]["queue_status"] == "manual_cancelled"


def test_resource_queue_manual_retry_running_item_requeues_attempt(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("running")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )
    queue.enqueue(task_id="running", handler_key="handler", kind="test", title="Running", resource_level=NORMAL_IO)
    attempt_id = queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0})

    result = queue.manual_adjust("running", "retry")
    item = queue.snapshot()["items"][0]

    assert result["action"] == "requeued"
    assert item["status"] == "queued"
    assert item["manual_priority"] == 0
    assert attempt_id in item["cancelled_attempt_ids"]
    assert registry.tasks["running"]["status"] == "queued"
    assert registry.tasks["running"]["metadata"]["queue_status"] == "manual_promoted"


def test_resource_queue_defers_head_task_when_memory_is_pressured(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("heavy")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 300, "swap_used_percent": 80, "load_1m": 20},
        poll_seconds=0.1,
    )
    queue.register("handler", lambda _task_id, _payload: None)
    queue.enqueue(task_id="heavy", handler_key="handler", kind="test", title="Heavy", resource_level=HEAVY_IO)

    queue._run_or_defer(queue._next_ready_item())
    snapshot = queue.snapshot()
    item = snapshot["items"][0]

    assert item["status"] == "deferred"
    assert item["defer_count"] == 1
    assert "可用内存" in item["last_defer_reason"]
    assert registry.tasks["heavy"]["metadata"]["queue_status"] == "deferred"
    assert any("资源承压" in event["message"] for event in registry.events)


def test_resource_queue_allows_ready_light_task_behind_deferred_heavy_head(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("heavy")
    registry.create_task("light")
    pressure = {"mem_available_mb": 300, "swap_used_percent": 80, "load_1m": 1}
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: pressure,
        poll_seconds=0.1,
    )
    seen = []
    queue.register("handler", lambda task_id, _payload: seen.append(task_id))
    queue.enqueue(task_id="heavy", handler_key="handler", kind="test", title="Heavy", resource_level=HEAVY_IO)
    queue.enqueue(task_id="light", handler_key="handler", kind="test", title="Light", resource_level=LIGHT_IO)

    queue._run_or_defer(queue._next_ready_item())
    queue._run_or_defer(queue._next_ready_item())

    assert seen == ["light"]


def test_task_registry_preserves_queued_queue_tasks_across_restart(tmp_path):
    path = tmp_path / "admin_tasks.json"
    registry = TaskRegistry(path)
    registry.create_task("queued-task", "daily_market", "每日股票数据更新", metadata={"queued_by": QUEUE_OWNER})
    registry.create_task("running-task", "daily_market", "每日股票数据更新", metadata={"queued_by": QUEUE_OWNER})
    registry.update_task("running-task", status="running")

    restarted = TaskRegistry(path)

    assert restarted.get_task("queued-task")["status"] == "queued"
    assert restarted.get_task("running-task")["status"] == "queued"
    assert restarted.get_task("running-task")["metadata"]["queue_status"] == "recovering"
    assert "等待资源队列恢复或放弃" in restarted.get_task("queued-task")["events"][-1]["message"]


def test_task_registry_quarantines_corrupt_state_file(tmp_path):
    path = tmp_path / "admin_tasks.json"
    path.write_text("{broken", encoding="utf-8")

    registry = TaskRegistry(path)

    assert registry.list_tasks() == []
    assert not path.exists()
    assert list(tmp_path.glob("admin_tasks.json.corrupt.*.json"))


def test_resource_queue_resumes_running_items_with_checkpoint_after_reload(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("a", metadata={"queued_by": QUEUE_OWNER})
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps(
            {
                "version": QUEUE_SCHEMA_VERSION,
                "items": [
                    {
                        "task_id": "a",
                        "handler_key": "handler",
                        "status": "running",
                        "updated_epoch": 1,
                        "checkpoint": {"version": 1, "stage": "unit", "details": {"cursor": 2}},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    queue = ResourceAwareTaskQueue(path, registry, poll_seconds=0.1)
    items = {item["task_id"]: item for item in queue.snapshot()["items"]}

    assert items["a"]["status"] == "queued"
    assert items["a"]["resume_count"] == 1
    assert items["a"]["payload"]["resume_checkpoint"]["details"]["cursor"] == 2
    assert registry.tasks["a"]["status"] == "queued"
    assert registry.tasks["a"]["metadata"]["queue_resume_pending"] is True


def test_resource_queue_abandons_running_items_without_checkpoint_after_reload(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("a", metadata={"queued_by": QUEUE_OWNER})
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps(
            {
                "version": QUEUE_SCHEMA_VERSION,
                "items": [{"task_id": "a", "handler_key": "handler", "status": "running", "updated_epoch": 1}],
            }
        ),
        encoding="utf-8",
    )

    queue = ResourceAwareTaskQueue(path, registry, poll_seconds=0.1)
    items = {item["task_id"]: item for item in queue.snapshot()["items"]}

    assert items["a"]["status"] == "abandoned"
    assert "缺少可恢复 checkpoint" in items["a"]["error"]
    assert registry.tasks["a"]["status"] == "failed"
    assert registry.tasks["a"]["metadata"]["queue_status"] == "abandoned_incompatible"


def test_resource_queue_abandons_future_queue_file_version(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("future", metadata={"queued_by": QUEUE_OWNER})
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps({"version": QUEUE_SCHEMA_VERSION + 100, "items": [{"task_id": "future", "status": "queued"}]}),
        encoding="utf-8",
    )

    queue = ResourceAwareTaskQueue(path, registry, poll_seconds=0.1)

    assert queue.snapshot()["items"] == []
    assert not path.exists()
    assert list(tmp_path.glob("task_queue.json.abandoned.*.json"))
    assert registry.tasks["future"]["status"] == "failed"
    assert "高于当前支持版本" in registry.tasks["future"]["error"]


def test_resource_queue_abandons_recovering_registry_task_when_queue_item_is_missing(tmp_path):
    tasks_path = tmp_path / "admin_tasks.json"
    registry = TaskRegistry(tasks_path)
    registry.create_task("running-task", "daily_market", "每日股票数据更新", metadata={"queued_by": QUEUE_OWNER})
    registry.update_task("running-task", status="running")
    restarted = TaskRegistry(tasks_path)

    ResourceAwareTaskQueue(tmp_path / "missing_task_queue.json", restarted, poll_seconds=0.1)

    task = restarted.get_task("running-task")
    assert task["status"] == "failed"
    assert "未找到对应队列项" in task["error"]


def test_resource_queue_abandons_handler_version_mismatch_when_switching(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("old", metadata={"queued_by": QUEUE_OWNER})
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps(
            {
                "version": QUEUE_SCHEMA_VERSION,
                "items": [
                    {
                        "task_id": "old",
                        "handler_key": "handler",
                        "handler_version": 1,
                        "status": "queued",
                        "enqueued_epoch": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    queue = ResourceAwareTaskQueue(path, registry, poll_seconds=0.1)
    seen = []
    queue.register("handler", lambda task_id, _payload: seen.append(task_id), handler_version=2)

    queue._run_or_defer(queue._next_ready_item())
    items = {item["task_id"]: item for item in queue.snapshot()["items"]}

    assert seen == []
    assert items["old"]["status"] == "abandoned"
    assert registry.tasks["old"]["status"] == "failed"


def test_resource_queue_checkpoint_pauses_running_task_until_pressure_recovers(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("heavy")
    pressures = iter(
        [
            {"mem_available_mb": 100, "swap_used_percent": 95, "load_1m": 1},
            {"mem_available_mb": 200, "swap_used_percent": 90, "load_1m": 1},
            {"mem_available_mb": 2048, "swap_used_percent": 10, "load_1m": 1},
        ]
    )
    sleeps = []
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: next(pressures),
        sleep_func=lambda seconds: sleeps.append(seconds),
        poll_seconds=0.1,
    )
    queue.enqueue(task_id="heavy", handler_key="handler", kind="test", title="Heavy", resource_level=HEAVY_IO)
    queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 2048, "swap_used_percent": 0, "load_1m": 0})

    result = queue.checkpoint("heavy", resource_level=HEAVY_IO, stage="unit_test")

    assert result["paused"] is True
    assert result["checkpoint"]["stage"] == "unit_test"
    assert sleeps == [5.0, 10.0]
    item = queue.snapshot()["items"][0]
    assert item["checkpoint"]["version"] == 1
    assert item["checkpoint"]["stage"] == "unit_test"
    stages = [event["stage"] for event in registry.events]
    assert "throttled" in stages
    assert "resumed" in stages
    assert registry.tasks["heavy"]["metadata"]["queue_status"] == "running"
    assert registry.tasks["heavy"]["metadata"]["queue_checkpoint_stage"] == "unit_test"


def test_resource_queue_checkpoint_can_yield_running_heavy_task(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("heavy")
    registry.create_task("light")
    pressure = {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0}
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: pressure,
        poll_seconds=0.1,
    )
    seen = []

    def heavy_handler(task_id, _payload):
        nonlocal pressure
        pressure = {"mem_available_mb": 300, "swap_used_percent": 90, "load_1m": 1}
        queue.checkpoint(
            task_id,
            resource_level=HEAVY_IO,
            stage="unit_test",
            details={"stage": "before_stock", "current": 2},
            yield_on_pressure=True,
            defer_seconds=120,
        )
        seen.append("heavy-after-checkpoint")

    def light_handler(task_id, _payload):
        seen.append(task_id)
        registry.update_task(task_id, status="succeeded")

    queue.register("heavy_handler", heavy_handler)
    queue.register("light_handler", light_handler)
    queue.enqueue(task_id="heavy", handler_key="heavy_handler", kind="test", title="Heavy", resource_level=HEAVY_IO)
    queue.enqueue(task_id="light", handler_key="light_handler", kind="test", title="Light", resource_level=LIGHT_IO)

    queue._run_or_defer(queue._next_ready_item())
    queue._run_or_defer(queue._next_ready_item())

    items = {item["task_id"]: item for item in queue.snapshot()["items"]}
    assert seen == ["light"]
    assert items["heavy"]["status"] == "deferred"
    assert items["heavy"]["payload"]["resume_checkpoint"]["details"]["current"] == 2
    assert items["heavy"]["run_after_epoch"] > time.time()
    assert registry.tasks["heavy"]["status"] == "queued"
    assert registry.tasks["heavy"]["metadata"]["queue_resume_pending"] is True


def test_resource_queue_migrates_old_kaipanla_items_to_light_io_with_trade_date(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("20260714_214524_abc12345", metadata={"queued_by": QUEUE_OWNER})
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps(
            {
                "version": QUEUE_SCHEMA_VERSION,
                "items": [
                    {
                        "task_id": "20260714_214524_abc12345",
                        "handler_key": "kaipanla",
                        "kind": "kaipanla",
                        "status": "queued",
                        "resource_level": NORMAL_IO,
                        "payload": {"trigger": "scheduled", "features": ["daily_data"]},
                        "enqueued_epoch": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    queue = ResourceAwareTaskQueue(path, registry, poll_seconds=0.1)
    item = queue.snapshot()["items"][0]

    assert item["resource_level"] == LIGHT_IO
    assert item["payload"]["trade_date"] == "20260714"


def test_resource_queue_force_retries_running_item_without_recent_heartbeat(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("stuck")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
        stuck_seconds_by_resource={NORMAL_IO: 10},
        max_stuck_retries=2,
    )
    queue.enqueue(
        task_id="stuck",
        handler_key="handler",
        kind="test",
        title="Stuck",
        payload={"resume_checkpoint": {"stage": "old"}, "target_date": "20260714"},
        resource_level=NORMAL_IO,
    )
    queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0})
    with queue.lock:
        queue.items["stuck"]["updated_epoch"] = 100

    actions = queue.force_retry_stuck_tasks(now=111)
    item = queue.snapshot()["items"][0]

    assert actions[0]["action"] == "requeued"
    assert item["status"] == "queued"
    assert item["stuck_retry_count"] == 1
    assert item["active_attempt_id"] == ""
    assert item["run_after_epoch"] == 111
    assert "resume_checkpoint" not in item["payload"]
    assert item["payload"]["target_date"] == "20260714"
    assert registry.tasks["stuck"]["status"] == "queued"
    assert registry.tasks["stuck"]["metadata"]["queue_status"] == "forced_retry"
    assert registry.tasks["stuck"]["metadata"]["queue_cancelled_attempt_id"]
    assert item["cancelled_attempt_ids"]


def test_resource_queue_checkpoint_rejects_cancelled_attempt_after_force_retry(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("stuck")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
        stuck_seconds_by_resource={NORMAL_IO: 10},
    )
    queue.enqueue(task_id="stuck", handler_key="handler", kind="test", title="Stuck", resource_level=NORMAL_IO)
    attempt_id = queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0})
    with queue.lock:
        queue.items["stuck"]["updated_epoch"] = 100

    queue.force_retry_stuck_tasks(now=111)

    try:
        queue.checkpoint("stuck", attempt_id=attempt_id, resource_level=NORMAL_IO, stage="old_attempt")
    except QueueTaskDeferred as exc:
        assert "取消" in exc.reason or "失效" in exc.reason
    else:
        raise AssertionError("cancelled attempt should stop at checkpoint")


def test_resource_queue_fails_stuck_item_after_retry_limit(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("stuck")
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
        stuck_seconds_by_resource={NORMAL_IO: 10},
        max_stuck_retries=1,
    )
    queue.enqueue(task_id="stuck", handler_key="handler", kind="test", title="Stuck", resource_level=NORMAL_IO)
    queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0})
    with queue.lock:
        queue.items["stuck"]["updated_epoch"] = 100
        queue.items["stuck"]["stuck_retry_count"] = 1

    actions = queue.force_retry_stuck_tasks(now=111)
    item = queue.snapshot()["items"][0]

    assert actions[0]["action"] == "failed"
    assert item["status"] == "failed"
    assert "最大强制重试次数" in item["error"]
    assert registry.tasks["stuck"]["status"] == "failed"
    assert registry.tasks["stuck"]["metadata"]["queue_status"] == "timed_out_failed"


def test_resource_queue_watchdog_requeues_handler_that_stops_heartbeating(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("stuck")
    release = threading.Event()
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
        stuck_seconds_by_resource={NORMAL_IO: 0.01},
        max_stuck_retries=1,
        watchdog_poll_seconds=0.01,
    )

    def stuck_handler(_task_id, _payload):
        release.wait(1)

    queue.register("handler", stuck_handler)
    queue.enqueue(task_id="stuck", handler_key="handler", kind="test", title="Stuck", resource_level=NORMAL_IO)

    queue._run_or_defer(queue._next_ready_item())
    item = queue.snapshot()["items"][0]

    assert item["status"] == "queued"
    assert item["stuck_retry_count"] == 1
    assert registry.tasks["stuck"]["status"] == "queued"
    assert registry.tasks["stuck"]["metadata"]["queue_status"] == "forced_retry"
    release.set()
