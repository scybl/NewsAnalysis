import json
import socket

from scripts import update_bloomberg_cookies as updater


def test_login_cookie_summary_requires_breg_uid_and_four_valid_cookies():
    cookies = [
        {"name": "_pxhd", "value": "x" * 12},
        {"name": "_px2", "value": "x" * 12},
        {"name": "session_id", "value": "x" * 12},
        {"name": "agent_id", "value": "x" * 12},
    ]

    summary = updater.login_cookie_summary(cookies)

    assert summary["valid"] is False
    assert "_breg-uid" in summary["missing"]

    cookies.append({"name": "_breg-uid", "value": "x" * 12})
    assert updater.login_cookie_summary(cookies)["valid"] is True


def test_websocket_text_frame_roundtrip():
    left, right = socket.socketpair()
    try:
        updater._send_ws_text(left, json.dumps({"ok": True}))
        assert json.loads(updater._recv_ws_text(right)) == {"ok": True}
    finally:
        left.close()
        right.close()


def test_browser_websocket_url_prefers_bloomberg_page(monkeypatch):
    responses = {
        "http://127.0.0.1:9222/json/list": [
            {
                "type": "page",
                "url": "https://example.com/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/example",
            },
            {
                "type": "page",
                "url": "https://www.bloomberg.com/asia",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/bloomberg",
            },
        ],
        "http://127.0.0.1:9222/json/version": {
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/browser-id"
        },
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(url, timeout):
        return FakeResponse(responses[url])

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    assert (
        updater.browser_websocket_url("http://127.0.0.1:9222", preferred_domain="bloomberg.com")
        == "ws://127.0.0.1:9222/devtools/page/bloomberg"
    )


def test_browser_websocket_url_prefers_politico_page(monkeypatch):
    responses = {
        "http://127.0.0.1:9222/json/list": [
            {
                "type": "page",
                "url": "https://www.bloomberg.com/asia",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/bloomberg",
            },
            {
                "type": "page",
                "url": "https://www.politico.com/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/politico",
            },
        ],
        "http://127.0.0.1:9222/json/version": {
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/browser-id"
        },
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(url, timeout):
        return FakeResponse(responses[url])

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    assert (
        updater.browser_websocket_url("http://127.0.0.1:9222", preferred_domain="politico.com")
        == "ws://127.0.0.1:9222/devtools/page/politico"
    )


def test_politico_cookie_preset_writes_to_politico_file():
    preset = updater.PRESETS["politico_browser"]

    assert preset["domain"] == "politico.com"
    assert str(preset["default_output"]).endswith("politico_browser_cookies_json.txt")
    assert preset["pause_sources"] == ("politico_browser", "politico_rss")
