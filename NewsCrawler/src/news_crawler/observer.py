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


class CompositeRunObserver:
    def __init__(self, observers: list[RunObserver] | tuple[RunObserver, ...]):
        self.observers = tuple(observers)

    def on_run_started(self, result: CrawlResult) -> None:
        self._notify("on_run_started", result)

    def on_article_inserted(self, article: NewsArticle) -> None:
        self._notify("on_article_inserted", article)

    def on_article_duplicated(self, article: NewsArticle, reason: str) -> None:
        self._notify("on_article_duplicated", article, reason)

    def on_provider_failed(self, source_name: str, issue: CrawlIssue) -> None:
        self._notify("on_provider_failed", source_name, issue)

    def on_run_finished(self, result: CrawlResult) -> None:
        self._notify("on_run_finished", result)

    def _notify(self, method: str, *args) -> None:
        for observer in self.observers:
            try:
                getattr(observer, method)(*args)
            except Exception:  # noqa: BLE001 - observers must not break a crawl run
                logging.exception("run_observer_failed observer=%s method=%s", type(observer).__name__, method)


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
