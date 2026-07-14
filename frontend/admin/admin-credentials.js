(() => {
const refreshCredentialsBtn = document.querySelector("#refreshCredentialsBtn");
const credentialsSummary = document.querySelector("#credentialsSummary");
const credentialsGrid = document.querySelector("#credentialsGrid");

let credentialsAdminReadonly = false;

initializeCredentialsPane();

refreshCredentialsBtn?.addEventListener("click", () => loadCredentials());

credentialsGrid?.addEventListener("click", async (event) => {
  const saveButton = event.target.closest("[data-credential-save]");
  const deleteButton = event.target.closest("[data-credential-delete]");
  if (!saveButton && !deleteButton) return;
  const name = saveButton?.dataset.credentialSave || deleteButton?.dataset.credentialDelete || "";
  if (!name || credentialsAdminReadonly) return;
  if (saveButton) {
    await saveCredential(name, saveButton);
  } else {
    await deleteCredential(name, deleteButton);
  }
});

async function initializeCredentialsPane() {
  if (!credentialsGrid) return;
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
    credentialsAdminReadonly = payload.role === "admin_readonly";
    await loadCredentials();
  } catch {
    window.location.href = "/login";
  }
}

async function loadCredentials() {
  if (credentialsSummary) credentialsSummary.textContent = "正在读取凭据状态...";
  try {
    const response = await fetch("/api/admin/credentials");
    const payload = await readApiPayload(response, "读取凭据失败");
    renderCredentials(payload.items || []);
  } catch (error) {
    if (credentialsSummary) credentialsSummary.textContent = `读取凭据失败：${error.message}`;
    if (credentialsGrid) credentialsGrid.innerHTML = "";
  }
}

async function saveCredential(name, button) {
  const input = document.querySelector(`[data-credential-value="${cssEscape(name)}"]`);
  const value = input?.value || "";
  if (!value.trim()) {
    setCredentialMessage(name, "请输入新值后再保存。", true);
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch("/api/admin/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save", name, value }),
    });
    const payload = await readApiPayload(response, "保存凭据失败");
    renderCredentials(payload.items || []);
    if (credentialsSummary) credentialsSummary.textContent = "凭据已保存。爬虫会在下一轮采集前重新读取。";
  } catch (error) {
    setCredentialMessage(name, `保存失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteCredential(name, button) {
  if (!window.confirm("确定移除这个凭据？移除后相关数据源可能不可用。")) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/admin/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", name }),
    });
    const payload = await readApiPayload(response, "移除凭据失败");
    renderCredentials(payload.items || []);
    if (credentialsSummary) credentialsSummary.textContent = "凭据已移除。";
  } catch (error) {
    setCredentialMessage(name, `移除失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function renderCredentials(items) {
  if (!credentialsGrid) return;
  const configuredCount = items.filter((item) => item.configured).length;
  if (credentialsSummary) credentialsSummary.textContent = `已配置 ${configuredCount} / ${items.length} 项；明文不会在页面回显。`;
  const groups = groupBySource(items);
  credentialsGrid.innerHTML = Object.entries(groups).map(([source, groupItems]) => `
    <section class="credential-section">
      <div class="credential-section-head">
        <h4>${escapeHtml(source)}</h4>
        <span>${escapeHtml(String(groupItems.filter((item) => item.configured).length))} / ${escapeHtml(String(groupItems.length))} 已配置</span>
      </div>
      <div class="credential-list">
        <div class="credential-row credential-row-head" aria-hidden="true">
          <span>凭据</span>
          <span>ENV</span>
          <span>状态</span>
          <span>更新时间</span>
          <span>新值</span>
          <span>操作</span>
        </div>
        ${groupItems.map(renderCredentialItem).join("")}
      </div>
    </section>
  `).join("");
}

function renderCredentialItem(item) {
  const statusClass = item.configured ? "is-configured" : "is-empty";
  const statusText = item.configured ? "已配置" : "未配置";
  const placeholder = item.configured ? "输入新值会覆盖当前凭据" : placeholderForKind(item.kind);
  return `
    <article class="credential-row credential-item ${statusClass}" data-credential-card="${escapeAttr(item.name)}">
      <div class="credential-title">
        <h5>${escapeHtml(item.label || item.name)}</h5>
        <p>${escapeHtml(item.description || "")}</p>
      </div>
      <code class="credential-env">${escapeHtml(item.env || "-")}</code>
      <div class="credential-status-list">
        <span class="credential-status ${item.configured ? "is-success" : "is-muted"}">${escapeHtml(statusText)}</span>
        ${item.status_note ? `<span class="credential-status is-danger">${escapeHtml(item.status_note)}</span>` : ""}
      </div>
      <time>${escapeHtml(item.updated_at || "-")}</time>
      <label class="credential-input">
        <span class="sr-only">新值</span>
        <textarea data-credential-value="${escapeAttr(item.name)}" autocomplete="off" spellcheck="false" placeholder="${escapeAttr(placeholder)}" ${credentialsAdminReadonly ? "disabled" : ""}></textarea>
      </label>
      <div class="credential-actions">
        <button class="primary-action" type="button" data-credential-save="${escapeAttr(item.name)}" ${credentialsAdminReadonly ? "disabled" : ""}>保存</button>
        <button type="button" data-credential-delete="${escapeAttr(item.name)}" ${credentialsAdminReadonly || !item.configured ? "disabled" : ""}>移除</button>
      </div>
      <small class="credential-message" data-credential-message="${escapeAttr(item.name)}">${item.reloads_next_run ? "下一轮采集前生效" : "后续请求立即使用"}</small>
    </article>
  `;
}

function groupBySource(items) {
  return items.reduce((groups, item) => {
    const source = item.source || "其他";
    groups[source] = groups[source] || [];
    groups[source].push(item);
    return groups;
  }, {});
}

function placeholderForKind(kind) {
  if (kind === "url") return "https://example.com/path";
  if (kind === "boolean") return "1 或 0";
  if (kind === "proxy") return "http://user:pass@host:port";
  if (kind === "cookie_json") return "[{\"name\":\"cf_clearance\",\"value\":\"...\",\"domain\":\".politico.com\"}]";
  if (kind === "cookie") return "name=value; another=value";
  return "输入 key / token";
}

function setCredentialMessage(name, message, isError = false) {
  const target = document.querySelector(`[data-credential-message="${cssEscape(name)}"]`);
  if (!target) return;
  target.textContent = message;
  target.classList.toggle("is-error", isError);
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
    return `${fallbackMessage}：后端返回了 HTML 错误页，请检查登录态和服务版本。`;
  }
  return raw || fallbackMessage;
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
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
})();
