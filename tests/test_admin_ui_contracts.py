import json
from pathlib import Path

from stock_pipeline.web import ApiKeyCipher, UserStore


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "stock_pipeline" / "web_static"


def _store(tmp_path, payload):
    path = tmp_path / "web_users.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return UserStore(path, ApiKeyCipher("test-secret"))


def _archive_payload():
    return {
        "users": {},
        "demo_accounts": {},
        "usage": {},
        "archived_users": {
            "alice": {
                "archived_at": "20260708_103700",
                "archived_by": "admin",
                "reason": "manual cleanup",
                "account": {
                    "created_at": "20260701_090000",
                    "role": "user",
                    "invite_code": "INV-1",
                    "api_keys": {
                        "deepseek": {"ciphertext": "secret-ciphertext", "updated_at": "20260708_090000"},
                        "tushare": {"ciphertext": "", "updated_at": ""},
                    },
                },
                "usage": {
                    "by_path": {
                        "/api/analyze": 12,
                        "/api/health": 999,
                    },
                    "last_request_at": "20260708_101100",
                },
            }
        },
        "archived_demo_accounts": {
            "demo001": {
                "archived_at": "20260707_213000",
                "archived_by": "operator",
                "reason": "old demo account",
                "account": {"created_at": "20260701_080000", "tier": "demo"},
                "usage": {"by_path": {"/api/sync-stock-data": 3}, "last_request_at": "20260707_210000"},
            }
        },
    }


def test_archive_backend_returns_unified_items_sorted_across_account_types(tmp_path):
    result = _store(tmp_path, _archive_payload()).admin_archives()

    assert result["counts"] == {"users": 1, "demo_accounts": 1, "total": 2}
    assert [item["username"] for item in result["items"]] == ["alice", "demo001"]
    assert result["users"][0]["username"] == "alice"
    assert result["demo_accounts"][0]["username"] == "demo001"


def test_archive_backend_query_matches_registered_and_demo_archive_fields(tmp_path):
    store = _store(tmp_path, _archive_payload())

    assert [item["username"] for item in store.admin_archives("manual")["items"]] == ["alice"]
    assert [item["username"] for item in store.admin_archives("operator")["items"]] == ["demo001"]
    assert [item["username"] for item in store.admin_archives("demo")["items"]] == ["demo001"]
    assert [item["username"] for item in store.admin_archives("INV-1")["items"]] == ["alice"]


def test_archive_backend_redacts_api_key_ciphertext_and_keeps_configured_summary(tmp_path):
    result = _store(tmp_path, _archive_payload()).admin_archives()
    user = result["items"][0]

    assert user["api_keys"]["deepseek"] == {"configured": True, "updated_at": "20260708_090000"}
    assert user["api_keys"]["tushare"] == {"configured": False, "updated_at": ""}
    assert "secret-ciphertext" not in json.dumps(user, ensure_ascii=False)


def test_archive_backend_counts_only_billable_usage_paths(tmp_path):
    result = _store(tmp_path, _archive_payload()).admin_archives()
    user = result["items"][0]

    assert user["usage_total"] == 12
    assert user["by_path"] == {"/api/analyze": 12}
    assert user["last_request_at"] == "20260708_101100"


def test_archive_frontend_prefers_unified_items_and_keeps_legacy_fallbacks():
    script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")

    assert "archiveItems(payload)" in script
    assert "Array.isArray(payload.items)" in script
    assert "...(payload.users || [])" in script
    assert "...(payload.demo_accounts || [])" in script
    assert "localeCompare" in script


def test_archive_frontend_renders_registered_and_demo_labels_without_secret_columns():
    html = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")

    assert "archiveDemoCount" in html
    assert "<h4>归档账号</h4>" in html
    assert "临时账号" in script
    assert "注册账号" in script
    assert "密码哈希" in html
    assert "ciphertext" not in html


def test_archive_route_keeps_backward_fields_and_adds_items_contract():
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert 'parsed.path == "/api/admin/archives"' in web
    assert '"items": items' in web
    assert '"users": users' in web
    assert '"demo_accounts": demo_accounts' in web
    assert '"total": len(users) + len(demo_accounts)' in web


def test_changed_admin_pages_bust_static_cache_versions():
    expected = {
        "admin-accounts.html": "time-archive-20260708-v1",
        "admin-market.html": "time-archive-20260708-v1",
        "admin-ops.html": "time-ops-layout-20260709-v1",
        "admin-crawler.html": "time-crawler-20260708-v1",
        "admin-news.html": "time-news-20260708-v1",
        "index.html": "time-maintenance-20260708-v1",
    }

    for filename, marker in expected.items():
        assert marker in (STATIC / filename).read_text(encoding="utf-8"), filename


