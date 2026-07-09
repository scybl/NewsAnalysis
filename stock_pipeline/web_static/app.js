const input = document.querySelector("#searchInput");
const results = document.querySelector("#results");
const statusEl = document.querySelector("#status");
const selectedTitle = document.querySelector("#selectedTitle");
const selectedMeta = document.querySelector("#selectedMeta");
const analyzeBtn = document.querySelector("#analyzeBtn");
const updateDataBtn = document.querySelector("#updateDataBtn");
const updateThsMarketBtn = document.querySelector("#updateThsMarketBtn");
const loadDataBtn = document.querySelector("#loadDataBtn");
const readAnalysisBtn = document.querySelector("#readAnalysisBtn");
const analysisTypeSelect = document.querySelector("#analysisTypeSelect");
const analysisHistorySelect = document.querySelector("#analysisHistorySelect");
const multiAgentBtn = document.querySelector("#multiAgentBtn");
const agentRunSelect = document.querySelector("#agentRunSelect");
const readAgentRunBtn = document.querySelector("#readAgentRunBtn");
const themeToggleBtn = document.querySelector("#themeToggleBtn");
const adminPanelLink = document.querySelector("#adminPanelLink");
const sidebarFooter = document.querySelector(".sidebar-footer");
const logoutBtn = document.querySelector("#logoutBtn");
const output = document.querySelector("#analysisOutput");
const scorePanel = document.querySelector("#scorePanel");
const apiKeyPanel = document.querySelector("#apiKeyPanel");
const accountTierText = document.querySelector("#accountTierText");
const userTushareApiInput = document.querySelector("#userTushareApiInput");
const userDeepSeekApiInput = document.querySelector("#userDeepSeekApiInput");
const saveUserApiKeysBtn = document.querySelector("#saveUserApiKeysBtn");
const deleteUserApiKeysBtn = document.querySelector("#deleteUserApiKeysBtn");
const apiKeyStatus = document.querySelector("#apiKeyStatus");
const metricLatestPrice = document.querySelector("#metricLatestPrice");
const metricPe = document.querySelector("#metricPe");
const metricPb = document.querySelector("#metricPb");
const metricDividend = document.querySelector("#metricDividend");
const agentDashboard = document.querySelector("#agentDashboard");
const agentDashboardMeta = document.querySelector("#agentDashboardMeta");
const agentFinalScore = document.querySelector("#agentFinalScore");
const agentProgressPanel = document.querySelector("#agentProgressPanel");
const agentCards = document.querySelector("#agentCards");
const dataPanel = document.querySelector("#dataPanel");
const dataMeta = document.querySelector("#dataMeta");
const datasetSelect = document.querySelector("#datasetSelect");
const datasetSummary = document.querySelector("#datasetSummary");
const tableFilterBar = document.querySelector("#tableFilterBar");
const tableSearchInput = document.querySelector("#tableSearchInput");
const clearTableFilterBtn = document.querySelector("#clearTableFilterBtn");
const tableFilterInfo = document.querySelector("#tableFilterInfo");
const tableFilterToggleBtn = document.querySelector("#tableFilterToggleBtn");
const columnFilterPopover = document.querySelector("#columnFilterPopover");
const columnFilterTitle = document.querySelector("#columnFilterTitle");
const columnFilterCloseBtn = document.querySelector("#columnFilterCloseBtn");
const columnFilterOperator = document.querySelector("#columnFilterOperator");
const columnFilterValue = document.querySelector("#columnFilterValue");
const columnFilterQuickSearch = document.querySelector("#columnFilterQuickSearch");
const columnFilterValues = document.querySelector("#columnFilterValues");
const columnFilterClearBtn = document.querySelector("#columnFilterClearBtn");
const columnFilterApplyBtn = document.querySelector("#columnFilterApplyBtn");
const dataTable = document.querySelector("#dataTable");
const tableViewBtn = document.querySelector("#tableViewBtn");
const chartViewBtn = document.querySelector("#chartViewBtn");
const chartMetricSelect = document.querySelector("#chartMetricSelect");
const chartSecondaryMetricSelect = document.querySelector("#chartSecondaryMetricSelect");
const chartPanel = document.querySelector("#chartPanel");
const dataChart = document.querySelector("#dataChart");
const chartNote = document.querySelector("#chartNote");
const lineRangeControls = document.querySelector("#lineRangeControls");
const lineWindowSlider = document.querySelector("#lineWindowSlider");
const lineWindowSelection = document.querySelector("#lineWindowSelection");
const lineWindowLeft = document.querySelector("#lineWindowLeft");
const lineWindowRight = document.querySelector("#lineWindowRight");
const lineRangeText = document.querySelector("#lineRangeText");
const prevPageBtn = document.querySelector("#prevPageBtn");
const nextPageBtn = document.querySelector("#nextPageBtn");
const pageInfo = document.querySelector("#pageInfo");

let selected = null;
let searchTimer = null;
let loadedDatasets = [];
let activeDataset = null;
let currentPage = 1;
let syncToken = 0;
let selectedHasDailyData = false;
let viewMode = "table";
let lineWindow = { start: 0, end: 0, total: 0 };
let lineDrag = null;
let tableFilterEnabled = false;
let tableFilters = { keyword: "", columns: {} };
let openFilterColumn = null;
let lineHoverIndex = -1;
let lineHitPoints = [];
let linePlotArea = null;
let pieSlices = [];
let hoveredPieIndex = -1;
const pageSize = 50;
let analysisModuleAvailable = false;
const ANALYSIS_MODULE_MESSAGE = "下游分析已拆分为外部 ValueScope，当前 DataHub 只保留数据资产、供给记录和历史报告读取。";
const defaultAnalysisFrameworks = [
  { key: "value_speculation", label: "价值投机" },
  { key: "value_quality", label: "质量成长价值" },
  { key: "value_dividend", label: "低估红利价值" },
  { key: "oversold_rebound", label: "超跌反弹" },
];
let analysisFrameworks = defaultAnalysisFrameworks;
let currentSession = null;

initializeTheme();
initializeSession();
loadAnalysisFrameworks();
loadInitialStockList();
initializeAnalysisModuleState();

function initializeAnalysisModuleState() {
  if (multiAgentBtn) {
    multiAgentBtn.disabled = !analysisModuleAvailable || !selected;
    multiAgentBtn.textContent = analysisModuleAvailable ? "多Agent分析" : "下游分析已外置";
    multiAgentBtn.title = analysisModuleAvailable ? "" : ANALYSIS_MODULE_MESSAGE;
  }
  if (analyzeBtn) {
    analyzeBtn.disabled = true;
    analyzeBtn.hidden = true;
  }
}

function initializeTheme() {
  let savedTheme = "light";
  try {
    savedTheme = localStorage.getItem("stockTheme") || "light";
  } catch {}
  applyTheme(savedTheme === "dark" ? "dark" : "light");
}

function applyTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.classList.toggle("theme-dark", isDark);
  if (themeToggleBtn) {
    themeToggleBtn.textContent = isDark ? "浅色模式" : "深色模式";
    themeToggleBtn.setAttribute("aria-pressed", String(isDark));
  }
  if (viewMode === "chart" && activeDataset) renderChart();
}

themeToggleBtn?.addEventListener("click", () => {
  const nextTheme = document.documentElement.classList.contains("theme-dark") ? "light" : "dark";
  try {
    localStorage.setItem("stockTheme", nextTheme);
  } catch {}
  applyTheme(nextTheme);
});

function chartPalette() {
  const styles = getComputedStyle(document.documentElement);
  return {
    text: styles.getPropertyValue("--chart-text").trim() || "#17202a",
    muted: styles.getPropertyValue("--chart-muted").trim() || "#667085",
    axis: styles.getPropertyValue("--chart-axis").trim() || "#d0d5dd",
    grid: styles.getPropertyValue("--chart-grid").trim() || "#eef1f5",
    primary: styles.getPropertyValue("--chart-primary").trim() || "#2f80ed",
    tooltip: styles.getPropertyValue("--chart-tooltip").trim() || "rgba(23, 32, 42, 0.9)",
    tooltipText: styles.getPropertyValue("--chart-tooltip-text").trim() || "#ffffff",
    panel: styles.getPropertyValue("--chart-panel").trim() || "#ffffff",
    candleUp: styles.getPropertyValue("--chart-up").trim() || "#eb5757",
    candleDown: styles.getPropertyValue("--chart-down").trim() || "#27ae60",
  };
}

async function readApiPayload(response, fallbackMessage) {
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(formatNonJsonApiError(text, fallbackMessage, response.status));
    }
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || payload.message || text || fallbackMessage);
  }
  return payload;
}

function approveDataFetch(message) {
  return window.confirm(`${message}\n\n该操作会访问外部数据源或消耗 API/模型额度。确认执行？`);
}

function formatNonJsonApiError(text, fallbackMessage, status) {
  const raw = String(text || "").trim();
  if (/<!doctype html|<html[\s>]/i.test(raw)) {
    if (status === 404 || /Error code:\s*404/i.test(raw)) {
      return `${fallbackMessage}：本地后端没有加载这个接口，请重启 Web 服务后刷新页面。`;
    }
    return `${fallbackMessage}：后端返回了 HTML 错误页，请检查服务是否仍在登录态并已重启到最新版本。`;
  }
  return raw || fallbackMessage;
}

input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => search(input.value), 180);
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
});

saveUserApiKeysBtn?.addEventListener("click", saveUserApiKeys);
deleteUserApiKeysBtn?.addEventListener("click", deleteUserApiKeys);

updateDataBtn.addEventListener("click", async () => {
  await syncSelectedData({ force: true });
});

updateThsMarketBtn?.addEventListener("click", async () => {
  await syncSelectedThsMarketData();
});

analysisTypeSelect.addEventListener("change", () => {
  refreshAnalysisResults();
  refreshAgentRuns();
});

analyzeBtn.addEventListener("click", async () => {
  if (!selected) return;
  const framework = selectedAnalysisFramework();
  if (!approveDataFetch(`生成 ${selected.name}（${selected.ts_code}）的${framework.label}分析`)) return;
  analyzeBtn.disabled = true;
  readAnalysisBtn.disabled = true;
  scorePanel.hidden = true;
  scorePanel.innerHTML = "";
  output.textContent = `正在准备 ${selected.name}（${selected.ts_code}）的${historyScopeText()}数据并生成${framework.label}分析，请稍等...`;
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, years: "all", analysis_type: framework.key, approved: true }),
    });
    const payload = await readApiPayload(response, "分析失败");
    if (!payload.answer) throw new Error("分析未返回正文，已停止展示结果。");
    renderScores(payload.rating_hint, payload.scores || {}, payload.analysis_type);
    const rows = Object.entries(payload.dataset_rows || {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `${key}: ${value}`)
      .join("\n");
    const errors = payload.fetch_errors?.length ? `\n\n未成功接口：${payload.fetch_errors.length} 个` : "";
    const risks = (payload.risk_flags || []).map((item) => `- [${item.level}] ${item.title}: ${item.message}`).join("\n");
    output.textContent = `${payload.answer}\n\n---\n分析类型：${payload.analysis_label || framework.label}\n分析结果：已保存\n\n规则风险提示：\n${risks || "暂无明显规则风险"}\n\n数据集行数：\n${rows}${errors}`;
    await refreshAnalysisResults();
  } catch (error) {
    output.textContent = `出错了：${error.message}`;
  } finally {
    analyzeBtn.disabled = false;
    syncReadAnalysisButtonState();
  }
});

readAnalysisBtn.addEventListener("click", async () => {
  if (!selected) return;
  const framework = selectedAnalysisFramework();
  readAnalysisBtn.disabled = true;
  scorePanel.hidden = true;
  scorePanel.innerHTML = "";
  output.textContent = `正在读取 ${selected.name}（${selected.ts_code}）的${framework.label}历史分析...`;
  try {
    const response = await fetch("/api/read-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, analysis_type: framework.key, snapshot_name: analysisHistorySelect.value }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "读取失败");
    const history = (payload.items || [])
      .map((item) => `- ${item.location === "current" ? "当前" : `快照 ${item.snapshot_name}`}`)
      .join("\n");
    output.textContent = `${payload.answer}\n\n---\n分析类型：${payload.analysis_label || framework.label}\n分析结果：已读取\n\n可读取历史：\n${history || "暂无其他历史分析"}`;
    renderAnalysisHistoryOptions(payload.items || []);
  } catch (error) {
    output.textContent = `读取分析失败：${error.message}`;
  } finally {
    syncReadAnalysisButtonState();
  }
});

multiAgentBtn.addEventListener("click", async () => {
  if (!selected) return;
  if (!analysisModuleAvailable) {
    output.textContent = ANALYSIS_MODULE_MESSAGE;
    multiAgentBtn.disabled = true;
    return;
  }
  const token = ++syncToken;
  const framework = selectedAnalysisFramework();
  if (!approveDataFetch(`创建 ${selected.name}（${selected.ts_code}）的${framework.label}多 Agent 分析任务`)) return;
  multiAgentBtn.disabled = true;
  output.textContent = `正在创建 ${selected.name}（${selected.ts_code}）的${framework.label}多 Agent 后台任务...`;
  try {
    const response = await fetch("/api/multi-agent-analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, analysis_type: framework.key, years: "all", allow_dynamic_fetch: true, async: true, max_parallel_agents: 8, approved: true }),
    });
    const job = await readApiPayload(response, "多 Agent 分析任务创建失败");
    await pollMultiAgentJob(job.job_id, framework, token);
  } catch (error) {
    if (token === syncToken) output.textContent = error.message || String(error);
  } finally {
    if (token === syncToken) {
      multiAgentBtn.disabled = false;
      syncReadAgentRunButtonState();
    }
  }
});

