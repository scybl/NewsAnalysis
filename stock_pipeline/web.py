from __future__ import annotations

import secrets
import json
import time
import hmac
import hashlib
import base64
import threading
import uuid
import random
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from http.cookies import SimpleCookie
from cryptography.fernet import Fernet, InvalidToken
import pymongo

from backend.auth_policy import ADMIN_ONLY_PAGES, ADMIN_ROLES, DATA_CONSOLE_ROLES, DATA_CONSOLE_PAGES, READONLY_ADMIN_ROLE
from backend.credentials_registry import ADMIN_CREDENTIALS, BAIDU_PAN_SECRET_DIR, CREDENTIAL_PUBLIC_FIELDS, CRAWLER_SECRET_DIR
from backend.fetch_registry import DATA_FETCH_ACTIONS, SPIDER_SOURCES, data_key_snapshot, fetch_method_snapshot
from backend.paths import STATIC_DIR

from .agent_jobs import PersistentAgentJobStore
from .analysis_frameworks import get_analysis_framework, list_analysis_frameworks
from .config import PROJECT_ROOT, get_settings
from .akshare_client import AkshareClient
from .composite_client import ValidatingStockClient
from .crawler_monitor import crawler_status_snapshot, news_crawler_prometheus_metrics
from .crawler_failure_actions import retry_failure_group
from .data_sources import configure_data_sources, data_source_snapshot, provider_available, provider_status
from .data_random_audit import build_random_audit_payload
from .deepseek_client import DeepSeekClient, DeepSeekError
from .eastmoney_client import EastmoneyClient
from .kaipanla import KAIPANLA_FEATURES, kaipanla_daily_overview, list_kaipanla_features, list_kaipanla_records, read_kaipanla_record, run_kaipanla_batch, run_kaipanla_feature, validate_kaipanla_integration
from .news_library import query_news_library
from .news_search import search_related_news
from .ops_status import active_heavy_io_tasks, build_ops_snapshot
from .minute_storage import minute_reference_row_counts
from .market_dimensions import STOCK_COLLECTIONS, STOCK_DATABASE
from .raw_news import MongoRawNewsRepository, raw_news_config
from .secret_store import get_secret_store
from .stock_search import StockSearchIndex
from .stock_storage import (
    analysis_output_path,
    analysis_review_context,
    build_local_stock_payload,
    choose_daily_market_target,
    current_dir,
    list_analysis_results,
    list_local_stock_codes,
    list_local_stock_summaries,
    read_current_analysis_dossier,
    read_current_dossier,
    read_current_full_data,
    read_current_metadata,
    read_analysis_result,
    stock_storage_status_snapshot,
    stock_exists,
    stock_status,
    sync_daily_market_for_existing_stocks,
    sync_stock_data,
)
from .stock_storage_repair import repair_stock_storage_issue, report_stock_storage_issue, run_stock_storage_health_check
from .task_queue import HEAVY_IO as QUEUE_HEAVY_IO
from .task_queue import LIGHT_IO as QUEUE_LIGHT_IO
from .task_queue import NORMAL_IO as QUEUE_NORMAL_IO
from .task_queue import QUEUE_OWNER, QueueTaskDeferred, ResourceAwareTaskQueue
from .ths_minute import build_config as build_ths_minute_config
from .ths_minute import fetch_and_store_minutes
from .tushare_client import TushareClient, TushareError
from .totp import verify_totp
from .translation import BaiduTranslateClient, BaiduTranslateConfig, TranslationError
from .utils import CN_TZ, ensure_dir, normalize_ts_code, read_json, timestamp, today_yyyymmdd, write_json


AGENT_GATEWAY_AVAILABLE = False
DATA_DISTRIBUTION_AVAILABLE = False
ANALYSIS_MODULE_STATUS_TEXT = "分析模块已拆分为外部项目，当前主站只保留数据资产和历史报告读取。"
SENSITIVE_LOCAL_PATH_KEYS = {
    "local_dir",
    "stock_dir",
    "output_dir",
    "full_data_path",
    "dossier_path",
    "value_dossier_path",
    "analysis_dossier_path",
    "analysis_path",
    "session_path",
    "local_path",
    "path",
}


def redact_local_paths(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: redact_local_paths(value)
            for key, value in payload.items()
            if key not in SENSITIVE_LOCAL_PATH_KEYS and not key.endswith("_path") and not key.endswith("_dir")
        }
    if isinstance(payload, list):
        return [redact_local_paths(item) for item in payload]
    return payload
BILLABLE_API_PATHS = {
    "/api/sync-stock-data",
    "/api/analyze",
    "/api/multi-agent-analyze",
}
USER_KEY_NAMES = {"tushare", "deepseek"}
SYSTEM_KEY_NAMES = {"deepseek"}
AGENT_TOKEN_PREFIX = "na_agent_"
AGENT_ALLOWED_SCOPES = {"R", "B"}
AGENT_SCOPE_LABELS = {
    "R": "读取本地股票、新闻、报告和任务状态",
    "B": "提交模型消耗型多 Agent 分析任务",
}


def _hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_agent_scopes(raw) -> list[str]:
    if isinstance(raw, str):
        values = [item.strip().upper() for item in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip().upper() for item in raw]
    else:
        values = ["R"]
    scopes = sorted({scope for scope in values if scope in AGENT_ALLOWED_SCOPES})
    return scopes or ["R"]


def _secure_text_equal(left: object, right: object) -> bool:
    """Constant-time comparison that also supports non-ASCII credentials."""
    return hmac.compare_digest(str(left).encode("utf-8"), str(right).encode("utf-8"))


def _is_admin_role(role: object) -> bool:
    return str(role or "") in ADMIN_ROLES


def _can_view_data_console(role: object) -> bool:
    return str(role or "") in DATA_CONSOLE_ROLES


def _is_readonly_admin_role(role: object) -> bool:
    return str(role or "") == READONLY_ADMIN_ROLE


def _readonly_admin_account(settings, username: str, password: str) -> dict | None:
    readonly_username = str(getattr(settings, "admin_readonly_username", "") or "").strip()
    readonly_password = str(getattr(settings, "admin_readonly_password", "") or "")
    if not readonly_username or not readonly_password:
        return None
    if _secure_text_equal(username, readonly_username) and _secure_text_equal(password, readonly_password):
        return {"username": readonly_username, "role": READONLY_ADMIN_ROLE, "admin_readonly": True}
    return None


def _public_stock_client(settings) -> ValidatingStockClient:
    return ValidatingStockClient(
        AkshareClient(pause=settings.tushare_pause_seconds),
        [EastmoneyClient(pause=settings.tushare_pause_seconds)],
    )


def _stock_metadata_age_seconds(updated_at: str) -> int | None:
    if not updated_at:
        return None
    try:
        value = datetime.strptime(updated_at, "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return max(0, int((datetime.now() - value).total_seconds()))


def _credential_spec(name: str) -> dict[str, Any]:
    for spec in ADMIN_CREDENTIALS:
        if spec["name"] == name:
            return spec
    raise KeyError("未知凭据。")


def _credential_file_path(spec: dict[str, Any]) -> Path:
    path_name = str(spec.get("path") or "")
    base_dir = BAIDU_PAN_SECRET_DIR if spec.get("secret_dir") == "baidu_pan" else CRAWLER_SECRET_DIR
    path = (base_dir / path_name).resolve()
    if base_dir.resolve() not in path.parents:
        raise ValueError("凭据文件路径无效。")
    return path


def _credential_file_state(spec: dict[str, Any]) -> dict[str, Any]:
    path = _credential_file_path(spec)
    if not path.exists() or path.stat().st_size == 0:
        return {"configured": False, "updated_at": ""}
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "configured": True,
        "updated_at": updated_at,
    }


def admin_credentials_snapshot(user_store=None) -> dict[str, Any]:
    secret_store = get_secret_store()
    items: list[dict[str, Any]] = []
    for spec in ADMIN_CREDENTIALS:
        item = {key: value for key, value in spec.items() if key in CREDENTIAL_PUBLIC_FIELDS}
        storage = str(spec.get("storage") or "")
        if storage == "file":
            item.update(_credential_file_state(spec))
        else:
            state = secret_store.state(str(spec["name"]))
            item.update({"configured": state.configured, "updated_at": state.updated_at})
        items.append(item)
    return {"items": items}


def set_admin_credential(name: str, value: str, *, updated_by: str, user_store=None) -> dict[str, Any]:
    spec = _credential_spec(name)
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("凭据值不能为空。")
    if len(raw_value) > 100_000:
        raise ValueError("凭据值过大，请拆分或使用文件方式手动配置。")
    kind = str(spec.get("kind") or "")
    if kind == "url" and not raw_value.startswith(("http://", "https://")):
        raise ValueError("URL 必须以 http:// 或 https:// 开头。")
    if kind == "boolean" and raw_value.lower() not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
        raise ValueError("布尔配置只能填写 1/0、true/false、yes/no 或 on/off。")
    storage = str(spec.get("storage") or "")
    if storage == "file":
        path = _credential_file_path(spec)
        ensure_dir(path.parent)
        path.write_text(raw_value, encoding="utf-8")
        os.chmod(path, 0o600)
        _clear_source_pause_for_credential(name)
        return _credential_file_state(spec)
    get_secret_store().set(str(spec["name"]), raw_value, updated_by=updated_by)
    _clear_source_pause_for_credential(name)
    state = get_secret_store().state(str(spec["name"]))
    return {"configured": state.configured, "updated_at": state.updated_at}


def delete_admin_credential(name: str, *, updated_by: str, user_store=None) -> dict[str, Any]:
    spec = _credential_spec(name)
    storage = str(spec.get("storage") or "")
    if storage == "file":
        path = _credential_file_path(spec)
        if path.exists():
            path.unlink()
        return _credential_file_state(spec)
    get_secret_store().delete(str(spec["name"]))
    state = get_secret_store().state(str(spec["name"]))
    return {"configured": state.configured, "updated_at": state.updated_at}


def _admin_credential_value(name: str) -> str:
    spec = _credential_spec(name)
    env_value = (os.getenv(str(spec.get("env") or "")) or "").strip() if spec.get("env") else ""
    if env_value:
        return env_value
    storage = str(spec.get("storage") or "")
    if storage == "file":
        path = _credential_file_path(spec)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""
    return get_secret_store().get(str(spec["name"]))