def test_frontend_copy_does_not_present_tushare_as_default_update_source():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "更新资料包" in html
    assert "Tushare API（封存兼容）" in html
    for stale_copy in (
        "更新 Tushare",
        "数据源：Tushare",
        "Tushare 资料包",
        "请先点击“更新 Tushare”",
    ):
        assert stale_copy not in html
        assert stale_copy not in app


def test_admin_time_formatters_hide_year_and_seconds_in_changed_scripts():
    for path in (
        "admin.js",
        "admin-archives.js",
        "admin-ops.js",
        "admin-data-audit.js",
        "admin-crawler.js",
        "admin-news.js",
        "app.js",
    ):
        script = (STATIC / path).read_text(encoding="utf-8")
        assert 'toLocaleString("zh-CN", { hour12: false })' not in script, path
        assert 'Intl.DateTimeFormat("zh-CN"' not in script, path
        assert "second:" not in script, path


def test_admin_time_formatters_support_compact_plain_and_iso_like_inputs():
    scripts = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("admin.js", "admin-archives.js", "admin-ops.js"))

    assert r"^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})" in scripts
    assert r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})" in scripts
    assert "`${Number(compact[2])}月${Number(compact[3])}日${compact[4]}:${compact[5]}`" in scripts
    assert "`${month}月${day}日${hour}:${minute}`" in scripts


def test_stock_and_market_date_labels_use_month_day_without_year():
    admin = (STATIC / "admin.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    news = (STATIC / "admin-news.js").read_text(encoding="utf-8")

    assert "function formatCompactDate(value)" in admin
    assert "dailyMarketLastDate.textContent = formatCompactDate" in admin
    assert "kaipanlaLastDate.textContent = formatCompactDate" in admin
    assert "return `${Number(text.slice(4, 6))}月${Number(text.slice(6, 8))}日`" in app
    assert "return `${Number(match[2])}月${Number(match[3])}日`" in news


def test_kaipanla_overview_formats_saved_time_and_fallback_date():
    admin = (STATIC / "admin.js").read_text(encoding="utf-8")

    assert "最近保存 ${formatCompactTimestamp(overview.latest_saved_at)}" in admin
    assert "${formatCompactDate(overview.requested_display_date)} 未更新" in admin
    assert "formatOverviewCell(row[key])" in admin
    assert "return formatCompactDate(text)" in admin


def test_ops_status_hints_cover_user_visible_status_values():
    script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")

    for status in ("succeeded", "failed", "running", "idle", "unknown", "paused", "failed_or_stopped"):
        assert f"{status}:" in script
    assert "OPS_STATUS_HINTS" in script
    assert "title=\"${escapeAttr(statusHint(safeStatus))}\"" in script
    assert "任务最近一次完整执行成功" in script
    assert "缺少配置、日志或状态文件" in script


def test_ops_event_labels_cover_cold_upload_lifecycle_and_crawler_snapshot():
    script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")

    for event in ("upload_start", "upload_done", "write_start", "write_done", "local_removed", "index_done", "crawler_status_snapshot"):
        assert event in script
    assert "eventLabel(task.last_event)" in script


def test_ops_task_table_uses_colgroup_for_alignment():
    script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")

    for column in ("ops-task-col", "ops-status-col", "ops-running-col", "ops-resource-col", "ops-progress-col", "ops-event-col", "ops-log-col"):
        assert column in script
    for cell in ("ops-task-cell", "ops-status-cell", "ops-running-cell", "ops-resource-cell", "ops-progress-cell", "ops-detail-cell", "ops-log-cell"):
        assert cell in script
    assert "<colgroup>" in script


def test_ops_log_column_preserves_table_cell_layout():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    script = (STATIC / "admin-ops.js").read_text(encoding="utf-8")

    assert 'td class="ops-log-cell"' in script
    assert '<div class="ops-log-command">' in script
    assert ".ops-log-command {" in styles
    assert ".ops-log-cell {\n  display: grid" not in styles


def test_ops_column_widths_keep_last_event_and_log_separate():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "min-width: 1240px" in styles
    assert ".ops-event-col" in styles
    assert "width: 21%" in styles
    assert ".ops-log-col" in styles
    assert "width: 14%" in styles
    assert ".ops-table-wrap td {\n  max-width: none" in styles
    assert "text-overflow: clip" in styles
    assert "white-space: normal" in styles
    assert "table-layout: fixed" in styles


def test_account_page_archive_script_initialization_is_safe_on_redirect_page():
    redirect = (STATIC / "admin-archives.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")

    assert "/admin-accounts.html#archives" in redirect
    assert "if (!archiveUsersTable) return;" in script


def test_frontend_tests_cover_backend_route_page_and_script_for_archive_flow():
    html = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert "archiveUsersTable" in html
    assert "fetch(`/api/admin/archives?${params.toString()}`)" in script
    assert "self._json({\"ok\": True, **app.user_store.admin_archives" in web
