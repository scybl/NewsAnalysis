#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared news document schema and dedupe helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import urllib.parse
from typing import Any


SCHEMA_VERSION = "news.v1"
MIN_CONTENT_HASH_CHARS = 120


def normalize_news_document(
    info: dict[str, Any],
    publisher_default: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Convert source-specific crawler payloads into one shared MongoDB shape."""
    now = _dt.datetime.utcnow()
    publisher = _clean(info.get("publisher") or publisher_default or "")
    source = _clean(info.get("source") or info.get("source_section") or publisher or source_name or "")
    title = _clean(info.get("title") or info.get("headline") or _nested(info, "document", "title"))
    headline = _clean(info.get("headline") or title)
    summary = _clean(info.get("summary") or info.get("description") or info.get("trailText"))
    content = _clean(info.get("content") or _flatten_document_content(_nested(info, "document", "content")))
    url = _clean(info.get("url"))
    canonical_url = canonicalize_url(info.get("canonical_url") or url)
    raw_time = info.get("time") or info.get("date") or info.get("published_at")
    time_value = normalize_time(raw_time)

    document = {
        "schema_version": SCHEMA_VERSION,
        "publisher": publisher,
        "source_name": source_name or _source_slug(publisher),
        "type": _clean(info.get("type") or info.get("section") or info.get("source_section") or _first(info.get("categories"))),
        "section": _clean(info.get("section") or info.get("source_section") or _first(info.get("categories"))),
        "seq": info.get("seq"),
        "url": url,
        "canonical_url": canonical_url,
        "title": title,
        "headline": headline,
        "summary": summary,
        "content": content,
        "time": time_value,
        "published_at": raw_time,
        "source": source,
        "author": _clean(info.get("author")),
        "language": _clean(info.get("language")),
        "tags": _as_list(info.get("tags")),
        "categories": _as_list(info.get("categories")),
        "entities": info.get("entities") or {},
        "document": info.get("document"),
        "raw_document": info.get("raw_document"),
        "crawler_meta": info.get("crawler_meta") or {},
        "mongodb_meta": info.get("mongodb_meta") or {},
        "content_hash": _content_hash(title, content),
        "title_time_hash": _title_time_hash(title, time_value),
        "created_at": info.get("created_at") or now,
        "updated_at": now,
    }

    if document["content_hash"]:
        document["dedupe_keys"] = [item for item in (canonical_url, document["content_hash"], document["title_time_hash"]) if item]
    return {key: value for key, value in document.items() if not _is_empty(value)}


def dedupe_filter(document: dict[str, Any]) -> dict[str, Any] | None:
    """Build a conservative MongoDB identity filter for cross-source dedupe."""
    clauses = []
    for key in ("seq", "canonical_url", "url", "content_hash"):
        value = document.get(key)
        if value:
            clauses.append({key: value})

    title_time_hash = document.get("title_time_hash")
    if title_time_hash and (document.get("content_hash") or document.get("canonical_url")):
        clauses.append({"title_time_hash": title_time_hash})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def ensure_news_indexes(collection: Any, pymongo_module: Any) -> None:
    """Create shared indexes used by all news crawlers."""
    asc = pymongo_module.ASCENDING
    desc = pymongo_module.DESCENDING
    _create_index(collection, [("seq", asc)], unique=True, sparse=True, name="uk_news_seq")
    _create_index(collection, [("url", asc)], unique=True, sparse=True, name="uk_news_url")
    _create_index(
        collection,
        [("canonical_url", asc)],
        fallback_name="idx_news_canonical_url",
        unique=True,
        sparse=True,
        name="uk_news_canonical_url",
    )
    _create_index(
        collection,
        [("content_hash", asc)],
        fallback_name="idx_news_content_hash",
        unique=True,
        sparse=True,
        name="uk_news_content_hash",
    )
    _create_index(collection, [("title_time_hash", asc)], sparse=True, name="idx_news_title_time_hash")
    _create_index(collection, [("schema_version", asc)], name="idx_news_schema_version")
    _create_index(collection, [("source_name", asc), ("time", desc)], name="idx_news_source_time")
    _create_index(collection, [("title", asc)], sparse=True, name="idx_news_title")
    _create_index(collection, [("time", desc)], name="idx_news_time")
    _create_index(collection, [("type", asc), ("time", desc)], name="idx_news_type_time")
    _create_index(collection, [("publisher", asc), ("time", desc)], name="idx_news_publisher_time")


def _create_index(collection: Any, keys: list[tuple[str, Any]], fallback_name: str | None = None, **kwargs: Any) -> None:
    try:
        collection.create_index(keys, **kwargs)
    except Exception:
        if not fallback_name:
            raise
        fallback_kwargs = {key: value for key, value in kwargs.items() if key != "unique"}
        fallback_kwargs["name"] = fallback_name
        collection.create_index(keys, **fallback_kwargs)


def canonicalize_url(url: Any) -> str:
    text = _clean(url)
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


def normalize_time(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text):
        return text
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _content_hash(title: str, content: str) -> str:
    normalized = _clean(content)
    if len(normalized) < MIN_CONTENT_HASH_CHARS:
        return ""
    return hashlib.sha256(f"{_clean(title)}\n{normalized}".encode("utf-8")).hexdigest()


def _title_time_hash(title: str, time_value: str) -> str:
    normalized_title = _clean(title).lower()
    day = str(time_value or "")[:10]
    if len(normalized_title) < 8 or not day:
        return ""
    return hashlib.sha256(f"{normalized_title}|{day}".encode("utf-8")).hexdigest()


def _flatten_document_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text") or item.get("value") or ""
            if text:
                parts.append(str(text))
        elif item:
            parts.append(str(item))
    return "\n".join(parts)


def _nested(info: dict[str, Any], *keys: str) -> Any:
    current: Any = info
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return ""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _source_slug(value: str) -> str:
    text = _clean(value).lower()
    if "guardian" in text:
        return "guardian"
    if "bloomberg" in text:
        return "bloomberg"
    if "10jqka" in text or "同花顺" in text:
        return "10jqka"
    return text.replace(" ", "_") or "unknown"


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
