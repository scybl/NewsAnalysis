from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities
from ..provider import ArticleSkipped
from ..provider import ProviderFailure


CATEGORIES = {
    "财经要闻": "today_list",
    "宏观经济": "cjzx_list",
    "产经新闻": "cjkx_list",
    "国际财经": "guojicj_list",
    "金融市场": "jrsc_list",
    "公司新闻": "fssgsxw_list",
    "区域经济": "region_list",
    "财经评论": "fortune_list",
    "财经人物": "cjrw_list",
}

DEFAULT_CATEGORY_HARD_LIMITS = {
    "产经新闻": 30,
    "区域经济": 18,
    "公司新闻": 16,
    "国际财经": 12,
    "财经评论": 6,
    "财经要闻": 5,
    "宏观经济": 3,
    "金融市场": 3,
    "财经人物": 2,
}


class TonghuashunProvider:
    name = "tonghuashun"
    capabilities = ProviderCapabilities(frozenset({"zh"}), supports_historical=True, supports_categories=True)

    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (compatible; NewsCrawler/0.1)"

    def discover(self, request: NewsCrawlRequest):
        categories = request.categories or tuple(CATEGORIES)
        for category in categories:
            if category not in CATEGORIES:
                raise ValueError(f"未知同花顺分类：{category}")
            hard_limit = _category_hard_limit(request, category)
            for page in range(1, hard_limit + 1):
                url = f"http://news.10jqka.com.cn/{CATEGORIES[category]}/index_{page}.shtml"
                response = self.session.get(url, timeout=self.timeout)
                if getattr(response, "status_code", None) == 404:
                    break
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
                nodes = soup.select(".arc-title > a")
                if not nodes:
                    break
                for node in nodes:
                    href = node.get("href")
                    if href:
                        yield ArticleRef(
                            self.name,
                            _mobile_url(href),
                            external_id=_seq(href),
                            section=category,
                            metadata={"crawl_group": category, "crawl_page": page, "crawl_hard_limit": hard_limit},
                        )

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        response = self.session.get(ref.url, timeout=self.timeout)
        if getattr(response, "status_code", None) == 404:
            raise ArticleSkipped("stale_link", "article link returned 404")
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        raw = soup.decode()
        detail = _extract_detail(raw)
        canonical_node = soup.find("link", rel="canonical")
        canonical = detail.get("url") or (canonical_node.get("href") if canonical_node else response.url)
        title = detail.get("title") or _first_text(soup, "#articleTitle, h1")
        content_html = detail.get("content")
        content = (
            BeautifulSoup(content_html, "lxml").get_text("\n", strip=True)
            if content_html
            else _first_text(soup, ".page_content, .article-content")
        )
        image_urls = _image_urls(content_html or "", response.url)
        ocr_used = False
        if title and not content and image_urls:
            content = _ocr_images(self.session, image_urls, timeout=self.timeout)
            ocr_used = bool(content)
            if not content:
                raise ArticleSkipped("image_only", "article contains images but OCR produced no usable text")
        if not title or not content:
            raise ProviderFailure("extraction_missing", "article title or content not found", retryable=True)
        published = _published_at(raw, detail, soup, response.url)
        summary_html = detail.get("summ") or ""
        summary = BeautifulSoup(summary_html, "lxml").get_text("", strip=True) if summary_html else ""
        return NewsArticle(
            source_name=self.name,
            external_id=str(detail.get("seq") or ref.external_id or "") or None,
            url=response.url,
            canonical_url=canonical,
            title=title.strip(),
            summary=summary,
            content=content.replace("\u3000", "").strip(),
            published_at=published,
            section=ref.section,
            language="zh",
            author=str(detail.get("source") or ""),
            raw_metadata={
                "source_payload": {key: detail.get(key) for key in ("seq", "source", "ctime")},
                "image_urls": image_urls,
                "content_extraction": "ocr" if ocr_used else "html",
            },
        )


def _mobile_url(url: str) -> str:
    if urlparse(url).netloc in {"news.10jqka.com.cn", "field.10jqka.com.cn", "bond.10jqka.com.cn"}:
        return re.sub(r"https?://\w+\.10jqka\.com\.cn/", "http://m.10jqka.com.cn/", url)
    return url


def _category_hard_limit(request: NewsCrawlRequest, category: str) -> int:
    if category in request.category_pages:
        return max(1, int(request.category_pages[category]))
    default_limit = max(1, DEFAULT_CATEGORY_HARD_LIMITS.get(category, 1))
    requested_pages = max(1, int(request.max_pages or default_limit))
    return min(requested_pages, default_limit)


def _seq(url: str) -> str | None:
    match = re.search(r"[cm](\d+)", url or "")
    return match.group(1) if match else None


def _extract_detail(text: str) -> dict:
    marker = text.find("detailContent:")
    if marker < 0:
        return {}
    start = text.find("{", marker)
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(text[start:])
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _first_text(soup, selector: str) -> str:
    node = soup.select_one(selector)
    return node.get_text("\n", strip=True) if node else ""


def _published_at(raw: str, detail: dict, soup, article_url: str = "") -> datetime:
    match = re.search(r"ctime:\s*'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'", raw)
    value = match.group(1) if match else str(detail.get("ctime") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?", value):
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\b", raw)
        value = match.group(1) if match else value
    if not value:
        value = _first_text(soup, ".date")
        match = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", value)
        value = match.group(0) if match else ""
    if not value:
        raise ValueError("article time not found")
    if re.fullmatch(r"\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?", value):
        year_match = re.search(r"/(20\d{2})\d{4}/", article_url)
        year = year_match.group(1) if year_match else str(datetime.now(timezone(timedelta(hours=8))).year)
        value = f"{year}-{value}"
    return datetime.fromisoformat(value).replace(tzinfo=timezone(timedelta(hours=8)))


def _image_urls(content_html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(content_html, "lxml")
    urls = []
    for image in soup.select("img"):
        value = str(image.get("src") or image.get("data-src") or "").strip()
        if value.startswith("//"):
            value = "https:" + value
        elif value.startswith("/"):
            parsed = urlparse(base_url)
            value = f"{parsed.scheme or 'https'}://{parsed.netloc}{value}"
        if value.startswith(("http://", "https://")) and value not in urls:
            urls.append(value)
    return urls[:6]


def _ocr_images(session, image_urls: list[str], timeout: float) -> str:
    blocks = []
    for image_url in image_urls:
        try:
            response = session.get(image_url, timeout=timeout)
            response.raise_for_status()
            suffix = ".png" if "png" in str(response.headers.get("content-type") or "").lower() else ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
                image_file.write(response.content)
                image_file.flush()
                result = subprocess.run(
                    ["tesseract", image_file.name, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                    capture_output=True,
                    text=True,
                    timeout=max(15, int(timeout * 2)),
                    check=False,
                )
            text = _normalize_ocr_text(result.stdout)
            if _usable_ocr_text(text):
                blocks.append(text)
        except (OSError, requests.RequestException, subprocess.SubprocessError):
            continue
    return "\n\n".join(blocks)


def _normalize_ocr_text(value: str) -> str:
    lines = []
    for raw_line in str(value or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", line))
        has_number = bool(re.search(r"\d", line))
        if chinese_count < 6 and not (has_number and chinese_count >= 3):
            continue
        if not line or line in lines:
            continue
        lines.append(line)
    return "\n".join(lines)


def _usable_ocr_text(value: str) -> bool:
    meaningful = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", value)
    chinese = re.findall(r"[\u4e00-\u9fff]", value)
    return len(meaningful) >= 25 and len(chinese) >= 15