def _clear_source_pause_for_credential(name: str) -> None:
    source_name = str(name).split(".", 1)[0]
    if source_name not in {"bloomberg", "politico", "guardian"}:
        return
    try:
        import pymongo

        config = raw_news_config()
        client = pymongo.MongoClient(config.uri, serverSelectionTimeoutMS=1000, socketTimeoutMS=1500)
        try:
            client[config.database]["source_pauses"].update_many(
                {"source_name": source_name, "active": True},
                {"$set": {"active": False, "cleared_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}},
            )
        finally:
            client.close()
    except Exception:
        return


def guardian_translation_payload(article_id: str) -> dict[str, Any]:
    target_language = "zh"
    repository = MongoRawNewsRepository(timeout_ms=5000)
    try:
        article = repository.get_by_article_id(article_id)
        if not article:
            raise ValueError("找不到这篇文章。")
        if str(article.get("source_name") or "").lower() != "guardian":
            raise ValueError("当前只支持 Guardian 文章翻译。")

        content_hash = _guardian_translation_hash(article)
        cached = ((article.get("translations") or {}).get(target_language) or {})
        if cached.get("content_hash") == content_hash:
            return {"cached": True, "translation": _public_translation(cached)}

        app_id = _admin_credential_value("guardian.baidu_translate_app_id")
        secret_key = _admin_credential_value("guardian.baidu_translate_secret_key")
        if not app_id or not secret_key:
            raise ValueError("请先在凭据管理中配置 Baidu Translate App ID 和 Secret Key。")

        client = BaiduTranslateClient(BaiduTranslateConfig(app_id=app_id, secret_key=secret_key))
        translation = {
            "provider": "baidu",
            "engine": "machine",
            "source_language": "en",
            "target_language": target_language,
            "content_hash": content_hash,
            "translated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "title": client.translate(str(article.get("title") or ""), source="en", target=target_language),
            "summary": client.translate(str(article.get("summary") or ""), source="en", target=target_language),
            "content": client.translate(str(article.get("content") or article.get("summary") or ""), source="en", target=target_language),
        }
        repository.set_translation(str(article.get("article_id") or article_id), target_language, translation)
        return {"cached": False, "translation": _public_translation(translation)}
    finally:
        repository.close()


def _guardian_translation_hash(article: dict[str, Any]) -> str:
    source = "\n".join(
        [
            str(article.get("title") or ""),
            str(article.get("summary") or ""),
            str(article.get("content") or ""),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _public_translation(translation: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": translation.get("provider") or "baidu",
        "engine": translation.get("engine") or "machine",
        "source_language": translation.get("source_language") or "en",
        "target_language": translation.get("target_language") or "zh",
        "translated_at": translation.get("translated_at") or "",
        "title": translation.get("title") or "",
        "summary": translation.get("summary") or "",
        "content": translation.get("content") or "",
    }


def admin_runtime_alerts() -> list[dict[str, Any]]:
    try:
        return crawler_status_snapshot(limit=1, failure_limit=10).get("alerts") or []
    except Exception:
        return []


def _public_heavy_io_blockers(tasks: list[dict[str, Any]], *, requested_task_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": task.get("id") or "",
            "title": task.get("title") or "",
            "kind": task.get("kind") or "",
            "status": task.get("status") or "",
            "last_event": task.get("last_event") or "",
            "progress": task.get("progress") or {},
        }
        for task in tasks
        if str(task.get("id") or "") != requested_task_id
    ]


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
        self.sessions_path = PROJECT_ROOT / "local_data" / "web_sessions.json"
        self.sessions: dict[str, dict] = {}
        self.active_session_by_user: dict[str, str] = {}
        self.session_lock = threading.Lock()
        self.admin_login_challenges: dict[str, float] = {}
        self.admin_login_challenge_lock = threading.Lock()
        self.session_ttl_seconds = 60 * 60 * 12
        self.auth_secret = self.settings.web_session_secret or secrets.token_urlsafe(32)
        self._load_sessions()
        self.key_cipher = ApiKeyCipher(self.settings.web_key_encryption_secret)
        self.user_store = UserStore(
            PROJECT_ROOT / "local_data" / "web_users.json",
            self.key_cipher,
            admin_username=self.settings.web_username,
        )
        self.invite_codes = {code.strip() for code in self.settings.web_invite_codes.split(",") if code.strip()}
        self.user_store.seed_invites(self.invite_codes, ttl_seconds=self.settings.web_invite_ttl_seconds, created_by="env")
        self.task_registry = TaskRegistry(PROJECT_ROOT / "local_data" / "admin_tasks.json")
        self.task_queue = ResourceAwareTaskQueue(
            PROJECT_ROOT / "local_data" / "task_queue.json",
            self.task_registry,
            external_blockers=lambda task_id: self._running_heavy_io_blockers(task_id),
            autostart=False,
        )
        self.daily_market_scheduler = DailyMarketScheduler(self, PROJECT_ROOT / "local_data" / "daily_market_scheduler.json", self.task_registry)
        self.kaipanla_scheduler = KaipanlaScheduler(
            PROJECT_ROOT / "local_data" / "kaipanla_scheduler.json",
            self.task_registry,
            self.task_queue,
        )
        self.stock_activity_lock = threading.Lock()
        self.last_stock_request_epoch = time.time()
        self.last_stock_request_at = timestamp()
        self.last_stock_request_code = ""
        self.idle_stock_prefetch_scheduler = IdleStockPrefetchScheduler(
            self,
            PROJECT_ROOT / "local_data" / "idle_stock_prefetch_scheduler.json",
            self.task_registry,
        )
        self.data_random_audit_scheduler = DataRandomAuditScheduler(
            self,
            PROJECT_ROOT / "local_data" / "data_random_audit_scheduler.json",
            self.task_registry,
        )
        self.stock_storage_health_scheduler = StockStorageHealthScheduler(
            self,
            PROJECT_ROOT / "local_data" / "stock_storage_health_scheduler.json",
            self.task_registry,
        )
        self.market_fetch_controller = MarketFetchController(PROJECT_ROOT, self.task_registry)
        self.news_refetch_controller = NewsRefetchController(PROJECT_ROOT, self.task_registry)
        self.agent_job_store = PersistentAgentJobStore(PROJECT_ROOT / "local_data" / "agent_jobs.json")
        self.agent_rate_lock = threading.Lock()
        self.agent_rate_state: dict[str, list[float]] = {}
        self.task_queue.start()

    def _running_heavy_io_blockers(self, requested_task_id: str) -> list[dict[str, Any]]:
        running_heavy_tasks = [
            task
            for task in active_heavy_io_tasks(build_ops_snapshot(PROJECT_ROOT, crawler_snapshot_fn=None))
            if task.get("running") or task.get("status") in {"running", "running_unknown_pid", "stopping", "warning"}
        ]
        return _public_heavy_io_blockers(running_heavy_tasks, requested_task_id=requested_task_id)

    def _build_multi_agent_result(self, payload: dict, progress_callback=None) -> dict:
        if not self.settings.stock_analysis_execution_enabled:
            raise RuntimeError(ANALYSIS_MODULE_STATUS_TEXT)
        from .agents import LangGraphMultiAgentRunner, MultiAgentRunner
        from .agents.multi_agent import MultiAgentOptions

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
            "agent_token_id": payload.get("_agent_token_id", ""),
            "created_epoch": time.time(),
            "updated_epoch": time.time(),
        }
        self.agent_job_store.create(job)
        self.task_registry.create_task(
            job_id,
            "multi_agent",
            f"多 Agent 分析 {payload.get('ts_code') or payload.get('code') or ''}",
            metadata={"analysis_type": payload.get("analysis_type") or "value_speculation", "agent_token_id": payload.get("_agent_token_id", "")},
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
        job = self.agent_job_store.update(job_id, status=status, event=event, result=result, error=error)
        if not job:
            return
        if status:
            self.task_registry.update_task(job_id, status=status, error=error, result=result)
        if event:
            self.task_registry.add_event(job_id, event.get("stage") or "progress", event.get("message") or "", event.get("details") or {})

    def _read_multi_agent_job(self, job_id: str) -> dict:
        job = self.agent_job_store.get(job_id)
        if not job:
            raise FileNotFoundError(f"找不到多 Agent 后台任务：{job_id}")
        return job

    def agent_rate_allowed(self, token: dict) -> bool:
        token_id = str(token.get("id") or token.get("token_prefix") or "")
        limit = max(1, int(token.get("rate_limit_per_min") or 60))
        now = time.time()
        window_start = now - 60
        with self.agent_rate_lock:
            bucket = [item for item in self.agent_rate_state.get(token_id, []) if item >= window_start]
            if len(bucket) >= limit:
                self.agent_rate_state[token_id] = bucket
                return False
            bucket.append(now)
            self.agent_rate_state[token_id] = bucket
            return True

    def agent_idempotency_get(self, token_id: str, route: str, key: str) -> dict | None:
        return self.agent_job_store.idempotency_get(token_id, route, key)

    def agent_idempotency_put(self, token_id: str, route: str, key: str, response: dict) -> None:
        self.agent_job_store.idempotency_put(token_id, route, key, response)

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
            "agent_token_id": "",
            "created_epoch": time.time(),
            "updated_epoch": time.time(),
        }
        self.agent_job_store.create(job)
        self.task_registry.create_task(job_id, "multi_agent_cache", "复用共享多 Agent 分析", metadata={"cache_hit": True})
        self.task_registry.update_task(job_id, status="succeeded", result=result)
        self.task_registry.add_event(job_id, "cache", message, {"cache_hit": True})
        return {"ok": True, "job_id": job_id, "status": "succeeded", "progress": job["progress"]}

    def health_snapshot(self) -> dict:
        spider = self.market_fetch_controller.status().get("spider", {})
        return {
            "ok": True,
            "status": "ok",
            "time": timestamp(),
            "web": {"host": self.host, "port": self.port},
            "config": {
                "tushare_configured": bool(self.settings.tushare_token),
                "tushare_status": provider_status("tushare"),
                "deepseek_configured": self.user_store.system_api_key_state().get("deepseek", {}).get("configured", False),
                "stock_agent_engine": self.settings.stock_agent_engine,
                "stock_agent_template": self.settings.stock_agent_template,
                "analysis_module": self.analysis_module_status(),
                "stock_analysis_refresh_ttl_seconds": self.settings.stock_analysis_refresh_ttl_seconds,
            },
            "data_sources": data_source_snapshot(self.settings).get("summary", {}),
            "storage": {
                "local_data_exists": (PROJECT_ROOT / "local_data").exists(),
                "web_user_store_exists": self.user_store.path.exists(),
            },
            "spider": {"status": spider.get("status", "idle"), "pid": spider.get("pid")},
            "idle_stock_prefetch": self.idle_stock_prefetch_scheduler.status().get("scheduler", {}),
            "tasks": {"count": len(self.task_registry.list_tasks(500))},
            "agent_jobs": {"count": len(self.agent_job_store.list(limit=200))},
        }

    def record_stock_request(self, ts_code: str = "") -> None:
        with self.stock_activity_lock:
            self.last_stock_request_epoch = time.time()
            self.last_stock_request_at = timestamp()
            self.last_stock_request_code = ts_code

    def stock_request_state(self) -> dict:
        with self.stock_activity_lock:
            last_epoch = float(self.last_stock_request_epoch or 0)
            last_at = self.last_stock_request_at
            last_code = self.last_stock_request_code
        idle_seconds = max(0, int(time.time() - last_epoch)) if last_epoch else 0
        return {"last_request_at": last_at, "last_request_code": last_code, "idle_seconds": idle_seconds}

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
        from .agents import list_agent_runs, read_agent_run

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
        from .agents import list_agent_runs, read_agent_run

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

    def analysis_module_status(self) -> dict:
        return {
            "available": bool(self.settings.stock_analysis_execution_enabled),
            "mode": "embedded" if self.settings.stock_analysis_execution_enabled else "external",
            "external_url": self.settings.stock_analysis_external_url,
            "message": "" if self.settings.stock_analysis_execution_enabled else ANALYSIS_MODULE_STATUS_TEXT,
        }

    def _current_data_fingerprint(self, ts_code: str) -> str:
        try:
            full_data = read_current_full_data(ts_code)
        except FileNotFoundError:
            return ""
        datasets = full_data.get("datasets", {})
        external_rows = minute_reference_row_counts(full_data)
        payload = {
            "ts_code": full_data.get("ts_code"),
            "date_range": full_data.get("date_range", {}),
            "dataset_rows": {**{name: len(rows) for name, rows in sorted(datasets.items())}, **external_rows},
            "external_datasets": full_data.get("external_datasets", {}),
            "latest_rows": {name: rows[:3] for name, rows in sorted(datasets.items()) if isinstance(rows, list) and rows},
            "fetch_errors": full_data.get("fetch_errors", []),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _stock_news_context(self, ts_code: str) -> dict:
        if not stock_exists(ts_code):
            raise FileNotFoundError(f"本地还没有 {ts_code} 的数据，请先更新本地数据。")
        full_data = read_current_full_data(ts_code)
        dossier = read_current_dossier(ts_code)
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

    def _create_admin_login_challenge(self) -> str:
        challenge = secrets.token_urlsafe(32)
        now = time.time()
        with self.admin_login_challenge_lock:
            self.admin_login_challenges = {
                token: expires_at
                for token, expires_at in self.admin_login_challenges.items()
                if expires_at > now
            }
            if len(self.admin_login_challenges) >= 1024:
                oldest = min(self.admin_login_challenges, key=self.admin_login_challenges.get)
                self.admin_login_challenges.pop(oldest, None)
            self.admin_login_challenges[challenge] = now + 300
        return challenge

    def _valid_admin_login_challenge(self, challenge: str) -> bool:
        if not challenge:
            return False
        now = time.time()
        with self.admin_login_challenge_lock:
            expires_at = self.admin_login_challenges.get(challenge, 0)
            if expires_at <= now:
                self.admin_login_challenges.pop(challenge, None)
                return False
            return True

    def _consume_admin_login_challenge(self, challenge: str) -> None:
        with self.admin_login_challenge_lock:
            self.admin_login_challenges.pop(challenge, None)

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
            self._write_sessions_locked()

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
                self._write_sessions_locked()
                return None
            session["expires_at"] = time.time() + self.session_ttl_seconds
            return dict(session)

    def _remove_session(self, token: str) -> None:
        with self.session_lock:
            self._remove_session_locked(token, self.sessions.get(token))
            self._write_sessions_locked()

    def _remove_sessions_for_user(self, username: str) -> None:
        with self.session_lock:
            for token, session in list(self.sessions.items()):
                if session.get("username") == username:
                    self._remove_session_locked(token, session)
            self._write_sessions_locked()

    def _remove_session_locked(self, token: str, session: dict | None) -> None:
        if not session:
            return
        self.sessions.pop(token, None)
        username = session.get("username", "")
        if username and self.active_session_by_user.get(username) == token:
            self.active_session_by_user.pop(username, None)

    def _load_sessions(self) -> None:
        if not self.sessions_path.exists():
            return
        now = time.time()
        try:
            payload = read_json(self.sessions_path)
        except (OSError, ValueError, TypeError):
            return
        items = payload.get("sessions", {}) if isinstance(payload, dict) else {}
        if not isinstance(items, dict):
            return
        for token, session in items.items():
            if not isinstance(token, str) or not isinstance(session, dict):
                continue
            username = str(session.get("username") or "")
            expires_at = float(session.get("expires_at") or 0)
            if not username or expires_at <= now:
                continue
            current_token = self.active_session_by_user.get(username)
            current = self.sessions.get(current_token, {}) if current_token else {}
            if expires_at <= float(current.get("expires_at") or 0):
                continue
            if current_token:
                self.sessions.pop(current_token, None)
            self.sessions[token] = {
                "username": username,
                "role": str(session.get("role") or "user"),
                "managed_demo": bool(session.get("managed_demo")),
                "expires_at": expires_at,
            }
            self.active_session_by_user[username] = token

    def _write_sessions_locked(self) -> None:
        ensure_dir(self.sessions_path.parent)
        payload = {"sessions": self.sessions, "updated_at": timestamp()}
        tmp_path = self.sessions_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.sessions_path)

    def serve(self) -> None:
        app = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

            def log_message(self, format: str, *args) -> None:
                print(f"{self.address_string()} - {format % args}")

            def end_headers(self) -> None:
                if not getattr(self, "path", "").startswith("/api/"):
                    self.send_header("Cache-Control", "no-store, max-age=0")
                super().end_headers()

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path.startswith("/api/agent/v1/"):
                    self._handle_agent_get(parsed)
                    return
                if parsed.path in ("/login", "/login.html"):
                    if self._is_authenticated():
                        self._redirect("/")
                        return
                    self.path = "/login.html"
                    super().do_GET()
                    return
                if parsed.path in ("/project", "/project.html"):
                    self.path = "/project.html"
                    super().do_GET()
                    return
                if parsed.path == "/styles.css":
                    self.path = "/styles.css"
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
                            "alerts": admin_runtime_alerts() if session and _is_admin_role(session.get("role")) else [],
                            **access,
                            "demo_remaining": self._demo_remaining(session) if session and session.get("role") == "demo" else None,
                        }
                    )
                    return
                if parsed.path == "/api/health":
                    self._json(app.health_snapshot())
                    return
                if parsed.path == "/metrics/news-crawler":
                    self._text(
                        news_crawler_prometheus_metrics(),
                        content_type="text/plain; version=0.0.4; charset=utf-8",
                    )
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path in ("/", "/index.html"):
                    self._redirect("/admin-crawler.html")
                    return
                if parsed.path == "/admin.html":
                    self._redirect("/admin-crawler.html")
                    return
                if parsed.path in ADMIN_ONLY_PAGES and not _is_admin_role((self._current_session() or {}).get("role")):
                    self._redirect("/admin-crawler.html")
                    return
                if parsed.path == "/admin-kaipanla.html":
                    self.send_response(302)
                    self.send_header("Location", "/admin-news.html#kaipanla-source")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                if parsed.path == "/api/search":
                    query = parse_qs(parsed.query).get("q", [""])[0]
                    app.record_stock_request()
                    self._json({"items": app.index.search(query)})
                    return
                if parsed.path == "/api/analysis-frameworks":
                    self._json({"ok": True, "items": list_analysis_frameworks(), "analysis_module": app.analysis_module_status()})
                    return
                if parsed.path == "/api/stock-news":
                    query = parse_qs(parsed.query)
                    try:
                        ts_code = normalize_ts_code(query.get("ts_code", query.get("code", [""]))[0])
                        app.record_stock_request(ts_code)
                        self._json({"ok": True, **app._stock_news_context(ts_code)})
                    except Exception as exc:  # noqa: BLE001 - readable UI error
                        self._json({"ok": False, "error": str(exc)}, status=404)
                    return
                if parsed.path == "/api/admin/overview":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.user_store.admin_overview(), "demo": self._demo_state()})
                    return
                if parsed.path == "/api/admin/archives":
                    if not self._require_admin():
                        return
                    query = parse_qs(parsed.query)
                    self._json({"ok": True, **app.user_store.admin_archives(query.get("q", [""])[0])})
                    return
                if parsed.path == "/api/admin/market-fetch/status":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **app.market_fetch_controller.status()})
                    return
                if parsed.path == "/api/admin/daily-market-scheduler":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **app.daily_market_scheduler.status()})
                    return
                if parsed.path == "/api/admin/idle-stock-prefetch":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **app.idle_stock_prefetch_scheduler.status()})
                    return
                if parsed.path == "/api/admin/market-fetch/logs":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    lines = max(20, min(500, int(query.get("lines", ["120"])[0] or 120)))
                    self._json({"ok": True, **app.market_fetch_controller.logs(lines=lines, source=query.get("source", [""])[0])})
                    return
                if parsed.path == "/api/admin/tasks":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, "items": app.task_registry.list_tasks()})
                    return
                if parsed.path == "/api/admin/ops/status":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, "snapshot": self._ops_snapshot()})
                    return
                if parsed.path == "/api/admin/data-random-audit":
                    if not self._require_admin():
                        return
                    query = parse_qs(parsed.query)
                    sample_size = max(1, min(200, int(query.get("sample_size", ["20"])[0] or 20)))
                    cold_read_samples = max(0, min(10, int(query.get("cold_read_samples", ["0"])[0] or 0)))
                    if self._is_readonly_admin_session():
                        cold_read_samples = 0
                    seed_text = str(query.get("seed", [""])[0] or "").strip()
                    seed = int(seed_text) if seed_text.isdigit() else None
                    config = build_ths_minute_config(database="market_data", collection="minute_day_buckets")
                    client = pymongo.MongoClient(config.mongo_uri, serverSelectionTimeoutMS=8000)
                    try:
                        payload = build_random_audit_payload(
                            client,
                            sample_size=sample_size,
                            seed=seed,
                            cold_read_samples=cold_read_samples,
                        )
                    finally:
                        client.close()
                    self._json({"ok": True, "audit": payload})
                    return
                if parsed.path == "/api/admin/data-random-audit/scheduler":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.data_random_audit_scheduler.status()})
                    return
                if parsed.path == "/api/admin/news-library":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **query_news_library(parse_qs(parsed.query))})
                    return
                if parsed.path == "/api/admin/news-library/refetch":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **app.news_refetch_controller.status()})
                    return
                if parsed.path == "/api/admin/news-crawler/status":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    limit = max(1, min(50, int(query.get("limit", ["12"])[0] or 12)))
                    failure_limit = max(1, min(500, int(query.get("failure_limit", ["200"])[0] or 200)))
                    self._json({"ok": True, **crawler_status_snapshot(limit=limit, failure_limit=failure_limit)})
                    return
                if parsed.path == "/api/admin/news-crawler/metrics":
                    if not self._require_data_console():
                        return
                    self._text(
                        news_crawler_prometheus_metrics(),
                        content_type="text/plain; version=0.0.4; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/admin/data-sources":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **data_source_snapshot(app.settings)})
                    return
                if parsed.path == "/api/admin/backend/registry":
                    if not self._require_admin():
                        return
                    self._json(
                        {
                            "ok": True,
                            "data_keys": data_key_snapshot(),
                            "fetch_methods": fetch_method_snapshot(),
                            "spider_sources": list(SPIDER_SOURCES),
                        }
                    )
                    return
                if parsed.path == "/api/admin/credentials":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **admin_credentials_snapshot(app.user_store)})
                    return
                if parsed.path == "/api/admin/kaipanla/features":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, "items": list_kaipanla_features()})
                    return
                if parsed.path == "/api/admin/kaipanla/validate":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **validate_kaipanla_integration()})
                    return
                if parsed.path == "/api/admin/kaipanla/scheduler":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **app.kaipanla_scheduler.status()})
                    return
                if parsed.path == "/api/admin/kaipanla/records":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    limit = max(1, min(500, int(query.get("limit", ["80"])[0] or 80)))
                    self._json({"ok": True, **list_kaipanla_records(limit=limit, feature=query.get("feature", [""])[0])})
                    return
                if parsed.path == "/api/admin/kaipanla/daily-overview":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    self._json({"ok": True, "overview": kaipanla_daily_overview(query.get("date", [""])[0])})
                    return
                if parsed.path == "/api/admin/kaipanla/record":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    self._json({"ok": True, "record": read_kaipanla_record(query.get("path", [""])[0])})
                    return
                if parsed.path == "/api/admin/data-library":
                    if not self._require_data_console():
                        return
                    self._json({"ok": True, **list_local_stock_summaries()})
                    return
                if parsed.path == "/api/admin/stock-storage-status":
                    if not self._require_data_console():
                        return
                    query = parse_qs(parsed.query)
                    page = max(1, int(query.get("page", ["1"])[0] or 1))
                    page_size = max(1, min(200, int(query.get("page_size", query.get("limit", ["40"]))[0] or 40)))
                    self._json(
                        {
                            "ok": True,
                            **stock_storage_status_snapshot(
                                limit=page_size,
                                query=query.get("q", [""])[0],
                                page=page,
                                page_size=page_size,
                                filter_key=query.get("filter", ["health_attention"])[0],
                                sort_key=query.get("sort", ["health"])[0],
                            ),
                        }
                    )
                    return
                if parsed.path == "/api/admin/data-distribution/status":
                    if not self._require_admin():
                        return
                    self._json(
                        {
                            "ok": DATA_DISTRIBUTION_AVAILABLE,
                            "available": DATA_DISTRIBUTION_AVAILABLE,
                            "reason": "" if DATA_DISTRIBUTION_AVAILABLE else "数据分发正在维护中，暂不可用。",
                        }
                    )
                    return
                if parsed.path == "/api/admin/agent-tokens":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, "items": app.user_store.list_agent_tokens()})
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
                if parsed.path.startswith("/api/agent/v1/"):
                    self._handle_agent_post(parsed)
                    return
                if parsed.path == "/api/login":
                    self._handle_login()
                    return
                if parsed.path == "/api/admin-login-entry":
                    self._handle_admin_login_entry()
                    return
                if parsed.path == "/api/logout":
                    self._handle_logout()
                    return
                if self._is_readonly_admin_session():
                    self._json({"ok": False, "error": "只读后台账号不能执行调用、保存或修改操作。"}, status=403)
                    return
                if parsed.path == "/api/register":
                    self._handle_register()
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
                if parsed.path == "/api/admin/credentials":
                    if not self._require_admin():
                        return
                    self._handle_admin_credentials()
                    return
                if parsed.path == "/api/admin/data-distribution/send":
                    if not self._require_admin():
                        return
                    if not DATA_DISTRIBUTION_AVAILABLE:
                        self._json({"ok": False, "error": "数据分发正在维护中，暂不可用。"}, status=503)
                        return
                    self._json({"ok": False, "error": "数据分发发送入口尚未接入。"}, status=501)
                    return
                if parsed.path == "/api/admin/agent-token":
                    if not self._require_admin():
                        return
                    if not AGENT_GATEWAY_AVAILABLE:
                        self._json({"ok": False, "error": "Agent Gateway 正在调试中，暂不可用。"}, status=503)
                        return
                    self._handle_admin_agent_token()
                    return
                if parsed.path == "/api/admin/agent-token/revoke":
                    if not self._require_admin():
                        return
                    if not AGENT_GATEWAY_AVAILABLE:
                        self._json({"ok": False, "error": "Agent Gateway 正在调试中，暂不可用。"}, status=503)
                        return
                    self._handle_admin_agent_token_revoke()
                    return
                if parsed.path == "/api/admin/user-access":
                    if not self._require_admin():
                        return
                    self._handle_admin_user_access()
                    return
                if parsed.path == "/api/admin/news-library/refetch":
                    if not self._require_admin():
                        return
                    self._handle_admin_news_refetch()
                    return
                if parsed.path == "/api/admin/news-library/translate":
                    if not self._require_admin():
                        return
                    self._handle_admin_news_translate()
                    return
                if parsed.path == "/api/admin/news-crawler/failure-action":
                    if not self._require_admin():
                        return
                    self._handle_admin_news_crawler_failure_action()
                    return
                if parsed.path == "/api/admin/demo-reset":
                    if not self._require_admin():
                        return
                    self._handle_admin_demo_reset()
                    return
                if parsed.path == "/api/admin/market-fetch/start":
                    if not self._require_admin():
                        return
                    self._handle_admin_spider_start()
                    return
                if parsed.path == "/api/admin/market-fetch/stop":
                    if not self._require_admin():
                        return
                    self._json({"ok": True, **app.market_fetch_controller.stop(self._read_json())})
                    return
                if parsed.path == "/api/admin/daily-market-scheduler":
                    if not self._require_admin():
                        return
                    self._handle_admin_daily_market_scheduler()
                    return
                if parsed.path == "/api/admin/idle-stock-prefetch":
                    if not self._require_admin():
                        return
                    self._handle_admin_idle_stock_prefetch()
                    return
                if parsed.path == "/api/admin/data-random-audit/scheduler":
                    if not self._require_admin():
                        return
                    self._handle_admin_data_random_audit_scheduler()
                    return
                if parsed.path == "/api/admin/stock-storage-repair":
                    if not self._require_admin():
                        return
                    self._handle_admin_stock_storage_repair()
                    return
                if parsed.path == "/api/admin/stock-storage-report":
                    if not self._require_admin():
                        return
                    self._handle_admin_stock_storage_report()
                    return
                if parsed.path == "/api/admin/kaipanla/run":
                    if not self._require_admin():
                        return
                    self._handle_admin_kaipanla_run()
                    return
                if parsed.path == "/api/admin/kaipanla/scheduler":
                    if not self._require_admin():
                        return
                    self._handle_admin_kaipanla_scheduler()
                    return
                if parsed.path == "/api/admin/data-sources":
                    if not self._require_admin():
                        return
                    self._handle_admin_data_sources()
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
                    one_time_code = str(payload.get("otp") or payload.get("totp") or payload.get("one_time_code") or "")
                    admin_challenge = str(payload.get("admin_challenge") or "")
                    account = self._authenticate(username, password, one_time_code, admin_challenge)
                    if not account:
                        self._json({"ok": False, "error": "账号或密码错误"}, status=401)
                        return
                    if account.get("role") == "admin" and admin_challenge:
                        app._consume_admin_login_challenge(admin_challenge)
                    self._login_account(account)
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=401)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_admin_login_entry(self) -> None:
                payload = self._read_json()
                username = str(payload.get("username") or "")
                password = str(payload.get("password") or "")
                if not (_secure_text_equal(username, "admin") and _secure_text_equal(password, "admin")):
                    self._json({"ok": False, "error": "管理员入口凭据错误"}, status=401)
                    return
                self._json({"ok": True, "admin_challenge": app._create_admin_login_challenge()})

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
                    if not app.settings.stock_analysis_execution_enabled:
                        self._json({"ok": False, "error": ANALYSIS_MODULE_STATUS_TEXT, "analysis_module": app.analysis_module_status()}, status=503)
                        return
                    payload = self._read_json()
                    if not self._require_data_fetch_approval("/api/multi-agent-analyze", payload):
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
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
                    from .agents import list_agent_runs

                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
                    analysis_type = str(payload.get("analysis_type") or "") or None
                    self._json({"ok": True, "ts_code": ts_code, "items": list_agent_runs(ts_code, analysis_type)})
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_read_agent_run(self) -> None:
                try:
                    from .agents import read_agent_run

                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
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

            def _handle_admin_credentials(self) -> None:
                payload = self._read_json()
                action = str(payload.get("action") or "save").strip()
                name = str(payload.get("name") or "").strip()
                session = self._current_session() or {}
                updated_by = session.get("username") or "admin"
                try:
                    if action == "delete":
                        delete_admin_credential(name, updated_by=updated_by, user_store=app.user_store)
                    elif action in {"save", "set"}:
                        value = str(payload.get("value") or "")
                        set_admin_credential(name, value, updated_by=updated_by, user_store=app.user_store)
                    else:
                        raise ValueError("未知凭据操作。")
                    self._json({"ok": True, **admin_credentials_snapshot(app.user_store)})
                except (KeyError, ValueError, PermissionError, RuntimeError, OSError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_agent_token(self) -> None:
                payload = self._read_json()
                session = self._current_session() or {}
                try:
                    token = app.user_store.issue_agent_token(
                        name=str(payload.get("name") or "agent"),
                        scopes=payload.get("scopes") or ["R"],
                        created_by=session.get("username") or "admin",
                        expires_in_days=int(payload.get("expires_in_days") or 30),
                        rate_limit_per_min=int(payload.get("rate_limit_per_min") or 60),
                    )
                    self._json({"ok": True, "agent_token": token, "warning": "token 明文只返回这一次，请保存到安全位置。"})
                except (TypeError, ValueError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_agent_token_revoke(self) -> None:
                payload = self._read_json()
                session = self._current_session() or {}
                try:
                    item = app.user_store.revoke_agent_token(str(payload.get("id") or ""), session.get("username") or "admin")
                    self._json({"ok": True, "agent_token": item})
                except KeyError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=404)

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
                        days = int(payload.get("days") or 0)
                        app.user_store.admin_set_disabled(username, True, session.get("username") or "admin", days=days)
                        app._remove_sessions_for_user(username)
                        self._json({"ok": True, **app.user_store.admin_overview()})
                        return
                    if action == "enable":
                        app.user_store.admin_set_disabled(username, False, session.get("username") or "admin")
                        self._json({"ok": True, **app.user_store.admin_overview()})
                        return
                    if action == "archive":
                        app.user_store.admin_archive_account(username, session.get("username") or "admin", str(payload.get("reason") or ""))
                        app._remove_sessions_for_user(username)
                        self._json({"ok": True, **app.user_store.admin_overview()})
                        return
                    self._json({"ok": False, "error": "未知用户操作。"}, status=400)
                except (KeyError, ValueError, PermissionError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_news_refetch(self) -> None:
                payload = self._read_json()
                if not self._require_data_fetch_approval("/api/admin/news-library/refetch", payload):
                    return
                try:
                    self._json({"ok": True, **app.news_refetch_controller.start(payload)})
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_news_translate(self) -> None:
                payload = self._read_json()
                if not self._require_data_fetch_approval("/api/admin/news-library/translate", payload):
                    return
                try:
                    article_id = str(payload.get("article_id") or "").strip()
                    if not article_id:
                        raise ValueError("缺少文章 ID。")
                    self._json({"ok": True, **guardian_translation_payload(article_id)})
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)
                except TranslationError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=502)

            def _handle_admin_news_crawler_failure_action(self) -> None:
                payload = self._read_json()
                if not self._require_data_fetch_approval("/api/admin/news-crawler/failure-action", payload):
                    return
                action = str(payload.get("action") or "retry").strip()
                session = self._current_session() or {}
                try:
                    if action != "retry":
                        self._json({"ok": False, "error": "未知失败 item 操作。"}, status=400)
                        return
                    self._json({"ok": True, **retry_failure_group(payload.get("item") or payload, actor=session.get("username") or "admin")})
                except (ValueError, RuntimeError) as exc:
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
                if not self._require_data_fetch_approval("/api/admin/market-fetch/start", payload):
                    return
                if self._reject_if_heavy_io_running("manual_market_fetch_full"):
                    return
                try:
                    result = app.market_fetch_controller.start(payload)
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
                        if not self._require_data_fetch_approval("/api/admin/daily-market-scheduler:run_now", payload):
                            return
                        self._json({"ok": True, **app.daily_market_scheduler.run_now()})
                        return
                    if action == "save":
                        enabled = bool(payload.get("enabled"))
                        schedule_time = str(payload.get("time") or "21:30").strip()
                        self._json({"ok": True, **app.daily_market_scheduler.configure(enabled=enabled, schedule_time=schedule_time)})
                        return
                    self._json({"ok": False, "error": "未知每日股票数据调度操作。"}, status=400)
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_idle_stock_prefetch(self) -> None:
                payload = self._read_json()
                action = str(payload.get("action") or "save").strip()
                try:
                    if action == "run_now":
                        if not self._require_data_fetch_approval("/api/sync-stock-data", payload):
                            return
                        self._json({"ok": True, **app.idle_stock_prefetch_scheduler.run_now()})
                        return
                    if action == "save":
                        app.idle_stock_prefetch_scheduler.configure(
                            enabled=bool(payload.get("enabled")),
                            idle_seconds=max(300, int(payload.get("idle_seconds") or app.settings.idle_stock_prefetch_seconds)),
                            minutes_enabled=payload.get("minutes_enabled"),
                            refresh_existing_days=payload.get("refresh_existing_days"),
                        )
                        self._json({"ok": True, **app.idle_stock_prefetch_scheduler.status()})
                        return
                    self._json({"ok": False, "error": "未知空闲股票预抓操作。"}, status=400)
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_data_random_audit_scheduler(self) -> None:
                payload = self._read_json()
                action = str(payload.get("action") or "save").strip()
                try:
                    if action == "run_now":
                        self._json({"ok": True, **app.data_random_audit_scheduler.run_now()})
                        return
                    if action == "save":
                        self._json(
                            {
                                "ok": True,
                                **app.data_random_audit_scheduler.configure(
                                    enabled=bool(payload.get("enabled")),
                                    idle_seconds=max(300, int(payload.get("idle_seconds") or 1800)),
                                    interval_seconds=max(1800, int(payload.get("interval_seconds") or 21600)),
                                    sample_size=max(1, min(200, int(payload.get("sample_size") or 20))),
                                    cold_read_samples=max(0, min(10, int(payload.get("cold_read_samples") or 0))),
                                ),
                            }
                        )
                        return
                    self._json({"ok": False, "error": "未知数据抽检调度操作。"}, status=400)
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_admin_stock_storage_repair(self) -> None:
                try:
                    payload = self._read_json()
                    if not self._require_data_fetch_approval("/api/admin/stock-storage-repair", payload):
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    max_daily_days = max(1, min(30, int(payload.get("max_daily_days") or 5)))
                    client = app.tushare if provider_available("tushare") and app.settings.tushare_token else _public_stock_client(app.settings)
                    self._json(repair_stock_storage_issue(client, ts_code, max_daily_days=max_daily_days))
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=400)
                except Exception as exc:  # noqa: BLE001 - repair failures should be visible in the admin page.
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_admin_stock_storage_report(self) -> None:
                try:
                    payload = self._read_json()
                    self._json({"ok": True, "report": report_stock_storage_issue({"source": "manual_api", "payload": payload})})
                except Exception as exc:  # noqa: BLE001 - keep the future report hook readable.
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_admin_kaipanla_run(self) -> None:
                try:
                    payload = self._read_json()
                    feature = str(payload.get("feature") or "").strip()
                    params = payload.get("params") or {}
                    save = payload.get("save", True) is not False
                    if not isinstance(params, dict):
                        self._json({"ok": False, "error": "开盘啦参数必须是 JSON object。"}, status=400)
                        return
                    self._json(run_kaipanla_feature(feature, params, save=save, run_id=timestamp()))
                except Exception as exc:  # noqa: BLE001 - keep admin page readable
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_admin_kaipanla_scheduler(self) -> None:
                try:
                    payload = self._read_json()
                    action = str(payload.get("action") or "save").strip()
                    if action == "run_now":
                        if not self._require_data_fetch_approval("/api/admin/kaipanla/scheduler:run_now", payload):
                            return
                        self._json({"ok": True, **app.kaipanla_scheduler.run_now()})
                        return
                    if action == "save":
                        features = payload.get("features") or []
                        params_by_feature = payload.get("params_by_feature") or {}
                        if not isinstance(features, list) or not isinstance(params_by_feature, dict):
                            self._json({"ok": False, "error": "开盘啦定时配置格式不正确。"}, status=400)
                            return
                        self._json({"ok": True, **app.kaipanla_scheduler.configure(
                            enabled=bool(payload.get("enabled")),
                            schedule_time=str(payload.get("time") or "21:45").strip(),
                            features=[str(item).strip() for item in features if str(item).strip()],
                            params_by_feature=params_by_feature,
                        )})
                        return
                    self._json({"ok": False, "error": "未知开盘啦调度操作。"}, status=400)
                except Exception as exc:  # noqa: BLE001 - keep admin page readable
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_admin_data_sources(self) -> None:
                try:
                    payload = self._read_json()
                    session = self._current_session() or {}
                    self._json({"ok": True, **configure_data_sources(payload, session.get("username") or "admin")})
                except Exception as exc:  # noqa: BLE001 - keep admin page readable
                    self._json({"ok": False, "error": str(exc)}, status=400)

            def _handle_analyze(self) -> None:
                try:
                    if not app.settings.stock_analysis_execution_enabled:
                        self._json({"ok": False, "error": ANALYSIS_MODULE_STATUS_TEXT, "analysis_module": app.analysis_module_status()}, status=503)
                        return
                    payload = self._read_json()
                    if not self._require_data_fetch_approval("/api/analyze", payload):
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
                    framework = get_analysis_framework(str(payload.get("analysis_type") or "value_speculation"))
                    years, full_history = self._parse_history_scope(payload)
                    question = str(payload.get("question") or framework.question)
                    deepseek_client = self._deepseek_for_session(require=True)
                    self._ensure_deepseek_ready(deepseek_client)
                    cached = app._recent_analysis_result(ts_code, framework.key)
                    if cached:
                        self._json(redact_local_paths(cached))
                        return
                    tushare_client = self._tushare_for_session()
                    if not self._consume_billable_budget("/api/analyze"):
                        return
                    if not stock_exists(ts_code):
                        sync_stock_data(tushare_client, ts_code, years=years, full_history=full_history)
                    local_dir = current_dir(ts_code)
                    analysis_dossier = read_current_analysis_dossier(ts_code, framework.key)
                    metadata = read_current_metadata(ts_code)
                    historical_context = analysis_review_context(
                        ts_code,
                        framework.key,
                        limit=app.settings.analysis_history_review_limit,
                    )

                    answer = ""
                    session_path = ""
                    from .analyst import StockAnalyst, session_path_for

                    analyst = StockAnalyst(deepseek_client)
                    session = session_path_for(ts_code, PROJECT_ROOT / "sessions", framework.key)
                    answer = analyst.framework_analysis(
                        analysis_dossier,
                        session,
                        framework,
                        question=question,
                        historical_context=historical_context,
                    )
                    output_path = analysis_output_path(ts_code, framework.key)
                    ensure_dir(output_path.parent)
                    output_path.write_text(answer, encoding="utf-8")
                    session_path = str(session)
                    self._record_billable_usage("/api/analyze")

                    self._json(
                        redact_local_paths({
                            "ok": True,
                            "ts_code": ts_code,
                            "analysis_type": framework.key,
                            "analysis_label": framework.label,
                            "output_dir": str(local_dir),
                            "local_dir": str(local_dir),
                            "dossier_path": str(local_dir / "dossier.json"),
                            "value_dossier_path": str(local_dir / "value_speculation_dossier.json"),
                            "analysis_dossier_path": f"mongodb://{STOCK_DATABASE}/{STOCK_COLLECTIONS['packages']}/{ts_code}/analysis_dossiers/{framework.key}",
                            "analysis_path": str(output_path) if answer else "",
                            "session_path": session_path,
                            "answer": answer,
                            "rating_hint": analysis_dossier.get("decision_helper", {}).get("rating_hint"),
                            "scores": analysis_dossier.get("decision_helper", {}).get("score_summary", {}),
                            "risk_flags": analysis_dossier.get("risk_flags", []),
                            "analysis_results": list_analysis_results(ts_code, framework.key),
                            "dataset_rows": metadata.get("dataset_rows", {}),
                            "fetch_errors": metadata.get("fetch_errors", []),
                        })
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
                    app.record_stock_request(ts_code)
                    analysis_type = str(payload.get("analysis_type") or "value_speculation")
                    snapshot_name = str(payload.get("snapshot_name") or "")
                    self._json(redact_local_paths(read_analysis_result(ts_code, analysis_type, snapshot_name=snapshot_name)))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_analysis_results(self) -> None:
                try:
                    payload = self._read_json()
                    if not app.settings.stock_analysis_execution_enabled:
                        self._json({"ok": False, "error": ANALYSIS_MODULE_STATUS_TEXT, "analysis_module": app.analysis_module_status()}, status=503)
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
                    analysis_type = str(payload.get("analysis_type") or "value_speculation")
                    framework = get_analysis_framework(analysis_type)
                    self._json(redact_local_paths({"ok": True, "ts_code": ts_code, "analysis_type": framework.key, "items": list_analysis_results(ts_code, framework.key)}))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_sync_stock_data(self) -> None:
                try:
                    payload = self._read_json()
                    if not self._require_data_fetch_approval("/api/sync-stock-data", payload):
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
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
                    self._json(redact_local_paths(result))
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_sync_ths_market_data(self) -> None:
                try:
                    payload = self._read_json()
                    if not self._require_data_fetch_approval("/api/sync-ths-market-data", payload):
                        return
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
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
                    error = ""
                    if not result.get("ok"):
                        failed = next((item for item in result.get("results", []) if not item.get("ok")), {})
                        error = str(failed.get("error") or "分钟行情更新失败")
                    self._json(redact_local_paths({"ok": result.get("ok", False), "error": error, "ts_code": ts_code, "market_result": result, **local_payload}))
                except PermissionError as exc:
                    self._json({"ok": False, "error": str(exc)}, status=403)
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_stock_status(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
                    self._json(redact_local_paths(stock_status(ts_code)))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_local_stock_data(self) -> None:
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    app.record_stock_request(ts_code)
                    self._json(redact_local_paths(build_local_stock_payload(ts_code)))
                except Exception as exc:  # noqa: BLE001 - return readable UI error
                    self._json({"ok": False, "error": str(exc)}, status=404)

            def _handle_agent_get(self, parsed) -> None:
                path = parsed.path
                if path == "/api/agent/v1/health":
                    payload = app.health_snapshot()
                    payload["agent_gateway"] = {
                        "ok": AGENT_GATEWAY_AVAILABLE,
                        "available": AGENT_GATEWAY_AVAILABLE,
                        "version": "v1",
                        "scopes": AGENT_SCOPE_LABELS,
                        "reason": "" if AGENT_GATEWAY_AVAILABLE else "Agent Gateway 正在调试中，暂不可用。",
                    }
                    self._json(payload)
                    return
                if path == "/api/agent/v1/openapi.json":
                    self._json(read_json(STATIC_DIR / "agent-openapi.json"))
                    return
                if not AGENT_GATEWAY_AVAILABLE:
                    self._json({"ok": False, "error": "Agent Gateway 正在调试中，暂不可用。"}, status=503)
                    return
                token = self._require_agent_scope("R", parsed)
                if not token:
                    return
                query = parse_qs(parsed.query)
                try:
                    if path == "/api/agent/v1/whoami":
                        self._agent_json(token, {"ok": True, "token": token, "scopes": token.get("scopes", [])}, "R")
                        return
                    if path == "/api/agent/v1/stocks/search":
                        q = query.get("q", [""])[0]
                        app.record_stock_request()
                        self._agent_json(token, {"ok": True, "items": app.index.search(q)}, "R")
                        return
                    prefix = "/api/agent/v1/stocks/"
                    if path.startswith(prefix):
                        rest = path[len(prefix):].strip("/")
                        code, _, action = rest.partition("/")
                        ts_code = normalize_ts_code(code)
                        app.record_stock_request(ts_code)
                        if action == "status":
                            self._agent_json(token, {"ok": True, **stock_status(ts_code)}, "R")
                            return
                        if action == "data":
                            self._agent_json(token, build_local_stock_payload(ts_code), "R")
                            return
                    if path == "/api/agent/v1/jobs":
                        limit = max(1, min(200, int(query.get("limit", ["50"])[0] or 50)))
                        items = app.agent_job_store.list(token_id=str(token.get("id") or ""), limit=limit)
                        self._agent_json(token, {"ok": True, "items": items, "count": len(items)}, "R")
                        return
                    jobs_prefix = "/api/agent/v1/jobs/"
                    if path.startswith(jobs_prefix):
                        remainder = path[len(jobs_prefix):].strip("/")
                        if remainder.endswith("/stream"):
                            job_id = remainder[: -len("/stream")].strip("/")
                            job = app._read_multi_agent_job(job_id)
                            owner = str(job.get("agent_token_id") or "")
                            if owner and owner != str(token.get("id") or ""):
                                app.user_store.record_agent_audit(token, path, "GET", "R", 403, {"reason": "job_owner_mismatch"})
                                self._json({"ok": False, "error": "无权读取该 Agent 任务。"}, status=403)
                                return
                            self._stream_agent_job(token, job_id)
                            return
                        job_id = remainder
                        job = app._read_multi_agent_job(job_id)
                        owner = str(job.get("agent_token_id") or "")
                        if owner and owner != str(token.get("id") or ""):
                            app.user_store.record_agent_audit(token, path, "GET", "R", 403, {"reason": "job_owner_mismatch"})
                            self._json({"ok": False, "error": "无权读取该 Agent 任务。"}, status=403)
                            return
                        self._agent_json(token, job, "R")
                        return
                    self._agent_json(token, {"ok": False, "error": "Agent endpoint not found"}, "R", status=404)
                except Exception as exc:  # noqa: BLE001 - readable agent error
                    app.user_store.record_agent_audit(token, path, "GET", "R", 500, {"error": str(exc)})
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _handle_agent_post(self, parsed) -> None:
                path = parsed.path
                if not AGENT_GATEWAY_AVAILABLE:
                    self._json({"ok": False, "error": "Agent Gateway 正在调试中，暂不可用。"}, status=503)
                    return
                if path != "/api/agent/v1/analysis-jobs":
                    token = self._require_agent_scope("R", parsed)
                    if token:
                        self._agent_json(token, {"ok": False, "error": "Agent endpoint not found"}, "R", status=404)
                    return
                token = self._require_agent_scope("B", parsed)
                if not token:
                    return
                idempotency_key = str(self.headers.get("Idempotency-Key") or "").strip()
                if not idempotency_key:
                    app.user_store.record_agent_audit(token, path, "POST", "B", 428, {"reason": "missing_idempotency_key"})
                    self._json({"ok": False, "error": "提交分析任务必须提供 Idempotency-Key。"}, status=428)
                    return
                replay = app.agent_idempotency_get(str(token.get("id") or ""), path, idempotency_key)
                if replay:
                    self._agent_json(token, {**replay, "duplicate": True}, "B", status=202)
                    return
                try:
                    payload = self._read_json()
                    ts_code = normalize_ts_code(str(payload.get("ts_code") or payload.get("code") or ""))
                    analysis_type = get_analysis_framework(str(payload.get("analysis_type") or "value_speculation")).key
                    system_key = app.user_store.decrypted_system_api_keys().get("deepseek", "")
                    if not system_key:
                        app.user_store.record_agent_audit(token, path, "POST", "B", 428, {"reason": "missing_system_deepseek"})
                        self._json({"ok": False, "error": "系统 DeepSeek key 未配置，无法启动 Agent 分析任务。"}, status=428)
                        return
                    job_payload = {
                        **payload,
                        "ts_code": ts_code,
                        "analysis_type": analysis_type,
                        "allow_dynamic_fetch": False,
                        "async": True,
                        "_agent_token_id": token.get("id", ""),
                        "_deepseek_client": DeepSeekClient(system_key, app.settings.deepseek_base_url, model=app.settings.deepseek_model),
                    }
                    result = app._start_multi_agent_job(job_payload)
                    result = {**result, "idempotency_key": idempotency_key, "agent_token_prefix": token.get("token_prefix", "")}
                    app.agent_idempotency_put(str(token.get("id") or ""), path, idempotency_key, result)
                    self._agent_json(token, result, "B", status=202)
                except Exception as exc:  # noqa: BLE001 - readable agent error
                    app.user_store.record_agent_audit(token, path, "POST", "B", 500, {"error": str(exc)})
                    self._json({"ok": False, "error": str(exc)}, status=500)

            def _agent_json(self, token: dict, payload: dict, scope: str, status: int = 200) -> None:
                app.user_store.record_agent_audit(token, self.path, self.command, scope, status, {})
                self._json(payload, status=status)

            def _stream_agent_job(self, token: dict, job_id: str) -> None:
                app.user_store.record_agent_audit(token, self.path, "GET", "R", 200, {"job_id": job_id, "transport": "sse"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last_progress_count = 0
                last_ping = time.monotonic()
                deadline = time.monotonic() + 300
                try:
                    initial = app._read_multi_agent_job(job_id)
                    self._write_sse("snapshot", initial)
                    last_progress_count = len(initial.get("progress") or [])
                    while time.monotonic() < deadline:
                        job = app._read_multi_agent_job(job_id)
                        progress = job.get("progress") or []
                        for event in progress[last_progress_count:]:
                            self._write_sse("progress", event)
                        last_progress_count = len(progress)
                        if job.get("status") in {"succeeded", "failed", "cancelled", "stopped"}:
                            self._write_sse("result", job)
                            return
                        if time.monotonic() - last_ping >= 15:
                            self._write_sse("ping", {"job_id": job_id, "time": timestamp()})
                            last_ping = time.monotonic()
                        time.sleep(1)
                    self._write_sse("timeout", {"job_id": job_id, "status": "timeout"})
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _write_sse(self, event: str, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str)
                self.wfile.write(f"event: {event}\ndata: {body}\n\n".encode("utf-8"))
                self.wfile.flush()

            def _require_agent_scope(self, scope: str, parsed) -> dict | None:
                raw_token = self._bearer_token()
                token = app.user_store.verify_agent_token(raw_token)
                if not token:
                    app.user_store.record_agent_audit(None, parsed.path, self.command, scope, 401, {"reason": "invalid_or_missing_token"})
                    self._json({"ok": False, "error": "Agent token 无效或已过期。"}, status=401)
                    return None
                if scope not in set(token.get("scopes") or []):
                    app.user_store.record_agent_audit(token, parsed.path, self.command, scope, 403, {"reason": "scope_denied"})
                    self._json({"ok": False, "error": f"Agent token 缺少 {scope} scope。"}, status=403)
                    return None
                if not app.agent_rate_allowed(token):
                    app.user_store.record_agent_audit(token, parsed.path, self.command, scope, 429, {"reason": "rate_limited"})
                    self._json({"ok": False, "error": "Agent token 请求过于频繁。"}, status=429)
                    return None
                return token

            def _bearer_token(self) -> str:
                header = self.headers.get("Authorization", "")
                parts = header.split()
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    return parts[1]
                return ""

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
                if not _is_admin_role(session.get("role")):
                    self._json({"ok": False, "error": "需要管理员权限"}, status=403)
                    return False
                return True

            def _ops_snapshot(self, *, include_crawler: bool = True) -> dict:
                return build_ops_snapshot(
                    PROJECT_ROOT,
                    crawler_snapshot_fn=(lambda: crawler_status_snapshot(limit=5, failure_limit=50)) if include_crawler else None,
                )

            def _reject_if_heavy_io_running(self, requested_task_id: str) -> bool:
                blockers = _public_heavy_io_blockers(
                    active_heavy_io_tasks(self._ops_snapshot(include_crawler=False)),
                    requested_task_id=requested_task_id,
                )
                if not blockers:
                    return False
                title = blockers[0].get("title") or "重 IO 任务"
                self._json(
                    {
                        "ok": False,
                        "error": f"已有重 IO 任务正在运行：{title}",
                        "blocking_tasks": blockers,
                    },
                    status=409,
                )
                return True

            def _require_data_console(self) -> bool:
                session = self._current_session()
                if not session:
                    self._json({"ok": False, "error": "请先登录"}, status=401)
                    return False
                if not _can_view_data_console(session.get("role")):
                    self._json({"ok": False, "error": "需要数据查看权限"}, status=403)
                    return False
                return True

            def _is_readonly_admin_session(self) -> bool:
                session = self._current_session()
                return bool(session and _is_readonly_admin_role(session.get("role")))

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
                if role == READONLY_ADMIN_ROLE:
                    return {"tier": READONLY_ADMIN_ROLE, "is_vip": False, "vip_until_text": "", "api_keys": {}}
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
                if not provider_available("tushare"):
                    return _public_stock_client(app.settings)
                session = self._current_session()
                mode = self._credential_mode(session)
                if mode == "system":
                    if not app.settings.tushare_token:
                        return _public_stock_client(app.settings)
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

            def _authenticate(
                self,
                username: str,
                password: str,
                one_time_code: str = "",
                admin_challenge: str = "",
            ) -> dict | None:
                if _secure_text_equal(username, app.settings.web_username) and _secure_text_equal(password, app.settings.web_password):
                    totp_secret = get_secret_store().get("web.admin_totp_secret")
                    if totp_secret:
                        if not verify_totp(totp_secret, one_time_code):
                            raise PermissionError("管理员一次性验证码错误或已过期。")
                    else:
                        raise PermissionError("管理员 Authenticator 尚未配置，请先运行 `.venv/bin/python -m stock_pipeline secrets setup-admin-totp`。")
                    return {"username": app.settings.web_username, "role": "admin"}
                readonly_account = _readonly_admin_account(app.settings, username, password)
                if readonly_account:
                    return readonly_account
                if app.user_store.verify_demo_account(username, password):
                    return {"username": username, "role": "demo", "managed_demo": True}
                user_account = app.user_store.authenticate_user(username, password)
                if user_account:
                    return user_account
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
                        "alerts": admin_runtime_alerts() if _is_admin_role(account.get("role")) else [],
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

            def _require_data_fetch_approval(self, action: str, payload) -> bool:
                if not app.settings.data_fetch_approval_required:
                    return True
                approved = False
                if isinstance(payload, dict):
                    approved = payload.get("approved") is True or str(payload.get("approved") or "").lower() in {"1", "true", "yes"}
                else:
                    values = payload.get("approved", []) if hasattr(payload, "get") else []
                    approved = any(str(item).lower() in {"1", "true", "yes"} for item in values)
                if not approved:
                    label = DATA_FETCH_ACTIONS.get(action, action)
                    self._json(
                        {
                            "ok": False,
                            "approval_required": True,
                            "approval_action": action,
                            "error": f"需要审批后才能执行：{label}",
                        },
                        status=428,
                    )
                    return False
                session = self._current_session() or {}
                app.user_store.record_audit_event(
                    session.get("username") or "anonymous",
                    "data_fetch_approved",
                    DATA_FETCH_ACTIONS.get(action, action),
                    {"action": action},
                )
                return True

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

            def _text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"前端已启动：http://{self.host}:{self.port}")
        print("按 Ctrl+C 停止服务。")
        server.serve_forever()


def serve_web(host: str = "127.0.0.1", port: int = 8765) -> None:
    StockWebApp(host=host, port=port).serve()


class TaskRegistry:
    def __init__(self, path: Path | None = None, max_items: int = 200):
        self.path = path
        self.max_items = max_items
        self.lock = threading.Lock()
        self.tasks: dict[str, dict] = self._load_tasks()
        self._mark_interrupted_tasks()

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
            self._write_locked()
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
            self._write_locked()

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
            self._write_locked()

    def list_tasks(self, limit: int = 80) -> list[dict]:
        with self.lock:
            items = sorted(self.tasks.values(), key=lambda item: item.get("updated_epoch", 0), reverse=True)[:limit]
            return json.loads(json.dumps(items, ensure_ascii=False, default=str))

    def get_task(self, task_id: str) -> dict | None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            return json.loads(json.dumps(task, ensure_ascii=False, default=str))

    def _trim_locked(self) -> None:
        if len(self.tasks) <= self.max_items:
            return
        ordered = sorted(self.tasks.values(), key=lambda item: item.get("updated_epoch", 0), reverse=True)
        keep = {item["task_id"] for item in ordered[: self.max_items]}
        for task_id in list(self.tasks):
            if task_id not in keep:
                self.tasks.pop(task_id, None)

    def _load_tasks(self) -> dict[str, dict]:
        if not self.path or not self.path.exists():
            return {}
        try:
            payload = read_json(self.path)
            items = payload.get("tasks", []) if isinstance(payload, dict) else payload
            return {
                str(item.get("task_id")): item
                for item in items
                if isinstance(item, dict) and item.get("task_id")
            }
        except Exception:
            return {}

    def _mark_interrupted_tasks(self) -> None:
        changed = False
        now = timestamp()
        now_epoch = time.time()
        for task in self.tasks.values():
            if task.get("status") not in {"queued", "running", "stopping"}:
                continue
            metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
            if metadata.get("queued_by") == QUEUE_OWNER:
                previous_status = str(task.get("status") or "")
                task["status"] = "queued"
                task["updated_at"] = now
                task["updated_epoch"] = now_epoch
                task_metadata = task.setdefault("metadata", {})
                task_metadata["queue_status"] = (
                    "recovering"
                    if previous_status in {"running", "stopping"}
                    else str(task_metadata.get("queue_status") or "queued")
                )
                task.setdefault("events", []).append(
                    {
                        "time": now,
                        "stage": "queued",
                        "message": "服务重启，队列任务保留，等待资源队列恢复或放弃。",
                        "details": {"previous_status": previous_status},
                    }
                )
                changed = True
                continue
            task["status"] = "failed"
            task["updated_at"] = now
            task["updated_epoch"] = now_epoch
            task["finished_at"] = now
            task["error"] = "服务重启，任务执行状态已中断。"
            task.setdefault("events", []).append(
                {"time": now, "stage": "failed", "message": "服务重启，任务执行状态已中断。", "details": {}}
            )
            changed = True
        if changed and self.path:
            ensure_dir(self.path.parent)
            write_json(self.path, {"version": 1, "tasks": list(self.tasks.values())})
            os.chmod(self.path, 0o600)

    def _write_locked(self) -> None:
        if not self.path:
            return
        ensure_dir(self.path.parent)
        write_json(self.path, {"version": 1, "tasks": list(self.tasks.values())})
        os.chmod(self.path, 0o600)

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
            "stock_list_count": result.get("stock_list_count", ""),
            "trigger": result.get("trigger", ""),
            "total": result.get("total", ""),
            "succeeded": result.get("succeeded", ""),
            "status": result.get("status", ""),
            "seed": result.get("seed", ""),
            "sample_size": result.get("sample_size", ""),
            "summary_status": (result.get("summary") or {}).get("status", "") if isinstance(result.get("summary"), dict) else "",
            "anomalies": (result.get("summary") or {}).get("anomalies", "") if isinstance(result.get("summary"), dict) else "",
        }


def _task_registry_status(task_registry: Any, task_id: str) -> str:
    if not task_id:
        return ""
    getter = getattr(task_registry, "get_task", None)
    if not callable(getter):
        return ""
    task = getter(task_id) or {}
    return str(task.get("status") or "")


def _task_registry_active(task_registry: Any, task_id: str) -> bool:
    return _task_registry_status(task_registry, task_id) in {"queued", "running", "stopping"}


class IdleStockPrefetchScheduler:
    def __init__(self, app: StockWebApp, config_path: Path, task_registry: TaskRegistry):
        self.app = app
        self.config_path = config_path
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.config = self._load_config()
        self.app.task_queue.register(
            "idle_stock_prefetch",
            lambda task_id, payload: self._run_task(task_id, str((payload or {}).get("trigger") or "queued")),
        )
        self.thread = threading.Thread(target=self._loop, name="idle-stock-prefetch-scheduler", daemon=True)
        self.thread.start()

    def configure(self, enabled: bool, idle_seconds: int, minutes_enabled: Any = None, refresh_existing_days: Any = None) -> dict:
        with self.lock:
            current_minutes_enabled = self.config.get("minutes_enabled", self.app.settings.idle_stock_prefetch_minutes_enabled)
            current_refresh_days = int(self.config.get("refresh_existing_days") or self.app.settings.idle_stock_prefetch_refresh_existing_days)
            self.config.update(
                {
                    "enabled": bool(enabled),
                    "idle_seconds": max(300, int(idle_seconds)),
                    "minutes_enabled": current_minutes_enabled if minutes_enabled is None else bool(minutes_enabled),
                    "refresh_existing_days": current_refresh_days if refresh_existing_days is None else max(0, int(refresh_existing_days)),
                    "full_history": True,
                    "updated_at": timestamp(),
                }
            )
            self._write_config_locked()
        return self.status()

    def run_now(self) -> dict:
        return self._start_run(trigger="manual")

    def status(self) -> dict:
        activity = self.app.stock_request_state()
        with self.lock:
            config = dict(self.config)
            task_status = _task_registry_status(self.task_registry, str(config.get("last_task_id") or ""))
            running = bool(self.worker and self.worker.is_alive()) or task_status == "running"
            queued = task_status == "queued"
        idle_seconds = int(config.get("idle_seconds") or self.app.settings.idle_stock_prefetch_seconds)
        remaining = max(0, idle_seconds - int(activity.get("idle_seconds") or 0))
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "idle_seconds": idle_seconds,
                "full_history": True,
                "minutes_enabled": bool(config.get("minutes_enabled", self.app.settings.idle_stock_prefetch_minutes_enabled)),
                "refresh_existing_days": int(config.get("refresh_existing_days") or self.app.settings.idle_stock_prefetch_refresh_existing_days),
                "running": running,
                "queued": queued,
                "last_request_at": activity.get("last_request_at") or "",
                "last_request_code": activity.get("last_request_code") or "",
                "current_idle_seconds": activity.get("idle_seconds") or 0,
                "remaining_seconds": remaining,
                "last_run_at": config.get("last_run_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "last_error": config.get("last_error") or "",
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(60):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    active = bool(self.worker and self.worker.is_alive()) or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or ""))
                    idle_seconds = int(self.config.get("idle_seconds") or self.app.settings.idle_stock_prefetch_seconds)
                if not enabled or active:
                    continue
                if int(self.app.stock_request_state().get("idle_seconds") or 0) < idle_seconds:
                    continue
                self._start_run(trigger="idle")
            except Exception as exc:  # noqa: BLE001 - background scheduler must keep ticking
                with self.lock:
                    self.config["last_error"] = str(exc)
                    self._write_config_locked()

    def _start_run(self, trigger: str) -> dict:
        with self.lock:
            if self.worker and self.worker.is_alive() or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or "")):
                raise RuntimeError("空闲股票预抓任务正在运行。")
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            self.config["last_task_id"] = task_id
            self._write_config_locked()
        self.task_registry.create_task(task_id, "idle_stock_prefetch", "空闲股票资料包预抓", metadata={"trigger": trigger})
        resource_level = QUEUE_HEAVY_IO if bool(self.config.get("minutes_enabled", self.app.settings.idle_stock_prefetch_minutes_enabled)) else QUEUE_NORMAL_IO
        self.app.task_queue.enqueue(
            task_id=task_id,
            handler_key="idle_stock_prefetch",
            kind="idle_stock_prefetch",
            title="空闲股票资料包预抓",
            payload={"trigger": trigger},
            resource_level=resource_level,
        )
        return self.status()

    def _run_task(self, task_id: str, trigger: str) -> None:
        ts_code = ""
        candidate_name = ""
        try:
            candidate = self._next_candidate()
            if not candidate:
                result = {"ok": True, "status": "skipped", "reason": "no_unfetched_stock", "trigger": trigger}
                self.task_registry.update_task(task_id, status="succeeded", result=result)
                self.task_registry.add_event(task_id, "succeeded", "没有找到尚未抓取详情的股票。", result)
                self._remember_result(result)
                return
            ts_code = str(candidate.get("ts_code") or "")
            candidate_name = str(candidate.get("name") or "")
            candidate_reason = str(candidate.get("reason") or "missing_package")
            force_refresh = candidate_reason == "stale_package"
            self.task_registry.add_event(
                task_id,
                "running",
                f"开始{'刷新' if force_refresh else '预抓'} {ts_code} 全量资料包。",
                {"ts_code": ts_code, "full_history": True, "reason": candidate_reason, "force": force_refresh},
            )
            self.app.task_queue.checkpoint(task_id, resource_level=QUEUE_NORMAL_IO, stage="stock_package_before_sync", details={"ts_code": ts_code})
            client = self.app.tushare if provider_available("tushare") and self.app.settings.tushare_token else _public_stock_client(self.app.settings)
            payload = sync_stock_data(
                client,
                ts_code,
                years=None,
                full_history=True,
                force=force_refresh,
                checkpoint=lambda details: self.app.task_queue.checkpoint(
                    task_id,
                    resource_level=QUEUE_NORMAL_IO,
                    stage=f"stock_package_{details.get('stage') or 'checkpoint'}",
                    details=details,
                ),
            )
            minutes_result = self._prefetch_minutes(ts_code, task_id)
            result = {
                "ok": True,
                "status": "succeeded",
                "trigger": trigger,
                "ts_code": ts_code,
                "name": candidate_name,
                "reason": candidate_reason,
                "full_history": True,
                "cache_hit": payload.get("cache_hit", False),
                "dataset_count": len(payload.get("datasets") or []),
                "minutes": minutes_result,
            }
            self.task_registry.update_task(task_id, status="succeeded", result=result)
            self.task_registry.add_event(task_id, "succeeded", f"空闲预抓完成：{ts_code}。", result)
            self._remember_result(result)
        except Exception as exc:  # noqa: BLE001 - keep task readable
            result = {
                "ok": False,
                "status": "failed",
                "trigger": trigger,
                "ts_code": ts_code,
                "name": candidate_name,
                "error": str(exc),
            }
            self.task_registry.update_task(task_id, status="failed", error=str(exc), result=result)
            self.task_registry.add_event(task_id, "failed", "空闲股票预抓失败。", result)
            self._remember_result(result)

    def _prefetch_minutes(self, ts_code: str, task_id: str) -> dict:
        minutes_enabled = bool(self.config.get("minutes_enabled", self.app.settings.idle_stock_prefetch_minutes_enabled))
        if not minutes_enabled:
            return {"ok": True, "status": "skipped", "reason": "minutes_disabled"}

        source = os.getenv("MARKET_MINUTE_DEFAULT_SOURCE", "pytdx_history")
        pages = os.getenv("MARKET_MINUTE_DEFAULT_PAGES", "all")
        page_size = int(os.getenv("MARKET_MINUTE_DEFAULT_PAGE_SIZE", "800"))
        self.task_registry.add_event(
            task_id,
            "running",
            f"开始补抓 {ts_code} 分钟行情。",
            {"ts_code": ts_code, "source": source, "pages": pages, "page_size": page_size},
        )
        try:
            self.app.task_queue.checkpoint(task_id, resource_level=QUEUE_HEAVY_IO, stage="minute_prefetch_before_fetch", details={"ts_code": ts_code})
            result = fetch_and_store_minutes(
                [ts_code],
                config=build_ths_minute_config(),
                sleep_range=(0, 0),
                source=source,
                pages=pages,
                page_size=page_size,
                checkpoint=lambda details: self.app.task_queue.checkpoint(
                    task_id,
                    resource_level=QUEUE_HEAVY_IO,
                    stage=f"minute_prefetch_{details.get('stage') or 'checkpoint'}",
                    details=details,
                ),
            )
            item = next((row for row in result.get("results", []) if row.get("ts_code") == ts_code), {})
            summary = {
                "ok": bool(result.get("ok")),
                "status": "succeeded" if result.get("ok") else "failed",
                "source": result.get("source") or source,
                "dataset": item.get("dataset") or "",
                "rows": int(item.get("rows") or 0),
                "stored_rows": int(item.get("stored_rows") or 0),
                "inserted": int(item.get("inserted") or 0),
                "updated": int(item.get("updated") or 0),
                "skipped_days": int(item.get("skipped_days") or 0),
                "failed_days": int(item.get("failed_days") or 0),
                "date_range": item.get("date_range") or {},
                "error": str(item.get("error") or ""),
            }
            if summary["ok"]:
                self.task_registry.add_event(task_id, "running", f"分钟行情补抓完成：{summary['stored_rows']} 行。", summary)
            else:
                self.task_registry.add_event(task_id, "warning", "分钟行情补抓失败，资料包预抓结果保留。", summary)
            return summary
        except Exception as exc:  # noqa: BLE001 - minutes are useful but must not fail the whole dossier prefetch
            summary = {"ok": False, "status": "failed", "source": source, "error": str(exc)}
            self.task_registry.add_event(task_id, "warning", "分钟行情补抓失败，资料包预抓结果保留。", summary)
            return summary

    def _next_candidate(self) -> dict | None:
        rows = self.app.index.stocks(refresh=False)
        recent_failed = self._recent_failed_codes()
        stale_candidates: list[dict[str, Any]] = []
        refresh_days = int(self.config.get("refresh_existing_days") or self.app.settings.idle_stock_prefetch_refresh_existing_days)
        refresh_seconds = refresh_days * 86400 if refresh_days > 0 else 0
        metadata_by_code = {str(item.get("ts_code") or ""): item for item in list_local_stock_summaries().get("items", [])}
        for row in rows:
            ts_code = str(row.get("ts_code") or "")
            if not ts_code or ts_code in recent_failed:
                continue
            try:
                normalized = normalize_ts_code(ts_code)
            except ValueError:
                continue
            if not stock_exists(normalized):
                return {**row, "ts_code": normalized, "reason": "missing_package"}
            if refresh_seconds:
                metadata = metadata_by_code.get(normalized) or {}
                age = _stock_metadata_age_seconds(str(metadata.get("updated_at") or ""))
                if age is None or age >= refresh_seconds:
                    stale_candidates.append({**row, "ts_code": normalized, "reason": "stale_package", "package_age_seconds": age})
        if stale_candidates:
            stale_candidates.sort(key=lambda item: int(item.get("package_age_seconds") if item.get("package_age_seconds") is not None else 10**12), reverse=True)
            return stale_candidates[0]
        return None

    def _recent_failed_codes(self) -> set[str]:
        attempts = self.config.get("attempts") or {}
        cutoff = time.time() - 86400
        blocked = set()
        if not isinstance(attempts, dict):
            return blocked
        for ts_code, item in attempts.items():
            if not isinstance(item, dict):
                continue
            if item.get("status") == "failed" and float(item.get("epoch") or 0) >= cutoff:
                blocked.add(str(ts_code))
        return blocked

    def _remember_result(self, result: dict) -> None:
        with self.lock:
            self.config["last_run_at"] = timestamp()
            self.config["last_result"] = result
            self.config["last_error"] = "" if result.get("ok") else str(result.get("error") or "空闲预抓失败")
            ts_code = str(result.get("ts_code") or "")
            if ts_code:
                attempts = self.config.setdefault("attempts", {})
                attempts[ts_code] = {"status": result.get("status"), "epoch": time.time(), "time": timestamp()}
                if len(attempts) > 500:
                    keep = sorted(attempts.items(), key=lambda item: float((item[1] or {}).get("epoch") or 0), reverse=True)[:500]
                    self.config["attempts"] = dict(keep)
            self._write_config_locked()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                if isinstance(data, dict):
                    data["enabled"] = data.get("enabled", self.app.settings.idle_stock_prefetch_enabled) is not False
                    data["idle_seconds"] = max(300, int(data.get("idle_seconds") or self.app.settings.idle_stock_prefetch_seconds))
                    data["minutes_enabled"] = data.get("minutes_enabled", self.app.settings.idle_stock_prefetch_minutes_enabled) is not False
                    data["refresh_existing_days"] = max(0, int(data.get("refresh_existing_days") or self.app.settings.idle_stock_prefetch_refresh_existing_days))
                    data["full_history"] = True
                    data.setdefault("last_result", {})
                    return data
            except Exception:
                pass
        return {
            "enabled": bool(self.app.settings.idle_stock_prefetch_enabled),
            "idle_seconds": max(300, int(self.app.settings.idle_stock_prefetch_seconds)),
            "minutes_enabled": bool(self.app.settings.idle_stock_prefetch_minutes_enabled),
            "refresh_existing_days": max(0, int(self.app.settings.idle_stock_prefetch_refresh_existing_days)),
            "full_history": True,
            "last_run_at": "",
            "last_task_id": "",
            "last_result": {},
            "last_error": "",
            "attempts": {},
        }

    def _write_config_locked(self) -> None:
        write_json(self.config_path, self.config)