async function pollMultiAgentJob(jobId, framework, token) {
  let lastPayload = null;
  while (token === syncToken) {
    const response = await fetch("/api/multi-agent-job", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    const payload = await readApiPayload(response, "读取分析进度失败");
    lastPayload = payload;
    renderAgentProgress(payload, framework);
    output.textContent = formatMultiAgentJobProgress(payload, framework);
    if (payload.status === "succeeded") break;
    if (payload.status === "failed") throw new Error(formatMultiAgentJobProgress(payload, framework));
    await sleep(1000);
  }
  if (!lastPayload || token !== syncToken) return;
  const payload = lastPayload.result;
  if (!payload?.ok) throw new Error(lastPayload.error || payload?.error || "多 Agent 分析失败");
  if (token !== syncToken) return;
  const requests = payload.data_requests?.approved_requests || [];
  const fetched = payload.fetch_result?.fetch_results || [];
  const failed = payload.fetch_result?.fetch_errors || [];
  renderMultiAgentResult(payload, [
    ["动态数据请求", `${requests.length} 个`],
    ["Agent补充请求", `${(payload.agent_data_requests || []).length} 个`],
    ["补抓成功", `${fetched.length} 个`],
    ["补抓失败/权限缺口", `${failed.length} 个`],
  ]);
  await refreshAgentRuns();
}

readAgentRunBtn.addEventListener("click", async () => {
  if (!selected || !agentRunSelect.value) return;
  readAgentRunBtn.disabled = true;
  output.textContent = `正在读取历史分析记录 ${agentRunSelect.value}...`;
  try {
    const response = await fetch("/api/read-agent-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, run_id: agentRunSelect.value }),
    });
    const payload = await readApiPayload(response, "读取失败");
    renderMultiAgentResult(payload, [
      ["Agent补充请求", `${(payload.agent_data_requests || []).length} 个`],
    ]);
  } catch (error) {
    output.textContent = error.message || String(error);
  } finally {
    syncReadAgentRunButtonState();
  }
});

loadDataBtn.addEventListener("click", async () => {
  if (!selected) return;
  loadDataBtn.disabled = true;
  dataPanel.hidden = false;
  dataMeta.textContent = `正在读取 ${selected.name}（${selected.ts_code}）的本地数据...`;
  datasetSummary.textContent = "";
  dataTable.innerHTML = "";
  try {
    const response = await fetch("/api/local-stock-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, pages: "all" }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "读取失败");
    loadedDatasets = payload.datasets || [];
    selectedHasDailyData = datasetsHaveDailyRows(loadedDatasets, payload.metadata?.dataset_rows || {});
    syncMinuteButtonState();
    renderStockMetricsFromDatasets(loadedDatasets);
    renderDatasetOptions();
    dataMeta.textContent = `资料包：已加载`;
    if (loadedDatasets.length) {
      activeDataset = loadedDatasets[0];
      currentPage = 1;
      datasetSelect.value = activeDataset.key;
      viewMode = "table";
      resetTableFilters();
      prepareChartMetric();
      renderActiveDataset();
    }
  } catch (error) {
    dataMeta.textContent = `读取失败：${error.message}`;
  } finally {
    loadDataBtn.disabled = false;
  }
});

datasetSelect.addEventListener("change", () => {
  activeDataset = loadedDatasets.find((item) => item.key === datasetSelect.value) || null;
  currentPage = 1;
  resetTableFilters();
  prepareChartMetric();
  renderActiveDataset();
});

tableViewBtn.addEventListener("click", () => {
  viewMode = "table";
  renderActiveDataset();
});

chartViewBtn.addEventListener("click", () => {
  viewMode = "chart";
  prepareChartMetric();
  renderActiveDataset();
});

chartMetricSelect.addEventListener("change", () => {
  resetLineWindow();
  if (viewMode === "chart") renderActiveDataset();
});
chartSecondaryMetricSelect.addEventListener("change", () => {
  if (viewMode === "chart") renderActiveDataset();
});

tableFilterToggleBtn.addEventListener("click", toggleTableFilters);
tableSearchInput.addEventListener("input", applyTableKeywordFilter);
clearTableFilterBtn.addEventListener("click", () => {
  resetTableFilters();
  renderActiveDataset();
});
dataTable.addEventListener("click", (event) => {
  const button = event.target.closest(".column-filter-btn");
  if (!button) return;
  event.stopPropagation();
  openColumnFilterPopover(button.dataset.column, button);
});
columnFilterCloseBtn.addEventListener("click", closeColumnFilterPopover);
columnFilterQuickSearch.addEventListener("input", renderColumnFilterValues);
columnFilterOperator.addEventListener("change", () => {
  columnFilterValue.disabled = ["empty", "not_empty"].includes(columnFilterOperator.value);
});
columnFilterClearBtn.addEventListener("click", clearOpenColumnFilter);
columnFilterApplyBtn.addEventListener("click", applyOpenColumnFilter);
document.addEventListener("click", (event) => {
  if (columnFilterPopover.hidden) return;
  if (columnFilterPopover.contains(event.target) || event.target.closest(".column-filter-btn")) return;
  closeColumnFilterPopover();
});

lineWindowLeft.addEventListener("pointerdown", (event) => beginLineWindowDrag(event, "left"));
lineWindowRight.addEventListener("pointerdown", (event) => beginLineWindowDrag(event, "right"));
lineWindowSelection.addEventListener("pointerdown", (event) => beginLineWindowDrag(event, "move"));
lineWindowSlider.addEventListener("pointerdown", (event) => {
  if (event.target !== lineWindowSlider && !event.target.classList.contains("line-window-track")) return;
  jumpLineWindowTo(event);
});
window.addEventListener("pointermove", moveLineWindowDrag);
window.addEventListener("pointerup", endLineWindowDrag);
window.addEventListener("pointercancel", endLineWindowDrag);

dataChart.addEventListener("mousemove", (event) => {
  if (viewMode !== "chart") return;
  const kind = chartKind(activeDataset || {});
  if (kind === "pie") {
    const nextIndex = hitTestPie(event);
    dataChart.style.cursor = nextIndex === -1 ? "default" : "pointer";
    if (nextIndex !== hoveredPieIndex) {
      hoveredPieIndex = nextIndex;
      renderActiveDataset();
    }
    return;
  }
  if (kind === "line") {
    const nextIndex = hitTestLine(event);
    dataChart.style.cursor = nextIndex === -1 ? "default" : "crosshair";
    if (nextIndex !== lineHoverIndex) {
      lineHoverIndex = nextIndex;
      renderActiveDataset();
    }
    return;
  }
  dataChart.style.cursor = "default";
});

dataChart.addEventListener("mouseleave", () => {
  dataChart.style.cursor = "default";
  if (hoveredPieIndex !== -1 || lineHoverIndex !== -1) {
    hoveredPieIndex = -1;
    lineHoverIndex = -1;
    renderActiveDataset();
  }
});

prevPageBtn.addEventListener("click", () => {
  if (currentPage > 1) {
    currentPage -= 1;
    renderActiveDataset();
  }
});

nextPageBtn.addEventListener("click", () => {
  if (!activeDataset) return;
  const totalPages = Math.max(1, Math.ceil(filteredTableRecords(activeDataset.records || [], activeDataset.columns || []).length / pageSize));
  if (currentPage < totalPages) {
    currentPage += 1;
    renderActiveDataset();
  }
});

async function search(query) {
  const q = query.trim();
  results.innerHTML = "";
  if (!q) {
    statusEl.textContent = "输入关键词开始检索";
    return;
  }
  statusEl.textContent = "检索中...";
  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const payload = await response.json();
    renderResults(payload.items || []);
  } catch (error) {
    statusEl.textContent = `检索失败：${error.message}`;
  }
}

async function loadInitialStockList() {
  if (input.value.trim()) return;
  statusEl.textContent = "正在加载股票列表...";
  try {
    const response = await fetch("/api/search?q=000");
    const payload = await response.json();
    renderResults(payload.items || []);
    if (!input.value.trim()) statusEl.textContent = payload.items?.length ? "默认展示部分 A 股，输入关键词可筛选" : "输入关键词开始检索";
  } catch (error) {
    statusEl.textContent = `股票列表加载失败：${error.message}`;
  }
}

async function initializeSession() {
  try {
    const response = await fetch("/api/session");
    const payload = await readApiPayload(response, "读取会话失败");
    currentSession = payload;
    const isAdminRole = ["admin", "admin_readonly"].includes(payload.role);
    if (sidebarFooter) {
      sidebarFooter.classList.toggle("is-admin", isAdminRole);
      sidebarFooter.classList.toggle("is-user", !isAdminRole);
    }
    if (adminPanelLink) {
      adminPanelLink.hidden = !isAdminRole;
    }
    renderApiKeyPanel(payload);
  } catch {}
}

function renderApiKeyPanel(session) {
  if (!apiKeyPanel) return;
  const role = session?.role || "";
  const isUser = role === "user";
  apiKeyPanel.hidden = !isUser;
  if (!isUser) return;
  const keys = session.api_keys || {};
  if (accountTierText) accountTierText.textContent = "普通用户";
  for (const input of [userTushareApiInput, userDeepSeekApiInput]) {
    if (!input) continue;
    input.disabled = false;
    input.value = "";
    input.placeholder = "输入后加密保存";
  }
  if (saveUserApiKeysBtn) saveUserApiKeysBtn.disabled = false;
  if (deleteUserApiKeysBtn) deleteUserApiKeysBtn.disabled = !keys.tushare?.configured && !keys.deepseek?.configured;
  if (apiKeyStatus) {
    apiKeyStatus.textContent = `Tushare 兼容：${keys.tushare?.configured ? "已保存" : "未保存"}；DeepSeek：${keys.deepseek?.configured ? "已保存" : "未保存"}。`;
  }
}

async function saveUserApiKeys() {
  if (!userTushareApiInput || !userDeepSeekApiInput) return;
  saveUserApiKeysBtn.disabled = true;
  try {
    const response = await fetch("/api/user/api-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tushare_api: userTushareApiInput.value, deepseek_api: userDeepSeekApiInput.value }),
    });
    const payload = await readApiPayload(response, "保存 API key 失败");
    currentSession = { ...currentSession, ...payload };
    renderApiKeyPanel(currentSession);
  } catch (error) {
    if (apiKeyStatus) apiKeyStatus.textContent = `保存失败：${formatApiKeyError(error.message)}`;
  } finally {
    saveUserApiKeysBtn.disabled = false;
  }
}

async function deleteUserApiKeys() {
  deleteUserApiKeysBtn.disabled = true;
  try {
    const response = await fetch("/api/user/api-keys/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys: ["tushare", "deepseek"] }),
    });
    const payload = await readApiPayload(response, "删除 API key 失败");
    currentSession = { ...currentSession, ...payload };
    renderApiKeyPanel(currentSession);
    if (apiKeyStatus) apiKeyStatus.textContent = "API key 已删除，未保留删除记录。";
  } catch (error) {
    if (apiKeyStatus) apiKeyStatus.textContent = `删除失败：${error.message}`;
  } finally {
    deleteUserApiKeysBtn.disabled = false;
  }
}

function formatApiKeyError(message) {
  const raw = String(message || "");
  const parts = [];
  if (/Tushare key 验证失败|stock_basic|token不对|tushare/i.test(raw)) {
    parts.push("Tushare 兼容 token 验证失败，请检查 token 是否正确。");
  }
  if (/DeepSeek key 验证失败|Authentication Fails|authentication_error|api key|invalid/i.test(raw)) {
    parts.push("DeepSeek API 验证失败，请检查 key 是否有效。");
  }
  if (parts.length) return [...new Set(parts)].join(" ");
  return raw.length > 140 ? `${raw.slice(0, 140)}...` : raw;
}

function renderResults(items) {
  statusEl.textContent = items.length ? `找到 ${items.length} 个结果` : "没有匹配结果";
  results.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.className = `result ${selected?.ts_code === item.ts_code ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <div>
        <div class="name">${escapeHtml(item.name || "")}</div>
        <div class="code">${escapeHtml(item.ts_code || "")}</div>
        <div class="tags">${escapeHtml([item.industry, item.area, item.market].filter(Boolean).join(" · "))}</div>
      </div>
      <span class="status-pill">${item.list_status === "L" ? "上市" : item.list_status || "-"}</span>
    `;
    button.addEventListener("click", () => selectStock(item));
    results.appendChild(button);
  }
}

