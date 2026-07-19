const opsMeta = document.querySelector("#opsMeta");
const opsSummary = document.querySelector("#opsSummary");
const opsTaskMeta = document.querySelector("#opsTaskMeta");
const opsQueueMeta = document.querySelector("#opsQueueMeta");
const opsQueueTable = document.querySelector("#opsQueueTable");
const opsErrorMeta = document.querySelector("#opsErrorMeta");
const opsDataMeta = document.querySelector("#opsDataMeta");
const opsTasksTable = document.querySelector("#opsTasksTable");
const opsErrors = document.querySelector("#opsErrors");
const opsData = document.querySelector("#opsData");
const opsRefreshBtn = document.querySelector("#opsRefreshBtn");

const OPS_STATUS_LABELS = {
  ok: "正常",
  warning: "警告",
  danger: "危险",
  running: "运行中",
  idle: "空闲",
  paused: "暂停",
  failed: "失败",
  failed_or_stopped: "异常停止",
  succeeded: "已完成",
  queued: "排队中",
  deferred: "延后中",
  cancelled: "已取消",
  unknown: "未知",
  unconfigured: "未配置",
  running_unknown_pid: "运行中",
};

const OPS_STATUS_HINTS = {
  succeeded: "任务最近一次完整执行成功，当前没有运行中的进程。",
  failed: "任务最近一次执行失败，或调度记录里保留了错误信息。",
  failed_or_stopped: "任务曾处于运行状态，但现在找不到进程，也没有成功 summary。",
  running: "任务正在执行，进程或调度记录仍处于运行状态。",
  queued: "任务已进入资源队列，按提交顺序等待执行。",
  deferred: "任务在队列中，但当前内存、swap、负载或重 IO 状态不适合执行。",
  cancelled: "任务已被管理员从队列中取消。",
  idle: "调度器可用但当前空闲，等待下一次触发。",
  paused: "调度器被关闭或手动暂停。",
  warning: "任务可读但存在告警，需要检查最近异常。",
  unknown: "缺少配置、日志或状态文件，暂时无法判断。",
  unconfigured: "调度配置文件尚未生成，保存一次定时配置后会进入空闲或排队状态。",
  running_unknown_pid: "状态显示运行中，但无法确认具体进程号。",
};

const OPS_EVENT_LABELS = {
  summary: "完成摘要",
  succeeded: "成功",
  failed: "失败",
  queued: "排队中",
  deferred: "延后中",
  cancelled: "已取消",
  running: "运行中",
  idle: "空闲",
  unknown: "未知",
  upload_start: "开始上传",
  upload_done: "上传完成",
  write_start: "开始写文件",
  write_done: "写文件完成",
  local_removed: "本地已清理",
  index_done: "索引完成",
  crawler_status_snapshot: "爬虫状态快照",
  throttled: "资源暂停",
  resumed: "恢复执行",
};

let opsAdminReadonly = false;
let draggedQueueRow = null;
let draggedQueueStartOrder = [];

document.addEventListener("DOMContentLoaded", async () => {
  if (!(await loadOpsSession())) return;
  opsRefreshBtn?.addEventListener("click", loadOpsStatus);
  opsQueueTable?.addEventListener("click", handleQueueTableClick);
  opsQueueTable?.addEventListener("dragstart", handleQueueDragStart);
  opsQueueTable?.addEventListener("dragover", handleQueueDragOver);
  opsQueueTable?.addEventListener("drop", handleQueueDrop);
  opsQueueTable?.addEventListener("dragend", handleQueueDragEnd);
  opsTasksTable?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy-tail]");
    if (button) copyTailCommand(button);
  });
  loadOpsStatus();
});

async function loadOpsSession() {
  try {
    const response = await fetch("/api/session");
    const payload = await response.json();
    if (!response.ok || payload.ok === false || !payload.authenticated) {
      window.location.href = "/login";
      return false;
    }
    if (!["admin", "admin_readonly"].includes(payload.role || "")) {
      window.location.href = "/";
      return false;
    }
    opsAdminReadonly = payload.role === "admin_readonly";
    applyOpsReadonlyMode();
    return true;
  } catch {
    window.location.href = "/login";
    return false;
  }
}

async function loadOpsStatus() {
  if (opsRefreshBtn) opsRefreshBtn.disabled = true;
  opsMeta.textContent = "正在读取状态...";
  try {
    const response = await fetch("/api/admin/ops/status");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "读取运维状态失败");
    }
    renderOpsSnapshot(payload.snapshot || {});
  } catch (error) {
    renderOpsError(error);
  } finally {
    if (opsRefreshBtn) opsRefreshBtn.disabled = false;
  }
}