class DataRandomAuditScheduler:
    def __init__(self, app: StockWebApp, config_path: Path, task_registry: TaskRegistry):
        self.app = app
        self.config_path = config_path
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.config = self._load_config()
        self.app.task_queue.register(
            "data_random_audit",
            lambda task_id, payload: self._run_task(
                task_id,
                str((payload or {}).get("trigger") or "queued"),
                max(1, min(200, int((payload or {}).get("sample_size") or 20))),
                max(0, min(10, int((payload or {}).get("cold_read_samples") or 0))),
            ),
        )
        self.thread = threading.Thread(target=self._loop, name="data-random-audit-scheduler", daemon=True)
        self.thread.start()

    def configure(self, enabled: bool, idle_seconds: int, interval_seconds: int, sample_size: int, cold_read_samples: int) -> dict:
        with self.lock:
            self.config.update(
                {
                    "enabled": bool(enabled),
                    "idle_seconds": max(300, int(idle_seconds)),
                    "interval_seconds": max(1800, int(interval_seconds)),
                    "sample_size": max(1, min(200, int(sample_size))),
                    "cold_read_samples": max(0, min(10, int(cold_read_samples))),
                    "updated_at": timestamp(),
                }
            )
            self._write_config_locked()
        return self.status()

    def run_now(self) -> dict:
        return self._start_run(trigger="manual")

    def status(self) -> dict:
        activity = self.app.stock_request_state()
        with self.lock:
            config = dict(self.config)
            task_status = _task_registry_status(self.task_registry, str(config.get("last_task_id") or ""))
            running = bool(self.worker and self.worker.is_alive()) or task_status == "running"
            queued = task_status == "queued"
        idle_seconds = int(config.get("idle_seconds") or 1800)
        interval_seconds = int(config.get("interval_seconds") or 21600)
        last_run_epoch = float(config.get("last_run_epoch") or 0)
        since_last_run = max(0, int(time.time() - last_run_epoch)) if last_run_epoch else 0
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "idle_seconds": idle_seconds,
                "interval_seconds": interval_seconds,
                "sample_size": max(1, min(200, int(config.get("sample_size") or 20))),
                "cold_read_samples": max(0, min(10, int(config.get("cold_read_samples") or 0))),
                "running": running,
                "queued": queued,
                "last_request_at": activity.get("last_request_at") or "",
                "current_idle_seconds": activity.get("idle_seconds") or 0,
                "remaining_idle_seconds": max(0, idle_seconds - int(activity.get("idle_seconds") or 0)),
                "since_last_run_seconds": since_last_run,
                "remaining_interval_seconds": max(0, interval_seconds - since_last_run) if last_run_epoch else 0,
                "last_run_at": config.get("last_run_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "last_error": config.get("last_error") or "",
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(60):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    active = bool(self.worker and self.worker.is_alive()) or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or ""))
                    idle_seconds = int(self.config.get("idle_seconds") or 1800)
                    interval_seconds = int(self.config.get("interval_seconds") or 21600)
                    last_run_epoch = float(self.config.get("last_run_epoch") or 0)
                if not enabled or active:
                    continue
                if int(self.app.stock_request_state().get("idle_seconds") or 0) < idle_seconds:
                    continue
                if last_run_epoch and time.time() - last_run_epoch < interval_seconds:
                    continue
                self._start_run(trigger="idle")
            except Exception as exc:  # noqa: BLE001 - background scheduler must keep ticking
                with self.lock:
                    self.config["last_error"] = str(exc)
                    self._write_config_locked()

    def _start_run(self, trigger: str) -> dict:
        with self.lock:
            if self.worker and self.worker.is_alive() or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or "")):
                raise RuntimeError("数据随机抽检任务正在运行。")
            sample_size = max(1, min(200, int(self.config.get("sample_size") or 20)))
            cold_read_samples = max(0, min(10, int(self.config.get("cold_read_samples") or 0)))
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            self.config["last_task_id"] = task_id
            self._write_config_locked()
        self.task_registry.create_task(
            task_id,
            "data_random_audit",
            "数据随机抽检",
            metadata={"trigger": trigger, "sample_size": sample_size, "cold_read_samples": cold_read_samples},
        )
        self.app.task_queue.enqueue(
            task_id=task_id,
            handler_key="data_random_audit",
            kind="data_random_audit",
            title="数据随机抽检",
            payload={"trigger": trigger, "sample_size": sample_size, "cold_read_samples": cold_read_samples},
            resource_level=QUEUE_NORMAL_IO,
        )
        return self.status()

    def _run_task(self, task_id: str, trigger: str, sample_size: int, cold_read_samples: int) -> None:
        client = None
        try:
            if trigger != "manual" and self._heavy_io_blockers(task_id):
                result = {"ok": True, "status": "skipped", "reason": "heavy_io_running", "trigger": trigger}
                self.task_registry.update_task(task_id, status="succeeded", result=result)
                self.task_registry.add_event(task_id, "succeeded", "检测到重 IO 任务，本轮抽检已跳过。", result)
                self._remember_result(result)
                return
            config = build_ths_minute_config(database="market_data", collection="minute_day_buckets")
            client = pymongo.MongoClient(config.mongo_uri, serverSelectionTimeoutMS=8000)
            self.app.task_queue.checkpoint(task_id, resource_level=QUEUE_NORMAL_IO, stage="data_random_audit_before_build", details={"sample_size": sample_size})

            def progress(message: str) -> None:
                self.task_registry.add_event(task_id, "running", str(message), {})
                self.app.task_queue.checkpoint(task_id, resource_level=QUEUE_NORMAL_IO, stage="data_random_audit_progress", details={"message": str(message)})

            payload = build_random_audit_payload(
                client,
                sample_size=sample_size,
                cold_read_samples=cold_read_samples,
                progress=progress,
            )
            summary = payload.get("summary") or {}
            status = "succeeded" if payload.get("ok") else "failed"
            result = {
                "ok": bool(payload.get("ok")),
                "status": status,
                "trigger": trigger,
                "generated_at": payload.get("generated_at") or "",
                "seed": payload.get("seed") or "",
                "sample_size": payload.get("sample_size") or sample_size,
                "cold_read_samples": payload.get("cold_read_samples") or cold_read_samples,
                "summary": summary,
            }
            self.task_registry.update_task(task_id, status=status, error="" if payload.get("ok") else "数据抽检发现危险项。", result=result)
            self.task_registry.add_event(task_id, status, f"数据抽检完成：{summary.get('status', 'unknown')}，异常 {summary.get('anomalies', 0)} 个。", result)
            self._remember_result(result)
        except Exception as exc:  # noqa: BLE001 - keep task readable
            result = {"ok": False, "status": "failed", "trigger": trigger, "error": str(exc)}
            self.task_registry.update_task(task_id, status="failed", error=str(exc), result=result)
            self.task_registry.add_event(task_id, "failed", "数据随机抽检失败。", result)
            self._remember_result(result)
        finally:
            if client is not None:
                client.close()

    def _heavy_io_blockers(self, requested_task_id: str) -> list[dict]:
        return self.app._running_heavy_io_blockers(requested_task_id)

    def _remember_result(self, result: dict) -> None:
        with self.lock:
            self.config["last_run_at"] = timestamp()
            self.config["last_run_epoch"] = time.time()
            self.config["last_result"] = result
            self.config["last_error"] = "" if result.get("ok") else str(result.get("error") or "数据随机抽检失败")
            self._write_config_locked()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                if isinstance(data, dict):
                    data["enabled"] = data.get("enabled", False) is True
                    data["idle_seconds"] = max(300, int(data.get("idle_seconds") or 1800))
                    data["interval_seconds"] = max(1800, int(data.get("interval_seconds") or 21600))
                    data["sample_size"] = max(1, min(200, int(data.get("sample_size") or 20)))
                    data["cold_read_samples"] = max(0, min(10, int(data.get("cold_read_samples") or 0)))
                    data.setdefault("last_result", {})
                    return data
            except Exception:
                pass
        return {
            "enabled": False,
            "idle_seconds": 1800,
            "interval_seconds": 21600,
            "sample_size": 20,
            "cold_read_samples": 0,
            "last_run_at": "",
            "last_run_epoch": 0,
            "last_task_id": "",
            "last_result": {},
            "last_error": "",
        }

    def _write_config_locked(self) -> None:
        write_json(self.config_path, self.config)