function selectStock(item) {
  selected = item;
  selectedHasDailyData = false;
  selectedTitle.textContent = `${item.name}（${item.ts_code}）`;
  selectedMeta.textContent = [item.industry, item.area, item.market, item.list_date && `上市日 ${item.list_date}`].filter(Boolean).join(" · ");
  resetStockMetrics();
  resetAgentDashboard();
  analyzeBtn.disabled = true;
  multiAgentBtn.disabled = !analysisModuleAvailable;
  updateDataBtn.disabled = false;
  syncMinuteButtonState();
  loadDataBtn.disabled = false;
  analysisHistorySelect.disabled = false;
  scorePanel.hidden = true;
  dataPanel.hidden = true;
  loadedDatasets = [];
  activeDataset = null;
  resetTableFilters();
  output.textContent = "正在读取本地更新状态；当前 DataHub 只保留数据读取、供给记录和历史报告读取。";
  renderAnalysisHistoryOptions([]);
  renderAgentRunOptions([]);
  for (const button of results.querySelectorAll(".result")) {
    button.classList.toggle("active", button.textContent.includes(item.ts_code));
  }
  loadStockSnapshotMetrics(item.ts_code);
  checkSelectedStatus();
  refreshAnalysisResults();
  refreshAgentRuns();
}

async function syncSelectedData(options = {}) {
  if (!selected) return;
  const force = options.force !== false;
  if (!approveDataFetch(`更新 ${selected.name}（${selected.ts_code}）的股票资料包（${historyScopeText()}）`)) return;
  const token = ++syncToken;
  updateDataBtn.disabled = true;
  if (updateThsMarketBtn) updateThsMarketBtn.disabled = true;
  loadDataBtn.disabled = true;
  multiAgentBtn.disabled = true;
  readAnalysisBtn.disabled = true;
  readAgentRunBtn.disabled = true;
  output.textContent = `正在全量更新 ${selected.name}（${selected.ts_code}）的股票资料包（${historyScopeText()}），请稍等...`;
  try {
    const response = await fetch("/api/sync-stock-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, years: "all", force, approved: true }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "更新失败");
    if (token !== syncToken) return;
    loadedDatasets = payload.datasets || [];
    selectedHasDailyData = datasetsHaveDailyRows(loadedDatasets, payload.metadata?.dataset_rows || {});
    syncMinuteButtonState();
    renderStockMetricsFromDatasets(loadedDatasets);
    const meta = payload.metadata || {};
    const snapshotCount = meta.snapshots?.length || 0;
    const range = meta.date_range ? `${formatDateLabel(meta.date_range.start_date)} 至 ${formatDateLabel(meta.date_range.end_date)}` : "未知";
    const dailySummary = buildDailyCoverageSummary(payload.datasets || [], meta.dataset_rows || {});
    const cacheLine = payload.cache_hit
      ? `已复用共享缓存，缓存年龄：${formatDurationText(payload.cache_age_seconds)}。`
      : "本地数据已更新。";
    output.textContent = `${cacheLine}\n数据源：默认股票资料源\n采集范围：${range}\n每日行情覆盖：${dailySummary}\n资料包：已保存\n更新时间：${formatUpdateTime(meta.updated_at)}\n历史快照：${snapshotCount} 个\n\n现在可以点击“读取数据”查看中文表格，或继续补抓分钟行情。`;
    await refreshAnalysisResults();
  } catch (error) {
    if (token === syncToken) {
      output.textContent = `更新本地数据失败：${error.message}\n\n如果本地之前已有数据，可以直接点击“读取数据”查看。`;
    }
  } finally {
    if (token === syncToken) {
      updateDataBtn.disabled = false;
      syncMinuteButtonState();
      loadDataBtn.disabled = false;
      multiAgentBtn.disabled = !analysisModuleAvailable;
      analysisHistorySelect.disabled = false;
      syncReadAnalysisButtonState();
      syncReadAgentRunButtonState();
    }
  }
}

async function syncSelectedThsMarketData() {
  if (!selected) return;
  if (!approveDataFetch(`补抓 ${selected.name}（${selected.ts_code}）的分钟行情数据`)) return;
  const token = ++syncToken;
  updateDataBtn.disabled = true;
  if (updateThsMarketBtn) updateThsMarketBtn.disabled = true;
  loadDataBtn.disabled = true;
  multiAgentBtn.disabled = true;
  readAnalysisBtn.disabled = true;
  readAgentRunBtn.disabled = true;
  output.textContent = `正在补抓 ${selected.name}（${selected.ts_code}）的分钟行情数据，请稍等...`;
  try {
    const response = await fetch("/api/sync-ths-market-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, source: "pytdx_history", approved: true }),
    });
    const payload = await readApiPayload(response, "分钟行情更新失败");
    if (token !== syncToken) return;
    loadedDatasets = payload.datasets || loadedDatasets || [];
    selectedHasDailyData = datasetsHaveDailyRows(loadedDatasets, payload.metadata?.dataset_rows || {});
    syncMinuteButtonState();
    renderStockMetricsFromDatasets(loadedDatasets);
    const result = payload.market_result?.results?.[0] || {};
    const localText = result.local_merged ? "MongoDB 引用已写入资料包。" : "本地资料包尚不存在，分钟数据已写入 MongoDB。";
    const dateRange = result.date_range?.start && result.date_range?.end ? `${result.date_range.start} - ${result.date_range.end}` : result.trade_date || "-";
    const pageText = result.requested_pages === "all"
      ? `全部可取页；实际 ${result.pages_fetched ?? "-"} 页 × ${result.page_size ?? "-"} 根/页${result.source_exhausted ? "；已到数据源尽头" : ""}`
      : result.requested_pages && result.page_size
        ? `${result.requested_pages} 页 × ${result.page_size} 根/页`
        : result.requested_pages ?? "-";
    const scopeText = result.source === "pytdx_history"
      ? `历史范围：${dateRange}；本次成功交易日：${result.succeeded_days ?? 0}；已跳过已有交易日：${result.skipped_days ?? 0}；失败交易日：${result.failed_days ?? 0}`
      : result.history_supported === false
        ? "当前接口仅更新最新交易日，不包含历史分钟分时。"
        : `历史范围：${dateRange}；覆盖交易日：${result.succeeded_days ?? 0}；请求窗口：${pageText}`;
    const estimateText = result.amount_estimated || result.ohlc_estimated ? "\n说明：该历史源只返回分时价格和成交量；OHLC 和成交额为估算字段。" : "";
    output.textContent = `分钟行情更新完成。\n数据源：${result.source || payload.market_result?.source || "-"}\n数据集：${result.dataset || "-"}\n股票：${result.ts_code || selected.ts_code} ${result.name || ""}\n最新交易日：${result.trade_date || "-"}\n${scopeText}\n本次分钟行数：${result.rows ?? 0}；MongoDB 累计：${result.stored_rows ?? result.rows ?? 0}\n新增：${result.inserted ?? 0}；更新：${result.updated ?? 0}${estimateText}\n${localText}\n\n现在可以点击“读取数据”查看最近的分钟行情，完整历史保存在 MongoDB。`;
  } catch (error) {
    if (token === syncToken) {
      output.textContent = `分钟行情更新失败：${error.message}`;
    }
  } finally {
    if (token === syncToken) {
      updateDataBtn.disabled = false;
      syncMinuteButtonState();
      loadDataBtn.disabled = false;
      multiAgentBtn.disabled = !analysisModuleAvailable;
      analysisHistorySelect.disabled = false;
      syncReadAnalysisButtonState();
      syncReadAgentRunButtonState();
    }
  }
}

async function refreshAnalysisResults() {
  if (!selected) {
    renderAnalysisHistoryOptions([]);
    return;
  }
  const framework = selectedAnalysisFramework();
  analysisHistorySelect.disabled = true;
  readAnalysisBtn.disabled = true;
  try {
    const response = await fetch("/api/analysis-results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, analysis_type: framework.key }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "读取历史分析失败");
    renderAnalysisHistoryOptions(payload.items || []);
  } catch {
    renderAnalysisHistoryOptions([]);
  } finally {
    analysisHistorySelect.disabled = false;
  }
}

function renderAnalysisHistoryOptions(items) {
  if (!items.length) {
    analysisHistorySelect.innerHTML = `<option value="">暂无历史分析</option>`;
    readAnalysisBtn.disabled = true;
    return;
  }
  analysisHistorySelect.innerHTML = items
    .map((item) => {
      const value = item.location === "current" ? "" : item.snapshot_name;
      const label = item.location === "current"
        ? `当前：${formatUpdateTime(item.updated_at)}`
        : `快照：${formatUpdateTime(item.updated_at)}`;
      return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
    })
    .join("");
  syncReadAnalysisButtonState();
}

function syncReadAnalysisButtonState() {
  const hasHistory = analysisHistorySelect.options.length > 0 && analysisHistorySelect.options[0].textContent !== "暂无历史分析";
  readAnalysisBtn.disabled = !selected || !hasHistory;
}

async function refreshAgentRuns() {
  if (!selected) {
    renderAgentRunOptions([]);
    return;
  }
  const framework = selectedAnalysisFramework();
  agentRunSelect.disabled = true;
  readAgentRunBtn.disabled = true;
  try {
    const response = await fetch("/api/agent-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code, analysis_type: framework.key }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "读取分析历史失败");
    renderAgentRunOptions(payload.items || []);
  } catch {
    renderAgentRunOptions([]);
  } finally {
    agentRunSelect.disabled = false;
  }
}

function renderAgentRunOptions(items) {
  if (!items.length) {
    agentRunSelect.innerHTML = `<option value="">暂无分析历史</option>`;
    readAgentRunBtn.disabled = true;
    return;
  }
  agentRunSelect.innerHTML = items
    .map((item) => `<option value="${escapeHtml(item.run_id)}">${escapeHtml(formatUpdateTime(item.created_at) || item.run_id)}</option>`)
    .join("");
  syncReadAgentRunButtonState();
}

function syncReadAgentRunButtonState() {
  const hasHistory = agentRunSelect.options.length > 0 && agentRunSelect.options[0].textContent !== "暂无分析历史";
  readAgentRunBtn.disabled = !selected || !hasHistory;
}

function formatMultiAgentJobProgress(job, framework) {
  const statusText = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败",
  }[job.status] || job.status || "未知";
  const lines = [
    `正在运行 ${selected?.name || ""}（${selected?.ts_code || ""}）的${framework.label}多 Agent 分析`,
    `任务ID：${job.job_id}`,
    `状态：${statusText}`,
    "",
    "## 执行日志",
  ];
  const progress = job.progress || [];
  for (const item of progress.slice(-30)) {
    const time = formatProgressTime(item.time);
    const stage = item.stage ? ` / ${item.stage}` : "";
    lines.push(`- ${time}${stage}：${formatRuntimeError(item.message || "")}`);
  }
  if (job.error) {
    lines.push("", "## 报错", formatRuntimeError(job.error));
  }
  return lines.join("\n");
}

function formatAgentConversation(messages) {
  if (!messages.length) return "## 多 Agent 对话摘要\n暂无对话摘要。";
  const lines = ["## 多 Agent 对话摘要"];
  for (const item of messages) {
    const role = item.role ? ` / ${item.role}` : "";
    lines.push(`[${item.speaker}${role}] ${item.message}`);
  }
  return lines.join("\n");
}

function renderMultiAgentResult(payload, metaItems = []) {
  const conversation = payload.agent_conversation || [];
  const enrichedMetaItems = [...metaItems, ...learningMetaItems(payload.learning_context)];
  renderAgentDashboard(payload);
  output.innerHTML = `
    <article class="agent-report">
      <header class="report-hero">
        <div>
          <div class="report-kicker">${escapeHtml(payload.analysis_label || "多 Agent 分析")}</div>
          <h3>${escapeHtml(payload.ts_code || payload.manifest?.ts_code || "多 Agent 分析报告")}</h3>
        </div>
        <div class="report-rating ${ratingTone(payload.rating_hint || "")}">
          <strong>${escapeHtml(payload.rating_hint || "-")}</strong>
          <span>置信度 ${escapeHtml(payload.confidence ?? "-")}</span>
        </div>
      </header>
      ${renderMetaGrid(enrichedMetaItems)}
      ${renderConversationTimeline(conversation)}
      ${renderMarkdownReport(payload.answer || "")}
    </article>
  `;
}

async function loadStockSnapshotMetrics(tsCode) {
  try {
    const response = await fetch("/api/local-stock-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: tsCode }),
    });
    const payload = await response.json();
    if (!payload.ok || selected?.ts_code !== tsCode) return;
    loadedDatasets = payload.datasets || loadedDatasets;
    renderStockMetricsFromDatasets(payload.datasets || []);
  } catch {
    resetStockMetrics();
  }
}

function resetStockMetrics() {
  for (const element of [metricLatestPrice, metricPe, metricPb, metricDividend]) {
    if (element) element.textContent = "-";
  }
}

