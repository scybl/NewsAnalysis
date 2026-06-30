from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities


DEFAULT_FEEDS = {
    "politics": "https://rss.politico.com/politics-news.xml",
    "healthcare": "https://rss.politico.com/healthcare.xml",
    "energy": "https://rss.politico.com/morningenergy.xml",
}

RSS_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class PoliticoProvider:
    name = "politico"
    capabilities = ProviderCapabilities(frozenset({"en"}), supports_historical=False, supports_categories=True)

    def __init__(
        self,
        feed_urls: dict[str, str] | None = None,
        timeout: float = 30,
        session=None,
    ):
        self.feed_urls = dict(feed_urls or DEFAULT_FEEDS)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        seen = set()
        categories = tuple(request.categories or self.feed_urls.keys())
        max_items = request.max_articles or 0
        emitted = 0
        for category in categories:
            feed_url = self.feed_urls.get(category, category if category.startswith(("http://", "https://")) else "")
            if not feed_url:
                raise ValueError(f"unknown Politico category: {category}")
            response = self.session.get(feed_url, timeout=self.timeout)
            response.raise_for_status()
            for item in parse_politico_feed(response.text, feed_url, category):
                if item.url in seen:
                    continue
                seen.add(item.url)
                emitted += 1
                yield item
                if max_items and emitted >= max_items:
                    return

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        payload = dict(ref.metadata)
        if not payload.get("content"):
            response = self.session.get(ref.url, timeout=self.timeout)
            response.raise_for_status()
            payload.update(parse_politico_article(response.text, response.url))
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not title or not content:
            raise ValueError("Politico article title or content not found")
        return NewsArticle(
            source_name=self.name,
            external_id=ref.external_id or payload.get("external_id") or _external_id(ref.url),
            url=payload.get("url") or ref.url,
            canonical_url=payload.get("canonical_url") or payload.get("url") or ref.url,
            title=title,
            summary=str(payload.get("summary") or ""),
            content=content,
            published_at=payload.get("published_at") or datetime.now(timezone.utc),
            section=str(payload.get("section") or ref.section or ""),
            language="en",
            author=str(payload.get("author") or ""),
            tags=list(payload.get("tags") or []),
            raw_metadata={
                "feed_url": payload.get("feed_url", ""),
                "guid": payload.get("guid", ""),
                "media_url": payload.get("media_url", ""),
            },
        )


def parse_politico_feed(xml_text: str, feed_url: str, section: str = "") -> list[ArticleRef]:
    root = ElementTree.fromstring(xml_text)
    refs: list[ArticleRef] = []
    for item in root.findall("./channel/item"):
        title = _xml_text(item, "title")
        url = _xml_text(item, "link")
        guid = _xml_text(item, "guid")
        content_html = _xml_text(item, "content:encoded")
        summary_html = _xml_text(item, "description")
        if not url:
            continue
        refs.append(
            ArticleRef(
                "politico",
                url,
                external_id=guid or _external_id(url),
                section=section,
                metadata={
                    "title": title,
                    "url": url,
                    "canonical_url": url,
                    "guid": guid,
                    "summary": _html_text(summary_html),
                    "content": _html_text(content_html),
                    "published_at": _parse_date(_xml_text(item, "pubDate")),
                    "author": _clean_author(_xml_text(item, "dc:creator") or _xml_text(item, "dc:contributor")),
                    "section": section,
                    "feed_url": feed_url,
                    "media_url": _media_url(item),
                },
            )
        )
    return refs


def parse_politico_article(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    article = _json_ld_article(soup)
    title = str(article.get("headline") or _meta(soup, "og:title") or "").strip()
    content = str(article.get("articleBody") or "").strip()
    if not content:
        paragraphs = [
            node.get_text(" ", strip=True)
            for node in soup.select("article p, [data-testid='BodyWrapper'] p, .story-text p")
        ]
        content = "\n".join(item for item in paragraphs if item)
    raw_time = article.get("datePublished") or _meta(soup, "article:published_time")
    canonical_node = soup.find("link", rel="canonical")
    return {
        "external_id": _external_id(url),
        "url": url,
        "canonical_url": canonical_node.get("href") if canonical_node else url,
        "title": title,
        "summary": str(article.get("description") or _meta(soup, "og:description") or ""),
        "content": content,
        "published_at": _parse_iso_date(str(raw_time or "")),
        "section": str(article.get("articleSection") or ""),
        "author": _author(article.get("author")),
        "tags": _keywords(article.get("keywords")),
    }


def _json_ld_article(soup) -> dict[str, Any]:
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for item in candidates:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() in {"newsarticle", "article"}:
                return item
    return {}


def _xml_text(item, tag: str) -> str:
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        node = item.find(f"{{{RSS_NAMESPACES[prefix]}}}{local}")
    else:
        node = item.find(tag)
    return str(node.text or "").strip() if node is not None else ""


def _html_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "lxml")
    for node in soup.select("script, style"):
        node.decompose()
    parts = [_normalize_text(node.get_text(" ", strip=True)) for node in soup.select("p")]
    if not parts:
        text = soup.get_text(" ", strip=True)
        return _normalize_text(text)
    return "\n".join(part for part in parts if part)


def _normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _media_url(item) -> str:
    for node in list(item):
        if node.tag.endswith("content"):
            return str(node.attrib.get("url") or "")
    return ""


def _parse_date(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_iso_date(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _parse_date(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clean_author(value: str) -> str:
    return re.sub(r"^by\s+", "", value.strip(), flags=re.IGNORECASE)


def _author(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_author(item) for item in value if item)
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def _keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _external_id(url: str) -> str:
    return urlsplit(url).path.rstrip("/").split("/")[-1]


def _meta(soup, property_name: str) -> str:
    node = soup.find("meta", attrs={"property": property_name}) or soup.find("meta", attrs={"name": property_name})
    return str(node.get("content") or "") if node else ""
