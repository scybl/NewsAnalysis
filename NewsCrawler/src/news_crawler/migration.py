from __future__ import annotations

from datetime import datetime, timezone

from .dedupe import DedupeService
from .models import NewsArticle


def migrate_legacy_collection(repository, source_collection: str = "articles", batch_limit: int = 0) -> dict[str, int]:
    source = repository.articles.database[source_collection]
    stats = {"read": 0, "inserted": 0, "updated": 0, "failed": 0}
    cursor = source.find({})
    if batch_limit > 0:
        cursor = cursor.limit(batch_limit)
    dedupe = DedupeService()
    for row in cursor:
        stats["read"] += 1
        try:
            article = _legacy_article(row)
            outcome = repository.upsert_article(article, dedupe.keys_for(article))
            stats[outcome] += 1
        except Exception:
            stats["failed"] += 1
    return stats


def _legacy_article(row) -> NewsArticle:
    source_name = str(row.get("source_name") or row.get("publisher") or "unknown").strip().lower().replace(" ", "_")
    published = _parse_time(row.get("published_at") or row.get("time"))
    url = str(row.get("canonical_url") or row.get("url") or "")
    title = str(row.get("title") or row.get("headline") or "")
    if not url or not title:
        raise ValueError("legacy article missing url or title")
    return NewsArticle(
        source_name=source_name,
        external_id=str(row.get("external_id") or row.get("seq") or "") or None,
        url=str(row.get("url") or url),
        canonical_url=url,
        title=title,
        summary=str(row.get("summary") or ""),
        content=str(row.get("content") or ""),
        published_at=published,
        section=str(row.get("section") or row.get("type") or ""),
        language=str(row.get("language") or ""),
        author=str(row.get("author") or row.get("source") or ""),
        tags=list(row.get("tags") or []),
        raw_metadata={"legacy_id": str(row.get("_id") or ""), "legacy_schema": row.get("schema_version", "")},
    )


def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
