import hashlib
import hmac
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer as RealThreadingHTTPServer

import pytest

from stock_pipeline.config import Settings


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


def _request_json(url: str, *, cookie: str = "") -> tuple[int, dict]:
    headers = {"Cookie": cookie} if cookie else {}
    request = urllib.request.Request(url, headers=headers)
    return _open_json(request)


def _post_json(url: str, payload: dict, *, cookie: str = "") -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    return _open_json(request)


def _open_json(request: urllib.request.Request) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body.strip().startswith("{") else {"raw": body}


@pytest.fixture
def running_ops_queue_app(monkeypatch, tmp_path):
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
        admin_readonly_username="readonly",
        admin_readonly_password="readonly-password",
        stock_analysis_execution_enabled=False,
        data_fetch_approval_required=True,
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
    app.task_queue.stop_event.set()
    if app.task_queue.thread:
        app.task_queue.thread.join(timeout=1)
    app._replace_user_session("admin-token", {"username": "admin", "role": "admin"})
    app._replace_user_session("user-token", {"username": "viewer", "role": "user"})
    app._replace_user_session("readonly-token", {"username": "readonly", "role": "admin_readonly"})
    for task_id in ["qa", "qb", "qc"]:
        app.task_registry.create_task(task_id, "manual_queue_test", task_id.upper())
        app.task_queue.enqueue(
            task_id=task_id,
            handler_key="handler",
            kind="manual_queue_test",
            title=task_id.upper(),
            payload={"trigger": "manual", "ts_code": f"00000{len(task_id)}.SZ"},
            resource_level="normal",
        )

    thread = threading.Thread(target=app.serve, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{app.port}"
    for _ in range(80):
        try:
            status, payload = _request_json(f"{base_url}/api/health")
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
            "readonly_cookie": _signed_cookie(app, "readonly-token"),
        }
    finally:
        app.task_queue.stop_event.set()
        for server in servers:
            server.shutdown()
            server.server_close()
        thread.join(timeout=2)


def test_task_queue_reorder_api_requires_admin_write_and_approval(running_ops_queue_app):
    base_url = running_ops_queue_app["base_url"]
    url = f"{base_url}/api/admin/task-queue"

    missing_status, missing = _post_json(url, {"action": "reorder", "task_ids": ["qc", "qa"]})
    user_status, user = _post_json(url, {"action": "reorder", "task_ids": ["qc", "qa"]}, cookie=running_ops_queue_app["user_cookie"])
    readonly_status, readonly = _post_json(url, {"action": "reorder", "task_ids": ["qc", "qa"], "approved": True}, cookie=running_ops_queue_app["readonly_cookie"])
    approval_status, approval = _post_json(url, {"action": "reorder", "task_ids": ["qc", "qa"]}, cookie=running_ops_queue_app["admin_cookie"])

    assert missing_status == 401
    assert missing["error"] == "请先登录"
    assert user_status == 403
    assert user["error"] == "需要管理员权限"
    assert readonly_status == 403
    assert "只读后台账号" in readonly["error"]
    assert approval_status == 428
    assert approval["approval_action"] == "/api/admin/task-queue"


def test_task_queue_reorder_api_persists_order_and_returns_fresh_snapshot(running_ops_queue_app):
    app = running_ops_queue_app["app"]
    status, payload = _post_json(
        f"{running_ops_queue_app['base_url']}/api/admin/task-queue",
        {"action": "reorder", "task_ids": ["qc", "qa", "qb"], "approved": True},
        cookie=running_ops_queue_app["admin_cookie"],
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["result"]["action"] == "reordered"
    assert [item["task_id"] for item in payload["snapshot"]["resources"]["task_queue"]["items"][:3]] == ["qc", "qa", "qb"]
    assert app.task_registry.get_task("qc")["metadata"]["queue_status"] == "manual_reordered"

    queue_file = json.loads((app.task_queue.path).read_text(encoding="utf-8"))
    persisted = {item["task_id"]: item for item in queue_file["items"]}
    assert persisted["qc"]["manual_order_index"] == 0
    assert persisted["qa"]["manual_order_index"] == 1
    assert persisted["qb"]["manual_order_index"] == 2


def test_task_queue_delay_api_updates_registry_and_snapshot(running_ops_queue_app):
    app = running_ops_queue_app["app"]
    status, payload = _post_json(
        f"{running_ops_queue_app['base_url']}/api/admin/task-queue",
        {"action": "delay", "task_id": "qb", "delay_seconds": 600, "approved": True},
        cookie=running_ops_queue_app["admin_cookie"],
    )
    items = {item["task_id"]: item for item in payload["snapshot"]["resources"]["task_queue"]["items"]}

    assert status == 200
    assert payload["result"]["action"] == "delayed"
    assert items["qb"]["status"] == "deferred"
    assert items["qb"]["reorderable"] is True
    assert app.task_registry.get_task("qb")["metadata"]["queue_status"] == "manual_delayed"
