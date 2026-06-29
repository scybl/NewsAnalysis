from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ProviderCapabilities:
    languages: frozenset[str]
    supports_historical: bool = True
    supports_categories: bool = True
    supports_stock_filter: bool = False


@dataclass(frozen=True)
class ArticleRef:
    source_name: str
    url: str
    external_id: str | None = None
    section: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsArticle:
    source_name: str
    url: str
    title: str
    content: str
    published_at: datetime
    external_id: str | None = None
    canonical_url: str = ""
    summary: str = ""
    fetched_at: datetime = field(default_factory=utc_now)
    section: str = ""
    language: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsCrawlRequest:
    mode: Literal["latest", "backfill"] = "latest"
    sources: tuple[str, ...] | None = None
    since: datetime | None = None
    until: datetime | None = None
    categories: tuple[str, ...] | None = None
    category_pages: dict[str, int] = field(default_factory=dict)
    max_pages: int = 1
    max_articles: int = 0
    request_delay_seconds: float = 0
    dry_run: bool = False
    stop_after_existing_page: bool = False


@dataclass(frozen=True)
class CrawlIssue:
    code: str
    message: str
    article_url: str | None = None
    retryable: bool = False


@dataclass
class CrawlResult:
    source_name: str
    run_id: str
    status: str = "running"
    discovered: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    metrics: dict[str, int | float] = field(default_factory=dict)
    warnings: list[CrawlIssue] = field(default_factory=list)
    errors: list[CrawlIssue] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
