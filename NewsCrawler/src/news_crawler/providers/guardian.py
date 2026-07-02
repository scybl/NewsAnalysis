from __future__ import annotations

from datetime import datetime

import requests
from bs4 import BeautifulSoup

from ..models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities


class GuardianProvider:
    name = "guardian"
    capabilities = ProviderCapabilities(frozenset({"en"}), supports_historical=True, supports_categories=True)

    def __init__(self, api_key: str, base_url: str = "https://content.guardianapis.com", timeout: float = 30):
        if not api_key:
            raise ValueError("GUARDIAN_API_KEY 未配置")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def discover(self, request: NewsCrawlRequest):
        for page in range(1, max(1, request.max_pages) + 1):
            params = {
                "api-key": self.api_key,
                "page": page,
                "page-size": min(request.max_articles or 200, 200),
                "show-fields": "headline,trailText,bodyText,byline,publication",
                "show-tags": "all",
                "order-by": "newest",
            }
            if request.since:
                params["from-date"] = request.since.date().isoformat()
            if request.until:
                params["to-date"] = request.until.date().isoformat()
            response = self.session.get(f"{self.base_url}/search", params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json().get("response", {})
            for item in payload.get("results", []):
                yield ArticleRef(
                    self.name,
                    item.get("webUrl", ""),
                    external_id=item.get("id"),
                    section=item.get("sectionName", ""),
                    metadata={**item, "crawl_group": "search", "crawl_page": page},
                )
            if page >= int(payload.get("pages") or page):
                break

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        item = ref.metadata
        fields = item.get("fields") or {}
        content = fields.get("bodyText") or ""
        if not content:
            response = self.session.get(
                f"{self.base_url}/{ref.external_id}",
                params={
                    "api-key": self.api_key,
                    "show-fields": "headline,trailText,bodyText,byline,publication",
                    "show-tags": "all",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            item = response.json().get("response", {}).get("content", item)
            fields = item.get("fields") or {}
            content = fields.get("bodyText") or ""
        title = fields.get("headline") or item.get("webTitle") or ""
        if not title:
            raise ValueError("Guardian title not found")
        published = datetime.fromisoformat(str(item.get("webPublicationDate") or "").replace("Z", "+00:00"))
        return NewsArticle(
            source_name=self.name,
            external_id=ref.external_id,
            url=item.get("webUrl") or ref.url,
            canonical_url=item.get("webUrl") or ref.url,
            title=title,
            summary=BeautifulSoup(fields.get("trailText") or "", "lxml").get_text(" ", strip=True),
            content=content,
            published_at=published,
            section=item.get("sectionName") or ref.section,
            language="en",
            author=fields.get("byline") or "",
            tags=_tag_titles(item.get("tags") or []),
            raw_metadata={
                "api_id": item.get("id"),
                "publication": fields.get("publication"),
                "type": item.get("type"),
                "pillar_id": item.get("pillarId"),
                "pillar_name": item.get("pillarName"),
                "section_id": item.get("sectionId"),
                "section_name": item.get("sectionName") or ref.section,
                "tag_ids": _tag_values(item.get("tags") or [], "id"),
                "tag_types": _tag_values(item.get("tags") or [], "type"),
            },
        )


def _tag_titles(tags: list[dict]) -> list[str]:
    values = []
    seen = set()
    for tag in tags:
        value = str(tag.get("webTitle") or tag.get("id") or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _tag_values(tags: list[dict], key: str) -> list[str]:
    values = []
    seen = set()
    for tag in tags:
        value = str(tag.get(key) or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values
