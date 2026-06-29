const themeToggleBtn = document.querySelector("#themeToggleBtn");
const logoutBtn = document.querySelector("#logoutBtn");
const createInviteBtn = document.querySelector("#createInviteBtn");
const createDemoAccountBtn = document.querySelector("#createDemoAccountBtn");
const createVipCodeBtn = document.querySelector("#createVipCodeBtn");
const vipCodeDaysInput = document.querySelector("#vipCodeDaysInput");
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
const adminVipCodesTable = document.querySelector("#adminVipCodesTable");
const adminDemoAccountsTable = document.querySelector("#adminDemoAccountsTable");
const adminTasksTable = document.querySelector("#adminTasksTable");
const adminAuditTable = document.querySelector("#adminAuditTable");
const adminUserCount = document.querySelector("#adminUserCount");
const adminInviteCount = document.querySelector("#adminInviteCount");
const adminVipCodeCount = document.querySelector("#adminVipCodeCount");
const adminDemoCount = document.querySelector("#adminDemoCount");
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
const saveIdlePrefetchBtn = document.querySelector("#saveIdlePrefetchBtn");
const runIdlePrefetchNowBtn = document.querySelector("#runIdlePrefetchNowBtn");
const idlePrefetchIdle = document.querySelector("#idlePrefetchIdle");
const idlePrefetchRemaining = document.querySelector("#idlePrefetchRemaining");
const idlePrefetchLastRequest = document.querySelector("#idlePrefetchLastRequest");
const idlePrefetchLastRun = document.querySelector("#idlePrefetchLastRun");
const idlePrefetchLastResult = document.querySelector("#idlePrefetchLastResult");
const kaipanlaMeta = document.querySelector("#kaipanlaMeta");
const kaipanlaFeatureSelect = document.querySelector("#kaipanlaFeatureSelect");
const kaipanlaFeatureGrid = document.querySelector("#kaipanlaFeatureGrid");
const kaipanlaParamsInput = document.querySelector("#kaipanlaParamsInput");
const kaipanlaValidateBtn = document.querySelector("#kaipanlaValidateBtn");
const kaipanlaSaveBtn = document.querySelector("#kaipanlaSaveBtn");
const kaipanlaRunBtn = document.querySelector("#kaipanlaRunBtn");
const kaipanlaOutput = document.querySelector("#kaipanlaOutput");
const kaipanlaEnabled = document.querySelector("#kaipanlaEnabled");
const kaipanlaTime = document.querySelector("#kaipanlaTime");
const kaipanlaStateText = document.querySelector("#kaipanlaStateText");
const kaipanlaTimeText = document.querySelector("#kaipanlaTimeText");
const kaipanlaFeatureCount = document.querySelector("#kaipanlaFeatureCount");
const kaipanlaLastDate = document.querySelector("#kaipanlaLastDate");
const kaipanlaLastResult = document.querySelector("#kaipanlaLastResult");
const kaipanlaRecordsTable = document.querySelector("#kaipanlaRecordsTable");

let spiderPollTimer = null;
let spiderStockSearchTimer = null;
let adminReadonly = false;
const kaipanlaState = {
  features: [],
  scheduler: {},
  paramsByFeature: {},
  currentParamFeature: "",
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

createDemoAccountBtn?.addEventListener("click", async () => {
  createDemoAccountBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/demo-account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 1 }),
    });
    const payload = await readApiPayload(response, "生成测试账号失败");
    const account = payload.items?.[0];
    await loadAdminOverview();
    if (account) {
      adminSummary.textContent = `测试账号已生成：${account.username} / ${account.password}`;
    }
  } catch (error) {
    adminSummary.textContent = `生成测试账号失败：${error.message}`;
  } finally {
    createDemoAccountBtn.disabled = false;
  }
});

