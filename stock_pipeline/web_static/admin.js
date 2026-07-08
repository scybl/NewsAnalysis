const themeToggleBtn = document.querySelector("#themeToggleBtn");
const logoutBtn = document.querySelector("#logoutBtn");
const createInviteBtn = document.querySelector("#createInviteBtn");
const systemDeepSeekInput = document.querySelector("#systemDeepSeekInput");
const saveSystemDeepSeekBtn = document.querySelector("#saveSystemDeepSeekBtn");
const deleteSystemDeepSeekBtn = document.querySelector("#deleteSystemDeepSeekBtn");
const systemDeepSeekStatus = document.querySelector("#systemDeepSeekStatus");
const agentTokenNameInput = document.querySelector("#agentTokenNameInput");
const agentTokenScopesInput = document.querySelector("#agentTokenScopesInput");
const agentTokenDaysInput = document.querySelector("#agentTokenDaysInput");
const agentTokenRateInput = document.querySelector("#agentTokenRateInput");
const createAgentTokenBtn = document.querySelector("#createAgentTokenBtn");
const adminAgentTokensTable = document.querySelector("#adminAgentTokensTable");
const adminAgentAuditTable = document.querySelector("#adminAgentAuditTable");
const agentGatewayStatus = document.querySelector("#agentGatewayStatus");
const agentTokenActiveCount = document.querySelector("#agentTokenActiveCount");
const agentAuditCount = document.querySelector("#agentAuditCount");
const AGENT_GATEWAY_AVAILABLE = false;
const adminSummary = document.querySelector("#adminSummary");
const adminUsersTable = document.querySelector("#adminUsersTable");
const adminInvitesTable = document.querySelector("#adminInvitesTable");
const adminTasksTable = document.querySelector("#adminTasksTable");
const adminAuditTable = document.querySelector("#adminAuditTable");
const adminAuditPage = document.body?.dataset.adminAuditPage === "true";
const adminUserCount = document.querySelector("#adminUserCount");
const adminInviteCount = document.querySelector("#adminInviteCount");
const adminVipCodeCount = document.querySelector("#adminVipCodeCount");
const adminDemoCount = document.querySelector("#adminDemoCount");
const adminTaskCount = document.querySelector("#adminTaskCount");
const spiderStatus = document.querySelector("#spiderStatus");
const spiderStateText = document.querySelector("#spiderStateText");
const spiderModeText = document.querySelector("#spiderModeText");
const spiderSourceText = document.querySelector("#spiderSourceText");
const spiderTypeText = document.querySelector("#spiderTypeText");
const spiderPagesText = document.querySelector("#spiderPagesText");
const spiderLogFile = document.querySelector("#spiderLogFile");
const spiderSourcesSelect = document.querySelector("#spiderSourcesSelect");
const spiderSourceHint = document.querySelector("#spiderSourceHint");
const spiderSourceTasks = document.querySelector("#spiderSourceTasks");
const spiderTypesSelect = document.querySelector("#spiderTypesSelect");
const spiderStockCodeField = document.querySelector("#spiderStockCodeField");
const spiderStockCode = document.querySelector("#spiderStockCode");
const spiderStockTsCode = document.querySelector("#spiderStockTsCode");
const spiderStockSuggestions = document.querySelector("#spiderStockSuggestions");
const spiderStockSelection = document.querySelector("#spiderStockSelection");
const spiderMaxPages = document.querySelector("#spiderMaxPages");
const spiderThreads = document.querySelector("#spiderThreads");
const spiderArticleSleep = document.querySelector("#spiderArticleSleep");
const spiderPageSleep = document.querySelector("#spiderPageSleep");
const spiderNewOnly = document.querySelector("#spiderNewOnly");
const startSpiderBtn = document.querySelector("#startSpiderBtn");
const stopSpiderBtn = document.querySelector("#stopSpiderBtn");
const spiderLogs = document.querySelector("#spiderLogs");
const dailyMarketStatus = document.querySelector("#dailyMarketStatus");
const dailyMarketEnabled = document.querySelector("#dailyMarketEnabled");
const dailyMarketTime = document.querySelector("#dailyMarketTime");
const saveDailyMarketSchedulerBtn = document.querySelector("#saveDailyMarketSchedulerBtn");
const runDailyMarketNowBtn = document.querySelector("#runDailyMarketNowBtn");
const dailyMarketStockCount = document.querySelector("#dailyMarketStockCount");
const dailyStockListCount = document.querySelector("#dailyStockListCount");
const dailyMarketLastDate = document.querySelector("#dailyMarketLastDate");
const dailyMarketUpdated = document.querySelector("#dailyMarketUpdated");
const dailyMarketSkipped = document.querySelector("#dailyMarketSkipped");
const idlePrefetchStatus = document.querySelector("#idlePrefetchStatus");
const idlePrefetchEnabled = document.querySelector("#idlePrefetchEnabled");
const idlePrefetchSeconds = document.querySelector("#idlePrefetchSeconds");
const idlePrefetchRefreshDays = document.querySelector("#idlePrefetchRefreshDays");
const saveIdlePrefetchBtn = document.querySelector("#saveIdlePrefetchBtn");
const runIdlePrefetchNowBtn = document.querySelector("#runIdlePrefetchNowBtn");
const idlePrefetchRemaining = document.querySelector("#idlePrefetchRemaining");
const idlePrefetchLastRequest = document.querySelector("#idlePrefetchLastRequest");
const idlePrefetchLastResult = document.querySelector("#idlePrefetchLastResult");
const kaipanlaMeta = document.querySelector("#kaipanlaMeta");
const kaipanlaValidateBtn = document.querySelector("#kaipanlaValidateBtn");
const kaipanlaSaveBtn = document.querySelector("#kaipanlaSaveBtn");
const kaipanlaRunBtn = document.querySelector("#kaipanlaRunBtn");
const kaipanlaEnabled = document.querySelector("#kaipanlaEnabled");
const kaipanlaTime = document.querySelector("#kaipanlaTime");
const kaipanlaStateText = document.querySelector("#kaipanlaStateText");
const kaipanlaTimeText = document.querySelector("#kaipanlaTimeText");
const kaipanlaFeatureCount = document.querySelector("#kaipanlaFeatureCount");
const kaipanlaLastDate = document.querySelector("#kaipanlaLastDate");
const kaipanlaLastResult = document.querySelector("#kaipanlaLastResult");
const kaipanlaOverviewDate = document.querySelector("#kaipanlaOverviewDate");
const kaipanlaOverviewRefreshBtn = document.querySelector("#kaipanlaOverviewRefreshBtn");
const kaipanlaOverviewMeta = document.querySelector("#kaipanlaOverviewMeta");
const kaipanlaOverviewKpis = document.querySelector("#kaipanlaOverviewKpis");
const kaipanlaOverviewSections = document.querySelector("#kaipanlaOverviewSections");

let spiderPollTimer = null;
let spiderStockSearchTimer = null;
let adminReadonly = false;
let adminDataViewer = false;
let adminTaskItems = [];
let selectedAdminTaskId = "";
const dataConsolePage = document.body?.dataset.dataConsolePage === "true";
const dataConsoleHrefs = new Set(["/admin-market.html", "/admin-news.html", "/admin-crawler.html"]);
const kaipanlaState = {
  features: [],
  scheduler: {},
};

initializeTheme();
initializeAdminPage();

spiderStockCode?.addEventListener("input", () => {
  if (spiderStockTsCode) spiderStockTsCode.value = "";
  if (spiderStockSelection) spiderStockSelection.textContent = "输入关键词并选择一只股票";
  window.clearTimeout(spiderStockSearchTimer);
  spiderStockSearchTimer = window.setTimeout(searchMarketStocks, 220);
});

spiderStockCode?.addEventListener("focus", () => {
  if (spiderStockCode.value.trim() && !spiderStockTsCode?.value) searchMarketStocks();
});

document.addEventListener("click", (event) => {
  if (!spiderStockCodeField?.contains(event.target)) hideMarketStockSuggestions();
});

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
}