def _stock_storage_cold_compare_sample_count(value: Any) -> int:
    raw = 1 if value in (None, "") else value
    return max(0, min(10, int(raw)))


class StockStorageHealthScheduler:
    def __init__(self, app: StockWebApp, config_path: Path, task_registry: TaskRegistry):
        self.app = app
        self.config_path = config_path
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.config = self._load_config()
        self.app.task_queue.register(
            "stock_storage_health",
            lambda task_id, payload: self._run_task(
                task_id,
                str((payload or {}).get("trigger") or "queued"),
                max(1, min(200, int((payload or {}).get("sample_size") or 30))),
                _stock_storage_cold_compare_sample_count((payload or {}).get("cold_compare_samples")),
            ),
        )
        self.thread = threading.Thread(target=self._loop, name="stock-storage-health-scheduler", daemon=True)
        self.thread.start()

    def status(self) -> dict:
        with self.lock:
            config = dict(self.config)
            task_status = _task_registry_status(self.task_registry, str(config.get("last_task_id") or ""))
            running = bool(self.worker and self.worker.is_alive()) or task_status == "running"
            queued = task_status == "queued"
        now = time.time()
        next_run_epoch = float(config.get("next_run_epoch") or 0)
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "idle_seconds": int(config.get("idle_seconds") or 900),
                "min_interval_seconds": int(config.get("min_interval_seconds") or 1800),
                "max_interval_seconds": int(config.get("max_interval_seconds") or 7200),
                "sample_size": max(1, min(200, int(config.get("sample_size") or 30))),
                "cold_compare_samples": _stock_storage_cold_compare_sample_count(config.get("cold_compare_samples")),
                "running": running,
                "queued": queued,
                "next_run_at": config.get("next_run_at") or "",
                "remaining_next_run_seconds": max(0, int(next_run_epoch - now)) if next_run_epoch else 0,
                "last_run_at": config.get("last_run_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "last_error": config.get("last_error") or "",
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(60):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    active = bool(self.worker and self.worker.is_alive()) or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or ""))
                    idle_seconds = int(self.config.get("idle_seconds") or 900)
                    next_run_epoch = float(self.config.get("next_run_epoch") or 0)
                    if enabled and not next_run_epoch:
                        self._schedule_next_locked()
                        next_run_epoch = float(self.config.get("next_run_epoch") or 0)
                if not enabled or active:
                    continue
                if int(self.app.stock_request_state().get("idle_seconds") or 0) < idle_seconds:
                    continue
                if next_run_epoch and time.time() < next_run_epoch:
                    continue
                self._start_run(trigger="idle")
            except Exception as exc:  # noqa: BLE001 - background scheduler must keep ticking
                with self.lock:
                    self.config["last_error"] = str(exc)
                    self._schedule_next_locked(short=True)
                    self._write_config_locked()

    def _start_run(self, trigger: str) -> dict:
        with self.lock:
            if self.worker and self.worker.is_alive() or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or "")):
                raise RuntimeError("股票存储健康检查正在运行。")
            sample_size = max(1, min(200, int(self.config.get("sample_size") or 30)))
            cold_compare_samples = _stock_storage_cold_compare_sample_count(self.config.get("cold_compare_samples"))
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            self.config["last_task_id"] = task_id
            self._write_config_locked()
        self.task_registry.create_task(
            task_id,
            "stock_storage_health",
            "股票存储健康检查",
            metadata={"trigger": trigger, "sample_size": sample_size, "cold_compare_samples": cold_compare_samples},
        )
        self.app.task_queue.enqueue(
            task_id=task_id,
            handler_key="stock_storage_health",
            kind="stock_storage_health",
            title="股票存储健康检查",
            payload={"trigger": trigger, "sample_size": sample_size, "cold_compare_samples": cold_compare_samples},
            resource_level=QUEUE_NORMAL_IO,
        )
        return self.status()

    def _run_task(self, task_id: str, trigger: str, sample_size: int, cold_compare_samples: int) -> None:
        try:
            if trigger != "manual" and self._heavy_io_blockers(task_id):
                result = {"ok": True, "status": "skipped", "reason": "heavy_io_running", "trigger": trigger}
                self.task_registry.update_task(task_id, status="succeeded", result=result)
                self.task_registry.add_event(task_id, "succeeded", "检测到重 IO 任务，本轮股票存储健康检查已跳过。", result)
                self._remember_result(result)
                return
            result = run_stock_storage_health_check(
                sample_size=sample_size,
                cold_compare_samples=cold_compare_samples,
                checkpoint=lambda details: self.app.task_queue.checkpoint(
                    task_id,
                    resource_level=QUEUE_NORMAL_IO,
                    stage=f"stock_storage_health_{details.get('stage') or 'checkpoint'}",
                    details=details,
                ),
            )
            status = "succeeded" if result.get("ok") else "failed"
            self.task_registry.update_task(task_id, status=status, error="" if result.get("ok") else str(result.get("error") or ""), result=result)
            self.task_registry.add_event(
                task_id,
                status,
                f"股票存储健康检查完成：抽样 {result.get('checked_count', 0)} 只，异常 {result.get('abnormal_count', 0)} 只。",
                result,
            )
            self._remember_result(result)
        except Exception as exc:  # noqa: BLE001 - keep task readable
            result = {"ok": False, "status": "failed", "trigger": trigger, "error": str(exc)}
            self.task_registry.update_task(task_id, status="failed", error=str(exc), result=result)
            self.task_registry.add_event(task_id, "failed", "股票存储健康检查失败。", result)
            self._remember_result(result)

    def _heavy_io_blockers(self, requested_task_id: str) -> list[dict]:
        return self.app._running_heavy_io_blockers(requested_task_id)

    def _remember_result(self, result: dict) -> None:
        with self.lock:
            self.config["last_run_at"] = timestamp()
            self.config["last_run_epoch"] = time.time()
            self.config["last_result"] = result
            self.config["last_error"] = "" if result.get("ok") else str(result.get("error") or "股票存储健康检查失败")
            self._schedule_next_locked()
            self._write_config_locked()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                if isinstance(data, dict):
                    data["enabled"] = data.get("enabled", True) is True
                    data["idle_seconds"] = max(300, int(data.get("idle_seconds") or 900))
                    data["min_interval_seconds"] = max(900, int(data.get("min_interval_seconds") or 1800))
                    data["max_interval_seconds"] = max(data["min_interval_seconds"], int(data.get("max_interval_seconds") or 7200))
                    data["sample_size"] = max(1, min(200, int(data.get("sample_size") or 30)))
                    data["cold_compare_samples"] = _stock_storage_cold_compare_sample_count(data.get("cold_compare_samples"))
                    data.setdefault("last_result", {})
                    if data["enabled"] and not data.get("next_run_epoch"):
                        self.config = data
                        self._schedule_next_locked()
                        self._write_config_locked()
                        data = self.config
                    return data
            except Exception:
                pass
        config = {
            "enabled": True,
            "idle_seconds": 900,
            "min_interval_seconds": 1800,
            "max_interval_seconds": 7200,
            "sample_size": 30,
            "cold_compare_samples": 1,
            "last_run_at": "",
            "last_run_epoch": 0,
            "next_run_at": "",
            "next_run_epoch": 0,
            "last_task_id": "",
            "last_result": {},
            "last_error": "",
        }
        self.config = config
        self._schedule_next_locked()
        self._write_config_locked()
        return config

    def _schedule_next_locked(self, short: bool = False) -> None:
        if short:
            delay = random.randint(300, 900)
        else:
            minimum = max(900, int(self.config.get("min_interval_seconds") or 1800))
            maximum = max(minimum, int(self.config.get("max_interval_seconds") or 7200))
            delay = random.randint(minimum, maximum)
        next_epoch = time.time() + delay
        self.config["next_run_epoch"] = next_epoch
        self.config["next_run_at"] = datetime.fromtimestamp(next_epoch).strftime("%Y%m%d_%H%M%S")

    def _write_config_locked(self) -> None:
        write_json(self.config_path, self.config)


