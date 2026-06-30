const crawlerPageMeta = document.querySelector("#crawlerPageMeta");
const crawlerHealthGrid = document.querySelector("#crawlerHealthGrid");
const crawlerHealthMeta = document.querySelector("#crawlerHealthMeta");
const crawlerFailureMeta = document.querySelector("#crawlerFailureMeta");
const crawlerFailureStats = document.querySelector("#crawlerFailureStats");
const crawlerRunsTable = document.querySelector("#crawlerRunsTable");
const crawlerRefreshBtn = document.querySelector("#crawlerRefreshBtn");
const crawlerAutoRefresh = document.querySelector("#crawlerAutoRefresh");
const crawlerRunLimit = document.querySelector("#crawlerRunLimit");
const crawlerRetryFailuresBtn = document.querySelector("#crawlerRetryFailuresBtn");
const crawlerRunDetailCard = document.querySelector("#crawlerRunDetailCard");
const crawlerRunDetailMeta = document.querySelector("#crawlerRunDetailMeta");
const crawlerRunDetail = document.querySelector("#crawlerRunDetail");
const crawlerRunDetailClose = document.querySelector("#crawlerRunDetailClose");

const CRAWLER_FAILURE_RETRY_THRESHOLD = 3;
const CRAWLER_EXPECTED_SOURCES = ["tonghuashun", "guardian", "bloomberg", "politico_browser", "politico_rss"];
const CRAWLER_SOURCE_CONFIG = {
  tonghuashun: { label: "同花顺", initial: "同" },
  guardian: { label: "Guardian", initial: "G" },
  bloomberg: { label: "Bloomberg", initial: "B", maintenance: true },
  politico: { label: "Politico Legacy", initial: "P" },
  politico_browser: { label: "Politico Web", initial: "P" },
  politico_rss: { label: "Politico RSS", initial: "R", maintenance: true },
  politico_chrome: { label: "Politico Chrome", initial: "C", maintenance: true },
};
const crawlerState = { payload: null, timer: null, failureItems: new Map() };

document.addEventListener("DOMContentLoaded", () => {
  crawlerRefreshBtn?.addEventListener("click", loadCrawlerStatus);
  crawlerRunLimit?.addEventListener("change", loadCrawlerStatus);
  crawlerRetryFailuresBtn?.addEventListener("click", () => retryFailureItems());
  crawlerFailureStats?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-failure-action='retry']");
    if (button) retryFailureItems(button.dataset.failureId);
  });
  crawlerAutoRefresh?.addEventListener("change", syncAutoRefresh);
  crawlerRunDetailClose?.addEventListener("click", closeRunDetail);
  showStoredRuntimeAlerts();
  syncAutoRefresh();
  loadCrawlerStatus();
});

async function loadCrawlerStatus() {
  crawlerRefreshBtn.disabled = true;
  crawlerPageMeta.textContent = "正在读取 NewsCrawler 运维数据...";
  try {
    const response = await fetch(`/api/admin/news-crawler/status?limit=${encodeURIComponent(crawlerRunLimit.value || "25")}`);
    const payload = await response.json();
    if (!response.ok || payload.ok === false || payload.enabled === false) {
      throw new Error(payload.error || "读取 NewsCrawler 状态失败");
    }
    crawlerState.payload = payload;
    renderCrawlerConsole(payload);
    crawlerPageMeta.textContent = `${payload.database} · 最近刷新 ${formatDateTime(new Date().toISOString())} · 只读`;
  } catch (error) {
    crawlerState.payload = null;
    crawlerPageMeta.textContent = `读取失败：${error.message}`;
    crawlerHealthMeta.textContent = "连接失败";
    crawlerFailureMeta.textContent = "连接失败";
    crawlerHealthGrid.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
    crawlerFailureStats.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
    crawlerRunsTable.innerHTML = `<tbody><tr><td class="news-empty is-error">${escapeHtml(error.message)}</td></tr></tbody>`;
  } finally {
    crawlerRefreshBtn.disabled = false;
  }
}

