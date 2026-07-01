const newsMeta = document.querySelector("#newsMeta");
const newsStats = document.querySelector("#newsStats");
const newsDistribution = document.querySelector("#newsDistribution");
const newsList = document.querySelector("#newsList");
const newsSearchInput = document.querySelector("#newsSearchInput");
const newsPublisherSelect = document.querySelector("#newsPublisherSelect");
const newsTypeSelect = document.querySelector("#newsTypeSelect");
const newsDaysSelect = document.querySelector("#newsDaysSelect");
const newsPageSizeSelect = document.querySelector("#newsPageSizeSelect");
const newsRefreshBtn = document.querySelector("#newsRefreshBtn");
const newsExportBtn = document.querySelector("#newsExportBtn");
const newsRefetchBtn = document.querySelector("#newsRefetchBtn");
const newsRefetchStatus = document.querySelector("#newsRefetchStatus");
const newsResetBtn = document.querySelector("#newsResetBtn");
const newsPrevBtn = document.querySelector("#newsPrevBtn");
const newsNextBtn = document.querySelector("#newsNextBtn");
const newsPageInfo = document.querySelector("#newsPageInfo");
const stockDataMeta = document.querySelector("#stockDataMeta");
const stockDataStats = document.querySelector("#stockDataStats");
const stockDataTable = document.querySelector("#stockDataTable");
const stockDataSearchInput = document.querySelector("#stockDataSearchInput");
const stockDataSortSelect = document.querySelector("#stockDataSortSelect");
const dataSourceMeta = document.querySelector("#dataSourceMeta");
const dataSourceStats = document.querySelector("#dataSourceStats");
const dataSourceProviders = document.querySelector("#dataSourceProviders");
const standardDataTable = document.querySelector("#standardDataTable");

const state = {
  page: 1,
  pages: 1,
  total: 0,
  loadedFilters: false,
  items: [],
  translations: {},
  languageByArticle: {},
  translating: {},
};

const stockState = {
  items: [],
  filteredItems: [],
  count: 0,
  totalDatasetRows: 0,
  totalMinuteRows: 0,
};

const dataSourceState = {
  providers: [],
  types: [],
  coverage: {},
  summary: {},
};
const STOCK_PROVIDER_KEYS = new Set(["stock_data", "eastmoney", "akshare", "tushare", "tencent_fallback"]);
const STOCK_STANDARD_CATEGORIES = new Set(["个股"]);
const hasNewsLibrary = Boolean(newsList);
const hasStockLibrary = Boolean(stockDataTable);
const newsDataConsolePage = document.body?.dataset.dataConsolePage === "true";

let searchTimer = null;
let stockSearchTimer = null;
let newsPageAdminReadonly = false;

document.addEventListener("DOMContentLoaded", async () => {
  await loadAdminSession();
  bindEvents();
  if (hasStockLibrary) {
    loadDataSources();
    loadStockData();
  }
  if (hasNewsLibrary) {
    loadNews();
  }
  applyNewsAdminReadonlyMode();
});

async function loadAdminSession() {
  try {
    const response = await fetch("/api/session");
    const payload = await readApiPayload(response, "读取会话失败");
    if (!payload.authenticated) {
      window.location.href = "/login";
      return;
    }
    const role = payload.role || "";
    const canViewDataConsole = newsDataConsolePage && role === "user";
    if (!["admin", "admin_readonly"].includes(role) && !canViewDataConsole) {
      window.location.href = "/";
      return;
    }
    newsPageAdminReadonly = role !== "admin";
  } catch {
    window.location.href = "/login";
  }
}

function applyNewsAdminReadonlyMode() {
  if (!newsPageAdminReadonly) return;
  if (!document.querySelector(".admin-readonly-banner")) {
    const banner = document.createElement("div");
    banner.className = "admin-readonly-banner";
    banner.textContent = "数据查看模式：可以查看股票数据和新闻数据，但补抓、翻译和刷新入库操作已禁用。";
    document.querySelector(".admin-workspace")?.prepend(banner);
  }
  [newsRefetchBtn].forEach((node) => {
    if (node) node.disabled = true;
  });
}

