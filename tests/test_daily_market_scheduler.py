import threading
from types import SimpleNamespace

from stock_pipeline import web


class FakeIndex:
    def __init__(self):
        self.refresh_values = []

    def stocks(self, *, refresh):
        self.refresh_values.append(refresh)
        return [{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}]


class FakeTaskRegistry:
    def __init__(self):
        self.updates = []
        self.events = []

    def update_task(self, task_id, status=None, error=None, result=None, metadata=None):
        self.updates.append({"task_id": task_id, "status": status, "error": error, "result": result, "metadata": metadata})

    def add_event(self, task_id, stage, message, details=None):
        self.events.append({"task_id": task_id, "stage": stage, "message": message, "details": details or {}})


def make_scheduler(tmp_path):
    scheduler = web.DailyMarketScheduler.__new__(web.DailyMarketScheduler)
    scheduler.app = SimpleNamespace(
        settings=SimpleNamespace(tushare_token="", tushare_base_url="", tushare_pause_seconds=0),
        index=FakeIndex(),
    )
    scheduler.config_path = tmp_path / "daily_market_scheduler.json"
    scheduler.task_registry = FakeTaskRegistry()
    scheduler.lock = threading.Lock()
    scheduler.config = {"enabled": True, "time": "21:30", "last_run_date": "", "last_run_at": "", "last_task_id": "", "last_result": {}}
    return scheduler


def test_daily_market_scheduler_records_stock_list_and_quote_result(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    monkeypatch.setattr(web, "provider_available", lambda provider: False)
    monkeypatch.setattr(web, "EastmoneyClient", lambda pause=0: SimpleNamespace(source="eastmoney"))
    monkeypatch.setattr(
        web,
        "sync_daily_market_for_existing_stocks",
        lambda client, target_date=None: {"updated": 2, "skipped": 1, "no_data": 0, "failed": 0},
    )

    scheduler._run_task("task-1", "20260629", "manual")

    assert scheduler.app.index.refresh_values == [False]
    assert scheduler.config["last_run_date"] == "20260629"
    assert scheduler.config["last_result"]["stock_list_count"] == 2
    assert scheduler.config["last_result"]["updated"] == 2
    assert scheduler.config["last_result"]["trigger"] == "manual"
    assert scheduler.task_registry.updates[-1]["status"] == "succeeded"
    assert scheduler.task_registry.updates[-1]["result"]["stock_list_count"] == 2
    assert any(event["details"].get("stock_list_count") == 2 for event in scheduler.task_registry.events)


def test_daily_market_scheduler_fails_when_market_stock_list_is_empty(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    scheduler.app.index.stocks = lambda *, refresh: []
    monkeypatch.setattr(web, "provider_available", lambda provider: False)
    monkeypatch.setattr(web, "EastmoneyClient", lambda pause=0: SimpleNamespace(source="eastmoney"))

    scheduler._run_task("task-2", "20260629", "manual")

    assert scheduler.config["last_error"]
    assert scheduler.task_registry.updates[-1]["status"] == "failed"
    assert "本地股票列表为空" in scheduler.task_registry.updates[-1]["error"]