createVipCodeBtn?.addEventListener("click", async () => {
  createVipCodeBtn.disabled = true;
  try {
    const response = await fetch("/api/admin/vip-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 1, days: Number(vipCodeDaysInput?.value || 30) }),
    });
    const payload = await readApiPayload(response, "生成 VIP 兑换码失败");
    const item = payload.items?.[0];
    await loadAdminOverview();
    if (item) {
      adminSummary.textContent = `VIP 兑换码已生成：${item.code}，兑换后有效 ${item.vip_days} 天。`;
    }
  } catch (error) {
    adminSummary.textContent = `生成 VIP 兑换码失败：${error.message}`;
  } finally {
    createVipCodeBtn.disabled = false;
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
  if (!window.confirm("确定移除系统 DeepSeek key？系统/VIP 分析会暂停使用全局模型额度。")) return;
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

kaipanlaFeatureSelect?.addEventListener("change", syncKaipanlaParams);
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
    if (!["admin", "admin_readonly"].includes(payload.role)) {
      window.location.href = "/";
      return;
    }
    adminReadonly = payload.role === "admin_readonly";
    applyAdminReadonlyMode();
    if (adminSummary) await loadAdminOverview();
    if (spiderStatus) {
      await refreshSpiderConsole();
      startSpiderPolling();
    }
    if (dailyMarketStatus) await refreshDailyMarketScheduler();
    if (idlePrefetchStatus) await refreshIdlePrefetchScheduler();
    if (kaipanlaFeatureSelect) await loadKaipanlaFeatures();
    applyAdminReadonlyMode();
  } catch {
    window.location.href = "/login";
  }
}

async function loadAdminOverview() {
  adminSummary.textContent = "正在读取账户和邀请码...";
  try {
    const response = await fetch("/api/admin/overview");
    const payload = await readApiPayload(response, "读取账户管理失败");
    const demo = payload.demo || {};
    renderSystemApiKeys(payload.system_api_keys || {});
    renderAdminAgentTokens(payload.agent_tokens || []);
    renderAdminAgentAudit(payload.agent_audit_logs || []);
    const invites = payload.invites || [];
    const vipCodes = payload.vip_codes || [];
    const demoAccounts = payload.demo_accounts || [];
    adminSummary.textContent = `新测试账号默认额度：${demo.limit ?? "-"} 次 / ${formatDuration(demo.window_seconds || 0)}。`;
    renderAdminUsers(payload.users || []);
    renderAdminInvites(invites);
    renderAdminVipCodes(vipCodes);
    renderAdminDemoAccounts(demoAccounts);
    renderAdminAudit(payload.audit_logs || []);
    await loadAdminTasks();
    if (agentGatewayStatus) agentGatewayStatus.textContent = AGENT_GATEWAY_AVAILABLE ? "v1" : "调试中";
    if (agentTokenActiveCount) agentTokenActiveCount.textContent = AGENT_GATEWAY_AVAILABLE ? String((payload.agent_tokens || []).filter((item) => item.status === "active").length) : "-";
    if (agentAuditCount) agentAuditCount.textContent = AGENT_GATEWAY_AVAILABLE ? String((payload.agent_audit_logs || []).length) : "-";
    if (adminUserCount) adminUserCount.textContent = String((payload.users || []).length);
    if (adminInviteCount) adminInviteCount.textContent = String(invites.filter((item) => item.status === "active").length);
    if (adminVipCodeCount) adminVipCodeCount.textContent = String(vipCodes.filter((item) => item.status === "active").length);
    if (adminDemoCount) adminDemoCount.textContent = String(demoAccounts.length);
  } catch (error) {
    adminSummary.textContent = `读取失败：${error.message}`;
  }
}

function renderSystemApiKeys(keys) {
  if (!systemDeepSeekStatus) return;
  const deepseek = keys.deepseek || {};
  systemDeepSeekStatus.textContent = deepseek.configured
    ? `已锁定${deepseek.updated_at ? ` · ${deepseek.updated_at}` : ""}`
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
      <td>${escapeHtml(token.expires_at_text || "-")}</td>
      <td>${escapeHtml(String(token.rate_limit_per_min || "-"))}</td>
      <td>${escapeHtml(token.last_used_at || "-")}</td>
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
      <td>${escapeHtml(item.time || "")}</td>
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
        <td>${escapeHtml(user.last_request_at || "-")}</td>
        <td>${escapeHtml(user.vip_until_text || "-")}</td>
        <td>${escapeHtml(apiKeySummary(user.api_keys || {}))}</td>
        <td>${escapeHtml(user.invite_code || "-")}</td>
        <td>
          <div class="table-actions">
            <button type="button" data-user-action="grant_vip" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>发 VIP</button>
            <button type="button" data-user-action="revoke_vip" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>撤 VIP</button>
            <button type="button" data-user-action="${user.disabled ? "enable" : "disable"}" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>${user.disabled ? "启用" : "禁用"}</button>
            <button type="button" data-user-action="archive" data-username="${escapeHtml(user.username || "")}" ${protectedAttr}>归档</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
  adminUsersTable.innerHTML = `
    <thead><tr><th>账号</th><th>角色</th><th>封禁至</th><th>API 用量</th><th>最近请求</th><th>VIP 到期</th><th>用户 Key</th><th>邀请码</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="9">暂无注册用户</td></tr>`}</tbody>
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
      <td>${escapeHtml(invite.expires_at_text || "-")}</td>
      <td>${escapeHtml(invite.used_by || "-")}</td>
    </tr>
  `).join("");
  adminInvitesTable.innerHTML = `
    <thead><tr><th>邀请码</th><th>状态</th><th>过期时间</th><th>使用者</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="4">暂无邀请码</td></tr>`}</tbody>
  `;
}

