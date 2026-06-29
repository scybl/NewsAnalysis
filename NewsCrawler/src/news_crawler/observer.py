from __future__ import annotations

import logging
from typing import Protocol

from .models import CrawlIssue, CrawlResult, NewsArticle


class RunObserver(Protocol):
    def on_run_started(self, result: CrawlResult) -> None: ...
    def on_article_inserted(self, article: NewsArticle) -> None: ...
    def on_article_duplicated(self, article: NewsArticle, reason: str) -> None: ...
    def on_provider_failed(self, source_name: str, issue: CrawlIssue) -> None: ...
    def on_run_finished(self, result: CrawlResult) -> None: ...


class LoggingRunObserver:
    def on_run_started(self, result: CrawlResult) -> None:
        logging.info("run_started source=%s run_id=%s", result.source_name, result.run_id)

    def on_article_inserted(self, article: NewsArticle) -> None:
        logging.info("inserted source=%s title=%s", article.source_name, article.title)

    def on_article_duplicated(self, article: NewsArticle, reason: str) -> None:
        logging.info("duplicate source=%s reason=%s title=%s", article.source_name, reason, article.title)

    def on_provider_failed(self, source_name: str, issue: CrawlIssue) -> None:
        logging.error("provider_failed source=%s code=%s error=%s", source_name, issue.code, issue.message)

    def on_run_finished(self, result: CrawlResult) -> None:
        logging.info(
            "run_finished source=%s status=%s discovered=%s fetched=%s inserted=%s updated=%s skipped=%s failed=%s",
            result.source_name,
            result.status,
            result.discovered,
            result.fetched,
            result.inserted,
            result.updated,
            result.skipped,
            result.failed,
        )
