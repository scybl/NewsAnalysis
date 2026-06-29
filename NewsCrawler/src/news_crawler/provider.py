from __future__ import annotations

from typing import Iterable, Protocol

from .models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities


class ProviderError(RuntimeError):
    pass


class ArticleSkipped(ProviderError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NewsProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        ...

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        ...
