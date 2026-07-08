import hmac
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer as RealThreadingHTTPServer

import pytest

from stock_pipeline.config import Settings


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib callback
        return None


class _FakeTushareClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeStockSearchIndex:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query):
        return [{"ts_code": "000001.SZ", "name": "平安银行"}] if query else []


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"local socket binding is disabled in this environment: {exc}")
        return int(sock.getsockname()[1])


def _signed_cookie(app, token: str) -> str:
    signature = hmac.new(app.auth_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"stock_session={token}.{signature}"


def _request_json(url: str, *, cookie: str = "", follow_redirects: bool = True) -> tuple[int, dict, dict]:
    request = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body), dict(response.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body.strip().startswith("{") else {"raw": body}
        return exc.code, payload, dict(exc.headers)


def _request_text(url: str, *, cookie: str = "", follow_redirects: bool = True) -> tuple[int, str, dict]:
    request = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


@pytest.fixture
def running_web_app(monkeypatch, tmp_path):
    from stock_pipeline import web

    servers = []

    class TestHTTPServer(RealThreadingHTTPServer):
        allow_reuse_address = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            servers.append(self)

    settings = Settings(
        tushare_token="",
        web_username="admin",
        web_password="admin-password",
        web_session_secret="test-session-secret",
        web_key_encryption_secret="test-key-secret",
        web_invite_codes="",
        stock_agent_engine="legacy",
        stock_agent_template="native",
        stock_analysis_execution_enabled=False,
        data_fetch_approval_required=False,
    )
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "ThreadingHTTPServer", TestHTTPServer)
    monkeypatch.setattr(web, "get_settings", lambda require_deepseek=False: settings)
    monkeypatch.setattr(web, "TushareClient", _FakeTushareClient)
    monkeypatch.setattr(web, "StockSearchIndex", _FakeStockSearchIndex)
    monkeypatch.setattr(web, "provider_status", lambda key: "archived" if key == "tushare" else "active")
    monkeypatch.setattr(
        web,
        "data_source_snapshot",
        lambda settings: {"summary": {"provider_count": 4, "active_count": 3, "archived_count": 1, "planned_count": 0}},
    )
    monkeypatch.setattr(
        web,
        "crawler_status_snapshot",
        lambda **kwargs: {"summary": {"running_count": 0, "expired_running_count": 0}, "alerts": []},
    )
    monkeypatch.setattr(web, "news_crawler_prometheus_metrics", lambda: "# no crawler metrics\n")

    app = web.StockWebApp(host="127.0.0.1", port=_free_port())
    archive_payload = {
        "users": {},
        "demo_accounts": {},
        "usage": {},
        "archived_users": {
            "alice": {
                "archived_at": "20260708_103700",
                "archived_by": "admin",
                "reason": "manual cleanup",
                "account": {"created_at": "20260701_090000", "invite_code": "INV-1"},
                "usage": {"by_path": {"/api/analyze": 7, "/api/health": 99}, "last_request_at": "20260708_103000"},
            }
        },
        "archived_demo_accounts": {
            "demo001": {
                "archived_at": "20260707_213000",
                "archived_by": "admin",
                "reason": "old demo",
                "account": {"created_at": "20260701_080000"},
                "usage": {"by_path": {"/api/sync-stock-data": 3}, "last_request_at": "20260707_210000"},
            }
        },
    }
    app.user_store.path.write_text(json.dumps(archive_payload, ensure_ascii=False), encoding="utf-8")
    app._replace_user_session("admin-token", {"username": "admin", "role": "admin"})
    app._replace_user_session("user-token", {"username": "viewer", "role": "user"})

    thread = threading.Thread(target=app.serve, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{app.port}"
    for _ in range(80):
        try:
            status, payload, _headers = _request_json(f"{base_url}/api/health")
            if status == 200 and payload.get("ok"):
                break
        except OSError:
            pass
        time.sleep(0.05)
    else:
        pytest.fail("web server did not become ready")

    try:
        yield {
            "app": app,
            "base_url": base_url,
            "admin_cookie": _signed_cookie(app, "admin-token"),
            "user_cookie": _signed_cookie(app, "user-token"),
        }
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        thread.join(timeout=2)


def test_health_api_smoke_returns_core_runtime_shape(running_web_app):
    status, payload, headers = _request_json(f"{running_web_app['base_url']}/api/health")

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["web"]["port"] == running_web_app["app"].port
    assert payload["config"]["tushare_status"] == "archived"
    assert payload["data_sources"]["provider_count"] == 4


def test_session_api_reports_anonymous_and_authenticated_sessions(running_web_app):
    base_url = running_web_app["base_url"]

    anonymous_status, anonymous, _headers = _request_json(f"{base_url}/api/session")
    admin_status, admin, _headers = _request_json(f"{base_url}/api/session", cookie=running_web_app["admin_cookie"])

    assert anonymous_status == 200
    assert anonymous["authenticated"] is False
    assert admin_status == 200
    assert admin["authenticated"] is True
    assert admin["user"] == "admin"
    assert admin["role"] == "admin"


def test_admin_api_denies_missing_bad_and_non_admin_sessions(running_web_app):
    base_url = running_web_app["base_url"]

    missing_status, missing, _headers = _request_json(f"{base_url}/api/admin/archives")
    bad_status, bad, _headers = _request_json(f"{base_url}/api/admin/archives", cookie="stock_session=admin-token.bad")
    user_status, user, _headers = _request_json(f"{base_url}/api/admin/archives", cookie=running_web_app["user_cookie"])

    assert missing_status == 401
    assert missing["error"] == "请先登录"
    assert bad_status == 401
    assert bad["error"] == "请先登录"
    assert user_status == 403
    assert user["error"] == "需要管理员权限"


def test_admin_archives_api_returns_unified_archive_contract(running_web_app):
    status, payload, _headers = _request_json(
        f"{running_web_app['base_url']}/api/admin/archives",
        cookie=running_web_app["admin_cookie"],
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["counts"] == {"users": 1, "demo_accounts": 1, "total": 2}
    assert [item["username"] for item in payload["items"]] == ["alice", "demo001"]
    assert payload["users"][0]["kind"] == "user"
    assert payload["demo_accounts"][0]["kind"] == "demo"
    assert payload["items"][0]["usage_total"] == 7
    assert "/api/health" not in payload["items"][0]["by_path"]


def test_admin_archives_api_searches_registered_and_demo_archive_fields(running_web_app):
    base_url = running_web_app["base_url"]
    cookie = running_web_app["admin_cookie"]

    by_reason = _request_json(f"{base_url}/api/admin/archives?q=manual", cookie=cookie)[1]
    by_operator = _request_json(f"{base_url}/api/admin/archives?q=demo", cookie=cookie)[1]
    by_invite = _request_json(f"{base_url}/api/admin/archives?q=INV-1", cookie=cookie)[1]

    assert [item["username"] for item in by_reason["items"]] == ["alice"]
    assert [item["username"] for item in by_operator["items"]] == ["demo001"]
    assert [item["username"] for item in by_invite["items"]] == ["alice"]


def test_admin_overview_api_exposes_archive_counts_without_archive_rows(running_web_app):
    status, payload, _headers = _request_json(
        f"{running_web_app['base_url']}/api/admin/overview",
        cookie=running_web_app["admin_cookie"],
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["archived_users_count"] == 1
    assert payload["archived_demo_accounts_count"] == 1
    assert payload["users"] == []
    assert payload["demo_accounts"] == []
    assert "items" not in payload


def test_ops_status_api_smoke_returns_task_snapshot(running_web_app):
    status, payload, _headers = _request_json(
        f"{running_web_app['base_url']}/api/admin/ops/status",
        cookie=running_web_app["admin_cookie"],
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["snapshot"]["overall"]["status"] in {"ok", "warning", "critical"}
    task_ids = {task["id"] for task in payload["snapshot"]["tasks"]}
    assert "minute_cold_stock_year_upload" in task_ids
    assert "news_crawler" in task_ids


def test_ops_status_api_denies_regular_user(running_web_app):
    status, payload, _headers = _request_json(
        f"{running_web_app['base_url']}/api/admin/ops/status",
        cookie=running_web_app["user_cookie"],
    )

    assert status == 403
    assert payload["ok"] is False
    assert payload["error"] == "需要管理员权限"


def test_protected_admin_page_redirects_without_session_and_loads_with_admin_cookie(running_web_app):
    base_url = running_web_app["base_url"]

    redirect_status, _body, redirect_headers = _request_text(
        f"{base_url}/admin-accounts.html",
        follow_redirects=False,
    )
    page_status, page, page_headers = _request_text(
        f"{base_url}/admin-accounts.html",
        cookie=running_web_app["admin_cookie"],
    )

    assert redirect_status == 302
    assert redirect_headers["Location"] == "/login"
    assert page_status == 200
    assert page_headers["Cache-Control"] == "no-store, max-age=0"
    assert "archiveUsersTable" in page
    assert "time-archive-20260708-v1" in page


def test_public_project_page_and_crawler_metrics_are_reachable_without_login(running_web_app):
    base_url = running_web_app["base_url"]

    project_status, project_page, _headers = _request_text(f"{base_url}/project.html")
    metrics_status, metrics, metrics_headers = _request_text(f"{base_url}/metrics/news-crawler")

    assert project_status == 200
    assert "NewsAnalysis" in project_page or "数据" in project_page
    assert metrics_status == 200
    assert metrics_headers["Content-Type"].startswith("text/plain")
    assert "# no crawler metrics" in metrics


def test_search_api_uses_authenticated_runtime_and_returns_stock_results(running_web_app):
    query = urllib.parse.quote("平安")
    status, payload, _headers = _request_json(
        f"{running_web_app['base_url']}/api/search?q={query}",
        cookie=running_web_app["user_cookie"],
    )

    assert status == 200
    assert payload["items"] == [{"ts_code": "000001.SZ", "name": "平安银行"}]
