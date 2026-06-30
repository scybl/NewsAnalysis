from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any

from .raw_news import raw_news_config


def crawler_status_snapshot(limit: int = 12, failure_limit: int = 200) -> dict[str, Any]:
    """Read NewsCrawler-owned operational collections without controlling it."""
    import pymongo

    config = raw_news_config()
    client = pymongo.MongoClient(
        config.uri,
        serverSelectionTimeoutMS=1800,
        socketTimeoutMS=2500,
    )
    try:
        database = client[config.database]
        expired_runs = _expire_stale_runs(database["crawl_runs"])
        health = list(
            database["source_health"]
            .find({}, {"_id": 0})
            .sort("source_name", pymongo.ASCENDING)
        )
        runs = list(
            database["crawl_runs"]
            .find({}, {"_id": 0})
            .sort("started_at", pymongo.DESCENDING)
            .limit(max(1, min(50, limit)))
        )
        failure_runs = list(
            database["crawl_runs"]
            .find(
                {"$or": [{"errors.0": {"$exists": True}}, {"warnings.0": {"$exists": True}}, {"failed": {"$gt": 0}}]},
                {"_id": 0},
            )
            .sort("started_at", pymongo.DESCENDING)
            .limit(max(1, min(500, failure_limit)))
        )
        running = database["crawl_runs"].count_documents(
            {"status": {"$in": ["queued", "running"]}}
        )
        archived_failures = {
            str(row.get("article_url") or ""): row
            for row in database["failed_article_archive"].find({"status": "archived"}, {"_id": 0, "article_url": 1, "archived_at": 1})
            if row.get("article_url")
        }
        runs_by_source = {}
        for run in runs:
            runs_by_source.setdefault(run.get("source_name"), []).append(run)
        for item in health:
            source_runs = runs_by_source.get(item.get("source_name")) or []
            latest = source_runs[0] if source_runs else {}
            item["latest_status"] = latest.get("status") or item.get("latest_status") or ""
            item["latest_error"] = (
                ((latest.get("errors") or [{}])[-1].get("message", ""))
                if latest.get("errors")
                else item.get("latest_error") or ""
            )
            if source_runs:
                item["recent_success_rate"] = sum(run.get("status") == "succeeded" for run in source_runs) / len(source_runs)
            if item.get("status") == "online" and item["latest_status"] == "partial":
                item["status"] = "warning"
        failure_stats = _failure_stats(failure_runs, item_limit=120, archived_urls=set(archived_failures))
        failure_stats["archived_articles"] = len(archived_failures)
        return {
            "enabled": True,
            "database": config.database,
            "collections": {
                "articles": config.collection,
                "runs": "crawl_runs",
                "health": "source_health",
            },
            "summary": {
                "source_count": len(health),
                "online_count": sum(item.get("status") == "online" for item in health),
                "warning_count": sum(item.get("status") == "warning" for item in health),
                "offline_count": sum(item.get("status") == "offline" for item in health),
                "running_count": running,
                "expired_running_count": expired_runs,
            },
            "health": health,
            "runs": runs,
            "failure_stats": failure_stats,
        }
    except Exception as exc:  # noqa: BLE001 - return a readable admin status
        return {
            "enabled": False,
            "database": config.database,
            "collections": {
                "articles": config.collection,
                "runs": "crawl_runs",
                "health": "source_health",
            },
            "summary": {},
            "health": [],
            "runs": [],
            "failure_stats": _empty_failure_stats(),
            "error": str(exc),
        }
    finally:
        client.close()


def _expire_stale_runs(runs_collection, *, max_age_seconds: int = 300) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    issue = {
        "code": "timeout",
        "message": f"crawl run exceeded max runtime of {max_age_seconds} seconds",
        "article_url": None,
        "retryable": True,
    }
    result = runs_collection.update_many(
        {
            "status": {"$in": ["queued", "running"]},
            "started_at": {"$lt": cutoff_iso},
        },
        {
            "$set": {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "errors": [issue],
                "failed": 1,
                "cancel_requested": True,
            },
            "$inc": {"metrics.timeout": 1},
        },
    )
    return int(getattr(result, "modified_count", 0) or 0)


