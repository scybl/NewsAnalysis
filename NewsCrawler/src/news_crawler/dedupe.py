from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass

from .models import ArticleRef, NewsArticle


@dataclass(frozen=True)
class DedupeKeys:
    article_id: str
    external_key: str
    canonical_url: str
    content_hash: str
    title_time_hash: str

    def query_keys(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "article_id": self.article_id,
                "source_external_key": self.external_key,
                "canonical_url": self.canonical_url,
                "content_hash": self.content_hash,
                "title_time_hash": self.title_time_hash,
            }.items()
            if value
        }


class DedupeService:
    def keys_for_ref(self, ref: ArticleRef) -> DedupeKeys:
        canonical = canonicalize_url(ref.url)
        external_key = f"{ref.source_name}:{ref.external_id}" if ref.external_id else ""
        stable_seed = external_key or canonical
        article_id = _sha256(stable_seed)
        return DedupeKeys(article_id, external_key, canonical, "", "")

    def keys_for(self, article: NewsArticle) -> DedupeKeys:
        canonical = canonicalize_url(article.canonical_url or article.url)
        external_key = f"{article.source_name}:{article.external_id}" if article.external_id else ""
        content = normalize_text(article.content)
        content_hash = _sha256(content) if len(content) >= 120 else ""
        day = article.published_at.date().isoformat()
        title_time_hash = _sha256(f"{normalize_text(article.title).lower()}|{day}") if article.title else ""
        stable_seed = external_key or canonical or content_hash or title_time_hash
        article_id = _sha256(stable_seed)
        return DedupeKeys(article_id, external_key, canonical, content_hash, title_time_hash)


def canonicalize_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""