function renderStockMetricsFromDatasets(datasets) {
  const dailyBasic = latestRecord(findDataset(datasets, "daily_basic")?.records || [], "trade_date");
  const daily = latestRecord(findDataset(datasets, "daily")?.records || [], "trade_date");
  const latestIncome = latestRecord(findDataset(datasets, "income")?.records || [], "end_date");
  const latestBalance = latestRecord(findDataset(datasets, "balancesheet")?.records || [], "end_date");
  const valuationRecords = latestValuationRecords(datasets);
  const latestPrice = firstFinite(valueByAliases(dailyBasic, METRIC_ALIASES.close), valueByAliases(daily, METRIC_ALIASES.close));
  const marketCap = firstFinite(...valuationRecords.map((row) => valueByAliases(row, METRIC_ALIASES.marketCap)));
  const pe = firstFinite(
    ...valuationRecords.map((row) => valueByAliases(row, METRIC_ALIASES.pe)),
    ratioFromWanMarketCap(marketCap, valueByAliases(latestIncome, METRIC_ALIASES.profit)),
  );
  const pb = firstFinite(
    ...valuationRecords.map((row) => valueByAliases(row, METRIC_ALIASES.pb)),
    ratioFromWanMarketCap(marketCap, valueByAliases(latestBalance, METRIC_ALIASES.equity)),
  );
  const dividend = firstFinite(...valuationRecords.map((row) => valueByAliases(row, METRIC_ALIASES.dividend)));
  if (metricLatestPrice) metricLatestPrice.textContent = formatMetric(latestPrice, 2);
  if (metricPe) metricPe.textContent = formatMetric(pe, 2);
  if (metricPb) metricPb.textContent = formatMetric(pb, 2);
  if (metricDividend) metricDividend.textContent = Number.isFinite(dividend) ? `${formatMetric(dividend, 2)}%` : "-";
}