function approveDataFetch(message) {
  return window.confirm(`${message}\n\n该操作会访问外部数据源。确认执行？`);
}

themeToggleBtn?.addEventListener("click", () => {
  const nextTheme = document.documentElement.classList.contains("theme-dark") ? "light" : "dark";
  try {
    localStorage.setItem("stockTheme", nextTheme);
  } catch {}
  applyTheme(nextTheme);
});

logoutBtn?.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
});

createInviteBtn?.addEventListener("click", async () => {
  createInviteBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/invite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 1 }),
    });
    await readApiPayload(response, "生成邀请码失败");
    await loadAdminOverview();
  } catch (error) {
    adminSummary.textContent = `生成邀请码失败：${error.message}`;
  } finally {
    createInviteBtn.disabled = false;
  }
});

saveSystemDeepSeekBtn?.addEventListener("click", async () => {
  const token = systemDeepSeekInput?.value.trim() || "";
  if (!token) {
    adminSummary.textContent = "请先输入 DeepSeek key。";
    return;
  }
  saveSystemDeepSeekBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/system-api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deepseek_api: token }),
    });
    await readApiPayload(response, "保存系统 DeepSeek key 失败");
    if (systemDeepSeekInput) systemDeepSeekInput.value = "";
    await loadAdminOverview();
    adminSummary.textContent = "系统 DeepSeek key 已验证并锁定。";
  } catch (error) {
    adminSummary.textContent = `保存系统 DeepSeek key 失败：${error.message}`;
  } finally {
    saveSystemDeepSeekBtn.disabled = false;
  }
});

deleteSystemDeepSeekBtn?.addEventListener("click", async () => {
  if (!window.confirm("确定移除系统 DeepSeek key？依赖全局模型额度的分析会暂停。")) return;
  deleteSystemDeepSeekBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/system-api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete" }),
    });
    await readApiPayload(response, "移除系统 DeepSeek key 失败");
    await loadAdminOverview();
    adminSummary.textContent = "系统 DeepSeek key 已移除。";
  } catch (error) {
    adminSummary.textContent = `移除系统 DeepSeek key 失败：${error.message}`;
  } finally {
    deleteSystemDeepSeekBtn.disabled = false;
  }
});

createAgentTokenBtn?.addEventListener("click", async () => {
  if (!AGENT_GATEWAY_AVAILABLE) {
    adminSummary.textContent = "Agent Gateway 正在调试中，暂不可用。";
    return;
  }
  createAgentTokenBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/agent-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: agentTokenNameInput?.value || "agent",
        scopes: agentTokenScopesInput?.value || "R",
        expires_in_days: Number(agentTokenDaysInput?.value || 30),
        rate_limit_per_min: Number(agentTokenRateInput?.value || 60),
      }),
    });
    const payload = await readApiPayload(response, "生成 Agent token 失败");
    await loadAdminOverview();
    const token = payload.agent_token?.token || "";
    adminSummary.textContent = token ? `Agent token 已生成（只显示一次）：${token}` : "Agent token 已生成。";
  } catch (error) {
    adminSummary.textContent = `生成 Agent token 失败：${error.message}`;
  } finally {
    createAgentTokenBtn.disabled = false;
  }
});

startSpiderBtn?.addEventListener("click", async () => {
  startSpiderBtn.disabled = true;
  let started = false;
  try {
    const selectedSource = spiderSourcesSelect?.querySelector("input[type='radio']:checked")?.value || "ths";
    if (!approveDataFetch(`启动 ${sourceLabel(selectedSource)} 爬虫`)) return;
    const selectedTypes = [...spiderTypesSelect.querySelectorAll("input[type='checkbox']:checked")].map((input) => input.value);
    const response = await fetch("/api/admin/market-fetch/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: selectedSource,
        types: selectedTypes.length ? selectedTypes : ["财经要闻"],
        max_pages: Number(spiderMaxPages.value || 1),
        threads: Number(spiderThreads.value || 2),
        article_sleep: spiderArticleSleep.value || "3,5",
        page_sleep: spiderPageSleep.value || "5,10",
        new_only: spiderNewOnly.checked,
        stock_code: selectedMarketStockCode(),
        approved: true,
      }),
    });
    await readApiPayload(response, "启动行情补采失败");
    started = true;
    await refreshSpiderConsole();
    startSpiderPolling();
  } catch (error) {
    spiderStatus.textContent = `启动失败：${error.message}`;
  } finally {
    if (!started) startSpiderBtn.disabled = false;
  }
});

stopSpiderBtn?.addEventListener("click", async () => {
  stopSpiderBtn.disabled = true;
  try {
    const selectedSource = getSelectedSpiderSource();
    const response = await fetch("/api/admin/market-fetch/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: selectedSource }),
    });
    await readApiPayload(response, "停止行情补采失败");
    await refreshSpiderConsole();
  } catch (error) {
    spiderStatus.textContent = `停止失败：${error.message}`;
  }
});

saveDailyMarketSchedulerBtn?.addEventListener("click", async () => {
  saveDailyMarketSchedulerBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/daily-market-scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save",
        enabled: !!dailyMarketEnabled?.checked,
        time: dailyMarketTime?.value || "21:30",
      }),
    });
    const payload = await readApiPayload(response, "保存每日股票数据定时失败");
    renderDailyMarketScheduler(payload.scheduler || {});
  } catch (error) {
    if (dailyMarketStatus) dailyMarketStatus.textContent = `保存失败：${error.message}`;
  } finally {
    saveDailyMarketSchedulerBtn.disabled = false;
  }
});

runDailyMarketNowBtn?.addEventListener("click", async () => {
  runDailyMarketNowBtn.disabled = true;
  try {
    if (!approveDataFetch("立即执行每日股票数据更新")) return;
    const response = await fetch("/api/admin/daily-market-scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now", approved: true }),
    });
    const payload = await readApiPayload(response, "启动每日股票数据更新失败");
    renderDailyMarketScheduler(payload.scheduler || {});
    await loadAdminTasks();
  } catch (error) {
    if (dailyMarketStatus) dailyMarketStatus.textContent = `启动失败：${error.message}`;
  } finally {
    runDailyMarketNowBtn.disabled = false;
  }
});

saveIdlePrefetchBtn?.addEventListener("click", async () => {
  saveIdlePrefetchBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/idle-stock-prefetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save",
        enabled: !!idlePrefetchEnabled?.checked,
        idle_seconds: Number(idlePrefetchSeconds?.value || 1800),
        refresh_existing_days: Number(idlePrefetchRefreshDays?.value || 14),
      }),
    });
    const payload = await readApiPayload(response, "保存空闲预抓失败");
    renderIdlePrefetchScheduler(payload.scheduler || {});
  } catch (error) {
    if (idlePrefetchStatus) idlePrefetchStatus.textContent = `保存失败：${error.message}`;
  } finally {
    saveIdlePrefetchBtn.disabled = false;
  }
});

runIdlePrefetchNowBtn?.addEventListener("click", async () => {
  runIdlePrefetchNowBtn.disabled = true;
  try {
    if (!approveDataFetch("立即预抓一只未建立详情资料包的股票")) return;
    const response = await fetch("/api/admin/idle-stock-prefetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now", approved: true }),
    });
    const payload = await readApiPayload(response, "启动空闲预抓失败");
    renderIdlePrefetchScheduler(payload.scheduler || {});
    await loadAdminTasks();
  } catch (error) {
    if (idlePrefetchStatus) idlePrefetchStatus.textContent = `启动失败：${error.message}`;
  } finally {
    runIdlePrefetchNowBtn.disabled = false;
  }
});

kaipanlaOverviewRefreshBtn?.addEventListener("click", () => loadKaipanlaDailyOverview(kaipanlaOverviewDate?.value || ""));
kaipanlaValidateBtn?.addEventListener("click", validateKaipanlaIntegration);
kaipanlaSaveBtn?.addEventListener("click", saveKaipanlaScheduler);
kaipanlaRunBtn?.addEventListener("click", runKaipanlaNow);