class DailyMarketScheduler:
    def __init__(self, app: StockWebApp, config_path: Path, task_registry: TaskRegistry):
        self.app = app
        self.config_path = config_path
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.config = self._load_config()
        self.app.task_queue.register(
            "daily_market",
            lambda task_id, payload: self._run_task(
                task_id,
                str((payload or {}).get("target_date") or today_yyyymmdd()),
                str((payload or {}).get("trigger") or "queued"),
                dict((payload or {}).get("resume_checkpoint") or {}),
                str((payload or {}).get("_queue_attempt_id") or ""),
            ),
            handler_version=2,
        )
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
            task_status = _task_registry_status(self.task_registry, str(config.get("last_task_id") or ""))
            running = bool(self.worker and self.worker.is_alive()) or task_status == "running"
            queued = task_status == "queued"
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "time": config.get("time") or "21:30",
                "last_run_date": config.get("last_run_date") or "",
                "last_run_at": config.get("last_run_at") or "",
                "last_target_date": config.get("last_target_date") or "",
                "last_target_reason": config.get("last_target_reason") or "",
                "last_started_at": config.get("last_started_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "running": running,
                "queued": queued,
                "stock_count": len(list_local_stock_codes()),
                "stock_list_count": (config.get("last_result") or {}).get("stock_list_count"),
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(30):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    schedule_time = str(self.config.get("time") or "21:30")
                    last_run_date = str(self.config.get("last_run_date") or "")
                    active = bool(self.worker and self.worker.is_alive()) or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or ""))
                if not enabled or active:
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
            if self.worker and self.worker.is_alive() or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or "")):
                raise RuntimeError("每日股票数据更新任务正在运行。")
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            target_info = choose_daily_market_target()
            target_date = str(target_info.get("target_date") or today_yyyymmdd())
            self.config["last_task_id"] = task_id
            self.config["last_target_date"] = target_date
            self.config["last_target_reason"] = target_info.get("reason") or ""
            self.config["last_started_at"] = timestamp()
            self._write_config_locked()
        self.task_registry.create_task(
            task_id,
            "daily_market",
            "每日股票数据更新",
            metadata={"trigger": trigger, "target_date": target_date, "target_reason": target_info.get("reason") or ""},
        )
        self.app.task_queue.enqueue(
            task_id=task_id,
            handler_key="daily_market",
            kind="daily_market",
            title="每日股票数据更新",
            payload={"trigger": trigger, "target_date": target_date},
            resource_level=QUEUE_HEAVY_IO,
        )
        return self.status()

    def _run_task(
        self,
        task_id: str,
        target_date: str,
        trigger: str,
        resume_checkpoint: dict[str, Any] | None = None,
        queue_attempt_id: str = "",
    ) -> None:
        try:
            client = _public_stock_client(self.app.settings)
            stock_list = self.app.index.stocks(refresh=False)
            if not stock_list:
                raise RuntimeError("本地股票列表为空，无法执行每日股票数据更新。请先同步至少一只股票资料包。")
            self.task_registry.add_event(
                task_id,
                "running",
                f"股票基础列表刷新完成，共 {len(stock_list)} 只。",
                {"stock_list_count": len(stock_list)},
            )
            result = sync_daily_market_for_existing_stocks(
                client,
                target_date=target_date,
                resume_checkpoint=resume_checkpoint or None,
                checkpoint=lambda details: self.app.task_queue.checkpoint(
                    task_id,
                    resource_level=QUEUE_HEAVY_IO,
                    stage=f"daily_market_{details.get('stage') or 'checkpoint'}",
                    details=details,
                    yield_on_pressure=True,
                ),
            )
            result["stock_list_count"] = len(stock_list)
            result["trigger"] = trigger
            if queue_attempt_id and not self.app.task_queue.is_attempt_active(task_id, queue_attempt_id):
                return
            self.task_registry.update_task(task_id, status="succeeded", result=result)
            self.task_registry.add_event(
                task_id,
                "succeeded",
                f"每日股票数据更新完成：列表 {result.get('stock_list_count')}，行情更新 {result.get('updated')}，跳过 {result.get('skipped')}，无数据 {result.get('no_data')}，失败 {result.get('failed')}。",
                result,
            )
            with self.lock:
                self.config["last_run_date"] = target_date
                self.config["last_run_at"] = timestamp()
                self.config["last_result"] = result
                self.config["last_error"] = ""
                self._write_config_locked()
        except QueueTaskDeferred:
            raise
        except Exception as exc:  # noqa: BLE001 - report task failure
            if queue_attempt_id and not self.app.task_queue.is_attempt_active(task_id, queue_attempt_id):
                return
            self.task_registry.update_task(task_id, status="failed", error=str(exc))
            self.task_registry.add_event(task_id, "failed", "每日股票数据更新失败。", {"error": str(exc)})
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


