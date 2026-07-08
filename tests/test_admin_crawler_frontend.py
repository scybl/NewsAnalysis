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
    assert 'const CRAWLER_EXPECTED_SOURCES = ["tonghuashun", "guardian", "bloomberg", "politico_browser", "politico_rss", "gdelt", "alpha_vantage_news"]' in script
    assert 'const CRAWLER_IGNORED_SOURCES = new Set(["politico"])' in script
    assert "filter(isVisibleCrawlerSource)" in script
    assert "maintenance: true" in script
    assert "暂停维护" in script
    assert "sourceName" in script
    assert 'guardian: { label: "Guardian", initial: "G" }' in script
    assert 'bloomberg: { label: "Bloomberg", initial: "B", maintenance: true }' in script
    assert "Politico Legacy" not in script
    assert 'politico_browser: { label: "Politico Web", initial: "P", maintenance: true }' in script
    assert 'politico_rss: { label: "Politico RSS", initial: "R", maintenance: true }' in script
    assert 'gdelt: { label: "GDELT", initial: "G", maintenance: true }' in script
    assert 'alpha_vantage_news: { label: "Alpha Vantage News", initial: "A", maintenance: true }' in script
    assert "等待首次采集运行记录。" in script
    assert 'code !== "empty_response"' in script
    assert "connection_closed: \"主动断连\"" in script
    assert "item.article_url" in script
    assert "adminRuntimeAlerts" in (STATIC / "login.html").read_text(encoding="utf-8")
    assert "crawler-runtime-alerts" in script
    assert "自动暂停" in script
    assert "凭据过期" in script
    assert "crawlerRunDetail" not in html
    assert "crawlerRunDetail" not in script
    assert "showRunDetail" not in script