function renderCrawlerConsole(payload) {
  const runs = payload.runs || [];
  renderCrawlerAlerts(payload.alerts || []);

  const health = payload.health || [];
  const healthWithPlaceholders = withCrawlerPlaceholders(health);
  crawlerHealthMeta.textContent = healthWithPlaceholders.length ? `${healthWithPlaceholders.length} 个来源投影` : "尚无投影";
  crawlerHealthGrid.innerHTML = healthWithPlaceholders.length
    ? healthWithPlaceholders.map(renderCrawlerHealth).join("")
    : `<div class="news-empty compact">尚无来源运行记录。NewsCrawler 完成首次采集后会显示。</div>`;
  renderFailureStats(payload.failure_stats || {});
  renderCrawlerRuns(runs);
}

function renderCrawlerAlerts(alerts) {
  const existing = document.querySelector(".crawler-runtime-alerts");
  existing?.remove();
  if (!alerts.length) return;
  const target = document.querySelector(".crawler-console");
  if (!target) return;
  const panel = document.createElement("section");
  panel.className = "crawler-runtime-alerts";
  panel.innerHTML = alerts.map((alert) => `
    <article>
      <strong>${escapeHtml(alert.title || "数据源告警")}</strong>
      <p>${escapeHtml(alert.message || "")}</p>
      <small>${escapeHtml([sourceLabel(alert.source_name), formatDateTime(alert.paused_at), alert.issue_code].filter(Boolean).join(" · "))}</small>
    </article>
  `).join("");
  target.prepend(panel);
}

function showStoredRuntimeAlerts() {
  let alerts = [];
  try {
    alerts = JSON.parse(sessionStorage.getItem("adminRuntimeAlerts") || "[]");
    sessionStorage.removeItem("adminRuntimeAlerts");
  } catch {
    alerts = [];
  }
  if (!Array.isArray(alerts) || !alerts.length) return;
  window.alert(alerts.map((item) => `${item.title || "数据源告警"}：${item.message || ""}`).join("\n\n"));
}

function renderCrawlerHealth(item) {
  const status = item.status || "unknown";
  const rate = Math.round(Number(item.recent_success_rate || 0) * 100);
  return `
    <article class="crawler-health-item is-${escapeAttr(status)}">
      <div class="crawler-health-title">
        <div><span class="crawler-source-mark">${escapeHtml(sourceInitial(item.source_name))}</span><strong>${escapeHtml(sourceLabel(item.source_name))}</strong></div>
        <span class="crawler-health-status">${escapeHtml(healthLabel(status))}</span>
      </div>
      <div class="crawler-health-metrics">
        <div><span>完整成功率</span><strong>${escapeHtml(String(rate))}%</strong></div>
        <div><span>连续整次失败</span><strong>${escapeHtml(String(item.consecutive_failures || 0))}</strong></div>
        <div><span>上次写入</span><strong>${escapeHtml(String(item.last_inserted_count || 0))}</strong></div>
        <div><span>平均运行耗时</span><strong>${escapeHtml(formatDuration(item.average_duration_seconds))}</strong></div>
      </div>
      <dl class="crawler-health-times">
        <div><dt>最近成功</dt><dd>${escapeHtml(formatDateTime(item.last_success_at))}</dd></div>
        <div><dt>最近失败</dt><dd>${escapeHtml(formatDateTime(item.last_failure_at))}</dd></div>
      </dl>
      ${item.latest_error ? `<p class="crawler-last-error" title="${escapeAttr(item.latest_error)}"><strong>最近文章异常：</strong>${escapeHtml(item.latest_error)}</p>` : ""}
    </article>
  `;
}

