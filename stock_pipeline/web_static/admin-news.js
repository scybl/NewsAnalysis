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
const kaipanlaMeta = document.querySelector("#kaipanlaMeta");
const kaipanlaFeatureSelect = document.querySelector("#kaipanlaFeatureSelect");
const kaipanlaParamsInput = document.querySelector("#kaipanlaParamsInput");
const kaipanlaValidateBtn = document.querySelector("#kaipanlaValidateBtn");
const kaipanlaRunBtn = document.querySelector("#kaipanlaRunBtn");
const kaipanlaOutput = document.querySelector("#kaipanlaOutput");

const state = {
  page: 1,
  pages: 1,
  total: 0,
  loadedFilters: false,
  items: [],
};

const stockState = {
  items: [],
  filteredItems: [],
  count: 0,
  totalDatasetRows: 0,
  totalMinuteRows: 0,
};

const kaipanlaState = {
  features: [],
};

const dataSourceState = {
  providers: [],
  types: [],
  coverage: {},
  summary: {},
};

let searchTimer = null;
let stockSearchTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadDataSources();
  loadStockData();
  loadKaipanlaFeatures();
  loadNews();
});

function bindEvents() {
  newsRefreshBtn?.addEventListener("click", () => {
    loadDataSources();
    loadStockData();
    loadNews();
  });
  newsExportBtn?.addEventListener("click", () => exportCurrentPage());
  newsResetBtn?.addEventListener("click", () => {
    newsSearchInput.value = "";
    newsPublisherSelect.value = "";
    newsTypeSelect.value = "";
    newsDaysSelect.value = "30";
    newsPageSizeSelect.value = "20";
    state.page = 1;
    loadNews();
  });
  newsPrevBtn?.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadNews();
    }
  });
  newsNextBtn?.addEventListener("click", () => {
    if (state.page < state.pages) {
      state.page += 1;
      loadNews();
    }
  });
  [newsPublisherSelect, newsTypeSelect, newsDaysSelect, newsPageSizeSelect].forEach((control) => {
    control?.addEventListener("change", () => {
      state.page = 1;
      loadNews();
    });
  });
  newsSearchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.page = 1;
      loadNews();
    }, 280);
  });
  stockDataSearchInput?.addEventListener("input", () => {
    window.clearTimeout(stockSearchTimer);
    stockSearchTimer = window.setTimeout(renderStockData, 160);
  });
  stockDataSortSelect?.addEventListener("change", renderStockData);
  kaipanlaFeatureSelect?.addEventListener("change", syncKaipanlaParams);
  kaipanlaValidateBtn?.addEventListener("click", validateKaipanlaIntegration);
  kaipanlaRunBtn?.addEventListener("click", runKaipanlaFeature);
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
    dataSourceState.providers = payload.providers || [];
    dataSourceState.types = payload.types || [];
    dataSourceState.coverage = payload.coverage || {};
    dataSourceState.summary = payload.summary || {};
    renderDataSources();
    dataSourceMeta.textContent = `已注册 ${dataSourceState.summary.provider_count || 0} 个来源，${dataSourceState.summary.standard_type_count || 0} 类标准数据`;
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
    ["本地股票", coverage.local_stock_count ?? 0, "local_data/current"],
    ["开盘啦记录", coverage.kaipanla_record_count ?? 0, `${coverage.kaipanla_recorded_features || 0} 类功能已有记录`],
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
      <td><code>${escapeHtml(primary)}</code></td>
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
  const latest = stockState.items[0]?.updated_at || "-";
  const cards = [
    ["股票资料包", stockState.count, "local_data/current"],
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
  const dateRange = item.date_range || {};
  const rangeText = [dateRange.start_date, dateRange.end_date].filter(Boolean).join(" - ") || "-";
  return `
    <tr>
      <td>
        <strong>${escapeHtml(item.name || "-")}</strong>
        <code>${escapeHtml(item.ts_code || "-")}</code>
      </td>
      <td>${escapeHtml([item.industry, item.market].filter(Boolean).join(" / ") || "-")}</td>
      <td>${escapeHtml(item.updated_at || "-")}</td>
      <td>${escapeHtml(rangeText)}</td>
      <td>${escapeHtml(String(item.dataset_count || 0))}</td>
      <td>${escapeHtml(formatNumber(item.minute_rows || 0))}</td>
      <td>${escapeHtml(String(item.fetch_error_count || 0))}</td>
    </tr>
  `;
}

function compareStockRows(left, right, key) {
  if (key === "ts_code") return String(left.ts_code || "").localeCompare(String(right.ts_code || ""));
  if (key === "dataset_count" || key === "minute_rows") {
    return Number(right[key] || 0) - Number(left[key] || 0);
  }
  return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
}

async function loadKaipanlaFeatures() {
  if (!kaipanlaFeatureSelect) return;
  kaipanlaMeta.textContent = "正在读取功能列表...";
  try {
    const response = await fetch("/api/admin/kaipanla/features");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "读取开盘啦功能失败");
    }
    kaipanlaState.features = payload.items || [];
    kaipanlaFeatureSelect.innerHTML = kaipanlaState.features
      .map((item) => `<option value="${escapeAttr(item.key)}">${escapeHtml(item.category)} · ${escapeHtml(item.label)}</option>`)
      .join("");
    syncKaipanlaParams();
    kaipanlaMeta.textContent = `已集成 ${kaipanlaState.features.length} 个功能`;
  } catch (error) {
    kaipanlaMeta.textContent = `读取失败：${error.message}`;
    kaipanlaOutput.textContent = error.message;
  }
}

