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
        self.created = []
        self.updates = []
        self.events = []
        self.tasks = {}

    def create_task(self, task_id, kind, title, metadata=None):
        task = {"task_id": task_id, "kind": kind, "title": title, "status": "queued", "metadata": metadata or {}}
        self.created.append(task)
        self.tasks[task_id] = task
        return task

    def update_task(self, task_id, status=None, error=None, result=None, metadata=None):
        self.updates.append({"task_id": task_id, "status": status, "error": error, "result": result, "metadata": metadata})
        self.tasks.setdefault(task_id, {"task_id": task_id, "metadata": {}})["status"] = status

    def add_event(self, task_id, stage, message, details=None):
        self.events.append({"task_id": task_id, "stage": stage, "message": message, "details": details or {}})

    def get_task(self, task_id):
        return self.tasks.get(task_id)


class FakeTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.active_attempts = {}

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)

    def is_attempt_active(self, _task_id, attempt_id):
        return self.active_attempts.get(attempt_id, True)


def make_scheduler(tmp_path):
    scheduler = web.DailyMarketScheduler.__new__(web.DailyMarketScheduler)
    scheduler.app = SimpleNamespace(
        settings=SimpleNamespace(tushare_token="", tushare_base_url="", tushare_pause_seconds=0),
        index=FakeIndex(),
        task_queue=FakeTaskQueue(),
    )
    scheduler.config_path = tmp_path / "daily_market_scheduler.json"
    scheduler.task_registry = FakeTaskRegistry()
    scheduler.lock = threading.Lock()
    scheduler.worker = None
    scheduler.config = {"enabled": True, "time": "21:30", "last_run_date": "", "last_run_at": "", "last_task_id": "", "last_result": {}}
    return scheduler


def make_kaipanla_scheduler(tmp_path):
    scheduler = web.KaipanlaScheduler.__new__(web.KaipanlaScheduler)
    scheduler.config_path = tmp_path / "kaipanla_scheduler.json"
    scheduler.task_registry = FakeTaskRegistry()
    scheduler.task_queue = FakeTaskQueue()
    scheduler.lock = threading.Lock()
    scheduler.worker = None
    scheduler.config = {
        "enabled": True,
        "time": "21:45",
        "features": ["daily_data"],
        "params_by_feature": {"daily_data": {"date": "ignored"}},
        "last_run_date": "",
        "last_run_at": "",
        "last_task_id": "",
        "last_result": {},
    }
    return scheduler