function withCrawlerPlaceholders(health) {
  const items = [...(health || [])];
  for (const sourceName of CRAWLER_EXPECTED_SOURCES) {
    if (!items.some((item) => item.source_name === sourceName)) {
      items.push({
        source_name: sourceName,
        status: "offline",
        recent_success_rate: 0,
        consecutive_failures: 0,
        last_inserted_count: 0,
        average_duration_seconds: 0,
        last_success_at: "",
        last_failure_at: "",
        latest_error: "等待首次采集运行记录。",
        placeholder: true,
      });
    }
  }
  return items.map((item) => {
    const config = CRAWLER_SOURCE_CONFIG[item.source_name] || {};
    if (item.status === "paused") {
      return {
        ...item,
        latest_error: item.pause_reason || item.latest_error || "已自动暂停，请更新凭据后再恢复。",
      };
    }
    if (!config.maintenance) return item;
    return {
      ...item,
      status: "maintenance",
      latest_status: "maintenance",
      latest_error: "已暂停自动采集，后续需要时再开启。",
    };
  }).sort((left, right) => {
    const leftIndex = CRAWLER_EXPECTED_SOURCES.indexOf(left.source_name);
    const rightIndex = CRAWLER_EXPECTED_SOURCES.indexOf(right.source_name);
    const normalizedLeft = leftIndex === -1 ? CRAWLER_EXPECTED_SOURCES.length : leftIndex;
    const normalizedRight = rightIndex === -1 ? CRAWLER_EXPECTED_SOURCES.length : rightIndex;
    return normalizedLeft === normalizedRight
      ? String(left.source_name || "").localeCompare(String(right.source_name || ""))
      : normalizedLeft - normalizedRight;
  });
}

function renderFailureStats(stats) {
  const codes = stats.codes || {};
  const items = stats.items || [];
  crawlerState.failureItems = new Map(items.map((item) => [String(item.id || ""), item]));
  if (crawlerRetryFailuresBtn) {
    const reachedThreshold = Number(stats.failed_articles || 0) >= CRAWLER_FAILURE_RETRY_THRESHOLD;
    crawlerRetryFailuresBtn.disabled = !reachedThreshold || !items.some((item) => canRetryFailureItem(item));
    crawlerRetryFailuresBtn.title = reachedThreshold
      ? "对当前展示的失败分组逐个重抓一次，仍失败则归档"
      : `待处理失败达到 ${CRAWLER_FAILURE_RETRY_THRESHOLD} 条后启用批量重抓`;
  }
  const archivedText = stats.archived_articles ? ` · 已归档 ${stats.archived_articles} 条` : "";
  crawlerFailureMeta.textContent = `${stats.failed_articles || 0} 条待处理失败 · ${stats.warning_articles || 0} 条警告 · 扫描 ${stats.runs_scanned || 0} 次运行${archivedText}`;
  const normalizedCodes = normalizeIssueCodeCounts(codes);
  const orderedCodes = Object.entries(normalizedCodes).sort((left, right) => Number(right[1]) - Number(left[1]));
  const knownCards = [
    ["connection_closed", normalizedCodes.connection_closed || 0],
    ["stale_link", normalizedCodes.stale_link || 0],
    ["blocked", normalizedCodes.blocked || 0],
    ["timeout", normalizedCodes.timeout || 0],
    ["parser_error", normalizedCodes.parser_error || 0],
  ].filter(([code, count]) => count || orderedCodes.length === 0);
  const cards = dedupeIssueCards(knownCards);
  const extraCodes = orderedCodes
    .filter(([code]) => code !== "empty_response" && !cards.some(([known]) => known === code))
    .slice(0, 4);
  crawlerFailureStats.innerHTML = `
    <div class="crawler-failure-overview">
      ${cards.concat(extraCodes).map(([code, count]) => `
        <div class="crawler-failure-code is-${escapeAttr(code)}">
          <span>${escapeHtml(issueLabel(code))}</span>
          <strong>${escapeHtml(String(count || 0))}</strong>
        </div>
      `).join("")}
    </div>
    <div class="crawler-failure-layout">
      <div class="crawler-failure-list">
        ${items.length ? items.map(renderFailureItem).join("") : `<div class="news-empty compact">最近运行没有失败 item。</div>`}
      </div>
      <div class="crawler-message-list">
        <h5>高频错误消息</h5>
        ${(stats.top_messages || []).length ? (stats.top_messages || []).map((item) => `
          <article>
            <strong>${escapeHtml(String(item.count || 0))} 次</strong>
            <p>${escapeHtml(item.message || "")}</p>
          </article>
        `).join("") : `<div class="news-empty compact">暂无错误消息。</div>`}
      </div>
    </div>
  `;
}

function normalizeIssueCodeCounts(codes) {
  return Object.entries(codes || {}).reduce((result, [code, count]) => {
    const normalized = normalizeIssueCode(code);
    result[normalized] = (result[normalized] || 0) + Number(count || 0);
    return result;
  }, {});
}

