const dataAuditMeta = document.querySelector("#dataAuditMeta");
const dataAuditRunBtn = document.querySelector("#dataAuditRunBtn");
const dataAuditSampleSize = document.querySelector("#dataAuditSampleSize");
const dataAuditSeed = document.querySelector("#dataAuditSeed");
const dataAuditColdRead = document.querySelector("#dataAuditColdRead");
const dataAuditSummary = document.querySelector("#dataAuditSummary");
const dataAuditChecksMeta = document.querySelector("#dataAuditChecksMeta");
const dataAuditChecks = document.querySelector("#dataAuditChecks");
const dataAuditAnomalyMeta = document.querySelector("#dataAuditAnomalyMeta");
const dataAuditAnomalies = document.querySelector("#dataAuditAnomalies");
const dataAuditDetailsMeta = document.querySelector("#dataAuditDetailsMeta");
const dataAuditDetails = document.querySelector("#dataAuditDetails");
const dataAuditSchedulerMeta = document.querySelector("#dataAuditSchedulerMeta");
const dataAuditSchedulerEnabled = document.querySelector("#dataAuditSchedulerEnabled");
const dataAuditSchedulerIdleSeconds = document.querySelector("#dataAuditSchedulerIdleSeconds");
const dataAuditSchedulerIntervalSeconds = document.querySelector("#dataAuditSchedulerIntervalSeconds");
const dataAuditSchedulerSampleSize = document.querySelector("#dataAuditSchedulerSampleSize");
const dataAuditSchedulerColdReadSamples = document.querySelector("#dataAuditSchedulerColdReadSamples");
const dataAuditSchedulerIdleRemaining = document.querySelector("#dataAuditSchedulerIdleRemaining");
const dataAuditSchedulerIntervalRemaining = document.querySelector("#dataAuditSchedulerIntervalRemaining");
const dataAuditSchedulerLastRun = document.querySelector("#dataAuditSchedulerLastRun");
const dataAuditSchedulerLastResult = document.querySelector("#dataAuditSchedulerLastResult");
const dataAuditSchedulerSaveBtn = document.querySelector("#dataAuditSchedulerSaveBtn");
const dataAuditSchedulerRunBtn = document.querySelector("#dataAuditSchedulerRunBtn");

const AUDIT_STATUS_LABELS = {
  ok: "正常",
  warning: "警告",
  danger: "危险",
};

document.addEventListener("DOMContentLoaded", async () => {
  if (!(await loadDataAuditSession())) return;
  dataAuditRunBtn?.addEventListener("click", runDataAudit);
  dataAuditSchedulerSaveBtn?.addEventListener("click", saveDataAuditScheduler);
  dataAuditSchedulerRunBtn?.addEventListener("click", runDataAuditSchedulerNow);
  refreshDataAuditScheduler();
  if (document.body?.dataset.dataAuditAutoRun === "true") {
    runDataAudit();
  }
});

async function loadDataAuditSession() {
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
    if (payload.role === "admin_readonly" && dataAuditColdRead) {
      dataAuditColdRead.checked = false;
      dataAuditColdRead.disabled = true;
      if (dataAuditSchedulerSaveBtn) dataAuditSchedulerSaveBtn.disabled = true;
      if (dataAuditSchedulerRunBtn) dataAuditSchedulerRunBtn.disabled = true;
      if (dataAuditSchedulerEnabled) dataAuditSchedulerEnabled.disabled = true;
      if (dataAuditSchedulerColdReadSamples) dataAuditSchedulerColdReadSamples.disabled = true;
    }
    return true;
  } catch {
    window.location.href = "/login";
    return false;
  }
}

async function refreshDataAuditScheduler() {
  if (!dataAuditSchedulerMeta) return;
  dataAuditSchedulerMeta.textContent = "正在读取空闲抽检配置...";
  try {
    const response = await fetch("/api/admin/data-random-audit/scheduler");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "读取空闲抽检配置失败");
    }
    renderDataAuditScheduler(payload.scheduler || {});
  } catch (error) {
    dataAuditSchedulerMeta.textContent = `读取失败：${error.message}`;
  }
}

