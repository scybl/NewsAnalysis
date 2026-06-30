from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "stock_pipeline" / "web_static"


def test_credentials_page_does_not_render_secret_values():
    html = (STATIC / "admin-credentials.html").read_text(encoding="utf-8")
    script = (STATIC / "admin-credentials.js").read_text(encoding="utf-8")
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert "凭据管理" in html
    assert "/api/admin/credentials" in script
    assert "明文不会在页面回显" in script
    assert "data-credential-value" in script
    assert 'value="' not in html
    assert "POLITICO_BROWSER_COOKIES_JSON" in web
    assert "BLOOMBERG_PROXY" in web
    assert "DeepSeek API Key" not in web
    assert "deepseek.api_key" not in web
    assert '"source": "Tushare"' in web
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


def test_credentials_console_is_last_available_admin_nav_item():
    for path in STATIC.glob("admin-*.html"):
        html = path.read_text(encoding="utf-8")
        nav = html.split('<nav class="admin-nav"', 1)[1].split("</nav>", 1)[0]
        assert "/admin-credentials.html" in nav, path.name
        assert nav.rfind("/admin-credentials.html") > nav.rfind("/admin-crawler.html"), path.name
        assert nav.rfind("数据分发") > nav.rfind("/admin-credentials.html"), path.name


def test_compose_uses_page_managed_crawler_secret_files():
    expected = (
        "GUARDIAN_API_KEY_FILE: ${GUARDIAN_API_KEY_FILE:-/app/local_data/secure/news_crawler/guardian_api_key.txt}",
        "BLOOMBERG_COOKIE_FILE: ${BLOOMBERG_COOKIE_FILE:-/app/local_data/secure/news_crawler/bloomberg_cookie.txt}",
        "BLOOMBERG_PROXY_FILE: ${BLOOMBERG_PROXY_FILE:-/app/local_data/secure/news_crawler/bloomberg_proxy.txt}",
        "POLITICO_BROWSER_PROXY_FILE: ${POLITICO_BROWSER_PROXY_FILE:-/app/local_data/secure/news_crawler/politico_browser_proxy.txt}",
        "POLITICO_BROWSER_COOKIES_JSON_FILE: ${POLITICO_BROWSER_COOKIES_JSON_FILE:-/app/local_data/secure/news_crawler/politico_browser_cookies_json.txt}",
    )
    for compose_path in (ROOT / "docker-compose.yml", ROOT / "docker-compose.prod.yml", ROOT / "NewsCrawler" / "docker-compose.yml"):
        text = compose_path.read_text(encoding="utf-8")
        for line in expected:
            assert line in text, compose_path.name