def test_daily_market_scheduler_start_uses_backfill_target(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    monkeypatch.setattr(
        web,
        "choose_daily_market_target",
        lambda: {
            "target_date": "20260710",
            "reason": "incomplete_recent_trade_date",
            "expected_stocks": 1151,
            "threshold": 1093,
            "date_counts": {"20260710": 357},
        },
    )

    status = scheduler._start_run("scheduled")

    assert status["scheduler"]["last_target_date"] == "20260710"
    assert scheduler.config["last_target_reason"] == "incomplete_recent_trade_date"
    assert scheduler.task_registry.created[-1]["metadata"]["target_date"] == "20260710"
    assert scheduler.app.task_queue.enqueued[-1]["payload"]["target_date"] == "20260710"


def test_daily_market_scheduler_records_stock_list_and_quote_result(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    monkeypatch.setattr(web, "provider_available", lambda provider: True)
    monkeypatch.setattr(web, "TushareClient", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("daily scheduler should not use Tushare")))
    monkeypatch.setattr(web, "_public_stock_client", lambda settings: SimpleNamespace(source="public"))
    monkeypatch.setattr(
        web,
        "sync_daily_market_for_existing_stocks",
        lambda client, target_date=None, checkpoint=None, resume_checkpoint=None: {"updated": 2, "skipped": 1, "no_data": 0, "failed": 0},
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


def test_daily_market_scheduler_marks_partial_batch_failure(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    monkeypatch.setattr(web, "_public_stock_client", lambda settings: SimpleNamespace(source="public"))
    monkeypatch.setattr(
        web,
        "sync_daily_market_for_existing_stocks",
        lambda client, target_date=None, checkpoint=None, resume_checkpoint=None: {"ok": False, "updated": 1, "skipped": 0, "no_data": 0, "failed": 1},
    )

    scheduler._run_task("task-1", "20260629", "scheduled")

    assert scheduler.task_registry.updates[-1]["status"] == "failed"
    assert scheduler.config["last_run_date"] == ""
    assert scheduler.config["last_failed_date"] == "20260629"
    assert scheduler.config["next_retry_epoch"] > 0
    assert "部分失败" in scheduler.config["last_error"]


def test_daily_market_scheduler_forwards_resume_checkpoint(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    captured = {}
    resume_checkpoint = {"stage": "daily_market_before_stock", "details": {"stage": "before_stock", "current": 2}}
    monkeypatch.setattr(web, "_public_stock_client", lambda settings: SimpleNamespace(source="public"))

    def fake_sync(client, target_date=None, checkpoint=None, resume_checkpoint=None):
        captured["target_date"] = target_date
        captured["resume_checkpoint"] = resume_checkpoint
        return {"updated": 1, "skipped": 0, "no_data": 0, "failed": 0}

    monkeypatch.setattr(web, "sync_daily_market_for_existing_stocks", fake_sync)

    scheduler._run_task("task-1", "20260629", "manual", resume_checkpoint)

    assert captured["target_date"] == "20260629"
    assert captured["resume_checkpoint"] == resume_checkpoint
    assert scheduler.task_registry.updates[-1]["status"] == "succeeded"


def test_daily_market_scheduler_propagates_queue_defer(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    monkeypatch.setattr(web, "_public_stock_client", lambda settings: SimpleNamespace(source="public"))

    def fake_sync(*_args, **_kwargs):
        raise web.QueueTaskDeferred("task-1", "pressure")

    monkeypatch.setattr(web, "sync_daily_market_for_existing_stocks", fake_sync)

    try:
        scheduler._run_task("task-1", "20260629", "manual")
    except web.QueueTaskDeferred:
        pass
    else:
        raise AssertionError("QueueTaskDeferred should propagate to the queue worker")

    assert not scheduler.task_registry.updates


def test_daily_market_scheduler_ignores_stale_queue_attempt(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    scheduler.app.task_queue.active_attempts["attempt-old"] = False
    monkeypatch.setattr(web, "_public_stock_client", lambda settings: SimpleNamespace(source="public"))
    monkeypatch.setattr(
        web,
        "sync_daily_market_for_existing_stocks",
        lambda client, target_date=None, checkpoint=None, resume_checkpoint=None: {"updated": 1, "skipped": 0, "no_data": 0, "failed": 0},
    )

    scheduler._run_task("task-1", "20260629", "manual", queue_attempt_id="attempt-old")

    assert not scheduler.task_registry.updates
    assert scheduler.config["last_run_date"] == ""


def test_daily_market_scheduler_fails_when_market_stock_list_is_empty(monkeypatch, tmp_path):
    scheduler = make_scheduler(tmp_path)
    scheduler.app.index.stocks = lambda *, refresh: []
    monkeypatch.setattr(web, "provider_available", lambda provider: provider == "eastmoney")
    monkeypatch.setattr(web, "EastmoneyClient", lambda pause=0: SimpleNamespace(source="eastmoney"))

    scheduler._run_task("task-2", "20260629", "manual")

    assert scheduler.config["last_error"]
    assert scheduler.task_registry.updates[-1]["status"] == "failed"
    assert "本地股票列表为空" in scheduler.task_registry.updates[-1]["error"]


def test_kaipanla_scheduler_freezes_trade_date_in_queue_payload(monkeypatch, tmp_path):
    scheduler = make_kaipanla_scheduler(tmp_path)
    monkeypatch.setattr(web, "today_yyyymmdd", lambda: "20260714")

    scheduler._start_run("scheduled")

    assert scheduler.task_registry.created[-1]["metadata"]["trade_date"] == "20260714"
    assert scheduler.task_queue.enqueued[-1]["payload"]["trade_date"] == "20260714"
    assert scheduler.task_queue.enqueued[-1]["resource_level"] == web.QUEUE_LIGHT_IO


def test_kaipanla_scheduler_ignores_stale_queue_attempt(monkeypatch, tmp_path):
    scheduler = make_kaipanla_scheduler(tmp_path)
    scheduler.task_queue.active_attempts["attempt-old"] = False
    monkeypatch.setattr(
        web,
        "run_kaipanla_batch",
        lambda *_args, **_kwargs: {"ok": True, "succeeded": 1, "failed": 0},
    )

    scheduler._run_task("task-1", "manual", "20260714", ["daily_data"], {}, queue_attempt_id="attempt-old")

    assert not scheduler.task_registry.updates
    assert scheduler.config["last_run_date"] == ""


def test_kaipanla_scheduler_marks_partial_failure_without_success_date(monkeypatch, tmp_path):
    scheduler = make_kaipanla_scheduler(tmp_path)
    monkeypatch.setattr(
        web,
        "run_kaipanla_batch",
        lambda *_args, **_kwargs: {"ok": False, "succeeded": 1, "failed": 1},
    )

    scheduler._run_task("task-1", "scheduled", "20260714", ["daily_data"], {})

    assert scheduler.task_registry.updates[-1]["status"] == "failed"
    assert scheduler.config["last_run_date"] == ""
    assert scheduler.config["last_failed_date"] == "20260714"
    assert scheduler.config["next_retry_epoch"] > 0
    assert "部分开盘啦功能抓取失败" in scheduler.config["last_error"]


def test_public_stock_client_respects_provider_status(monkeypatch):
    monkeypatch.setattr(web, "provider_available", lambda key: key == "eastmoney")
    monkeypatch.setattr(web, "EastmoneyClient", lambda pause=0: SimpleNamespace(source_name="eastmoney"))
    monkeypatch.setattr(web, "AkshareClient", lambda pause=0: (_ for _ in ()).throw(AssertionError("akshare should be disabled")))

    client = web._public_stock_client(SimpleNamespace(tushare_pause_seconds=0))

    assert client.source_name == "eastmoney"


def test_public_stock_client_fails_when_public_providers_disabled(monkeypatch):
    monkeypatch.setattr(web, "provider_available", lambda _key: False)

    try:
        web._public_stock_client(SimpleNamespace(tushare_pause_seconds=0))
    except web.TushareError as exc:
        assert "均未启用" in str(exc)
    else:
        raise AssertionError("disabled public providers should fail loudly")
