from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .secret_store import get_secret_store, secret_value


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    tushare_token: str
    deepseek_api_key: str = ""
    tushare_base_url: str = "http://api.tushare.pro"
    tushare_pause_seconds: float = 0.22
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    web_username: str = "admin"
    web_password: str = "admin"
    admin_readonly_username: str = ""
    admin_readonly_password: str = ""
    web_session_secret: str = ""
    web_invite_codes: str = ""
    web_demo_request_limit: int = 30
    web_demo_window_seconds: int = 86400
    web_invite_ttl_seconds: int = 259200
    stock_data_cache_ttl_seconds: int = 86400
    analysis_history_review_limit: int = 3
    web_key_encryption_secret: str = ""
    stock_analysis_reuse_ttl_seconds: int = 1800
    stock_analysis_refresh_ttl_seconds: int = 3600
    idle_stock_prefetch_enabled: bool = True
    idle_stock_prefetch_seconds: int = 1800
    idle_stock_prefetch_minutes_enabled: bool = True
    idle_stock_prefetch_refresh_existing_days: int = 14
    stock_agent_engine: str = "legacy"
    stock_agent_template: str = "native"
    stock_analysis_execution_enabled: bool = False
    stock_analysis_external_url: str = ""
    data_fetch_approval_required: bool = True


def get_settings(require_deepseek: bool = False) -> Settings:
    load_dotenv()
    secret_store = get_secret_store()
    tushare_token = secret_value("tushare.api_token", ("TUSHARE_TOKEN", "TUSHARE_API"))
    if require_deepseek:
        deepseek_token = secret_store.get("deepseek.api_key")
        if not deepseek_token:
            raise RuntimeError("DeepSeek API key 已从 .env 隔离，请在管理员后台配置系统 DeepSeek key，或运行 secrets set deepseek.api_key。")
    else:
        deepseek_token = secret_store.get("deepseek.api_key")
    return Settings(
        tushare_token=tushare_token,
        tushare_base_url=os.getenv("TUSHARE_BASE_URL", "http://api.tushare.pro"),
        tushare_pause_seconds=float(os.getenv("TUSHARE_PAUSE_SECONDS", "0.22")),
        deepseek_api_key=deepseek_token,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        web_username=secret_value("web.admin_username", ("STOCK_WEB_USER",), "admin"),
        web_password=secret_value("web.admin_password", ("STOCK_WEB_PASSWORD", "STOCK_WEB_PASS"), "admin"),
        admin_readonly_username=secret_value("web.admin_readonly_username", ("ADMIN_READONLY_USER", "STOCK_ADMIN_READONLY_USER"), ""),
        admin_readonly_password=secret_value("web.admin_readonly_password", ("ADMIN_READONLY_PASSWORD", "STOCK_ADMIN_READONLY_PASSWORD"), ""),
        web_session_secret=secret_value("web.session_secret", ("STOCK_WEB_SESSION_SECRET",)),
        web_invite_codes=os.getenv("STOCK_WEB_INVITE_CODES", ""),
        web_demo_request_limit=int(os.getenv("STOCK_WEB_DEMO_REQUEST_LIMIT", "30")),
        web_demo_window_seconds=int(os.getenv("STOCK_WEB_DEMO_WINDOW_SECONDS", "86400")),
        web_invite_ttl_seconds=int(os.getenv("STOCK_WEB_INVITE_TTL_SECONDS", "259200")),
        stock_data_cache_ttl_seconds=int(os.getenv("STOCK_DATA_CACHE_TTL_SECONDS", "86400")),
        analysis_history_review_limit=int(os.getenv("STOCK_ANALYSIS_HISTORY_REVIEW_LIMIT", "3")),
        web_key_encryption_secret=secret_value("web.key_encryption_secret", ("STOCK_WEB_KEY_ENCRYPTION_SECRET",), secret_store.master_secret()),
        stock_analysis_reuse_ttl_seconds=int(os.getenv("STOCK_ANALYSIS_REUSE_TTL_SECONDS", "1800")),
        stock_analysis_refresh_ttl_seconds=int(os.getenv("STOCK_ANALYSIS_REFRESH_TTL_SECONDS", "3600")),
        idle_stock_prefetch_enabled=os.getenv("IDLE_STOCK_PREFETCH_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
        idle_stock_prefetch_seconds=int(os.getenv("IDLE_STOCK_PREFETCH_SECONDS", "1800")),
        idle_stock_prefetch_minutes_enabled=os.getenv("IDLE_STOCK_PREFETCH_MINUTES_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
        idle_stock_prefetch_refresh_existing_days=int(os.getenv("IDLE_STOCK_PREFETCH_REFRESH_EXISTING_DAYS", "14")),
        stock_agent_engine=os.getenv("STOCK_AGENT_ENGINE", "legacy").strip().lower() or "legacy",
        stock_agent_template=os.getenv("STOCK_AGENT_TEMPLATE", "native").strip().lower() or "native",
        stock_analysis_execution_enabled=os.getenv("STOCK_ANALYSIS_EXECUTION_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
        stock_analysis_external_url=os.getenv("STOCK_ANALYSIS_EXTERNAL_URL", "").strip(),
        data_fetch_approval_required=os.getenv("DATA_FETCH_APPROVAL_REQUIRED", "1").strip().lower() not in {"0", "false", "no", "off"},
    )