async function initializeAdminPage() {
  try {
    const response = await fetch("/api/session");
    const payload = await readApiPayload(response, "读取会话失败");
    if (!payload.authenticated) {
      window.location.href = "/login";
      return;
    }
    const role = payload.role || "";
    const canViewDataConsole = dataConsolePage && role === "user";
    if (!["admin", "admin_readonly"].includes(role) && !canViewDataConsole) {
      window.location.href = "/";
      return;
    }
    adminReadonly = role === "admin_readonly";
    adminDataViewer = role === "user";
    applyDataViewerMode();
    applyAdminReadonlyMode();
    if (adminSummary || adminAuditTable || adminUsersTable) await loadAdminOverview();
    if (spiderStatus) {
      await refreshSpiderConsole();
      startSpiderPolling();
    }
    if (dailyMarketStatus) await refreshDailyMarketScheduler();
    if (idlePrefetchStatus) await refreshIdlePrefetchScheduler();
    if (kaipanlaOverviewSections) await loadKaipanlaDailyOverview();
    if (kaipanlaMeta || kaipanlaStateText) await loadKaipanlaFeatures();
    applyDataViewerMode();
    applyAdminReadonlyMode();
  } catch {
    window.location.href = "/login";
  }
}

async function loadAdminOverview() {
  if (adminSummary) adminSummary.textContent = adminAuditPage ? "正在读取审计日志..." : "正在读取账户和邀请码...";
  try {
    const response = await fetch("/api/admin/overview");
    const payload = await readApiPayload(response, "读取访问与安全失败");
    renderSystemApiKeys(payload.system_api_keys || {});
    renderAdminAgentTokens(payload.agent_tokens || []);
    renderAdminAgentAudit(payload.agent_audit_logs || []);
    const invites = payload.invites || [];
    if (adminSummary) {
      adminSummary.textContent = adminAuditPage ? "" : "用户与邀请码仅保留数据端账号；分析端额度能力已迁出。";
    }
    renderAdminUsers(payload.users || []);
    renderAdminInvites(invites);
    renderAdminAudit(payload.audit_logs || []);
    const tasks = await loadAdminTasks();
    if (agentGatewayStatus) agentGatewayStatus.textContent = AGENT_GATEWAY_AVAILABLE ? "v1" : "调试中";
    if (agentTokenActiveCount) agentTokenActiveCount.textContent = AGENT_GATEWAY_AVAILABLE ? String((payload.agent_tokens || []).filter((item) => item.status === "active").length) : "-";
    if (agentAuditCount) agentAuditCount.textContent = AGENT_GATEWAY_AVAILABLE ? String((payload.agent_audit_logs || []).length) : "-";
    if (adminUserCount) adminUserCount.textContent = String((payload.users || []).length);
    if (adminInviteCount) adminInviteCount.textContent = String(invites.filter((item) => item.status === "active").length);
    if (adminVipCodeCount) adminVipCodeCount.textContent = "-";
    if (adminDemoCount) adminDemoCount.textContent = "-";
    if (adminTaskCount) adminTaskCount.textContent = String(tasks?.length ?? 0);
  } catch (error) {
    if (adminSummary) adminSummary.textContent = `读取失败：${error.message}`;
  }
}

function renderSystemApiKeys(keys) {
  if (!systemDeepSeekStatus) return;
  const deepseek = keys.deepseek || {};
  systemDeepSeekStatus.textContent = deepseek.configured
    ? `已锁定${deepseek.updated_at ? ` · ${formatCompactTimestamp(deepseek.updated_at)}` : ""}`
    : "未配置";
  if (deleteSystemDeepSeekBtn) deleteSystemDeepSeekBtn.disabled = !deepseek.configured;
}

function renderAdminAgentTokens(tokens) {
  if (!adminAgentTokensTable) return;
  const rows = tokens.map((token) => `
    <tr>
      <td>${escapeHtml(token.name || "")}</td>
      <td><code>${escapeHtml(token.token_prefix || "")}</code></td>
      <td>${escapeHtml((token.scopes || []).join(","))}</td>
      <td>${escapeHtml(token.status || "")}</td>
      <td>${escapeHtml(formatCompactTimestamp(token.expires_at_text || "-"))}</td>
      <td>${escapeHtml(String(token.rate_limit_per_min || "-"))}</td>
      <td>${escapeHtml(formatCompactTimestamp(token.last_used_at || "-"))}</td>
      <td>
        <button type="button" data-agent-token-revoke="${escapeHtml(token.id || "")}" ${!AGENT_GATEWAY_AVAILABLE || token.status === "revoked" ? "disabled" : ""}>撤销</button>
      </td>
    </tr>
  `).join("");
  adminAgentTokensTable.innerHTML = `
    <thead><tr><th>名称</th><th>前缀</th><th>Scope</th><th>状态</th><th>过期</th><th>限速</th><th>最近使用</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="8">暂无 Agent token</td></tr>`}</tbody>
  `;
  adminAgentTokensTable.querySelectorAll("[data-agent-token-revoke]").forEach((button) => {
    button.addEventListener("click", () => revokeAgentToken(button.dataset.agentTokenRevoke));
  });
}

function renderAdminAgentAudit(logs) {
  if (!adminAgentAuditTable) return;
  const rows = logs.map((item) => `
    <tr>
      <td>${escapeHtml(formatCompactTimestamp(item.time || ""))}</td>
      <td><code>${escapeHtml(item.token_prefix || "-")}</code></td>
      <td>${escapeHtml(item.method || "")}</td>
      <td>${escapeHtml(item.route || "")}</td>
      <td>${escapeHtml(item.scope || "")}</td>
      <td>${escapeHtml(String(item.status_code || ""))}</td>
    </tr>
  `).join("");
  adminAgentAuditTable.innerHTML = `
    <thead><tr><th>时间</th><th>Token</th><th>方法</th><th>路径</th><th>Scope</th><th>状态</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6">暂无 Agent 调用</td></tr>`}</tbody>
  `;
}

async function revokeAgentToken(id) {
  if (!id) return;
  if (!AGENT_GATEWAY_AVAILABLE) {
    adminSummary.textContent = "Agent Gateway 正在调试中，暂不可用。";
    return;
  }
  if (!window.confirm("确定撤销这个 Agent token？撤销后使用该 token 的 MCP/Codex 调用会立即失败。")) return;
  adminSummary.textContent = "正在撤销 Agent token...";
  try {
    const response = await fetch("/api/admin/agent-token/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await readApiPayload(response, "撤销 Agent token 失败");
    await loadAdminOverview();
    adminSummary.textContent = "Agent token 已撤销。";
  } catch (error) {
    adminSummary.textContent = `撤销 Agent token 失败：${error.message}`;
  }
}

function renderAdminUsers(users) {
  if (!adminUsersTable) return;
  const rows = users.map((user) => {
    const protectedAccount = !!user.protected || user.role === "admin";
    const protectedAttr = protectedAccount ? "disabled title=\"最高管理员权限不可修改\"" : "";
    return `
      <tr>
        <td>${escapeHtml(user.username || "")}</td>
        <td>${escapeHtml(user.disabled ? "已禁用" : user.role || "")}</td>
        <td>${escapeHtml(user.disabled_until_text || "-")}</td>
        <td>${escapeHtml(String(user.usage_total || 0))}</td>
        <td>${escapeHtml(formatCompactTimestamp(user.last_request_at || "-"))}</td>
        <td>${escapeHtml(apiKeySummary(user.api_keys || {}))}</td>
        <td>${escapeHtml(user.invite_code || "-")}</td>
        <td>
          <div class="table-actions">
            <button type="button" data-user-action="${user.disabled ? "enable" : "disable"}" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>${user.disabled ? "启用" : "禁用"}</button>
            <button type="button" data-user-action="archive" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>归档</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
  adminUsersTable.innerHTML = `
    <thead><tr><th>账号</th><th>角色</th><th>封禁至</th><th>API 用量</th><th>最近请求</th><th>用户 Key</th><th>邀请码</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="8">暂无注册用户</td></tr>`}</tbody>
  `;
  adminUsersTable.querySelectorAll("[data-user-action]").forEach((button) => {
    button.addEventListener("click", () => runUserAction(button.dataset.username, button.dataset.userAction));
  });
}

function renderAdminInvites(invites) {
  if (!adminInvitesTable) return;
  const rows = invites.map((invite) => `
    <tr>
      <td><code>${escapeHtml(invite.code || "")}</code></td>
      <td>${inviteStatusLabel(invite.status)}</td>
      <td>${escapeHtml(formatCompactTimestamp(invite.expires_at_text || "-"))}</td>
      <td>${escapeHtml(invite.used_by || "-")}</td>
    </tr>
  `).join("");
  adminInvitesTable.innerHTML = `
    <thead><tr><th>邀请码</th><th>状态</th><th>过期时间</th><th>使用者</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="4">暂无邀请码</td></tr>`}</tbody>
  `;
}

