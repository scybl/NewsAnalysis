const crawlerPageMeta = document.querySelector("#crawlerPageMeta");
const crawlerHealthGrid = document.querySelector("#crawlerHealthGrid");
const crawlerHealthMeta = document.querySelector("#crawlerHealthMeta");
const crawlerFailureMeta = document.querySelector("#crawlerFailureMeta");
const crawlerFailureStats = document.querySelector("#crawlerFailureStats");
const crawlerRunsTable = document.querySelector("#crawlerRunsTable");
const crawlerRefreshBtn = document.querySelector("#crawlerRefreshBtn");
const crawlerAutoRefresh = document.querySelector("#crawlerAutoRefresh");
const crawlerRunLimit = document.querySelector("#crawlerRunLimit");
const crawlerRunDetailCard = document.querySelector("#crawlerRunDetailCard");
const crawlerRunDetailMeta = document.querySelector("#crawlerRunDetailMeta");
const crawlerRunDetail = document.querySelector("#crawlerRunDetail");
const crawlerRunDetailClose = document.querySelector("#crawlerRunDetailClose");

const crawlerState = { payload: null, timer: null };

document.addEventListener("DOMContentLoaded", () => {
  crawlerRefreshBtn?.addEventListener("click", loadCrawlerStatus);
  crawlerRunLimit?.addEventListener("change", loadCrawlerStatus);
  crawlerAutoRefresh?.addEventListener("change", syncAutoRefresh);
  crawlerRunDetailClose?.addEventListener("click", closeRunDetail);
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

  const health = payload.health || [];
  const healthWithPlaceholders = withCrawlerPlaceholders(health);
  crawlerHealthMeta.textContent = healthWithPlaceholders.length ? `${healthWithPlaceholders.length} 个来源投影` : "尚无投影";
  crawlerHealthGrid.innerHTML = healthWithPlaceholders.length
    ? healthWithPlaceholders.map(renderCrawlerHealth).join("")
    : `<div class="news-empty compact">尚无来源运行记录。NewsCrawler 完成首次采集后会显示。</div>`;
  renderFailureStats(payload.failure_stats || {});
  renderCrawlerRuns(runs);
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
  if (!items.some((item) => item.source_name === "politico")) {
    items.push({
      source_name: "politico",
      status: "offline",
      recent_success_rate: 0,
      consecutive_failures: 0,
      last_inserted_count: 0,
      average_duration_seconds: 0,
      last_success_at: "",
      last_failure_at: "",
      latest_error: "占位数据源，暂未接入采集。",
      placeholder: true,
    });
  }
  return items;
}

function renderFailureStats(stats) {
  const codes = stats.codes || {};
  const items = stats.items || [];
  crawlerFailureMeta.textContent = `${stats.failed_articles || 0} 条失败 · ${stats.warning_articles || 0} 条警告 · 扫描 ${stats.runs_scanned || 0} 次运行`;
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
  return `
    <article class="crawler-failure-item">
      <div class="crawler-failure-item-head">
        <span class="crawler-run-status is-${escapeAttr(item.severity || "failed")}">${escapeHtml(issueLabel(item.code))}</span>
        <small>${escapeHtml(sourceLabel(item.source_name))} · ${escapeHtml(formatDateTime(item.started_at))} · ${escapeHtml(shortRunId(item.run_id))}</small>
      </div>
      <p>${escapeHtml(item.message || "")}</p>
      ${url ? `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>` : `<em>无文章链接</em>`}
    </article>
  `;
}

function renderCrawlerRuns(runs) {
  if (!runs.length) {
    crawlerRunsTable.innerHTML = `<tbody><tr><td class="news-empty">尚无采集运行记录。</td></tr></tbody>`;
    return;
  }
  crawlerRunsTable.innerHTML = `
    <thead><tr>
      <th>来源</th><th>状态</th><th>开始时间</th><th>耗时</th>
      <th>发现 / 获取</th><th>新增 / 更新</th><th>跳过 / 失败</th>
    </tr></thead>
    <tbody>${runs.map((item, index) => `
      <tr class="crawler-run-row" tabindex="0" data-run-index="${index}">
        <td><strong>${escapeHtml(sourceLabel(item.source_name))}</strong><small>${escapeHtml(shortRunId(item.run_id))}</small></td>
        <td><span class="crawler-run-status is-${escapeAttr(item.status || "unknown")}">${escapeHtml(statusLabel(item.status))}</span></td>
        <td>${escapeHtml(formatDateTime(item.started_at))}</td>
        <td>${escapeHtml(runDuration(item))}</td>
        <td>${escapeHtml(`${item.discovered || 0} / ${item.fetched || 0}`)}</td>
        <td>${escapeHtml(`${item.inserted || 0} / ${item.updated || 0}`)}</td>
        <td>${escapeHtml(`${item.skipped || 0} / ${item.failed || 0}`)}</td>
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
  return { tonghuashun: "同花顺", guardian: "Guardian", bloomberg: "Bloomberg", politico: "Politico" }[value] || value || "未知来源";
}

function sourceInitial(value) {
  return { tonghuashun: "同", guardian: "G", bloomberg: "B", politico: "P" }[value] || String(value || "?").slice(0, 1).toUpperCase();
}

function healthLabel(status) {
  return { online: "正常", warning: "有异常", offline: "不可用" }[status] || "未知";
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

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (value < 1) return `${Math.round(value * 1000)}ms`;
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`;
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
