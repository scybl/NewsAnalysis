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
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.cookies import SimpleCookie
from cryptography.fernet import Fernet, InvalidToken

from .analyst import StockAnalyst, session_path_for
from .agents import LangGraphMultiAgentRunner, MultiAgentRunner, list_agent_runs, read_agent_run
from .agents.multi_agent import MultiAgentOptions
from .analysis_frameworks import get_analysis_framework, list_analysis_frameworks
from .collector import StockDataCollector
from .config import PROJECT_ROOT, get_settings
from .deepseek_client import DeepSeekClient, DeepSeekError
from .dossier import build_dossier
from .field_labels import build_table_datasets
from .news_library import query_news_library
from .news_search import search_related_news
from .stock_search import StockSearchIndex
from .stock_storage import (
    analysis_dossier_path,
    analysis_output_path,
    analysis_review_context,
    build_local_stock_payload,
    current_dir,
    list_analysis_results,
    list_local_stock_codes,
    read_analysis_result,
    stock_exists,
    stock_status,
    sync_daily_market_for_existing_stocks,
    sync_stock_data,
)
from .ths_minute import build_config as build_ths_minute_config
from .ths_minute import fetch_and_store_minutes
from .tushare_client import TushareClient, TushareError
from .utils import CN_TZ, ensure_dir, normalize_ts_code, read_json, timestamp, today_yyyymmdd, write_json


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
SPIDER_TYPES = ("财经要闻", "宏观经济", "产经新闻", "国际财经", "金融市场", "公司新闻", "区域经济", "财经评论", "财经人物")
SPIDER_SOURCES = (
    {"id": "ths", "name": "同花顺", "description": "中文财经新闻分类抓取"},
    {"id": "ths_market", "name": "分钟行情", "description": "指定股票分钟行情补抓，默认通达信历史分钟 K，写入 MongoDB 和本地资料包"},
    {"id": "guardian", "name": "Guardian", "description": "Guardian Content API 文章抓取"},
    {"id": "bloomberg_urls", "name": "Bloomberg URL", "description": "抓取 Bloomberg URL 队列", "disabled": True, "disabled_reason": "暂时关闭，等待后续稳定性优化"},
    {"id": "bloomberg_articles", "name": "Bloomberg 正文", "description": "读取 URL 队列并抓正文，需要 Chrome 登录态", "disabled": True, "disabled_reason": "暂时关闭，等待后续稳定性优化"},
)
BILLABLE_API_PATHS = {
    "/api/refresh",
    "/api/sync-stock-data",
    "/api/analyze",
    "/api/multi-agent-analyze",
}
USER_KEY_NAMES = {"tushare", "deepseek"}
SYSTEM_KEY_NAMES = {"deepseek"}