function renderAdminVipCodes(items) {
  if (!adminVipCodesTable) return;
  const rows = items.map((item) => `
    <tr>
      <td><code>${escapeHtml(item.code || "")}</code></td>
      <td>${inviteStatusLabel(item.status)}</td>
      <td>${escapeHtml(`${item.vip_days || "-"} 天`)}</td>
      <td>${escapeHtml(item.expires_at_text || "-")}</td>
      <td>${escapeHtml(item.used_by || "-")}</td>
    </tr>
  `).join("");
  adminVipCodesTable.innerHTML = `
    <thead><tr><th>兑换码</th><th>状态</th><th>VIP 天数</th><th>过期时间</th><th>使用者</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5">暂无 VIP 兑换码</td></tr>`}</tbody>
  `;
}

function renderAdminDemoAccounts(accounts) {
  if (!adminDemoAccountsTable) return;
  const rows = accounts.map((account) => `
    <tr>
      <td><code>${escapeHtml(account.username || "")}</code></td>
      <td>${escapeHtml(`${account.remaining ?? "-"} / ${account.limit ?? "-"}`)}</td>
      <td>${escapeHtml(formatDuration(account.window_seconds || 0))}</td>
      <td>${escapeHtml(formatDuration(account.resets_in_seconds || 0))}</td>
      <td>${escapeHtml(account.created_at || "-")}</td>
      <td>
        <div class="table-actions">
          <button type="button" data-demo-reset="${escapeHtml(account.username || "")}">重置额度</button>
          <button type="button" data-user-action="archive" data-username="${escapeHtml(account.username || "")}">归档</button>
        </div>
      </td>
    </tr>
  `).join("");
  adminDemoAccountsTable.innerHTML = `
    <thead><tr><th>账号</th><th>剩余额度</th><th>刷新周期</th><th>下次刷新</th><th>创建时间</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6">暂无测试账号</td></tr>`}</tbody>
  `;
  adminDemoAccountsTable.querySelectorAll("[data-demo-reset]").forEach((button) => {
    button.addEventListener("click", () => resetDemoBudget(button.dataset.demoReset));
  });
  adminDemoAccountsTable.querySelectorAll("[data-user-action]").forEach((button) => {
    button.addEventListener("click", () => runUserAction(button.dataset.username, button.dataset.userAction));
  });
}

async function runUserAction(username, action) {
  if (!username || !action) return;
  if (adminReadonly) {
    adminSummary.textContent = "只读展示模式不能修改账号。";
    return;
  }
  const payload = { username, action };
  if (action === "grant_vip") {
    const rawDays = window.prompt("发放 VIP 天数", "30");
    if (!rawDays) return;
    payload.days = Number(rawDays);
  }
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

async function resetDemoBudget(username) {
  if (!username) return;
  adminSummary.textContent = "正在重置测试账号额度...";
  try {
    const response = await fetch("/api/admin/demo-reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    await readApiPayload(response, "重置测试账号额度失败");
    await loadAdminOverview();
  } catch (error) {
    adminSummary.textContent = `重置测试账号额度失败：${error.message}`;
  }
}

async function loadAdminTasks() {
  if (!adminTasksTable) return;
  try {
    const response = await fetch("/api/admin/tasks");
    const payload = await readApiPayload(response, "读取后台任务失败");
    renderAdminTasks(payload.items || []);
  } catch (error) {
    adminTasksTable.innerHTML = `<tbody><tr><td>任务读取失败：${escapeHtml(error.message)}</td></tr></tbody>`;
  }
}

function renderAdminTasks(tasks) {
  const rows = tasks.map((task) => `
      <tr>
        <td>${escapeHtml(taskKindLabel(task.kind))}</td>
        <td>${escapeHtml(taskTriggerLabel(task.metadata?.trigger))}</td>
        <td>${escapeHtml(task.title || "")}</td>
        <td>${taskStatusLabel(task.status)}</td>
        <td>${escapeHtml(task.created_at || "-")}</td>
        <td>${escapeHtml(task.finished_at || "-")}</td>
        <td>${escapeHtml(taskSummary(task))}</td>
      </tr>
    `).join("");
  adminTasksTable.innerHTML = `
    <thead><tr><th>类型</th><th>触发</th><th>任务</th><th>状态</th><th>开始</th><th>完成</th><th>摘要</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="7">暂无后台任务</td></tr>`}</tbody>
  `;
}