function bindEvents() {
  newsRefreshBtn?.addEventListener("click", () => {
    if (hasStockLibrary) {
      loadDataSources();
      loadStockData();
    }
    if (hasNewsLibrary) {
      loadNews();
    }
  });
  newsRefetchBtn?.addEventListener("click", () => runNewsRefetch());
  newsExportBtn?.addEventListener("click", () => exportCurrentPage());
  newsList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-news-translation-toggle]");
    if (!button) return;
    toggleNewsTranslation(button.dataset.newsTranslationToggle || "");
  });
  newsResetBtn?.addEventListener("click", () => {
    newsSearchInput.value = "";
    newsPublisherSelect.value = "";
    newsTypeSelect.value = "";
    newsDaysSelect.value = "30";
    newsPageSizeSelect.value = "20";
    state.page = 1;
    if (hasNewsLibrary) loadNews();
  });
  newsPrevBtn?.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      if (hasNewsLibrary) loadNews();
    }
  });
  newsNextBtn?.addEventListener("click", () => {
    if (state.page < state.pages) {
      state.page += 1;
      if (hasNewsLibrary) loadNews();
    }
  });
  [newsPublisherSelect, newsTypeSelect, newsDaysSelect, newsPageSizeSelect].forEach((control) => {
    control?.addEventListener("change", () => {
      state.page = 1;
      if (hasNewsLibrary) loadNews();
    });
  });
  newsSearchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.page = 1;
      if (hasNewsLibrary) loadNews();
    }, 280);
  });
  stockDataSearchInput?.addEventListener("input", () => {
    window.clearTimeout(stockSearchTimer);
    stockSearchTimer = window.setTimeout(renderStockData, 160);
  });
  stockDataSortSelect?.addEventListener("change", renderStockData);
}

