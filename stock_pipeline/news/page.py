from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urlparse

import bs4
import requests

from .article import Article
from .categories import CATEGORIES


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}

class Fetcher:
    def __init__(self, timeout: tuple[int, int] = (5, 20), retries: int = 3, backoff: float = 2.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url: str) -> requests.Response:
        last_error: requests.RequestException | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 403:
                    raise requests.HTTPError("403 Forbidden", response=response)
                response.raise_for_status()
                if not response.encoding:
                    response.encoding = response.apparent_encoding
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                sleep_time = self.backoff ** (attempt - 1) + random.uniform(0.2, 1.0)
                logging.warning("fetch retry %s/%s url=%s error=%s", attempt, self.retries, url, exc)
                time.sleep(sleep_time)
        if last_error:
            raise last_error
        raise RuntimeError(f"failed to fetch {url}")


class Page:
    def __init__(self, kind: str, pn: int, fetcher: Fetcher | None = None, article_sleep: tuple[float, float] = (2.0, 5.0)):
        self._mobile_base_url = "http://m.10jqka.com.cn/"
        self.fetcher = fetcher or Fetcher()
        self.article_sleep = article_sleep
        self.type = kind

        if kind not in CATEGORIES:
            raise ValueError("该分类不存在: " + str(kind))
        self.url = self.build_url(kind, pn)
        self._analyze_page()
        self.articles: list[Article] | None = None

    @staticmethod
    def build_url(kind: str, pn: int) -> str:
        return "http://news.10jqka.com.cn/" + CATEGORIES[kind] + "/index_" + str(pn) + ".shtml"

    def _analyze_page(self) -> None:
        response = self.fetcher.get(self.url)
        self._soup = bs4.BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)

    def _normalize_article_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc.endswith("10jqka.com.cn"):
            return re.sub(r"https?://\w+\.10jqka\.com\.cn/", self._mobile_base_url, url)
        return url

    def _get_article_links(self) -> list[str]:
        links = []
        seen = set()
        for node in self._soup.select(".arc-title > a"):
            href = node.get("href")
            if not href:
                continue
            url = self._normalize_article_url(str(href))
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
        return links

    def get_article_links(self) -> list[str]:
        return self._get_article_links()

    def fetch_article(self, link: str) -> Article:
        response = self.fetcher.get(link)
        return Article(self.type, response.content, response.encoding, url=response.url)

    def _get_all_article(self) -> list[Article]:
        articles = []
        for link in self._get_article_links():
            try:
                articles.append(self.fetch_article(link))
            except (IndexError, KeyError, ValueError, TypeError, requests.RequestException) as exc:
                logging.warning("parse article failed kind=%s url=%s error=%s", self.type, link, exc)
            finally:
                time.sleep(random.uniform(*self.article_sleep))
        return articles

    def get_articles(self) -> list[Article]:
        if self.articles is None:
            self.articles = self._get_all_article()
        return self.articles
