from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "stock_pipeline" / "web_static"


def test_crawler_console_is_dedicated_and_read_only():
    html = (STATIC / "admin-crawler.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-crawler.js").read_text(encoding="utf-8")

    assert "NewsCrawler" in html
    assert "Admin Console" not in html
    assert "返回分析" not in html
    assert "采集控制台" not in html
    assert "NEWS DATA · READ ONLY".lower() in html.lower()
    assert "news.raw_articles" in html
    assert "采集与分析已经分离" not in html
    assert "数据所有权" not in html
    assert "运维事实" not in html
    assert "唯一写入方" not in html
    assert "crawlerRawCollection" not in html
    assert "/api/admin/news-crawler/status" in script
    assert "crawlerRawCollection" not in script
    assert "/api/admin/market-fetch/start" not in script
    assert "/api/admin/market-fetch/stop" not in script
    assert "/api/admin/spider/" not in script
    assert "function escapeAttr(value)" in script
    assert "失败 item 诊断" in html
    assert "crawlerFailureStats" in script
    assert "crawler-ops-grid" in html
    assert "crawler-ops-grid-detailed" in html
    assert ".crawler-ops-grid" in (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".crawler-console .crawler-ops-grid-detailed" in (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "empty_response: \"返回空\"" in script
    assert "issueLabel(item.code))} ·" not in script
    assert "normalizeIssueCodeCounts" in script
    assert 'source_name: "politico"' in script
    assert 'politico: "Politico"' in script
    assert 'code !== "empty_response"' in script
    assert "connection_closed: \"主动断连\"" in script
    assert "item.article_url" in script


def test_all_admin_pages_link_to_crawler_console():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        assert "/admin-crawler.html" in html, path.name


def test_admin_navigation_keeps_closed_entries_after_crawler_and_kaipanla_inside_data_sources():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        nav = html.split('<nav class="admin-nav"', 1)[1].split("</nav>", 1)[0]
        assert nav.rfind("数据分发") > nav.rfind("/admin-crawler.html"), path.name
        assert nav.rfind("Agent Gateway") > nav.rfind("数据分发"), path.name
        assert "/admin-distribution.html" not in nav, path.name
        assert "/admin-kaipanla.html" not in nav, path.name
    stock_data = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    assert "NEWS LIBRARY" not in stock_data
    assert "新闻资料库" not in stock_data


def test_stock_home_no_longer_exposes_admin_console_entry():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Admin Console" not in html
    assert "adminPanelLink" not in html


def test_data_distribution_page_is_retained_but_disabled():
    html = (STATIC / "admin-distribution.html").read_text(encoding="utf-8")
    assert 'data-distribution-disabled="true"' in html
    assert "数据分发 · 维护中" in html
    assert "SMTP 邮件分发能力已经在后端保留" in html
    assert 'type="button" disabled>保存配置' in html


def test_market_fetch_uses_shared_stock_search():
    html = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    script = (STATIC / "admin.js").read_text(encoding="utf-8")
    assert "代码、名称、拼音或缩写" in html
    assert "/api/search?q=" in script
    assert "selectedMarketStockCode()" in script
    assert "请先从检索结果中选择一只股票" in script


def test_market_and_data_source_pages_have_explicit_layout_sections():
    market = (STATIC / "admin-market.html").read_text(encoding="utf-8")
    stock_sources = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    news_sources = (STATIC / "admin-crawler.html").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "market-schedule-grid" in market
    assert ".market-schedule-grid" in styles
    for class_name in ("market-primary-grid", "market-observability-grid"):
        assert class_name in stock_sources
        assert f".{class_name}" in styles
    for heading in ("行情定时采集", "全市场股票列表", "开盘啦行情数据"):
        assert heading in market
    assert "开盘啦功能配置与历史结果" in market
    assert "手动行情补采" not in market
    assert "每日自动刷新全市场股票列表" in market
    assert "每日自动刷新股票列表" not in stock_sources
    for heading in ("股票来源与标准", "手动行情补采", "分钟行情", "空闲预抓", "本地股票资料库"):
        assert heading in stock_sources
    assert "新闻资料库" in news_sources
    assert "NEWS LIBRARY" in news_sources
    assert "data-source-overview-grid" in stock_sources
    assert ".data-source-overview-grid" in styles


def test_news_source_distribution_uses_chinese_publisher_label():
    script = (STATIC / "admin-news.js").read_text(encoding="utf-8")
    assert 'tonghuashun: "同花顺新闻"' in script
    assert "newsPublisherLabel(item.publisher)" in script


def test_crawler_run_table_matches_crawl_result_metrics():
    script = (STATIC / "admin-crawler.js").read_text(encoding="utf-8")
    for field in (
        "started_at",
        "finished_at",
        "discovered",
        "fetched",
        "inserted",
        "updated",
        "skipped",
        "failed",
        "metrics",
        "errors",
        "run_id",
    ):
        assert f"item.{field}" in script