def _failure_stats(runs: list[dict[str, Any]], *, item_limit: int = 80, archived_urls: set[str] | None = None) -> dict[str, Any]:
    code_counts: Counter[str] = Counter()
    source_counts: dict[str, Counter[str]] = {}
    message_counts: Counter[tuple[str, str]] = Counter()
    items: list[dict[str, Any]] = []
    item_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    archived_urls = archived_urls or set()
    failed_runs = 0
    failed_articles = 0
    warning_articles = 0
    archived_articles = 0
    for run in runs:
        source = str(run.get("source_name") or "unknown")
        source_counts.setdefault(source, Counter())
        errors = list(run.get("errors") or [])
        warnings = list(run.get("warnings") or [])
        if errors or run.get("failed"):
            failed_runs += 1
        warning_articles += len(warnings)
        for issue in errors:
            if str(issue.get("article_url") or "") in archived_urls:
                archived_articles += 1
                continue
            failed_articles += 1
            _record_issue(
                issue,
                run,
                source,
                "error",
                code_counts,
                source_counts[source],
                message_counts,
                items,
                item_groups,
                item_limit,
            )
        for issue in warnings:
            if str(issue.get("article_url") or "") in archived_urls:
                archived_articles += 1
                continue
            _record_issue(
                issue,
                run,
                source,
                "warning",
                code_counts,
                source_counts[source],
                message_counts,
                items,
                item_groups,
                item_limit,
            )
    return {
        "runs_scanned": len(runs),
        "failed_runs": failed_runs,
        "failed_articles": failed_articles,
        "warning_articles": warning_articles,
        "archived_articles": archived_articles,
        "codes": dict(code_counts),
        "by_source": {source: dict(counts) for source, counts in sorted(source_counts.items()) if counts},
        "top_messages": [
            {"code": code, "message": message, "count": count}
            for (code, message), count in message_counts.most_common(12)
        ],
        "items": items,
    }


def _record_issue(
    issue: dict[str, Any],
    run: dict[str, Any],
    source: str,
    severity: str,
    code_counts: Counter[str],
    source_counts: Counter[str],
    message_counts: Counter[tuple[str, str]],
    items: list[dict[str, Any]],
    item_groups: dict[tuple[str, str, str, str], dict[str, Any]],
    item_limit: int,
) -> None:
    message = str(issue.get("message") or "").strip()
    code = _issue_category(str(issue.get("code") or ""), message)
    message_key = _message_group_key(message)
    article_url = str(issue.get("article_url") or "")
    code_counts[code] += 1
    source_counts[code] += 1
    if message:
        message_counts[(code, message_key[:180])] += 1
    group_key = (source, severity, code, message_key)
    if group_key in item_groups:
        item_groups[group_key]["count"] += 1
        item_groups[group_key]["latest_at"] = run.get("started_at") or item_groups[group_key].get("latest_at") or ""
        if article_url and len(item_groups[group_key]["sample_urls"]) < 5:
            item_groups[group_key]["sample_urls"].append(article_url)
        return
    if len(items) < item_limit:
        item = {
            "id": _failure_item_id(source, severity, code, message_key),
            "source_name": source,
            "run_id": run.get("run_id") or "",
            "started_at": run.get("started_at") or "",
            "latest_at": run.get("started_at") or "",
            "severity": severity,
            "code": code,
            "raw_code": issue.get("code") or "",
            "message": message,
            "message_group": message_key,
            "article_url": article_url,
            "sample_urls": [article_url] if article_url else [],
            "count": 1,
            "retryable": bool(issue.get("retryable")),
        }
        item_groups[group_key] = item
        items.append(item)


def _message_group_key(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"\b20\d{6,}\b", "<date>", text)
    text = re.sub(r"\bc\d{6,}\b", "c<id>", text)
    return text[:240]


def _failure_item_id(source: str, severity: str, code: str, message_key: str) -> str:
    seed = "|".join([source, severity, code, message_key])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _issue_category(raw_code: str, message: str) -> str:
    code = raw_code.strip() or "unknown"
    text = message.lower()
    if "title or content not found" in text or "time not found" in text or "empty" in text or "no usable text" in text:
        return "empty_response"
    if "remote end closed connection" in text or "remotedisconnected" in text or "connection reset" in text:
        return "connection_closed"
    if "connection aborted" in text or "connection closed" in text or "broken pipe" in text:
        return "connection_closed"
    if "404" in text or "not found" in text or code == "stale_link":
        return "stale_link"
    if "timeout" in text or code == "timeout":
        return "timeout"
    if "403" in text or "anti-bot" in text or "captcha" in text or "blocked" in text or code == "blocked":
        return "blocked"
    if code in {"parser_error", "unknown"}:
        return "parser_error"
    return code


def _empty_failure_stats() -> dict[str, Any]:
    return {
        "runs_scanned": 0,
        "failed_runs": 0,
        "failed_articles": 0,
        "warning_articles": 0,
        "archived_articles": 0,
        "codes": {},
        "by_source": {},
        "top_messages": [],
        "items": [],
    }
