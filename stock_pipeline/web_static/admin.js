const themeToggleBtn = document.querySelector("#themeToggleBtn");
const logoutBtn = document.querySelector("#logoutBtn");
const createInviteBtn = document.querySelector("#createInviteBtn");
const createDemoAccountBtn = document.querySelector("#createDemoAccountBtn");
const createVipCodeBtn = document.querySelector("#createVipCodeBtn");
const vipCodeDaysInput = document.querySelector("#vipCodeDaysInput");
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
const spiderTypeText = document.querySelector("#spiderTypeText");
const spiderPagesText = document.querySelector("#spiderPagesText");
const spiderLogFile = document.querySelector("#spiderLogFile");
const spiderTypesSelect = document.querySelector("#spiderTypesSelect");
const spiderMaxPages = document.querySelector("#spiderMaxPages");
const spiderThreads = document.querySelector("#spiderThreads");
const spiderArticleSleep = document.querySelector("#spiderArticleSleep");
const spiderPageSleep = document.querySelector("#spiderPageSleep");
const spiderDryRun = document.querySelector("#spiderDryRun");
const spiderNewOnly = document.querySelector("#spiderNewOnly");
const startSpiderBtn = document.querySelector("#startSpiderBtn");
const stopSpiderBtn = document.querySelector("#stopSpiderBtn");
const spiderLogs = document.querySelector("#spiderLogs");

let spiderPollTimer = null;

initializeTheme();
initializeAdminPage();

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

startSpiderBtn?.addEventListener("click", async () => {
  startSpiderBtn.disabled = true;
  let started = false;
  try {
    const selectedTypes = [...spiderTypesSelect.selectedOptions].map((option) => option.value);
    const response = await fetch("/api/admin/spider/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        types: selectedTypes.length ? selectedTypes : ["财经要闻"],
        max_pages: Number(spiderMaxPages.value || 1),
        threads: Number(spiderThreads.value || 1),
        article_sleep: spiderArticleSleep.value || "0,0",
        page_sleep: spiderPageSleep.value || "0,0",
        dry_run: spiderDryRun.checked,
        new_only: spiderNewOnly.checked,
      }),
    });
    await readApiPayload(response, "启动爬虫失败");
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
    const response = await fetch("/api/admin/spider/stop", { method: "POST" });
    await readApiPayload(response, "停止爬虫失败");
    await refreshSpiderConsole();
  } catch (error) {
    spiderStatus.textContent = `停止失败：${error.message}`;
  }
});

async function initializeAdminPage() {
  try {
    const response = await fetch("/api/session");
    const payload = await readApiPayload(response, "读取会话失败");
    if (!payload.authenticated) {
      window.location.href = "/login";
      return;
    }
    if (payload.role !== "admin") {
      window.location.href = "/";
      return;
    }
    if (adminSummary) await loadAdminOverview();
    if (spiderStatus) {
      await refreshSpiderConsole();
      startSpiderPolling();
    }
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
    if (adminUserCount) adminUserCount.textContent = String((payload.users || []).length);
    if (adminInviteCount) adminInviteCount.textContent = String(invites.filter((item) => item.status === "active").length);
    if (adminVipCodeCount) adminVipCodeCount.textContent = String(vipCodes.filter((item) => item.status === "active").length);
    if (adminDemoCount) adminDemoCount.textContent = String(demoAccounts.length);
  } catch (error) {
    adminSummary.textContent = `读取失败：${error.message}`;
  }
}