const METRIC_ALIASES = {
  close: ["close", "latest_price", "price", "收盘价", "最新价", "价格"],
  pe: ["pe_ttm", "pe", "市盈率ttm", "滚动市盈率", "市盈率", "动态市盈率"],
  pb: ["pb", "市净率"],
  dividend: ["dv_ttm", "dv_ratio", "dividend_yield", "股息率", "滚动股息率"],
  marketCap: ["total_mv", "market_cap", "total_market_value", "总市值", "市值"],
  profit: ["n_income_attr_p", "n_income", "net_profit", "parent_netprofit", "归母净利润", "净利润"],
  equity: ["total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "total_equity", "净资产", "股东权益合计", "所有者权益合计"],
};

function latestValuationRecords(datasets) {
  return ["daily_basic", "valuation", "daily", "fina_indicator", "stock_basic"]
    .map((key) => latestRecord(findDataset(datasets, key)?.records || [], key === "daily_basic" || key === "daily" ? "trade_date" : "end_date"))
    .filter(Boolean);
}

function valueByAliases(row, aliases) {
  if (!row) return NaN;
  for (const key of aliases) {
    const value = toNumber(row[key]);
    if (Number.isFinite(value)) return value;
  }
  const entries = Object.entries(row);
  for (const key of aliases) {
    const normalized = normalizeMetricKey(key);
    const match = entries.find(([name]) => normalizeMetricKey(name) === normalized);
    const value = toNumber(match?.[1]);
    if (Number.isFinite(value)) return value;
  }
  return NaN;
}

function normalizeMetricKey(value) {
  return String(value || "").toLowerCase().replace(/[\s_\-（）()]/g, "");
}

function ratioFromWanMarketCap(marketCapWan, denominatorYuan) {
  if (!Number.isFinite(marketCapWan) || !Number.isFinite(denominatorYuan) || denominatorYuan === 0) return NaN;
  return (marketCapWan * 10000) / denominatorYuan;
}

function findDataset(datasets, key) {
  return (datasets || []).find((item) => item.key === key);
}

function latestRecord(records, dateKey) {
  return [...(records || [])]
    .filter((row) => row && row[dateKey])
    .sort((a, b) => String(b[dateKey]).localeCompare(String(a[dateKey])))[0] || records?.[0] || null;
}

function buildDailyCoverageSummary(datasets, datasetRows = {}) {
  const daily = findDataset(datasets, "daily");
  const records = daily?.records || [];
  const dates = records
    .map((row) => String(row?.trade_date || ""))
    .filter((value) => /^\d{8}$/.test(value))
    .sort();
  const dailyRows = datasetRows.daily ?? records.length;
  const parts = [
    `日线 ${dailyRows} 行`,
    `每日指标 ${datasetRows.daily_basic ?? findDataset(datasets, "daily_basic")?.records?.length ?? 0} 行`,
    `资金流 ${datasetRows.moneyflow ?? findDataset(datasets, "moneyflow")?.records?.length ?? 0} 行`,
  ];
  if (dates.length) {
    parts.unshift(`${formatDateLabel(dates[0])} 至 ${formatDateLabel(dates[dates.length - 1])}`);
  }
  return parts.join("；");
}

function firstFinite(...values) {
  for (const value of values) {
    const number = toNumber(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function formatMetric(value, digits = 2) {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: value % 1 === 0 ? 0 : Math.min(2, digits) });
}

function resetAgentDashboard() {
  if (agentDashboard) agentDashboard.hidden = true;
  if (agentProgressPanel) {
    agentProgressPanel.hidden = true;
    agentProgressPanel.innerHTML = "";
  }
  if (agentCards) agentCards.innerHTML = "";
  if (agentFinalScore) agentFinalScore.textContent = "-";
  if (agentDashboardMeta) agentDashboardMeta.textContent = "运行完成后展示各 Agent 观点。";
}

function renderAgentProgress(job, framework) {
  if (!agentDashboard || !agentProgressPanel) return;
  agentDashboard.hidden = false;
  agentProgressPanel.hidden = false;
  const statusText = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败",
  }[job.status] || job.status || "未知";
  const progress = job.progress || [];
  const latest = progress[progress.length - 1]?.message || "等待任务进度...";
  const percent = job.status === "succeeded" ? 100 : job.status === "failed" ? 100 : Math.min(90, 12 + progress.length * 8);
  if (agentDashboardMeta) agentDashboardMeta.textContent = `${framework.label} · ${statusText}`;
  if (agentFinalScore) agentFinalScore.textContent = statusText;
  agentProgressPanel.innerHTML = `
    <div class="agent-progress-top">
      <strong>${escapeHtml(statusText)}</strong>
      <span>${escapeHtml(job.job_id || "")}</span>
    </div>
    <div class="agent-progress-track"><span style="width: ${percent}%"></span></div>
    <p>${escapeHtml(latest)}</p>
  `;
}

function renderAgentDashboard(payload) {
  if (!agentDashboard || !agentCards) return;
  const agentResults = normalizedAgentResults(payload);
  const trace = payload.confidence_trace || {};
  const debate = payload.debate || {};
  const finalRating = trace.final_rating || payload.rating_hint || debate.final_direction?.label || "-";
  const confidence = trace.final_confidence ?? payload.confidence ?? "-";
  agentDashboard.hidden = false;
  if (agentProgressPanel) agentProgressPanel.hidden = true;
  if (agentDashboardMeta) {
    const mode = payload.analysis_label || selectedAnalysisFramework().label;
    const count = agentResults.length ? `${agentResults.length} 个 Agent` : "暂无 Agent 明细";
    agentDashboardMeta.textContent = `${mode} · ${count} · 置信度 ${confidence}`;
  }
  if (agentFinalScore) agentFinalScore.innerHTML = `<strong>${escapeHtml(finalRating)}</strong><span>${escapeHtml(String(confidence))}</span>`;
  agentCards.innerHTML = agentResults.length
    ? agentResults.map(renderAgentResultCard).join("")
    : `<div class="agent-empty-card">当前报告没有返回 Agent 明细。</div>`;
}

function renderAgentResultCard(item) {
  const name = agentDisplayName(item.agent || item.agent_role || "agent");
  const rating = agentDisplayLabel(item);
  const confidence = item.system_confidence ?? item.confidence ?? "-";
  const opinionStrength = item.opinion_strength ?? item.confidence_components?.opinion_strength;
  const evidenceConfidence = item.evidence_confidence ?? item.confidence_components?.evidence_confidence;
  const findings = item.findings || item.key_findings || [];
  const summary = item.reasoning_summary || item.summary || firstFindingText(findings) || "暂无观点摘要。";
  const reason = firstFindingText(findings) || firstCounterText(item.counter_evidence) || "暂无明确原因。";
  const llmError = item.llm_error ? formatRuntimeError(item.llm_error) : "";
  const scoreItems = Object.entries(item.scores || {}).slice(0, 4);
  const confidenceMeta = [
    Number.isFinite(toNumber(opinionStrength)) ? `观点 ${formatConfidence(opinionStrength)}` : "",
    Number.isFinite(toNumber(evidenceConfidence)) ? `证据 ${formatConfidence(evidenceConfidence)}` : "",
  ].filter(Boolean).join(" · ");
  return `
    <article class="agent-result-card ${agentCardTone(item, rating)}">
      <div class="agent-result-head">
        <div>
          <h4>${escapeHtml(name)}</h4>
          <span>${escapeHtml(item.source === "llm_agent" ? "LLM 专家" : "规则/数据 Agent")}</span>
        </div>
        <strong>${escapeHtml(rating)}</strong>
      </div>
      <p><b>观点：</b>${escapeHtml(summary)}</p>
      <p><b>原因：</b>${escapeHtml(reason)}</p>
      <div class="agent-confidence">
        <span>系统置信度</span>
        <div><i style="width: ${confidencePercent(confidence)}%"></i></div>
        <b>${escapeHtml(formatConfidence(confidence))}</b>
      </div>
      ${llmError ? `<div class="agent-confidence-meta">${escapeHtml(llmError)}</div>` : ""}
      ${confidenceMeta ? `<div class="agent-confidence-meta">${escapeHtml(confidenceMeta)}</div>` : ""}
      ${scoreItems.length ? `<div class="agent-score-list">${scoreItems.map(([key, value]) => `<span>${escapeHtml(scoreLabel(key))} ${escapeHtml(value)}/5</span>`).join("")}</div>` : ""}
    </article>
  `;
}

function formatRuntimeError(message) {
  const raw = String(message || "");
  if (!raw) return "";
  if (/errno 32|broken pipe/i.test(raw)) {
    return "LLM 连接中断，系统已自动重试；若仍失败则使用规则回退结果。";
  }
  if (/connection reset|connection aborted|remote end closed|server disconnected/i.test(raw)) {
    return "LLM 远端连接提前关闭，系统已自动重试；若仍失败则使用规则回退结果。";
  }
  if (/timed out|timeout/i.test(raw)) {
    return "LLM 请求超时，系统已自动重试；若仍失败则使用规则回退结果。";
  }
  return raw;
}

function agentDisplayLabel(item) {
  if (item.agent === "moat_governance_agent") return item.domain_label || moatGovernanceLabel(item.scores || {});
  const raw = item.rating_hint || item.rating_direction?.label || "-";
  return String(raw).length > 18 ? `${String(raw).slice(0, 18)}...` : raw;
}

function agentCardTone(item, label) {
  if (item.agent === "moat_governance_agent") return "is-neutral";
  return ratingTone(label);
}

function moatGovernanceLabel(scores) {
  const values = [scores.moat_strength, scores.technology_moat, scores.governance_quality]
    .map(toNumber)
    .filter(Number.isFinite);
  if (!values.length) return "护城河待验证";
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  if (avg >= 4) return "护城河较强";
  if (avg >= 3) return "护城河中等";
  return "护城河偏弱";
}

function normalizedAgentResults(payload) {
  const direct = payload.agent_results || payload.manifest?.agent_results || [];
  if (direct.length) return direct;
  const conversation = payload.agent_conversation || [];
  return conversation
    .filter((item) => item?.type === "agent_statement" || item?.speaker)
    .map((item) => ({
      agent: item.speaker,
      agent_role: item.role,
      rating_hint: "-",
      confidence: payload.confidence ?? "-",
      reasoning_summary: item.message || "",
      source: "conversation",
    }))
    .slice(0, 12);
}

function firstFindingText(findings) {
  const first = Array.isArray(findings) ? findings[0] : null;
  return first?.claim || "";
}

function firstCounterText(items) {
  const first = Array.isArray(items) ? items[0] : null;
  return first?.claim || "";
}

function confidencePercent(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(4, Math.min(100, number <= 1 ? number * 100 : number));
}

function formatConfidence(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return number.toFixed(2);
}

function agentDisplayName(agent) {
  const labels = {
    valuation_agent: "估值 Agent",
    technical_timing_agent: "技术时机 Agent",
    moneyflow_agent: "资金流 Agent",
    catalyst_agent: "催化 Agent",
    risk_auditor: "风险审计 Agent",
    value_floor_agent: "价值底线 Agent",
    cheapness_agent: "低估 Agent",
    dividend_sustainability_agent: "分红 Agent",
    cashflow_agent: "现金流 Agent",
    financial_trend_agent: "财务趋势 Agent",
    business_quality_agent: "商业质量 Agent",
    governance_agent: "治理 Agent",
    industry_cycle_agent: "行业周期 Agent",
    market_analyst: "市场分析师",
    news_analyst: "新闻分析师",
    fundamental_analyst: "基本面分析师",
    sentiment_analyst: "情绪分析师",
    moat_governance_agent: "隐形护城河与治理分析师",
    bull_researcher: "多头研究员",
    bear_researcher: "空头研究员",
    research_manager: "研究经理",
    trader: "交易员",
    aggressive_risk_analyst: "激进风控分析师",
    neutral_risk_analyst: "中性风控分析师",
    conservative_risk_analyst: "保守风控分析师",
    portfolio_manager: "组合经理",
  };
  return labels[agent] || String(agent).replace(/_/g, " ");
}

function scoreLabel(key) {
  const labels = {
    valuation_attractiveness: "估值",
    technical_timing: "技术",
    capital_confirmation: "资金",
    catalyst_strength: "催化",
    risk_pressure: "风险",
    earnings_trend: "业绩",
    value_basis: "价值",
    industry_cycle: "行业",
    business_quality: "质量",
    cashflow_quality: "现金流",
    dividend_attractiveness: "分红",
  };
  return labels[key] || key;
}

function renderMetaGrid(items) {
  const visible = items.filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!visible.length) return "";
  return `
    <section class="report-meta-grid">
      ${visible.map(([label, value]) => `
        <div class="report-meta-item">
          <span>${escapeHtml(label)}</span>
          <strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </section>
  `;
}

function learningMetaItems(learningContext = {}) {
  if (!learningContext || learningContext.error) return [];
  const regime = learningContext.market_regime || {};
  const distribution = learningContext.outcome_distribution?.distribution || {};
  const pieces = [];
  const trend = [regime.trend, regime.liquidity].filter(Boolean).join(" / ");
  if (trend) pieces.push(["市场状态", trend]);
  if (Array.isArray(learningContext.similar_cases)) pieces.push(["相似样本", `${learningContext.similar_cases.length} 个`]);
  pieces.push([
    "结局概率",
    `修复 ${distribution.value_repair ?? 0}% · 陷阱 ${distribution.value_trap ?? 0}% · 横盘 ${distribution.long_flat ?? 0}%`,
  ]);
  if (Array.isArray(learningContext.failure_case_matches)) {
    pieces.push(["打脸案例", `${learningContext.failure_case_matches.length} 个`]);
  }
  return pieces;
}

function renderConversationTimeline(messages) {
  if (!messages.length) return "";
  return `
    <section class="report-section conversation-section">
      <h4>多 Agent 对话摘要</h4>
      <div class="agent-timeline">
        ${messages.map((item) => `
          <div class="timeline-item">
            <div class="timeline-head">
              <strong>${escapeHtml(item.speaker || "")}</strong>
              <span>${escapeHtml(item.role || "")}</span>
            </div>
            <p>${escapeHtml(item.message || "")}</p>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderMarkdownReport(markdown) {
  if (!markdown) return "";
  const lines = markdown.split("\n");
  let html = "";
  let listOpen = false;
  let sectionOpen = false;
  let agentOpen = false;

  const closeList = () => {
    if (listOpen) {
      html += "</ul>";
      listOpen = false;
    }
  };
  const closeAgent = () => {
    closeList();
    if (agentOpen) {
      html += "</div>";
      agentOpen = false;
    }
  };
  const closeSection = () => {
    closeAgent();
    if (sectionOpen) {
      html += "</section>";
      sectionOpen = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line === "---") {
      closeList();
      continue;
    }
    if (line.startsWith("# ")) {
      closeSection();
      html += `<h3 class="report-title">${escapeHtml(line.slice(2))}</h3>`;
      continue;
    }
    if (line.startsWith("## ")) {
      closeSection();
      html += `<section class="report-section"><h4>${escapeHtml(line.slice(3))}</h4>`;
      sectionOpen = true;
      continue;
    }
    if (line.startsWith("### ")) {
      closeAgent();
      if (!sectionOpen) {
        html += `<section class="report-section">`;
        sectionOpen = true;
      }
      html += `<div class="agent-card"><h5>${escapeHtml(line.slice(4))}</h5>`;
      agentOpen = true;
      continue;
    }
    if (line.startsWith("- ")) {
      if (!listOpen) {
        html += "<ul>";
        listOpen = true;
      }
      html += `<li>${formatInlineReportText(line.slice(2))}</li>`;
      continue;
    }
    closeList();
    html += `<p>${formatInlineReportText(line)}</p>`;
  }
  closeSection();
  return html;
}

function formatInlineReportText(text) {
  const escaped = escapeHtml(text);
  const index = escaped.indexOf("：");
  if (index > 0 && index < 16) {
    return `<span class="report-label">${escaped.slice(0, index)}</span>${escaped.slice(index)}`;
  }
  return escaped;
}

function ratingTone(rating) {
  const text = String(rating || "");
  if (/(回避|风险|谨慎|等待)/.test(text)) return "is-risk";
  if (/(积极|可试|机会)/.test(text)) return "is-positive";
  return "is-neutral";
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function checkSelectedStatus() {
  if (!selected) return;
  const token = ++syncToken;
  try {
    const response = await fetch("/api/stock-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_code: selected.ts_code }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "状态读取失败");
    if (token !== syncToken) return;
    if (payload.exists) {
      const snapshotCount = payload.metadata?.snapshots?.length || 0;
      selectedHasDailyData = Number(payload.metadata?.dataset_rows?.daily || 0) > 0;
      syncMinuteButtonState();
      output.textContent = `本地已有 ${selected.name}（${selected.ts_code}）的数据。\n上次更新时间：${formatUpdateTime(payload.updated_at)}\n距离现在：${payload.age_text}\n资料包：已保存\n历史快照：${snapshotCount} 个\n\n你可以直接点击“读取数据”查看表格，点击“读取分析”加载已生成报告，也可以点击“更新数据”保存新版本并归档旧版本。`;
    } else {
      selectedHasDailyData = false;
      syncMinuteButtonState();
      output.textContent = `${selected.name}（${selected.ts_code}）本地还没有更新过。\n\n请点击“更新数据”抓取并保存本地数据；更新后再点击“读取数据”查看中文表格。`;
    }
  } catch (error) {
    if (token === syncToken) {
      output.textContent = `读取本地状态失败：${error.message}`;
    }
  }
}

function syncMinuteButtonState() {
  if (!updateThsMarketBtn) return;
  updateThsMarketBtn.disabled = !selected || !selectedHasDailyData;
  updateThsMarketBtn.title = selectedHasDailyData
    ? "补抓分钟行情"
    : "请先点击“更新资料包”，生成 daily 交易日列表";
}

function datasetsHaveDailyRows(datasets, datasetRows = {}) {
  if (Number(datasetRows.daily || 0) > 0) return true;
  const daily = (datasets || []).find((item) => item.key === "daily");
  return Boolean(daily && (daily.row_count || daily.records?.length));
}

function formatUpdateTime(value) {
  if (!value) return "未知";
  const text = String(value).trim();
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})/);
  if (compact) return `${Number(compact[2])}月${Number(compact[3])}日${compact[4]}:${compact[5]}`;
  const plain = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})/);
  if (plain) return `${Number(plain[2])}月${Number(plain[3])}日${plain[4].padStart(2, "0")}:${plain[5]}`;
  const date = new Date(text);
  if (!Number.isNaN(date.getTime())) {
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const hour = String(date.getHours()).padStart(2, "0");
    const minute = String(date.getMinutes()).padStart(2, "0");
    return `${month}月${day}日${hour}:${minute}`;
  }
  return text;
}

function formatDurationText(seconds) {
  const value = Number(seconds || 0);
  if (!Number.isFinite(value) || value <= 0) return "刚刚";
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  if (value < 86400) return `${Math.round(value / 3600)} 小时`;
  return `${Math.round(value / 86400)} 天`;
}

function formatProgressTime(value) {
  const formatted = formatUpdateTime(value);
  return formatted === "未知" ? "" : formatted;
}

function historyScopeText() {
  return "全部历史";
}

async function loadAnalysisFrameworks() {
  try {
    const response = await fetch("/api/analysis-frameworks");
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "读取分析类型失败");
    analysisFrameworks = payload.items?.length ? payload.items : defaultAnalysisFrameworks;
    analysisModuleAvailable = Boolean(payload.analysis_module?.available);
  } catch {
    analysisFrameworks = defaultAnalysisFrameworks;
    analysisModuleAvailable = false;
  }
  analysisTypeSelect.innerHTML = analysisFrameworks
    .map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`)
    .join("");
  initializeAnalysisModuleState();
}

function selectedAnalysisFramework() {
  const key = analysisTypeSelect.value || "value_speculation";
  return analysisFrameworks.find((item) => item.key === key) || defaultAnalysisFrameworks[0];
}

function renderDatasetOptions() {
  datasetSelect.innerHTML = loadedDatasets
    .map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}（${item.row_count}）</option>`)
    .join("");
}

function renderActiveDataset() {
  updateViewModeControls();
  if (!activeDataset) {
    datasetSummary.textContent = "暂无数据";
    tableFilterBar.hidden = true;
    tableFilterToggleBtn.hidden = true;
    closeColumnFilterPopover();
    dataTable.innerHTML = "";
    pageInfo.textContent = "第 0 页";
    prevPageBtn.disabled = true;
    nextPageBtn.disabled = true;
    return;
  }

  const records = activeDataset.records || [];
  const columns = activeDataset.columns || [];
  const visibleRecords = viewMode === "table" ? filteredTableRecords(records, columns) : records;
  const totalPages = Math.max(1, Math.ceil(visibleRecords.length / pageSize));
  currentPage = Math.min(currentPage, totalPages);
  const start = (currentPage - 1) * pageSize;
  const pageRecords = visibleRecords.slice(start, start + pageSize);

  const shownStart = visibleRecords.length ? start + 1 : 0;
  const shownEnd = Math.min(start + pageSize, visibleRecords.length);
  const totalRows = activeDataset.row_count ?? records.length;
  const storageText = activeDataset.storage === "mongodb" && totalRows > records.length
    ? `，MongoDB 共 ${totalRows} 行，已载入最近 ${records.length} 行`
    : `，共 ${records.length} 行`;
  const filteredText = visibleRecords.length === records.length ? "" : `，筛选后 ${visibleRecords.length} 行`;
  datasetSummary.textContent = `${activeDataset.label}${storageText}${filteredText}，当前显示 ${shownStart}-${shownEnd} 行`;
  updateTableFilterInfo(records.length, visibleRecords.length);
  pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页`;
  prevPageBtn.disabled = currentPage <= 1;
  nextPageBtn.disabled = currentPage >= totalPages;

  if (viewMode === "chart") {
    tableFilterBar.hidden = true;
    tableFilterToggleBtn.hidden = true;
    closeColumnFilterPopover();
    document.querySelector(".table-wrap").hidden = true;
    document.querySelector(".pager").hidden = true;
    chartPanel.hidden = false;
    renderChart();
    return;
  }

  tableFilterToggleBtn.hidden = false;
  tableFilterBar.hidden = !tableFilterEnabled;
  document.querySelector(".table-wrap").hidden = false;
  document.querySelector(".pager").hidden = false;
  chartPanel.hidden = true;

  if (!records.length || !columns.length) {
    dataTable.innerHTML = `<tbody><tr><td class="empty-cell">这个数据集暂无记录</td></tr></tbody>`;
    return;
  }

  if (!visibleRecords.length) {
    dataTable.innerHTML = `<tbody><tr><td class="empty-cell">没有符合筛选条件的记录</td></tr></tbody>`;
    return;
  }

  const head = `<thead><tr>${columns.map((col) => renderTableHeaderCell(col)).join("")}</tr></thead>`;
  const bodyRows = pageRecords
    .map((row) => {
      const cells = columns
        .map((col) => {
          const value = row[col.key];
          const text = value === null || value === undefined || value === "" ? "-" : String(value);
          const cls = text === "-" ? " class=\"empty-cell\"" : "";
          return `<td${cls} title="${escapeHtml(text)}">${escapeHtml(text)}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  dataTable.innerHTML = `${head}<tbody>${bodyRows}</tbody>`;
}

function updateViewModeControls() {
  tableViewBtn.classList.toggle("active", viewMode === "table");
  chartViewBtn.classList.toggle("active", viewMode === "chart");
  chartMetricSelect.hidden = viewMode !== "chart";
  chartSecondaryMetricSelect.hidden = viewMode !== "chart" || chartKind(activeDataset || {}) !== "line";
  tableFilterToggleBtn.hidden = viewMode !== "table";
  tableFilterBar.hidden = viewMode !== "table" || !tableFilterEnabled;
  tableFilterToggleBtn.textContent = tableFilterEnabled ? "关闭筛选" : "开启筛选";
  if (viewMode !== "table") closeColumnFilterPopover();
}

function prepareChartMetric() {
  if (!activeDataset) return;
  hoveredPieIndex = -1;
  lineHoverIndex = -1;
  lineHitPoints = [];
  linePlotArea = null;
  pieSlices = [];
  const metrics = numericColumns(activeDataset);
  chartMetricSelect.innerHTML = metrics
    .map((col) => `<option value="${escapeHtml(col.key)}">${escapeHtml(col.label)}</option>`)
    .join("");
  chartSecondaryMetricSelect.innerHTML = [
    `<option value="">无副图</option>`,
    ...metrics.map((col) => `<option value="${escapeHtml(col.key)}">${escapeHtml(col.label)}</option>`),
  ].join("");
  const preferred = preferredMetric(activeDataset.key, metrics);
  if (preferred) chartMetricSelect.value = preferred;
  const secondary = preferredSecondaryMetric(activeDataset.key, metrics, preferred);
  chartSecondaryMetricSelect.value = secondary;
  resetLineWindow();
}

function resetTableFilters() {
  tableFilters = { keyword: "", columns: {} };
  openFilterColumn = null;
  tableSearchInput.value = "";
  tableFilterInfo.textContent = "未筛选";
  closeColumnFilterPopover();
}

function toggleTableFilters() {
  tableFilterEnabled = !tableFilterEnabled;
  if (!tableFilterEnabled) resetTableFilters();
  currentPage = 1;
  renderActiveDataset();
}

function applyTableKeywordFilter() {
  tableFilters.keyword = tableSearchInput.value.trim();
  currentPage = 1;
  renderActiveDataset();
}

function renderTableHeaderCell(col) {
  const active = tableFilterEnabled && Boolean(tableFilters.columns[col.key]);
  const button = tableFilterEnabled
    ? `<button class="column-filter-btn ${active ? "active" : ""}" type="button" data-column="${escapeHtml(col.key)}" title="筛选 ${escapeHtml(col.label)}">⌄</button>`
    : "";
  return `<th title="${escapeHtml(col.key)}"><div class="table-th-inner"><span class="table-th-label">${escapeHtml(col.label)}</span>${button}</div></th>`;
}

function openColumnFilterPopover(columnKey, anchor) {
  if (!activeDataset || !columnKey) return;
  openFilterColumn = columnKey;
  const existing = tableFilters.columns[columnKey] || { operator: "contains", value: "" };
  const label = labelForKey(activeDataset.columns || [], columnKey);
  columnFilterTitle.textContent = label;
  columnFilterOperator.value = existing.operator;
  columnFilterValue.value = existing.value || "";
  columnFilterValue.disabled = ["empty", "not_empty"].includes(columnFilterOperator.value);
  columnFilterQuickSearch.value = "";
  renderColumnFilterValues();

  const rect = anchor.getBoundingClientRect();
  columnFilterPopover.hidden = false;
  const popoverWidth = columnFilterPopover.offsetWidth || 280;
  const left = clampNumber(rect.left, 8, window.innerWidth - popoverWidth - 8);
  columnFilterPopover.style.left = `${left}px`;
  columnFilterPopover.style.top = `${rect.bottom + 6}px`;
}

function closeColumnFilterPopover() {
  openFilterColumn = null;
  columnFilterPopover.hidden = true;
}

function renderColumnFilterValues() {
  if (!activeDataset || !openFilterColumn) {
    columnFilterValues.innerHTML = "";
    return;
  }
  const query = columnFilterQuickSearch.value.trim().toLowerCase();
  const counts = new Map();
  for (const row of activeDataset.records || []) {
    const text = cellText(row[openFilterColumn]) || "(空)";
    if (query && !text.toLowerCase().includes(query)) continue;
    counts.set(text, (counts.get(text) || 0) + 1);
  }
  const values = Array.from(counts, ([text, count]) => ({ text, count }))
    .sort((a, b) => b.count - a.count || a.text.localeCompare(b.text))
    .slice(0, 80);
  if (!values.length) {
    columnFilterValues.innerHTML = `<div class="empty-cell">没有匹配值</div>`;
    return;
  }
  columnFilterValues.innerHTML = values
    .map((item) => `<button class="column-filter-value" type="button" data-value="${escapeHtml(item.text === "(空)" ? "" : item.text)}" title="${escapeHtml(item.text)}">${escapeHtml(item.text)} <span>${item.count}</span></button>`)
    .join("");
  for (const button of columnFilterValues.querySelectorAll(".column-filter-value")) {
    button.addEventListener("click", () => {
      columnFilterOperator.value = button.dataset.value ? "equals" : "empty";
      columnFilterValue.value = button.dataset.value || "";
      applyOpenColumnFilter();
    });
  }
}

function applyOpenColumnFilter() {
  if (!openFilterColumn) return;
  const operator = columnFilterOperator.value;
  const value = columnFilterValue.value.trim();
  if (!value && !["empty", "not_empty"].includes(operator)) {
    delete tableFilters.columns[openFilterColumn];
  } else {
    tableFilters.columns[openFilterColumn] = { operator, value };
  }
  currentPage = 1;
  closeColumnFilterPopover();
  renderActiveDataset();
}

function clearOpenColumnFilter() {
  if (!openFilterColumn) return;
  delete tableFilters.columns[openFilterColumn];
  currentPage = 1;
  closeColumnFilterPopover();
  renderActiveDataset();
}

function filteredTableRecords(records, columns) {
  if (!tableFilterEnabled) return records;
  const keyword = tableFilters.keyword.toLowerCase();
  const columnFilters = Object.entries(tableFilters.columns);

  return records.filter((row) => {
    if (keyword) {
      const matchesKeyword = columns.some((col) => cellText(row[col.key]).toLowerCase().includes(keyword));
      if (!matchesKeyword) return false;
    }
    return columnFilters.every(([key, filter]) => matchFilterValue(row[key], filter.operator, filter.value));
  });
}

function matchFilterValue(value, operator, expected) {
  const text = cellText(value);
  const normalized = text.toLowerCase();
  if (operator === "empty") return text === "";
  if (operator === "not_empty") return text !== "";
  if (!expected) return true;
  if (operator === "contains") return normalized.includes(expected);
  if (operator === "equals") return normalized === expected;
  if (operator === "not_equals") return normalized !== expected;

  const left = Number(text);
  const right = Number(expected);
  if (!Number.isFinite(left) || !Number.isFinite(right)) return false;
  if (operator === "gt") return left > right;
  if (operator === "gte") return left >= right;
  if (operator === "lt") return left < right;
  if (operator === "lte") return left <= right;
  return true;
}

function updateTableFilterInfo(total, visible) {
  const columnCount = Object.keys(tableFilters.columns).length;
  const active = tableFilterEnabled && (tableFilters.keyword || columnCount);
  if (!active) {
    tableFilterInfo.textContent = "未筛选";
    return;
  }
  const keywordText = tableFilters.keyword ? "全文搜索" : "";
  const columnText = columnCount ? `${columnCount} 列筛选` : "";
  tableFilterInfo.textContent = `筛选中：${[keywordText, columnText].filter(Boolean).join("，")}，匹配 ${visible}/${total} 行`;
}

function renderChart() {
  const records = activeDataset.records || [];
  const columns = activeDataset.columns || [];
  const metric = chartMetricSelect.value || numericColumns(activeDataset)[0]?.key;
  const secondaryMetric = chartSecondaryMetricSelect.value || "";
  const metricLabel = labelForKey(columns, metric);
  const secondaryLabel = secondaryMetric ? labelForKey(columns, secondaryMetric) : "";
  if (!records.length || !metric) {
    drawEmptyChart("这个数据集暂无可视化数据");
    chartNote.textContent = "可以切回表格查看原始记录。";
    return;
  }

  const kind = chartKind(activeDataset);
  if (kind === "pie") {
    lineHoverIndex = -1;
    lineHitPoints = [];
    linePlotArea = null;
    lineRangeControls.hidden = true;
    const labelKey = categoricalKey(activeDataset) || "name";
    const data = aggregateByCategory(records, labelKey, metric).slice(0, 10);
    drawPieChart(data, metricLabel);
    const selectedSlice = data[hoveredPieIndex];
    chartNote.textContent = selectedSlice
      ? `已选中：${selectedSlice.label}，占比 ${selectedSlice.percentText}。`
      : `饼图：按“${labelForKey(columns, labelKey)}”汇总“${metricLabel}”，显示前 10 项。`;
    return;
  }

  if (kind === "bar") {
    hoveredPieIndex = -1;
    lineHoverIndex = -1;
    lineHitPoints = [];
    linePlotArea = null;
    pieSlices = [];
    lineRangeControls.hidden = true;
    const labelKey = categoricalKey(activeDataset);
    const data = aggregateByCategory(records, labelKey, metric).slice(0, 20);
    drawBarChart(data, metricLabel);
    chartNote.textContent = `柱状图：按“${labelForKey(columns, labelKey)}”汇总“${metricLabel}”，显示前 20 项。`;
    return;
  }

  const dateKey = dateColumnKey(activeDataset);
  hoveredPieIndex = -1;
  pieSlices = [];
  if (!dateKey) {
    lineHoverIndex = -1;
    lineHitPoints = [];
    linePlotArea = null;
    drawEmptyChart("这个数据集更适合表格查看");
    chartNote.textContent = "当前数据缺少日期或分类字段。";
    return;
  }
  const data = records
    .map((row) => ({
      label: formatDateLabel(row[dateKey]),
      value: toNumber(row[metric]),
      rawDate: String(row[dateKey] || ""),
      open: toNumber(row.open),
      high: toNumber(row.high),
      low: toNumber(row.low),
      close: toNumber(row.close),
      secondary: secondaryMetric ? toNumber(row[secondaryMetric]) : NaN,
    }))
    .filter((item) => item.rawDate && Number.isFinite(item.value))
    .sort((a, b) => a.rawDate.localeCompare(b.rawDate));
  const windowed = lineWindowData(data);
  const useCandlestick = shouldDrawCandlestick(windowed, metric);
  const secondary = secondaryMetric ? { key: secondaryMetric, label: secondaryLabel } : null;
  if (useCandlestick) {
    drawCandlestickChart(windowed, secondary);
  } else {
    drawLineChart(windowed, metricLabel, secondary);
  }
  lineRangeControls.hidden = data.length < 3;
  const secondaryText = secondary && hasSecondaryData(windowed) ? `，下方副图为“${secondary.label}”` : "";
  chartNote.textContent = useCandlestick
    ? `K线图：窗口密度较低，按开盘价、最高价、最低价、收盘价展示${secondaryText}。当前显示 ${windowed.length}/${data.length} 根。`
    : `线图：横轴为“${labelForKey(columns, dateKey)}”，纵轴为“${metricLabel}”${secondaryText}。当前显示 ${windowed.length}/${data.length} 个点。`;
}

function resetLineWindow() {
  lineWindow = { start: 0, end: 0, total: 0 };
  lineHoverIndex = -1;
  renderLineWindowControl([]);
}

function lineWindowData(data) {
  lineWindow.total = data.length;
  clampLineWindow();
  renderLineWindowControl(data);
  return data.slice(lineWindow.start, lineWindow.end);
}

function clampLineWindow() {
  const total = Math.max(0, Number(lineWindow.total) || 0);
  if (!total) {
    lineWindow.start = 0;
    lineWindow.end = 0;
    return;
  }
  const minSpan = Math.min(total, 2);
  let start = Math.round(Number(lineWindow.start) || 0);
  let end = Math.round(Number(lineWindow.end) || total);
  if (end <= 0 || end > total) end = total;
  start = clampNumber(start, 0, Math.max(0, total - minSpan));
  end = clampNumber(end, start + minSpan, total);
  if (end - start < minSpan) {
    start = clampNumber(end - minSpan, 0, Math.max(0, total - minSpan));
    end = start + minSpan;
  }
  lineWindow.start = start;
  lineWindow.end = end;
}

function renderLineWindowControl(data) {
  const total = data.length || lineWindow.total || 0;
  if (!total) {
    lineWindowSelection.style.left = "0%";
    lineWindowSelection.style.width = "100%";
    lineRangeText.textContent = "暂无范围";
    return;
  }
  const left = (lineWindow.start / total) * 100;
  const width = ((lineWindow.end - lineWindow.start) / total) * 100;
  lineWindowSelection.style.left = `${left}%`;
  lineWindowSelection.style.width = `${Math.max(width, 1)}%`;
  const startLabel = data[lineWindow.start]?.label || `第 ${lineWindow.start + 1} 个点`;
  const endLabel = data[Math.max(lineWindow.start, lineWindow.end - 1)]?.label || `第 ${lineWindow.end} 个点`;
  lineRangeText.textContent = `${startLabel} 至 ${endLabel}，${lineWindow.end - lineWindow.start}/${total} 个点`;
}

function beginLineWindowDrag(event, mode) {
  event.preventDefault();
  event.stopPropagation();
  if (lineWindow.total < 3) return;
  lineDrag = {
    mode,
    pointerId: event.pointerId,
    startX: event.clientX,
    initialStart: lineWindow.start,
    initialEnd: lineWindow.end,
  };
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function moveLineWindowDrag(event) {
  if (!lineDrag || event.pointerId !== lineDrag.pointerId) return;
  const total = Math.max(0, lineWindow.total || 0);
  const minSpan = Math.min(total, 2);
  if (!total) return;
  const rect = lineWindowSlider.getBoundingClientRect();
  const delta = Math.round(((event.clientX - lineDrag.startX) / Math.max(1, rect.width)) * total);
  if (lineDrag.mode === "move") {
    const span = lineDrag.initialEnd - lineDrag.initialStart;
    const start = clampNumber(lineDrag.initialStart + delta, 0, Math.max(0, total - span));
    lineWindow.start = start;
    lineWindow.end = start + span;
  } else if (lineDrag.mode === "left") {
    lineWindow.start = clampNumber(lineDrag.initialStart + delta, 0, lineDrag.initialEnd - minSpan);
    lineWindow.end = lineDrag.initialEnd;
  } else {
    lineWindow.start = lineDrag.initialStart;
    lineWindow.end = clampNumber(lineDrag.initialEnd + delta, lineDrag.initialStart + minSpan, total);
  }
  clampLineWindow();
  renderActiveDataset();
}

function endLineWindowDrag(event) {
  if (!lineDrag || event.pointerId !== lineDrag.pointerId) return;
  lineDrag = null;
}

function jumpLineWindowTo(event) {
  if (lineWindow.total < 3) return;
  const total = lineWindow.total;
  const span = Math.max(2, lineWindow.end - lineWindow.start);
  const rect = lineWindowSlider.getBoundingClientRect();
  const fraction = clampNumber((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  const center = Math.round(fraction * total);
  const start = clampNumber(center - Math.floor(span / 2), 0, Math.max(0, total - span));
  lineWindow.start = start;
  lineWindow.end = start + span;
  clampLineWindow();
  renderActiveDataset();
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function renderScores(rating, scores, analysisType = "value_speculation") {
  const labelSets = {
    value_speculation: {
      value_basis: "价值基础",
      valuation_attractiveness: "估值吸引力",
      earnings_trend: "业绩趋势",
      industry_cycle: "行业周期",
      catalyst_strength: "催化强度",
      capital_confirmation: "资金确认",
      technical_timing: "技术时机",
      risk_pressure: "风险压力",
    },
    value_quality: {
      business_quality: "商业质量",
      earnings_resilience: "盈利韧性",
      growth_sustainability: "成长持续性",
      cashflow_quality: "现金流质量",
      balance_sheet_safety: "负债安全",
      governance_return: "治理回报",
      valuation_margin: "估值边际",
      risk_pressure: "风险压力",
    },
    value_dividend: {
      valuation_cheapness: "估值便宜度",
      dividend_attractiveness: "分红吸引力",
      earnings_stability: "盈利稳定性",
      cashflow_coverage: "现金流覆盖",
      balance_sheet_safety: "负债安全",
      industry_defensiveness: "行业防御性",
      governance_return: "治理回报",
      risk_pressure: "风险压力",
    },
    oversold_rebound: {
      oversold_degree: "超跌幅度",
      technical_repair: "技术修复",
      volume_confirmation: "成交配合",
      capital_return: "资金回流",
      industry_resonance: "行业共振",
      catalyst_support: "催化支撑",
      fundamental_floor: "基本面底线",
      risk_pressure: "风险压力",
    },
  };
  const labels = labelSets[analysisType] || Object.fromEntries(Object.keys(scores || {}).map((key) => [key, key]));
  const cards = [
    `<div class="score-card rating-card"><strong>${escapeHtml(rating || "-")}</strong><span>评级提示</span></div>`,
    ...Object.entries(labels).map(([key, label]) => {
      const value = scores[key] ?? "-";
      return `<div class="score-card"><strong>${escapeHtml(value)}/5</strong><span>${label}</span></div>`;
    }),
  ];
  scorePanel.innerHTML = cards.join("");
  scorePanel.hidden = false;
}

function numericColumns(dataset) {
  const records = dataset.records || [];
  return (dataset.columns || []).filter((col) => {
    let count = 0;
    for (const row of records.slice(0, 80)) {
      if (Number.isFinite(toNumber(row[col.key]))) count += 1;
    }
    return count >= Math.min(3, records.length || 3);
  });
}

function preferredMetric(datasetKey, metrics) {
  const preference = {
    daily: ["close", "pct_chg", "amount", "vol"],
    weekly: ["close", "pct_chg", "amount"],
    monthly: ["close", "pct_chg", "amount"],
    sw_daily: ["close", "pct_change", "amount"],
    daily_basic: ["pe_ttm", "pb", "total_mv", "turnover_rate"],
    moneyflow: ["net_mf_amount", "buy_lg_amount", "sell_lg_amount"],
    margin_detail: ["rzrqye", "rzye", "rqye"],
    income: ["revenue", "total_revenue", "n_income_attr_p", "n_income"],
    balancesheet: ["total_assets", "total_liab", "money_cap"],
    cashflow: ["n_cashflow_act", "free_cashflow", "net_profit"],
    fina_indicator: ["roe", "netprofit_yoy", "grossprofit_margin"],
    fina_mainbz: ["bz_sales", "bz_profit", "bz_cost"],
    dividend: ["cash_div", "stk_div"],
    top10_holders: ["hold_ratio", "hold_amount"],
    top10_floatholders: ["hold_ratio", "hold_amount"],
    stk_holdernumber: ["holder_num"],
    pledge_stat: ["pledge_ratio", "pledge_count"],
    block_trade: ["amount", "price", "vol"],
  };
  const keys = metrics.map((item) => item.key);
  return (preference[datasetKey] || []).find((key) => keys.includes(key)) || keys[0] || "";
}

function preferredSecondaryMetric(datasetKey, metrics, primaryKey) {
  const keys = metrics.map((item) => item.key);
  const preference = {
    daily: ["vol", "amount", "turnover_rate", "pct_chg"],
    weekly: ["vol", "amount", "pct_chg"],
    monthly: ["vol", "amount", "pct_chg"],
    sw_daily: ["vol", "amount", "pct_change"],
    daily_basic: ["turnover_rate", "volume_ratio", "total_mv", "circ_mv"],
    moneyflow: ["net_mf_amount", "buy_lg_amount", "sell_lg_amount"],
  };
  return (preference[datasetKey] || ["vol", "amount"])
    .find((key) => key !== primaryKey && keys.includes(key)) || "";
}

function chartKind(dataset) {
  if (["fina_mainbz", "top10_holders", "top10_floatholders", "pledge_stat"].includes(dataset.key)) {
    return "pie";
  }
  if (dateColumnKey(dataset)) return "line";
  if (categoricalKey(dataset)) return "bar";
  return "none";
}

function dateColumnKey(dataset) {
  const keys = (dataset.columns || []).map((col) => col.key);
  return ["trade_date", "ann_date", "end_date", "f_ann_date", "start_date", "float_date"].find((key) => keys.includes(key));
}

function categoricalKey(dataset) {
  const keys = (dataset.columns || []).map((col) => col.key);
  return ["bz_item", "holder_name", "name", "title", "buyer", "seller", "l3_name", "l2_name", "l1_name", "audit_result", "div_proc"].find((key) => keys.includes(key));
}

function aggregateByCategory(records, labelKey, valueKey) {
  const totals = new Map();
  for (const row of records) {
    const label = String(row[labelKey] || "未分类").slice(0, 40);
    const value = toNumber(row[valueKey]);
    if (!Number.isFinite(value)) continue;
    totals.set(label, (totals.get(label) || 0) + Math.abs(value));
  }
  return Array.from(totals, ([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
}

function shouldDrawCandlestick(data, metric) {
  if (!["open", "high", "low", "close"].includes(metric)) return false;
  if (data.length < 2) return false;
  if (!data.every((item) => ["open", "high", "low", "close"].every((key) => Number.isFinite(item[key])))) return false;
  const rect = dataChart.getBoundingClientRect();
  const plotWidth = Math.max(0, (rect.width || dataChart.clientWidth || 960) - 160);
  return plotWidth / data.length >= 7;
}

function hasSecondaryData(data) {
  return data.some((item) => Number.isFinite(item.secondary));
}

function canvasContext() {
  const rect = dataChart.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(360, Math.floor(rect.width || dataChart.clientWidth || 960));
  const height = 420;
  const palette = chartPalette();
  dataChart.width = width * ratio;
  dataChart.height = height * ratio;
  const ctx = dataChart.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.panel;
  ctx.fillRect(0, 0, width, height);
  ctx.font = "13px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  return { ctx, width, height };
}

function drawEmptyChart(message) {
  const { ctx, width, height } = canvasContext();
  const palette = chartPalette();
  ctx.fillStyle = palette.muted;
  ctx.textAlign = "center";
  ctx.fillText(message, width / 2, height / 2);
}

function drawLineChart(data, metricLabel, secondary = null) {
  const { ctx, width, height } = canvasContext();
  if (data.length < 2) {
    lineHitPoints = [];
    linePlotArea = null;
    drawEmptyChart("数据点太少，无法绘制线图");
    return;
  }
  const margin = { top: 34, right: 72, bottom: 66, left: 88 };
  const plotW = width - margin.left - margin.right;
  const showSecondary = secondary && hasSecondaryData(data);
  const secondaryH = showSecondary ? 68 : 0;
  const secondaryGap = showSecondary ? 34 : 0;
  const plotH = height - margin.top - margin.bottom - secondaryH - secondaryGap;
  const secondaryArea = showSecondary
    ? { top: margin.top + plotH + secondaryGap, bottom: margin.top + plotH + secondaryGap + secondaryH, height: secondaryH }
    : null;
  const values = data.map((item) => item.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const rawSpan = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
  const min = rawMin - rawSpan * 0.08;
  const max = rawMax + rawSpan * 0.08;
  const span = max - min || 1;

  drawAxes(ctx, margin, plotW, plotH, min, max);
  const palette = chartPalette();
  ctx.strokeStyle = palette.primary;
  ctx.lineWidth = 2;
  ctx.beginPath();
  linePlotArea = { left: margin.left, right: margin.left + plotW, top: margin.top, bottom: secondaryArea?.bottom || margin.top + plotH };
  lineHitPoints = data.map((item, index) => {
    const x = margin.left + (plotW * index) / (data.length - 1);
    const y = margin.top + plotH - ((item.value - min) / span) * plotH;
    return { ...item, x, y, index };
  });
  if (lineHoverIndex >= lineHitPoints.length) lineHoverIndex = lineHitPoints.length - 1;
  data.forEach((item, index) => {
    const { x, y } = lineHitPoints[index];
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  if (secondaryArea) drawSecondaryBars(ctx, data, margin, plotW, secondaryArea, secondary.label);
  drawLineCrosshair(ctx, margin, plotW, plotH, metricLabel, secondaryArea);
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText(fitText(ctx, metricLabel, width - margin.left - margin.right), margin.left, 22);
  drawXAxisLabels(ctx, data, margin, plotW, plotH);
}

function drawCandlestickChart(data, secondary = null) {
  const { ctx, width, height } = canvasContext();
  if (data.length < 2) {
    lineHitPoints = [];
    linePlotArea = null;
    drawEmptyChart("数据点太少，无法绘制K线图");
    return;
  }
  const margin = { top: 34, right: 72, bottom: 66, left: 88 };
  const plotW = width - margin.left - margin.right;
  const showSecondary = secondary && hasSecondaryData(data);
  const secondaryH = showSecondary ? 68 : 0;
  const secondaryGap = showSecondary ? 34 : 0;
  const plotH = height - margin.top - margin.bottom - secondaryH - secondaryGap;
  const secondaryArea = showSecondary
    ? { top: margin.top + plotH + secondaryGap, bottom: margin.top + plotH + secondaryGap + secondaryH, height: secondaryH }
    : null;
  const lows = data.map((item) => item.low);
  const highs = data.map((item) => item.high);
  const rawMin = Math.min(...lows);
  const rawMax = Math.max(...highs);
  const rawSpan = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
  const min = rawMin - rawSpan * 0.08;
  const max = rawMax + rawSpan * 0.08;
  const span = max - min || 1;
  const valueToY = (value) => margin.top + plotH - ((value - min) / span) * plotH;
  const candleGap = data.length > 1 ? plotW / (data.length - 1) : plotW;
  const bodyWidth = Math.max(3, Math.min(14, candleGap * 0.56));

  drawAxes(ctx, margin, plotW, plotH, min, max);
  linePlotArea = { left: margin.left, right: margin.left + plotW, top: margin.top, bottom: secondaryArea?.bottom || margin.top + plotH };
  lineHitPoints = data.map((item, index) => {
    const x = margin.left + (plotW * index) / (data.length - 1);
    const y = valueToY(item.close);
    return {
      ...item,
      x,
      y,
      index,
      value: item.close,
      tooltipLines: [
        `收 ${formatNumber(item.close)}  开 ${formatNumber(item.open)}`,
        `高 ${formatNumber(item.high)}  低 ${formatNumber(item.low)}`,
        item.label,
      ],
    };
  });
  if (lineHoverIndex >= lineHitPoints.length) lineHoverIndex = lineHitPoints.length - 1;

  for (const point of lineHitPoints) {
    const rising = point.close >= point.open;
    const palette = chartPalette();
    const color = rising ? palette.candleUp : palette.candleDown;
    const highY = valueToY(point.high);
    const lowY = valueToY(point.low);
    const openY = valueToY(point.open);
    const closeY = valueToY(point.close);
    const bodyTop = Math.min(openY, closeY);
    const bodyH = Math.max(2, Math.abs(closeY - openY));

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(point.x, highY);
    ctx.lineTo(point.x, lowY);
    ctx.stroke();
    ctx.fillStyle = color;
    if (rising) {
      ctx.strokeRect(point.x - bodyWidth / 2, bodyTop, bodyWidth, bodyH);
    } else {
      ctx.fillRect(point.x - bodyWidth / 2, bodyTop, bodyWidth, bodyH);
    }
  }

  if (secondaryArea) drawSecondaryBars(ctx, data, margin, plotW, secondaryArea, secondary.label);
  drawLineCrosshair(ctx, margin, plotW, plotH, "收盘价", secondaryArea);
  const palette = chartPalette();
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText("K线图", margin.left, 22);
  drawXAxisLabels(ctx, data, margin, plotW, plotH);
}

function drawSecondaryBars(ctx, data, margin, plotW, area, label) {
  const values = data.map((item) => item.secondary).filter(Number.isFinite);
  if (!values.length) return;
  const max = Math.max(...values.map(Math.abs)) || 1;
  const gap = data.length > 1 ? plotW / (data.length - 1) : plotW;
  const barW = Math.max(2, Math.min(12, gap * 0.58));

  ctx.save();
  const palette = chartPalette();
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margin.left, area.top);
  ctx.lineTo(margin.left + plotW, area.top);
  ctx.moveTo(margin.left, area.bottom);
  ctx.lineTo(margin.left + plotW, area.bottom);
  ctx.stroke();

  data.forEach((item, index) => {
    if (!Number.isFinite(item.secondary)) return;
    const x = margin.left + (plotW * index) / Math.max(1, data.length - 1);
    const h = Math.max(1, (Math.abs(item.secondary) / max) * area.height);
    const rising = Number.isFinite(item.close) && Number.isFinite(item.open) ? item.close >= item.open : item.secondary >= 0;
    ctx.fillStyle = rising ? "rgba(235, 87, 87, 0.72)" : "rgba(39, 174, 96, 0.72)";
    ctx.fillRect(x - barW / 2, area.bottom - h, barW, h);
  });

  ctx.fillStyle = palette.muted;
  ctx.textAlign = "left";
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(fitText(ctx, label, plotW * 0.45), margin.left, area.top - 10);
  ctx.textAlign = "right";
  ctx.fillText(formatNumber(max), margin.left - 10, area.top + 4);
  ctx.restore();
}

function drawLineCrosshair(ctx, margin, plotW, plotH, metricLabel, secondaryArea = null) {
  const point = lineHitPoints[lineHoverIndex];
  if (!point) return;
  const plotLeft = margin.left;
  const plotRight = margin.left + plotW;
  const plotTop = margin.top;
  const plotBottom = margin.top + plotH;
  const verticalBottom = secondaryArea?.bottom || plotBottom;

  ctx.save();
  const palette = chartPalette();
  ctx.strokeStyle = palette.muted;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(point.x, plotTop);
  ctx.lineTo(point.x, verticalBottom);
  ctx.moveTo(plotLeft, point.y);
  ctx.lineTo(plotRight, point.y);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = palette.primary;
  ctx.strokeStyle = palette.panel;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(point.x, point.y, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  const valueLabel = formatNumber(point.value);
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  const valueW = Math.min(76, Math.max(42, ctx.measureText(valueLabel).width + 16));
  const valueX = Math.max(4, plotLeft - valueW - 8);
  const valueY = clampNumber(point.y - 13, plotTop, plotBottom - 26);
  roundedRect(ctx, valueX, valueY, valueW, 26, 4);
  ctx.fillStyle = palette.primary;
  ctx.fill();
  ctx.fillStyle = palette.tooltipText;
  ctx.textAlign = "center";
  ctx.fillText(fitText(ctx, valueLabel, valueW - 10), valueX + valueW / 2, valueY + 17);

  const dateW = Math.max(88, ctx.measureText(point.label).width + 18);
  const dateX = clampNumber(point.x - dateW / 2, plotLeft, plotRight - dateW);
  const dateY = verticalBottom + 34;
  roundedRect(ctx, dateX, dateY, dateW, 26, 4);
  ctx.fillStyle = palette.primary;
  ctx.fill();
  ctx.fillStyle = palette.tooltipText;
  ctx.textAlign = "center";
  ctx.fillText(point.label, dateX + dateW / 2, dateY + 17);

  const secondaryLine = secondaryArea && Number.isFinite(point.secondary) ? `副图 ${formatNumber(point.secondary)}` : "";
  const tooltipLines = (point.tooltipLines || [`${metricLabel} ${valueLabel}`, point.label])
    .concat(secondaryLine ? [secondaryLine] : []);
  const tooltipW = Math.min(240, Math.max(...tooltipLines.map((line) => ctx.measureText(line).width)) + 22);
  const tooltipH = tooltipLines.length * 18 + 12;
  const tooltipX = point.x + tooltipW + 14 > plotRight ? point.x - tooltipW - 14 : point.x + 14;
  const tooltipY = clampNumber(point.y - tooltipH - 12, plotTop + 4, plotBottom - tooltipH - 4);
  roundedRect(ctx, tooltipX, tooltipY, tooltipW, tooltipH, 6);
  ctx.fillStyle = palette.tooltip;
  ctx.fill();
  ctx.fillStyle = palette.tooltipText;
  ctx.textAlign = "left";
  ctx.font = "700 12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  tooltipLines.forEach((line, index) => {
    ctx.font = index === 0 ? "700 12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" : "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
    ctx.fillText(fitText(ctx, line, tooltipW - 18), tooltipX + 10, tooltipY + 18 + index * 18);
  });
  ctx.restore();
}

function drawBarChart(data, metricLabel) {
  const { ctx, width, height } = canvasContext();
  if (!data.length) {
    drawEmptyChart("没有可绘制的分类数据");
    return;
  }
  const margin = { top: 28, right: 24, bottom: 100, left: 72 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const max = Math.max(...data.map((item) => item.value)) || 1;
  drawAxes(ctx, margin, plotW, plotH, 0, max);
  const gap = 6;
  const barW = Math.max(8, (plotW - gap * (data.length - 1)) / data.length);
  data.forEach((item, index) => {
    const x = margin.left + index * (barW + gap);
    const h = (item.value / max) * plotH;
    const y = margin.top + plotH - h;
    const palette = chartPalette();
    ctx.fillStyle = palette.primary;
    ctx.fillRect(x, y, barW, h);
    ctx.save();
    ctx.translate(x + barW / 2, margin.top + plotH + 12);
    ctx.rotate(-Math.PI / 4);
    ctx.fillStyle = palette.muted;
    ctx.textAlign = "right";
    ctx.fillText(item.label.slice(0, 12), 0, 0);
    ctx.restore();
  });
  const palette = chartPalette();
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText(metricLabel, margin.left, 18);
}

function drawPieChart(data, metricLabel) {
  const { ctx, width, height } = canvasContext();
  if (!data.length) {
    drawEmptyChart("没有可绘制的占比数据");
    return;
  }
  const total = data.reduce((sum, item) => sum + item.value, 0) || 1;
  const colors = ["#2f80ed", "#27ae60", "#f2994a", "#eb5757", "#9b51e0", "#00a3a3", "#344054", "#56ccf2", "#f2c94c", "#6fcf97"];
  const legendX = Math.max(width * 0.56, 430);
  const legendWidth = Math.max(160, width - legendX - 24);
  const radius = Math.min(height * 0.32, Math.max(110, (legendX - 96) * 0.42));
  const cx = Math.max(150, Math.min(legendX * 0.42, legendX - radius - 42));
  const cy = height * 0.52;
  let start = -Math.PI / 2;
  pieSlices = [];
  data.forEach((item, index) => {
    const angle = (item.value / total) * Math.PI * 2;
    const end = start + angle;
    const mid = start + angle / 2;
    const isHovered = index === hoveredPieIndex;
    const offset = isHovered ? 10 : 0;
    const sliceCx = cx + Math.cos(mid) * offset;
    const sliceCy = cy + Math.sin(mid) * offset;
    ctx.beginPath();
    ctx.moveTo(sliceCx, sliceCy);
    ctx.arc(sliceCx, sliceCy, radius, start, end);
    ctx.closePath();
    ctx.fillStyle = colors[index % colors.length];
    ctx.fill();
    if (isHovered) {
      const palette = chartPalette();
      ctx.strokeStyle = palette.panel;
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.strokeStyle = palette.text;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    item.percentText = `${((item.value / total) * 100).toFixed(1)}%`;
    pieSlices.push({ start, end, cx, cy, radius, item });
    start = end;
  });
  const palette = chartPalette();
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText(metricLabel, 20, 22);
  data.forEach((item, index) => {
    const x = legendX;
    const y = 62 + index * 30;
    const isHovered = index === hoveredPieIndex;
    ctx.fillStyle = colors[index % colors.length];
    ctx.fillRect(x, y - 10, 14, 14);
    ctx.fillStyle = palette.text;
    ctx.font = `${isHovered ? "700 " : ""}13px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif`;
    ctx.fillText(fitText(ctx, `${item.label} ${item.percentText}`, legendWidth - 22), x + 22, y);
    ctx.font = "13px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  });
}

function hitTestPie(event) {
  const rect = dataChart.getBoundingClientRect();
  const scaleX = dataChart.width / (window.devicePixelRatio || 1) / rect.width;
  const scaleY = dataChart.height / (window.devicePixelRatio || 1) / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  for (let index = 0; index < pieSlices.length; index += 1) {
    const slice = pieSlices[index];
    const dx = x - slice.cx;
    const dy = y - slice.cy;
    const distance = Math.sqrt(dx * dx + dy * dy);
    if (distance > slice.radius) continue;
    let angle = Math.atan2(dy, dx);
    if (angle < -Math.PI / 2) angle += Math.PI * 2;
    if (angle >= slice.start && angle <= slice.end) return index;
  }
  return -1;
}

function hitTestLine(event) {
  if (!lineHitPoints.length || !linePlotArea) return -1;
  const rect = dataChart.getBoundingClientRect();
  const scaleX = dataChart.width / (window.devicePixelRatio || 1) / rect.width;
  const scaleY = dataChart.height / (window.devicePixelRatio || 1) / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  if (x < linePlotArea.left || x > linePlotArea.right || y < linePlotArea.top || y > linePlotArea.bottom) return -1;
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const point of lineHitPoints) {
    const distance = Math.abs(point.x - x);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = point.index;
    }
  }
  return nearestIndex;
}

function fitText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let result = text;
  while (result.length > 2 && ctx.measureText(`${result}...`).width > maxWidth) {
    result = result.slice(0, -1);
  }
  return `${result}...`;
}

function roundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawAxes(ctx, margin, plotW, plotH, min, max) {
  const palette = chartPalette();
  ctx.strokeStyle = palette.axis;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margin.left, margin.top);
  ctx.lineTo(margin.left, margin.top + plotH);
  ctx.lineTo(margin.left + plotW, margin.top + plotH);
  ctx.stroke();
  ctx.fillStyle = palette.muted;
  ctx.textAlign = "right";
  const labelWidth = Math.max(36, margin.left - 16);
  for (let i = 0; i <= 4; i += 1) {
    const value = min + ((max - min) * i) / 4;
    const y = margin.top + plotH - (plotH * i) / 4;
    ctx.fillText(fitText(ctx, formatNumber(value), labelWidth), margin.left - 10, y + 4);
    ctx.strokeStyle = palette.grid;
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(margin.left + plotW, y);
    ctx.stroke();
  }
}

function drawXAxisLabels(ctx, data, margin, plotW, plotH) {
  const palette = chartPalette();
  ctx.fillStyle = palette.muted;
  const positions = [
    { index: 0, align: "left", maxWidth: Math.max(70, plotW * 0.28) },
    { index: Math.floor(data.length / 2), align: "center", maxWidth: Math.max(70, plotW * 0.26) },
    { index: data.length - 1, align: "right", maxWidth: Math.max(70, plotW * 0.28) },
  ];
  const seen = new Set();
  for (const item of positions) {
    const index = Math.max(0, Math.min(data.length - 1, item.index));
    if (seen.has(index)) continue;
    seen.add(index);
    const x = margin.left + (plotW * index) / Math.max(1, data.length - 1);
    ctx.textAlign = item.align;
    ctx.fillText(fitText(ctx, data[index].label, item.maxWidth), x, margin.top + plotH + 32);
  }
}

function labelForKey(columns, key) {
  return columns.find((col) => col.key === key)?.label || key || "";
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return NaN;
  const text = String(value).trim();
  if (!text || text === "-" || text === "--") return NaN;
  const number = Number(text.replaceAll(",", "").replace(/%$/, ""));
  return Number.isFinite(number) ? number : NaN;
}

function cellText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function formatDateLabel(value) {
  const text = String(value || "");
  if (/^\d{8}$/.test(text)) return `${Number(text.slice(4, 6))}月${Number(text.slice(6, 8))}日`;
  const plain = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (plain) return `${Number(plain[2])}月${Number(plain[3])}日`;
  return text;
}

function formatNumber(value) {
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${(value / 10000).toFixed(1)}万`;
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 1) return value.toFixed(2);
  return value.toFixed(4);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