function taskKindLabel(kind) {
  return ({
    daily_market: "股票数据",
    kaipanla: "行情数据",
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
    spiderLogs.textContent = logsPayload.content || statusPayload.spider?.error || "暂无日志";
    if (spiderLogFile) spiderLogFile.textContent = logsPayload.log_file ? basename(logsPayload.log_file) : "暂无日志文件";
    await refreshDailyMarketScheduler();
    await refreshIdlePrefetchScheduler();
    await loadAdminTasks();
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
  if (dailyMarketLastDate) dailyMarketLastDate.textContent = scheduler.last_run_date || "-";
  if (dailyMarketUpdated) dailyMarketUpdated.textContent = String(last.updated ?? "-");
  if (dailyMarketSkipped) dailyMarketSkipped.textContent = String(last.skipped ?? "-");
  if (runDailyMarketNowBtn) runDailyMarketNowBtn.disabled = running;
}

function renderIdlePrefetchScheduler(scheduler) {
  if (!idlePrefetchStatus) return;
  if (idlePrefetchEnabled) idlePrefetchEnabled.checked = !!scheduler.enabled;
  if (idlePrefetchSeconds) idlePrefetchSeconds.value = scheduler.idle_seconds || 1800;
  const running = !!scheduler.running;
  idlePrefetchStatus.textContent = running
    ? "运行中"
    : scheduler.enabled
      ? `已启用 · 空闲 ${formatDuration(scheduler.idle_seconds || 1800)}`
      : "未启用";
  if (idlePrefetchIdle) idlePrefetchIdle.textContent = formatDuration(scheduler.current_idle_seconds || 0);
  if (idlePrefetchRemaining) idlePrefetchRemaining.textContent = scheduler.remaining_seconds ? formatDuration(scheduler.remaining_seconds) : "可触发";
  if (idlePrefetchLastRequest) {
    const code = scheduler.last_request_code ? ` · ${scheduler.last_request_code}` : "";
    idlePrefetchLastRequest.textContent = scheduler.last_request_at ? `${scheduler.last_request_at}${code}` : "-";
  }
  const last = scheduler.last_result || {};
  if (idlePrefetchLastRun) idlePrefetchLastRun.textContent = scheduler.last_run_at || "-";
  if (idlePrefetchLastResult) {
    idlePrefetchLastResult.textContent = last.ts_code
      ? `${last.ts_code}${last.name ? ` ${last.name}` : ""} · 全量历史`
      : (last.reason === "no_unfetched_stock" ? "没有待预抓股票" : (scheduler.last_error || "-"));
  }
  if (runIdlePrefetchNowBtn) runIdlePrefetchNowBtn.disabled = running;
}

async function loadKaipanlaFeatures() {
  if (!kaipanlaFeatureSelect) return;
  if (kaipanlaMeta) kaipanlaMeta.textContent = "正在读取开盘啦配置...";
  try {
    const [featuresResponse, schedulerResponse, recordsResponse] = await Promise.all([
      fetch("/api/admin/kaipanla/features"),
      fetch("/api/admin/kaipanla/scheduler"),
      fetch("/api/admin/kaipanla/records?limit=20"),
    ]);
    const featuresPayload = await readApiPayload(featuresResponse, "读取开盘啦功能失败");
    const schedulerPayload = await readApiPayload(schedulerResponse, "读取开盘啦定时失败");
    const recordsPayload = await readApiPayload(recordsResponse, "读取开盘啦记录失败");
    kaipanlaState.features = featuresPayload.items || [];
    kaipanlaState.currentParamFeature = "";
    renderKaipanlaScheduler(schedulerPayload.scheduler || {});
    renderKaipanlaFeatures();
    renderKaipanlaRecords(recordsPayload.items || []);
    if (kaipanlaMeta) kaipanlaMeta.textContent = `${kaipanlaState.features.length} 个功能 · 行情数据`;
  } catch (error) {
    if (kaipanlaMeta) kaipanlaMeta.textContent = `读取失败：${error.message}`;
    if (kaipanlaOutput) kaipanlaOutput.textContent = error.message;
  }
}

function renderKaipanlaFeatures() {
  if (!kaipanlaFeatureGrid || !kaipanlaFeatureSelect) return;
  const selected = new Set(kaipanlaState.scheduler.features || ["daily_data", "market_limit_up_ladder", "sector_ranking"]);
  kaipanlaFeatureGrid.innerHTML = kaipanlaState.features.map((item) => `
    <label class="kaipanla-feature-option">
      <input type="checkbox" value="${escapeAttr(item.key)}" ${selected.has(item.key) ? "checked" : ""} />
      <span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.category)}${item.requires ? ` · ${escapeHtml(item.requires)}` : ""}</small></span>
    </label>
  `).join("");
  kaipanlaFeatureSelect.innerHTML = kaipanlaState.features
    .map((item) => `<option value="${escapeAttr(item.key)}">${escapeHtml(item.category)} · ${escapeHtml(item.label)}</option>`)
    .join("");
  syncKaipanlaParams();
}

function renderKaipanlaScheduler(scheduler) {
  kaipanlaState.scheduler = scheduler || {};
  kaipanlaState.paramsByFeature = scheduler.params_by_feature || {};
  const running = !!scheduler.running;
  if (kaipanlaEnabled) kaipanlaEnabled.value = scheduler.enabled ? "1" : "0";
  if (kaipanlaTime) kaipanlaTime.value = scheduler.time || "21:45";
  if (kaipanlaStateText) kaipanlaStateText.textContent = running ? "运行中" : scheduler.enabled ? "已启用" : "未启用";
  if (kaipanlaTimeText) kaipanlaTimeText.textContent = scheduler.time || "21:45";
  if (kaipanlaFeatureCount) kaipanlaFeatureCount.textContent = String((scheduler.features || []).length);
  if (kaipanlaLastDate) kaipanlaLastDate.textContent = scheduler.last_run_date || "-";
  const last = scheduler.last_result || {};
  if (kaipanlaLastResult) kaipanlaLastResult.textContent = last.total ? `${last.succeeded || 0} / ${last.failed || 0}` : "-";
  if (kaipanlaRunBtn) kaipanlaRunBtn.disabled = running;
}

function syncKaipanlaParams() {
  try {
    persistKaipanlaParams();
  } catch (error) {
    if (kaipanlaOutput) kaipanlaOutput.textContent = `参数格式错误：${error.message}`;
    return;
  }
  const feature = selectedKaipanlaFeature();
  if (!feature || !kaipanlaParamsInput) return;
  kaipanlaParamsInput.value = JSON.stringify(kaipanlaState.paramsByFeature[feature.key] || feature.default_params || {}, null, 2);
  if (kaipanlaOutput) kaipanlaOutput.textContent = `${feature.description || ""}${feature.requires ? `\n需要：${feature.requires}` : ""}`;
  kaipanlaState.currentParamFeature = feature.key;
}

function persistKaipanlaParams() {
  const key = kaipanlaState.currentParamFeature;
  if (!key || !kaipanlaParamsInput?.value) return;
  const params = JSON.parse(kaipanlaParamsInput.value || "{}");
  if (!params || Array.isArray(params) || typeof params !== "object") throw new Error("参数必须是 JSON object");
  kaipanlaState.paramsByFeature[key] = params;
}

function selectedKaipanlaFeature() {
  const key = kaipanlaFeatureSelect?.value || "";
  return kaipanlaState.features.find((item) => item.key === key) || null;
}

async function validateKaipanlaIntegration() {
  if (!kaipanlaOutput || !kaipanlaValidateBtn) return;
  kaipanlaValidateBtn.disabled = true;
  kaipanlaOutput.textContent = "正在验证开盘啦功能映射...";
  try {
    const response = await fetch("/api/admin/kaipanla/validate");
    const payload = await readApiPayload(response, "验证开盘啦功能失败");
    kaipanlaOutput.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    kaipanlaOutput.textContent = `验证失败：${error.message}`;
  } finally {
    kaipanlaValidateBtn.disabled = adminReadonly;
  }
}

function kaipanlaSchedulerPayload() {
  persistKaipanlaParams();
  return {
    action: "save",
    enabled: kaipanlaEnabled?.value === "1",
    time: kaipanlaTime?.value || "21:45",
    features: [...(kaipanlaFeatureGrid?.querySelectorAll("input[type='checkbox']:checked") || [])].map((input) => input.value),
    params_by_feature: { ...kaipanlaState.paramsByFeature },
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
    if (kaipanlaOutput) kaipanlaOutput.textContent = "开盘啦行情数据定时配置已保存。";
    return true;
  } catch (error) {
    if (kaipanlaOutput) kaipanlaOutput.textContent = `保存失败：${error.message}`;
    return false;
  } finally {
    kaipanlaSaveBtn.disabled = adminReadonly;
  }
}

async function runKaipanlaNow() {
  if (!kaipanlaRunBtn || !approveDataFetch("立即执行开盘啦行情数据抓取")) return;
  kaipanlaRunBtn.disabled = true;
  if (kaipanlaOutput) kaipanlaOutput.textContent = "正在启动开盘啦行情数据任务...";
  try {
    if (!(await saveKaipanlaScheduler())) return;
    const response = await fetch("/api/admin/kaipanla/scheduler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run_now", approved: true }),
    });
    const payload = await readApiPayload(response, "启动开盘啦抓取失败");
    renderKaipanlaScheduler(payload.scheduler || {});
    if (kaipanlaOutput) kaipanlaOutput.textContent = "开盘啦行情数据任务已启动。";
    window.setTimeout(loadKaipanlaFeatures, 2500);
  } catch (error) {
    if (kaipanlaOutput) kaipanlaOutput.textContent = `启动失败：${error.message}`;
  } finally {
    kaipanlaRunBtn.disabled = adminReadonly;
  }
}