async function runUserAction(username, action) {
  if (!username || !action) return;
  if (adminReadonly) {
    adminSummary.textContent = "只读展示模式不能修改账号。";
    return;
  }
  const payload = { username, action };
  if (action === "disable") {
    const rawDays = window.prompt("封禁天数（到期后自动解锁）", "30");
    if (rawDays === null) return;
    const days = Number(rawDays);
    if (!Number.isInteger(days) || days < 1 || days > 3650) {
      window.alert("请输入 1-3650 之间的整数天数。");
      return;
    }
    payload.days = days;
  }
  if (action === "archive") {
    const confirmed = window.confirm(`确认归档账号 ${username}？账号将不能登录，但历史数据会保存在归档区，不会物理删除。`);
    if (!confirmed) return;
    const reason = window.prompt("归档原因（可选）", "");
    if (reason === null) return;
    payload.reason = reason;
  }
  adminSummary.textContent = "正在更新用户权限...";
  try {
    const response = await fetch("/api/admin/user-access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await readApiPayload(response, "更新用户权限失败");
    await loadAdminOverview();
  } catch (error) {
    adminSummary.textContent = `更新用户权限失败：${error.message}`;
  }
}

function applyAdminReadonlyMode() {
  if (!adminReadonly) return;
  if (!document.querySelector(".admin-readonly-banner")) {
    const banner = document.createElement("div");
    banner.className = "admin-readonly-banner";
    banner.textContent = "只读展示模式：可以查看后台状态和数据，但所有调用、保存、生成、删除和调度操作都已禁用。";
    document.querySelector(".admin-workspace")?.prepend(banner);
  }
  document.querySelectorAll("button, input, select, textarea").forEach((node) => {
    if (node.id === "logoutBtn" || node.id === "themeToggleBtn") return;
    node.disabled = true;
  });
  if (adminSummary) adminSummary.textContent = "只读展示模式已启用。";
}

function applyDataViewerMode() {
  if (!adminDataViewer) return;
  document.querySelectorAll(".admin-nav a").forEach((link) => {
    const href = link.getAttribute("href") || "";
    if (!dataConsoleHrefs.has(href)) link.remove();
  });
  if (!document.querySelector(".admin-data-viewer-banner")) {
    const banner = document.createElement("div");
    banner.className = "admin-readonly-banner admin-data-viewer-banner";
    banner.textContent = "为保证抓取稳定，暂时冻结手动抓取功能。";
    document.querySelector(".admin-workspace")?.prepend(banner);
  }
  [
    startSpiderBtn,
    stopSpiderBtn,
    saveDailyMarketSchedulerBtn,
    runDailyMarketNowBtn,
    saveIdlePrefetchBtn,
    runIdlePrefetchNowBtn,
    kaipanlaValidateBtn,
    kaipanlaSaveBtn,
    kaipanlaRunBtn,
  ].forEach((node) => {
    if (!node) return;
    node.disabled = true;
    node.hidden = true;
  });
  [
    dailyMarketEnabled,
    dailyMarketTime,
    idlePrefetchEnabled,
    idlePrefetchSeconds,
    idlePrefetchRefreshDays,
    kaipanlaEnabled,
    kaipanlaTime,
  ].forEach((node) => {
    if (node) node.disabled = true;
  });
  document.querySelectorAll("[data-admin-operation-section]").forEach((node) => {
    node.hidden = true;
  });
}

async function loadAdminTasks() {
  if (!adminTasksTable) return;
  if (adminDataViewer) {
    adminTasksTable.innerHTML = `<tbody><tr><td>普通账号不展示后台任务历史。</td></tr></tbody>`;
    return [];
  }
  try {
    const response = await fetch("/api/admin/tasks");
    const payload = await readApiPayload(response, "读取后台任务失败");
    const items = payload.items || [];
    renderAdminTasks(items);
    return items;
  } catch (error) {
    adminTasksTable.innerHTML = `<tbody><tr><td>任务读取失败：${escapeHtml(error.message)}</td></tr></tbody>`;
    return [];
  }
}

function renderAdminTasks(tasks) {
  adminTaskItems = Array.isArray(tasks) ? tasks : [];
  if (selectedAdminTaskId && !adminTaskItems.some((task) => task.task_id === selectedAdminTaskId)) {
    selectedAdminTaskId = "";
  }
  if (!selectedAdminTaskId && adminTaskItems.length) {
    selectedAdminTaskId = adminTaskItems[0].task_id || "";
  }
  const rows = adminTaskItems.map((task) => `
      <tr class="${task.task_id === selectedAdminTaskId ? "selected" : ""}" data-admin-task-id="${escapeAttr(task.task_id || "")}">
        <td>${escapeHtml(taskKindLabel(task.kind))}</td>
        <td>${escapeHtml(taskTriggerLabel(task.metadata?.trigger))}</td>
        <td>${escapeHtml(task.title || "")}</td>
        <td>${taskStatusLabel(task.status)}</td>
        <td>${escapeHtml(formatCompactTimestamp(task.created_at || "-"))}</td>
        <td>${escapeHtml(formatCompactTimestamp(task.finished_at || "-"))}</td>
        <td>${escapeHtml(taskSummary(task))}</td>
      </tr>
    `).join("");
  adminTasksTable.innerHTML = `
    <thead><tr><th>类型</th><th>触发</th><th>任务</th><th>状态</th><th>开始</th><th>完成</th><th>摘要</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="7">暂无后台任务</td></tr>`}</tbody>
  `;
  adminTasksTable.querySelectorAll("[data-admin-task-id]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedAdminTaskId = row.dataset.adminTaskId || "";
      renderAdminTasks(adminTaskItems);
    });
  });
  renderSelectedAdminTaskDetail();
}

function taskKindLabel(kind) {
  return ({
    daily_market: "股票数据",
    idle_stock_prefetch: "空闲预抓",
    kaipanla: "行情数据",
    data_random_audit: "数据抽检",
    spider: "行情数据",
    multi_agent: "多 Agent",
    multi_agent_cache: "分析缓存",
  })[kind] || kind || "-";
}

function taskTriggerLabel(trigger) {
  if (trigger === "scheduled") return "定时";
  if (trigger === "manual") return "手动";
  return trigger || "手动";
}

function taskSummary(task) {
  if (task.error) return task.error;
  const result = task.result_summary || {};
  if (task.kind === "daily_market") {
    return `列表 ${result.stock_list_count ?? "-"} · 更新 ${result.updated ?? "-"} · 跳过 ${result.skipped ?? "-"} · 失败 ${result.failed ?? "-"}`;
  }
  if (task.kind === "kaipanla") {
    return `功能 ${result.total ?? "-"} · 成功 ${result.succeeded ?? "-"} · 失败 ${result.failed ?? "-"}`;
  }
  if (result.rating_hint) return result.rating_hint;
  const events = Array.isArray(task.events) ? task.events : [];
  return events.at(-1)?.message || "-";
}

function renderSelectedAdminTaskDetail() {
  if (!spiderLogs || !spiderLogFile) return;
  const task = adminTaskItems.find((item) => item.task_id === selectedAdminTaskId);
  if (!task) {
    spiderLogFile.textContent = "暂无任务事件";
    spiderLogs.textContent = "选择右侧任务查看执行事件。";
    return;
  }
  spiderLogFile.textContent = `${taskKindLabel(task.kind)} · ${taskStatusLabel(task.status)}`;
  spiderLogs.textContent = formatTaskDetail(task);
}

function formatTaskDetail(task) {
  const events = Array.isArray(task.events) ? task.events : [];
  const lines = [
    `${task.title || taskKindLabel(task.kind)} · ${taskStatusLabel(task.status)}`,
    `触发：${taskTriggerLabel(task.metadata?.trigger)} · 开始：${formatCompactTimestamp(task.created_at || "-")} · 完成：${formatCompactTimestamp(task.finished_at || "-")}`,
  ];
  const summary = taskSummary(task);
  if (summary && summary !== "-") lines.push(`摘要：${summary}`);
  if (task.error) lines.push(`错误：${task.error}`);
  lines.push("");
  lines.push("事件：");
  if (!events.length) {
    lines.push("暂无事件");
    return lines.join("\n");
  }
  events.forEach((event) => {
    lines.push(`${formatCompactTimestamp(event.time || "-")} · ${taskEventStageLabel(event.stage)} · ${event.message || "-"}`);
    const details = formatTaskEventDetails(event.details);
    if (details) lines.push(`  ${details}`);
  });
  return lines.join("\n");
}

function taskEventStageLabel(stage) {
  return ({
    queued: "已创建",
    running: "运行中",
    warning: "警告",
    succeeded: "成功",
    failed: "失败",
    stopped: "已停止",
    stopping: "停止中",
    cache: "缓存",
  })[stage] || stage || "进度";
}

function formatTaskEventDetails(details) {
  if (!details || typeof details !== "object" || Array.isArray(details)) return "";
  const entries = Object.entries(details).filter(([, value]) => value !== "" && value !== null && value !== undefined);
  if (!entries.length) return "";
  return entries
    .slice(0, 8)
    .map(([key, value]) => `${key}: ${formatTaskEventValue(value)}`)
    .join(" · ");
}

function formatTaskEventValue(value) {
  if (Array.isArray(value)) return value.join("、");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderAdminAudit(logs) {
  if (!adminAuditTable) return;
  const rows = logs.map((item) => `
    <tr>
      <td>${escapeHtml(item.time || "")}</td>
      <td>${escapeHtml(item.actor || "")}</td>
      <td>${escapeHtml(auditActionLabel(item.action))}</td>
      <td>${escapeHtml(item.target || "")}</td>
    </tr>
  `).join("");
  adminAuditTable.innerHTML = `
    <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>目标</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="4">暂无审计日志</td></tr>`}</tbody>
  `;
}