class KaipanlaScheduler:
    def __init__(self, config_path: Path, task_registry: TaskRegistry, task_queue: ResourceAwareTaskQueue):
        self.config_path = config_path
        self.task_registry = task_registry
        self.task_queue = task_queue
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.config = self._load_config()
        self.task_queue.register(
            "kaipanla",
            lambda task_id, payload: self._run_task(
                task_id,
                str((payload or {}).get("trigger") or "queued"),
                str((payload or {}).get("trade_date") or today_yyyymmdd()),
                list((payload or {}).get("features") or []),
                dict((payload or {}).get("params_by_feature") or {}),
                str((payload or {}).get("_queue_attempt_id") or ""),
            ),
            handler_version=2,
        )
        self.thread = threading.Thread(target=self._loop, name="kaipanla-scheduler", daemon=True)
        self.thread.start()

    def configure(self, enabled: bool, schedule_time: str, features: list[str], params_by_feature: dict[str, dict]) -> dict:
        schedule_time = self._validate_time(schedule_time)
        selected = [key for key in features if key]
        if not selected:
            raise ValueError("请至少选择一个开盘啦功能。")
        unknown = [key for key in selected if key not in KAIPANLA_FEATURES]
        if unknown:
            raise ValueError(f"未知开盘啦功能：{', '.join(unknown)}")
        clean_params = {str(key): value for key, value in params_by_feature.items() if isinstance(value, dict)}
        with self.lock:
            self.config.update(
                {
                    "enabled": bool(enabled),
                    "time": schedule_time,
                    "features": selected,
                    "params_by_feature": clean_params,
                    "updated_at": timestamp(),
                }
            )
            self._write_config_locked()
        return self.status()

    def run_now(self) -> dict:
        return self._start_run(trigger="manual")

    def status(self) -> dict:
        with self.lock:
            config = dict(self.config)
            task_status = _task_registry_status(self.task_registry, str(config.get("last_task_id") or ""))
            running = bool(self.worker and self.worker.is_alive()) or task_status == "running"
            queued = task_status == "queued"
        return {
            "scheduler": {
                "enabled": bool(config.get("enabled")),
                "time": config.get("time") or "21:45",
                "features": config.get("features") or [],
                "params_by_feature": config.get("params_by_feature") or {},
                "last_run_date": config.get("last_run_date") or "",
                "last_run_at": config.get("last_run_at") or "",
                "last_task_id": config.get("last_task_id") or "",
                "last_result": config.get("last_result") or {},
                "last_error": config.get("last_error") or "",
                "running": running,
                "queued": queued,
            }
        }

    def _loop(self) -> None:
        while not self.stop_event.wait(30):
            try:
                with self.lock:
                    enabled = bool(self.config.get("enabled"))
                    schedule_time = str(self.config.get("time") or "21:45")
                    last_run_date = str(self.config.get("last_run_date") or "")
                    active = bool(self.worker and self.worker.is_alive()) or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or ""))
                if not enabled or active:
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
            if self.worker and self.worker.is_alive() or _task_registry_active(self.task_registry, str(self.config.get("last_task_id") or "")):
                raise RuntimeError("开盘啦数据抓取任务正在运行。")
            features = list(self.config.get("features") or [])
            if not features:
                raise RuntimeError("尚未配置开盘啦抓取功能。")
            params_by_feature = dict(self.config.get("params_by_feature") or {})
            task_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            trade_date = today_yyyymmdd()
            self.config["last_task_id"] = task_id
            self._write_config_locked()
        self.task_registry.create_task(task_id, "kaipanla", "开盘啦数据抓取", metadata={"trigger": trigger, "features": features, "trade_date": trade_date})
        self.task_queue.enqueue(
            task_id=task_id,
            handler_key="kaipanla",
            kind="kaipanla",
            title="开盘啦数据抓取",
            payload={"trigger": trigger, "trade_date": trade_date, "features": features, "params_by_feature": params_by_feature},
            resource_level=QUEUE_LIGHT_IO,
        )
        return self.status()

    def _run_task(self, task_id: str, trigger: str, trade_date: str, features: list[str], params_by_feature: dict[str, dict], queue_attempt_id: str = "") -> None:
        try:
            result = run_kaipanla_batch(
                features,
                params_by_feature,
                save=True,
                run_id=task_id,
                trade_date=trade_date,
                checkpoint=lambda details: self.task_queue.checkpoint(
                    task_id,
                    resource_level=QUEUE_LIGHT_IO,
                    stage=f"kaipanla_{details.get('stage') or 'checkpoint'}",
                    details=details,
                ),
            )
            status = "succeeded" if result.get("ok") else "failed"
            if queue_attempt_id and not self.task_queue.is_attempt_active(task_id, queue_attempt_id):
                return
            self.task_registry.add_event(task_id, status, f"开盘啦抓取完成：成功 {result.get('succeeded', 0)}，失败 {result.get('failed', 0)}。", result)
            self.task_registry.update_task(task_id, status=status, error="" if result.get("ok") else "部分开盘啦功能抓取失败。", result=result)
            with self.lock:
                self.config["last_run_date"] = trade_date
                self.config["last_run_at"] = timestamp()
                self.config["last_result"] = {**result, "trigger": trigger}
                self.config["last_error"] = "" if result.get("ok") else "部分开盘啦功能抓取失败。"
                self._write_config_locked()
        except Exception as exc:  # noqa: BLE001 - task registry should record readable failure
            if queue_attempt_id and not self.task_queue.is_attempt_active(task_id, queue_attempt_id):
                return
            self.task_registry.add_event(task_id, "failed", str(exc), {})
            self.task_registry.update_task(task_id, status="failed", error=str(exc))
            with self.lock:
                self.config["last_error"] = str(exc)
                self._write_config_locked()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                if isinstance(data, dict):
                    data.setdefault("features", ["daily_data", "market_limit_up_ladder", "sector_ranking"])
                    data.setdefault("params_by_feature", {})
                    data["enabled"] = data.get("enabled", False) is True
                    data["time"] = self._validate_time(str(data.get("time") or "21:45"))
                    return data
            except Exception:
                pass
        return {
            "enabled": False,
            "time": "21:45",
            "features": ["daily_data", "market_limit_up_ladder", "sector_ranking"],
            "params_by_feature": {},
            "last_run_date": "",
            "last_run_at": "",
            "last_task_id": "",
            "last_result": {},
            "last_error": "",
        }

    def _write_config_locked(self) -> None:
        write_json(self.config_path, self.config)

    def _validate_time(self, value: str) -> str:
        text = str(value or "").strip()
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("开盘啦定时时间格式必须是 HH:MM。")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("开盘啦定时时间必须是数字格式 HH:MM。") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("开盘啦定时时间必须在 00:00-23:59 之间。")
        return f"{hour:02d}:{minute:02d}"