class StockWebApp:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.settings = get_settings(require_deepseek=False)
        self.tushare = TushareClient(
            self.settings.tushare_token,
            self.settings.tushare_base_url,
            pause=self.settings.tushare_pause_seconds,
        )
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
        self.task_registry = TaskRegistry()
        self.daily_market_scheduler = DailyMarketScheduler(self, PROJECT_ROOT / "local_data" / "daily_market_scheduler.json", self.task_registry)
        self.spider_controller = SpiderController(PROJECT_ROOT, self.task_registry)
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
        runner_cls = LangGraphMultiAgentRunner if self.settings.stock_agent_engine == "langgraph" else MultiAgentRunner
        return runner_cls(tushare_client, llm_client=llm_client, progress_callback=progress_callback).run(
            ts_code,
            MultiAgentOptions(
                analysis_type=analysis_type,
                allow_dynamic_fetch=allow_dynamic_fetch,
                use_llm_agents=bool(llm_client),
                years=years,
                full_history=full_history,
                max_parallel_agents=max_parallel_agents,
                template=self.settings.stock_agent_template,
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
        self.task_registry.create_task(
            job_id,
            "multi_agent",
            f"多 Agent 分析 {payload.get('ts_code') or payload.get('code') or ''}",
            metadata={"analysis_type": payload.get("analysis_type") or "value_speculation"},
        )
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
        if status:
            self.task_registry.update_task(job_id, status=status, error=error, result=result)
        if event:
            self.task_registry.add_event(job_id, event.get("stage") or "progress", event.get("message") or "", event.get("details") or {})

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
        self.task_registry.create_task(job_id, "multi_agent_cache", "复用共享多 Agent 分析", metadata={"cache_hit": True})
        self.task_registry.update_task(job_id, status="succeeded", result=result)
        self.task_registry.add_event(job_id, "cache", message, {"cache_hit": True})
        return {"ok": True, "job_id": job_id, "status": "succeeded", "progress": job["progress"]}

    def health_snapshot(self) -> dict:
        spider = self.spider_controller.status().get("spider", {})
        return {
            "ok": True,
            "status": "ok",
            "time": timestamp(),
            "web": {"host": self.host, "port": self.port},
            "config": {
                "tushare_configured": bool(self.settings.tushare_token),
                "deepseek_configured": self.user_store.system_api_key_state().get("deepseek", {}).get("configured", False),
                "stock_agent_engine": self.settings.stock_agent_engine,
                "stock_agent_template": self.settings.stock_agent_template,
                "stock_analysis_refresh_ttl_seconds": self.settings.stock_analysis_refresh_ttl_seconds,
            },
            "storage": {
                "local_data_exists": (PROJECT_ROOT / "local_data").exists(),
                "web_user_store_exists": self.user_store.path.exists(),
            },
            "spider": {"status": spider.get("status", "idle"), "pid": spider.get("pid")},
            "tasks": {"count": len(self.task_registry.list_tasks(500))},
        }

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
            if self._agent_result_has_runtime_error(payload):
                continue
            payload["cached_analysis"] = True
            payload["cache_age_seconds"] = age
            return payload
        return None

    def _same_data_agent_result(self, ts_code: str, analysis_type: str) -> dict | None:
        current_fingerprint = self._current_data_fingerprint(ts_code)
        if not current_fingerprint:
            return None
        for item in list_agent_runs(ts_code, analysis_type):
            run_dir = Path(item.get("run_dir") or "")
            manifest_path = run_dir / "run_manifest.json"
            if not manifest_path.exists():
                continue
            manifest = read_json(manifest_path)
            if manifest.get("data_fingerprint") != current_fingerprint:
                continue
            payload = read_agent_run(ts_code, item.get("run_id") or "")
            if self._agent_result_has_runtime_error(payload):
                continue
            payload["cached_analysis"] = True
            payload["cache_reason"] = "same_data_fingerprint"
            payload["cache_age_seconds"] = int(time.time() - run_dir.stat().st_mtime)
            return payload
        return None

    def _agent_result_has_runtime_error(self, payload: dict) -> bool:
        if payload.get("error"):
            return True
        for item in payload.get("agent_results") or []:
            if isinstance(item, dict) and (item.get("llm_error") or item.get("schema_error")):
                return True
        review = payload.get("critic_review") or {}
        return bool(isinstance(review, dict) and review.get("llm_error"))

    def _current_data_fingerprint(self, ts_code: str) -> str:
        path = current_dir(ts_code) / "full_data.json"
        if not path.exists():
            return ""
        full_data = read_json(path)
        datasets = full_data.get("datasets", {})
        payload = {
            "ts_code": full_data.get("ts_code"),
            "date_range": full_data.get("date_range", {}),
            "dataset_rows": {name: len(rows) for name, rows in sorted(datasets.items())},
            "latest_rows": {name: rows[:3] for name, rows in sorted(datasets.items()) if isinstance(rows, list) and rows},
            "fetch_errors": full_data.get("fetch_errors", []),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _stock_news_context(self, ts_code: str) -> dict:
        if not stock_exists(ts_code):
            raise FileNotFoundError(f"本地还没有 {ts_code} 的数据，请先更新本地数据。")
        base_dir = current_dir(ts_code)
        full_data = read_json(base_dir / "full_data.json")
        dossier = read_json(base_dir / "dossier.json") if (base_dir / "dossier.json").exists() else {}
        company = self._company_identity(dossier, full_data)
        return {"ts_code": ts_code, **search_related_news(company, limit=20, days=60)}

    def _company_identity(self, dossier: dict, full_data: dict) -> dict:
        company = dossier.get("company", {})
        stock_basic = company.get("stock_basic") or {}
        stock_company = company.get("stock_company") or {}
        industry_rows = dossier.get("industry", {}).get("sw_classification") or full_data.get("datasets", {}).get("index_member_all", [])
        industry = ""
        if industry_rows and isinstance(industry_rows, list):
            first = industry_rows[0]
            industry = str(first.get("industry_name") or first.get("index_name") or first.get("l2_name") or first.get("l1_name") or "")
        ts_code = stock_basic.get("ts_code") or full_data.get("ts_code")
        return {
            "ts_code": ts_code,
            "symbol": stock_basic.get("symbol") or str(ts_code or "").split(".")[0],
            "name": stock_basic.get("name") or stock_company.get("name") or stock_company.get("com_name"),
            "industry": stock_basic.get("industry") or industry,
            "area": stock_basic.get("area") or stock_company.get("province"),
        }

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

    def _remove_sessions_for_user(self, username: str) -> None:
        with self.session_lock:
            for token, session in list(self.sessions.items()):
                if session.get("username") == username:
                    self._remove_session_locked(token, session)

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
                if parsed.path == "/api/health":
                    self._json(app.health_snapshot())
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
                if parsed.path == "/api/stock-news":
                    query = parse_qs(parsed.query)
                    try:
                        ts_code = normalize_ts_code(query.get("ts_code", query.get("code", [""]))[0])
                        self._json({"ok": True, **app._stock_news_context(ts_code)})
                    except Exception as exc:  # noqa: BLE001 - readable UI error
                        self._json({"ok": False, "error": str(exc)}, status=404)
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
                if parsed.path == "/api/admin/daily-market-scheduler":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.daily_market_scheduler.status()})
                    return
                if parsed.path == "/api/admin/spider/logs":
                    if not self._require_admin():
                        return
                    query = parse_qs(parsed.query)
                    lines = max(20, min(500, int(query.get("lines", ["120"])[0] or 120)))
                    self._json({"ok": True, **app.spider_controller.logs(lines=lines, source=query.get("source", [""])[0])})
                    return
                if parsed.path == "/api/admin/tasks":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, "items": app.task_registry.list_tasks()})
                    return
                if parsed.path == "/api/admin/news-library":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **query_news_library(parse_qs(parsed.query))})
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
                if parsed.path == "/api/admin/system-api-key":
                    if not self._require_admin():
                        return
                    self._handle_admin_system_api_key()
                    return
                if parsed.path == "/api/admin/user-access":
                    if not self._require_admin():
                        return
                    self._handle_admin_user_access()
                    return
                if parsed.path == "/api/admin/demo-reset":
                    if not self._require_admin():
                        return
                    self._handle_admin_demo_reset()
                    return
                if parsed.path == "/api/admin/spider/start":
                    if not self._require_admin():
                        return
                    self._handle_admin_spider_start()
                    return
                if parsed.path == "/api/admin/spider/stop":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.spider_controller.stop(self._read_json())})
                    return
                if parsed.path == "/api/admin/daily-market-scheduler":
                    if not self._require_admin():
                        return
                    self._handle_admin_daily_market_scheduler()
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
                if parsed.path == "/api/sync-ths-market-data":
                    self._handle_sync_ths_market_data()
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
                    deepseek_client = self._deepseek_for_session(require=True)
                    self._ensure_deepseek_ready(deepseek_client)
                    cached = app._recent_agent_result(ts_code, analysis_type)
                    if cached:
                        if payload.get("async"):
                            self._json(app._completed_multi_agent_job(cached, "检测到近期共享多 Agent 分析，已复用结果。"))
                        else:
                            self._json(cached)
                        return
                    if not self._consume_billable_budget("/api/multi-agent-analyze"):
                        return
                    tushare_client = self._tushare_for_session()
                    years, full_history = self._parse_history_scope(payload)
                    refresh_ttl = max(0, int(app.settings.stock_analysis_refresh_ttl_seconds or 0))
                    if stock_exists(ts_code) and refresh_ttl > 0:
                        before_fingerprint = app._current_data_fingerprint(ts_code)
                        status = stock_status(ts_code)
                        age = status.get("age_seconds")
                        if isinstance(age, int) and age > refresh_ttl:
                            sync_stock_data(tushare_client, ts_code, years=years, full_history=full_history, max_age_seconds=refresh_ttl)
                        after_fingerprint = app._current_data_fingerprint(ts_code)
                        if before_fingerprint and after_fingerprint and before_fingerprint == after_fingerprint:
                            same_data_cached = app._same_data_agent_result(ts_code, analysis_type)
                            if same_data_cached:
                                message = "数据刷新检查后未发现资料包变化，已复用同数据版本的历史多 Agent 分析。"
                                self._record_billable_usage("/api/multi-agent-analyze")
                                if payload.get("async"):
                                    self._json(app._completed_multi_agent_job(same_data_cached, message))
                                else:
                                    self._json(same_data_cached)
                                return
                    payload["_tushare_client"] = tushare_client
                    payload["_deepseek_client"] = deepseek_client
                    if payload.get("async"):
                        result = app._start_multi_agent_job(payload)
                    else:
                        result = app._build_multi_agent_result(payload)
                    self._record_billable_usage("/api/multi-agent-analyze")
                    self._json(result)
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except DeepSeekError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=502)
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

            def _handle_admin_system_api_key(self) -> None:
                payload = self._read_json()
                action = str(payload.get("action") or "save").strip()
                session = self._current_session() or {}
                try:
                    if action == "delete":
                        state = app.user_store.delete_system_api_keys(["deepseek"], session.get("username") or "admin")
                        self._json({"ok": True, "system_api_keys": state})
                        return
                    token = str(payload.get("deepseek_api") or payload.get("deepseek") or "").strip()
                    validation = self._validate_deepseek_key(token)
                    if validation["errors"]:
                        self._json({"ok": False, "error": "；".join(validation["errors"]), "validation": validation}, status=400)
                        return
                    state = app.user_store.save_system_api_keys({"deepseek": token}, session.get("username") or "admin")
                    self._json({"ok": True, "validation": validation, "system_api_keys": state})
                except (ValueError, PermissionError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_user_access(self) -> None:
                payload = self._read_json()
                username = str(payload.get("username") or "").strip()
                action = str(payload.get("action") or "").strip()
                session = self._current_session() or {}
                try:
                    if action == "grant_vip":
                        days = max(1, min(3650, int(payload.get("days") or 30)))
                        access = app.user_store.admin_grant_vip(username, days, session.get("username") or "admin")
                        self._json({"ok": True, "access": access, **app.user_store.admin_overview()})
                        return
                    if action == "revoke_vip":
                        access = app.user_store.admin_revoke_vip(username, session.get("username") or "admin")
                        self._json({"ok": True, "access": access, **app.user_store.admin_overview()})
                        return
                    if action == "disable":
                        app.user_store.admin_set_disabled(username, True, session.get("username") or "admin")
                        app._remove_sessions_for_user(username)
                        self._json({"ok": True, **app.user_store.admin_overview()})
                        return
                    if action == "enable":
                        app.user_store.admin_set_disabled(username, False, session.get("username") or "admin")
                        self._json({"ok": True, **app.user_store.admin_overview()})
                        return
                    self._json({"ok": False, "error": "未知用户操作。"}, status=400)
                except (KeyError, ValueError, PermissionError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_demo_reset(self) -> None:
                payload = self._read_json()
                username = str(payload.get("username") or "").strip()
                session = self._current_session() or {}
                try:
                    state = app.user_store.admin_reset_demo_budget(username, session.get("username") or "admin")
                    self._json({"ok": True, "demo_account": state, **app.user_store.admin_overview()})
                except (KeyError, ValueError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

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
                keys_to_save = {"tushare": payload.get("tushare_api") or payload.get("tushare"), "deepseek": payload.get("deepseek_api") or payload.get("deepseek")}
                validation = self._validate_user_api_keys(keys_to_save)
                if validation["errors"]:
                    self._json({"ok": False, "error": "；".join(validation["errors"]), "validation": validation}, status=400)
                    return
                state = app.user_store.save_user_api_keys(
                    session.get("username") or "",
                    keys_to_save,
                )
                self._json({"ok": True, "validation": validation, **self._access_state(session, api_key_state=state)})

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

            def _handle_admin_daily_market_scheduler(self) -> None:
                payload = self._read_json()
                action = str(payload.get("action") or "save").strip()
                try:
                    if action == "run_now":
                        self._json({"ok": True, **app.daily_market_scheduler.run_now()})
                        return
                    if action == "save":
                        enabled = bool(payload.get("enabled"))
                        schedule_time = str(payload.get("time") or "21:30").strip()
                        self._json({"ok": True, **app.daily_market_scheduler.configure(enabled=enabled, schedule_time=schedule_time)})
                        return
                    self._json({"ok": False, "error": "未知每日行情调度操作。"}, status=400)
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_analyze(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    framework = get_analysis_framework(str(payload.get("analysis_type") or "value_speculation"))
                    years, full_history = self._parse_history_scope(payload)
                    question = str(payload.get("question") or framework.question)
                    deepseek_client = self._deepseek_for_session(require=True)
                    self._ensure_deepseek_ready(deepseek_client)
                    cached = app._recent_analysis_result(ts_code, framework.key)
                    if cached:
                        self._json(cached)
                        return
                    tushare_client = self._tushare_for_session()
                    if not self._consume_billable_budget("/api/analyze"):
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
                except DeepSeekError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=502)
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

            def _handle_sync_ths_market_data(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    result = fetch_and_store_minutes(
                        [ts_code],
                        config=build_ths_minute_config(
                            database=str(payload.get("mongo_db") or "").strip() or None,
                            collection=str(payload.get("collection") or "").strip() or None,
                        ),
                        sleep_range=(0, 0),
                        source=str(payload.get("source") or os.getenv("MARKET_MINUTE_DEFAULT_SOURCE", "pytdx_history")),
                        pages=payload.get("pages") or os.getenv("MARKET_MINUTE_DEFAULT_PAGES", "all"),
                        page_size=int(payload.get("page_size") or 800),
                    )
                    local_payload = build_local_stock_payload(ts_code) if stock_exists(ts_code) else {"datasets": [], "metadata": {}}
                    self._json({"ok": result.get("ok", False), "ts_code": ts_code, "market_result": result, **local_payload})
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
                return TushareClient(token, app.settings.tushare_base_url, pause=app.settings.tushare_pause_seconds)

            def _deepseek_for_session(self, require: bool = False) -> DeepSeekClient | None:
                session = self._current_session()
                mode = self._credential_mode(session)
                if mode == "system":
                    token = app.user_store.decrypted_system_api_keys().get("deepseek", "")
                    if not token:
                        if require:
                            raise PermissionError("系统 DeepSeek key 未配置或不可解密，请先在管理员后台验证并锁定。")
                        return None
                    return DeepSeekClient(token, app.settings.deepseek_base_url, model=app.settings.deepseek_model)
                keys = app.user_store.decrypted_user_api_keys(session.get("username") if session else "")
                token = keys.get("deepseek")
                if not token:
                    raise PermissionError("普通用户需要先保存自己的 DeepSeek API key，或兑换 VIP。")
                return DeepSeekClient(token, app.settings.deepseek_base_url, model=app.settings.deepseek_model)

            def _ensure_deepseek_ready(self, client: DeepSeekClient | None) -> None:
                if not client:
                    raise PermissionError("DeepSeek key 未配置，无法启动多 Agent 分析。")
                try:
                    client.chat([{"role": "user", "content": "请只回复 ok"}], max_tokens=8)
                except (DeepSeekError, RuntimeError, json.JSONDecodeError) as exc:
                    raise DeepSeekError(f"DeepSeek key 验证失败，已停止分析：{exc}") from exc

            def _validate_deepseek_key(self, token: str) -> dict:
                if not token:
                    return {"checks": {"deepseek": {"ok": False, "error": "DeepSeek key 不能为空。"}}, "errors": ["DeepSeek key 不能为空。"]}
                try:
                    DeepSeekClient(token, app.settings.deepseek_base_url, model=app.settings.deepseek_model, timeout=20).chat(
                        [{"role": "user", "content": "请只回复 ok"}],
                        max_tokens=8,
                    )
                    return {"checks": {"deepseek": {"ok": True}}, "errors": []}
                except (DeepSeekError, RuntimeError, json.JSONDecodeError) as exc:
                    return {"checks": {"deepseek": {"ok": False, "error": str(exc)}}, "errors": [f"DeepSeek key 验证失败：{exc}"]}

            def _validate_user_api_keys(self, values: dict[str, str]) -> dict:
                checks = {}
                errors = []
                tushare_token = str(values.get("tushare") or "").strip()
                deepseek_token = str(values.get("deepseek") or "").strip()
                if tushare_token:
                    try:
                        TushareClient(tushare_token, app.settings.tushare_base_url, timeout=12, pause=0).query("stock_basic", {"list_status": "L"}, "ts_code,name")
                        checks["tushare"] = {"ok": True}
                    except (TushareError, RuntimeError, json.JSONDecodeError) as exc:
                        checks["tushare"] = {"ok": False, "error": str(exc)}
                        errors.append(f"Tushare key 验证失败：{exc}")
                if deepseek_token:
                    validation = self._validate_deepseek_key(deepseek_token)
                    checks.update(validation["checks"])
                    errors.extend(validation["errors"])
                return {"checks": checks, "errors": errors}

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


class TaskRegistry:
    def __init__(self, max_items: int = 200):
        self.max_items = max_items
        self.lock = threading.Lock()
        self.tasks: dict[str, dict] = {}

    def create_task(self, task_id: str, kind: str, title: str, metadata: dict | None = None) -> dict:
        now = timestamp()
        now_epoch = time.time()
        task = {
            "task_id": task_id,
            "kind": kind,
            "title": title,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "created_epoch": now_epoch,
            "updated_epoch": now_epoch,
            "finished_at": "",
            "metadata": metadata or {},
            "events": [{"time": now, "stage": "queued", "message": "任务已创建。", "details": {}}],
            "error": "",
            "result_summary": {},
        }
        with self.lock:
            self.tasks[task_id] = task
            self._trim_locked()
            return json.loads(json.dumps(task, ensure_ascii=False, default=str))

    def update_task(self, task_id: str, status: str | None = None, error: str | None = None, result: dict | None = None, metadata: dict | None = None) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task["updated_at"] = timestamp()
            task["updated_epoch"] = time.time()
            if status:
                task["status"] = status
                if status in {"succeeded", "failed", "stopped"}:
                    task["finished_at"] = task.get("finished_at") or timestamp()
            if error is not None:
                task["error"] = error
            if metadata:
                task.setdefault("metadata", {}).update(metadata)
            if result:
                task["result_summary"] = self._summarize_result(result)

    def add_event(self, task_id: str, stage: str, message: str, details: dict | None = None) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task["updated_at"] = timestamp()
            task["updated_epoch"] = time.time()
            events = task.setdefault("events", [])
            events.append({"time": timestamp(), "stage": stage or "progress", "message": message or "", "details": details or {}})
            if len(events) > 80:
                task["events"] = events[-80:]

    def list_tasks(self, limit: int = 80) -> list[dict]:
        with self.lock:
            items = sorted(self.tasks.values(), key=lambda item: item.get("updated_epoch", 0), reverse=True)[:limit]
            return json.loads(json.dumps(items, ensure_ascii=False, default=str))

    def _trim_locked(self) -> None:
        if len(self.tasks) <= self.max_items:
            return
        ordered = sorted(self.tasks.values(), key=lambda item: item.get("updated_epoch", 0), reverse=True)
        keep = {item["task_id"] for item in ordered[: self.max_items]}
        for task_id in list(self.tasks):
            if task_id not in keep:
                self.tasks.pop(task_id, None)

    def _summarize_result(self, result: dict) -> dict:
        return {
            "ts_code": result.get("ts_code", ""),
            "analysis_type": result.get("analysis_type", ""),
            "rating_hint": result.get("rating_hint", ""),
            "confidence": result.get("confidence", ""),
            "run_id": result.get("run_id", ""),
            "target_date": result.get("target_date", ""),
            "updated": result.get("updated", ""),
            "skipped": result.get("skipped", ""),
            "no_data": result.get("no_data", ""),
            "failed": result.get("failed", ""),
        }


class DailyMarketScheduler:
    def __init__(self, app: StockWebApp, config_path: Path, task_registry: TaskRegistry):
        self.app = app
        self.config_path = config_path
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.config = self._load_config()
        self.thread = threading.Thread(target=self._loop, name="daily-market-scheduler", daemon=True)
        self.thread.start()

    def configure(self, enabled: bool, schedule_time: str) -> dict:
        schedule_time = self._validate_time(schedule_time)
        with self.lock:
            self.config["enabled"] = bool(enabled)
            self.config["time"] = schedule_time
            self.config["updated_at"] = timestamp()
            self._write_config_locked()
        return self.status()

    def run_now(self) -> dict:
        return self._start_run(trigger="manual")

    def status(self) -> dict:
        with self.lock:
            config = dict(self.config)
            running = bool(self.worker and self.worker.is_alive())
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "time": config.get("time") or "21:30",
                "last_run_date": config.get("last_run_date") or "",
                "last_run_at": config.get("last_run_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "running": running,
                "stock_count": len(list_local_stock_codes()),
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(30):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    schedule_time = str(self.config.get("time") or "21:30")
                    last_run_date = str(self.config.get("last_run_date") or "")
                    running = bool(self.worker and self.worker.is_alive())
                if not enabled or running:
                    continue
                now = datetime.now(CN_TZ).strftime("%H:%M")
                today = today_yyyymmdd()
                if now >= schedule_time and last_run_date != today:
                    self._start_run(trigger="scheduled")
            except Exception as exc:  # noqa: BLE001 - scheduler must keep ticking
                with self.lock:
                    self.config["last_error"] = str(exc)
                    self._write_config_locked()

    def _start_run(self, trigger: str) -> dict:
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise RuntimeError("每日行情更新任务正在运行。")
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            target_date = today_yyyymmdd()
            self.config["last_task_id"] = task_id
            self._write_config_locked()
        self.task_registry.create_task(
            task_id,
            "daily_market",
            "每日行情增量更新",
            metadata={"trigger": trigger, "target_date": target_date},
        )
        self.task_registry.update_task(task_id, status="running")
        self.task_registry.add_event(task_id, "running", "开始检查本地已有股票的当日行情。", {"target_date": target_date})
        self.worker = threading.Thread(target=self._run_task, args=(task_id, target_date, trigger), name=f"daily-market-{target_date}", daemon=True)
        self.worker.start()
        return self.status()

    def _run_task(self, task_id: str, target_date: str, trigger: str) -> None:
        try:
            client = TushareClient(
                self.app.settings.tushare_token,
                self.app.settings.tushare_base_url,
                pause=self.app.settings.tushare_pause_seconds,
            )
            result = sync_daily_market_for_existing_stocks(client, target_date=target_date)
            result["trigger"] = trigger
            self.task_registry.update_task(task_id, status="succeeded", result=result)
            self.task_registry.add_event(
                task_id,
                "succeeded",
                f"每日行情更新完成：更新 {result.get('updated')}，跳过 {result.get('skipped')}，无数据 {result.get('no_data')}，失败 {result.get('failed')}。",
                result,
            )
            with self.lock:
                self.config["last_run_date"] = target_date
                self.config["last_run_at"] = timestamp()
                self.config["last_result"] = result
                self.config["last_error"] = ""
                self._write_config_locked()
        except Exception as exc:  # noqa: BLE001 - report task failure
            self.task_registry.update_task(task_id, status="failed", error=str(exc))
            self.task_registry.add_event(task_id, "failed", "每日行情更新失败。", {"error": str(exc)})
            with self.lock:
                self.config["last_error"] = str(exc)
                self._write_config_locked()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                data["time"] = self._validate_time(str(data.get("time") or "21:30"))
                data["enabled"] = data.get("enabled", True) is not False
                return data
            except Exception:
                pass
        return {"enabled": True, "time": "21:30", "last_run_date": "", "last_run_at": "", "last_task_id": "", "last_result": {}}

    def _write_config_locked(self) -> None:
        write_json(self.config_path, self.config)

    def _validate_time(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("请设置每日更新时间。")
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("每日更新时间格式必须是 HH:MM。")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("每日更新时间必须是数字格式 HH:MM。") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("每日更新时间必须在 00:00-23:59 之间。")
        return f"{hour:02d}:{minute:02d}"


class SpiderController:
    def __init__(self, project_root: Path, task_registry: TaskRegistry | None = None):
        self.project_root = project_root
        self.spider_dir = project_root / "spider"
        self.logs_dir = project_root / "logs"
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.currents: dict[str, dict] = {}

    def start(self, payload: dict) -> dict:
        with self.lock:
            self._refresh_locked()

            source = self._parse_source(payload.get("source"))
            source_meta = self._source_meta(source)
            if source_meta.get("disabled"):
                raise ValueError(f"{source_meta.get('name', source)}暂时关闭：{source_meta.get('disabled_reason', '等待后续优化')}")
            process = self.processes.get(source)
            if process and process.poll() is None:
                raise RuntimeError(f"{self._source_label(source)}爬虫已经在运行。")
            selected_types = self._parse_types(payload.get("types")) if source == "ths" else []
            stock_code = normalize_ts_code(str(payload.get("stock_code") or payload.get("ts_code") or payload.get("code") or "")) if source == "ths_market" else ""
            max_pages = self._bounded_int(payload.get("max_pages"), default=1, minimum=1, maximum=50, field="max_pages")
            threads = self._bounded_int(payload.get("threads"), default=2, minimum=1, maximum=4, field="threads")
            new_only = bool(payload.get("new_only", False))
            article_sleep = self._sleep_range(payload.get("article_sleep"), default="3,5", field="article_sleep")
            page_sleep = self._sleep_range(payload.get("page_sleep"), default="5,10", field="page_sleep")

            job_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            log_file = self.logs_dir / f"admin-spider-{source}-{job_id}.log"
            ensure_dir(log_file.parent)
            env = dict(os.environ)
            env["SPIDER_NO_CONSOLE_LOG"] = "1"
            cmd, cwd, source_label = self._build_command(
                source=source,
                selected_types=selected_types,
                max_pages=max_pages,
                threads=threads,
                new_only=new_only,
                article_sleep=article_sleep,
                page_sleep=page_sleep,
                log_file=log_file,
                env=env,
                stock_code=stock_code,
            )

            with log_file.open("a", encoding="utf-8") as output:
                output.write("admin spider command: " + " ".join(cmd) + "\n")
                output.flush()
                process = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    start_new_session=True,
                )
            self.processes[source] = process
            self.currents[source] = {
                "job_id": job_id,
                "status": "running",
                "pid": process.pid,
                "started_at": timestamp(),
                "finished_at": "",
                "returncode": None,
                "source": source,
                "source_label": source_label,
                "types": selected_types,
                "max_pages": max_pages,
                "threads": threads,
                "new_only": new_only,
                "stock_code": stock_code,
                "log_file": str(log_file),
                "error": "",
            }
            if self.task_registry:
                self.task_registry.create_task(
                    job_id,
                    "spider",
                    f"{source_label}爬虫",
                    metadata={"source": source, "types": selected_types, "stock_code": stock_code, "max_pages": max_pages, "new_only": new_only},
                )
                self.task_registry.update_task(job_id, status="running")
                self.task_registry.add_event(job_id, "running", "爬虫进程已启动。", {"pid": process.pid, "log_file": str(log_file)})
            return self.status_locked()

    def stop(self, payload: dict | None = None) -> dict:
        with self.lock:
            self._refresh_locked()
            source = self._parse_source((payload or {}).get("source"))
            process = self.processes.get(source)
            current = self.currents.get(source)
            if not process or process.poll() is not None:
                return self.status_locked()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            current = dict(current or {})
            current["status"] = "stopping"
            self.currents[source] = current
            if self.task_registry and current.get("job_id"):
                self.task_registry.update_task(current["job_id"], status="stopping")
                self.task_registry.add_event(current["job_id"], "stopping", "已发送停止信号。")
            return self.status_locked()

    def status(self) -> dict:
        with self.lock:
            self._refresh_locked()
            return self.status_locked()

    def logs(self, lines: int = 120, source: str | None = None) -> dict:
        with self.lock:
            self._refresh_locked()
            current = self._selected_current_locked(source)
            log_file = current.get("log_file") or ""
        if not log_file or not Path(log_file).exists():
            return {"source": current.get("source", ""), "log_file": log_file, "content": ""}
        return {
            "source": current.get("source", ""),
            "log_file": log_file,
            "content": "\n".join(Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]),
        }

    def status_locked(self) -> dict:
        spiders = self._spider_snapshots_locked()
        selected = self._selected_current_locked(None)
        return {
            "spider": selected,
            "spiders": spiders,
            "spider_list": [spiders[item["id"]] for item in SPIDER_SOURCES],
            "available_types": list(SPIDER_TYPES),
            "available_sources": list(SPIDER_SOURCES),
        }

    def _spider_snapshots_locked(self) -> dict[str, dict]:
        snapshots = {}
        for item in SPIDER_SOURCES:
            source = item["id"]
            current = dict(self.currents.get(source) or {})
            if not current:
                current = {
                    "job_id": "",
                    "status": "idle",
                    "pid": None,
                    "started_at": "",
                    "finished_at": "",
                    "returncode": None,
                    "source": source,
                    "source_label": item["name"],
                    "types": [],
                    "max_pages": None,
                    "threads": None,
                    "new_only": False,
                    "stock_code": "",
                    "log_file": "",
                    "error": "",
                }
            snapshots[source] = current
        return snapshots

    def _selected_current_locked(self, source: str | None) -> dict:
        if source:
            return self._spider_snapshots_locked().get(self._parse_source(source), {})
        running = [item for item in self.currents.values() if item.get("status") in {"running", "stopping"}]
        if running:
            return sorted(running, key=lambda item: item.get("started_at") or "", reverse=True)[0]
        if self.currents:
            return sorted(self.currents.values(), key=lambda item: item.get("started_at") or "", reverse=True)[0]
        return {"status": "idle", "pid": None, "log_file": "", "source": "", "source_label": ""}

    def _build_command(
        self,
        source: str,
        selected_types: list[str],
        max_pages: int,
        threads: int,
        new_only: bool,
        article_sleep: str,
        page_sleep: str,
        log_file: Path,
        env: dict,
        stock_code: str,
    ) -> tuple[list[str], Path, str]:
        if source == "ths":
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
            if new_only:
                cmd.extend(["--new-only", "--existing-stop-count", "10"])
            return cmd, self.spider_dir, "同花顺"

        if source == "ths_market":
            if not stock_code:
                raise ValueError("分钟行情抓取需要填写股票代码。")
            return [
                sys.executable,
                "-m",
                "stock_pipeline",
                "market",
                "ths-minute",
                "--codes",
                stock_code,
                "--sleep",
                "0,0",
            ], self.project_root, "分钟行情"

        if source == "guardian":
            env["GUARDIAN_START_PAGE"] = "1"
            env["GUARDIAN_END_PAGE"] = str(max_pages)
            return [sys.executable, "Guardian.py"], self.spider_dir / "newsweaver" / "Guardian", "Guardian"

        raise ValueError("未知爬虫数据源。")

    def _refresh_locked(self) -> None:
        for source, process in list(self.processes.items()):
            current = self.currents.get(source)
            if not current:
                continue
            returncode = process.poll()
            if returncode is None:
                continue
            current["returncode"] = returncode
            current["finished_at"] = current.get("finished_at") or timestamp()
            if current.get("status") == "stopping":
                current["status"] = "stopped"
            else:
                current["status"] = "succeeded" if returncode == 0 else "failed"
            if returncode != 0:
                current["error"] = self._failure_summary(Path(current.get("log_file") or ""))
                self._append_process_summary(Path(current.get("log_file") or ""), returncode, current["error"])
            if self.task_registry and current.get("job_id"):
                final_status = current["status"]
                error = "" if returncode == 0 else current.get("error") or f"returncode={returncode}"
                self.task_registry.update_task(current["job_id"], status=final_status, error=error)
                self.task_registry.add_event(current["job_id"], final_status, f"爬虫进程结束，returncode={returncode}。")
            self.processes.pop(source, None)

    def _failure_summary(self, log_file: Path) -> str:
        if not log_file.exists():
            return "爬虫进程异常退出，但没有生成日志。"
        lines = [line.strip() for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        if not lines:
            return "爬虫进程异常退出，但日志为空。"
        important = [
            line
            for line in lines
            if "Traceback" in line
            or "Error" in line
            or "ERROR" in line
            or "Exception" in line
            or "ModuleNotFoundError" in line
            or "ImportError" in line
            or "SystemExit" in line
            or "failed" in line.lower()
        ]
        if important:
            return important[-1][-500:]
        return lines[-1][-500:]

    def _append_process_summary(self, log_file: Path, returncode: int, error: str) -> None:
        try:
            ensure_dir(log_file.parent)
            with log_file.open("a", encoding="utf-8") as output:
                output.write(f"\nadmin spider finished: returncode={returncode}\n")
                if error:
                    output.write(f"admin spider error summary: {error}\n")
        except OSError:
            pass

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

    def _parse_source(self, raw_value) -> str:
        source = str(raw_value or "ths").strip()
        allowed = {item["id"] for item in SPIDER_SOURCES}
        if source not in allowed:
            raise ValueError("未知爬虫数据源：" + source)
        return source

    def _source_label(self, source: str) -> str:
        return self._source_meta(source).get("name", source)

    def _source_meta(self, source: str) -> dict:
        for item in SPIDER_SOURCES:
            if item["id"] == source:
                return item
        return {"id": source, "name": source}

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
        if not user or user.get("disabled"):
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

    def system_api_key_state(self, data: dict | None = None) -> dict:
        if data is None:
            with self.lock:
                keys = self._read().get("system_api_keys", {})
        else:
            keys = data.get("system_api_keys", {})
        return {
            name: {
                "configured": bool(keys.get(name, {}).get("ciphertext")),
                "updated_at": keys.get(name, {}).get("updated_at", ""),
            }
            for name in sorted(SYSTEM_KEY_NAMES)
        }

    def save_system_api_keys(self, values: dict[str, str], updated_by: str) -> dict:
        cleaned = {name: str(value or "").strip() for name, value in values.items() if name in SYSTEM_KEY_NAMES}
        if any(not value for value in cleaned.values()):
            raise ValueError("系统 API key 不能为空。")
        with self.lock:
            data = self._read()
            keys = data.setdefault("system_api_keys", {})
            for name, value in cleaned.items():
                keys[name] = {
                    "ciphertext": self.key_cipher.encrypt(value),
                    "updated_at": timestamp(),
                    "updated_by": updated_by,
                }
                self._audit(data, updated_by, "system_api_key_saved", name, {})
            self._write(data)
        return self.system_api_key_state()

    def delete_system_api_keys(self, names: list[str] | None, updated_by: str) -> dict:
        selected = set(names or SYSTEM_KEY_NAMES) & SYSTEM_KEY_NAMES
        with self.lock:
            data = self._read()
            keys = data.get("system_api_keys") or {}
            for name in selected:
                if name in keys:
                    keys.pop(name, None)
                    self._audit(data, updated_by, "system_api_key_deleted", name, {})
            if keys:
                data["system_api_keys"] = keys
            else:
                data.pop("system_api_keys", None)
            self._write(data)
        return self.system_api_key_state()

    def decrypted_system_api_keys(self) -> dict[str, str]:
        with self.lock:
            keys = self._read().get("system_api_keys", {})
        result = {}
        for name in SYSTEM_KEY_NAMES:
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

    def admin_grant_vip(self, username: str, days: int, actor: str) -> dict:
        now = time.time()
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            base = max(now, float(user.get("vip_until") or 0))
            user["vip_until"] = base + max(1, int(days)) * 86400
            user["tier"] = "vip"
            self._audit(data, actor, "grant_vip", username, {"days": days})
            self._write(data)
            return self.user_access_state(username, data=data)

    def admin_revoke_vip(self, username: str, actor: str) -> dict:
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            user["vip_until"] = 0
            user["tier"] = "user"
            self._audit(data, actor, "revoke_vip", username, {})
            self._write(data)
            return self.user_access_state(username, data=data)

    def admin_set_disabled(self, username: str, disabled: bool, actor: str) -> None:
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            user["disabled"] = bool(disabled)
            self._audit(data, actor, "disable_user" if disabled else "enable_user", username, {})
            self._write(data)

    def admin_reset_demo_budget(self, username: str, actor: str) -> dict:
        now = time.time()
        with self.lock:
            data = self._read()
            account = data.get("demo_accounts", {}).get(username)
            if not account:
                raise KeyError("找不到测试账号。")
            account["window_start"] = now
            account["count"] = 0
            self._audit(data, actor, "reset_demo_budget", username, {})
            self._write(data)
            return self._public_demo_account(account)

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
                    "disabled": bool(user.get("disabled")),
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
            "system_api_keys": self.system_api_key_state(data),
            "users": users,
            "invites": [self._public_invite(invite) for invite in sorted(data.get("invites", {}).values(), key=lambda item: item.get("expires_at", 0), reverse=True)],
            "vip_codes": [self._public_vip_code(item) for item in sorted(data.get("vip_codes", {}).values(), key=lambda item: item.get("expires_at", 0), reverse=True)],
            "demo_accounts": [
                self._public_demo_account(account)
                for account in sorted(data.get("demo_accounts", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
            ],
            "audit_logs": list(reversed(data.get("audit_logs", [])[-80:])),
        }

    def _read(self) -> dict:
        if not self.path.exists():
            return {"users": {}, "used_invites": {}, "invites": {}, "usage": {}, "demo_accounts": {}, "vip_codes": {}, "system_api_keys": {}, "audit_logs": []}
        data = read_json(self.path)
        data.setdefault("users", {})
        data.setdefault("used_invites", {})
        data.setdefault("invites", {})
        data.setdefault("usage", {})
        data.setdefault("demo_accounts", {})
        data.setdefault("vip_codes", {})
        data.setdefault("system_api_keys", {})
        data.setdefault("audit_logs", [])
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

    def _audit(self, data: dict, actor: str, action: str, target: str, details: dict) -> None:
        logs = data.setdefault("audit_logs", [])
        logs.append({"time": timestamp(), "actor": actor, "action": action, "target": target, "details": details})
        if len(logs) > 500:
            data["audit_logs"] = logs[-500:]