function startSpiderPolling() {
  if (spiderPollTimer) return;
  spiderPollTimer = window.setInterval(refreshSpiderConsole, 2500);
}

async function refreshSpiderConsole() {
  try {
    const statusResponse = await fetch("/api/admin/market-fetch/status");
    const statusPayload = await readApiPayload(statusResponse, "读取爬虫状态失败");
    renderSpiderStatus(statusPayload);
    const logsSource = getSelectedSpiderSource();
    const logsResponse = await fetch(`/api/admin/market-fetch/logs?lines=160&source=${encodeURIComponent(logsSource)}`);
    const logsPayload = await readApiPayload(logsResponse, "读取爬虫日志失败");
    if (!selectedAdminTaskId) {
      spiderLogs.textContent = logsPayload.content || statusPayload.spider?.error || "暂无日志";
      if (spiderLogFile) spiderLogFile.textContent = logsPayload.log_file ? basename(logsPayload.log_file) : "暂无日志文件";
    }
    await refreshDailyMarketScheduler();
    await refreshIdlePrefetchScheduler();
    await loadAdminTasks();
    applyDataViewerMode();
  } catch (error) {
    spiderStatus.textContent = `爬虫状态读取失败：${error.message}`;
  }
}

async function refreshDailyMarketScheduler() {
  if (!dailyMarketStatus) return;
  try {
    const response = await fetch("/api/admin/daily-market-scheduler");
    const payload = await readApiPayload(response, "读取每日股票数据定时失败");
    renderDailyMarketScheduler(payload.scheduler || {});
  } catch (error) {
    dailyMarketStatus.textContent = `读取失败：${error.message}`;
  }
}

async function refreshIdlePrefetchScheduler() {
  if (!idlePrefetchStatus) return;
  try {
    const response = await fetch("/api/admin/idle-stock-prefetch");
    const payload = await readApiPayload(response, "读取空闲预抓状态失败");
    renderIdlePrefetchScheduler(payload.scheduler || {});
  } catch (error) {
    idlePrefetchStatus.textContent = `读取失败：${error.message}`;
  }
}

function renderDailyMarketScheduler(scheduler) {
  if (!dailyMarketStatus) return;
  if (dailyMarketEnabled) dailyMarketEnabled.checked = !!scheduler.enabled;
  if (dailyMarketTime) dailyMarketTime.value = scheduler.time || "21:30";
  const last = scheduler.last_result || {};
  const running = !!scheduler.running;
  dailyMarketStatus.textContent = running
    ? "运行中"
    : scheduler.enabled
      ? `已启用 · ${scheduler.time || "21:30"}`
      : "未启用";
  if (dailyMarketStockCount) dailyMarketStockCount.textContent = String(scheduler.stock_count ?? "-");
  if (dailyStockListCount) dailyStockListCount.textContent = String(scheduler.stock_list_count ?? "-");
  if (dailyMarketLastDate) dailyMarketLastDate.textContent = formatCompactDate(scheduler.last_run_date || "-");
  if (dailyMarketUpdated) dailyMarketUpdated.textContent = String(last.updated ?? "-");
  if (dailyMarketSkipped) dailyMarketSkipped.textContent = String(last.skipped ?? "-");
  if (runDailyMarketNowBtn) runDailyMarketNowBtn.disabled = running;
}

function renderIdlePrefetchScheduler(scheduler) {
  if (!idlePrefetchStatus) return;
  if (idlePrefetchEnabled) idlePrefetchEnabled.checked = !!scheduler.enabled;
  if (idlePrefetchSeconds) idlePrefetchSeconds.value = scheduler.idle_seconds || 1800;
  if (idlePrefetchRefreshDays) idlePrefetchRefreshDays.value = scheduler.refresh_existing_days ?? 14;
  const running = !!scheduler.running;
  idlePrefetchStatus.textContent = running
    ? "运行中"
    : scheduler.enabled
      ? `已启用 · 空闲 ${formatDuration(scheduler.idle_seconds || 1800)} · ${scheduler.refresh_existing_days ?? 14} 天刷新已有资料包`
      : "未启用";
  if (idlePrefetchRemaining) idlePrefetchRemaining.textContent = scheduler.remaining_seconds ? formatDuration(scheduler.remaining_seconds) : "可触发";
  if (idlePrefetchLastRequest) {
    const code = scheduler.last_request_code ? ` · ${scheduler.last_request_code}` : "";
    idlePrefetchLastRequest.textContent = scheduler.last_request_at ? `${formatCompactTimestamp(scheduler.last_request_at)}${code}` : "-";
  }
  const last = scheduler.last_result || {};
  if (idlePrefetchLastResult) {
    idlePrefetchLastResult.textContent = last.ts_code
      ? `${last.ts_code}${last.name ? ` ${last.name}` : ""} · ${last.reason === "stale_package" ? "刷新已有资料包" : "全量历史"}`
      : (last.reason === "no_unfetched_stock" ? "没有待预抓股票" : (scheduler.last_error || "-"));
  }
  if (runIdlePrefetchNowBtn) runIdlePrefetchNowBtn.disabled = running;
}

