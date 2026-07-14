const opsMeta = document.querySelector("#opsMeta");
const opsSummary = document.querySelector("#opsSummary");
const opsTaskMeta = document.querySelector("#opsTaskMeta");
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
  unknown: "未知",
  running_unknown_pid: "运行中",
};

const OPS_STATUS_HINTS = {
  succeeded: "任务最近一次完整执行成功，当前没有运行中的进程。",
  failed: "任务最近一次执行失败，或调度记录里保留了错误信息。",
  failed_or_stopped: "任务曾处于运行状态，但现在找不到进程，也没有成功 summary。",
  running: "任务正在执行，进程或调度记录仍处于运行状态。",
  queued: "任务已进入资源队列，按提交顺序等待执行。",
  deferred: "任务在队列中，但当前内存、swap、负载或重 IO 状态不适合执行。",
  idle: "调度器可用但当前空闲，等待下一次触发。",
  paused: "调度器被关闭或手动暂停。",
  warning: "任务可读但存在告警，需要检查最近异常。",
  unknown: "缺少配置、日志或状态文件，暂时无法判断。",
  running_unknown_pid: "状态显示运行中，但无法确认具体进程号。",
};

const OPS_EVENT_LABELS = {
  summary: "完成摘要",
  succeeded: "成功",
  failed: "失败",
  queued: "排队中",
  deferred: "延后中",
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

document.addEventListener("DOMContentLoaded", async () => {
  if (!(await loadOpsSession())) return;
  opsRefreshBtn?.addEventListener("click", loadOpsStatus);
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
      <td class="ops-resource-cell">${escapeHtml(task.resource_level === "heavy_io" ? "heavy_io" : "normal")}</td>
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
    ...tasks.filter((task) => task.last_error || ["failed", "failed_or_stopped", "warning"].includes(task.status || "")),
    ...warnings.map((message) => ({ title: "系统告警", status: "warning", last_error: message })),
  ].slice(0, 8);
  opsErrorMeta.textContent = items.length ? `${items.length} 条` : "无异常";
  opsErrors.innerHTML = items.length
    ? items.map((item) => `
      <article class="ops-error-item">
        <div>
          <strong>${escapeHtml(item.title || item.id || "异常")}</strong>
          ${statusBadge(item.status || "warning")}
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
  opsTaskMeta.textContent = "连接失败";
  opsErrorMeta.textContent = "连接失败";
  opsDataMeta.textContent = "连接失败";
  opsTasksTable.innerHTML = `<tbody><tr><td class="news-empty is-error">${escapeHtml(error.message)}</td></tr></tbody>`;
  opsErrors.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  opsData.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
}

function statusBadge(status) {
  const safeStatus = status || "unknown";
  return `<span class="ops-status-badge is-${escapeAttr(safeStatus)}" title="${escapeAttr(statusHint(safeStatus))}">${escapeHtml(statusLabel(safeStatus))}</span>`;
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
