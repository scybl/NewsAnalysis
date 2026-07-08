from __future__ import annotations

from types import SimpleNamespace

import stock_pipeline.web as web


class FakeTaskRegistry:
    def __init__(self) -> None:
        self.events = []
        self.tasks = {}

    def add_event(self, task_id: str, status: str, message: str, metadata: dict) -> None:
        self.events.append({"task_id": task_id, "status": status, "message": message, "metadata": metadata})

    def update_task(self, task_id: str, **kwargs) -> None:
        self.tasks.setdefault(task_id, {}).update(kwargs)


def _scheduler(*, enabled: bool = True):
    scheduler = object.__new__(web.IdleStockPrefetchScheduler)
    scheduler.config = {"minutes_enabled": enabled}
    scheduler.lock = web.threading.Lock()
    scheduler.app = SimpleNamespace(settings=SimpleNamespace(idle_stock_prefetch_minutes_enabled=True, idle_stock_prefetch_refresh_existing_days=14))
    scheduler.task_registry = FakeTaskRegistry()
    scheduler._write_config_locked = lambda: None
    return scheduler


def test_idle_prefetch_fetches_minutes(monkeypatch):
    scheduler = _scheduler()

    def fake_fetch(codes, *, config, sleep_range, source, pages, page_size):
        return {
            "ok": True,
            "source": source,
            "results": [
                {
                    "ts_code": codes[0],
                    "dataset": "pytdx_history_minutes",
                    "rows": 240,
                    "stored_rows": 786960,
                    "inserted": 240,
                    "updated": 0,
                    "skipped_days": 3,
                    "failed_days": 0,
                    "date_range": {"start": "20220101", "end": "20260626"},
                }
            ],
        }

    monkeypatch.setattr(web, "build_ths_minute_config", lambda: object())
    monkeypatch.setattr(web, "fetch_and_store_minutes", fake_fetch)
    result = scheduler._prefetch_minutes("300308.SZ", "task-1")

    assert result["ok"] is True
    assert result["dataset"] == "pytdx_history_minutes"
    assert result["stored_rows"] == 786960
    assert scheduler.task_registry.events[-1]["status"] == "running"


def test_idle_prefetch_keeps_dossier_when_minutes_fail(monkeypatch):
    scheduler = _scheduler()

    def fail_fetch(*args, **kwargs):
        raise RuntimeError("minute source unavailable")

    monkeypatch.setattr(web, "build_ths_minute_config", lambda: object())
    monkeypatch.setattr(web, "fetch_and_store_minutes", fail_fetch)
    result = scheduler._prefetch_minutes("001266.SZ", "task-2")

    assert result == {
        "ok": False,
        "status": "failed",
        "source": "pytdx_history",
        "error": "minute source unavailable",
    }
    assert scheduler.task_registry.events[-1]["status"] == "warning"


def test_idle_prefetch_records_failed_candidate_for_cooldown(monkeypatch):
    scheduler = _scheduler()
    scheduler.config = {"minutes_enabled": True, "attempts": {}}
    scheduler._next_candidate = lambda: {"ts_code": "001267.SZ", "name": "汇绿生态"}
    monkeypatch.setattr(web, "provider_available", lambda _key: False)
    monkeypatch.setattr(web, "_public_stock_client", lambda _settings: object())

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("本次更新缺少关键数据集：stock_basic，已保留原 current。")

    monkeypatch.setattr(web, "sync_stock_data", fail_sync)
    scheduler._run_task("task-3", "idle")

    task = scheduler.task_registry.tasks["task-3"]
    assert task["status"] == "failed"
    assert task["result"]["ts_code"] == "001267.SZ"
    assert scheduler.config["attempts"]["001267.SZ"]["status"] == "failed"


def test_idle_prefetch_selects_stale_existing_package(monkeypatch):
    scheduler = _scheduler()
    scheduler.config = {"minutes_enabled": True, "refresh_existing_days": 14, "attempts": {}}
    scheduler.app.index = SimpleNamespace(stocks=lambda refresh=False: [{"ts_code": "000001.SZ", "name": "平安银行"}])

    monkeypatch.setattr(web, "stock_exists", lambda _code: True)
    monkeypatch.setattr(
        web,
        "list_local_stock_summaries",
        lambda: {
            "items": [
                {
                    "ts_code": "000001.SZ",
                    "updated_at": "20200101_000000",
                }
            ]
        },
    )

    candidate = scheduler._next_candidate()

    assert candidate["ts_code"] == "000001.SZ"
    assert candidate["reason"] == "stale_package"