async function loadKaipanlaDailyOverview(date = "") {
  if (!kaipanlaOverviewSections) return;
  if (kaipanlaOverviewRefreshBtn) kaipanlaOverviewRefreshBtn.disabled = true;
  if (kaipanlaOverviewMeta) kaipanlaOverviewMeta.textContent = "正在读取每日市场纵览...";
  try {
    const query = date ? `?date=${encodeURIComponent(date)}` : "";
    const response = await fetch(`/api/admin/kaipanla/daily-overview${query}`);
    const payload = await readApiPayload(response, "读取开盘啦每日纵览失败");
    renderKaipanlaDailyOverview(payload.overview || {});
  } catch (error) {
    if (kaipanlaOverviewMeta) kaipanlaOverviewMeta.textContent = `读取失败：${error.message}`;
    if (kaipanlaOverviewKpis) kaipanlaOverviewKpis.innerHTML = "";
    kaipanlaOverviewSections.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  } finally {
    if (kaipanlaOverviewRefreshBtn) kaipanlaOverviewRefreshBtn.disabled = false;
  }
}

function renderKaipanlaDailyOverview(overview) {
  const coverage = overview.coverage || {};
  if (kaipanlaOverviewDate && overview.display_date) kaipanlaOverviewDate.value = overview.display_date;
  if (kaipanlaOverviewMeta) {
    const displayDate = formatCompactDate(overview.display_date || overview.date || "");
    const saved = overview.latest_saved_at ? ` · 最近保存 ${formatCompactTimestamp(overview.latest_saved_at)}` : "";
    const fallback = overview.fallback && overview.requested_display_date
      ? ` · ${formatCompactDate(overview.requested_display_date)} 未更新，展示上一交易日`
      : "";
    kaipanlaOverviewMeta.textContent = `${displayDate || "最近交易日"} · 已采 ${coverage.collected_features || 0}/${coverage.total_features || 0} 个功能${fallback}${saved}`;
  }
  if (kaipanlaOverviewKpis) {
    const kpis = [
      { label: "采集覆盖", value: `${coverage.collected_features || 0}/${coverage.total_features || 0}`, hint: `成功 ${coverage.succeeded || 0} · 失败 ${coverage.failed || 0}` },
      ...(overview.kpis || []),
    ];
    kaipanlaOverviewKpis.innerHTML = kpis.map((item) => `
      <article>
        <span>${escapeHtml(item.label || "")}</span>
        <strong>${escapeHtml(formatKaipanlaKpiValue(item))}</strong>
        <small>${escapeHtml(item.hint || "")}</small>
      </article>
    `).join("");
  }
  const sections = [
    ["temperature", "市场温度", "涨跌停、百日新高和回撤"],
    ["limit_up", "连板梯队", "短线高度、题材和反包"],
    ["sectors", "板块强弱", "板块排行、强度、资金和竞价异动"],
    ["capital", "龙虎榜", "上榜股票与席位资金"],
    ["etf", "ETF", "ETF 排行和风险偏好"],
    ["intraday", "盘中监控", "实时情绪、涨跌分析和回撤"],
  ];
  kaipanlaOverviewSections.innerHTML = sections.map(([key, title, subtitle]) => {
    const items = overview.sections?.[key] || [];
    return `
      <section class="kaipanla-overview-section-card">
        <div class="kaipanla-overview-section-head">
          <div><h5>${escapeHtml(title)}</h5><p>${escapeHtml(subtitle)}</p></div>
          <span>${escapeHtml(String(items.length))} 个数据集</span>
        </div>
        ${items.length ? items.map(renderKaipanlaOverviewFeature).join("") : `<div class="news-empty compact">当天暂无这类数据。</div>`}
      </section>
    `;
  }).join("");
}

function formatKaipanlaKpiValue(item) {
  if (!item || item.status === "missing" || item.value === "-" || item.value === null || item.value === undefined || item.value === "") {
    return "暂无";
  }
  return String(item.value);
}

function renderKaipanlaOverviewFeature(item) {
  return `
    <article class="kaipanla-overview-feature">
      <div class="kaipanla-overview-feature-head">
        <div><strong>${escapeHtml(item.label || item.feature || "")}</strong><small>${escapeHtml(item.category || "")} · ${escapeHtml(formatCompactTimestamp(item.saved_at || ""))}</small></div>
        <span class="${item.ok ? "is-ok" : "is-failed"}">${item.ok ? "成功" : "失败"}</span>
      </div>
      <p>${escapeHtml(item.summary || "无摘要")}</p>
      ${renderKaipanlaOverviewRows(item.rows || [], item.item_count || 0, item.feature || "")}
    </article>
  `;
}

function renderKaipanlaOverviewRows(rows, totalCount = 0, feature = "") {
  if (!rows.length) return "";
  const columns = overviewColumns(rows, feature);
  if (!columns.length) return "";
  const previewRows = rows.slice(0, 5);
  const total = Math.max(Number(totalCount) || 0, rows.length);
  return `
    <div class="kaipanla-overview-table">
      <table>
        <thead><tr>${columns.map((key) => `<th>${escapeHtml(key)}</th>`).join("")}</tr></thead>
        <tbody>${previewRows.map((row) => `
          <tr>${columns.map((key) => `<td>${escapeHtml(formatOverviewCell(row[key]))}</td>`).join("")}</tr>
        `).join("")}</tbody>
      </table>
      <small>预览 ${previewRows.length} / 共 ${total} 条</small>
    </div>
  `;
}

function overviewColumns(rows, feature = "") {
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row || {})))];
  const featureColumns = {
    sector_ranking: ["股票代码", "股票名称", "首次封板时间", "连板天数", "涨停原因"],
    market_limit_up_ladder: ["stock_code", "stock_name", "timestamp", "consecutive_days", "limit_up_reason"],
    sector_limit_up_ladder: ["stock_code", "stock_name", "timestamp", "consecutive_days", "limit_up_reason"],
    consecutive_limit_up: ["stock_code", "stock_name", "consecutive_days", "concepts", "limit_up_reason"],
    longhubang_dataframe: ["stock_code", "stock_name", "change_pct", "buy_amount", "turnover"],
    longhubang_stock_list: ["stock_code", "stock_name", "change_pct", "buy_amount", "turnover"],
    all_etf_ranking: ["ETF代码", "ETF名称", "涨跌幅(%)", "成交额", "量比"],
    etf_ranking: ["ETF代码", "ETF名称", "涨跌幅(%)", "成交额", "量比"],
  };
  const defaults = [
    "股票代码",
    "stock_code",
    "股票名称",
    "stock_name",
    "日期",
    "date",
    "指标",
    "值",
    "limit_up_reason",
    "涨停原因",
    "change_pct",
    "buy_amount",
    "ETF代码",
    "ETF名称",
    "涨跌幅(%)",
    "成交额",
  ];
  const preferred = [...(featureColumns[feature] || []), ...defaults];
  const columns = preferred.filter((key, index) => keys.includes(key) && preferred.indexOf(key) === index);
  columns.push(...keys.filter((key) => !columns.includes(key) && key !== "reason_type"));
  return columns.slice(0, 5);
}

function formatOverviewCell(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  const text = String(value);
  if (/^\d{8}$/.test(text) || /^\d{4}-\d{1,2}-\d{1,2}$/.test(text)) return formatCompactDate(text);
  if (/^\d{8}[_-]\d{4}/.test(text) || /^\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}/.test(text)) return formatCompactTimestamp(text);
  return text;
}

async function loadKaipanlaFeatures() {
  if (!kaipanlaMeta && !kaipanlaStateText) return;
  if (kaipanlaMeta) kaipanlaMeta.textContent = "正在读取开盘啦配置...";
  try {
    const [featuresResponse, schedulerResponse] = await Promise.all([
      fetch("/api/admin/kaipanla/features"),
      fetch("/api/admin/kaipanla/scheduler"),
    ]);
    const featuresPayload = await readApiPayload(featuresResponse, "读取开盘啦功能失败");
    const schedulerPayload = await readApiPayload(schedulerResponse, "读取开盘啦定时失败");
    kaipanlaState.features = featuresPayload.items || [];
    renderKaipanlaScheduler(schedulerPayload.scheduler || {});
    if (kaipanlaMeta) kaipanlaMeta.textContent = `${kaipanlaState.features.length} 个功能 · 行情数据`;
  } catch (error) {
    if (kaipanlaMeta) kaipanlaMeta.textContent = `读取失败：${error.message}`;
  }
}