class NewsRefetchController:
    def __init__(self, project_root: Path, task_registry: TaskRegistry | None = None):
        self.project_root = project_root
        self.logs_dir = project_root / "logs"
        self.task_registry = task_registry
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.current: dict = self._idle_state()

    def start(self, payload: dict) -> dict:
        with self.lock:
            self._refresh_locked()
            if self.process and self.process.poll() is None:
                raise RuntimeError("新闻补抓任务已经在运行。")

            source = self._source(payload.get("source") or payload.get("publisher"))
            max_pages = self._bounded_int(payload.get("max_pages"), default=2, minimum=1, maximum=10, field="max_pages")
            max_articles = self._bounded_int(payload.get("max_articles"), default=0, minimum=0, maximum=500, field="max_articles")
            request_delay = self._bounded_float(payload.get("request_delay"), default=0.5, minimum=0, maximum=30, field="request_delay")
            categories = self._categories(payload.get("categories") or payload.get("type"))

            job_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            log_file = self.logs_dir / f"admin-news-refetch-{job_id}.log"
            ensure_dir(log_file.parent)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(self.project_root / "NewsCrawler" / "src") + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            env.setdefault("MONGODB_URI", raw_news_config().uri)
            cmd = [
                sys.executable,
                "-m",
                "news_crawler.cli",
                "crawl",
                "--source",
                source,
                "--latest",
                "--max-pages",
                str(max_pages),
                "--request-delay",
                f"{request_delay:g}",
                "--stop-after-existing-page",
            ]
            if max_articles:
                cmd.extend(["--max-articles", str(max_articles)])
            if categories:
                cmd.extend(["--categories", ",".join(categories)])

            with log_file.open("a", encoding="utf-8") as output:
                output.write("admin news refetch command: " + " ".join(cmd) + "\n")
                output.flush()
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    start_new_session=True,
                )

            self.current = {
                "job_id": job_id,
                "status": "running",
                "pid": self.process.pid,
                "started_at": timestamp(),
                "finished_at": "",
                "returncode": None,
                "source": source,
                "categories": categories,
                "max_pages": max_pages,
                "max_articles": max_articles,
                "request_delay": request_delay,
                "log_file": str(log_file),
                "error": "",
            }
            if self.task_registry:
                self.task_registry.create_task(
                    job_id,
                    "news_refetch",
                    "新闻资料库补抓",
                    metadata={"trigger": "manual", "source": source, "categories": categories, "max_pages": max_pages},
                )
                self.task_registry.update_task(job_id, status="running")
                self.task_registry.add_event(job_id, "running", "NewsCrawler 补抓进程已启动。", {"pid": self.process.pid, "log_file": str(log_file)})
            return self.status_locked()

    def status(self) -> dict:
        with self.lock:
            self._refresh_locked()
            return self.status_locked()

    def status_locked(self) -> dict:
        state = dict(self.current or self._idle_state())
        state["log_tail"] = self._log_tail(Path(state.get("log_file") or ""), lines=40)
        return {"refetch": state}

    def _refresh_locked(self) -> None:
        if not self.process:
            return
        returncode = self.process.poll()
        if returncode is None:
            return
        self.current["returncode"] = returncode
        self.current["finished_at"] = self.current.get("finished_at") or timestamp()
        self.current["status"] = "succeeded" if returncode == 0 else "failed"
        if returncode != 0:
            self.current["error"] = self._failure_summary(Path(self.current.get("log_file") or ""))
        if self.task_registry and self.current.get("job_id"):
            error = "" if returncode == 0 else self.current.get("error") or f"returncode={returncode}"
            self.task_registry.update_task(self.current["job_id"], status=self.current["status"], error=error)
            self.task_registry.add_event(self.current["job_id"], self.current["status"], f"NewsCrawler 补抓结束，returncode={returncode}。")
        self.process = None

    def _source(self, value) -> str:
        source = str(value or "all").strip()
        return source if source in {"all", "tonghuashun", "guardian", "bloomberg"} else "all"

    def _categories(self, value) -> list[str]:
        values = value if isinstance(value, list) else str(value or "").split(",")
        return [str(item).strip() for item in values if str(item).strip()][:12]

    def _bounded_int(self, value, default: int, minimum: int, maximum: int, field: str) -> int:
        try:
            parsed = int(value if value not in (None, "") else default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是数字。") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{field} 必须在 {minimum}-{maximum} 之间。")
        return parsed

    def _bounded_float(self, value, default: float, minimum: float, maximum: float, field: str) -> float:
        try:
            parsed = float(value if value not in (None, "") else default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是数字。") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{field} 必须在 {minimum:g}-{maximum:g} 之间。")
        return parsed

    def _failure_summary(self, log_file: Path) -> str:
        lines = self._log_tail(log_file, lines=80).splitlines()
        important = [
            line.strip()
            for line in lines
            if "Traceback" in line
            or "Error" in line
            or "ERROR" in line
            or "Exception" in line
            or "failed" in line.lower()
            or "ModuleNotFoundError" in line
            or "ImportError" in line
        ]
        return (important[-1] if important else (lines[-1] if lines else "新闻补抓进程异常退出，但没有生成日志。"))[-500:]

    def _log_tail(self, log_file: Path, *, lines: int) -> str:
        if not log_file.exists():
            return ""
        return "\n".join(log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def _idle_state(self) -> dict:
        return {
            "job_id": "",
            "status": "idle",
            "pid": None,
            "started_at": "",
            "finished_at": "",
            "returncode": None,
            "source": "",
            "categories": [],
            "max_pages": None,
            "max_articles": None,
            "request_delay": None,
            "log_file": "",
            "log_tail": "",
            "error": "",
        }


class MarketFetchController:
    def __init__(self, project_root: Path, task_registry: TaskRegistry | None = None):
        self.project_root = project_root
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
            selected_types = []
            stock_code = normalize_ts_code(str(payload.get("stock_code") or payload.get("ts_code") or payload.get("code") or "")) if source == "ths_market" else ""
            max_pages = self._bounded_int(payload.get("max_pages"), default=1, minimum=1, maximum=50, field="max_pages")
            threads = self._bounded_int(payload.get("threads"), default=2, minimum=1, maximum=4, field="threads")
            new_only = bool(payload.get("new_only", False))
            article_sleep = self._sleep_range(payload.get("article_sleep"), default="3,5", field="article_sleep")
            page_sleep = self._sleep_range(payload.get("page_sleep"), default="5,10", field="page_sleep")

            job_id = timestamp() + "_" + uuid.uuid4().hex[:8]
            log_file = self.logs_dir / f"admin-market-fetch-{source}-{job_id}.log"
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
                    metadata={"trigger": "manual", "source": source, "types": selected_types, "stock_code": stock_code, "max_pages": max_pages, "new_only": new_only},
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
            "available_types": [],
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

        raise ValueError("未知行情补采来源。")

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
            raise RuntimeError("缺少 API key 加密密钥，请运行 stock_pipeline secrets migrate-env 或让系统生成本地 master.key。")
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
    def __init__(self, path: Path, key_cipher: ApiKeyCipher, admin_username: str = "admin"):
        self.path = path
        self.key_cipher = key_cipher
        self.admin_username = admin_username or "admin"
        self.lock = threading.Lock()
        ensure_dir(path.parent)
        self._lock_down_file()

    def issue_agent_token(
        self,
        *,
        name: str,
        scopes,
        created_by: str,
        expires_in_days: int = 30,
        rate_limit_per_min: int = 60,
    ) -> dict:
        name = (name or "agent").strip()[:80]
        scope_list = _parse_agent_scopes(scopes)
        expires_in_days = max(1, min(365, int(expires_in_days or 30)))
        rate_limit_per_min = max(1, min(600, int(rate_limit_per_min or 60)))
        raw_token = AGENT_TOKEN_PREFIX + secrets.token_urlsafe(32).rstrip("=")
        token_id = uuid.uuid4().hex
        token_prefix = raw_token[: len(AGENT_TOKEN_PREFIX) + 8]
        item = {
            "id": token_id,
            "name": name,
            "token_prefix": token_prefix,
            "token_hash": _hash_agent_token(raw_token),
            "scopes": scope_list,
            "status": "active",
            "created_by": created_by or "admin",
            "created_at": timestamp(),
            "expires_at": time.time() + expires_in_days * 86400,
            "last_used_at": "",
            "rate_limit_per_min": rate_limit_per_min,
        }
        with self.lock:
            data = self._read()
            data.setdefault("agent_tokens", {})[token_id] = item
            self._audit(data, created_by or "admin", "agent_token_issued", token_prefix, {"scopes": scope_list, "name": name})
            self._write(data)
        public = self._public_agent_token(item)
        public["token"] = raw_token
        return public

    def list_agent_tokens(self) -> list[dict]:
        with self.lock:
            data = self._read()
            items = list(data.get("agent_tokens", {}).values())
        return [self._public_agent_token(item) for item in sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)]

    def revoke_agent_token(self, token_id: str, actor: str) -> dict:
        with self.lock:
            data = self._read()
            item = data.get("agent_tokens", {}).get(token_id)
            if not item:
                raise KeyError("找不到 Agent token。")
            item["status"] = "revoked"
            item["revoked_at"] = timestamp()
            item["revoked_by"] = actor or "admin"
            self._audit(data, actor or "admin", "agent_token_revoked", item.get("token_prefix", token_id), {})
            self._write(data)
            return self._public_agent_token(item)

    def verify_agent_token(self, raw_token: str) -> dict | None:
        if not raw_token or not raw_token.startswith(AGENT_TOKEN_PREFIX):
            return None
        token_hash = _hash_agent_token(raw_token)
        now = time.time()
        with self.lock:
            data = self._read()
            for item in data.get("agent_tokens", {}).values():
                if not hmac.compare_digest(str(item.get("token_hash") or ""), token_hash):
                    continue
                if item.get("status") != "active" or float(item.get("expires_at") or 0) <= now:
                    return None
                item["last_used_at"] = timestamp()
                self._write(data)
                return self._public_agent_token(item)
        return None

    def record_agent_audit(self, token: dict | None, route: str, method: str, scope: str, status_code: int, details: dict | None = None) -> None:
        with self.lock:
            data = self._read()
            logs = data.setdefault("agent_audit_logs", [])
            logs.append(
                {
                    "time": timestamp(),
                    "token_id": (token or {}).get("id", ""),
                    "token_prefix": (token or {}).get("token_prefix", ""),
                    "agent_name": (token or {}).get("name", ""),
                    "route": route,
                    "method": method,
                    "scope": scope,
                    "status_code": status_code,
                    "details": details or {},
                }
            )
            if len(logs) > 500:
                data["agent_audit_logs"] = logs[-500:]
            self._write(data)

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
        return bool(self.authenticate_user(username, password))

    def authenticate_user(self, username: str, password: str) -> dict | None:
        with self.lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                return None
            disabled, changed = self._refresh_disabled_state(user)
            if changed:
                self._audit(data, "system", "auto_enable_user", username, {})
                self._write(data)
            if disabled:
                return None
            if not self._verify_password(password, user.get("password", "")):
                return None
            return {"username": username, "role": "user"}

    def user_access_state(self, username: str, data: dict | None = None) -> dict:
        data = data or self._read()
        if username == "":
            return {"tier": "", "is_vip": False, "vip_until": 0, "vip_until_text": ""}
        user = data.get("users", {}).get(username)
        if not user:
            is_admin = _secure_text_equal(username, self.admin_username)
            return {"tier": "admin" if is_admin else "", "is_vip": is_admin, "vip_until": 0, "vip_until_text": ""}
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
            self._assert_manageable_user(username)
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            self._assert_manageable_user(username, user)
            base = max(now, float(user.get("vip_until") or 0))
            user["vip_until"] = base + max(1, int(days)) * 86400
            user["tier"] = "vip"
            self._audit(data, actor, "grant_vip", username, {"days": days})
            self._write(data)
            return self.user_access_state(username, data=data)

    def admin_revoke_vip(self, username: str, actor: str) -> dict:
        with self.lock:
            self._assert_manageable_user(username)
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            self._assert_manageable_user(username, user)
            user["vip_until"] = 0
            user["tier"] = "user"
            self._audit(data, actor, "revoke_vip", username, {})
            self._write(data)
            return self.user_access_state(username, data=data)

    def admin_set_disabled(self, username: str, disabled: bool, actor: str, days: int = 0) -> None:
        with self.lock:
            self._assert_manageable_user(username)
            data = self._read()
            user = data.get("users", {}).get(username)
            if not user:
                raise KeyError("找不到用户。")
            self._assert_manageable_user(username, user)
            user["disabled"] = bool(disabled)
            details = {}
            if disabled:
                if days < 1 or days > 3650:
                    raise ValueError("封禁天数必须在 1-3650 天之间。")
                disabled_until = time.time() + days * 86400
                user["disabled_until"] = disabled_until
                user["disabled_at"] = timestamp()
                user["disabled_by"] = actor
                details = {"days": days, "disabled_until": disabled_until}
            else:
                user.pop("disabled_until", None)
                user.pop("disabled_at", None)
                user.pop("disabled_by", None)
            self._audit(data, actor, "disable_user" if disabled else "enable_user", username, details)
            self._write(data)

    def _assert_manageable_user(self, username: str, user: dict | None = None) -> None:
        role = str((user or {}).get("role") or (user or {}).get("tier") or "")
        if _secure_text_equal(username, self.admin_username) or role == "admin":
            raise PermissionError("最高管理员账号不能修改权限、禁用或归档。")

    def _refresh_disabled_state(self, user: dict, now: float | None = None) -> tuple[bool, bool]:
        now = time.time() if now is None else now
        disabled = bool(user.get("disabled"))
        disabled_until = float(user.get("disabled_until") or 0)
        if disabled and disabled_until and disabled_until <= now:
            user["disabled"] = False
            user.pop("disabled_until", None)
            user.pop("disabled_at", None)
            user.pop("disabled_by", None)
            return False, True
        if not disabled and disabled_until:
            user.pop("disabled_until", None)
            user.pop("disabled_at", None)
            user.pop("disabled_by", None)
            return False, True
        return disabled, False

    def admin_archive_account(self, username: str, actor: str, reason: str = "") -> dict:
        if not username:
            raise ValueError("缺少账号。")
        with self.lock:
            self._assert_manageable_user(username)
            data = self._read()
            users = data.setdefault("users", {})
            demo_accounts = data.setdefault("demo_accounts", {})
            if username in users:
                user = users[username]
                self._assert_manageable_user(username, user)
                archived = data.setdefault("archived_users", {})
                user = users.pop(username)
                user["archived_at"] = timestamp()
                user["archived_by"] = actor
                user["archive_reason"] = reason.strip()
                user["disabled"] = True
                archived[username] = {
                    "account": user,
                    "usage": data.get("usage", {}).get(username, {}),
                    "archived_at": user["archived_at"],
                    "archived_by": actor,
                    "reason": reason.strip(),
                }
                self._audit(data, actor, "archive_user", username, {"reason": reason.strip()})
                self._write(data)
                return {"kind": "user", "username": username}
            if username in demo_accounts:
                account = demo_accounts.pop(username)
                account["archived_at"] = timestamp()
                account["archived_by"] = actor
                account["archive_reason"] = reason.strip()
                account["disabled"] = True
                archived = data.setdefault("archived_demo_accounts", {})
                archived[username] = {
                    "account": account,
                    "usage": data.get("usage", {}).get(username, {}),
                    "archived_at": account["archived_at"],
                    "archived_by": actor,
                    "reason": reason.strip(),
                }
                self._audit(data, actor, "archive_demo_account", username, {"reason": reason.strip()})
                self._write(data)
                return {"kind": "demo", "username": username}
            raise KeyError("找不到用户或测试账号。")

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

    def record_audit_event(self, actor: str, action: str, target: str, details: dict | None = None) -> None:
        with self.lock:
            data = self._read()
            self._audit(data, actor or "anonymous", action, target, details or {})
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
            changed = False
            for username, user in data.get("users", {}).items():
                _, user_changed = self._refresh_disabled_state(user)
                if user_changed:
                    self._audit(data, "system", "auto_enable_user", username, {})
                    changed = True
            if changed:
                self._write(data)
        users = []
        usage = data.get("usage", {})
        archived_names = set(data.get("archived_users", {})) | set(data.get("archived_demo_accounts", {}))
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
                    "disabled_until": float(user.get("disabled_until") or 0),
                    "disabled_until_text": self._format_expiry(float(user.get("disabled_until") or 0)),
                    "protected": _secure_text_equal(username, self.admin_username) or access["tier"] == "admin",
                    "usage_total": billable_usage["total"],
                    "last_request_at": billable_usage["last_request_at"],
                    "by_path": billable_usage["by_path"],
                }
            )
        for username, user_usage in sorted(usage.items()):
            if any(item["username"] == username for item in users):
                continue
            if username in archived_names:
                continue
            billable_usage = self._billable_usage_view(user_usage)
            users.append(
                {
                    "username": username,
                    "role": user_usage.get("role", ""),
                    "created_at": "",
                    "invite_code": "",
                    "protected": _secure_text_equal(username, self.admin_username) or user_usage.get("role") == "admin",
                    "disabled": False,
                    "disabled_until": 0,
                    "disabled_until_text": "",
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
            "agent_tokens": self.list_agent_tokens(),
            "archived_users_count": len(data.get("archived_users", {})),
            "archived_demo_accounts_count": len(data.get("archived_demo_accounts", {})),
            "audit_logs": list(reversed(data.get("audit_logs", [])[-80:])),
            "agent_audit_logs": list(reversed(data.get("agent_audit_logs", [])[-80:])),
        }

    def admin_archives(self, query: str = "") -> dict:
        needle = query.strip().lower()
        with self.lock:
            data = self._read()
        users = [
            self._public_archived_account(username, item, kind="user")
            for username, item in sorted(data.get("archived_users", {}).items(), key=lambda pair: pair[1].get("archived_at", ""), reverse=True)
        ]
        demo_accounts = [
            self._public_archived_account(username, item, kind="demo")
            for username, item in sorted(data.get("archived_demo_accounts", {}).items(), key=lambda pair: pair[1].get("archived_at", ""), reverse=True)
        ]
        if needle:
            users = [item for item in users if self._archive_matches(item, needle)]
            demo_accounts = [item for item in demo_accounts if self._archive_matches(item, needle)]
        items = sorted([*users, *demo_accounts], key=lambda item: item.get("archived_at", ""), reverse=True)
        return {
            "query": query,
            "items": items,
            "users": users,
            "demo_accounts": demo_accounts,
            "counts": {
                "users": len(users),
                "demo_accounts": len(demo_accounts),
                "total": len(users) + len(demo_accounts),
            },
        }

    def _read(self) -> dict:
        if not self.path.exists():
            return {"users": {}, "used_invites": {}, "invites": {}, "usage": {}, "demo_accounts": {}, "archived_users": {}, "archived_demo_accounts": {}, "vip_codes": {}, "system_api_keys": {}, "agent_tokens": {}, "audit_logs": [], "agent_audit_logs": []}
        data = read_json(self.path)
        data.setdefault("users", {})
        data.setdefault("used_invites", {})
        data.setdefault("invites", {})
        data.setdefault("usage", {})
        data.setdefault("demo_accounts", {})
        data.setdefault("archived_users", {})
        data.setdefault("archived_demo_accounts", {})
        data.setdefault("vip_codes", {})
        data.setdefault("system_api_keys", {})
        data.setdefault("agent_tokens", {})
        data.setdefault("audit_logs", [])
        data.setdefault("agent_audit_logs", [])
        return data

    def _write(self, data: dict) -> None:
        ensure_dir(self.path.parent)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)
        self._lock_down_file()

    def _lock_down_file(self) -> None:
        if self.path.exists():
            os.chmod(self.path, 0o600)

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

    def _public_agent_token(self, item: dict) -> dict:
        expires_at = float(item.get("expires_at") or 0)
        return {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "token_prefix": item.get("token_prefix", ""),
            "scopes": _parse_agent_scopes(item.get("scopes")),
            "scope_labels": {scope: AGENT_SCOPE_LABELS.get(scope, scope) for scope in _parse_agent_scopes(item.get("scopes"))},
            "status": item.get("status", "active"),
            "created_by": item.get("created_by", ""),
            "created_at": item.get("created_at", ""),
            "expires_at": expires_at,
            "expires_at_text": self._format_expiry(expires_at),
            "last_used_at": item.get("last_used_at", ""),
            "rate_limit_per_min": int(item.get("rate_limit_per_min") or 60),
        }

    def _public_archived_account(self, username: str, item: dict, kind: str) -> dict:
        account = item.get("account") or {}
        usage = item.get("usage") or {}
        billable_usage = self._billable_usage_view(usage)
        api_keys = {}
        if kind == "user":
            keys = account.get("api_keys") or {}
            api_keys = {
                name: {"configured": bool(value.get("ciphertext")), "updated_at": value.get("updated_at", "")}
                for name, value in keys.items()
                if isinstance(value, dict)
            }
        return {
            "username": username,
            "kind": kind,
            "archived_at": item.get("archived_at", account.get("archived_at", "")),
            "archived_by": item.get("archived_by", account.get("archived_by", "")),
            "reason": item.get("reason", account.get("archive_reason", "")),
            "created_at": account.get("created_at", ""),
            "created_by": account.get("created_by", ""),
            "role": account.get("role") or account.get("tier") or ("demo" if kind == "demo" else "user"),
            "invite_code": account.get("invite_code", ""),
            "api_keys": api_keys,
            "usage_total": billable_usage["total"],
            "last_request_at": billable_usage["last_request_at"],
            "by_path": billable_usage["by_path"],
        }

    def _archive_matches(self, item: dict, needle: str) -> bool:
        haystack = " ".join(
            str(item.get(field, ""))
            for field in ("username", "kind", "archived_at", "archived_by", "reason", "created_at", "created_by", "role", "invite_code")
        ).lower()
        return needle in haystack

    def _audit(self, data: dict, actor: str, action: str, target: str, details: dict) -> None:
        logs = data.setdefault("audit_logs", [])
        logs.append({"time": timestamp(), "actor": actor, "action": action, "target": target, "details": details})
        if len(logs) > 500:
            data["audit_logs"] = logs[-500:]
