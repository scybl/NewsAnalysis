import json

from stock_pipeline.task_queue import HEAVY_IO, NORMAL_IO, QUEUE_OWNER, ResourceAwareTaskQueue
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


def test_resource_queue_keeps_later_tasks_behind_deferred_head(tmp_path):
    registry = FakeTaskRegistry()
    registry.create_task("heavy")
    registry.create_task("normal")
    pressure = {"mem_available_mb": 300, "swap_used_percent": 80, "load_1m": 20}
    queue = ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: pressure,
        poll_seconds=0.1,
    )
    seen = []
    queue.register("handler", lambda task_id, _payload: seen.append(task_id))
    queue.enqueue(task_id="heavy", handler_key="handler", kind="test", title="Heavy", resource_level=HEAVY_IO)
    queue.enqueue(task_id="normal", handler_key="handler", kind="test", title="Normal", resource_level=NORMAL_IO)

    queue._run_or_defer(queue._next_ready_item())

    assert seen == []
    assert queue._next_ready_item() is None


def test_task_registry_preserves_queued_queue_tasks_across_restart(tmp_path):
    path = tmp_path / "admin_tasks.json"
    registry = TaskRegistry(path)
    registry.create_task("queued-task", "daily_market", "每日股票数据更新", metadata={"queued_by": QUEUE_OWNER})
    registry.create_task("running-task", "daily_market", "每日股票数据更新", metadata={"queued_by": QUEUE_OWNER})
    registry.update_task("running-task", status="running")

    restarted = TaskRegistry(path)

    assert restarted.get_task("queued-task")["status"] == "queued"
    assert restarted.get_task("running-task")["status"] == "failed"
    assert "队列任务保留" in restarted.get_task("queued-task")["events"][-1]["message"]


def test_resource_queue_marks_running_items_failed_when_queue_file_is_reloaded(tmp_path):
    path = tmp_path / "task_queue.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {"task_id": "a", "status": "running", "updated_epoch": 1},
                    {"task_id": "b", "status": "queued", "updated_epoch": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    queue = ResourceAwareTaskQueue(path, FakeTaskRegistry(), poll_seconds=0.1)
    items = {item["task_id"]: item for item in queue.snapshot()["items"]}

    assert items["a"]["status"] == "failed"
    assert "服务重启" in items["a"]["error"]
    assert items["b"]["status"] == "queued"


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
    assert sleeps == [5.0, 10.0]
    stages = [event["stage"] for event in registry.events]
    assert "throttled" in stages
    assert "resumed" in stages
    assert registry.tasks["heavy"]["metadata"]["queue_status"] == "running"
