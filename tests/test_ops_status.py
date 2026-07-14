import json
from datetime import datetime, timezone
from pathlib import Path

from stock_pipeline.ops_status import active_heavy_io_tasks, build_ops_snapshot


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
    assert _task(snapshot, "data_random_audit_scheduler")["status"] == "unknown"
    assert _task(snapshot, "stock_storage_health_scheduler")["status"] == "unknown"
    assert snapshot["resources"]["files"]["admin_tasks"]["status"] == "missing"
    assert snapshot["resources"]["files"]["kaipanla_scheduler"]["status"] == "missing"


def test_ops_snapshot_includes_data_random_audit_scheduler(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "data_random_audit_scheduler.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "idle_seconds": 1800,
                "interval_seconds": 21600,
                "sample_size": 20,
                "last_run_at": "20260707_120000",
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(tmp_path, crawler_snapshot_fn=lambda: {"summary": {}, "alerts": []})
    task = _task(snapshot, "data_random_audit_scheduler")

    assert task["kind"] == "data_random_audit"
    assert task["status"] == "idle"
    assert task["resource_level"] == "normal"
    assert task["details"]["scheduler"]["sample_size"] == 20


def test_ops_snapshot_includes_stock_storage_health_scheduler(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "stock_storage_health_scheduler.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "idle_seconds": 900,
                "min_interval_seconds": 1800,
                "max_interval_seconds": 7200,
                "sample_size": 30,
                "last_run_at": "20260707_130000",
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(tmp_path, crawler_snapshot_fn=lambda: {"summary": {}, "alerts": []})
    task = _task(snapshot, "stock_storage_health_scheduler")

    assert task["kind"] == "stock_storage_health"
    assert task["status"] == "idle"
    assert task["resource_level"] == "normal"
    assert task["details"]["scheduler"]["sample_size"] == 30


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


def test_ops_snapshot_keeps_scheduler_queue_state_separate_from_running(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "admin_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "daily-queued",
                        "kind": "daily_market",
                        "title": "每日股票数据更新",
                        "status": "queued",
                        "updated_epoch": 10,
                        "events": [{"stage": "queued", "message": "任务已进入资源队列。"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (local_data / "daily_market_scheduler.json").write_text(
        json.dumps({"enabled": True, "last_task_id": "daily-queued", "last_error": ""}, ensure_ascii=False),
        encoding="utf-8",
    )
    (local_data / "task_queue.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "task_id": "daily-queued",
                        "title": "每日股票数据更新",
                        "status": "deferred",
                        "resource_level": "heavy_io",
                        "last_defer_reason": "可用内存不足",
                        "defer_count": 2,
                        "enqueued_epoch": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(tmp_path)
    task = _task(snapshot, "daily_market_scheduler")

    assert task["status"] == "queued"
    assert task["running"] is False
    assert snapshot["overall"]["heavy_io_running"] is False
    assert "daily_market_scheduler" in {item["id"] for item in active_heavy_io_tasks(snapshot)}
    assert snapshot["resources"]["task_queue"]["counts"]["deferred"] == 1
    assert snapshot["resources"]["task_queue"]["head"]["last_defer_reason"] == "可用内存不足"


def test_active_heavy_io_tasks_include_minute_upload_and_market_spider(tmp_path):
    local_data = tmp_path / "local_data"
    logs_dir = tmp_path / "logs"
    local_data.mkdir()
    logs_dir.mkdir()
    (logs_dir / "minute-cold-stock-year-upload.pid").write_text("321\n", encoding="utf-8")
    (logs_dir / "minute-cold-stock-year-upload.log").write_text(
        "[minute-cold][2026-07-03T10:00:00Z] check current=1/2 percent=50 source=pytdx_history ts_code=000001.SZ year=2024\n",
        encoding="utf-8",
    )
    (local_data / "admin_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "spider-1",
                        "kind": "spider",
                        "title": "分钟行情爬虫",
                        "status": "running",
                        "updated_epoch": 20,
                        "metadata": {"source": "ths_market"},
                    },
                    {
                        "task_id": "news-1",
                        "kind": "news_refetch",
                        "title": "新闻资料库补抓",
                        "status": "running",
                        "updated_epoch": 10,
                        "metadata": {"source": "guardian"},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = build_ops_snapshot(
        tmp_path,
        pid_checker=lambda pid: pid == 321,
        now=datetime(2026, 7, 3, 10, 1, tzinfo=timezone.utc),
    )
    blockers = active_heavy_io_tasks(snapshot)
    blocker_ids = {item["id"] for item in blockers}

    assert "minute_cold_stock_year_upload" in blocker_ids
    assert "admin_task:spider-1" in blocker_ids
    assert "admin_task:news-1" not in blocker_ids


def test_ops_snapshot_tolerates_non_dict_crawler_alerts(tmp_path):
    snapshot = build_ops_snapshot(
        tmp_path,
        crawler_snapshot_fn=lambda: {
            "summary": {"running_count": 0, "expired_running_count": 0},
            "alerts": ["plain alert"],
        },
    )
    task = _task(snapshot, "news_crawler")

    assert task["status"] == "warning"
    assert task["last_error"] == "plain alert"


def test_ops_status_route_is_admin_only_and_read_only():
    source = (Path(__file__).resolve().parents[1] / "stock_pipeline" / "web.py").read_text(encoding="utf-8")
    route_start = source.index('if parsed.path == "/api/admin/ops/status":')
    route = source[route_start : route_start + 700]
    helper_start = source.index("def _ops_snapshot")
    helper = source[helper_start : helper_start + 400]
    require_admin_start = source.index("def _require_admin")
    require_admin = source[require_admin_start : require_admin_start + 500]

    assert "if not self._require_admin()" in route
    assert "self._ops_snapshot()" in route
    assert "build_ops_snapshot" in helper
    assert "_require_data_fetch_approval" not in route
    assert "status=401" in require_admin
    assert "status=403" in require_admin


def test_heavy_io_guard_is_wired_to_heavy_start_routes_only():
    source = (Path(__file__).resolve().parents[1] / "stock_pipeline" / "web.py").read_text(encoding="utf-8")
    kaipanla_start = source.index("def _handle_admin_kaipanla_scheduler")
    kaipanla = source[kaipanla_start : kaipanla_start + 900]
    daily_start = source.index("def _handle_admin_daily_market_scheduler")
    daily = source[daily_start : daily_start + 900]
    idle_start = source.index("def _handle_admin_idle_stock_prefetch")
    idle = source[idle_start : idle_start + 900]
    audit_start = source.index("def _handle_admin_data_random_audit_scheduler")
    audit = source[audit_start : audit_start + 700]

    assert 'active_heavy_io_tasks' in source
    assert '_reject_if_heavy_io_running("manual_market_fetch_full")' in source
    assert 'task_queue.enqueue' in source
    assert '_reject_if_heavy_io_running("full_market_daily_fetch")' not in source
    assert '_reject_if_heavy_io_running("idle_stock_prefetch_with_minutes")' not in source
    assert "已有重 IO 任务正在运行" in source
    assert "self._ops_snapshot(include_crawler=False)" in source
    assert "_reject_if_heavy_io_running" not in daily
    assert "_reject_if_heavy_io_running" not in idle
    assert "_reject_if_heavy_io_running" not in audit
    assert "_reject_if_heavy_io_running" not in kaipanla


def test_admin_ops_frontend_is_read_only_and_linked():
    static = Path(__file__).resolve().parents[1] / "frontend" / "admin"
    html = (static / "admin-ops.html").read_text(encoding="utf-8")
    script = (static / "admin-ops.js").read_text(encoding="utf-8")
    styles = (static / "styles.css").read_text(encoding="utf-8")

    assert "/api/admin/ops/status" in script
    assert "/api/admin/market-fetch/start" not in script
    assert "/api/admin/market-fetch/stop" not in script
    assert "/api/admin/daily-market-scheduler" not in script
    assert "/api/admin/idle-stock-prefetch" not in script
    assert "data-copy-tail" in script
    assert "opsTasksTable" in html
    assert ".ops-grid" in styles
    for path in static.glob("admin-*.html"):
        page = path.read_text(encoding="utf-8")
        if '<nav class="admin-nav"' not in page:
            continue
        assert "/admin-ops.html" in page, path.name
