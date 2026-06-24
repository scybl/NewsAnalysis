const kaipanlaStatus = document.querySelector("#kaipanlaStatus");
const kaipanlaRunNowBtn = document.querySelector("#kaipanlaRunNowBtn");
const kaipanlaSaveBtn = document.querySelector("#kaipanlaSaveBtn");
const kaipanlaScheduleMeta = document.querySelector("#kaipanlaScheduleMeta");
const kaipanlaStateText = document.querySelector("#kaipanlaStateText");
const kaipanlaTimeText = document.querySelector("#kaipanlaTimeText");
const kaipanlaFeatureCount = document.querySelector("#kaipanlaFeatureCount");
const kaipanlaLastDate = document.querySelector("#kaipanlaLastDate");
const kaipanlaLastResult = document.querySelector("#kaipanlaLastResult");
const kaipanlaEnabled = document.querySelector("#kaipanlaEnabled");
const kaipanlaTime = document.querySelector("#kaipanlaTime");
const kaipanlaFeatureMeta = document.querySelector("#kaipanlaFeatureMeta");
const kaipanlaFeatureGrid = document.querySelector("#kaipanlaFeatureGrid");
const kaipanlaParamFeatureSelect = document.querySelector("#kaipanlaParamFeatureSelect");
const kaipanlaParamsInput = document.querySelector("#kaipanlaParamsInput");
const kaipanlaParamMeta = document.querySelector("#kaipanlaParamMeta");
const kaipanlaRecordsTable = document.querySelector("#kaipanlaRecordsTable");
const kaipanlaRecordMeta = document.querySelector("#kaipanlaRecordMeta");
const kaipanlaOutput = document.querySelector("#kaipanlaOutput");

const kaipanlaState = {
  features: [],
  scheduler: {},
  paramsByFeature: {},
  currentParamFeature: "",
};

document.addEventListener("DOMContentLoaded", () => {
  bindKaipanlaEvents();
  loadKaipanlaPage();
});

function bindKaipanlaEvents() {
  kaipanlaSaveBtn?.addEventListener("click", saveKaipanlaScheduler);
  kaipanlaRunNowBtn?.addEventListener("click", runKaipanlaNow);
  kaipanlaParamFeatureSelect?.addEventListener("change", () => {
    persistCurrentParams();
    renderSelectedParams();
  });
}

async function loadKaipanlaPage() {
  try {
    const [featuresResponse, schedulerResponse, recordsResponse] = await Promise.all([
      fetch("/api/admin/kaipanla/features"),
      fetch("/api/admin/kaipanla/scheduler"),
      fetch("/api/admin/kaipanla/records?limit=80"),
    ]);
    const featuresPayload = await readJsonPayload(featuresResponse, "读取开盘啦功能失败");
    const schedulerPayload = await readJsonPayload(schedulerResponse, "读取开盘啦定时失败");
    const recordsPayload = await readJsonPayload(recordsResponse, "读取开盘啦记录失败");
    kaipanlaState.features = featuresPayload.items || [];
    renderFeatures();
    renderScheduler(schedulerPayload.scheduler || {});
    renderRecords(recordsPayload.items || []);
    kaipanlaStatus.textContent = `已集成 ${kaipanlaState.features.length} 个开盘啦功能。`;
  } catch (error) {
    kaipanlaStatus.textContent = `读取失败：${error.message}`;
    kaipanlaOutput.textContent = error.message;
  }
}

function renderFeatures() {
  const selected = new Set(kaipanlaState.scheduler.features || ["daily_data", "market_limit_up_ladder", "sector_ranking"]);
  kaipanlaFeatureGrid.innerHTML = kaipanlaState.features
    .map((item) => `
      <label class="kaipanla-feature-option">
        <input type="checkbox" value="${escapeAttr(item.key)}" ${selected.has(item.key) ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(item.label)}</strong>
          <small>${escapeHtml(item.category)}${item.requires ? ` · ${escapeHtml(item.requires)}` : ""}</small>
        </span>
      </label>
    `)
    .join("");
  kaipanlaParamFeatureSelect.innerHTML = kaipanlaState.features
    .map((item) => `<option value="${escapeAttr(item.key)}">${escapeHtml(item.label)}</option>`)
    .join("");
  kaipanlaFeatureMeta.textContent = `${kaipanlaState.features.length} 个功能`;
  renderSelectedParams();
}

function renderScheduler(scheduler) {
  kaipanlaState.scheduler = scheduler || {};
  kaipanlaState.paramsByFeature = scheduler.params_by_feature || {};
  const running = !!scheduler.running;
  kaipanlaEnabled.value = scheduler.enabled ? "1" : "0";
  kaipanlaTime.value = scheduler.time || "21:45";
  kaipanlaScheduleMeta.textContent = running ? "运行中" : scheduler.enabled ? `已启用 · ${scheduler.time || "21:45"}` : "未启用";
  kaipanlaStateText.textContent = running ? "运行中" : scheduler.enabled ? "已启用" : "未启用";
  kaipanlaTimeText.textContent = scheduler.time || "21:45";
  kaipanlaFeatureCount.textContent = String((scheduler.features || []).length);
  kaipanlaLastDate.textContent = scheduler.last_run_date || "-";
  const last = scheduler.last_result || {};
  kaipanlaLastResult.textContent = last.total ? `${last.succeeded || 0} / ${last.failed || 0}` : "-";
  kaipanlaRunNowBtn.disabled = running;
  renderFeatures();
}