function renderAdminUsers(users) {
  const rows = users.map((user) => `
    <tr>
      <td>${escapeHtml(user.username || "")}</td>
      <td>${escapeHtml(user.disabled ? "已禁用" : user.role || "")}</td>
      <td>${escapeHtml(String(user.usage_total || 0))}</td>
      <td>${escapeHtml(user.last_request_at || "-")}</td>
      <td>${escapeHtml(user.vip_until_text || "-")}</td>
      <td>${escapeHtml(apiKeySummary(user.api_keys || {}))}</td>
      <td>${escapeHtml(user.invite_code || "-")}</td>
      <td>
        <div class="table-actions">
          <button type="button" data-user-action="grant_vip" data-username="${escapeHtml(user.username || "")}">发 VIP</button>
          <button type="button" data-user-action="revoke_vip" data-username="${escapeHtml(user.username || "")}">撤 VIP</button>
          <button type="button" data-user-action="${user.disabled ? "enable" : "disable"}" data-username="${escapeHtml(user.username || "")}">${user.disabled ? "启用" : "禁用"}</button>
        </div>
      </td>
    </tr>
  `).join("");
  adminUsersTable.innerHTML = `
    <thead><tr><th>账号</th><th>角色</th><th>API 用量</th><th>最近请求</th><th>VIP 到期</th><th>用户 Key</th><th>邀请码</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="8">暂无注册用户</td></tr>`}</tbody>
  `;
  adminUsersTable.querySelectorAll("[data-user-action]").forEach((button) => {
    button.addEventListener("click", () => runUserAction(button.dataset.username, button.dataset.userAction));
  });
}

function renderAdminInvites(invites) {
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
  const rows = accounts.map((account) => `
    <tr>
      <td><code>${escapeHtml(account.username || "")}</code></td>
      <td>${escapeHtml(`${account.remaining ?? "-"} / ${account.limit ?? "-"}`)}</td>
      <td>${escapeHtml(formatDuration(account.window_seconds || 0))}</td>
      <td>${escapeHtml(formatDuration(account.resets_in_seconds || 0))}</td>
      <td>${escapeHtml(account.created_at || "-")}</td>
      <td><button type="button" data-demo-reset="${escapeHtml(account.username || "")}">重置额度</button></td>
    </tr>
  `).join("");
  adminDemoAccountsTable.innerHTML = `
    <thead><tr><th>账号</th><th>剩余额度</th><th>刷新周期</th><th>下次刷新</th><th>创建时间</th><th>操作</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6">暂无测试账号</td></tr>`}</tbody>
  `;
  adminDemoAccountsTable.querySelectorAll("[data-demo-reset]").forEach((button) => {
    button.addEventListener("click", () => resetDemoBudget(button.dataset.demoReset));
  });
}

async function runUserAction(username, action) {
  if (!username || !action) return;
  const payload = { username, action };
  if (action === "grant_vip") {
    const rawDays = window.prompt("发放 VIP 天数", "30");
    if (!rawDays) return;
    payload.days = Number(rawDays);
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
      <td>${escapeHtml(task.kind || "")}</td>
      <td>${escapeHtml(task.title || "")}</td>
      <td>${taskStatusLabel(task.status)}</td>
      <td>${escapeHtml(task.updated_at || "-")}</td>
      <td>${escapeHtml(task.error || task.result_summary?.rating_hint || "-")}</td>
    </tr>
  `).join("");
  adminTasksTable.innerHTML = `
    <thead><tr><th>类型</th><th>任务</th><th>状态</th><th>更新时间</th><th>摘要</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5">暂无后台任务</td></tr>`}</tbody>
  `;
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
    const statusResponse = await fetch("/api/admin/spider/status");
    const statusPayload = await readApiPayload(statusResponse, "读取爬虫状态失败");
    renderSpiderStatus(statusPayload);
    const logsResponse = await fetch("/api/admin/spider/logs?lines=160");
    const logsPayload = await readApiPayload(logsResponse, "读取爬虫日志失败");
    spiderLogs.textContent = logsPayload.content || statusPayload.spider?.error || "暂无日志";
    if (spiderLogFile) spiderLogFile.textContent = logsPayload.log_file ? basename(logsPayload.log_file) : "暂无日志文件";
  } catch (error) {
    spiderStatus.textContent = `爬虫状态读取失败：${error.message}`;
  }
}

function renderSpiderStatus(payload) {
  const spider = payload.spider || {};
  renderSpiderTypes(payload.available_types || []);
  const status = spider.status || "idle";
  const running = status === "running" || status === "stopping";
  startSpiderBtn.disabled = running;
  stopSpiderBtn.disabled = !running;
  const typeText = Array.isArray(spider.types) ? spider.types.join("、") : "-";
  const dryRunText = spider.dry_run ? "dry-run" : "写入 MongoDB";
  const pages = spider.max_pages ? `${spider.max_pages} 页` : "-";
  const errorText = spider.error ? `；错误：${spider.error}` : "";
  const returnText = Number.isInteger(spider.returncode) ? `；退出码：${spider.returncode}` : "";
  spiderStatus.textContent = `状态：${spiderStatusLabel(status)}；分类：${typeText}；模式：${dryRunText}；页数：${pages}${returnText}${errorText}`;
  if (spiderStateText) spiderStateText.textContent = spiderStatusLabel(status);
  if (spiderModeText) spiderModeText.textContent = dryRunText;
  if (spiderTypeText) spiderTypeText.textContent = typeText;
  if (spiderPagesText) spiderPagesText.textContent = pages;
}

function renderSpiderTypes(types) {
  if (!spiderTypesSelect || spiderTypesSelect.options.length || !types.length) return;
  spiderTypesSelect.innerHTML = types
    .map((type, index) => `<option value="${escapeHtml(type)}" ${index === 0 ? "selected" : ""}>${escapeHtml(type)}</option>`)
    .join("");
}

async function readApiPayload(response, fallbackMessage) {
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      if (!response.ok) throw new Error(text);
      throw new Error(text || fallbackMessage);
    }
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || payload.message || text || fallbackMessage);
  }
  return payload;
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

function basename(path) {
  return String(path || "").split("/").filter(Boolean).pop() || "";
}
