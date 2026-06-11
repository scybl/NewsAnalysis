from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    deepseek_api_key: str
    tushare_base_url: str = "http://api.tushare.pro"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    web_username: str = "admin"
    web_password: str = "admin"
    web_session_secret: str = ""


def get_settings(require_deepseek: bool = False) -> Settings:
    load_dotenv()
    tushare_token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API") or ""
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API") or ""
    if not tushare_token:
        raise RuntimeError("缺少 Tushare token，请在 .env 中设置 TUSHARE_API 或 TUSHARE_TOKEN。")
    if require_deepseek and not deepseek_api_key:
        raise RuntimeError("缺少 DeepSeek API key，请在 .env 中设置 DEEPSEEK_API 或 DEEPSEEK_API_KEY。")
    return Settings(
        tushare_token=tushare_token,
        deepseek_api_key=deepseek_api_key,
        tushare_base_url=os.getenv("TUSHARE_BASE_URL", "http://api.tushare.pro"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        web_username=os.getenv("STOCK_WEB_USER", "admin"),
        web_password=os.getenv("STOCK_WEB_PASSWORD") or os.getenv("STOCK_WEB_PASS") or "admin",
        web_session_secret=os.getenv("STOCK_WEB_SESSION_SECRET", ""),
    )