function renderKaipanlaScheduler(scheduler) {
  kaipanlaState.scheduler = scheduler || {};
  const running = !!scheduler.running;
  if (kaipanlaEnabled) kaipanlaEnabled.value = scheduler.enabled ? "1" : "0";
  if (kaipanlaTime) kaipanlaTime.value = scheduler.time || "21:45";
  if (kaipanlaStateText) kaipanlaStateText.textContent = running ? "运行中" : scheduler.enabled ? "已启用" : "未启用";
  if (kaipanlaTimeText) kaipanlaTimeText.textContent = scheduler.time || "21:45";
  if (kaipanlaFeatureCount) kaipanlaFeatureCount.textContent = String((scheduler.features || []).length);
  if (kaipanlaLastDate) kaipanlaLastDate.textContent = formatCompactDate(scheduler.last_run_date || "-");
  const last = scheduler.last_result || {};
  if (kaipanlaLastResult) kaipanlaLastResult.textContent = last.total ? `${last.succeeded || 0} / ${last.failed || 0}` : "-";
  if (kaipanlaRunBtn) kaipanlaRunBtn.disabled = running;
}

async function validateKaipanlaIntegration() {
  if (!kaipanlaValidateBtn) return;
  kaipanlaValidateBtn.disabled = true;
  if (kaipanlaMeta) kaipanlaMeta.textContent = "正在验证开盘啦功能映射...";
  try {
    const response = await fetch("/api/admin/kaipanla/validate");
    const payload = await readApiPayload(response, "验证开盘啦功能失败");
    const valid = payload.ok === false ? "验证失败" : "验证通过";
    if (kaipanlaMeta) kaipanlaMeta.textContent = `${valid} · ${kaipanlaState.features.length || 0} 个功能`;
  } catch (error) {
    if (kaipanlaMeta) kaipanlaMeta.textContent = `验证失败：${error.message}`;
  } finally {
    kaipanlaValidateBtn.disabled = adminReadonly;
  }
}

function kaipanlaSchedulerPayload() {
  return {
    action: "save",
    enabled: kaipanlaEnabled?.value === "1",
    time: kaipanlaTime?.value || "21:45",
    features: kaipanlaState.scheduler.features || [],
    params_by_feature: kaipanlaState.scheduler.params_by_feature || {},
  };
}

async function saveKaipanlaScheduler() {
  if (!kaipanlaSaveBtn) return false;
  kaipanlaSaveBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/kaipanla/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(kaipanlaSchedulerPayload()),
    });
    const payload = await readApiPayload(response, "保存开盘啦定时失败");
    renderKaipanlaScheduler(payload.scheduler || {});
    if (kaipanlaMeta) kaipanlaMeta.textContent = "开盘啦行情数据定时配置已保存。";
    return true;
  } catch (error) {
    if (kaipanlaMeta) kaipanlaMeta.textContent = `保存失败：${error.message}`;
    return false;
  } finally {
    kaipanlaSaveBtn.disabled = adminReadonly;
  }
}

async function runKaipanlaNow() {
  if (!kaipanlaRunBtn || !approveDataFetch("立即执行开盘啦行情数据抓取")) return;
  kaipanlaRunBtn.disabled = true;
  if (kaipanlaMeta) kaipanlaMeta.textContent = "正在启动开盘啦行情数据任务...";
  try {
    if (!(await saveKaipanlaScheduler())) return;
    const response = await fetch("/api/admin/kaipanla/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now", approved: true }),
    });
    const payload = await readApiPayload(response, "启动开盘啦抓取失败");
    renderKaipanlaScheduler(payload.scheduler || {});
    if (kaipanlaMeta) kaipanlaMeta.textContent = "开盘啦行情数据任务已启动。";
    window.setTimeout(loadKaipanlaFeatures, 2500);
  } catch (error) {
    if (kaipanlaMeta) kaipanlaMeta.textContent = `启动失败：${error.message}`;
  } finally {
    kaipanlaRunBtn.disabled = adminReadonly;
  }
}

function renderSpiderStatus(payload) {
  const spider = payload.spider || {};
  renderSpiderSources(payload.available_sources || []);
  renderSpiderTypes(payload.available_types || []);
  renderSpiderTaskCards(payload.spider_list || []);
  const selectedSource = getSelectedSpiderSource();
  const selectedSpider = payload.spiders?.[selectedSource] || spider;
  const status = selectedSpider.status || "idle";
  const running = status === "running" || status === "stopping";
  const sourceDisabled = !!spiderSourcesSelect?.querySelector("input[type='radio']:checked")?.disabled;
  startSpiderBtn.disabled = running || sourceDisabled;
  stopSpiderBtn.disabled = !running;
  const sourceText = selectedSpider.source_label || sourceLabel(selectedSpider.source) || "-";
  const typeText = selectedSpider.stock_code || (Array.isArray(selectedSpider.types) && selectedSpider.types.length ? selectedSpider.types.join("、") : "-");
  const modeText = "写入 MongoDB";
  const pages = selectedSpider.max_pages ? `${selectedSpider.max_pages} 页` : "-";
  const errorText = selectedSpider.error ? `；错误：${selectedSpider.error}` : "";
  const returnText = Number.isInteger(selectedSpider.returncode) ? `；退出码：${selectedSpider.returncode}` : "";
  spiderStatus.textContent = `状态：${spiderStatusLabel(status)}；来源：${sourceText}；分类：${typeText}；模式：${modeText}；页数/批量：${pages}${returnText}${errorText}`;
  if (spiderStateText) spiderStateText.textContent = spiderStatusLabel(status);
  if (spiderModeText) spiderModeText.textContent = modeText;
  if (spiderSourceText) spiderSourceText.textContent = sourceText;
  if (spiderTypeText) spiderTypeText.textContent = typeText;
  if (spiderPagesText) spiderPagesText.textContent = pages;
}

function renderSpiderTaskCards(items) {
  if (!spiderSourceTasks) return;
  spiderSourceTasks.innerHTML = (items || [])
    .map((item) => {
      const running = item.status === "running" || item.status === "stopping";
      const detail = item.source === "ths" && Array.isArray(item.types) && item.types.length ? item.types.join("、") : sourceHint(item.source);
      return `
        <button class="spider-task-card ${running ? "running" : ""}" type="button" data-spider-source="${escapeHtml(item.source || "")}">
          <span>${escapeHtml(item.source_label || sourceLabel(item.source))}</span>
          <strong>${escapeHtml(spiderStatusLabel(item.status || "idle"))}</strong>
          <small>${escapeHtml(detail || "-")}</small>
        </button>
      `;
    })
    .join("");
  spiderSourceTasks.querySelectorAll("[data-spider-source]").forEach((button) => {
    button.addEventListener("click", () => selectSpiderSource(button.dataset.spiderSource));
  });
  updateSelectedTaskCard();
}

function renderSpiderSources(sources) {
  if (!spiderSourcesSelect || spiderSourcesSelect.children.length || !sources.length) return;
  spiderSourcesSelect.innerHTML = sources
    .map(
      (source, index) => `
        <label class="spider-source-option ${source.disabled ? "disabled" : ""}">
          <input type="radio" name="spiderSource" value="${escapeHtml(source.id)}" ${index === 0 && !source.disabled ? "checked" : ""} ${source.disabled ? "disabled" : ""} />
          <span data-mark="${escapeHtml(sourceMark(source.id))}">
            <strong>${escapeHtml(source.name || source.id)}</strong>
            <small>${escapeHtml(source.disabled ? source.disabled_reason || "暂时关闭" : source.description || "")}</small>
          </span>
        </label>
      `
    )
    .join("");
  spiderSourcesSelect.querySelectorAll("input[type='radio']").forEach((input) => {
    input.addEventListener("change", updateSpiderSourceControls);
  });
  updateSpiderSourceControls();
}

