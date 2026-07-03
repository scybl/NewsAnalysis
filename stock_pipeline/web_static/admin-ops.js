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
  unknown: "未知",
  running_unknown_pid: "运行中",
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
  opsMeta.textContent = `${statusLabel(overall.status)} · ${formatDateTime(snapshot.generated_at)} · ${tasks.length} 个任务`;
  renderOpsSummary(overall);
  renderOpsTasks(tasks);
  renderOpsErrors(tasks, overall.warnings || []);
  renderOpsData(snapshot.data || {});
}

function renderOpsSummary(overall) {
  const items = [
    ["系统状态", statusLabel(overall.status), overall.status || "unknown"],
    ["运行任务", overall.running_count ?? 0, ""],
    ["重 IO", overall.heavy_io_running ? "占用" : "空闲", overall.heavy_io_running ? "warning" : "ok"],
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
      <td>
        <strong>${escapeHtml(task.title || task.id || "-")}</strong>
        <small>${escapeHtml(task.kind || "")}</small>
      </td>
      <td>${statusBadge(task.status)}</td>
      <td>${task.running ? "是" : "否"}</td>
      <td>${escapeHtml(task.resource_level === "heavy_io" ? "heavy_io" : "normal")}</td>
      <td>${escapeHtml(progressText(task.progress || {}))}</td>
      <td class="ops-detail-cell">${escapeHtml(detailText(task))}</td>
      <td class="ops-log-cell">${logCommand(task)}</td>
    </tr>
  `).join("");
  opsTasksTable.innerHTML = `
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
  return `<span class="ops-status-badge is-${escapeAttr(safeStatus)}">${escapeHtml(statusLabel(safeStatus))}</span>`;
}

function statusLabel(status) {
  return OPS_STATUS_LABELS[status] || status || "未知";
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
    task.last_event || "",
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
    <code title="${escapeAttr(task.log_file)}">${escapeHtml(fileName(task.log_file))}</code>
    <button type="button" data-copy-tail="${escapeAttr(command)}">复制</button>
  `;
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
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
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
