from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_database: str = "news"
    raw_collection: str = "raw_articles"
    runs_collection: str = "crawl_runs"
    guardian_api_key: str = ""
    guardian_base_url: str = "https://content.guardianapis.com"
    bloomberg_latest_url: str = "https://www.bloomberg.com/latest"
    bloomberg_api_url: str = "https://www.bloomberg.com/lineup-next/api/stories"
    bloomberg_cookie: str = ""
    bloomberg_cookies_json: str = ""
    bloomberg_proxy: str = ""
    bloomberg_use_api: bool = True
    bloomberg_require_login_cookie: bool = False
    politico_feed_urls: str = ""
    politico_fetch_article_pages: bool = False
    politico_browser_news_url: str = "https://www.politico.com/"
    politico_browser_headless: bool = True
    politico_browser_wait_seconds: float = 8
    politico_browser_profile_dir: str = ""
    politico_browser_proxy: str = ""
    politico_browser_cookies_json: str = ""
    disabled_sources: frozenset[str] = frozenset()
    max_runtime_seconds: float = 300


def get_settings() -> Settings:
    return Settings(
        mongodb_uri=_mongo_uri(),
        mongodb_database=os.getenv("MONGODB_DATABASE", "news"),
        raw_collection=os.getenv("MONGODB_RAW_COLLECTION", "raw_articles"),
        runs_collection=os.getenv("MONGODB_RUNS_COLLECTION", "crawl_runs"),
        guardian_api_key=_env_or_file("GUARDIAN_API_KEY"),
        guardian_base_url=os.getenv("GUARDIAN_BASE_URL", "https://content.guardianapis.com"),
        bloomberg_latest_url=_env_or_file("BLOOMBERG_LATEST_URL") or "https://www.bloomberg.com/latest",
        bloomberg_api_url=_env_or_file("BLOOMBERG_API_URL") or "https://www.bloomberg.com/lineup-next/api/stories",
        bloomberg_cookie=_env_or_file("BLOOMBERG_COOKIE"),
        bloomberg_cookies_json=_env_or_file("BLOOMBERG_COOKIES_JSON"),
        bloomberg_proxy=_env_or_file("BLOOMBERG_PROXY"),
        bloomberg_use_api=_env_bool_or_file("BLOOMBERG_USE_API", True),
        bloomberg_require_login_cookie=_env_bool_or_file("BLOOMBERG_REQUIRE_LOGIN_COOKIE", False),
        politico_feed_urls=os.getenv("POLITICO_FEED_URLS", ""),
        politico_fetch_article_pages=_env_bool("POLITICO_FETCH_ARTICLE_PAGES", False),
        politico_browser_news_url=os.getenv("POLITICO_BROWSER_NEWS_URL", "https://www.politico.com/"),
        politico_browser_headless=_env_bool("POLITICO_BROWSER_HEADLESS", True),
        politico_browser_wait_seconds=float(os.getenv("POLITICO_BROWSER_WAIT_SECONDS", "8")),
        politico_browser_profile_dir=os.getenv("POLITICO_BROWSER_PROFILE_DIR", ""),
        politico_browser_proxy=_env_or_file("POLITICO_BROWSER_PROXY"),
        politico_browser_cookies_json=_env_or_file("POLITICO_BROWSER_COOKIES_JSON"),
        max_runtime_seconds=max(0.0, float(os.getenv("NEWS_CRAWLER_MAX_RUNTIME_SECONDS", "300"))),
        disabled_sources=frozenset(
            item.strip()
            for item in os.getenv("NEWS_CRAWLER_DISABLED_SOURCES", "bloomberg,politico_browser,politico_rss,politico_chrome").split(",")
            if item.strip()
        ),
    )


def _mongo_uri() -> str:
    direct = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    if direct:
        return direct
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    password = os.getenv("MONGO_PASSWORD", "") or _read_secret_file(
        os.getenv("MONGO_PASSWORD_FILE", "") or _default_mongo_password_file()
    )
    username = os.getenv("MONGO_USER", "admin" if password else "")
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if username and password:
        return (
            f"mongodb://{urllib.parse.quote_plus(username)}:"
            f"{urllib.parse.quote_plus(password)}@{host}:{port}/?authSource={auth_source}"
        )
    return f"mongodb://{host}:{port}/"


def _read_secret_file(path: str) -> str:
    if not path:
        return ""
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _default_mongo_password_file() -> str:
    candidates = [
        Path.cwd() / "local_data" / "secure" / "mongo_root_password.txt",
        Path.cwd().parent / "local_data" / "secure" / "mongo_root_password.txt",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def _env_or_file(name: str) -> str:
    return os.getenv(name, "") or _read_secret_file(os.getenv(f"{name}_FILE", ""))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_bool_or_file(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        value = _read_secret_file(os.getenv(f"{name}_FILE", ""))
    if not value:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}
