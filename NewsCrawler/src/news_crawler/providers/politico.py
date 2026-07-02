from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities
from ..provider import ProviderFailure


DEFAULT_FEEDS = {
    "picks": "https://www.politico.com/rss/politicopicks.xml",
}
DEFAULT_NEWS_URL = "https://www.politico.com/"

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
        fetch_article_pages: bool = False,
        discovery_mode: str = "site",
        news_url: str = DEFAULT_NEWS_URL,
        source_name: str = "politico",
        proxy: str = "",
        cookies_json: str = "",
        curl_getter=None,
    ):
        self.name = source_name
        self.feed_urls = dict(feed_urls or DEFAULT_FEEDS)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.fetch_article_pages = fetch_article_pages
        self.discovery_mode = discovery_mode
        self.news_url = news_url
        self.proxy = proxy
        self.curl_getter = curl_getter or (lambda url, headers, timeout: _curl_get(url, headers, timeout, proxy=self.proxy))
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.politico.com/",
            }
        )
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        cookie_header = _cookie_header(cookies_json)
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        if self.discovery_mode == "site":
            yield from self._discover_site(request)
            return
        if self.discovery_mode != "rss":
            raise ValueError(f"unknown Politico discovery mode: {self.discovery_mode}")

        seen = set()
        categories = tuple(request.categories or self.feed_urls.keys())
        max_items = request.max_articles or 0
        emitted = 0
        for category in categories:
            feed_url = self.feed_urls.get(category, category if category.startswith(("http://", "https://")) else "")
            if not feed_url:
                raise ValueError(f"unknown Politico category: {category}")
            feed_text = self._fetch_feed(feed_url)
            for item in parse_politico_feed(feed_text, feed_url, category, source_name=self.name):
                if item.url in seen:
                    continue
                seen.add(item.url)
                emitted += 1
                yield item
                if max_items and emitted >= max_items:
                    return

    def _discover_site(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        seen = set()
        max_items = request.max_articles or 0
        emitted = 0
        page_count = max(1, request.max_pages)
        for page in range(1, page_count + 1):
            html = self._fetch_text(self.news_url)
            for url in extract_politico_news_urls(html, self.news_url):
                if url in seen:
                    continue
                seen.add(url)
                emitted += 1
                yield ArticleRef(
                    self.name,
                    url,
                    external_id=_external_id(url),
                    section="news",
                    metadata={"discovered_from": self.news_url, "crawl_group": "news", "crawl_page": page},
                )
                if max_items and emitted >= max_items:
                    return
            if emitted:
                return
        raise ProviderFailure("blocked", "Politico site found no news links; page may be blocked or not fully loaded", retryable=True)

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        payload = dict(ref.metadata)
        if self.discovery_mode == "site" or (not payload.get("content") and self.fetch_article_pages):
            payload.update(self._fetch_article_payload(ref.url))
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or payload.get("summary") or title).strip()
        if not title or not content:
            raise ProviderFailure("extraction_missing", "Politico article title or content not found", retryable=True)
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
                "discovered_from": payload.get("discovered_from", ref.metadata.get("discovered_from", "")),
                "crawl_group": payload.get("crawl_group", ref.metadata.get("crawl_group", "")),
            },
        )

    def _fetch_feed(self, feed_url: str) -> str:
        return self._fetch_text(feed_url)

    def _fetch_text(self, url: str) -> str:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return self.curl_getter(url, dict(self.session.headers), self.timeout)
        status_code = int(getattr(response, "status_code", 200) or 200)
        if _needs_curl_fallback(response):
            try:
                return self.curl_getter(url, dict(self.session.headers), self.timeout)
            except Exception:
                if status_code == 429:
                    raise ProviderFailure("rate_limited", f"Politico returned HTTP 429 for {url}", retryable=True)
                if status_code == 403:
                    raise ProviderFailure("blocked", f"Politico returned HTTP 403 for {url}", retryable=True)
                response.raise_for_status()
                raise
        response.raise_for_status()
        return response.text

    def _fetch_article_payload(self, url: str) -> dict[str, Any]:
        html = self._fetch_text(url)
        payload = parse_politico_article(html, url)
        if payload.get("title") and payload.get("content"):
            return payload
        try:
            fallback_payload = parse_politico_article(self.curl_getter(url, {}, self.timeout), url)
        except Exception:
            return payload
        return fallback_payload if fallback_payload.get("title") or fallback_payload.get("content") else payload


def parse_politico_feed(
    xml_text: str,
    feed_url: str,
    section: str = "",
    *,
    source_name: str = "politico",
) -> list[ArticleRef]:
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
                source_name,
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
        content = _article_paragraph_text(soup)
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


def _article_paragraph_text(soup) -> str:
    paragraphs = []
    seen = set()
    selectors = (
        "article p",
        "[data-testid='BodyWrapper'] p",
        "[data-module='ArticleBody'] p",
        ".article__content p",
        ".body-content p",
        ".story-content p",
        ".story-text__paragraph",
        ".story-text p",
        "[class*='RichText'] p",
        "[class*='story-text'] p",
        "p.is-magazine",
    )
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            text = _normalize_text(node.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_politico_news_urls(html: str, base_url: str = DEFAULT_NEWS_URL) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen = set()
    for node in soup.select("a[href]"):
        raw_url = node.get("href") or ""
        url = _canonical_news_url(urljoin(base_url, raw_url))
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _canonical_news_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.netloc.endswith("politico.com"):
        return ""
    path = parsed.path.rstrip("/")
    if not path.startswith("/news/"):
        return ""
    if path in {"/news", "/news/"}:
        return ""
    if not re.search(r"/\d{4}/\d{2}/\d{2}/", path):
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"


def _needs_curl_fallback(response) -> bool:
    if getattr(response, "status_code", 200) in {403, 429}:
        return True
    text = str(getattr(response, "text", "") or "")[:2000].lower()
    return any(
        marker in text
        for marker in (
            "just a moment",
            "challenges.cloudflare.com",
            "enable javascript and cookies",
            "cf-browser-verification",
        )
    )


def _curl_get(url: str, headers: dict[str, str], timeout: float, *, proxy: str = "") -> str:
    command = ["curl", "-L", "--max-time", str(max(1, int(timeout))), "--silent", "--show-error"]
    if proxy:
        command.extend(["--proxy", proxy])
    for name in ("User-Agent", "Accept", "Accept-Language", "Referer", "Cookie"):
        value = str(headers.get(name) or "").strip()
        if value:
            command.extend(["-H", f"{name}: {value}"])
    command.append(url)
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(2, timeout + 5), check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"curl failed with exit code {result.returncode}")
    return result.stdout


def _cookie_header(cookies_json: str) -> str:
    text = str(cookies_json or "").strip()
    if not text:
        return ""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return text if "=" in text else ""
    if isinstance(raw, dict):
        if isinstance(raw.get("cookies"), list):
            raw = raw["cookies"]
        elif raw.get("name") and raw.get("value"):
            raw = [raw]
        else:
            raw = [{"name": key, "value": value} for key, value in raw.items()]
    if not isinstance(raw, list):
        return ""
    pairs = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if name and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _json_ld_article(soup) -> dict[str, Any]:
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        article = _find_json_ld_article(value)
        if article:
            return article
    return {}


def _find_json_ld_article(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            article = _find_json_ld_article(item)
            if article:
                return article
    if isinstance(value, dict):
        item_type = value.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if {str(item).lower() for item in types} & {"newsarticle", "article"}:
            return value
        graph_article = _find_json_ld_article(value.get("@graph"))
        if graph_article:
            return graph_article
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