function renderKaipanlaRecords(items) {
  if (!kaipanlaRecordsTable) return;
  kaipanlaRecordsTable.innerHTML = `
    <thead><tr><th>保存时间</th><th>功能</th><th>分类</th><th>Run</th><th>操作</th></tr></thead>
    <tbody>${items.length ? items.map((item) => `
      <tr><td>${escapeHtml(item.saved_at || "")}</td><td>${escapeHtml(item.label || item.feature || "")}</td><td>${escapeHtml(item.category || "")}</td><td><code>${escapeHtml(item.run_id || "")}</code></td><td><button type="button" data-record-path="${escapeAttr(item.path || "")}">查看</button></td></tr>
    `).join("") : `<tr><td colspan="5" class="news-empty">暂无本地记录</td></tr>`}</tbody>
  `;
  kaipanlaRecordsTable.querySelectorAll("[data-record-path]").forEach((button) => {
    button.addEventListener("click", () => readKaipanlaRecord(button.dataset.recordPath));
  });
}

async function readKaipanlaRecord(path) {
  if (!path || !kaipanlaOutput) return;
  try {
    const response = await fetch(`/api/admin/kaipanla/record?path=${encodeURIComponent(path)}`);
    const payload = await readApiPayload(response, "读取开盘啦记录失败");
    kaipanlaOutput.textContent = JSON.stringify(payload.record || {}, null, 2);
  } catch (error) {
    kaipanlaOutput.textContent = `读取记录失败：${error.message}`;
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
    grant_vip: "发放 VIP",
    revoke_vip: "撤销 VIP",
    disable_user: "禁用用户",
    enable_user: "启用用户",
    archive_user: "归档用户",
    archive_demo_account: "归档测试账号",
    reset_demo_budget: "重置测试额度",
  })[action] || action || "-";
}

function formatDuration(seconds) {
  if (!seconds) return "-";
  if (seconds % 86400 === 0) return `${seconds / 86400} 天`;
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  return `${seconds} 秒`;
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
