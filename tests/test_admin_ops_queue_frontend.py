from pathlib import Path


ADMIN_STATIC = Path(__file__).resolve().parents[1] / "frontend" / "admin"


def test_ops_queue_frontend_uses_native_drag_drop_without_extra_library():
    script = (ADMIN_STATIC / "admin-ops.js").read_text(encoding="utf-8")

    assert 'addEventListener("dragstart", handleQueueDragStart)' in script
    assert 'addEventListener("dragover", handleQueueDragOver)' in script
    assert 'addEventListener("drop", handleQueueDrop)' in script
    assert 'addEventListener("dragend", handleQueueDragEnd)' in script
    assert "data-queue-drag-handle" in script
    assert 'draggable="${canDrag ? "true" : "false"}"' in script
    assert "Sortable" not in script
    assert "interact.js" not in script


def test_ops_queue_frontend_persists_reordered_task_ids_to_admin_api():
    script = (ADMIN_STATIC / "admin-ops.js").read_text(encoding="utf-8")

    assert "queueDraggableTaskIds" in script
    assert "submitQueueReorder(taskIds)" in script
    assert 'body: JSON.stringify({ action: "reorder", task_ids: taskIds, approved: true })' in script
    assert 'fetch("/api/admin/task-queue"' in script
    assert "await loadOpsStatus()" in script


def test_ops_queue_frontend_disables_dragging_for_readonly_or_running_rows():
    script = (ADMIN_STATIC / "admin-ops.js").read_text(encoding="utf-8")

    assert '["queued", "deferred"].includes(item.status || "")' in script
    assert "item.reorderable !== false" in script
    assert "opsAdminReadonly" in script
    assert "不能拖拽排序、置顶、延后、取消或重试任务" in script
    assert "运行中任务不可排序" in script


def test_ops_queue_drag_styles_cover_light_and_dark_modes():
    styles = (ADMIN_STATIC / "styles.css").read_text(encoding="utf-8")
    html = (ADMIN_STATIC / "admin-ops.html").read_text(encoding="utf-8")

    assert "后台任务队列" in html
    assert "opsQueueTable" in html
    assert ".ops-drag-handle" in styles
    assert ".ops-queue-wrap tbody tr.is-dragging" in styles
    assert ".ops-queue-wrap table.is-drag-active" in styles
    assert ".ops-queue-wrap table.is-queue-saving" in styles
    assert "html.theme-dark .ops-drag-handle" in styles
