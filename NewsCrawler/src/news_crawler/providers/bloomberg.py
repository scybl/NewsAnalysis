from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities
from ..provider import ProviderFailure

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - optional production hardening
    curl_requests = None


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
        api_url: str = "https://www.bloomberg.com/lineup-next/api/stories",
        proxy: str = "",
        use_api: bool = True,
        cookies_json: str = "",
        require_login_cookie: bool = False,
    ):
        self.latest_url = latest_url
        self.api_url = api_url
        self.use_api = use_api
        self.require_login_cookie = require_login_cookie
        self.checkpoints = checkpoint_repository
        self.timeout = timeout
        self.uses_curl_cffi = bool(curl_requests and session is None)
        self.session = session or (curl_requests.Session() if curl_requests else requests.Session())
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            }
        )
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header
        self.cookies_dict = parse_browser_cookies(cookies_json) if cookies_json else {}
        if self.cookies_dict and hasattr(self.session, "cookies"):
            self.session.cookies.update(self.cookies_dict)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        self._validate_credentials()
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
            urls, discovered_from = self._discover_page(page)
            for article_url in urls:
                if article_url in seen:
                    continue
                seen.add(article_url)
                pending.append(article_url)
                if self.checkpoints:
                    self.checkpoints.save_checkpoint(
                        self.name,
                        "discovery",
                        {"page": page, "last_url": discovered_from, "discovered": len(seen), "pending_urls": pending},
                    )
                yield ArticleRef(
                    self.name,
                    article_url,
                    external_id=_external_id(article_url),
                    metadata={"discovered_from": discovered_from, "crawl_group": "latest", "crawl_page": page},
                )
            if not urls:
                break

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        self._validate_credentials()
        response = self._get(ref.url, headers=_article_headers())
        response.raise_for_status()
        if _blocked(response.text):
            raise ProviderFailure(
                "blocked",
                "Bloomberg 返回登录、反爬或验证码页面。",
                retryable=False,
            )
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

    def _discover_page(self, page: int) -> tuple[list[str], str]:
        if self.use_api:
            try:
                self._warm_session()
                response = self._get(
                    self.api_url,
                    headers=_api_headers(),
                    params={
                        "types": "ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS",
                        "pageNumber": str(page),
                        "limit": "25",
                    },
                )
                response.raise_for_status()
                urls = extract_bloomberg_api_urls(response.text)
                if urls:
                    return urls, response.url
            except Exception:
                if page > 1:
                    raise
        url = self.latest_url if page == 1 else f"{self.latest_url}?page={page}"
        response = self._get(url, headers=_page_headers("https://www.bloomberg.com/"))
        response.raise_for_status()
        return extract_bloomberg_urls(response.text, response.url), response.url

    def _warm_session(self) -> None:
        for url, referer in (
            ("https://www.bloomberg.com/asia", ""),
            (self.latest_url, "https://www.bloomberg.com/"),
        ):
            try:
                self._get(url, headers=_page_headers(referer))
            except Exception:
                continue

    def _get(self, url: str, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        if self.uses_curl_cffi:
            kwargs.setdefault("impersonate", "chrome120")
        return self.session.get(url, **kwargs)

    def _validate_credentials(self) -> None:
        if self.require_login_cookie:
            validate_bloomberg_login_cookies(self.cookies_dict or _cookie_header_dict(self.session.headers.get("Cookie", "")))


class BloombergCredentialExpired(ProviderFailure):
    def __init__(self, message: str):
        super().__init__("credential_expired", message, retryable=False, pause_source=True)


def parse_browser_cookies(cookies_json: str) -> dict[str, str]:
    text = str(cookies_json or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Bloomberg cookies JSON 格式无效。") from exc
    if not isinstance(data, list):
        raise ValueError("Bloomberg cookies JSON 必须是数组。")
    cookies: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        if name and value and "bloomberg.com" in domain.lower():
            cookies[name] = value
    return cookies


def validate_bloomberg_login_cookies(cookies: dict[str, str]) -> None:
    indicators = ("_pxhd", "_px2", "session_id", "agent_id", "_breg-uid")
    valid = [name for name in indicators if len(str(cookies.get(name) or "")) > 10]
    if "_breg-uid" not in valid:
        raise BloombergCredentialExpired("缺少 Bloomberg 登录 Cookie _breg-uid，疑似未登录或 cookie 已过期，已自动暂停 Bloomberg。")
    if len(valid) < 4:
        raise BloombergCredentialExpired(f"Bloomberg 登录 Cookie 不完整：{len(valid)}/{len(indicators)} 个关键 cookie 有效，已自动暂停 Bloomberg。")


def _cookie_header_dict(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in str(cookie_header or "").split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def extract_bloomberg_api_urls(json_text: str) -> list[str]:
    data = json.loads(json_text)
    stories = _story_items(data)
    candidates = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        for key in ("url", "uri", "path", "link", "href", "longURL"):
            value = story.get(key)
            if value:
                candidates.append(str(value))
                break
    return _canonical_article_urls(candidates, "https://www.bloomberg.com/latest")


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
    return _canonical_article_urls(candidates, base_url)


def parse_bloomberg_article(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    story = _next_story(soup)
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
    title = str(story.get("headline") or article.get("headline") or _meta(soup, "og:title") or "").strip()
    content = _story_content(story) or str(article.get("articleBody") or "").strip()
    if not content:
        paragraphs = [
            node.get_text(" ", strip=True)
            for node in soup.select("article p, [data-component='paragraph'] p, [data-testid='paragraph']")
        ]
        content = "\n".join(item for item in paragraphs if item)
    if not title or not content:
        raise ValueError("Bloomberg article title or content not found")
    raw_time = story.get("publishedAt") or article.get("datePublished") or _meta(soup, "article:published_time")
    published = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")) if raw_time else datetime.now(timezone.utc)
    author_value = story.get("authors") or article.get("author")
    if isinstance(author_value, list):
        author = ", ".join(str(item.get("name") if isinstance(item, dict) else item) for item in author_value)
    elif isinstance(author_value, dict):
        author = str(author_value.get("name") or "")
    else:
        author = str(author_value or "")
    canonical_node = soup.find("link", rel="canonical")
    tags = [str(item.get("name") or "") for item in story.get("contentTags", []) if isinstance(item, dict) and item.get("name")]
    return {
        "external_id": _external_id(url),
        "canonical_url": canonical_node.get("href") if canonical_node else url,
        "title": title,
        "summary": str(story.get("summaryText") or article.get("description") or _meta(soup, "og:description") or ""),
        "content": content,
        "published_at": published,
        "section": str(story.get("pillar") or article.get("articleSection") or ""),
        "author": author,
        "tags": tags or _keywords(article.get("keywords")),
    }


def _story_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for path in (
        ("stories",),
        ("data", "stories"),
        ("results",),
        ("data", "results"),
        ("articles",),
        ("data", "articles"),
        ("items",),
        ("data", "items"),
    ):
        value = data
        for key in path:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                value = None
                break
        if isinstance(value, list):
            return value
    return []


def _canonical_article_urls(candidates: list[str], base_url: str) -> list[str]:
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


def _next_story(soup) -> dict[str, Any]:
    node = soup.find("script", id="__NEXT_DATA__")
    if not node:
        return {}
    try:
        data = json.loads(node.string or node.get_text())
        story = data["props"]["pageProps"]["story"]
        return story if isinstance(story, dict) else {}
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}


def _story_content(story: dict[str, Any]) -> str:
    sections = []
    current = []
    for item in ((story.get("body") or {}).get("content") or []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "heading":
            if current:
                sections.append(" ".join(current).strip())
                current = []
            heading = _story_text(item)
            if heading:
                current.append(heading)
        elif item.get("type") == "paragraph":
            text = _story_text(item)
            if text:
                current.append(text)
    if current:
        sections.append(" ".join(current).strip())
    return "\n".join(item for item in sections if item)


def _story_text(item: dict[str, Any]) -> str:
    parts = []
    for child in item.get("content") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "text":
            parts.append(str(child.get("value") or ""))
        elif child.get("type") in {"link", "entity"}:
            parts.append(_story_text(child))
    return " ".join(part.strip() for part in parts if part and part.strip())


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
    return any(
        marker in lower
        for marker in (
            "px-captcha",
            "verify you are human",
            "access denied",
            "sign in to continue",
            "login.bloomberg.com",
            "subscribe to continue",
            "please enable cookies",
        )
    )


def _page_headers(referer: str = "") -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _api_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Cache-Control": "no-cache",
        "DNT": "1",
        "Origin": "https://www.bloomberg.com",
        "Pragma": "no-cache",
        "Referer": "https://www.bloomberg.com/latest",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }


def _article_headers() -> dict[str, str]:
    headers = _page_headers("https://www.bloomberg.com/asia")
    headers["Sec-Fetch-User"] = "?1"
    return headers
