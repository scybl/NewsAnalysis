from __future__ import annotations

from typing import Any

from .raw_news import MongoRawNewsRepository


def query_news_library(params: dict[str, list[str]]) -> dict[str, Any]:
    page = _bounded_int(_first(params, "page"), 1, 1, 500)
    page_size = _bounded_int(_first(params, "page_size"), 20, 1, 80)
    repository = None
    try:
        repository = MongoRawNewsRepository()
        result = repository.page(
            query_text=_first(params, "q").strip(),
            source_name=_first(params, "publisher").strip(),
            section=_first(params, "type").strip(),
            days=_bounded_int(_first(params, "days"), 30, 0, 3650),
            page=page,
            page_size=page_size,
        )
        result["items"] = [_public_news_item(row) for row in result["items"]]
        return {"enabled": True, **result, "error": ""}
    except Exception as exc:  # keep admin page readable
        return {"enabled": False, "items": [], "error": str(exc)}
    finally:
        if repository:
            repository.close()


def _public_news_item(row: dict[str, Any]) -> dict[str, Any]:
    content = str(row.get("content") or "")
    summary = str(row.get("summary") or "")
    translation = ((row.get("translations") or {}).get("zh") or {})
    return {
        "publisher": row.get("source_name", ""),
        "type": row.get("section", ""),
        "seq": row.get("external_id", ""),
        "article_id": row.get("article_id", ""),
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "summary": summary,
        "excerpt": _trim(summary or content, 220),
        "content": _trim(content, 3200),
        "time": row.get("published_at", ""),
        "source": row.get("author", ""),
        "translation": _public_translation(translation) if translation else None,
    }


def _public_translation(translation: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": translation.get("provider") or "baidu",
        "engine": translation.get("engine") or "machine",
        "source_language": translation.get("source_language") or "en",
        "target_language": translation.get("target_language") or "zh",
        "translated_at": translation.get("translated_at") or "",
        "content_hash": translation.get("content_hash") or "",
        "title": str(translation.get("title") or ""),
        "summary": str(translation.get("summary") or ""),
        "content": _trim(str(translation.get("content") or ""), 4200),
    }


def _trim(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _first(params: dict[str, list[str]], key: str) -> str:
    return str(params.get(key, [""])[0] or "")


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
