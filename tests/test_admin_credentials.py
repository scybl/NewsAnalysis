from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "stock_pipeline" / "web_static"


def test_credentials_pane_does_not_render_secret_values():
    html = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    redirect = (STATIC / "admin-credentials.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-credentials.js").read_text(encoding="utf-8")
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert "<title>访问与安全 - NewsCrawler</title>" in html
    assert 'data-account-tab="credentials"' in html
    assert 'data-account-pane="credentials"' in html
    assert 'id="credentialsGrid"' in html
    assert "凭据管理" in html
    assert "/admin-accounts.html#credentials" in redirect
    assert "credentialsGrid" not in redirect
    assert "/api/admin/credentials" in script
    assert "明文不会在页面回显" in script
    assert "data-credential-value" in script
    assert "credential-row-head" in script
    assert "credential-env" in script
    assert "credential-meta" not in script
    assert 'value="' not in html
    assert 'value="' not in redirect
    assert "POLITICO_BROWSER_COOKIES_JSON" in web
    assert "BLOOMBERG_PROXY" in web
    assert "BLOOMBERG_COOKIES_JSON" in web
    assert "BLOOMBERG_LATEST_URL" in web
    assert "BLOOMBERG_API_URL" in web
    assert "BLOOMBERG_USE_API" in web
    assert "BLOOMBERG_REQUIRE_LOGIN_COOKIE" in web
    assert "DeepSeek API Key" not in web
    assert "deepseek.api_key" not in web
    assert '"source": "Tushare"' in web
    assert '"source": "Guardian"' in web
    assert '"source": "Baidu Translate"' in web
    assert "BAIDU_TRANSLATE_APP_ID" in web
    assert "BAIDU_TRANSLATE_SECRET_KEY" in web
    assert "baidu_translate_app_id.txt" in web
    assert "baidu_translate_secret_key.txt" in web
    assert '"source": "Baidu Netdisk"' in web
    assert "BAIDU_PAN_APP_KEY" in web
    assert "BAIDU_PAN_SECRET_KEY" in web
    assert "BAIDU_PAN_SIGN_KEY" in web
    assert "BAIDU_PAN_ACCESS_TOKEN" in web
    assert "BAIDU_PAN_REFRESH_TOKEN" in web
    assert "BAIDU_PAN_SECRET_DIR" in web
    assert '"source": "Bloomberg"' in web
    assert '"source": "Politico"' in web
    assert '"status_note": "暂停维护"' in web
    assert "credential-status is-danger" in script
    assert 'credential-status ${item.configured ? "is-success" : "is-muted"}' in script
    assert "item.file_env" not in script
    assert "item.path" not in script
    assert "item.storage" not in script
    assert "groupBySource" in script
    assert "groupByCategory" not in script
    assert "item.reloads_next_run" in script
    assert "restart_required" not in web
    assert "restart_required" not in script
    assert "CREDENTIAL_PUBLIC_FIELDS" in web
    assert '"file_env", "path", "storage"' not in web
    assert '"storage"' not in web.split("CREDENTIAL_PUBLIC_FIELDS", 1)[1].split("ADMIN_CREDENTIALS", 1)[0]
    assert '"path": str(path.relative_to(PROJECT_ROOT))' not in web


def test_admin_nav_collapses_credentials_into_access_security():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        if '<nav class="admin-nav"' not in html:
            continue
        nav = html.split('<nav class="admin-nav"', 1)[1].split("</nav>", 1)[0]
        assert "/admin-accounts.html" in nav, path.name
        assert "访问与安全" in nav, path.name
        assert "/admin-credentials.html" not in nav, path.name
        assert nav.rfind("/admin-accounts.html") < nav.rfind("/admin-ops.html"), path.name
        assert "/admin-archives.html" not in nav, path.name
        assert "/admin-audit.html" not in nav, path.name
        assert "/admin-data-audit.html" not in nav, path.name
        assert nav.rfind("数据分发") > nav.rfind("/admin-crawler.html"), path.name


def test_credentials_script_is_safe_to_embed_in_accounts_page():
    accounts = (STATIC / "admin-accounts.html").read_text(encoding="utf-8")
    credentials_script = (STATIC / "admin-credentials.js").read_text(encoding="utf-8")
    archives_script = (STATIC / "admin-archives.js").read_text(encoding="utf-8")

    assert "/admin-credentials.js?v=access-security-20260708-v1" in accounts
    assert "initializeCredentialsPane()" in credentials_script
    assert "if (!credentialsGrid) return;" in credentials_script
    assert "let credentialsAdminReadonly = false;" in credentials_script
    assert "const themeToggleBtn" not in credentials_script
    assert "const logoutBtn" not in credentials_script
    assert credentials_script.startswith("(() => {")
    assert credentials_script.rstrip().endswith("})();")
    assert archives_script.startswith("(() => {")
    assert archives_script.rstrip().endswith("})();")


def test_compose_uses_page_managed_crawler_secret_files():
    expected = (
        "GUARDIAN_API_KEY_FILE: ${GUARDIAN_API_KEY_FILE:-/app/local_data/secure/news_crawler/guardian_api_key.txt}",
        "BLOOMBERG_COOKIE_FILE: ${BLOOMBERG_COOKIE_FILE:-/app/local_data/secure/news_crawler/bloomberg_cookie.txt}",
        "BLOOMBERG_COOKIES_JSON_FILE: ${BLOOMBERG_COOKIES_JSON_FILE:-/app/local_data/secure/news_crawler/bloomberg_cookies_json.txt}",
        "BLOOMBERG_PROXY_FILE: ${BLOOMBERG_PROXY_FILE:-/app/local_data/secure/news_crawler/bloomberg_proxy.txt}",
        "BLOOMBERG_LATEST_URL_FILE: ${BLOOMBERG_LATEST_URL_FILE:-/app/local_data/secure/news_crawler/bloomberg_latest_url.txt}",
        "BLOOMBERG_API_URL_FILE: ${BLOOMBERG_API_URL_FILE:-/app/local_data/secure/news_crawler/bloomberg_api_url.txt}",
        "BLOOMBERG_USE_API_FILE: ${BLOOMBERG_USE_API_FILE:-/app/local_data/secure/news_crawler/bloomberg_use_api.txt}",
        "BLOOMBERG_REQUIRE_LOGIN_COOKIE_FILE: ${BLOOMBERG_REQUIRE_LOGIN_COOKIE_FILE:-/app/local_data/secure/news_crawler/bloomberg_require_login_cookie.txt}",
        "POLITICO_BROWSER_PROXY_FILE: ${POLITICO_BROWSER_PROXY_FILE:-/app/local_data/secure/news_crawler/politico_browser_proxy.txt}",
        "POLITICO_BROWSER_COOKIES_JSON_FILE: ${POLITICO_BROWSER_COOKIES_JSON_FILE:-/app/local_data/secure/news_crawler/politico_browser_cookies_json.txt}",
    )
    for compose_path in (ROOT / "docker-compose.yml", ROOT / "docker-compose.prod.yml", ROOT / "NewsCrawler" / "docker-compose.yml"):
        text = compose_path.read_text(encoding="utf-8")
        for line in expected:
            assert line in text, compose_path.name