function dedupeIssueCards(cards) {
  const seen = new Set();
  return cards.filter(([code]) => {
    const normalized = normalizeIssueCode(code);
    if (seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function normalizeIssueCode(code) {
  const value = String(code || "").trim();
  if (value === "empty" || value === "empty_response" || value === "no_content") return "empty_response";
  return value || "unknown";
}

function renderFailureItem(item) {
  const url = item.article_url || "";
  const sampleText = (item.sample_urls || []).length > 1 ? `；样例 ${item.sample_urls.length} 条` : "";
  return `
    <article class="crawler-failure-item">
      <div class="crawler-failure-item-head">
        <div>
          <span class="crawler-run-status is-${escapeAttr(item.severity || "failed")}">${escapeHtml(issueLabel(item.code))}</span>
          <strong>${escapeHtml(String(item.count || 1))} 次</strong>
        </div>
        <small>${escapeHtml(sourceLabel(item.source_name))} · ${escapeHtml(formatDateTime(item.latest_at || item.started_at))} · ${escapeHtml(shortRunId(item.run_id))}${escapeHtml(sampleText)}</small>
      </div>
      <p>${escapeHtml(item.message || "")}</p>
      ${url ? `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>` : `<em>无文章链接</em>`}
      <div class="crawler-failure-item-actions">
        <button type="button" data-failure-action="retry" data-failure-id="${escapeAttr(item.id || "")}" ${canRetryFailureItem(item) ? "" : "disabled"}>重抓一次</button>
      </div>
    </article>
  `;
}

async function retryFailureItems(itemId = "") {
  const items = itemId
    ? [crawlerState.failureItems.get(String(itemId))].filter(Boolean)
    : [...crawlerState.failureItems.values()].filter(canRetryFailureItem).slice(0, 20);
  if (!items.length) return;
  const label = itemId ? "重抓这个失败新闻分组" : `重抓当前 ${items.length} 个失败新闻分组`;
  if (typeof approveDataFetch === "function" && !approveDataFetch(label)) return;
  setFailureRetryBusy(true, "正在重抓失败 item...");
  const totals = { retried: 0, recovered: 0, archived: 0 };
  try {
    for (const item of items) {
      const response = await fetch("/api/admin/news-crawler/failure-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "retry", approved: true, item }),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.error || "失败 item 重抓失败");
      totals.retried += Number(payload.retried || 0);
      totals.recovered += Number(payload.recovered || 0);
      totals.archived += Number(payload.archived || 0);
    }
    setFailureRetryBusy(false, `重抓完成：处理 ${totals.retried} 条，恢复 ${totals.recovered} 条，归档 ${totals.archived} 条。`);
    await loadCrawlerStatus();
  } catch (error) {
    setFailureRetryBusy(false, `重抓失败：${error.message}`);
  }
}

function canRetryFailureItem(item) {
  return item && item.source_name === "tonghuashun" && ((item.sample_urls || []).length || item.article_url);
}

function setFailureRetryBusy(busy, text) {
  if (crawlerRetryFailuresBtn) {
    crawlerRetryFailuresBtn.disabled = busy;
    crawlerRetryFailuresBtn.textContent = busy ? "重抓中..." : "重抓可处理失败";
  }
  crawlerFailureMeta.textContent = text;
}

function renderCrawlerRuns(runs) {
  if (!runs.length) {
    crawlerRunsTable.innerHTML = `<tbody><tr><td class="news-empty">尚无采集运行记录。</td></tr></tbody>`;
    return;
  }
  crawlerRunsTable.innerHTML = `
    <thead><tr>
      <th>来源</th><th>状态</th><th>开始时间</th><th>耗时</th>
      <th>发现</th><th>新的</th><th>入库</th><th>失败</th>
    </tr></thead>
    <tbody>${runs.map((item, index) => `
      <tr class="crawler-run-row" tabindex="0" data-run-index="${index}">
        <td><strong>${escapeHtml(sourceLabel(item.source_name))}</strong><small>${escapeHtml(shortRunId(item.run_id))}</small></td>
        <td><span class="crawler-run-status is-${escapeAttr(item.status || "unknown")}">${escapeHtml(statusLabel(item.status))}</span></td>
        <td>${escapeHtml(formatDateTime(item.started_at))}</td>
        <td>${escapeHtml(runDuration(item))}</td>
        <td>${escapeHtml(item.discovered || 0)}</td>
        <td>${escapeHtml(item.inserted || 0)}</td>
        <td>${escapeHtml(storedCount(item))}</td>
        <td>${escapeHtml(item.failed || 0)}</td>
      </tr>
    `).join("")}</tbody>
  `;
  crawlerRunsTable.querySelectorAll(".crawler-run-row").forEach((row) => {
    const open = () => showRunDetail(runs[Number(row.dataset.runIndex)]);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
}

function showRunDetail(item) {
  const issues = [...(item.errors || []), ...(item.warnings || [])];
  crawlerRunDetailMeta.textContent = `${sourceLabel(item.source_name)} · ${item.run_id || "-"}`;
  crawlerRunDetail.innerHTML = `
    <dl class="crawler-detail-facts">
      <div><dt>状态</dt><dd>${escapeHtml(statusLabel(item.status))}</dd></div>
      <div><dt>开始</dt><dd>${escapeHtml(formatDateTime(item.started_at))}</dd></div>
      <div><dt>结束</dt><dd>${escapeHtml(formatDateTime(item.finished_at))}</dd></div>
      <div><dt>耗时</dt><dd>${escapeHtml(runDuration(item))}</dd></div>
    </dl>
    <section><h5>运行指标</h5><pre>${escapeHtml(JSON.stringify(item.metrics || {}, null, 2))}</pre></section>
    <section><h5>错误与警告</h5>${issues.length ? `<div class="crawler-issue-list">${issues.map((issue) => `
      <article><strong>${escapeHtml(issue.code || "error")}</strong><p>${escapeHtml(issue.message || "")}</p>${issue.article_url ? `<a href="${escapeAttr(issue.article_url)}" target="_blank" rel="noreferrer">${escapeHtml(issue.article_url)}</a>` : ""}</article>
    `).join("")}</div>` : `<div class="news-empty compact">本次运行没有记录错误或警告。</div>`}</section>
  `;
  crawlerRunDetailCard.hidden = false;
  crawlerRunDetailCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeRunDetail() {
  crawlerRunDetailCard.hidden = true;
  crawlerRunDetail.innerHTML = "";
}

function syncAutoRefresh() {
  window.clearInterval(crawlerState.timer);
  crawlerState.timer = crawlerAutoRefresh.checked ? window.setInterval(loadCrawlerStatus, 30000) : null;
}

function sourceLabel(value) {
  return CRAWLER_SOURCE_CONFIG[value]?.label || value || "未知来源";
}

function sourceInitial(value) {
  return CRAWLER_SOURCE_CONFIG[value]?.initial || String(value || "?").slice(0, 1).toUpperCase();
}

function healthLabel(status) {
  return { online: "正常", warning: "有异常", offline: "不可用", maintenance: "暂停维护", paused: "自动暂停" }[status] || "未知";
}

function statusLabel(status) {
  return { succeeded: "成功", partial: "部分成功", failed: "失败", running: "运行中", queued: "排队中", cancelled: "已取消" }[status] || status || "-";
}

function issueLabel(code) {
  const normalized = normalizeIssueCode(code);
  return {
    empty_response: "返回空",
    connection_closed: "主动断连",
    stale_link: "旧链接 / 404",
    blocked: "反爬拦截",
    credential_expired: "凭据过期",
    timeout: "超时",
    parser_error: "解析失败",
    image_only: "图片正文",
  }[normalized] || normalized || "未知原因";
}

function shortRunId(value) {
  return value ? `#${String(value).slice(0, 8)}` : "-";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date);
}

function runDuration(item) {
  if (!item.started_at || !item.finished_at) return item.status === "running" ? "进行中" : "-";
  return formatDuration((new Date(item.finished_at) - new Date(item.started_at)) / 1000);
}

function storedCount(item) {
  return (Number(item.inserted) || 0) + (Number(item.updated) || 0);
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (value < 1) return `${Math.round(value * 1000)}ms`;
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`;
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