async function loadDataSources() {
  if (!dataSourceMeta) return;
  dataSourceMeta.textContent = "正在读取数据源...";
  try {
    const response = await fetch("/api/admin/data-sources");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "读取数据源失败");
    }
    dataSourceState.providers = (payload.providers || []).filter((item) => STOCK_PROVIDER_KEYS.has(item.key));
    dataSourceState.types = (payload.types || []).filter((item) => STOCK_STANDARD_CATEGORIES.has(item.category));
    dataSourceState.coverage = payload.coverage || {};
    dataSourceState.summary = {
      provider_count: dataSourceState.providers.length,
      active_count: dataSourceState.providers.filter((item) => item.status === "active").length,
      archived_count: dataSourceState.providers.filter((item) => item.status === "archived").length,
      planned_count: dataSourceState.providers.filter((item) => item.status === "planned").length,
      standard_type_count: dataSourceState.types.length,
    };
    renderDataSources();
    dataSourceMeta.textContent = `已注册 ${dataSourceState.summary.provider_count || 0} 个股票来源，${dataSourceState.summary.standard_type_count || 0} 类股票标准数据`;
  } catch (error) {
    dataSourceMeta.textContent = `读取失败：${error.message}`;
    if (dataSourceProviders) dataSourceProviders.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderDataSources() {
  renderDataSourceStats();
  renderProviderGrid();
  renderStandardDataTable();
}

function renderDataSourceStats() {
  if (!dataSourceStats) return;
  const summary = dataSourceState.summary || {};
  const coverage = dataSourceState.coverage || {};
  const cards = [
    ["活跃来源", summary.active_count ?? 0, "当前可用于新数据"],
    ["封存来源", summary.archived_count ?? 0, "保留旧数据，不默认抓取"],
    ["本地股票", coverage.stock_count ?? 0, "数据库资料包"],
    ["标准类型", summary.standard_type_count ?? 0, "股票 / 财务"],
  ];
  dataSourceStats.innerHTML = cards
    .map(
      ([label, value, note]) => `
        <div>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
          <p>${escapeHtml(note)}</p>
        </div>
      `,
    )
    .join("");
}

function renderProviderGrid() {
  if (!dataSourceProviders) return;
  dataSourceProviders.innerHTML = dataSourceState.providers
    .map((provider) => {
      const status = provider.status || "unknown";
      const statusText = {
        active: "启用",
        archived: "封存",
        planned: "待接入",
        disabled: "停用",
      }[status] || status;
      const capabilities = (provider.capabilities || []).slice(0, 5).join(" / ");
      return `
        <article class="data-source-provider ${escapeAttr(`is-${status}`)}">
          <div>
            <span class="data-source-status">${escapeHtml(statusText)}</span>
            <h5>${escapeHtml(provider.label || provider.key)}</h5>
            <p>${escapeHtml(provider.description || "")}</p>
          </div>
          <dl>
            <div><dt>配置</dt><dd>${provider.configured ? "已具备" : "未配置"}</dd></div>
            <div><dt>优先级</dt><dd>${escapeHtml(String(provider.priority || "-"))}</dd></div>
          </dl>
          <small>${escapeHtml(capabilities || "暂无能力映射")}</small>
          ${provider.limitations ? `<em>${escapeHtml(provider.limitations)}</em>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderStandardDataTable() {
  if (!standardDataTable) return;
  const rows = dataSourceState.types || [];
  if (!rows.length) {
    standardDataTable.innerHTML = `<tbody><tr><td class="news-empty">暂无标准数据类型。</td></tr></tbody>`;
    return;
  }
  standardDataTable.innerHTML = `
    <thead>
      <tr>
        <th>类型</th>
        <th>分类</th>
        <th>主来源</th>
        <th>优先级</th>
        <th>状态</th>
      </tr>
    </thead>
    <tbody>
      ${rows.map(renderStandardDataRow).join("")}
    </tbody>
  `;
}

function renderStandardDataRow(item) {
  const status = item.needs_provider ? "缺少活跃来源" : "可用";
  const primary = item.primary_provider || "-";
  return `
    <tr>
      <td>
        <strong>${escapeHtml(item.label || item.key)}</strong>
        <p>${escapeHtml(item.description || "")}</p>
      </td>
      <td>${escapeHtml(item.category || "-")}</td>
      <td>${escapeHtml(primary)}</td>
      <td>${escapeHtml((item.priority || []).join(" > ") || "-")}</td>
      <td><span class="data-type-status ${item.needs_provider ? "is-missing" : "is-ok"}">${escapeHtml(status)}</span></td>
    </tr>
  `;
}

async function loadStockData() {
  if (!stockDataMeta || !stockDataTable) return;
  stockDataMeta.textContent = "正在读取本地资料包...";
  try {
    const response = await fetch("/api/admin/data-library");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "读取本地数据失败");
    }
    stockState.items = payload.items || [];
    stockState.count = payload.count || 0;
    stockState.totalDatasetRows = payload.total_dataset_rows || 0;
    stockState.totalMinuteRows = payload.total_minute_rows || 0;
    renderStockData();
    renderStockStats();
    stockDataMeta.textContent = `已同步 ${stockState.count} 只股票资料包`;
  } catch (error) {
    stockState.items = [];
    stockState.filteredItems = [];
    stockDataMeta.textContent = `读取失败：${error.message}`;
    stockDataTable.innerHTML = `<tbody><tr><td class="news-empty is-error">${escapeHtml(error.message)}</td></tr></tbody>`;
    renderStockStats();
  }
}

function renderStockStats() {
  if (!stockDataStats) return;
  const latest = formatStockTimestamp(stockState.items[0]?.updated_at);
  const cards = [
    ["股票资料包", stockState.count, "数据库资料包"],
    ["数据集总行数", formatNumber(stockState.totalDatasetRows), "按 metadata 统计"],
    ["分钟行情行数", formatNumber(stockState.totalMinuteRows), "MongoDB 引用"],
    ["最近更新", latest, "按 updated_at 排序"],
  ];
  stockDataStats.innerHTML = cards
    .map(
      ([label, value, note]) => `
        <div>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
          <p>${escapeHtml(note)}</p>
        </div>
      `,
    )
    .join("");
}

function renderStockData() {
  if (!stockDataTable) return;
  const query = (stockDataSearchInput?.value || "").trim().toLowerCase();
  const sortKey = stockDataSortSelect?.value || "updated_at";
  const items = stockState.items
    .filter((item) => {
      if (!query) return true;
      return [item.ts_code, item.name, item.industry, item.market]
        .some((value) => String(value || "").toLowerCase().includes(query));
    })
    .sort((left, right) => compareStockRows(left, right, sortKey));
  stockState.filteredItems = items;
  if (!items.length) {
    stockDataTable.innerHTML = `<tbody><tr><td class="news-empty">当前条件下没有本地股票资料包。</td></tr></tbody>`;
    return;
  }
  stockDataTable.innerHTML = `
    <thead>
      <tr>
        <th>股票</th>
        <th>行业 / 市场</th>
        <th>更新时间</th>
        <th>日期范围</th>
        <th>数据集</th>
        <th>分钟行数</th>
        <th>异常</th>
      </tr>
    </thead>
    <tbody>
      ${items.map(renderStockRow).join("")}
    </tbody>
  `;
}

function renderStockRow(item) {
  const dateRange = item.daily_date_range || item.date_range || {};
  const rangeText = formatStockDateRange(dateRange);
  return `
    <tr>
      <td>
        <strong>${escapeHtml(item.name || "-")}</strong>
        <code>${escapeHtml(item.ts_code || "-")}</code>
      </td>
      <td>${escapeHtml([item.industry, item.market].filter(Boolean).join(" / ") || "-")}</td>
      <td>${escapeHtml(formatStockTimestamp(item.updated_at))}</td>
      <td>${escapeHtml(rangeText)}</td>
      <td>${escapeHtml(String(item.dataset_count || 0))}</td>
      <td>${escapeHtml(formatNumber(item.minute_rows || 0))}</td>
      <td>${escapeHtml(String(item.fetch_error_count || 0))}</td>
    </tr>
  `;
}

function formatStockDateRange(dateRange) {
  const start = formatStockDate(dateRange?.start_date);
  const end = formatStockDate(dateRange?.end_date);
  if (start && end) return `${start} - ${end}`;
  return start || end || "-";
}

function formatStockDate(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (!match) return text;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function formatStockTimestamp(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (!match) return text || "-";
  const [, , month, day, hour, minute] = match;
  return `${Number(month)}月${Number(day)}日 ${hour}:${minute}`;
}

function compareStockRows(left, right, key) {
  if (key === "ts_code") return String(left.ts_code || "").localeCompare(String(right.ts_code || ""));
  if (key === "dataset_count" || key === "minute_rows") {
    return Number(right[key] || 0) - Number(left[key] || 0);
  }
  return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
}

async function runNewsRefetch() {
  if (newsPageAdminReadonly) return;
  const source = newsPublisherSelect.value || "all";
  const sourceText = source === "all" ? "全部可用新闻源" : newsPublisherLabel(source);
  const confirmed = window.confirm(`将通过 NewsCrawler 重新抓取 ${sourceText} 的最新新闻，并补充写入 MongoDB 新闻库。确认执行？`);
  if (!confirmed) return;
  newsRefetchBtn.disabled = true;
  if (newsRefetchStatus) newsRefetchStatus.textContent = "补抓状态：正在启动...";
  try {
    const payload = {
      approved: true,
      source,
      type: newsTypeSelect.value || "",
      request_delay: 0.5,
    };
    const response = await fetch("/api/admin/news-library/refetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readNewsAdminPayload(response, "启动新闻补抓失败");
    renderNewsRefetchStatus(result.refetch || {});
    await pollNewsRefetch();
  } catch (error) {
    if (newsRefetchStatus) newsRefetchStatus.textContent = `补抓失败：${error.message}`;
  } finally {
    newsRefetchBtn.disabled = false;
  }
}

async function pollNewsRefetch() {
  for (let i = 0; i < 60; i += 1) {
    await sleep(2000);
    const response = await fetch("/api/admin/news-library/refetch");
    const payload = await readNewsAdminPayload(response, "读取新闻补抓状态失败");
    const refetch = payload.refetch || {};
    renderNewsRefetchStatus(refetch);
    if (!["running", "queued"].includes(refetch.status)) {
      await loadNews();
      return;
    }
  }
}

function renderNewsRefetchStatus(refetch) {
  if (!newsRefetchStatus) return;
  const status = refetch.status || "idle";
  if (status === "running") {
    newsRefetchStatus.textContent = `补抓状态：运行中 · ${refetch.source || "all"} · ${refetch.started_at || "-"}`;
    return;
  }
  if (status === "succeeded") {
    newsRefetchStatus.textContent = `补抓状态：完成 · ${refetch.finished_at || "-"}，已刷新新闻库。`;
    return;
  }
  if (status === "failed") {
    newsRefetchStatus.textContent = `补抓状态：失败 · ${refetch.error || "请查看任务日志"}`;
    return;
  }
  newsRefetchStatus.textContent = "补抓状态：空闲";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function readNewsAdminPayload(response, fallbackMessage) {
  const payload = await response.json();
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("登录状态已失效");
  }
  if (!response.ok || payload.ok === false) throw new Error(payload.error || fallbackMessage);
  return payload;
}

async function loadNews() {
  if (!hasNewsLibrary || !newsMeta || !newsList) return;
  newsMeta.textContent = "正在读取 MongoDB 新闻库...";
  if (newsRefreshBtn) newsRefreshBtn.disabled = true;
  try {
    const params = new URLSearchParams({
      page: String(state.page),
      page_size: newsPageSizeSelect.value || "20",
      days: newsDaysSelect.value || "30",
    });
    if (newsSearchInput.value.trim()) params.set("q", newsSearchInput.value.trim());
    if (newsPublisherSelect.value) params.set("publisher", newsPublisherSelect.value);
    if (newsTypeSelect.value) params.set("type", newsTypeSelect.value);

    const response = await fetch(`/api/admin/news-library?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || payload.ok === false || payload.enabled === false) {
      throw new Error(payload.error || "读取新闻库失败");
    }

    state.page = payload.page || 1;
    state.pages = payload.pages || 1;
    state.total = payload.total || 0;
    state.items = payload.items || [];
    preloadCachedTranslations(state.items);
    renderFilters(payload.filters || {});
    renderStats(payload.stats || {}, payload);
    renderDistribution(payload.stats || {});
    renderList(state.items);
    renderPager();
    newsMeta.textContent = `${payload.database}.${payload.collection}，当前筛选 ${state.total} 篇`;
  } catch (error) {
    newsMeta.textContent = `读取失败：${error.message}`;
    state.items = [];
    if (newsList) newsList.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  } finally {
    if (newsRefreshBtn) newsRefreshBtn.disabled = false;
  }
}

function preloadCachedTranslations(items) {
  (items || []).forEach((item) => {
    const articleId = String(item.article_id || "");
    if (articleId && item.translation && !state.translations[articleId]) {
      state.translations[articleId] = item.translation;
    }
  });
}

function renderDistribution(stats) {
  if (!newsDistribution) return;
  const publisherItems = (stats.by_publisher || []).map((item) => ({
    label: newsPublisherLabel(item.publisher),
    count: item.count || 0,
  }));
  const typeItems = (stats.by_type || []).map((item) => ({
    label: item.type || "-",
    count: item.count || 0,
  }));
  newsDistribution.innerHTML = [
    renderDistributionPanel("来源分布", publisherItems),
    renderDistributionPanel("分类分布", typeItems),
  ].join("");
}

function renderDistributionPanel(title, items) {
  const maxCount = Math.max(1, ...items.map((item) => item.count));
  const rows = items.length
    ? items
        .map((item) => {
          const width = Math.max(4, Math.round((item.count / maxCount) * 100));
          return `
            <div class="news-dist-row">
              <span>${escapeHtml(item.label)}</span>
              <span class="news-dist-track">
                <span style="width: ${width}%"></span>
              </span>
              <strong>${escapeHtml(String(item.count))}</strong>
            </div>
          `;
        })
        .join("")
    : `<div class="news-empty compact">暂无数据</div>`;
  return `
    <section class="admin-card news-dist-card">
      <div class="admin-card-head">
        <h4>${escapeHtml(title)}</h4>
        <span>Top</span>
      </div>
      <div class="news-dist-body">${rows}</div>
    </section>
  `;
}

function renderFilters(filters) {
  if (!newsPublisherSelect || !newsTypeSelect) return;
  const currentPublisher = newsPublisherSelect.value;
  const currentType = newsTypeSelect.value;
  fillSelect(newsPublisherSelect, "全部来源", filters.publishers || [], currentPublisher);
  fillSelect(newsTypeSelect, "全部分类", filters.types || [], currentType);
}

function fillSelect(select, label, values, currentValue) {
  if (!select) return;
  const options = [`<option value="">${label}</option>`].concat(
    values.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(newsPublisherLabel(value))}</option>`),
  );
  select.innerHTML = options.join("");
  select.value = values.includes(currentValue) ? currentValue : "";
}

function renderStats(stats, payload) {
  if (!newsStats) return;
  const publisherLines = (stats.by_publisher || [])
    .slice(0, 3)
    .map((item) => `${newsPublisherLabel(item.publisher)} ${item.count || 0}`)
    .join(" / ");
  const cards = [
    ["总文章", stats.total ?? "-", "MongoDB 当前文章总数"],
    ["今日新增", stats.today ?? "-", "按 time 字段统计"],
    ["最新时间", formatNewsDateTime(stats.latest_time), "新闻库最新发布时间"],
    ["当前筛选", payload.total ?? "-", publisherLines || "暂无来源分布"],
  ];
  newsStats.innerHTML = cards
    .map(
      ([label, value, note]) => `
        <div>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
          <p>${escapeHtml(note)}</p>
        </div>
      `,
    )
    .join("");
}

function formatNewsDateTime(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})/);
  if (compact) {
    return `${Number(compact[2])}月${Number(compact[3])}日 ${compact[4]}:${compact[5]}`;
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function renderList(items) {
  if (!items.length) {
    newsList.innerHTML = `<div class="news-empty">当前条件下没有新闻。</div>`;
    return;
  }
  newsList.innerHTML = items.map(renderItem).join("");
}

function renderItem(item) {
  const url = item.url ? `<a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">原文</a>` : "";
  const articleId = String(item.article_id || "");
  const translation = articleId ? state.translations[articleId] : null;
  const language = articleId ? state.languageByArticle[articleId] || "source" : "source";
  const isChinese = language === "zh" && translation;
  const isTranslating = Boolean(articleId && state.translating[articleId]);
  const hasCachedTranslation = Boolean(translation);
  const title = isChinese ? translation.title || item.title : item.title;
  const summary = isChinese ? translation.summary || item.summary : item.excerpt || item.summary;
  const body = renderArticleBody(item, translation, isChinese);
  const translationToggle =
    item.publisher === "guardian" && articleId
      ? `<button class="news-translation-toggle ${isChinese ? "is-active" : ""}" type="button" data-news-translation-toggle="${escapeAttr(articleId)}" ${isTranslating || newsPageAdminReadonly ? "disabled" : ""}>${escapeHtml(isTranslating ? "翻译中" : isChinese ? "对照" : hasCachedTranslation ? "已翻译" : "中文")}</button>`
      : "";
  const translationMeta = isChinese && translation.translated_at ? `<span>百度翻译 ${escapeHtml(translation.translated_at)}</span>` : "";
  return `
    <article class="news-item">
      <div class="news-item-meta">
        <span>${escapeHtml(newsPublisherLabel(item.publisher))}</span>
        <span>${escapeHtml(item.type || "-")}</span>
        <span>${escapeHtml(item.time || "-")}</span>
        ${url}
        ${translationToggle}
        ${translationMeta}
      </div>
      <h2>${escapeHtml(title || "无标题")}</h2>
      <p>${escapeHtml(summary || "暂无摘要")}</p>
      ${body}
    </article>
  `;
}

function renderArticleBody(item, translation, isChinese) {
  if (isChinese && translation) {
    return `
      <details class="news-compare-details" open>
        <summary>段落对照</summary>
        ${renderParagraphComparison(item.content || "", translation.content || "")}
      </details>
    `;
  }
  return `
    <details>
      <summary>展开正文</summary>
      <p>${escapeHtml(item.content || "暂无正文")}</p>
    </details>
  `;
}

function renderParagraphComparison(sourceContent, translatedContent) {
  const sourceParagraphs = splitArticleParagraphs(sourceContent);
  const translatedParagraphs = splitArticleParagraphs(translatedContent);
  const count = Math.max(sourceParagraphs.length, translatedParagraphs.length, 1);
  const rows = Array.from({ length: count }, (_, index) => {
    const source = sourceParagraphs[index] || "";
    const translated = translatedParagraphs[index] || "";
    return `
      <div class="news-compare-row">
        <div class="news-compare-cell is-source">
          <span>原文 ${index + 1}</span>
          <p>${escapeHtml(source || "-")}</p>
        </div>
        <div class="news-compare-cell is-translation">
          <span>译文 ${index + 1}</span>
          <p>${escapeHtml(translated || "-")}</p>
        </div>
      </div>
    `;
  }).join("");
  return `<div class="news-compare-grid">${rows}</div>`;
}

function splitArticleParagraphs(value) {
  return String(value || "")
    .split(/\n{2,}/)
    .map((part) => part.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean);
}

async function toggleNewsTranslation(articleId) {
  if (!articleId || newsPageAdminReadonly) return;
  const current = state.languageByArticle[articleId] || "source";
  if (current === "zh") {
    state.languageByArticle[articleId] = "source";
    renderList(state.items);
    return;
  }
  if (!state.translations[articleId]) {
    const confirmed =
      typeof approveDataFetch === "function"
        ? approveDataFetch("调用百度翻译生成 Guardian 中文译文")
        : window.confirm("调用百度翻译生成 Guardian 中文译文，确认执行？");
    if (!confirmed) return;
    state.translating[articleId] = true;
    renderList(state.items);
    try {
      const response = await fetch("/api/admin/news-library/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, article_id: articleId }),
      });
      const payload = await readNewsAdminPayload(response, "翻译失败");
      state.translations[articleId] = payload.translation || {};
    } catch (error) {
      window.alert(`翻译失败：${error.message}`);
      return;
    } finally {
      delete state.translating[articleId];
    }
  }
  state.languageByArticle[articleId] = "zh";
  renderList(state.items);
}

function newsPublisherLabel(value) {
  return {
    tonghuashun: "同花顺新闻",
    guardian: "Guardian",
    bloomberg: "Bloomberg",
  }[value] || value || "-";
}

function renderPager() {
  if (!newsPageInfo || !newsPrevBtn || !newsNextBtn) return;
  newsPageInfo.textContent = `第 ${state.page} / ${state.pages} 页，共 ${state.total} 篇`;
  newsPrevBtn.disabled = state.page <= 1;
  newsNextBtn.disabled = state.page >= state.pages;
}

function exportCurrentPage() {
  if (!hasNewsLibrary || !state.items.length) return;
  const headers = ["time", "publisher", "type", "title", "source", "url", "summary"];
  const rows = state.items.map((item) => headers.map((key) => csvCell(item[key] || "")));
  const csv = [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `news-page-${state.page}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
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