function renderSelectedParams() {
  const key = kaipanlaParamFeatureSelect.value || kaipanlaState.features[0]?.key || "";
  const feature = kaipanlaState.features.find((item) => item.key === key);
  if (!feature) return;
  const params = kaipanlaState.paramsByFeature[key] || feature.default_params || {};
  kaipanlaParamsInput.value = JSON.stringify(params, null, 2);
  kaipanlaParamMeta.textContent = feature.description || "";
  kaipanlaState.currentParamFeature = key;
}

function persistCurrentParams() {
  const currentKey = kaipanlaState.currentParamFeature || kaipanlaParamFeatureSelect.value;
  if (!currentKey) return;
  kaipanlaState.paramsByFeature = {
    ...kaipanlaState.paramsByFeature,
    [currentKey]: JSON.parse(kaipanlaParamsInput.value || "{}"),
  };
}

function collectSchedulerPayload() {
  const features = [...kaipanlaFeatureGrid.querySelectorAll("input[type='checkbox']:checked")].map((input) => input.value);
  persistCurrentParams();
  const paramsByFeature = { ...kaipanlaState.paramsByFeature };
  return {
    action: "save",
    enabled: kaipanlaEnabled.value === "1",
    time: kaipanlaTime.value || "21:45",
    features,
    params_by_feature: paramsByFeature,
  };
}

async function saveKaipanlaScheduler() {
  kaipanlaSaveBtn.disabled = true;
  try {
    const payload = collectSchedulerPayload();
    const response = await fetch("/api/admin/kaipanla/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readJsonPayload(response, "保存开盘啦定时失败");
    renderScheduler(result.scheduler || {});
    kaipanlaOutput.textContent = "开盘啦定时配置已保存。";
    return true;
  } catch (error) {
    kaipanlaOutput.textContent = `保存失败：${error.message}`;
    return false;
  } finally {
    kaipanlaSaveBtn.disabled = false;
  }
}

async function runKaipanlaNow() {
  if (!window.confirm("该操作会访问开盘啦等外部数据源并把结果保存到本地。确认执行？")) return;
  kaipanlaRunNowBtn.disabled = true;
  try {
    const saved = await saveKaipanlaScheduler();
    if (!saved) return;
    const response = await fetch("/api/admin/kaipanla/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now", approved: true }),
    });
    const payload = await readJsonPayload(response, "启动开盘啦抓取失败");
    renderScheduler(payload.scheduler || {});
    kaipanlaOutput.textContent = "开盘啦抓取任务已启动。";
    window.setTimeout(loadKaipanlaPage, 2500);
  } catch (error) {
    kaipanlaOutput.textContent = `启动失败：${error.message}`;
  } finally {
    kaipanlaRunNowBtn.disabled = false;
  }
}

function renderRecords(items) {
  kaipanlaRecordMeta.textContent = `${items.length} 条记录`;
  const rows = items.map((item) => `
    <tr>
      <td>${escapeHtml(item.saved_at || "")}</td>
      <td>${escapeHtml(item.label || item.feature || "")}<br><code>${escapeHtml(item.feature || "")}</code></td>
      <td>${escapeHtml(item.category || "")}</td>
      <td><code>${escapeHtml(item.run_id || "")}</code></td>
      <td><button type="button" data-record-path="${escapeAttr(item.path || "")}">查看</button></td>
    </tr>
  `).join("");
  kaipanlaRecordsTable.innerHTML = `
    <thead><tr><th>保存时间</th><th>功能</th><th>分类</th><th>Run</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5">暂无本地记录</td></tr>`}</tbody>
  `;
  kaipanlaRecordsTable.querySelectorAll("[data-record-path]").forEach((button) => {
    button.addEventListener("click", () => readKaipanlaRecord(button.dataset.recordPath));
  });
}

async function readKaipanlaRecord(path) {
  if (!path) return;
  try {
    const response = await fetch(`/api/admin/kaipanla/record?path=${encodeURIComponent(path)}`);
    const payload = await readJsonPayload(response, "读取记录失败");
    kaipanlaOutput.textContent = JSON.stringify(payload.record || {}, null, 2);
  } catch (error) {
    kaipanlaOutput.textContent = `读取记录失败：${error.message}`;
  }
}

async function readJsonPayload(response, fallbackMessage) {
  const payload = await response.json();
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("登录状态已失效，正在返回登录页。");
  }
  if (!response.ok || payload.ok === false) throw new Error(payload.error || fallbackMessage);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
