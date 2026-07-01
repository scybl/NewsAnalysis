from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import math
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
        active_pauses = list(
            database["source_pauses"]
            .find({"active": True}, {"_id": 0})
            .sort("paused_at", pymongo.DESCENDING)
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
                "paused_count": len(active_pauses),
                "running_count": running,
                "expired_running_count": expired_runs,
            },
            "health": health,
            "active_pauses": active_pauses,
            "alerts": _source_pause_alerts(active_pauses),
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
            "active_pauses": [],
            "alerts": [],
            "runs": [],
            "failure_stats": _empty_failure_stats(),
            "error": str(exc),
        }
    finally:
        client.close()


def news_crawler_prometheus_metrics(snapshot: dict[str, Any] | None = None) -> str:
    """Render NewsCrawler monitor state as Prometheus exposition text."""
    payload = snapshot if snapshot is not None else crawler_status_snapshot(limit=25, failure_limit=300)
    lines: list[str] = [
        "# HELP news_crawler_up 1 if NewsAnalysis can read NewsCrawler monitor collections.",
        "# TYPE news_crawler_up gauge",
        f"news_crawler_up {1 if payload.get('enabled') else 0}",
    ]
    _append_gauge(lines, "news_crawler_sources", "Configured NewsCrawler sources by aggregate state.", {
        "total": _number(payload.get("summary", {}).get("source_count")),
        "online": _number(payload.get("summary", {}).get("online_count")),
        "warning": _number(payload.get("summary", {}).get("warning_count")),
        "offline": _number(payload.get("summary", {}).get("offline_count")),
        "paused": _number(payload.get("summary", {}).get("paused_count")),
        "running": _number(payload.get("summary", {}).get("running_count")),
        "expired_running": _number(payload.get("summary", {}).get("expired_running_count")),
    })

    lines.extend([
        "# HELP news_crawler_source_status Source health status as one-hot gauges.",
        "# TYPE news_crawler_source_status gauge",
    ])
    for item in payload.get("health") or []:
        source = str(item.get("source_name") or "unknown")
        current = str(item.get("status") or "unknown")
        for status in ("online", "warning", "offline", "paused", "maintenance", "unknown"):
            lines.append(f'news_crawler_source_status{{source="{_label(source)}",status="{status}"}} {1 if current == status else 0}')

    source_fields = {
        "news_crawler_source_recent_success_rate": ("Recent source success rate from the health projection.", "recent_success_rate"),
        "news_crawler_source_consecutive_failures": ("Consecutive failed runs by source.", "consecutive_failures"),
        "news_crawler_source_last_inserted": ("Articles inserted by the latest projected successful run.", "last_inserted_count"),
        "news_crawler_source_average_duration_seconds": ("Average crawler run duration by source.", "average_duration_seconds"),
    }
    for metric, (help_text, field) in source_fields.items():
        lines.extend([f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge"])
        for item in payload.get("health") or []:
            source = str(item.get("source_name") or "unknown")
            lines.append(f'{metric}{{source="{_label(source)}"}} {_number(item.get(field))}')

    timestamp_fields = {
        "news_crawler_source_last_success_timestamp_seconds": ("Unix timestamp of the latest successful source run.", "last_success_at"),
        "news_crawler_source_last_failure_timestamp_seconds": ("Unix timestamp of the latest failed source run.", "last_failure_at"),
    }
    for metric, (help_text, field) in timestamp_fields.items():
        lines.extend([f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge"])
        for item in payload.get("health") or []:
            source = str(item.get("source_name") or "unknown")
            lines.append(f'{metric}{{source="{_label(source)}"}} {_timestamp_seconds(item.get(field))}')

    run_counts: Counter[tuple[str, str]] = Counter()
    discovered: Counter[str] = Counter()
    inserted: Counter[str] = Counter()
    updated: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    for run in payload.get("runs") or []:
        source = str(run.get("source_name") or "unknown")
        status = str(run.get("status") or "unknown")
        run_counts[(source, status)] += 1
        discovered[source] += int(_number(run.get("discovered")))
        inserted[source] += int(_number(run.get("inserted")))
        updated[source] += int(_number(run.get("updated")))
        failed[source] += int(_number(run.get("failed")))
    lines.extend(["# HELP news_crawler_recent_runs Recent crawl runs exposed by source and status.", "# TYPE news_crawler_recent_runs gauge"])
    for (source, status), count in sorted(run_counts.items()):
        lines.append(f'news_crawler_recent_runs{{source="{_label(source)}",status="{_label(status)}"}} {count}')
    for metric, help_text, values in (
        ("news_crawler_recent_discovered_articles", "Recently discovered articles by source.", discovered),
        ("news_crawler_recent_inserted_articles", "Recently inserted articles by source.", inserted),
        ("news_crawler_recent_updated_articles", "Recently updated articles by source.", updated),
        ("news_crawler_recent_failed_articles", "Recently failed articles by source.", failed),
    ):
        lines.extend([f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge"])
        for source, value in sorted(values.items()):
            lines.append(f'{metric}{{source="{_label(source)}"}} {value}')

    failure_stats = payload.get("failure_stats") or {}
    lines.extend([
        "# HELP news_crawler_recent_failure_articles Failure diagnostics from the recent scan window.",
        "# TYPE news_crawler_recent_failure_articles gauge",
        f'news_crawler_recent_failure_articles{{state="failed"}} {_number(failure_stats.get("failed_articles"))}',
        f'news_crawler_recent_failure_articles{{state="warning"}} {_number(failure_stats.get("warning_articles"))}',
        f'news_crawler_recent_failure_articles{{state="archived"}} {_number(failure_stats.get("archived_articles"))}',
    ])
    lines.extend(["# HELP news_crawler_recent_failure_codes Failure diagnostics by normalized issue code.", "# TYPE news_crawler_recent_failure_codes gauge"])
    for code, count in sorted((failure_stats.get("codes") or {}).items()):
        lines.append(f'news_crawler_recent_failure_codes{{code="{_label(code)}"}} {_number(count)}')
    lines.extend(["# HELP news_crawler_recent_failure_codes_by_source Failure diagnostics by source and normalized issue code.", "# TYPE news_crawler_recent_failure_codes_by_source gauge"])
    for source, codes in sorted((failure_stats.get("by_source") or {}).items()):
        for code, count in sorted((codes or {}).items()):
            lines.append(f'news_crawler_recent_failure_codes_by_source{{source="{_label(source)}",code="{_label(code)}"}} {_number(count)}')

    return "\n".join(lines) + "\n"


def _append_gauge(lines: list[str], metric: str, help_text: str, values: dict[str, float]) -> None:
    lines.extend([f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge"])
    for state, value in values.items():
        lines.append(f'{metric}{{state="{_label(state)}"}} {value}')


def _number(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if math.isnan(number) or math.isinf(number):
        return 0
    return int(number) if number.is_integer() else number


def _timestamp_seconds(value: Any) -> int:
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _label(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _expire_stale_runs(runs_collection, *, max_age_seconds: int = 300) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    stale_runs = list(
        runs_collection.find(
            {
                "status": {"$in": ["queued", "running"]},
                "started_at": {"$lt": cutoff_iso},
            },
            {"started_at": 1, "failed": 1},
        )
    )
    expired = 0
    for run in stale_runs:
        issue = {
            "code": "timeout",
            "message": f"crawl run exceeded max runtime of {max_age_seconds} seconds",
            "article_url": None,
            "retryable": True,
        }
        result = runs_collection.update_one(
            {"_id": run.get("_id"), "status": {"$in": ["queued", "running"]}},
            {
                "$set": {
                    "status": "failed",
                    "finished_at": _stale_finished_at(run.get("started_at"), max_age_seconds),
                    "errors": [issue],
                    "failed": max(1, int(run.get("failed") or 0)),
                    "cancel_requested": True,
                },
                "$inc": {"metrics.timeout": 1},
            },
        )
        expired += int(getattr(result, "modified_count", 0) or 0)
    return expired


def _stale_finished_at(started_at: Any, max_age_seconds: int) -> str:
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError:
        started = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (started + timedelta(seconds=max_age_seconds)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _source_pause_alerts(pauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    for item in pauses:
        source = str(item.get("source_name") or "")
        reason = str(item.get("reason") or "")
        if not source:
            continue
        alerts.append(
            {
                "type": "source_auto_paused",
                "severity": "warning",
                "source_name": source,
                "title": f"{source} 已自动暂停",
                "message": reason or "数据源凭据疑似过期，请更新后再启用。",
                "paused_at": item.get("paused_at") or "",
                "issue_code": item.get("issue_code") or "",
                "run_id": item.get("run_id") or "",
            }
        )
    return alerts