def test_guardian_news_cards_can_request_machine_translation():
    script = (STATIC / "admin-news.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    news_library = (STATIC.parents[1] / "stock_pipeline" / "news_library.py").read_text(encoding="utf-8")
    raw_news = (STATIC.parents[1] / "stock_pipeline" / "raw_news.py").read_text(encoding="utf-8")

    assert "/api/admin/news-library/translate" in script
    assert "data-news-translation-toggle" in script
    assert "调用百度翻译生成 Guardian 中文译文" in script
    assert "state.translations" in script
    assert "preloadCachedTranslations" in script
    assert "hasCachedTranslation ? \"已翻译\"" in script
    assert "renderParagraphComparison" in script
    assert "formatNewsDateTime(stats.latest_time)" in script
    assert "splitArticleParagraphs" in script
    assert "news-compare-row" in script
    assert "段落对照" in script
    assert ".news-translation-toggle" in styles
    assert ".news-compare-row" in styles
    assert "overflow-wrap: anywhere" in styles
    assert '"translations.zh": 1' in raw_news
    assert '"translation": _public_translation(translation) if translation else None' in news_library


def test_politico_browser_is_paused_while_guardian_worker_stays_focused():
    compose = (STATIC.parents[1] / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "NEWS_CRAWLER_DISABLED_SOURCES: ${NEWS_CRAWLER_DISABLED_SOURCES:-bloomberg,politico_browser,politico_rss,politico_chrome,guardian}" in compose
    assert "NEWS_CRAWLER_DISABLED_SOURCES: ${NEWS_CRAWLER_GUARDIAN_DISABLED_SOURCES:-bloomberg,politico_rss,politico_browser,politico_chrome,tonghuashun}" in compose
    assert 'command: ["schedule", "--source", "guardian", "--interval", "${GUARDIAN_CRAWLER_INTERVAL_SECONDS:-3600}"' in compose


def test_all_admin_pages_link_to_crawler_console():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        if '<nav class="admin-nav"' not in html:
            continue
        assert "/admin-crawler.html" in html, path.name
        assert "/admin-ops.html" in html, path.name


def test_admin_navigation_keeps_closed_entries_after_crawler_and_kaipanla_inside_data_sources():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        if '<nav class="admin-nav"' not in html:
            continue
        nav = html.split('<nav class="admin-nav"', 1)[1].split("</nav>", 1)[0]
        assert nav.rfind("数据分发") > nav.rfind("/admin-crawler.html"), path.name
        assert nav.rfind("Agent Gateway") > nav.rfind("数据分发"), path.name
        assert "/admin-distribution.html" not in nav, path.name
        assert "/admin-kaipanla.html" not in nav, path.name
    stock_data = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    assert "NEWS LIBRARY" not in stock_data
    assert "新闻资料库" not in stock_data


def test_admin_audit_log_is_inside_system_governance_page_not_account_card():
    accounts = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    ops = (STATIC / "admin-ops.html").read_text(encoding="utf-8")
    audit_redirect = (STATIC / "admin-audit.html").read_text(encoding="utf-8")
    script = (STATIC / "admin.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "id=\"adminAuditTable\"" not in accounts
    assert "<h4>审计日志</h4>" not in accounts
    assert "<title>系统治理 - NewsCrawler</title>" in ops
    assert "data-governance-tab=\"audit-log\"" in ops
    assert "id=\"adminAuditTable\"" in ops
    assert "后台操作记录" in ops
    assert "/admin-ops.html#audit-log" in audit_redirect
    assert "adminAuditPage" in script
    assert "id=\"adminSummary\"" not in ops
    assert "最近 80 条后台权限操作" not in script
    assert ".audit-log-card .audit-table-wrap" in styles


def test_data_console_accounts_excludes_analysis_only_vip_and_demo_tools():
    accounts = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    archives = (STATIC / "admin-archives.html").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app_script = (STATIC / "app.js").read_text(encoding="utf-8")
    admin_script = (STATIC / "admin.js").read_text(encoding="utf-8")

    assert "生成测试账号" not in accounts
    assert "测试账号" not in accounts
    assert "VIP 兑换码" not in accounts
    assert "生成 VIP 码" not in accounts
    assert 'data-account-tab="accounts"' in accounts
    assert 'data-account-tab="archives"' in accounts
    assert "archiveUsersTable" in accounts
    assert "/admin-accounts.html#archives" in archives
    assert "archiveUsersTable" not in archives
    assert "VIP 到期" not in admin_script
    assert "发 VIP" not in admin_script
    assert "撤 VIP" not in admin_script
    assert "归档测试账号" not in archives
    assert "archiveDemoAccountsTable" not in (STATIC / "admin-archives.js").read_text(encoding="utf-8")
    assert "VIP 兑换码" not in index
    assert "兑换 VIP" not in index
    assert "redeemVipCode" not in app_script
    assert "VIP 使用系统 API" not in app_script


def test_archived_accounts_page_keeps_registered_and_demo_archive_path_wired():
    root = STATIC.parents[1]
    accounts = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    archive_script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")
    web = (root / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert "archiveDemoCount" in accounts
    assert "<h4>归档账号</h4>" in accounts
    assert "/api/admin/archives" in archive_script
    assert "archiveItems(payload)" in archive_script
    assert "...(payload.demo_accounts || [])" in archive_script
    assert "临时账号" in archive_script
    assert '"items": items' in web
    assert 'parsed.path == "/api/admin/archives"' in web


def test_admin_time_labels_hide_year_and_seconds_in_frontend_formatters():
    scripts = {
        "admin.js": (STATIC / "admin.js").read_text(encoding="utf-8"),
        "admin-archives.js": (STATIC / "admin-archives.js").read_text(encoding="utf-8"),
        "admin-ops.js": (STATIC / "admin-ops.js").read_text(encoding="utf-8"),
        "admin-data-audit.js": (STATIC / "admin-data-audit.js").read_text(encoding="utf-8"),
        "admin-crawler.js": (STATIC / "admin-crawler.js").read_text(encoding="utf-8"),
        "admin-news.js": (STATIC / "admin-news.js").read_text(encoding="utf-8"),
        "app.js": (STATIC / "app.js").read_text(encoding="utf-8"),
    }

    for name, script in scripts.items():
        assert 'toLocaleString("zh-CN", { hour12: false })' not in script, name
        assert 'Intl.DateTimeFormat("zh-CN"' not in script, name
    assert "`${Number(month)}月${Number(day)}日${hour}:${minute}`" in scripts["admin.js"]
    assert "`${Number(compact[2])}月${Number(compact[3])}日${compact[4]}:${compact[5]}`" in scripts["admin-ops.js"]
    assert "`${Number(text.slice(4, 6))}月${Number(text.slice(6, 8))}日`" in scripts["app.js"]


def test_regular_user_data_console_is_limited_and_read_only():
    web = (STATIC.parents[1] / "stock_pipeline" / "web.py").read_text(encoding="utf-8")
    admin_script = (STATIC / "admin.js").read_text(encoding="utf-8")
    news_script = (STATIC / "admin-news.js").read_text(encoding="utf-8")
    crawler_script = (STATIC / "admin-crawler.js").read_text(encoding="utf-8")

    for page in ("admin-market.html", "admin-news.html", "admin-crawler.html"):
        assert 'data-data-console-page="true"' in (STATIC / page).read_text(encoding="utf-8")

    market_html = (STATIC / "admin-market.html").read_text(encoding="utf-8")
    stock_html = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    assert 'DATA_CONSOLE_PAGES = {"/admin-market.html", "/admin-news.html", "/admin-crawler.html"}' in web
    assert 'DATA_CONSOLE_ROLES = {*ADMIN_ROLES, "user"}' in web
    assert '"/admin-accounts.html"' in web
    assert '"/admin-audit.html"' in web
    assert "parsed.path in ADMIN_ONLY_PAGES" in web
    assert "def _require_data_console" in web
    assert 'parsed.path == "/metrics/news-crawler"' in web
    assert 'parsed.path == "/api/admin/news-crawler/metrics"' in web
    assert "news_crawler_prometheus_metrics" in web
    assert 'dataConsoleHrefs = new Set(["/admin-market.html", "/admin-news.html", "/admin-crawler.html"])' in admin_script
    assert 'role === "user"' in admin_script
    assert "link.remove()" in admin_script
    assert "if (!dataConsoleHrefs.has(href)) link.remove();" in admin_script
    assert "if (!crawlerDataConsoleHrefs.has(href)) link.remove();" in crawler_script
    assert "为保证抓取稳定，暂时冻结手动抓取功能。" in admin_script
    assert "普通账号数据查看模式：只开放行情数据、股票数据和新闻数据" not in admin_script
    assert "data-admin-operation-section" in market_html
    assert stock_html.count("data-admin-operation-section") == 3
    assert 'document.querySelectorAll("[data-admin-operation-section]")' in admin_script
    for control in (
        "startSpiderBtn",
        "runDailyMarketNowBtn",
        "runIdlePrefetchNowBtn",
        "kaipanlaRunBtn",
    ):
        assert control in admin_script
    assert "newsPageAdminReadonly = role !== \"admin\"" in news_script
    assert "补抓、翻译和刷新入库操作已禁用" in news_script
    assert "crawlerReadOnly = role !== \"admin\"" in crawler_script
    assert "link.remove()" in crawler_script
    assert "失败 item 重抓等手动操作已关闭" in crawler_script
    assert "if (crawlerReadOnly) return;" in crawler_script


def test_monitoring_compose_profile_and_grafana_dashboard_are_wired():
    root = STATIC.parents[1]
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    prometheus = (root / "monitoring" / "prometheus.yml").read_text(encoding="utf-8")
    datasource = (root / "monitoring" / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
    dashboard_provider = (root / "monitoring" / "grafana" / "provisioning" / "dashboards" / "news-crawler.yml").read_text(encoding="utf-8")
    dashboard = (root / "monitoring" / "grafana" / "dashboards" / "news-crawler.json").read_text(encoding="utf-8")

    assert "prometheus:" in compose
    assert "grafana:" in compose
    assert 'profiles: ["monitoring"]' in compose
    assert "prometheus_data:/prometheus" in compose
    assert "grafana_data:/var/lib/grafana" in compose
    assert "./local_data/prometheus:/prometheus" not in compose
    assert "./local_data/grafana:/var/lib/grafana" not in compose
    assert "web:8765" in prometheus
    assert "metrics_path: /metrics/news-crawler" in prometheus
    assert "uid: Prometheus" in datasource
    assert "http://prometheus:9090" in datasource
    assert "/var/lib/grafana/dashboards" in dashboard_provider
    assert "NewsCrawler Monitor" in dashboard
    assert "news_crawler_source_recent_success_rate" in dashboard


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


def test_stock_task_history_drives_task_detail_panel():
    html = (STATIC / "admin-ops.html").read_text(encoding="utf-8")
    accounts = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    script = (STATIC / "admin.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "id=\"adminTasksTable\"" not in accounts
    assert "<h4>后台任务</h4>" not in accounts
    assert "后台任务历史" in html
    assert "<h4>任务详情</h4>" in html
    assert "选择右侧任务查看执行事件。" in html
    assert "id=\"adminTasksTable\"" in html
    assert "adminTaskItems" in script
    assert "selectedAdminTaskId" in script
    assert "data-admin-task-id" in script
    assert "renderSelectedAdminTaskDetail" in script
    assert "formatTaskDetail" in script
    assert 'idle_stock_prefetch: "空闲预抓"' in script
    assert 'data_random_audit: "数据抽检"' in script
    assert "taskEventStageLabel" in script
    assert ".spider-task-history-card tbody tr.selected td" in styles


def test_governance_data_audit_has_idle_scheduler_controls():
    html = (STATIC / "admin-ops.html").read_text(encoding="utf-8")
    ops_script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")
    audit_script = (STATIC / "admin-data-audit.js").read_text(encoding="utf-8")

    assert "空闲自动抽检" in html
    assert "dataAuditSchedulerEnabled" in html
    assert "dataAuditSchedulerIdleSeconds" in html
    assert "dataAuditSchedulerIntervalSeconds" in html
    assert "/api/admin/data-random-audit/scheduler" in audit_script
    assert "refreshDataAuditScheduler" in audit_script
    assert "runDataAuditSchedulerNow" in audit_script
    assert 'data_random_audit: "数据抽检"' in ops_script


def test_governance_ops_layout_keeps_tables_aligned():
    script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "align-items: stretch" in styles
    assert ".ops-grid > .admin-card" in styles
    assert "table-layout: fixed" in styles
    assert "align-content: start" in styles
    assert "<colgroup>" in script
    assert "OPS_STATUS_HINTS" in script
    assert "OPS_EVENT_LABELS" in script
    assert "title=\"${escapeAttr(statusHint(safeStatus))}\"" in script
    assert "ops-log-command" in script
    assert ".ops-log-command" in styles
    assert ".ops-log-cell {\n  display: grid" not in styles


def test_market_and_data_source_pages_have_explicit_layout_sections():
    market = (STATIC / "admin-market.html").read_text(encoding="utf-8")
    stock_sources = (STATIC / "admin-news.html").read_text(encoding="utf-8")
    news_sources = (STATIC / "admin-crawler.html").read_text(encoding="utf-8")
    admin_script = (STATIC / "admin.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "market-schedule-grid" in market
    assert ".market-schedule-grid" in styles
    assert "每日市场纵览" in market
    assert "kaipanlaOverviewKpis" in market
    assert "/api/admin/kaipanla/daily-overview" in admin_script
    assert "renderKaipanlaDailyOverview" in admin_script
    assert "个数据集" in admin_script
    assert "预览 ${previewRows.length} / 共 ${total} 条" in admin_script
    assert ".kaipanla-overview-kpis" in styles
    assert ".kaipanla-overview-table small" in styles
    for class_name in ("market-primary-grid", "market-observability-grid"):
        assert class_name in stock_sources
        assert f".{class_name}" in styles
    for heading in ("行情定时采集", "全市场股票列表", "开盘啦行情数据"):
        assert heading in market
    assert "开盘啦功能配置与历史结果" not in market
    assert "kaipanla-config-section" not in market
    assert "参数 JSON" not in market
    assert "kaipanla-detail-panel" not in market
    assert "手动行情补采" not in market
    assert "每日自动刷新全市场股票列表" in market
    assert "每日自动刷新股票列表" not in stock_sources
    for heading in ("股票来源与标准", "手动行情补采", "分钟行情", "空闲预抓", "本地股票资料库"):
        assert heading in stock_sources
    assert "新闻资料库" in news_sources
    assert "NEWS LIBRARY" in news_sources
    assert "data-source-overview-grid" in stock_sources
    assert ".data-source-overview-grid" in styles
    assert 'data-stock-tab="storage"' in stock_sources
    assert "stockStorageTable" in stock_sources
    assert "stockStorageFilterSelect" in stock_sources
    for option in ("daily_missing", "minute_missing", "cold_pending", "health_attention"):
        assert f'value="{option}"' in stock_sources
    assert "idlePrefetchRefreshDays" in stock_sources
    stock_script = (STATIC / "admin-news.js").read_text(encoding="utf-8")
    assert "/api/admin/stock-storage-status" in stock_script
    assert "stockStorageMatchesFilter" in stock_script
    assert "stockStorageFilterSelect?.addEventListener" in stock_script
    assert "stock_storage_status_snapshot" in (STATIC.parents[1] / "stock_pipeline" / "web.py").read_text(encoding="utf-8")
    assert ".stock-health-pill" in styles


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
        "inserted",
        "updated",
        "failed",
        "run_id",
    ):
        assert f"item.{field}" in script
    for heading in ("<th>发现</th>", "<th>新的</th>", "<th>入库</th>", "<th>失败</th>"):
        assert heading in script
    assert "storedCount(item)" in script


def test_stock_data_table_uses_daily_range_and_formats_time():
    script = (STATIC / "admin-news.js").read_text(encoding="utf-8")

    assert "item.daily_date_range || item.date_range" in script
    assert "formatStockTimestamp(item.updated_at)" in script
    assert "formatStockDateRange(dateRange)" in script


def test_crawler_failure_diagnostics_support_retry_and_grouping():
    html = (STATIC / "admin-crawler.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-crawler.js").read_text(encoding="utf-8")

    assert "crawlerRetryFailuresBtn" in html
    assert "/api/admin/news-crawler/failure-action" in script
    assert "重抓一次" in script
    assert "item.count" in script
    assert "sample_urls" in script
