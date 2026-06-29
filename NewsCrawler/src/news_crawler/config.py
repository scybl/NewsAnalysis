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
    bloomberg_cookie: str = ""
    disabled_sources: frozenset[str] = frozenset()


def get_settings() -> Settings:
    return Settings(
        mongodb_uri=_mongo_uri(),
        mongodb_database=os.getenv("MONGODB_DATABASE", "news"),
        raw_collection=os.getenv("MONGODB_RAW_COLLECTION", "raw_articles"),
        runs_collection=os.getenv("MONGODB_RUNS_COLLECTION", "crawl_runs"),
        guardian_api_key=_env_or_file("GUARDIAN_API_KEY"),
        guardian_base_url=os.getenv("GUARDIAN_BASE_URL", "https://content.guardianapis.com"),
        bloomberg_latest_url=os.getenv("BLOOMBERG_LATEST_URL", "https://www.bloomberg.com/latest"),
        bloomberg_cookie=_env_or_file("BLOOMBERG_COOKIE"),
        disabled_sources=frozenset(
            item.strip()
            for item in os.getenv("NEWS_CRAWLER_DISABLED_SOURCES", "bloomberg").split(",")
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
