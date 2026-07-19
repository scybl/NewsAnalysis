import pytest

from stock_pipeline.task_queue import NORMAL_IO, ResourceAwareTaskQueue


class FakeTaskRegistry:
    def __init__(self):
        self.tasks = {}
        self.events = []

    def create_task(self, task_id, *, kind="test", title="test"):
        self.tasks[task_id] = {"task_id": task_id, "kind": kind, "title": title, "status": "queued", "metadata": {}}

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


def _queue(tmp_path, registry):
    return ResourceAwareTaskQueue(
        tmp_path / "task_queue.json",
        registry,
        pressure_reader=lambda: {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0},
        poll_seconds=0.1,
    )


def _enqueue(queue, registry, task_id):
    registry.create_task(task_id, title=task_id.upper())
    return queue.enqueue(
        task_id=task_id,
        handler_key="handler",
        kind="manual_queue_test",
        title=task_id.upper(),
        payload={"trigger": "manual"},
        resource_level=NORMAL_IO,
    )


def test_manual_reorder_is_persisted_and_survives_queue_reload(tmp_path):
    registry = FakeTaskRegistry()
    queue = _queue(tmp_path, registry)
    for task_id in ["a", "b", "c"]:
        _enqueue(queue, registry, task_id)

    result = queue.manual_adjust("", "reorder", task_ids=["c", "a", "b"])
    reloaded = _queue(tmp_path, registry)
    items = reloaded.snapshot()["items"]

    assert result["action"] == "reordered"
    assert [item["task_id"] for item in items[:3]] == ["c", "a", "b"]
    assert [item["manual_order_index"] for item in items[:3]] == [0, 1, 2]


def test_manual_reorder_deduplicates_frontend_task_ids(tmp_path):
    registry = FakeTaskRegistry()
    queue = _queue(tmp_path, registry)
    for task_id in ["a", "b", "c"]:
        _enqueue(queue, registry, task_id)

    result = queue.manual_adjust("", "reorder", task_ids=["b", "b", "a", "", "a"])
    items = queue.snapshot()["items"]

    assert result["task_ids"] == ["b", "a"]
    assert [item["task_id"] for item in items[:3]] == ["b", "a", "c"]
    assert registry.tasks["b"]["metadata"]["queue_manual_order_index"] == 0
    assert registry.tasks["a"]["metadata"]["queue_manual_order_index"] == 1


def test_manual_reorder_rejects_missing_or_running_tasks_without_partial_mutation(tmp_path):
    registry = FakeTaskRegistry()
    queue = _queue(tmp_path, registry)
    for task_id in ["a", "b"]:
        _enqueue(queue, registry, task_id)
    queue._mark_running(queue.snapshot()["items"][0], {"mem_available_mb": 4096, "swap_used_percent": 0, "load_1m": 0})

    with pytest.raises(ValueError, match="队列任务不存在"):
        queue.manual_adjust("", "reorder", task_ids=["b", "missing"])
    with pytest.raises(ValueError, match="只有排队中或延后中的任务可以拖拽排序"):
        queue.manual_adjust("", "reorder", task_ids=["b", "a"])

    items = {item["task_id"]: item for item in queue.snapshot()["items"]}
    assert items["a"]["status"] == "running"
    assert "manual_order_index" not in items["b"]
    assert registry.tasks["b"]["metadata"].get("queue_manual_order_index") is None


def test_manual_delay_and_promote_do_not_keep_stale_drag_order(tmp_path):
    registry = FakeTaskRegistry()
    queue = _queue(tmp_path, registry)
    for task_id in ["a", "b"]:
        _enqueue(queue, registry, task_id)

    queue.manual_adjust("", "reorder", task_ids=["b", "a"])
    delayed = queue.manual_adjust("b", "delay", delay_seconds=600)["item"]
    promoted = queue.manual_adjust("b", "promote")["item"]

    assert "manual_order_index" not in delayed
    assert delayed["manual_priority"] == 100
    assert promoted["manual_order_index"] == 0
    assert promoted["manual_priority"] == 0
