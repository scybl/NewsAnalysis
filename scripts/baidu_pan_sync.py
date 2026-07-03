from __future__ import annotations

import argparse
import json
import mimetypes
import os
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SECURE_DIR = "/opt/NewsAnalysis/local_data/secure/baidu_pan"
DEFAULT_REMOTE_ROOT = "/apps/NewsAnalysis/NewsAnalysis"
DEFAULT_SCOPE = "basic,netdisk"
DEVICE_CODE_URL = "https://openapi.baidu.com/oauth/2.0/device/code"
TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
LOCATE_UPLOAD_URL = "https://d.pcs.baidu.com/rest/2.0/pcs/file"
FALLBACK_UPLOAD_HOST = "https://c3.pcs.baidu.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorize and upload small probes to Baidu Netdisk.")
    parser.add_argument("--secure-dir", default=DEFAULT_SECURE_DIR, help="Directory containing app_key/secret_key and token files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="Start device-code authorization and save access/refresh tokens.")
    auth.add_argument("--scope", default=DEFAULT_SCOPE)
    auth.add_argument("--poll-seconds", type=int, default=300, help="How long to poll after printing the user code.")

    probe = subparsers.add_parser("probe", help="Upload a tiny JSON probe file.")
    probe.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    probe.add_argument("--remote-path", default="", help="Absolute /apps/... path. Overrides --remote-root.")
    probe.add_argument("--file", default="", help="Optional local file to upload instead of an auto-created probe.")
    probe.add_argument("--ondup", default="newcopy", choices=("fail", "overwrite", "newcopy"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    secure_dir = Path(args.secure_dir)
    if args.command == "auth":
        return authorize(secure_dir, args.scope, args.poll_seconds)
    if args.command == "probe":
        return upload_probe(secure_dir, args)
    raise SystemExit(f"unknown command: {args.command}")


def authorize(secure_dir: Path, scope: str, poll_seconds: int) -> int:
    app_key = read_secret(secure_dir / "app_key")
    secret_key = read_secret(secure_dir / "secret_key")
    response = http_json(
        DEVICE_CODE_URL,
        {
            "response_type": "device_code",
            "client_id": app_key,
            "scope": scope,
        },
    )
    if "error" in response:
        print(json.dumps(redact(response), ensure_ascii=False, indent=2))
        return 1

    device_code = str(response["device_code"])
    user_code = str(response.get("user_code") or "")
    interval = max(5, int(response.get("interval") or 5))
    expires_in = int(response.get("expires_in") or 0)
    print("Open this URL and authorize the device:")
    print(str(response.get("verification_url") or "https://openapi.baidu.com/device"))
    if user_code:
        print(f"User code: {user_code}")
    if response.get("qrcode_url"):
        print(f"QR code URL: {response['qrcode_url']}")
    if poll_seconds <= 0:
        print("Authorization request created. Re-run auth with polling after approving it.")
        return 0

    deadline = time.monotonic() + min(poll_seconds, expires_in or poll_seconds)
    while time.monotonic() < deadline:
        time.sleep(interval)
        token = http_json(
            TOKEN_URL,
            {
                "grant_type": "device_token",
                "code": device_code,
                "client_id": app_key,
                "client_secret": secret_key,
            },
            fail_on_http_error=False,
        )
        if token.get("access_token"):
            save_token_files(secure_dir, token)
            print("Authorization succeeded. Token files saved.")
            print(json.dumps(redact(token), ensure_ascii=False, indent=2))
            return 0
        error = str(token.get("error") or "")
        if error not in {"authorization_pending", "slow_down"}:
            print(json.dumps(redact(token), ensure_ascii=False, indent=2))
            return 1
        if error == "slow_down":
            interval += 5
        print("Waiting for user authorization...")
    print("Timed out waiting for authorization.")
    return 2


def upload_probe(secure_dir: Path, args: argparse.Namespace) -> int:
    token = load_or_refresh_token(secure_dir)
    if not token:
        print("No access_token found. Run auth first:")
        print(f"python3 {Path(__file__).name} --secure-dir {secure_dir} auth")
        return 2

    local_path = Path(args.file) if args.file else create_probe_file()
    remote_path = args.remote_path or build_remote_probe_path(args.remote_root, local_path.name)
    host = locate_upload_host(str(token["access_token"]))
    response = upload_file(host, str(token["access_token"]), remote_path, local_path, args.ondup)
    print(json.dumps(redact(response), ensure_ascii=False, indent=2))
    if response.get("error_code") or response.get("error"):
        return 1
    print(f"Uploaded probe to {remote_path}")
    return 0


def load_or_refresh_token(secure_dir: Path) -> dict[str, Any]:
    token = read_token(secure_dir)
    if token.get("access_token"):
        return token
    refresh_token = token.get("refresh_token") or read_optional_secret(secure_dir / "refresh_token")
    if not refresh_token:
        return {}
    app_key = read_secret(secure_dir / "app_key")
    secret_key = read_secret(secure_dir / "secret_key")
    refreshed = http_json(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": app_key,
            "client_secret": secret_key,
        },
        fail_on_http_error=False,
    )
    if refreshed.get("access_token"):
        save_token_files(secure_dir, refreshed)
        return refreshed
    print(json.dumps(redact(refreshed), ensure_ascii=False, indent=2))
    return {}


def locate_upload_host(access_token: str) -> str:
    response = http_json(
        LOCATE_UPLOAD_URL,
        {
            "method": "locateupload",
            "access_token": access_token,
        },
        fail_on_http_error=False,
    )
    servers = response.get("servers") if isinstance(response, dict) else None
    if isinstance(servers, list):
        for server in servers:
            value = server.get("server") if isinstance(server, dict) else ""
            if isinstance(value, str) and value.startswith("https://"):
                return value.rstrip("/")
    value = response.get("server") if isinstance(response, dict) else ""
    if isinstance(value, str) and value.startswith("https://"):
        return value.rstrip("/")
    return FALLBACK_UPLOAD_HOST


def upload_file(host: str, access_token: str, remote_path: str, local_path: Path, ondup: str) -> dict[str, Any]:
    url = host.rstrip("/") + "/rest/2.0/pcs/file?" + urllib.parse.urlencode(
        {
            "method": "upload",
            "access_token": access_token,
            "path": remote_path,
            "ondup": ondup,
        }
    )
    body, content_type = multipart_body("file", local_path)
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    return request_json(request, fail_on_http_error=False)


def multipart_body(field_name: str, path: Path) -> tuple[bytes, str]:
    boundary = f"----NewsAnalysisBaiduPan{int(time.time() * 1000)}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return prefix + path.read_bytes() + suffix, f"multipart/form-data; boundary={boundary}"


def create_probe_file() -> Path:
    payload = {
        "kind": "newsanalysis.baidu_pan_probe",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    handle, name = tempfile.mkstemp(prefix="baidu-pan-probe-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return Path(name)


def build_remote_probe_path(remote_root: str, filename: str) -> str:
    root = "/" + remote_root.strip("/")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{root}/probe/{stamp}-{filename}"


def http_json(url: str, params: dict[str, str], fail_on_http_error: bool = True) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}")
    return request_json(request, fail_on_http_error=fail_on_http_error)


def request_json(request: urllib.request.Request, fail_on_http_error: bool = True) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if fail_on_http_error:
            raise
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"http_status": exc.code, "body": body}


def read_secret(path: Path) -> str:
    value = read_optional_secret(path)
    if not value:
        raise SystemExit(f"missing secret file: {path}")
    return value


def read_optional_secret(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def read_token(secure_dir: Path) -> dict[str, Any]:
    token_path = secure_dir / "token.json"
    if token_path.exists():
        return json.loads(token_path.read_text(encoding="utf-8"))
    access_token = read_optional_secret(secure_dir / "access_token")
    refresh_token = read_optional_secret(secure_dir / "refresh_token")
    token: dict[str, Any] = {}
    if access_token:
        token["access_token"] = access_token
    if refresh_token:
        token["refresh_token"] = refresh_token
    return token


def save_token_files(secure_dir: Path, token: dict[str, Any]) -> None:
    secure_dir.mkdir(parents=True, exist_ok=True)
    write_secret(secure_dir / "token.json", json.dumps(token, ensure_ascii=False, indent=2) + "\n")
    if token.get("access_token"):
        write_secret(secure_dir / "access_token", str(token["access_token"]) + "\n")
    if token.get("refresh_token"):
        write_secret(secure_dir / "refresh_token", str(token["refresh_token"]) + "\n")


def write_secret(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if key in {"access_token", "refresh_token", "session_key", "session_secret"}:
                result[key] = f"<redacted:{len(str(value))}>"
            else:
                result[key] = redact(value)
        return result
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