async function saveDataAuditScheduler() {
  if (!dataAuditSchedulerSaveBtn) return;
  dataAuditSchedulerSaveBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/data-random-audit/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save",
        enabled: !!dataAuditSchedulerEnabled?.checked,
        idle_seconds: Number(dataAuditSchedulerIdleSeconds?.value || 1800),
        interval_seconds: Number(dataAuditSchedulerIntervalSeconds?.value || 21600),
        sample_size: Number(dataAuditSchedulerSampleSize?.value || 20),
        cold_read_samples: Number(dataAuditSchedulerColdReadSamples?.value || 0),
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "保存空闲抽检配置失败");
    }
    renderDataAuditScheduler(payload.scheduler || {});
  } catch (error) {
    dataAuditSchedulerMeta.textContent = `保存失败：${error.message}`;
  } finally {
    dataAuditSchedulerSaveBtn.disabled = false;
  }
}

async function runDataAuditSchedulerNow() {
  if (!dataAuditSchedulerRunBtn) return;
  dataAuditSchedulerRunBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/data-random-audit/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now" }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "启动后台抽检失败");
    }
    renderDataAuditScheduler(payload.scheduler || {});
  } catch (error) {
    dataAuditSchedulerMeta.textContent = `启动失败：${error.message}`;
  } finally {
    dataAuditSchedulerRunBtn.disabled = false;
  }
}

function renderDataAuditScheduler(scheduler) {
  const running = !!scheduler.running;
  const queued = !!scheduler.queued;
  if (dataAuditSchedulerEnabled) dataAuditSchedulerEnabled.checked = !!scheduler.enabled;
  if (dataAuditSchedulerIdleSeconds) dataAuditSchedulerIdleSeconds.value = scheduler.idle_seconds || 1800;
  if (dataAuditSchedulerIntervalSeconds) dataAuditSchedulerIntervalSeconds.value = scheduler.interval_seconds || 21600;
  if (dataAuditSchedulerSampleSize) dataAuditSchedulerSampleSize.value = scheduler.sample_size || 20;
  if (dataAuditSchedulerColdReadSamples) dataAuditSchedulerColdReadSamples.value = scheduler.cold_read_samples || 0;
  if (dataAuditSchedulerMeta) {
    dataAuditSchedulerMeta.textContent = running
      ? "后台抽检运行中"
      : queued
        ? "后台抽检排队中"
        : scheduler.enabled
          ? `已启用 · 空闲 ${formatDuration(scheduler.idle_seconds || 1800)} · 间隔 ${formatDuration(scheduler.interval_seconds || 21600)}`
          : "未启用";
  }
  if (dataAuditSchedulerIdleRemaining) dataAuditSchedulerIdleRemaining.textContent = scheduler.remaining_idle_seconds ? formatDuration(scheduler.remaining_idle_seconds) : "可触发";
  if (dataAuditSchedulerIntervalRemaining) dataAuditSchedulerIntervalRemaining.textContent = scheduler.remaining_interval_seconds ? formatDuration(scheduler.remaining_interval_seconds) : "可触发";
  if (dataAuditSchedulerLastRun) dataAuditSchedulerLastRun.textContent = scheduler.last_run_at ? formatDateTime(scheduler.last_run_at) : "-";
  if (dataAuditSchedulerLastResult) {
    const result = scheduler.last_result || {};
    const summary = result.summary || {};
    dataAuditSchedulerLastResult.textContent = result.status
      ? `${statusLabel(summary.status || result.status)} · 异常 ${summary.anomalies ?? 0}`
      : "-";
  }
  if (dataAuditSchedulerRunBtn) dataAuditSchedulerRunBtn.disabled = running || queued;
}

