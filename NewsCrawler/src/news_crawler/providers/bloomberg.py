from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities


class BloombergProvider:
    name = "bloomberg"
    capabilities = ProviderCapabilities(frozenset({"en"}), supports_historical=False, supports_categories=True)

    def __init__(
        self,
        latest_url: str = "https://www.bloomberg.com/latest",
        cookie_header: str = "",
        checkpoint_repository=None,
        timeout: float = 30,
        session=None,
    ):
        self.latest_url = latest_url
        self.checkpoints = checkpoint_repository
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        seen = set()
        checkpoint = self.checkpoints.load_checkpoint(self.name, "discovery") if self.checkpoints else None
        pending = list((checkpoint or {}).get("pending_urls") or [])
        for article_url in pending:
            seen.add(article_url)
            yield ArticleRef(
                self.name,
                article_url,
                external_id=_external_id(article_url),
                metadata={"checkpoint": True, "crawl_group": "checkpoint", "crawl_page": 0},
            )
        for page in range(1, max(1, request.max_pages) + 1):
            url = self.latest_url if page == 1 else f"{self.latest_url}?page={page}"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            urls = extract_bloomberg_urls(response.text, response.url)
            for article_url in urls:
                if article_url in seen:
                    continue
                seen.add(article_url)
                pending.append(article_url)
                if self.checkpoints:
                    self.checkpoints.save_checkpoint(
                        self.name,
                        "discovery",
                        {"page": page, "last_url": response.url, "discovered": len(seen), "pending_urls": pending},
                    )
                yield ArticleRef(
                    self.name,
                    article_url,
                    external_id=_external_id(article_url),
                    metadata={"discovered_from": response.url, "crawl_group": "latest", "crawl_page": page},
                )
            if not urls:
                break

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        response = self.session.get(ref.url, timeout=self.timeout)
        response.raise_for_status()
        if _blocked(response.text):
            raise RuntimeError("Bloomberg anti-bot or paywall challenge detected")
        payload = parse_bloomberg_article(response.text, response.url)
        article = NewsArticle(
            source_name=self.name,
            external_id=ref.external_id or payload.get("external_id"),
            url=response.url,
            canonical_url=payload.get("canonical_url") or response.url,
            title=payload["title"],
            summary=payload.get("summary", ""),
            content=payload.get("content", ""),
            published_at=payload["published_at"],
            section=payload.get("section", ""),
            language="en",
            author=payload.get("author", ""),
            tags=payload.get("tags", []),
            raw_metadata={"discovered_from": ref.metadata.get("discovered_from", "")},
        )
        if self.checkpoints:
            checkpoint = self.checkpoints.load_checkpoint(self.name, "discovery") or {}
            pending = [url for url in checkpoint.get("pending_urls", []) if url != ref.url]
            self.checkpoints.save_checkpoint(self.name, "discovery", {**checkpoint, "pending_urls": pending})
        return article


def extract_bloomberg_urls(html: str, base_url: str = "https://www.bloomberg.com/latest") -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []
    for node in soup.select("a[href]"):
        candidates.append(node.get("href") or "")
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data and next_data.string:
        try:
            _collect_urls(json.loads(next_data.string), candidates)
        except json.JSONDecodeError:
            pass
    result = []
    seen = set()
    for value in candidates:
        url = urljoin(base_url, value)
        parsed = urlsplit(url)
        if not parsed.netloc.endswith("bloomberg.com") or not _article_path(parsed.path):
            continue
        canonical = f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def parse_bloomberg_article(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    objects = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
            objects.extend(value if isinstance(value, list) else [value])
        except (json.JSONDecodeError, TypeError):
            continue
    article = next(
        (
            item
            for item in objects
            if isinstance(item, dict)
            and str(item.get("@type", "")).lower() in {"newsarticle", "article", "reportagenewsarticle"}
        ),
        {},
    )
    title = str(article.get("headline") or _meta(soup, "og:title") or "").strip()
    content = str(article.get("articleBody") or "").strip()
    if not content:
        paragraphs = [
            node.get_text(" ", strip=True)
            for node in soup.select("article p, [data-component='paragraph'] p, [data-testid='paragraph']")
        ]
        content = "\n".join(item for item in paragraphs if item)
    if not title or not content:
        raise ValueError("Bloomberg article title or content not found")
    raw_time = article.get("datePublished") or _meta(soup, "article:published_time")
    published = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")) if raw_time else datetime.now(timezone.utc)
    author_value = article.get("author")
    if isinstance(author_value, list):
        author = ", ".join(str(item.get("name") if isinstance(item, dict) else item) for item in author_value)
    elif isinstance(author_value, dict):
        author = str(author_value.get("name") or "")
    else:
        author = str(author_value or "")
    canonical_node = soup.find("link", rel="canonical")
    return {
        "external_id": _external_id(url),
        "canonical_url": canonical_node.get("href") if canonical_node else url,
        "title": title,
        "summary": str(article.get("description") or _meta(soup, "og:description") or ""),
        "content": content,
        "published_at": published,
        "section": str(article.get("articleSection") or ""),
        "author": author,
        "tags": _keywords(article.get("keywords")),
    }


def _collect_urls(value: Any, output: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"url", "href", "canonicalurl"} and isinstance(item, str):
                output.append(item)
            else:
                _collect_urls(item, output)
    elif isinstance(value, list):
        for item in value:
            _collect_urls(item, output)


def _article_path(path: str) -> bool:
    return bool(re.search(r"/news/articles?/", path) or re.search(r"/(?:features|opinion)/", path))


def _external_id(url: str) -> str:
    return urlsplit(url).path.rstrip("/").split("/")[-1]


def _meta(soup, property_name: str) -> str:
    node = soup.find("meta", attrs={"property": property_name}) or soup.find("meta", attrs={"name": property_name})
    return str(node.get("content") or "") if node else ""


def _keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _blocked(html: str) -> bool:
    lower = html.lower()
    return any(marker in lower for marker in ("px-captcha", "verify you are human", "access denied"))
