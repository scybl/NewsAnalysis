from __future__ import annotations

import secrets
import json
import time
import hmac
import hashlib
import threading
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.cookies import SimpleCookie

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
from .stock_storage import analysis_dossier_path, analysis_output_path, build_local_stock_payload, current_dir, list_analysis_results, read_analysis_result, stock_exists, stock_status, sync_stock_data
from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, write_json


STATIC_DIR = Path(__file__).resolve().parent / "web_static"


class StockWebApp:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.settings = get_settings(require_deepseek=False)
        self.tushare = TushareClient(self.settings.tushare_token, self.settings.tushare_base_url)
        self.index = StockSearchIndex(self.tushare, PROJECT_ROOT / "cache" / "stocks.json")
        self.sessions: dict[str, float] = {}
        self.session_ttl_seconds = 60 * 60 * 12
        self.auth_secret = self.settings.web_session_secret or secrets.token_urlsafe(32)
        self.multi_agent_jobs: dict[str, dict] = {}
        self.multi_agent_jobs_lock = threading.Lock()

    def _build_multi_agent_result(self, payload: dict, progress_callback=None) -> dict:
        ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
        analysis_type = str(payload.get("analysis_type") or "value_speculation")
        years, full_history = self._parse_history_scope_value(payload.get("years"))
        allow_dynamic_fetch = payload.get("allow_dynamic_fetch", True) is not False
        max_parallel_agents = int(payload.get("max_parallel_agents") or 8)
        llm_client = (
            DeepSeekClient(
                self.settings.deepseek_api_key,
                self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
            )
            if self.settings.deepseek_api_key
            else None
        )
        return MultiAgentRunner(self.tushare, llm_client=llm_client, progress_callback=progress_callback).run(
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

    def _parse_history_scope_value(self, value) -> tuple[int | None, bool]:
        if value in (None, "", "all", "full", "history"):
            return None, True
        return int(value), False

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
                    self._json({"ok": True, "authenticated": self._is_authenticated(), "user": app.settings.web_username if self._is_authenticated() else ""})
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path == "/api/search":
                    query = parse_qs(parsed.query).get("q", [""])[0]
                    self._json({"items": app.index.search(query)})
                    return
                if parsed.path == "/api/refresh":
                    app.index.stocks(refresh=True)
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/analysis-frameworks":
                    self._json({"ok": True, "items": list_analysis_frameworks()})
                    return
                super().do_GET()

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/login":
                    self._handle_login()
                    return
                if parsed.path == "/api/logout":
                    self._handle_logout()
                    return
                if not self._require_auth(parsed.path):
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
                    valid_user = secrets.compare_digest(username, app.settings.web_username)
                    valid_password = secrets.compare_digest(password, app.settings.web_password)
                    if not (valid_user and valid_password):
                        self._json({"ok": False, "error": "账号或密码错误"}, status=401)
                        return
                    token = secrets.token_urlsafe(32)
                    app.sessions[token] = time.time() + app.session_ttl_seconds
                    self._json(
                        {"ok": True, "user": app.settings.web_username},
                        headers={"Set-Cookie": self._session_cookie(self._signed_token(token))},
                    )
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_multi_agent_analyze(self) -> None:
                try:
                    payload = self._read_json()
                    if payload.get("async"):
                        self._json(app._start_multi_agent_job(payload))
                    else:
                        self._json(app._build_multi_agent_result(payload))
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
                    app.sessions.pop(token, None)
                self._json({"ok": True}, headers={"Set-Cookie": "stock_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

            def _handle_analyze(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    framework = get_analysis_framework(str(payload.get("analysis_type") or "value_speculation"))
                    years, full_history = self._parse_history_scope(payload)
                    question = str(payload.get("question") or framework.question)
                    if not stock_exists(ts_code):
                        sync_stock_data(app.tushare, ts_code, years=years, full_history=full_history)
                    local_dir = current_dir(ts_code)
                    analysis_dossier = read_json(analysis_dossier_path(ts_code, framework.key))
                    metadata = read_json(local_dir / "metadata.json") if (local_dir / "metadata.json").exists() else {}

                    answer = ""
                    session_path = ""
                    if app.settings.deepseek_api_key:
                        analyst = StockAnalyst(
                            DeepSeekClient(
                                app.settings.deepseek_api_key,
                                app.settings.deepseek_base_url,
                                model=app.settings.deepseek_model,
                            )
                        )
                        session = session_path_for(ts_code, PROJECT_ROOT / "sessions", framework.key)
                        answer = analyst.framework_analysis(analysis_dossier, session, framework, question=question)
                        analysis_output_path(ts_code, framework.key).write_text(answer, encoding="utf-8")
                        session_path = str(session)

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
                    self._json(sync_stock_data(app.tushare, ts_code, years=years, full_history=full_history))
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
                if self._is_authenticated():
                    return True
                if path.startswith("/api/"):
                    self._json({"ok": False, "error": "请先登录"}, status=401)
                else:
                    self._redirect("/login")
                return False

            def _is_authenticated(self) -> bool:
                token = self._session_token()
                if not token:
                    return False
                expires_at = app.sessions.get(token)
                if not expires_at:
                    return False
                if expires_at < time.time():
                    app.sessions.pop(token, None)
                    return False
                app.sessions[token] = time.time() + app.session_ttl_seconds
                return True

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
