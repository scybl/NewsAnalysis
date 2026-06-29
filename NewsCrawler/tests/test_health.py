from datetime import datetime, timedelta, timezone

from news_crawler.health import HealthProjector


def test_health_projection_contains_traceable_metrics():
    now = datetime.now(timezone.utc)
    rows = [{
        "run_id": "1",
        "source_name": "guardian",
        "status": "succeeded",
        "started_at": (now - timedelta(seconds=3)).isoformat(),
        "finished_at": now.isoformat(),
        "inserted": 4,
        "metrics": {},
        "errors": [],
    }]
    health = HealthProjector().from_documents("guardian", rows)
    assert health["status"] == "online"
    assert health["last_inserted_count"] == 4
    assert health["average_duration_seconds"] == 3


def test_partial_run_is_warning_not_online():
    now = datetime.now(timezone.utc)
    rows = [{
        "run_id": "partial",
        "source_name": "tonghuashun",
        "status": "partial",
        "started_at": (now - timedelta(seconds=5)).isoformat(),
        "finished_at": now.isoformat(),
        "inserted": 19,
        "metrics": {"parser_error": 1},
        "errors": [{"code": "parser_error", "message": "one article returned 404"}],
    }]
    health = HealthProjector().from_documents("tonghuashun", rows)
    assert health["status"] == "warning"
    assert health["recent_success_rate"] == 0
    assert health["latest_status"] == "partial"
    assert health["latest_error"] == "one article returned 404"
