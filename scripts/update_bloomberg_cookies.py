#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "local_data" / "secure" / "news_crawler" / "bloomberg_cookies_json.txt"
LOGIN_COOKIE_NAMES = ("_pxhd", "_px2", "session_id", "agent_id", "_breg-uid")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Bloomberg cookies from a logged-in Chrome debugging session.")
    parser.add_argument("--debug-url", default=os.getenv("BLOOMBERG_CHROME_DEBUG_URL", "http://127.0.0.1:9222"))
    parser.add_argument("--output", default=os.getenv("BLOOMBERG_COOKIES_JSON_FILE", str(DEFAULT_OUTPUT)))
    parser.add_argument("--domain", default="bloomberg.com")
    parser.add_argument("--require-login", action="store_true", default=_env_bool("BLOOMBERG_REQUIRE_LOGIN_COOKIE", False))
    parser.add_argument("--write-require-login-flag", action="store_true", help="Write BLOOMBERG_REQUIRE_LOGIN_COOKIE_FILE=1 after cookie refresh.")
    parser.add_argument("--clear-pause", action=argparse.BooleanOptionalAction, default=True, help="Clear active Bloomberg source pause in MongoDB after refresh.")
    args = parser.parse_args()

    try:
        cookies = get_bloomberg_cookies(args.debug_url, args.domain)
    except Exception as exc:
        raise SystemExit(f"读取 Chrome 调试 cookie 失败：{exc}") from exc
    if not cookies:
        raise SystemExit("未从 Chrome 调试会话获取到 Bloomberg cookie，请确认 Chrome 已登录 Bloomberg。")
    summary = login_cookie_summary(cookies)
    if args.require_login and not summary["valid"]:
        raise SystemExit(f"Bloomberg 登录 cookie 不完整：{summary['valid_count']}/{len(LOGIN_COOKIE_NAMES)}，缺失 {', '.join(summary['missing'])}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(output, 0o600)

    if args.write_require_login_flag:
        flag_path = Path(os.getenv("BLOOMBERG_REQUIRE_LOGIN_COOKIE_FILE", str(output.parent / "bloomberg_require_login_cookie.txt")))
        flag_path.write_text("1", encoding="utf-8")
        os.chmod(flag_path, 0o600)

    if args.clear_pause:
        clear_bloomberg_pause()

    print(
        json.dumps(
            {
                "ok": True,
                "cookie_count": len(cookies),
                "output": str(output),
                "login_cookie_valid": summary["valid"],
                "login_cookie_count": summary["valid_count"],
                "missing_login_cookies": summary["missing"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def get_bloomberg_cookies(debug_url: str, domain: str) -> list[dict]:
    websocket_url = browser_websocket_url(debug_url, preferred_domain=domain)
    with DevToolsWebSocket(websocket_url) as ws:
        ws.call("Network.enable")
        result = ws.call("Network.getAllCookies")
    items = result.get("cookies") or []
    cookies = []
    for cookie in items:
        cookie_domain = str(cookie.get("domain") or "")
        if domain.lower() not in cookie_domain.lower():
            continue
        cookies.append(
            {
                "domain": cookie.get("domain"),
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "path": cookie.get("path", "/"),
                "expires": cookie.get("expires", -1),
                "secure": bool(cookie.get("secure", False)),
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "sameSite": cookie.get("sameSite", "None"),
            }
        )
    return [cookie for cookie in cookies if cookie.get("name") and cookie.get("value")]


def browser_websocket_url(debug_url: str, preferred_domain: str = "") -> str:
    base = debug_url.rstrip("/")
    version_websocket_url = ""
    for path in ("/json/list", "/json/version"):
        with urllib.request.urlopen(base + path, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl"):
            version_websocket_url = str(payload["webSocketDebuggerUrl"])
            continue
        if isinstance(payload, list):
            preferred = _select_page_websocket_url(payload, preferred_domain)
            if preferred:
                return preferred
            for item in payload:
                if isinstance(item, dict) and item.get("webSocketDebuggerUrl"):
                    return str(item["webSocketDebuggerUrl"])
    if version_websocket_url:
        return version_websocket_url
    raise RuntimeError("Chrome DevTools 没有返回 webSocketDebuggerUrl。")


def _select_page_websocket_url(items: list, preferred_domain: str = "") -> str:
    page_targets = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("webSocketDebuggerUrl")
        and str(item.get("type") or "").lower() == "page"
    ]
    if preferred_domain:
        preferred_domain = preferred_domain.lower()
        for item in page_targets:
            if preferred_domain in str(item.get("url") or "").lower():
                return str(item["webSocketDebuggerUrl"])
    if page_targets:
        return str(page_targets[0]["webSocketDebuggerUrl"])
    return ""


class DevToolsWebSocket:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.sock = None
        self.next_id = 1

    def __enter__(self):
        self.sock = _connect_websocket(self.websocket_url)
        return self

    def __exit__(self, *_):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def call(self, method: str, params: dict | None = None) -> dict:
        message_id = self.next_id
        self.next_id += 1
        _send_ws_text(self.sock, json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + 10
        while time.time() < deadline:
            message = json.loads(_recv_ws_text(self.sock))
            if message.get("id") != message_id:
                continue
            if message.get("error"):
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return dict(message.get("result") or {})
        raise TimeoutError(f"CDP {method} timed out")


def _connect_websocket(url: str):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"ws", "wss"}:
        raise ValueError(f"Unsupported websocket URL: {url}")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    raw = socket.create_connection((parsed.hostname, port), timeout=5)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname) if parsed.scheme == "wss" else raw
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {parsed.hostname}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        raise RuntimeError(f"WebSocket handshake failed: {response[:200]!r}")
    return sock


def _send_ws_text(sock, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.extend([0x80 | 126, *struct.pack("!H", length)])
    else:
        header.extend([0x80 | 127, *struct.pack("!Q", length)])
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _recv_ws_text(sock) -> str:
    first = _read_exact(sock, 2)
    opcode = first[0] & 0x0F
    length = first[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    masked = bool(first[1] & 0x80)
    mask = _read_exact(sock, 4) if masked else b""
    payload = _read_exact(sock, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 0x8:
        raise RuntimeError("WebSocket closed by Chrome")
    if opcode != 0x1:
        return _recv_ws_text(sock)
    return payload.decode("utf-8")


def _read_exact(sock, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("WebSocket connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def login_cookie_summary(cookies: list[dict]) -> dict:
    values = {str(item.get("name") or ""): str(item.get("value") or "") for item in cookies}
    valid = [name for name in LOGIN_COOKIE_NAMES if len(values.get(name, "")) > 10]
    missing = [name for name in LOGIN_COOKIE_NAMES if name not in valid]
    return {"valid": "_breg-uid" in valid and len(valid) >= 4, "valid_count": len(valid), "missing": missing}


def clear_bloomberg_pause() -> None:
    try:
        import pymongo
    except ImportError:
        return
    uri = _mongo_uri()
    if not uri:
        return
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=1200, socketTimeoutMS=1500)
    try:
        database = os.getenv("MONGODB_DATABASE", "news")
        client[database]["source_pauses"].update_many(
            {"source_name": "bloomberg", "active": True},
            {"$set": {"active": False, "cleared_at": _utc_now()}},
        )
    except Exception:
        return
    finally:
        client.close()


def _mongo_uri() -> str:
    direct = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    if direct:
        return direct
    host = os.getenv("MONGO_HOST", "")
    if not host:
        return ""
    port = os.getenv("MONGO_PORT", "27017")
    user = os.getenv("MONGO_USER", "")
    password = os.getenv("MONGO_PASSWORD", "") or _read_file(os.getenv("MONGO_PASSWORD_FILE", ""))
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if user and password:
        return f"mongodb://{urllib.parse.quote_plus(user)}:{urllib.parse.quote_plus(password)}@{host}:{port}/?authSource={auth_source}"
    return f"mongodb://{host}:{port}/"


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip() if path else ""
    except OSError:
        return ""


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    sys.exit(main())
