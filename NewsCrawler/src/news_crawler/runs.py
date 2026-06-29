from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CrawlRunRecord:
    run_id: str
    source_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    metrics: dict[str, int | float]
