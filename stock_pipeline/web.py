from __future__ import annotations

import secrets
import json
import time
import hmac
import hashlib
import base64
import threading
import uuid
import os
import signal
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.cookies import SimpleCookie
from cryptography.fernet import Fernet, InvalidToken

from .analyst import StockAnalyst, session_path_for
from .agents import MultiAgentRunner, list_agent_runs, read_agent_run
from .agents.multi_agent import MultiAgentOptions
from .analysis_frameworks import get_analysis_framework, list_analysis_frameworks
from .collector import StockDataCollector
from .config import PROJECT_ROOT, get_settings
from .deepseek_client import DeepSeekClient
from .dossier import build_dossier
from .field_labels import build_table_datasets
from .stock_search import StockSearchIndex
from .stock_storage import analysis_dossier_path, analysis_output_path, analysis_review_context, build_local_stock_payload, current_dir, list_analysis_results, read_analysis_result, stock_exists, stock_status, sync_stock_data
from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, write_json


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
SPIDER_TYPES = ("财经要闻", "宏观经济", "产经新闻", "国际财经", "金融市场", "公司新闻", "区域经济", "财经评论", "财经人物")
BILLABLE_API_PATHS = {
    "/api/refresh",
    "/api/sync-stock-data",
    "/api/analyze",
    "/api/multi-agent-analyze",
}
USER_KEY_NAMES = {"tushare", "deepseek"}