function updateSpiderSourceControls() {
  const source = getSelectedSpiderSource();
  const isThs = source === "ths";
  const isThsMarket = source === "ths_market";
  const categoryField = spiderTypesSelect?.closest("label");
  if (categoryField) categoryField.hidden = !isThs;
  if (spiderThreads) spiderThreads.closest("label").hidden = !isThs;
  if (spiderPageSleep) spiderPageSleep.closest("label").hidden = !isThs;
  if (spiderNewOnly) spiderNewOnly.closest("label").hidden = !isThs;
  if (spiderStockCodeField) spiderStockCodeField.hidden = !isThsMarket;
  if (spiderMaxPages) {
    const label = spiderMaxPages.closest("label")?.querySelector("span");
    if (label) label.textContent = "页数";
    spiderMaxPages.max = "50";
    if (source === "bloomberg_urls" || isThsMarket) spiderMaxPages.closest("label").hidden = true;
    else spiderMaxPages.closest("label").hidden = false;
  }
  if (spiderArticleSleep) {
    const label = spiderArticleSleep.closest("label")?.querySelector("span");
    if (label) label.textContent = "文章间隔";
    spiderArticleSleep.closest("label").hidden = source === "guardian" || source === "bloomberg_urls" || isThsMarket;
  }
  const disabled = !!spiderSourcesSelect?.querySelector("input[type='radio']:checked")?.disabled;
  if (startSpiderBtn) startSpiderBtn.disabled = disabled;
  const hints = {
    ths: "多分类 · 增量 · MongoDB",
    ths_market: "指定股票 · 分钟行情 · MongoDB + 本地资料包",
    guardian: "API · 页数范围 · MongoDB",
    bloomberg_urls: "暂时关闭 · 等待稳定性优化",
    bloomberg_articles: "暂时关闭 · 等待稳定性优化",
  };
  if (spiderSourceHint) spiderSourceHint.textContent = hints[source] || "";
}

function getSelectedSpiderSource() {
  return spiderSourcesSelect?.querySelector("input[type='radio']:checked")?.value || "ths";
}

async function searchMarketStocks() {
  if (!spiderStockCode || !spiderStockSuggestions) return;
  const query = spiderStockCode.value.trim();
  if (!query) {
    hideMarketStockSuggestions();
    return;
  }
  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const payload = await readApiPayload(response, "股票检索失败");
    renderMarketStockSuggestions(payload.items || []);
  } catch (error) {
    spiderStockSuggestions.hidden = false;
    spiderStockSuggestions.innerHTML = `<div class="market-stock-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderMarketStockSuggestions(items) {
  if (!spiderStockSuggestions) return;
  const rows = items.slice(0, 12);
  spiderStockSuggestions.hidden = false;
  spiderStockSuggestions.innerHTML = rows.length
    ? rows.map((item) => `
        <button type="button" class="market-stock-option" data-ts-code="${escapeHtml(item.ts_code || "")}" data-name="${escapeHtml(item.name || "")}">
          <span><strong>${escapeHtml(item.name || "-")}</strong><small>${escapeHtml([item.industry, item.market].filter(Boolean).join(" · ") || "A 股")}</small></span>
          <code>${escapeHtml(item.ts_code || item.symbol || "-")}</code>
        </button>
      `).join("")
    : `<div class="market-stock-empty">没有匹配股票，请尝试代码、名称、全拼或首字母缩写。</div>`;
  spiderStockSuggestions.querySelectorAll("[data-ts-code]").forEach((button) => {
    button.addEventListener("click", () => selectMarketStock(button.dataset.tsCode, button.dataset.name));
  });
}

function selectMarketStock(tsCode, name) {
  if (!tsCode) return;
  spiderStockTsCode.value = tsCode;
  spiderStockCode.value = `${name || ""} ${tsCode}`.trim();
  spiderStockSelection.textContent = `已选择：${name || "-"} · ${tsCode}`;
  hideMarketStockSuggestions();
}

function selectedMarketStockCode() {
  const selected = spiderStockTsCode?.value || "";
  if (!selected) throw new Error("请先从检索结果中选择一只股票。");
  return selected;
}

function hideMarketStockSuggestions() {
  if (!spiderStockSuggestions) return;
  spiderStockSuggestions.hidden = true;
  spiderStockSuggestions.innerHTML = "";
}

function selectSpiderSource(source) {
  const radio = spiderSourcesSelect?.querySelector(`input[value="${cssEscape(source)}"]`);
  if (!radio) return;
  radio.checked = true;
  updateSpiderSourceControls();
  updateSelectedTaskCard();
  refreshSpiderConsole();
}

function updateSelectedTaskCard() {
  const source = getSelectedSpiderSource();
  spiderSourceTasks?.querySelectorAll("[data-spider-source]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.spiderSource === source);
  });
}

function renderSpiderTypes(types) {
  if (!spiderTypesSelect || spiderTypesSelect.children.length || !types.length) return;
  spiderTypesSelect.innerHTML = types
    .map(
      (type, index) => `
        <label class="spider-type-option">
          <input type="checkbox" value="${escapeHtml(type)}" ${index === 0 ? "checked" : ""} />
          <span>${escapeHtml(type)}</span>
        </label>
      `
    )
    .join("");
}

function sourceLabel(source) {
  const labels = {
    ths_market: "分钟行情",
  };
  return labels[source] || source || "";
}

function sourceHint(source) {
  const hints = {
    ths_market: "指定股票行情补抓",
  };
  return hints[source] || "";
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value || "");
  return String(value || "").replace(/"/g, '\\"');
}

function sourceMark(source) {
  const marks = {
    ths: "TH",
    ths_market: "HQ",
    guardian: "GD",
    bloomberg_urls: "BU",
    bloomberg_articles: "BA",
  };
  return marks[source] || "DS";
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

function inviteStatusLabel(status) {
  if (status === "active") return "可用";
  if (status === "used") return "已使用";
  if (status === "expired") return "已过期";
  return status || "-";
}

function spiderStatusLabel(status) {
  if (status === "idle") return "空闲";
  if (status === "running") return "运行中";
  if (status === "stopping") return "停止中";
  if (status === "stopped") return "已停止";
  if (status === "succeeded") return "已完成";
  if (status === "failed") return "失败";
  return status || "-";
}

function taskStatusLabel(status) {
  if (status === "queued") return "等待中";
  if (status === "running") return "运行中";
  if (status === "stopping") return "停止中";
  if (status === "stopped") return "已停止";
  if (status === "succeeded") return "成功";
  if (status === "failed") return "失败";
  return status || "-";
}

function auditActionLabel(action) {
  return ({
    grant_vip: "发放分析授权",
    revoke_vip: "撤销分析授权",
    disable_user: "禁用用户",
    enable_user: "启用用户",
    archive_user: "归档用户",
    archive_demo_account: "归档临时账号",
    reset_demo_budget: "重置临时额度",
  })[action] || action || "-";
}

function formatDuration(seconds) {
  if (!seconds) return "-";
  if (seconds % 86400 === 0) return `${seconds / 86400} 天`;
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  return `${seconds} 秒`;
}

function formatCompactTimestamp(value) {
  const text = String(value || "").trim();
  if (!text || text === "-") return "-";
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})/);
  if (compact) {
    const [, , month, day, hour, minute] = compact;
    return `${Number(month)}月${Number(day)}日${hour}:${minute}`;
  }
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

function formatCompactDate(value) {
  const text = String(value || "").trim();
  if (!text || text === "-") return "-";
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compact) return `${Number(compact[2])}月${Number(compact[3])}日`;
  const plain = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (plain) return `${Number(plain[2])}月${Number(plain[3])}日`;
  return text;
}

function apiKeySummary(keys) {
  const names = [];
  if (keys.tushare?.configured) names.push("Tushare");
  if (keys.deepseek?.configured) names.push("DeepSeek");
  return names.length ? names.join(" / ") : "-";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

function basename(path) {
  return String(path || "").split("/").filter(Boolean).pop() || "";
}
