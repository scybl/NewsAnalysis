const themeToggleBtn = document.querySelector("#themeToggleBtn");
const logoutBtn = document.querySelector("#logoutBtn");
const createInviteBtn = document.querySelector("#createInviteBtn");
const createDemoAccountBtn = document.querySelector("#createDemoAccountBtn");
const adminSummary = document.querySelector("#adminSummary");
const adminUsersTable = document.querySelector("#adminUsersTable");
const adminInvitesTable = document.querySelector("#adminInvitesTable");
const adminDemoAccountsTable = document.querySelector("#adminDemoAccountsTable");
const adminUserCount = document.querySelector("#adminUserCount");
const adminInviteCount = document.querySelector("#adminInviteCount");
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
    const demoAccounts = payload.demo_accounts || [];
    adminSummary.textContent = `新测试账号默认额度：${demo.limit ?? "-"} 次 / ${formatDuration(demo.window_seconds || 0)}。`;
    renderAdminUsers(payload.users || []);
    renderAdminInvites(invites);
    renderAdminDemoAccounts(demoAccounts);
    if (adminUserCount) adminUserCount.textContent = String((payload.users || []).length);
    if (adminInviteCount) adminInviteCount.textContent = String(invites.filter((item) => item.status === "active").length);
    if (adminDemoCount) adminDemoCount.textContent = String(demoAccounts.length);
  } catch (error) {
    adminSummary.textContent = `读取失败：${error.message}`;
  }
}

function renderAdminUsers(users) {
  const rows = users.map((user) => `
    <tr>
      <td>${escapeHtml(user.username || "")}</td>
      <td>${escapeHtml(user.role || "")}</td>
      <td>${escapeHtml(String(user.usage_total || 0))}</td>
      <td>${escapeHtml(user.last_request_at || "-")}</td>
      <td>${escapeHtml(user.invite_code || "-")}</td>
    </tr>
  `).join("");
  adminUsersTable.innerHTML = `
    <thead><tr><th>账号</th><th>角色</th><th>API 用量</th><th>最近请求</th><th>邀请码</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5">暂无注册用户</td></tr>`}</tbody>
  `;
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

function renderAdminDemoAccounts(accounts) {
  const rows = accounts.map((account) => `
    <tr>
      <td><code>${escapeHtml(account.username || "")}</code></td>
      <td>${escapeHtml(`${account.remaining ?? "-"} / ${account.limit ?? "-"}`)}</td>
      <td>${escapeHtml(formatDuration(account.window_seconds || 0))}</td>
      <td>${escapeHtml(formatDuration(account.resets_in_seconds || 0))}</td>
      <td>${escapeHtml(account.created_at || "-")}</td>
    </tr>
  `).join("");
  adminDemoAccountsTable.innerHTML = `
    <thead><tr><th>账号</th><th>剩余额度</th><th>刷新周期</th><th>下次刷新</th><th>创建时间</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5">暂无测试账号</td></tr>`}</tbody>
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
    spiderLogs.textContent = logsPayload.content || "暂无日志";
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
  spiderStatus.textContent = `状态：${spiderStatusLabel(status)}；分类：${typeText}；模式：${dryRunText}；页数：${pages}`;
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

function formatDuration(seconds) {
  if (!seconds) return "-";
  if (seconds % 86400 === 0) return `${seconds / 86400} 天`;
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  return `${seconds} 秒`;
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