class StockWebApp:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.settings = get_settings(require_deepseek=False)
        self.tushare = TushareClient(self.settings.tushare_token, self.settings.tushare_base_url)
        self.index = StockSearchIndex(self.tushare, PROJECT_ROOT / "cache" / "stocks.json")
        self.sessions: dict[str, dict] = {}
        self.active_session_by_user: dict[str, str] = {}
        self.session_lock = threading.Lock()
        self.session_ttl_seconds = 60 * 60 * 12
        self.auth_secret = self.settings.web_session_secret or secrets.token_urlsafe(32)
        key_secret = self.settings.web_key_encryption_secret or self.settings.web_session_secret or self.settings.web_password
        self.key_cipher = ApiKeyCipher(key_secret)
        self.user_store = UserStore(PROJECT_ROOT / "local_data" / "web_users.json", self.key_cipher)
        self.invite_codes = {code.strip() for code in self.settings.web_invite_codes.split(",") if code.strip()}
        self.user_store.seed_invites(self.invite_codes, ttl_seconds=self.settings.web_invite_ttl_seconds, created_by="env")
        self.spider_controller = SpiderController(PROJECT_ROOT)
        self.multi_agent_jobs: dict[str, dict] = {}
        self.multi_agent_jobs_lock = threading.Lock()

    def _build_multi_agent_result(self, payload: dict, progress_callback=None) -> dict:
        ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
        analysis_type = str(payload.get("analysis_type") or "value_speculation")
        years, full_history = self._parse_history_scope_value(payload.get("years"))
        allow_dynamic_fetch = payload.get("allow_dynamic_fetch", True) is not False
        max_parallel_agents = int(payload.get("max_parallel_agents") or 8)
        tushare_client = payload.get("_tushare_client") or self.tushare
        llm_client = payload.get("_deepseek_client")
        return MultiAgentRunner(tushare_client, llm_client=llm_client, progress_callback=progress_callback).run(
            ts_code,
            MultiAgentOptions(
                analysis_type=analysis_type,
                allow_dynamic_fetch=allow_dynamic_fetch,
                use_llm_agents=bool(llm_client),
                years=years,
                full_history=full_history,
                max_parallel_agents=max_parallel_agents,
            ),
        )

    def _start_multi_agent_job(self, payload: dict) -> dict:
        job_id = uuid.uuid4().hex
        now = timestamp()
        job = {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "progress": [{"time": now, "stage": "queued", "message": "后台任务已创建，等待开始运行。", "details": {}}],
            "result": None,
            "error": "",
        }
        with self.multi_agent_jobs_lock:
            self.multi_agent_jobs[job_id] = job
        thread = threading.Thread(target=self._run_multi_agent_job, args=(job_id, payload), daemon=True)
        thread.start()
        return {"ok": True, "job_id": job_id, "status": "queued", "progress": job["progress"]}

    def _run_multi_agent_job(self, job_id: str, payload: dict) -> None:
        self._update_multi_agent_job(job_id, status="running", event={"stage": "running", "message": "后台任务开始运行。"})

        def progress(event: dict) -> None:
            self._update_multi_agent_job(job_id, event=event)

        try:
            result = self._build_multi_agent_result(payload, progress_callback=progress)
            self._update_multi_agent_job(job_id, status="succeeded", result=result, event={"stage": "succeeded", "message": "后台任务完成，结果已生成。"})
        except Exception as exc:  # noqa: BLE001 - expose readable UI error
            self._update_multi_agent_job(job_id, status="failed", error=str(exc), event={"stage": "failed", "message": str(exc)})

    def _update_multi_agent_job(
        self,
        job_id: str,
        status: str | None = None,
        event: dict | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self.multi_agent_jobs_lock:
            job = self.multi_agent_jobs.get(job_id)
            if not job:
                return
            job["updated_at"] = timestamp()
            if status:
                job["status"] = status
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = error
            if event:
                item = {"time": event.get("time") or timestamp(), "stage": event.get("stage") or "progress", "message": event.get("message") or "", "details": event.get("details") or {}}
                job.setdefault("progress", []).append(item)

    def _read_multi_agent_job(self, job_id: str) -> dict:
        with self.multi_agent_jobs_lock:
            job = self.multi_agent_jobs.get(job_id)
            if not job:
                raise FileNotFoundError(f"找不到多 Agent 后台任务：{job_id}")
            return json.loads(json.dumps(job, ensure_ascii=False, default=str))

    def _completed_multi_agent_job(self, result: dict, message: str) -> dict:
        job_id = uuid.uuid4().hex
        now = timestamp()
        job = {
            "ok": True,
            "job_id": job_id,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
            "progress": [
                {"time": now, "stage": "queued", "message": "后台任务已创建，等待共享结果。", "details": {}},
                {"time": now, "stage": "cache", "message": message, "details": {"cache_hit": True}},
                {"time": now, "stage": "succeeded", "message": "共享分析结果已加载。", "details": {}},
            ],
            "result": result,
            "error": "",
        }
        with self.multi_agent_jobs_lock:
            self.multi_agent_jobs[job_id] = job
        return {"ok": True, "job_id": job_id, "status": "succeeded", "progress": job["progress"]}

    def _recent_analysis_result(self, ts_code: str, analysis_type: str) -> dict | None:
        ttl = max(0, int(self.settings.stock_analysis_reuse_ttl_seconds or 0))
        if ttl <= 0:
            return None
        path = analysis_output_path(ts_code, analysis_type)
        if not path.exists():
            return None
        age = int(time.time() - path.stat().st_mtime)
        if age > ttl:
            return None
        payload = read_analysis_result(ts_code, analysis_type)
        payload["cached_analysis"] = True
        payload["cache_age_seconds"] = age
        return payload

    def _recent_agent_result(self, ts_code: str, analysis_type: str) -> dict | None:
        ttl = max(0, int(self.settings.stock_analysis_reuse_ttl_seconds or 0))
        if ttl <= 0:
            return None
        for item in list_agent_runs(ts_code, analysis_type):
            run_dir = Path(item.get("run_dir") or "")
            if not run_dir.exists():
                continue
            age = int(time.time() - run_dir.stat().st_mtime)
            if age > ttl:
                continue
            payload = read_agent_run(ts_code, item.get("run_id") or "")
            payload["cached_analysis"] = True
            payload["cache_age_seconds"] = age
            return payload
        return None

    def _parse_history_scope_value(self, value) -> tuple[int | None, bool]:
        if value in (None, "", "all", "full", "history"):
            return None, True
        return int(value), False

    def _replace_user_session(self, token: str, account: dict) -> None:
        username = account["username"]
        with self.session_lock:
            old_token = self.active_session_by_user.get(username)
            if old_token:
                self.sessions.pop(old_token, None)
            self.sessions[token] = {
                "username": username,
                "role": account["role"],
                "managed_demo": bool(account.get("managed_demo")),
                "expires_at": time.time() + self.session_ttl_seconds,
            }
            self.active_session_by_user[username] = token

    def _session_for_token(self, token: str) -> dict | None:
        with self.session_lock:
            session = self.sessions.get(token)
            if not session:
                return None
            username = session.get("username", "")
            if self.active_session_by_user.get(username) != token:
                self.sessions.pop(token, None)
                return None
            if session.get("expires_at", 0) < time.time():
                self._remove_session_locked(token, session)
                return None
            session["expires_at"] = time.time() + self.session_ttl_seconds
            return dict(session)

    def _remove_session(self, token: str) -> None:
        with self.session_lock:
            self._remove_session_locked(token, self.sessions.get(token))

    def _remove_session_locked(self, token: str, session: dict | None) -> None:
        if not session:
            return
        self.sessions.pop(token, None)
        username = session.get("username", "")
        if username and self.active_session_by_user.get(username) == token:
            self.active_session_by_user.pop(username, None)

    def serve(self) -> None:
        app = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

            def log_message(self, format: str, *args) -> None:
                print(f"{self.address_string()} - {format % args}")

            def end_headers(self) -> None:
                if not self.path.startswith("/api/"):
                    self.send_header("Cache-Control", "no-store, max-age=0")
                super().end_headers()

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path in ("/login", "/login.html"):
                    if self._is_authenticated():
                        self._redirect("/")
                        return
                    self.path = "/login.html"
                    super().do_GET()
                    return
                if parsed.path == "/api/session":
                    session = self._current_session()
                    access = self._access_state(session)
                    self._json(
                        {
                            "ok": True,
                            "authenticated": bool(session),
                            "user": session.get("username", "") if session else "",
                            "role": session.get("role", "") if session else "",
                            **access,
                            "demo_remaining": self._demo_remaining(session) if session and session.get("role") == "demo" else None,
                        }
                    )
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path == "/api/search":
                    query = parse_qs(parsed.query).get("q", [""])[0]
                    self._json({"items": app.index.search(query)})
                    return
                if parsed.path == "/api/refresh":
                    if not self._consume_billable_budget(parsed.path):
                        return
                    app.index.stocks(refresh=True)
                    self._record_billable_usage(parsed.path)
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/analysis-frameworks":
                    self._json({"ok": True, "items": list_analysis_frameworks()})
                    return
                if parsed.path == "/api/admin/overview":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.user_store.admin_overview(), "demo": self._demo_state()})
                    return
                if parsed.path == "/api/admin/spider/status":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.spider_controller.status()})
                    return
                if parsed.path == "/api/admin/spider/logs":
                    if not self._require_admin():
                        return
                    query = parse_qs(parsed.query)
                    lines = max(20, min(500, int(query.get("lines", ["120"])[0] or 120)))
                    self._json({"ok": True, **app.spider_controller.logs(lines=lines)})
                    return
                if parsed.path == "/api/user/api-keys":
                    session = self._current_session()
                    if not session:
                        self._json({"ok": False, "error": "请先登录"}, status=401)
                        return
                    self._json({"ok": True, **self._access_state(session)})
                    return
                super().do_GET()

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/login":
                    self._handle_login()
                    return
                if parsed.path == "/api/register":
                    self._handle_register()
                    return
                if parsed.path == "/api/logout":
                    self._handle_logout()
                    return
                if parsed.path == "/api/admin/invite":
                    if not self._require_admin():
                        return
                    self._handle_admin_invite()
                    return
                if parsed.path == "/api/admin/demo-account":
                    if not self._require_admin():
                        return
                    self._handle_admin_demo_account()
                    return
                if parsed.path == "/api/admin/vip-code":
                    if not self._require_admin():
                        return
                    self._handle_admin_vip_code()
                    return
                if parsed.path == "/api/admin/spider/start":
                    if not self._require_admin():
                        return
                    self._handle_admin_spider_start()
                    return
                if parsed.path == "/api/admin/spider/stop":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.spider_controller.stop()})
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path == "/api/redeem-vip":
                    self._handle_redeem_vip()
                    return
                if parsed.path == "/api/user/api-keys":
                    self._handle_save_user_api_keys()
                    return
                if parsed.path == "/api/user/api-keys/delete":
                    self._handle_delete_user_api_keys()
                    return
                if parsed.path == "/api/analyze":
                    self._handle_analyze()
                    return
                if parsed.path == "/api/multi-agent-analyze":
                    self._handle_multi_agent_analyze()
                    return
                if parsed.path == "/api/multi-agent-job":
                    self._handle_multi_agent_job()
                    return
                if parsed.path == "/api/agent-runs":
                    self._handle_agent_runs()
                    return
                if parsed.path == "/api/read-agent-run":
                    self._handle_read_agent_run()
                    return
                if parsed.path == "/api/read-analysis":
                    self._handle_read_analysis()
                    return
                if parsed.path == "/api/analysis-results":
                    self._handle_analysis_results()
                    return
                if parsed.path == "/api/sync-stock-data":
                    self._handle_sync_stock_data()
                    return
                if parsed.path == "/api/stock-status":
                    self._handle_stock_status()
                    return
                if parsed.path == "/api/local-stock-data":
                    self._handle_local_stock_data()
                    return
                if parsed.path == "/api/stock-data":
                    self._handle_local_stock_data()
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            def _handle_login(self) -> None:
                try:
                    payload = self._read_json()
                    username = str(payload.get("username") or "")
                    password = str(payload.get("password") or "")
                    account = self._authenticate(username, password)
                    if not account:
                        self._json({"ok": False, "error": "账号或密码错误"}, status=401)
                        return
                    self._login_account(account)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_register(self) -> None:
                try:
                    payload = self._read_json()
                    username = str(payload.get("username") or "").strip()
                    password = str(payload.get("password") or "")
                    invite_code = str(payload.get("invite_code") or "").strip()
                    if not invite_code:
                        self._json({"ok": False, "error": "请输入邀请码。"}, status=400)
                        return
                    invite_status = app.user_store.invite_status(invite_code)
                    if invite_status == "missing":
                        self._json({"ok": False, "error": "邀请码无效。"}, status=403)
                        return
                    if invite_status == "used":
                        self._json({"ok": False, "error": "邀请码已被使用。"}, status=403)
                        return
                    if invite_status == "expired":
                        self._json({"ok": False, "error": "邀请码已过期。"}, status=403)
                        return
                    if not self._valid_username(username):
                        self._json({"ok": False, "error": "账号只能包含字母、数字、下划线和短横线，长度 3-32。"}, status=400)
                        return
                    if len(password) < 8:
                        self._json({"ok": False, "error": "密码至少 8 位。"}, status=400)
                        return
                    if self._reserved_username(username):
                        self._json({"ok": False, "error": "该账号名不可注册。"}, status=409)
                        return
                    created, error = app.user_store.create_user(username, password, invite_code)
                    if not created:
                        if error == "invite_used":
                            self._json({"ok": False, "error": "邀请码已被使用。"}, status=403)
                            return
                        if error == "user_exists":
                            self._json({"ok": False, "error": "账号已存在。"}, status=409)
                            return
                        self._json({"ok": False, "error": "注册失败。"}, status=500)
                        return
                    self._login_account({"username": username, "role": "user"})
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_multi_agent_analyze(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    analysis_type = str(payload.get("analysis_type") or "value_speculation")
                    cached = app._recent_agent_result(ts_code, analysis_type)
                    if cached:
                        if payload.get("async"):
                            self._json(app._completed_multi_agent_job(cached, "检测到近期共享多 Agent 分析，已复用结果。"))
                        else:
                            self._json(cached)
                        return
                    payload["_tushare_client"] = self._tushare_for_session()
                    payload["_deepseek_client"] = self._deepseek_for_session()
                    if not self._consume_billable_budget("/api/multi-agent-analyze"):
                        return
                    if payload.get("async"):
                        result = app._start_multi_agent_job(payload)
                    else:
                        result = app._build_multi_agent_result(payload)
                    self._record_billable_usage("/api/multi-agent-analyze")
                    self._json(result)
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_multi_agent_job(self) -> None:
                try:
                    payload = self._read_json()
                    job_id = str(payload.get("job_id") or "")
                    self._json(app._read_multi_agent_job(job_id))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_agent_runs(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    analysis_type = str(payload.get("analysis_type") or "") or None
                    self._json({"ok": True, "ts_code": ts_code, "items": list_agent_runs(ts_code, analysis_type)})
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_read_agent_run(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    run_id = str(payload.get("run_id") or "")
                    self._json(read_agent_run(ts_code, run_id))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_logout(self) -> None:
                token = self._session_token()
                if token:
                    app._remove_session(token)
                self._json({"ok": True}, headers={"Set-Cookie": "stock_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

            def _handle_admin_invite(self) -> None:
                payload = self._read_json()
                count = max(1, min(20, int(payload.get("count") or 1)))
                session = self._current_session() or {}
                invites = [app.user_store.create_invite(session.get("username") or "admin", app.settings.web_invite_ttl_seconds) for _ in range(count)]
                self._json({"ok": True, "items": invites})

            def _handle_admin_demo_account(self) -> None:
                payload = self._read_json()
                count = max(1, min(20, int(payload.get("count") or 1)))
                limit = max(1, int(payload.get("limit") or app.settings.web_demo_request_limit))
                window_seconds = max(60, int(payload.get("window_seconds") or app.settings.web_demo_window_seconds))
                session = self._current_session() or {}
                accounts = [
                    app.user_store.create_demo_account(
                        created_by=session.get("username") or "admin",
                        limit=limit,
                        window_seconds=window_seconds,
                    )
                    for _ in range(count)
                ]
                self._json({"ok": True, "items": accounts})

            def _handle_admin_vip_code(self) -> None:
                payload = self._read_json()
                count = max(1, min(20, int(payload.get("count") or 1)))
                days = max(1, min(3650, int(payload.get("days") or 30)))
                ttl_seconds = max(300, min(31_536_000, int(payload.get("ttl_seconds") or app.settings.web_invite_ttl_seconds)))
                session = self._current_session() or {}
                items = [
                    app.user_store.create_vip_code(session.get("username") or "admin", days, ttl_seconds)
                    for _ in range(count)
                ]
                self._json({"ok": True, "items": items})

            def _handle_redeem_vip(self) -> None:
                session = self._current_session() or {}
                if session.get("role") != "user":
                    self._json({"ok": False, "error": "只有普通注册用户需要兑换 VIP。"}, status=400)
                    return
                code = str(self._read_json().get("code") or "").strip()
                ok, reason, access = app.user_store.redeem_vip_code(session.get("username") or "", code)
                if not ok:
                    message = {
                        "missing": "VIP 兑换码无效。",
                        "used": "VIP 兑换码已被使用。",
                        "expired": "VIP 兑换码已过期。",
                        "user_missing": "找不到当前用户。",
                    }.get(reason, "VIP 兑换失败。")
                    self._json({"ok": False, "error": message}, status=400)
                    return
                self._json({"ok": True, **self._access_state(session, access_override=access)})

            def _handle_save_user_api_keys(self) -> None:
                session = self._current_session() or {}
                if session.get("role") != "user":
                    self._json({"ok": False, "error": "只有普通注册用户可以保存自己的 API key。"}, status=400)
                    return
                payload = self._read_json()
                state = app.user_store.save_user_api_keys(
                    session.get("username") or "",
                    {"tushare": payload.get("tushare_api") or payload.get("tushare"), "deepseek": payload.get("deepseek_api") or payload.get("deepseek")},
                )
                self._json({"ok": True, **self._access_state(session, api_key_state=state)})

            def _handle_delete_user_api_keys(self) -> None:
                session = self._current_session() or {}
                if session.get("role") != "user":
                    self._json({"ok": False, "error": "只有普通注册用户可以删除自己的 API key。"}, status=400)
                    return
                payload = self._read_json()
                names = payload.get("keys")
                if not isinstance(names, list):
                    names = None
                state = app.user_store.delete_user_api_keys(session.get("username") or "", names)
                self._json({"ok": True, **self._access_state(session, api_key_state=state)})

            def _handle_admin_spider_start(self) -> None:
                payload = self._read_json()
                try:
                    result = app.spider_controller.start(payload)
                    self._json({"ok": True, **result})
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)
                except RuntimeError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=409)

            def _handle_analyze(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    framework = get_analysis_framework(str(payload.get("analysis_type") or "value_speculation"))
                    years, full_history = self._parse_history_scope(payload)
                    question = str(payload.get("question") or framework.question)
                    cached = app._recent_analysis_result(ts_code, framework.key)
                    if cached:
                        self._json(cached)
                        return
                    tushare_client = self._tushare_for_session()
                    deepseek_client = self._deepseek_for_session()
                    billable = bool(deepseek_client) or not stock_exists(ts_code)
                    if billable and not self._consume_billable_budget("/api/analyze"):
                        return
                    if not stock_exists(ts_code):
                        sync_stock_data(tushare_client, ts_code, years=years, full_history=full_history)
                    local_dir = current_dir(ts_code)
                    analysis_dossier = read_json(analysis_dossier_path(ts_code, framework.key))
                    metadata = read_json(local_dir / "metadata.json") if (local_dir / "metadata.json").exists() else {}
                    historical_context = analysis_review_context(
                        ts_code,
                        framework.key,
                        limit=app.settings.analysis_history_review_limit,
                    )

                    answer = ""
                    session_path = ""
                    if deepseek_client:
                        analyst = StockAnalyst(deepseek_client)
                        session = session_path_for(ts_code, PROJECT_ROOT / "sessions", framework.key)
                        answer = analyst.framework_analysis(
                            analysis_dossier,
                            session,
                            framework,
                            question=question,
                            historical_context=historical_context,
                        )
                        analysis_output_path(ts_code, framework.key).write_text(answer, encoding="utf-8")
                        session_path = str(session)
                    if billable:
                        self._record_billable_usage("/api/analyze")

                    self._json(
                        {
                            "ok": True,
                            "ts_code": ts_code,
                            "analysis_type": framework.key,
                            "analysis_label": framework.label,
                            "output_dir": str(local_dir),
                            "local_dir": str(local_dir),
                            "dossier_path": str(local_dir / "dossier.json"),
                            "value_dossier_path": str(local_dir / "value_speculation_dossier.json"),
                            "analysis_dossier_path": str(analysis_dossier_path(ts_code, framework.key)),
                            "analysis_path": str(analysis_output_path(ts_code, framework.key)) if answer else "",
                            "session_path": session_path,
                            "answer": answer,
                            "rating_hint": analysis_dossier.get("decision_helper", {}).get("rating_hint"),
                            "scores": analysis_dossier.get("decision_helper", {}).get("score_summary", {}),
                            "risk_flags": analysis_dossier.get("risk_flags", []),
                            "analysis_results": list_analysis_results(ts_code, framework.key),
                            "dataset_rows": metadata.get("dataset_rows", {}),
                            "fetch_errors": metadata.get("fetch_errors", []),
                        }
                    )
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_read_analysis(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    analysis_type = str(payload.get("analysis_type") or "value_speculation")
                    snapshot_name = str(payload.get("snapshot_name") or "")
                    self._json(read_analysis_result(ts_code, analysis_type, snapshot_name=snapshot_name))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_analysis_results(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    analysis_type = str(payload.get("analysis_type") or "value_speculation")
                    framework = get_analysis_framework(analysis_type)
                    self._json({"ok": True, "ts_code": ts_code, "analysis_type": framework.key, "items": list_analysis_results(ts_code, framework.key)})
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_sync_stock_data(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    years, full_history = self._parse_history_scope(payload)
                    tushare_client = self._tushare_for_session()
                    force = bool(payload.get("force"))
                    max_age = app.settings.stock_data_cache_ttl_seconds
                    status = stock_status(ts_code)
                    age = status.get("age_seconds")
                    cache_fresh = (
                        not force
                        and status.get("exists")
                        and isinstance(age, int)
                        and age <= max_age
                    )
                    if not cache_fresh and not self._consume_billable_budget("/api/sync-stock-data"):
                        return
                    result = sync_stock_data(
                        tushare_client,
                        ts_code,
                        years=years,
                        full_history=full_history,
                        force=force,
                        max_age_seconds=max_age,
                    )
                    if not result.get("cache_hit"):
                        self._record_billable_usage("/api/sync-stock-data")
                    self._json(result)
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_stock_status(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    self._json(stock_status(ts_code))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_local_stock_data(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    self._json(build_local_stock_payload(ts_code))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def _parse_history_scope(self, payload: dict) -> tuple[int | None, bool]:
                return app._parse_history_scope_value(payload.get("years"))

            def _require_auth(self, path: str) -> bool:
                session = self._current_session()
                if session:
                    return True
                if path.startswith("/api/"):
                    self._json({"ok": False, "error": "请先登录"}, status=401)
                else:
                    self._redirect("/login")
                return False

            def _require_admin(self) -> bool:
                session = self._current_session()
                if not session:
                    self._json({"ok": False, "error": "请先登录"}, status=401)
                    return False
                if session.get("role") != "admin":
                    self._json({"ok": False, "error": "需要管理员权限"}, status=403)
                    return False
                return True

            def _is_authenticated(self) -> bool:
                return bool(self._current_session())

            def _current_session(self) -> dict | None:
                token = self._session_token()
                if not token:
                    return None
                return app._session_for_token(token)

            def _access_state(self, session: dict | None, access_override: dict | None = None, api_key_state: dict | None = None) -> dict:
                if not session:
                    return {"tier": "", "is_vip": False, "vip_until_text": "", "api_keys": {}}
                role = session.get("role", "")
                if role in {"admin", "demo"}:
                    return {"tier": role, "is_vip": True, "vip_until_text": "", "api_keys": {}}
                access = access_override or app.user_store.user_access_state(session.get("username") or "")
                return {
                    "tier": access.get("tier", "user"),
                    "is_vip": bool(access.get("is_vip")),
                    "vip_until_text": access.get("vip_until_text", ""),
                    "api_keys": api_key_state if api_key_state is not None else app.user_store.user_api_key_state(session.get("username") or ""),
                }

            def _credential_mode(self, session: dict | None) -> str:
                if not session:
                    return "anonymous"
                if session.get("role") in {"admin", "demo"}:
                    return "system"
                access = app.user_store.user_access_state(session.get("username") or "")
                return "system" if access.get("is_vip") else "user"

            def _tushare_for_session(self) -> TushareClient:
                session = self._current_session()
                mode = self._credential_mode(session)
                if mode == "system":
                    return app.tushare
                keys = app.user_store.decrypted_user_api_keys(session.get("username") if session else "")
                token = keys.get("tushare")
                if not token:
                    raise PermissionError("普通用户需要先保存自己的 Tushare API key，或兑换 VIP。")
                return TushareClient(token, app.settings.tushare_base_url)

            def _deepseek_for_session(self) -> DeepSeekClient | None:
                session = self._current_session()
                mode = self._credential_mode(session)
                if mode == "system":
                    if not app.settings.deepseek_api_key:
                        return None
                    return DeepSeekClient(app.settings.deepseek_api_key, app.settings.deepseek_base_url, model=app.settings.deepseek_model)
                keys = app.user_store.decrypted_user_api_keys(session.get("username") if session else "")
                token = keys.get("deepseek")
                if not token:
                    raise PermissionError("普通用户需要先保存自己的 DeepSeek API key，或兑换 VIP。")
                return DeepSeekClient(token, app.settings.deepseek_base_url, model=app.settings.deepseek_model)

            def _authenticate(self, username: str, password: str) -> dict | None:
                if secrets.compare_digest(username, app.settings.web_username) and secrets.compare_digest(password, app.settings.web_password):
                    return {"username": app.settings.web_username, "role": "admin"}
                if app.user_store.verify_demo_account(username, password):
                    return {"username": username, "role": "demo", "managed_demo": True}
                if app.user_store.verify_user(username, password):
                    return {"username": username, "role": "user"}
                return None

            def _login_account(self, account: dict) -> None:
                token = secrets.token_urlsafe(32)
                app._replace_user_session(token, account)
                session = app._session_for_token(token) or account
                self._json(
                    {
                        "ok": True,
                        "user": account["username"],
                        "role": account["role"],
                        "demo_remaining": self._demo_remaining(session) if account["role"] == "demo" else None,
                    },
                    headers={"Set-Cookie": self._session_cookie(self._signed_token(token))},
                )

            def _reserved_username(self, username: str) -> bool:
                reserved = {app.settings.web_username}
                return username in reserved

            def _valid_username(self, username: str) -> bool:
                if not 3 <= len(username) <= 32:
                    return False
                return all(char.isalnum() or char in {"_", "-"} for char in username)

            def _check_demo_budget(self, path: str, session: dict) -> bool:
                if session.get("role") != "demo" or path not in BILLABLE_API_PATHS:
                    return True
                allowed, _state = app.user_store.consume_demo_budget(session.get("username") or "")
                if not allowed:
                    self._json({"ok": False, "error": "测试账号请求次数已用完，请稍后再试。"}, status=429)
                return allowed

            def _demo_remaining(self, session: dict | None = None) -> int:
                if session and session.get("managed_demo"):
                    state = app.user_store.demo_account_state(session.get("username") or "")
                    return int(state.get("remaining") or 0)
                return 0

            def _demo_state(self) -> dict:
                return {
                    "username": "",
                    "limit": app.settings.web_demo_request_limit,
                    "window_seconds": max(60, app.settings.web_demo_window_seconds),
                    "remaining": app.settings.web_demo_request_limit,
                    "resets_in_seconds": max(60, app.settings.web_demo_window_seconds),
                }

            def _record_usage(self, path: str, session: dict) -> None:
                if path not in BILLABLE_API_PATHS:
                    return
                app.user_store.record_usage(session.get("username") or "", session.get("role") or "", path)

            def _consume_billable_budget(self, path: str) -> bool:
                session = self._current_session()
                if not session:
                    self._json({"ok": False, "error": "请先登录"}, status=401)
                    return False
                return self._check_demo_budget(path, session)

            def _record_billable_usage(self, path: str) -> None:
                session = self._current_session()
                if session:
                    self._record_usage(path, session)

            def _session_token(self) -> str:
                header = self.headers.get("Cookie", "")
                if not header:
                    return ""
                cookie = SimpleCookie()
                cookie.load(header)
                morsel = cookie.get("stock_session")
                if not morsel:
                    return ""
                return self._verify_signed_token(morsel.value)

            def _session_cookie(self, token: str) -> str:
                return f"stock_session={token}; Path=/; Max-Age={app.session_ttl_seconds}; HttpOnly; SameSite=Lax"

            def _signed_token(self, token: str) -> str:
                signature = hmac.new(app.auth_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
                return f"{token}.{signature}"

            def _verify_signed_token(self, value: str) -> str:
                token, sep, signature = value.partition(".")
                if not sep or not token or not signature:
                    return ""
                expected = hmac.new(app.auth_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
                return token if hmac.compare_digest(signature, expected) else ""

            def _redirect(self, location: str) -> None:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", location)
                self.end_headers()

            def _json(self, payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"前端已启动：http://{self.host}:{self.port}")
        print("按 Ctrl+C 停止服务。")
        server.serve_forever()


def serve_web(host: str = "127.0.0.1", port: int = 8765) -> None:
    StockWebApp(host=host, port=port).serve()


class SpiderController:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.spider_dir = project_root / "spider"
        self.logs_dir = project_root / "logs"
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.current: dict | None = None

    def start(self, payload: dict) -> dict:
        with self.lock:
            self._refresh_locked()
            if self.process and self.process.poll() is None:
                raise RuntimeError("已有爬虫任务正在运行。")

            selected_types = self._parse_types(payload.get("types"))
            max_pages = self._bounded_int(payload.get("max_pages"), default=1, minimum=1, maximum=50, field="max_pages")
            threads = self._bounded_int(payload.get("threads"), default=1, minimum=1, maximum=4, field="threads")
            dry_run = payload.get("dry_run", True) is not False
            new_only = bool(payload.get("new_only", False))
            article_sleep = self._sleep_range(payload.get("article_sleep"), default="0,0" if dry_run else "3,8", field="article_sleep")
            page_sleep = self._sleep_range(payload.get("page_sleep"), default="0,0" if dry_run else "10,30", field="page_sleep")

            job_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            log_file = self.logs_dir / f"admin-spider-{job_id}.log"
            ensure_dir(log_file.parent)
            cmd = [
                sys.executable,
                "main.py",
                "--types",
                ",".join(selected_types),
                "--max-pages",
                str(max_pages),
                "--threads",
                str(threads),
                "--article-sleep",
                article_sleep,
                "--page-sleep",
                page_sleep,
                "--max-page-failures",
                "2",
                "--log-file",
                str(log_file),
            ]
            if dry_run:
                cmd.append("--dry-run")
            if new_only:
                cmd.extend(["--new-only", "--existing-stop-count", "10"])

            with log_file.open("a", encoding="utf-8") as output:
                output.write("admin spider command: " + " ".join(cmd) + "\n")
            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.spider_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            self.current = {
                "job_id": job_id,
                "status": "running",
                "pid": self.process.pid,
                "started_at": timestamp(),
                "finished_at": "",
                "returncode": None,
                "types": selected_types,
                "max_pages": max_pages,
                "threads": threads,
                "dry_run": dry_run,
                "new_only": new_only,
                "log_file": str(log_file),
            }
            return self.status_locked()

    def stop(self) -> dict:
        with self.lock:
            self._refresh_locked()
            if not self.process or self.process.poll() is not None:
                return self.status_locked()
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.current = dict(self.current or {})
            self.current["status"] = "stopping"
            return self.status_locked()

    def status(self) -> dict:
        with self.lock:
            self._refresh_locked()
            return self.status_locked()

    def logs(self, lines: int = 120) -> dict:
        with self.lock:
            self._refresh_locked()
            current = self.current or {}
            log_file = current.get("log_file") or ""
        if not log_file or not Path(log_file).exists():
            return {"log_file": log_file, "content": ""}
        return {"log_file": log_file, "content": "\n".join(Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])}

    def status_locked(self) -> dict:
        return {"spider": self.current or {"status": "idle", "pid": None, "log_file": ""}, "available_types": list(SPIDER_TYPES)}

    def _refresh_locked(self) -> None:
        if not self.process or not self.current:
            return
        returncode = self.process.poll()
        if returncode is None:
            return
        self.current["returncode"] = returncode
        self.current["finished_at"] = self.current.get("finished_at") or timestamp()
        if self.current.get("status") == "stopping":
            self.current["status"] = "stopped"
        else:
            self.current["status"] = "succeeded" if returncode == 0 else "failed"
        self.process = None

    def _parse_types(self, raw_value) -> list[str]:
        if isinstance(raw_value, list):
            candidates = [str(item).strip() for item in raw_value]
        else:
            candidates = [part.strip() for part in str(raw_value or "财经要闻").split(",")]
        selected = [item for item in candidates if item]
        if not selected:
            raise ValueError("至少选择一个爬虫分类。")
        unknown = [item for item in selected if item not in SPIDER_TYPES]
        if unknown:
            raise ValueError("未知爬虫分类：" + ",".join(unknown))
        return selected

    def _bounded_int(self, value, default: int, minimum: int, maximum: int, field: str) -> int:
        try:
            parsed = int(value if value not in (None, "") else default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是数字。") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{field} 必须在 {minimum}-{maximum} 之间。")
        return parsed

    def _sleep_range(self, value, default: str, field: str) -> str:
        raw = str(value or default).strip()
        parts = raw.split(",")
        if len(parts) != 2:
            raise ValueError(f"{field} 格式必须是 min,max。")
        try:
            left, right = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise ValueError(f"{field} 必须是数字范围。") from exc
        if left < 0 or right < left or right > 300:
            raise ValueError(f"{field} 范围不合法。")
        return f"{left:g},{right:g}"


class ApiKeyCipher:
    def __init__(self, secret: str):
        if not secret:
            raise RuntimeError("缺少 API key 加密密钥，请设置 STOCK_WEB_KEY_ENCRYPTION_SECRET。")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self.fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("用户 API key 解密失败，请检查加密密钥是否变更。") from exc


class UserStore:
    def __init__(self, path: Path, key_cipher: ApiKeyCipher):
        self.path = path
        self.key_cipher = key_cipher
        self.lock = threading.Lock()
        ensure_dir(path.parent)

    def create_user(self, username: str, password: str, invite_code: str) -> tuple[bool, str]:
        with self.lock:
            data = self._read()
            users = data.setdefault("users", {})
            used_invites = data.setdefault("used_invites", {})
            invites = data.setdefault("invites", {})
            if invite_code in used_invites:
                return False, "invite_used"
            invite = invites.get(invite_code)
            if not invite:
                return False, "invite_missing"
            if invite.get("used_at"):
                return False, "invite_used"
            if invite.get("expires_at", 0) < time.time():
                return False, "invite_expired"
            if username in users:
                return False, "user_exists"
            users[username] = {
                "password": self._hash_password(password),
                "created_at": timestamp(),
                "invite_code": invite_code,
                "tier": "user",
                "vip_until": 0,
            }
            used_invites[invite_code] = {
                "username": username,
                "used_at": timestamp(),
            }
            invite["used_by"] = username
            invite["used_at"] = timestamp()
            self._write(data)
            return True, ""

    def seed_invites(self, invite_codes: set[str], ttl_seconds: int, created_by: str) -> None:
        if not invite_codes:
            return
        now = time.time()
        with self.lock:
            data = self._read()
            invites = data.setdefault("invites", {})
            changed = False
            for code in invite_codes:
                if code in invites:
                    continue
                invites[code] = {
                    "code": code,
                    "created_by": created_by,
                    "created_at": timestamp(),
                    "expires_at": now + ttl_seconds,
                    "used_by": "",
                    "used_at": "",
                }
                changed = True
            if changed:
                self._write(data)

    def create_invite(self, created_by: str, ttl_seconds: int) -> dict:
        now = time.time()
        with self.lock:
            data = self._read()
            invites = data.setdefault("invites", {})
            code = self._new_numeric_invite_code(invites)
            invite = {
                "code": code,
                "created_by": created_by,
                "created_at": timestamp(),
                "expires_at": now + ttl_seconds,
                "used_by": "",
                "used_at": "",
            }
            invites[code] = invite
            self._write(data)
        return self._public_invite(invite)

    def create_vip_code(self, created_by: str, days: int, ttl_seconds: int) -> dict:
        now = time.time()
        days = max(1, min(3650, int(days or 1)))
        with self.lock:
            data = self._read()
            vip_codes = data.setdefault("vip_codes", {})
            code = self._new_numeric_invite_code(vip_codes)
            item = {
                "code": code,
                "created_by": created_by,
                "created_at": timestamp(),
                "expires_at": now + ttl_seconds,
                "vip_days": days,
                "used_by": "",
                "used_at": "",
            }
            vip_codes[code] = item
            self._write(data)
        return self._public_vip_code(item)

    def redeem_vip_code(self, username: str, code: str) -> tuple[bool, str, dict]:
        now = time.time()
        with self.lock:
            data = self._read()
            users = data.setdefault("users", {})
            user = users.get(username)
            if not user:
                return False, "user_missing", {}
            item = data.setdefault("vip_codes", {}).get(code)
            if not item:
                return False, "missing", {}
            if item.get("used_at"):
                return False, "used", {}
            if item.get("expires_at", 0) < now:
                return False, "expired", {}
            base = max(now, float(user.get("vip_until") or 0))
            user["vip_until"] = base + int(item.get("vip_days") or 1) * 86400
            user["tier"] = "vip"
            item["used_by"] = username
            item["used_at"] = timestamp()
            self._write(data)
            return True, "", self.user_access_state(username, data=data)

    def _new_numeric_invite_code(self, invites: dict) -> str:
        for _ in range(100):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in invites:
                return code
        raise RuntimeError("无法生成唯一邀请码，请稍后重试。")

    def invite_status(self, invite_code: str) -> str:
        with self.lock:
            invite = self._read().get("invites", {}).get(invite_code)
        if not invite:
            return "missing"
        if invite.get("used_at"):
            return "used"
        if invite.get("expires_at", 0) < time.time():
            return "expired"
        return "active"

    def verify_user(self, username: str, password: str) -> bool:
        with self.lock:
            user = self._read().get("users", {}).get(username)
        if not user:
            return False
        return self._verify_password(password, user.get("password", ""))

    def user_access_state(self, username: str, data: dict | None = None) -> dict:
        data = data or self._read()
        if username == "":
            return {"tier": "", "is_vip": False, "vip_until": 0, "vip_until_text": ""}
        user = data.get("users", {}).get(username)
        if not user:
            return {"tier": "admin" if username else "", "is_vip": True, "vip_until": 0, "vip_until_text": ""}
        vip_until = float(user.get("vip_until") or 0)
        is_vip = vip_until > time.time()
        return {
            "tier": "vip" if is_vip else "user",
            "is_vip": is_vip,
            "vip_until": vip_until,
            "vip_until_text": self._format_expiry(vip_until) if is_vip else "",
        }

    def user_api_key_state(self, username: str, data: dict | None = None) -> dict:
        if data is None:
            with self.lock:
                user = self._read().get("users", {}).get(username, {})
        else:
            user = data.get("users", {}).get(username, {})
        keys = user.get("api_keys") or {}
        return {
            name: {
                "configured": bool(keys.get(name, {}).get("ciphertext")),
                "updated_at": keys.get(name, {}).get("updated_at", ""),
            }
            for name in sorted(USER_KEY_NAMES)
        }

    def save_user_api_keys(self, username: str, values: dict[str, str]) -> dict:
        cleaned = {name: str(value or "").strip() for name, value in values.items() if name in USER_KEY_NAMES}
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise PermissionError("只有普通注册用户可以保存自己的 API key。")
            keys = user.setdefault("api_keys", {})
            for name, value in cleaned.items():
                if not value:
                    continue
                keys[name] = {"ciphertext": self.key_cipher.encrypt(value), "updated_at": timestamp()}
            self._write(data)
        return self.user_api_key_state(username)

    def delete_user_api_keys(self, username: str, names: list[str] | None = None) -> dict:
        selected = set(names or USER_KEY_NAMES) & USER_KEY_NAMES
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                return {}
            keys = user.get("api_keys") or {}
            for name in selected:
                keys.pop(name, None)
            if keys:
                user["api_keys"] = keys
            else:
                user.pop("api_keys", None)
            self._write(data)
        return self.user_api_key_state(username)

    def decrypted_user_api_keys(self, username: str) -> dict[str, str]:
        with self.lock:
            user = self._read().get("users", {}).get(username, {})
            keys = user.get("api_keys") or {}
        result = {}
        for name in USER_KEY_NAMES:
            ciphertext = keys.get(name, {}).get("ciphertext")
            if ciphertext:
                result[name] = self.key_cipher.decrypt(ciphertext)
        return result

    def create_demo_account(self, created_by: str, limit: int, window_seconds: int) -> dict:
        now = time.time()
        password = secrets.token_urlsafe(10)
        with self.lock:
            data = self._read()
            demo_accounts = data.setdefault("demo_accounts", {})
            username = self._new_demo_username(data)
            account = {
                "username": username,
                "password": self._hash_password(password),
                "created_by": created_by,
                "created_at": timestamp(),
                "limit": limit,
                "window_seconds": window_seconds,
                "window_start": now,
                "count": 0,
                "disabled": False,
            }
            demo_accounts[username] = account
            self._write(data)
        public = self._public_demo_account(account)
        public["password"] = password
        return public

    def verify_demo_account(self, username: str, password: str) -> bool:
        with self.lock:
            account = self._read().get("demo_accounts", {}).get(username)
        if not account or account.get("disabled"):
            return False
        return self._verify_password(password, account.get("password", ""))

    def consume_demo_budget(self, username: str) -> tuple[bool, dict]:
        now = time.time()
        with self.lock:
            data = self._read()
            account = data.get("demo_accounts", {}).get(username)
            if not account or account.get("disabled"):
                return False, {}
            window_seconds = max(60, int(account.get("window_seconds") or 86400))
            if now - float(account.get("window_start") or 0) >= window_seconds:
                account["window_start"] = now
                account["count"] = 0
            limit = max(1, int(account.get("limit") or 1))
            if int(account.get("count") or 0) >= limit:
                state = self._public_demo_account(account)
                return False, state
            account["count"] = int(account.get("count") or 0) + 1
            self._write(data)
            return True, self._public_demo_account(account)

    def demo_account_state(self, username: str) -> dict:
        with self.lock:
            account = self._read().get("demo_accounts", {}).get(username)
            if not account:
                return {}
            return self._public_demo_account(account)

    def record_usage(self, username: str, role: str, path: str) -> None:
        if not username:
            return
        with self.lock:
            data = self._read()
            usage = data.setdefault("usage", {})
            item = usage.setdefault(username, {"username": username, "role": role, "total": 0, "by_path": {}, "last_request_at": ""})
            item["role"] = role
            item["total"] = int(item.get("total") or 0) + 1
            item["last_request_at"] = timestamp()
            by_path = item.setdefault("by_path", {})
            by_path[path] = int(by_path.get(path) or 0) + 1
            self._write(data)

    def _billable_usage_view(self, user_usage: dict) -> dict:
        by_path = {
            path: int(count or 0)
            for path, count in (user_usage.get("by_path") or {}).items()
            if path in BILLABLE_API_PATHS
        }
        return {
            "total": sum(by_path.values()),
            "by_path": by_path,
            "last_request_at": user_usage.get("last_request_at", "") if by_path else "",
        }

    def admin_overview(self) -> dict:
        with self.lock:
            data = self._read()
        users = []
        usage = data.get("usage", {})
        for username, user in sorted(data.get("users", {}).items()):
            user_usage = usage.get(username, {})
            billable_usage = self._billable_usage_view(user_usage)
            access = self.user_access_state(username, data=data)
            users.append(
                {
                    "username": username,
                    "role": access["tier"],
                    "created_at": user.get("created_at", ""),
                    "invite_code": user.get("invite_code", ""),
                    "vip_until_text": access.get("vip_until_text", ""),
                    "api_keys": self.user_api_key_state(username, data=data),
                    "usage_total": billable_usage["total"],
                    "last_request_at": billable_usage["last_request_at"],
                    "by_path": billable_usage["by_path"],
                }
            )
        for username, user_usage in sorted(usage.items()):
            if any(item["username"] == username for item in users):
                continue
            billable_usage = self._billable_usage_view(user_usage)
            users.append(
                {
                    "username": username,
                    "role": user_usage.get("role", ""),
                    "created_at": "",
                    "invite_code": "",
                    "usage_total": billable_usage["total"],
                    "last_request_at": billable_usage["last_request_at"],
                    "by_path": billable_usage["by_path"],
                }
            )
        return {
            "users": users,
            "invites": [self._public_invite(invite) for invite in sorted(data.get("invites", {}).values(), key=lambda item: item.get("expires_at", 0), reverse=True)],
            "vip_codes": [self._public_vip_code(item) for item in sorted(data.get("vip_codes", {}).values(), key=lambda item: item.get("expires_at", 0), reverse=True)],
            "demo_accounts": [
                self._public_demo_account(account)
                for account in sorted(data.get("demo_accounts", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
            ],
        }

    def _read(self) -> dict:
        if not self.path.exists():
            return {"users": {}, "used_invites": {}, "invites": {}, "usage": {}, "demo_accounts": {}, "vip_codes": {}}
        data = read_json(self.path)
        data.setdefault("users", {})
        data.setdefault("used_invites", {})
        data.setdefault("invites", {})
        data.setdefault("usage", {})
        data.setdefault("demo_accounts", {})
        data.setdefault("vip_codes", {})
        return data

    def _write(self, data: dict) -> None:
        write_json(self.path, data)

    def _hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        iterations = 200_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"

    def _new_demo_username(self, data: dict) -> str:
        users = set(data.get("users", {}))
        demo_accounts = set(data.get("demo_accounts", {}))
        for _ in range(100):
            username = f"demo{secrets.randbelow(1_000_000):06d}"
            if username not in users and username not in demo_accounts:
                return username
        raise RuntimeError("无法生成唯一测试账号，请稍后重试。")

    def _verify_password(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    def _public_invite(self, invite: dict) -> dict:
        status = "active"
        if invite.get("used_at"):
            status = "used"
        elif invite.get("expires_at", 0) < time.time():
            status = "expired"
        return {
            "code": invite.get("code", ""),
            "created_by": invite.get("created_by", ""),
            "created_at": invite.get("created_at", ""),
            "expires_at": invite.get("expires_at", 0),
            "expires_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(invite.get("expires_at", 0))) if invite.get("expires_at") else "",
            "used_by": invite.get("used_by", ""),
            "used_at": invite.get("used_at", ""),
            "status": status,
        }

    def _public_vip_code(self, item: dict) -> dict:
        status = "active"
        if item.get("used_at"):
            status = "used"
        elif item.get("expires_at", 0) < time.time():
            status = "expired"
        return {
            "code": item.get("code", ""),
            "created_by": item.get("created_by", ""),
            "created_at": item.get("created_at", ""),
            "expires_at": item.get("expires_at", 0),
            "expires_at_text": self._format_expiry(item.get("expires_at", 0)),
            "vip_days": int(item.get("vip_days") or 0),
            "used_by": item.get("used_by", ""),
            "used_at": item.get("used_at", ""),
            "status": status,
        }

    def _format_expiry(self, expires_at: float) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)) if expires_at else ""

    def _public_demo_account(self, account: dict) -> dict:
        now = time.time()
        window_seconds = max(60, int(account.get("window_seconds") or 86400))
        window_start = float(account.get("window_start") or now)
        count = int(account.get("count") or 0)
        if now - window_start >= window_seconds:
            count = 0
            resets_in = window_seconds
        else:
            resets_in = max(0, int(window_seconds - (now - window_start)))
        limit = max(1, int(account.get("limit") or 1))
        return {
            "username": account.get("username", ""),
            "created_by": account.get("created_by", ""),
            "created_at": account.get("created_at", ""),
            "limit": limit,
            "window_seconds": window_seconds,
            "used": count,
            "remaining": max(0, limit - count),
            "resets_in_seconds": resets_in,
            "disabled": bool(account.get("disabled")),
        }
