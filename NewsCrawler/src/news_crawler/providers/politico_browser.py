from __future__ import annotations

import atexit
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities
from .politico import _external_id, parse_politico_article


class PoliticoBrowserProvider:
    name = "politico_browser"
    capabilities = ProviderCapabilities(frozenset({"en"}), supports_historical=False, supports_categories=False)

    def __init__(
        self,
        news_url: str = "https://www.politico.com/news/",
        *,
        headless: bool = True,
        wait_seconds: float = 8,
        profile_dir: str = "",
        proxy: str = "",
        cookies_json: str = "",
        browser_factory=None,
        sleep_fn=time.sleep,
    ):
        self.news_url = news_url
        self.headless = headless
        self.wait_seconds = max(0, wait_seconds)
        self.profile_dir = profile_dir
        self.proxy = proxy
        self.cookies_json = cookies_json
        self.browser_factory = browser_factory or self._default_browser_factory
        self.sleep_fn = sleep_fn
        self._driver = None
        self._cookies_applied = False
        atexit.register(self.close)

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        driver = self._browser()
        self._apply_cookies(driver)
        driver.get(self.news_url)
        self._wait_for_page(driver)
        seen = set()
        max_articles = request.max_articles or 0
        page_count = max(1, request.max_pages)
        emitted = 0
        for page in range(1, page_count + 1):
            html = driver.page_source
            self._raise_if_blocked(html, driver.current_url)
            for url in extract_politico_news_urls(html, driver.current_url or self.news_url):
                if url in seen:
                    continue
                seen.add(url)
                emitted += 1
                yield ArticleRef(
                    self.name,
                    url,
                    external_id=_external_id(url),
                    section="news",
                    metadata={"discovered_from": driver.current_url or self.news_url, "crawl_group": "news", "crawl_page": page},
                )
                if max_articles and emitted >= max_articles:
                    return
            if page < page_count:
                self._scroll(driver)
        if emitted == 0:
            raise RuntimeError("Politico browser found no news links; page may be blocked or not fully loaded")

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        driver = self._browser()
        driver.get(ref.url)
        self._wait_for_page(driver)
        html = driver.page_source
        self._raise_if_blocked(html, driver.current_url or ref.url)
        payload = parse_politico_article(html, driver.current_url or ref.url)
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not title or not content:
            raise ValueError("Politico browser article title or content not found")
        return NewsArticle(
            source_name=self.name,
            external_id=ref.external_id or payload.get("external_id") or _external_id(ref.url),
            url=driver.current_url or ref.url,
            canonical_url=payload.get("canonical_url") or driver.current_url or ref.url,
            title=title,
            summary=str(payload.get("summary") or ""),
            content=content,
            published_at=payload.get("published_at") or datetime.now(timezone.utc),
            section=str(payload.get("section") or ref.section or "news"),
            language="en",
            author=str(payload.get("author") or ""),
            tags=list(payload.get("tags") or []),
            raw_metadata={"discovered_from": ref.metadata.get("discovered_from", "")},
        )

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None

    def _browser(self):
        if self._driver is None:
            self._driver = self.browser_factory()
        return self._driver

    def _default_browser_factory(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            raise RuntimeError("selenium is required for politico_browser provider") from exc

        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1200")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        if self.profile_dir:
            options.add_argument(f"--user-data-dir={self.profile_dir}")
        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy}")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(max(15, int(self.wait_seconds) + 10))
        return driver

    def _apply_cookies(self, driver) -> None:
        if self._cookies_applied or not self.cookies_json:
            return
        cookies = parse_browser_cookies(self.cookies_json)
        if not cookies:
            self._cookies_applied = True
            return
        origin = _origin(self.news_url)
        driver.get(origin)
        self._wait_for_page(driver)
        for cookie in cookies:
            driver.add_cookie(cookie)
        self._cookies_applied = True

    def _wait_for_page(self, driver) -> None:
        if self.wait_seconds:
            self.sleep_fn(self.wait_seconds)

    def _scroll(self, driver) -> None:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        self._wait_for_page(driver)

    def _raise_if_blocked(self, html: str, url: str) -> None:
        lower = html.lower()
        cloudflare_markers = (
            "just a moment",
            "challenges.cloudflare.com",
            "enable javascript and cookies",
            "正在进行安全验证",
            "由 cloudflare 提供",
            "请稍候",
        )
        if any(marker in lower for marker in cloudflare_markers):
            raise RuntimeError(f"Politico browser blocked by Cloudflare challenge: {url}")
        if "verify you are human" in lower or "access denied" in lower:
            raise RuntimeError(f"Politico browser blocked by anti-bot page: {url}")


def extract_politico_news_urls(html: str, base_url: str = "https://www.politico.com/news/") -> list[str]:
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


def parse_browser_cookies(value: str) -> list[dict[str, Any]]:
    raw = json.loads(value)
    if isinstance(raw, dict):
        if isinstance(raw.get("cookies"), list):
            raw = raw["cookies"]
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("POLITICO_BROWSER_COOKIES_JSON must be a cookie object, a list, or {'cookies': [...]}")
    cookies = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        cookie_value = str(item.get("value") or "")
        if not name:
            continue
        cookie = {"name": name, "value": cookie_value}
        for key in ("domain", "path", "secure", "httpOnly", "sameSite"):
            if key in item and item[key] not in (None, ""):
                cookie[key] = item[key]
        if "expiry" in item:
            try:
                cookie["expiry"] = int(item["expiry"])
            except (TypeError, ValueError):
                pass
        elif "expirationDate" in item:
            try:
                cookie["expiry"] = int(float(item["expirationDate"]))
            except (TypeError, ValueError):
                pass
        cookies.append(cookie)
    return cookies


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.politico.com'}/"