function renderOpsSnapshot(snapshot) {
  const overall = snapshot.overall || {};
  const tasks = snapshot.tasks || [];
  const resources = snapshot.resources || {};
  opsMeta.textContent = `${statusLabel(overall.status)} · ${formatDateTime(snapshot.generated_at)} · ${tasks.length} 个任务`;
  renderOpsSummary(overall, resources.task_queue || {});
  renderOpsQueue(resources.task_queue || {});
  renderOpsTasks(tasks);
  renderOpsErrors(tasks, overall.warnings || []);
  renderOpsData(snapshot.data || {});
}

function renderOpsSummary(overall, queue) {
  const queueCounts = queue.counts || {};
  const queuedCount = Number(queueCounts.queued || 0) + Number(queueCounts.deferred || 0) + Number(queueCounts.running || 0);
  const queueTone = Number(queueCounts.deferred || 0) ? "warning" : queuedCount ? "ok" : "";
  const items = [
    ["系统状态", statusLabel(overall.status), overall.status || "unknown"],
    ["运行任务", overall.running_count ?? 0, ""],
    ["重 IO", overall.heavy_io_running ? "占用" : "空闲", overall.heavy_io_running ? "warning" : "ok"],
    ["队列", queuedCount ? `${queuedCount} 个` : "空", queueTone],
    ["告警", (overall.warnings || []).length, ""],
  ];
  opsSummary.innerHTML = items.map(([label, value, tone]) => `
    <div class="${tone ? `is-${escapeAttr(tone)}` : ""}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");
}

function applyOpsReadonlyMode() {
  if (!opsAdminReadonly || document.querySelector(".admin-readonly-banner")) return;
  const banner = document.createElement("div");
  banner.className = "admin-readonly-banner";
  banner.textContent = "只读展示模式：可以查看后台队列和运行状态，但不能拖拽排序、置顶、延后、取消或重试任务。";
  document.querySelector(".admin-workspace")?.prepend(banner);
}

function renderOpsQueue(queue) {
  const items = queue.items || [];
  const counts = queue.counts || {};
  const activeCount = Number(counts.queued || 0) + Number(counts.deferred || 0) + Number(counts.running || 0);
  if (opsQueueMeta) {
    opsQueueMeta.textContent = items.length ? `${activeCount} 个活动队列项，展示 ${items.length} 个` : "当前队列为空";
  }
  if (!opsQueueTable) return;
  const rows = items.map((item) => `
    <tr data-queue-task-id="${escapeAttr(item.task_id || "")}" data-queue-draggable="${queueItemCanDrag(item) ? "true" : "false"}" class="${queueItemCanDrag(item) ? "is-draggable" : ""}">
      <td class="ops-queue-drag-cell">${queueDragHandle(item)}</td>
      <td class="ops-queue-task-cell">
        <strong>${escapeHtml(item.title || item.task_id || "-")}</strong>
        <small>${escapeHtml(taskKindLabel(item.kind))} · ${escapeHtml(item.task_id || "-")}</small>
      </td>
      <td>${statusBadge(item.status)}</td>
      <td>${escapeHtml(queuePriorityText(item))}</td>
      <td>${escapeHtml(queueRunAfterText(item))}</td>
      <td class="ops-queue-payload-cell">${escapeHtml(queuePayloadText(item.payload || {}))}</td>
      <td>${queueActionButtons(item)}</td>
    </tr>
  `).join("");
  opsQueueTable.innerHTML = `
    <colgroup>
      <col class="ops-queue-drag-col" />
      <col class="ops-queue-task-col" />
      <col class="ops-queue-status-col" />
      <col class="ops-queue-priority-col" />
      <col class="ops-queue-run-col" />
      <col class="ops-queue-payload-col" />
      <col class="ops-queue-action-col" />
    </colgroup>
    <thead>
      <tr>
        <th></th>
        <th>队列项</th>
        <th>状态</th>
        <th>优先级</th>
        <th>下次运行</th>
        <th>参数摘要</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody>${rows || `<tr><td colspan="7" class="news-empty compact">暂无活动队列项。</td></tr>`}</tbody>
  `;
}

function queueItemCanDrag(item) {
  return !opsAdminReadonly && Boolean(item.task_id) && item.reorderable !== false && ["queued", "deferred"].includes(item.status || "");
}

function queueDragHandle(item) {
  const canDrag = queueItemCanDrag(item);
  const title = canDrag ? "拖动排序" : (opsAdminReadonly ? "只读账号不可排序" : "运行中任务不可排序");
  return `
    <span
      class="ops-drag-handle ${canDrag ? "" : "is-disabled"}"
      data-queue-drag-handle="true"
      draggable="${canDrag ? "true" : "false"}"
      title="${escapeAttr(title)}"
      aria-label="${escapeAttr(title)}"
    >⋮⋮</span>
  `;
}

function queueActionButtons(item) {
  const status = item.status || "";
  const taskId = item.task_id || "";
  const disabled = opsAdminReadonly || !taskId;
  const buttons = [];
  if (["queued", "deferred"].includes(status)) {
    buttons.push(queueButton("promote", taskId, "置顶", disabled));
    buttons.push(queueButton("delay", taskId, "延后30分", disabled));
  }
  if (["running"].includes(status)) {
    buttons.push(queueButton("retry", taskId, "重试", disabled));
  }
  if (["queued", "deferred", "running"].includes(status)) {
    buttons.push(queueButton("cancel", taskId, "取消", disabled, "danger"));
  }
  return buttons.length ? `<div class="ops-queue-actions">${buttons.join("")}</div>` : "-";
}

function queueButton(action, taskId, label, disabled, tone = "") {
  return `<button type="button" data-queue-action="${escapeAttr(action)}" data-queue-task-id="${escapeAttr(taskId)}" class="${tone ? `is-${escapeAttr(tone)}` : ""}" ${disabled ? "disabled" : ""}>${escapeHtml(label)}</button>`;
}

function handleQueueDragStart(event) {
  const handle = event.target.closest("[data-queue-drag-handle]");
  if (!handle || opsAdminReadonly) {
    event.preventDefault();
    return;
  }
  const row = handle.closest("tr[data-queue-draggable='true']");
  if (!row) {
    event.preventDefault();
    return;
  }
  draggedQueueRow = row;
  draggedQueueStartOrder = queueDraggableTaskIds();
  row.classList.add("is-dragging");
  opsQueueTable?.classList.add("is-drag-active");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", row.dataset.queueTaskId || "");
}

function handleQueueDragOver(event) {
  if (!draggedQueueRow) return;
  const targetRow = event.target.closest("tbody tr[data-queue-draggable='true']");
  if (!targetRow || targetRow === draggedQueueRow) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  const rect = targetRow.getBoundingClientRect();
  const insertAfter = event.clientY > rect.top + rect.height / 2;
  targetRow.parentNode.insertBefore(draggedQueueRow, insertAfter ? targetRow.nextSibling : targetRow);
}

function handleQueueDrop(event) {
  if (!draggedQueueRow) return;
  event.preventDefault();
  const taskIds = queueDraggableTaskIds();
  const changed = taskIds.join("\n") !== draggedQueueStartOrder.join("\n");
  cleanupQueueDrag();
  if (!changed || taskIds.length < 1) return;
  submitQueueReorder(taskIds);
}

function handleQueueDragEnd() {
  cleanupQueueDrag();
}

function cleanupQueueDrag() {
  if (draggedQueueRow) draggedQueueRow.classList.remove("is-dragging");
  opsQueueTable?.classList.remove("is-drag-active");
  draggedQueueRow = null;
  draggedQueueStartOrder = [];
}

function queueDraggableTaskIds() {
  if (!opsQueueTable) return [];
  return Array.from(opsQueueTable.querySelectorAll("tbody tr[data-queue-draggable='true']"))
    .map((row) => row.dataset.queueTaskId || "")
    .filter(Boolean);
}

async function submitQueueReorder(taskIds) {
  if (opsAdminReadonly) return;
  opsQueueTable?.classList.add("is-queue-saving");
  try {
    const response = await fetch("/api/admin/task-queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "reorder", task_ids: taskIds, approved: true }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "队列排序失败");
    }
    renderOpsSnapshot(payload.snapshot || {});
  } catch (error) {
    window.alert(error.message);
    await loadOpsStatus();
  } finally {
    opsQueueTable?.classList.remove("is-queue-saving");
  }
}

async function handleQueueTableClick(event) {
  const button = event.target.closest("[data-queue-action]");
  if (!button || opsAdminReadonly || button.disabled) return;
  const action = button.dataset.queueAction || "";
  const taskId = button.dataset.queueTaskId || "";
  if (!taskId) return;
  const label = button.textContent || action;
  if (!window.confirm(`确认${label}这个队列任务？`)) return;
  const body = { action, task_id: taskId, approved: true };
  if (action === "delay") body.delay_seconds = 30 * 60;
  button.disabled = true;
  try {
    const response = await fetch("/api/admin/task-queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "队列操作失败");
    }
    renderOpsSnapshot(payload.snapshot || {});
  } catch (error) {
    window.alert(error.message);
    await loadOpsStatus();
  }
}

function queuePriorityText(item) {
  if (item.manual_order_index === 0 || item.manual_order_index) return `手动 ${Number(item.manual_order_index) + 1}`;
  if (Number(item.manual_priority) === 0) return "手动置顶";
  if (item.status === "running") return "运行中";
  return "-";
}

function queueRunAfterText(item) {
  const runAfter = Number(item.run_after_epoch || 0);
  if (!runAfter) return "-";
  const remaining = Math.max(0, runAfter - Date.now() / 1000);
  return remaining <= 1 ? "可执行" : `${formatDuration(remaining)}后`;
}

function queuePayloadText(payload) {
  const parts = [];
  for (const key of ["trigger", "trade_date", "target_date", "ts_code", "source"]) {
    if (payload[key]) parts.push(`${key}=${payload[key]}`);
  }
  if (payload.features || payload.features === 0) parts.push(`features=${payload.features}`);
  if (payload.resume_stage) parts.push(`resume=${payload.resume_stage}`);
  return parts.join(" · ") || "-";
}

function renderOpsTasks(tasks) {
  opsTaskMeta.textContent = tasks.length ? `${tasks.length} 个状态源` : "暂无状态源";
  const rows = tasks.map((task) => `
    <tr>
      <td class="ops-task-cell">
        <strong>${escapeHtml(task.title || task.id || "-")}</strong>
        <small>${escapeHtml(taskKindLabel(task.kind))}</small>
      </td>
      <td class="ops-status-cell">${statusBadge(task.status)}</td>
      <td class="ops-running-cell">${task.running ? "是" : "否"}</td>
      <td class="ops-resource-cell">${escapeHtml(task.resource_level || "normal")}</td>
      <td class="ops-progress-cell">${escapeHtml(progressText(task.progress || {}))}</td>
      <td class="ops-detail-cell">${escapeHtml(detailText(task))}</td>
      <td class="ops-log-cell">${logCommand(task)}</td>
    </tr>
  `).join("");
  opsTasksTable.innerHTML = `
    <colgroup>
      <col class="ops-task-col" />
      <col class="ops-status-col" />
      <col class="ops-running-col" />
      <col class="ops-resource-col" />
      <col class="ops-progress-col" />
      <col class="ops-event-col" />
      <col class="ops-log-col" />
    </colgroup>
    <thead>
      <tr>
        <th>任务</th>
        <th>状态</th>
        <th>运行</th>
        <th>资源</th>
        <th>进度</th>
        <th>最后事件</th>
        <th>日志</th>
      </tr>
    </thead>
    <tbody>${rows || `<tr><td colspan="7" class="news-empty compact">暂无任务状态。</td></tr>`}</tbody>
  `;
}

function taskKindLabel(kind) {
  return ({
    daily_market: "股票数据",
    idle_stock_prefetch: "空闲预抓",
    kaipanla: "行情数据",
    data_random_audit: "数据抽检",
    stock_storage_health: "存储健康",
    spider: "行情数据",
    news_crawler: "新闻爬虫",
  })[kind] || kind || "";
}

function renderOpsErrors(tasks, warnings) {
  const items = [
    ...tasks
      .filter((task) => task.last_error || ["failed", "failed_or_stopped", "warning"].includes(task.status || ""))
      .map((task) => ({ ...task, alert_status: alertStatus(task) })),
    ...warnings.map((message) => ({ title: "系统告警", status: "warning", alert_status: "warning", last_error: message })),
  ].slice(0, 8);
  opsErrorMeta.textContent = items.length ? `${items.length} 条` : "无异常";
  opsErrors.innerHTML = items.length
    ? items.map((item) => `
      <article class="ops-error-item">
        <div>
          <strong>${escapeHtml(item.title || item.id || "异常")}</strong>
          ${statusBadge(item.alert_status || item.status || "warning")}
        </div>
        <p>${escapeHtml(item.last_error || item.last_event || "")}</p>
      </article>
    `).join("")
    : `<div class="news-empty compact">暂无异常。</div>`;
}

function renderOpsData(data) {
  const entries = Object.entries(data || {});
  opsDataMeta.textContent = entries.length ? `${entries.length} 类` : "未接入";
  opsData.innerHTML = entries.length
    ? entries.map(([key, value]) => `
      <article>
        <strong>${escapeHtml(key)}</strong>
        <pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>
      </article>
    `).join("")
    : `<div class="news-empty compact">暂无数据覆盖快照。</div>`;
}

function renderOpsError(error) {
  opsMeta.textContent = `读取失败：${error.message}`;
  opsSummary.innerHTML = "";
  if (opsQueueMeta) opsQueueMeta.textContent = "连接失败";
  opsTaskMeta.textContent = "连接失败";
  opsErrorMeta.textContent = "连接失败";
  opsDataMeta.textContent = "连接失败";
  if (opsQueueTable) opsQueueTable.innerHTML = `<tbody><tr><td class="news-empty is-error">${escapeHtml(error.message)}</td></tr></tbody>`;
  opsTasksTable.innerHTML = `<tbody><tr><td class="news-empty is-error">${escapeHtml(error.message)}</td></tr></tbody>`;
  opsErrors.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  opsData.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
}

function statusBadge(status) {
  const safeStatus = status || "unknown";
  return `<span class="ops-status-badge is-${escapeAttr(safeStatus)}" title="${escapeAttr(statusHint(safeStatus))}">${escapeHtml(statusLabel(safeStatus))}</span>`;
}

function alertStatus(item) {
  const status = item.status || "";
  if (["failed", "failed_or_stopped", "danger"].includes(status)) return status;
  if (["warning", "running_unknown_pid"].includes(status)) return "warning";
  return item.last_error ? "warning" : (status || "warning");
}

function statusLabel(status) {
  return OPS_STATUS_LABELS[status] || status || "未知";
}

function statusHint(status) {
  return OPS_STATUS_HINTS[status] || "系统返回的自定义状态。";
}

function progressText(progress) {
  const current = progress.current;
  const total = progress.total;
  const percent = progress.percent;
  const ratio = current || total ? `${current ?? "-"}/${total ?? "-"}` : "";
  const pct = percent === 0 || percent ? `${Number(percent).toFixed(1)}%` : "";
  return [ratio, pct].filter(Boolean).join(" · ") || "-";
}

function detailText(task) {
  const details = task.details || {};
  const parts = [
    eventLabel(task.last_event),
    task.last_event_age_seconds || task.last_event_age_seconds === 0 ? `${formatDuration(task.last_event_age_seconds)}前` : "",
    details.ts_code || "",
    details.year || "",
    details.source || "",
    details.reason ? `reason=${details.reason}` : "",
  ];
  return parts.filter(Boolean).join(" · ") || "-";
}

function logCommand(task) {
  if (!task.log_file) return "-";
  const command = `tail -n 120 ${shellQuote(task.log_file)}`;
  return `
    <div class="ops-log-command">
      <code title="${escapeAttr(task.log_file)}">${escapeHtml(fileName(task.log_file))}</code>
      <button type="button" data-copy-tail="${escapeAttr(command)}">复制</button>
    </div>
  `;
}

function eventLabel(event) {
  if (!event) return "";
  return OPS_EVENT_LABELS[event] || event;
}

async function copyTailCommand(button) {
  const command = button.dataset.copyTail || "";
  if (!command) return;
  try {
    await navigator.clipboard.writeText(command);
    button.textContent = "已复制";
    setTimeout(() => {
      button.textContent = "复制";
    }, 1400);
  } catch {
    window.prompt("tail", command);
  }
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function fileName(value) {
  return String(value || "").split("/").filter(Boolean).pop() || value || "";
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${Math.round(value / 3600)} 小时`;
}

function formatDateTime(value) {
  const text = String(value || "").trim();
  if (!text || text === "-") return "-";
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})/);
  if (compact) return `${Number(compact[2])}月${Number(compact[3])}日${compact[4]}:${compact[5]}`;
  const plain = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})/);
  if (plain) return `${Number(plain[2])}月${Number(plain[3])}日${plain[4].padStart(2, "0")}:${plain[5]}`;
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}月${day}日${hour}:${minute}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