async function runDataAudit() {
  const sampleSize = Math.max(1, Math.min(200, Number(dataAuditSampleSize?.value || 20)));
  const seed = String(dataAuditSeed?.value || "").trim();
  const coldReadSamples = dataAuditColdRead?.checked ? 2 : 0;
  const params = new URLSearchParams({
    sample_size: String(sampleSize),
    cold_read_samples: String(coldReadSamples),
  });
  if (seed) params.set("seed", seed);
  setLoadingState(true);
  try {
    const response = await fetch(`/api/admin/data-random-audit?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "随机抽检失败");
    }
    renderDataAudit(payload.audit || {});
  } catch (error) {
    renderDataAuditError(error);
  } finally {
    setLoadingState(false);
  }
}

function setLoadingState(loading) {
  if (dataAuditRunBtn) {
    dataAuditRunBtn.disabled = loading;
    dataAuditRunBtn.textContent = loading ? "抽检中..." : "开始抽检";
  }
  if (loading) {
    dataAuditMeta.textContent = "正在连接 MongoDB 并随机抽样...";
    dataAuditChecksMeta.textContent = "抽检运行中";
    dataAuditAnomalyMeta.textContent = "等待结果";
    dataAuditDetailsMeta.textContent = "等待结果";
  }
}

function renderDataAudit(audit) {
  const summary = audit.summary || {};
  const checks = audit.checks || [];
  const anomalies = checks.flatMap((check) => (check.anomalies || []).map((item) => ({ ...item, check_title: check.title })));
  dataAuditMeta.textContent = `${statusLabel(summary.status)} · ${formatDateTime(audit.generated_at)} · seed ${audit.seed || "-"} · 每类 ${audit.sample_size || 0} 个样本`;
  renderSummary(audit);
  renderChecks(checks);
  renderAnomalies(anomalies);
  renderDetails(checks);
}

function renderSummary(audit) {
  const summary = audit.summary || {};
  const items = [
    ["总体状态", statusLabel(summary.status), summary.status || "unknown"],
    ["检查项", summary.checks ?? 0, ""],
    ["正常", summary.ok_checks ?? 0, "ok"],
    ["警告", summary.warning_checks ?? 0, "warning"],
    ["危险", summary.danger_checks ?? 0, "danger"],
    ["异常点", summary.anomalies ?? 0, summary.anomalies ? "warning" : "ok"],
  ];
  dataAuditSummary.innerHTML = items.map(([label, value, tone]) => `
    <div class="${tone ? `is-${escapeAttr(tone)}` : ""}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `).join("");
}

function renderChecks(checks) {
  dataAuditChecksMeta.textContent = checks.length ? `${checks.length} 个检查项` : "暂无检查项";
  dataAuditChecks.innerHTML = checks.length
    ? checks.map((check) => `
      <article class="data-audit-check is-${escapeAttr(check.status || "unknown")}">
        <div class="data-audit-check-head">
          <div>
            <strong>${escapeHtml(check.title || check.key || "")}</strong>
            <p>${escapeHtml(check.description || "")}</p>
          </div>
          ${statusBadge(check.status)}
        </div>
        <dl>${metricPairs(check.metrics || {}).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatMetric(value))}</dd></div>`).join("")}</dl>
      </article>
    `).join("")
    : `<div class="news-empty compact">暂无检查项。</div>`;
}

function renderAnomalies(anomalies) {
  dataAuditAnomalyMeta.textContent = anomalies.length ? `${anomalies.length} 个异常点` : "未发现异常";
  dataAuditAnomalies.innerHTML = anomalies.length
    ? anomalies.map((item) => `
      <article class="data-audit-anomaly is-${escapeAttr(item.severity || "warning")}">
        <div>
          <strong>${escapeHtml(item.message || item.code || "")}</strong>
          ${statusBadge(item.severity)}
        </div>
        <p>${escapeHtml(item.check_title || "")} · ${escapeHtml(item.code || "")}</p>
        <pre>${escapeHtml(JSON.stringify(cleanAnomaly(item), null, 2))}</pre>
      </article>
    `).join("")
    : `<div class="news-empty compact">本次随机抽检未发现异常。</div>`;
}

function renderDetails(checks) {
  const groups = checks.filter((check) => (check.details || []).length);
  dataAuditDetailsMeta.textContent = groups.length ? `${groups.length} 类样本` : "无抽样明细";
  dataAuditDetails.innerHTML = groups.length
    ? groups.map((check) => `
      <section class="data-audit-detail-group">
        <h4>${escapeHtml(check.title || "")}</h4>
        <div>${(check.details || []).slice(0, 30).map((item) => `<pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre>`).join("")}</div>
      </section>
    `).join("")
    : `<div class="news-empty compact">暂无抽样明细。</div>`;
}

function renderDataAuditError(error) {
  dataAuditMeta.textContent = `抽检失败：${error.message}`;
  dataAuditSummary.innerHTML = "";
  dataAuditChecksMeta.textContent = "失败";
  dataAuditAnomalyMeta.textContent = "失败";
  dataAuditDetailsMeta.textContent = "失败";
  dataAuditChecks.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  dataAuditAnomalies.innerHTML = "";
  dataAuditDetails.innerHTML = "";
}

function metricPairs(metrics) {
  return Object.entries(metrics || {}).slice(0, 12);
}

function formatMetric(value) {
  if (Array.isArray(value)) return value.slice(0, 6).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return value ?? "-";
}

function statusBadge(status) {
  const value = status || "unknown";
  return `<span class="ops-status-badge is-${escapeAttr(value)}">${escapeHtml(statusLabel(value))}</span>`;
}

function statusLabel(status) {
  return AUDIT_STATUS_LABELS[status] || status || "未知";
}

function cleanAnomaly(item) {
  const clone = { ...item };
  delete clone.check_title;
  return clone;
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

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${value} 秒`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
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
