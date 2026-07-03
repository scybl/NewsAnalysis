import json
from datetime import datetime, timezone
from pathlib import Path

from stock_pipeline.ops_status import build_ops_snapshot


def _task(snapshot, task_id):
    return next(item for item in snapshot["tasks"] if item["id"] == task_id)


def test_ops_snapshot_handles_missing_files_without_failing(tmp_path):
    snapshot = build_ops_snapshot(
        tmp_path,
        crawler_snapshot_fn=lambda: {"summary": {"running_count": 0, "expired_running_count": 0}, "alerts": []},
    )

    assert snapshot["overall"]["status"] == "ok"
    assert _task(snapshot, "minute_cold_stock_year_upload")["status"] == "unknown"
    assert _task(snapshot, "daily_market_scheduler")["status"] == "unknown"
    assert snapshot["resources"]["files"]["admin_tasks"]["status"] == "missing"
    assert snapshot["resources"]["files"]["kaipanla_scheduler"]["status"] == "missing"


def test_ops_snapshot_parses_minute_upload_progress(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "minute-cold-stock-year-upload.pid").write_text("123\n", encoding="utf-8")
    (logs_dir / "minute-cold-stock-year-upload.log").write_text(
        "\n".join(
            [
                "[minute-cold][2026-07-03T10:00:00Z] plan stocks=100 year_files=10573 upload=True",
                "[minute-cold][2026-07-03T10:05:00Z] upload_start current=995/10573 percent=9.4 source=pytdx_history ts_code=002030.SZ year=2015 size=20MB remote=NewsAnalysis/cold/object.jsonl",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(
        tmp_path,
        pid_checker=lambda pid: pid == 123,
        now=datetime(2026, 7, 3, 10, 6, tzinfo=timezone.utc),
    )
    task = _task(snapshot, "minute_cold_stock_year_upload")

    assert task["status"] == "running"
    assert task["running"] is True
    assert task["last_event"] == "upload_start"
    assert task["progress"] == {"current": 995, "total": 10573, "percent": 9.4}
    assert task["details"]["ts_code"] == "002030.SZ"
    assert task["details"]["year"] == 2015
    assert task["last_event_age_seconds"] == 60
    assert snapshot["overall"]["heavy_io_running"] is True


def test_ops_snapshot_marks_stale_upload_start_as_warning(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "minute-cold-stock-year-upload.pid").write_text("456\n", encoding="utf-8")
    (logs_dir / "minute-cold-stock-year-upload.log").write_text(
        "[minute-cold][2026-07-03T10:00:00Z] upload_start current=10/20 percent=50 source=pytdx_history ts_code=000001.SZ year=2020\n",
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(
        tmp_path,
        pid_checker=lambda pid: pid == 456,
        now=datetime(2026, 7, 3, 10, 16, 1, tzinfo=timezone.utc),
    )
    task = _task(snapshot, "minute_cold_stock_year_upload")

    assert task["status"] == "warning"
    assert task["running"] is True
    assert "upload_start" in task["last_error"]
    assert snapshot["overall"]["status"] == "warning"


def test_ops_snapshot_reads_scheduler_and_admin_task_state(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "admin_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "daily-1",
                        "kind": "daily_market",
                        "title": "每日股票数据更新",
                        "status": "running",
                        "updated_epoch": 10,
                        "events": [{"stage": "running", "message": "开始刷新股票基础列表。"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (local_data / "daily_market_scheduler.json").write_text(
        json.dumps({"enabled": True, "last_task_id": "daily-1", "last_error": ""}, ensure_ascii=False),
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(tmp_path)
    task = _task(snapshot, "daily_market_scheduler")

    assert task["status"] == "running"
    assert task["running"] is True
    assert task["task_id"] == "daily-1"
    assert task["last_event"] == "running"
    assert snapshot["overall"]["heavy_io_running"] is True


def test_ops_status_route_is_admin_only_and_read_only():
    source = (Path(__file__).resolve().parents[1] / "stock_pipeline" / "web.py").read_text(encoding="utf-8")
    route_start = source.index('if parsed.path == "/api/admin/ops/status":')
    route = source[route_start : route_start + 700]
    require_admin_start = source.index("def _require_admin")
    require_admin = source[require_admin_start : require_admin_start + 500]

    assert "if not self._require_admin()" in route
    assert "build_ops_snapshot" in route
    assert "_require_data_fetch_approval" not in route
    assert "status=401" in require_admin
    assert "status=403" in require_admin
