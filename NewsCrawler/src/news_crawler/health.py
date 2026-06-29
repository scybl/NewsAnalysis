from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .runs import CrawlRunRecord


@dataclass(frozen=True)
class SourceHealth:
    source_name: str
    status: str
    consecutive_failures: int
    recent_success_rate: float


class HealthProjector:
    def project(self, source_name: str, records: list[CrawlRunRecord]) -> SourceHealth:
        recent = sorted(records, key=lambda item: item.started_at, reverse=True)[:20]
        failures = 0
        for item in recent:
            if item.status in {"succeeded", "partial"}:
                break
            failures += 1
        successes = sum(item.status == "succeeded" for item in recent)
        rate = successes / len(recent) if recent else 0.0
        latest_status = recent[0].status if recent else ""
        status = "offline" if failures >= 3 else "warning" if failures or latest_status == "partial" or rate < 0.8 else "online"
        return SourceHealth(source_name, status, failures, rate)

    def from_documents(self, source_name: str, rows: list[dict]) -> dict:
        records = [
            CrawlRunRecord(
                run_id=str(row.get("run_id") or ""),
                source_name=source_name,
                status=str(row.get("status") or "failed"),
                started_at=_parse_time(row.get("started_at")),
                finished_at=_parse_time(row.get("finished_at")) if row.get("finished_at") else None,
                metrics=dict(row.get("metrics") or {}),
            )
            for row in rows
        ]
        health = self.project(source_name, records)
        return {
            "source_name": health.source_name,
            "status": health.status,
            "consecutive_failures": health.consecutive_failures,
            "recent_success_rate": health.recent_success_rate,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "last_success_at": next((row.get("finished_at") for row in rows if row.get("status") in {"succeeded", "partial"}), None),
            "last_failure_at": next((row.get("finished_at") for row in rows if row.get("status") == "failed"), None),
            "last_error": next(((row.get("errors") or [{}])[-1].get("message", "") for row in rows if row.get("errors")), ""),
            "latest_status": str(rows[0].get("status") or "") if rows else "",
            "latest_error": ((rows[0].get("errors") or [{}])[-1].get("message", "") if rows and rows[0].get("errors") else ""),
            "last_inserted_count": int(rows[0].get("inserted") or 0) if rows else 0,
            "average_duration_seconds": _average_duration(rows),
        }


def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _average_duration(rows: list[dict]) -> float:
    durations = []
    for row in rows:
        if row.get("started_at") and row.get("finished_at"):
            durations.append((_parse_time(row["finished_at"]) - _parse_time(row["started_at"])).total_seconds())
    return round(sum(durations) / len(durations), 3) if durations else 0.0