function syncKaipanlaParams() {
  const feature = selectedKaipanlaFeature();
  if (!feature || !kaipanlaParamsInput) return;
  kaipanlaParamsInput.value = JSON.stringify(feature.default_params || {}, null, 2);
  kaipanlaOutput.textContent = `${feature.description || ""}${feature.requires ? `\n需要：${feature.requires}` : ""}`;
}

async function validateKaipanlaIntegration() {
  if (!kaipanlaOutput) return;
  kaipanlaValidateBtn.disabled = true;
  kaipanlaOutput.textContent = "正在验证开盘啦功能映射...";
  try {
    const response = await fetch("/api/admin/kaipanla/validate");
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "验证失败");
    }
    kaipanlaOutput.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    kaipanlaOutput.textContent = `验证失败：${error.message}`;
  } finally {
    kaipanlaValidateBtn.disabled = false;
  }
}

async function runKaipanlaFeature() {
  const feature = selectedKaipanlaFeature();
  if (!feature || !kaipanlaOutput) return;
  kaipanlaRunBtn.disabled = true;
  kaipanlaOutput.textContent = `正在运行 ${feature.label}...`;
  try {
    const params = JSON.parse(kaipanlaParamsInput.value || "{}");
    if (!params || Array.isArray(params) || typeof params !== "object") {
      throw new Error("参数必须是 JSON object");
    }
    const response = await fetch("/api/admin/kaipanla/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feature: feature.key, params }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "运行失败");
    }
    kaipanlaOutput.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    kaipanlaOutput.textContent = `运行失败：${error.message}`;
  } finally {
    kaipanlaRunBtn.disabled = false;
  }
}

function selectedKaipanlaFeature() {
  const key = kaipanlaFeatureSelect?.value || "";
  return kaipanlaState.features.find((item) => item.key === key) || null;
}

async function loadNews() {
  newsMeta.textContent = "正在读取 MongoDB 新闻库...";
  newsRefreshBtn.disabled = true;
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
    renderFilters(payload.filters || {});
    renderStats(payload.stats || {}, payload);
    renderDistribution(payload.stats || {});
    renderList(state.items);
    renderPager();
    newsMeta.textContent = `${payload.database}.${payload.collection}，当前筛选 ${state.total} 篇`;
  } catch (error) {
    newsMeta.textContent = `读取失败：${error.message}`;
    state.items = [];
    newsList.innerHTML = `<div class="news-empty is-error">${escapeHtml(error.message)}</div>`;
  } finally {
    newsRefreshBtn.disabled = false;
  }
}

function renderDistribution(stats) {
  const publisherItems = (stats.by_publisher || []).map((item) => ({
    label: item.publisher || "-",
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
  const currentPublisher = newsPublisherSelect.value;
  const currentType = newsTypeSelect.value;
  fillSelect(newsPublisherSelect, "全部来源", filters.publishers || [], currentPublisher);
  fillSelect(newsTypeSelect, "全部分类", filters.types || [], currentType);
}

function fillSelect(select, label, values, currentValue) {
  const options = [`<option value="">${label}</option>`].concat(
    values.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`),
  );
  select.innerHTML = options.join("");
  select.value = values.includes(currentValue) ? currentValue : "";
}

function renderStats(stats, payload) {
  const publisherLines = (stats.by_publisher || [])
    .slice(0, 3)
    .map((item) => `${item.publisher || "-"} ${item.count || 0}`)
    .join(" / ");
  const cards = [
    ["总文章", stats.total ?? "-", "MongoDB 当前文章总数"],
    ["今日新增", stats.today ?? "-", "按 time 字段统计"],
    ["最新时间", stats.latest_time || "-", "新闻库最新发布时间"],
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

function renderList(items) {
  if (!items.length) {
    newsList.innerHTML = `<div class="news-empty">当前条件下没有新闻。</div>`;
    return;
  }
  newsList.innerHTML = items.map(renderItem).join("");
}

function renderItem(item) {
  const url = item.url ? `<a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">原文</a>` : "";
  return `
    <article class="news-item">
      <div class="news-item-meta">
        <span>${escapeHtml(item.publisher || "-")}</span>
        <span>${escapeHtml(item.type || "-")}</span>
        <span>${escapeHtml(item.time || "-")}</span>
        ${url}
      </div>
      <h2>${escapeHtml(item.title || "无标题")}</h2>
      <p>${escapeHtml(item.excerpt || item.summary || "暂无摘要")}</p>
      <details>
        <summary>展开正文</summary>
        <p>${escapeHtml(item.content || "暂无正文")}</p>
      </details>
    </article>
  `;
}

function renderPager() {
  newsPageInfo.textContent = `第 ${state.page} / ${state.pages} 页，共 ${state.total} 篇`;
  newsPrevBtn.disabled = state.page <= 1;
  newsNextBtn.disabled = state.page >= state.pages;
}

function exportCurrentPage() {
  if (!state.items.length) return;
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
