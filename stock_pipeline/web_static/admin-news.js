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

const state = {
  page: 1,
  pages: 1,
  total: 0,
  loadedFilters: false,
  items: [],
};

let searchTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadNews();
});

function bindEvents() {
  newsRefreshBtn?.addEventListener("click", () => loadNews());
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
