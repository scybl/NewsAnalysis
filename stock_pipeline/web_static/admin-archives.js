const themeToggleBtn = document.querySelector("#themeToggleBtn");
const logoutBtn = document.querySelector("#logoutBtn");
const archiveSearchInput = document.querySelector("#archiveSearchInput");
const archiveSearchBtn = document.querySelector("#archiveSearchBtn");
const archiveSummary = document.querySelector("#archiveSummary");
const archiveUsersTable = document.querySelector("#archiveUsersTable");
const archiveDemoAccountsTable = document.querySelector("#archiveDemoAccountsTable");
const archiveTotalCount = document.querySelector("#archiveTotalCount");
const archiveUserCount = document.querySelector("#archiveUserCount");
const archiveDemoCount = document.querySelector("#archiveDemoCount");
const archiveQueryLabel = document.querySelector("#archiveQueryLabel");

initializeTheme();
initializeArchivePage();

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
  try {
    await fetch("/api/logout", { method: "POST" });
  } finally {
    window.location.href = "/login.html";
  }
});

function initializeArchivePage() {
  archiveSearchBtn?.addEventListener("click", () => loadArchives());
  archiveSearchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadArchives();
  });
  loadArchives();
}

async function loadArchives() {
  const query = archiveSearchInput?.value?.trim() || "";
  archiveSummary.textContent = "正在读取归档账号...";
  try {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    const response = await fetch(`/api/admin/archives?${params.toString()}`);
    const payload = await readApiPayload(response, "读取归档账号失败");
    renderCounts(payload.counts || {}, query);
    renderArchivedUsers(payload.users || []);
    renderArchivedDemoAccounts(payload.demo_accounts || []);
    archiveSummary.textContent = `已读取 ${payload.counts?.total || 0} 个归档账号。归档只冻结登录，历史数据仍保留在服务器用户库中。`;
  } catch (error) {
    archiveSummary.textContent = `读取失败：${error.message}`;
  }
}

function renderCounts(counts, query) {
  archiveTotalCount.textContent = String(counts.total ?? 0);
  archiveUserCount.textContent = String(counts.users ?? 0);
  archiveDemoCount.textContent = String(counts.demo_accounts ?? 0);
  archiveQueryLabel.textContent = query || "全部";
}

function renderArchivedUsers(users) {
  const rows = users.map((user) => `
    <tr>
      <td><code>${escapeHtml(user.username || "")}</code></td>
      <td>${escapeHtml(user.role || "user")}</td>
      <td>${escapeHtml(user.archived_at || "-")}</td>
      <td>${escapeHtml(user.archived_by || "-")}</td>
      <td>${escapeHtml(user.reason || "-")}</td>
      <td>${escapeHtml(String(user.usage_total || 0))}</td>
      <td>${escapeHtml(user.last_request_at || "-")}</td>
      <td>${escapeHtml(apiKeySummary(user.api_keys || {}))}</td>
      <td>${escapeHtml(user.created_at || "-")}</td>
    </tr>
  `).join("");
  archiveUsersTable.innerHTML = `
    <thead><tr><th>账号</th><th>原角色</th><th>归档时间</th><th>归档人</th><th>原因</th><th>API 用量</th><th>最近请求</th><th>Key 状态</th><th>创建时间</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="9">暂无归档注册用户</td></tr>`}</tbody>
  `;
}

function renderArchivedDemoAccounts(accounts) {
  const rows = accounts.map((account) => `
    <tr>
      <td><code>${escapeHtml(account.username || "")}</code></td>
      <td>${escapeHtml(account.archived_at || "-")}</td>
      <td>${escapeHtml(account.archived_by || "-")}</td>
      <td>${escapeHtml(account.reason || "-")}</td>
      <td>${escapeHtml(String(account.usage_total || 0))}</td>
      <td>${escapeHtml(account.last_request_at || "-")}</td>
      <td>${escapeHtml(account.created_by || "-")}</td>
      <td>${escapeHtml(account.created_at || "-")}</td>
    </tr>
  `).join("");
  archiveDemoAccountsTable.innerHTML = `
    <thead><tr><th>账号</th><th>归档时间</th><th>归档人</th><th>原因</th><th>API 用量</th><th>最近请求</th><th>创建人</th><th>创建时间</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="8">暂无归档测试账号</td></tr>`}</tbody>
  `;
}

async function readApiPayload(response, fallbackMessage) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || fallbackMessage);
  }
  return payload;
}

function apiKeySummary(keys) {
  const labels = [];
  if (keys.tushare?.configured) labels.push("Tushare");
  if (keys.deepseek?.configured) labels.push("DeepSeek");
  return labels.length ? labels.join(" / ") : "未保存";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
