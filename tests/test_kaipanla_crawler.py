import requests

from stock_pipeline.kaipanla_crawler import KaipanlaCrawler


def test_sector_strength_dataframe_normalizes_compact_dates(monkeypatch):
    crawler = KaipanlaCrawler()

    monkeypatch.setattr(
        crawler,
        "get_sector_strength_history",
        lambda *_args, **_kwargs: {
            "success": True,
            "history_data": [
                {"date": "20260518", "strength": 12, "time": "15:00", "is_historical": True},
                {"date": "2026-05-19", "strength": 8, "time": "15:00", "is_historical": True},
            ],
        },
    )

    frame = crawler.get_sector_strength_dataframe("801346", "2026-05-18", "2026-05-19")

    assert list(frame["date"].dt.strftime("%Y-%m-%d")) == ["2026-05-18", "2026-05-19"]
    assert list(frame["strength"]) == [12, 8]


def test_realtime_index_list_parses_float_turnover(monkeypatch):
    crawler = KaipanlaCrawler()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "errcode": "0",
                "StockList": [
                    {
                        "StockID": "801900",
                        "prod_name": "示例指数",
                        "last_px": "24126092789.000",
                        "increase_rate": "1.2%",
                        "increase_amount": "3",
                        "turnover": "24126092789.000",
                    }
                ],
            }

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.post", lambda *args, **kwargs: Response())

    result = crawler.get_realtime_index_list(["801900"], timeout=1)

    assert result["indexes"][0]["turnover"] == 24126092789


def test_daily_data_uses_default_request_timeout(monkeypatch):
    crawler = KaipanlaCrawler()
    timeouts = []

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(*_args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        action = kwargs.get("data", {}).get("a")
        if action == "HisZhangFuDetail":
            return Response({"date": "2026-07-14", "info": {"ZT": 1, "SJZT": 1, "DT": 0, "SJDT": 0, "SZJS": 2, "XDJS": 3, "0": 4}})
        if action == "GetZsReal":
            return Response({"StockList": [{"StockID": "SH000001", "last_px": "3000", "increase_rate": "1.0%", "turnover": "100"}]})
        if action == "ZhangTingExpression":
            return Response({"info": [1, 2, 3, 4, 5]})
        return Response({"num": 6})

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.post", fake_post)

    result = crawler.get_daily_data("2026-07-14")

    assert result["涨停数"] == 1
    assert timeouts == [20, 20, 20, 20]


def test_kaipanla_request_timeout_is_capped(monkeypatch):
    crawler = KaipanlaCrawler()
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": "0", "x": []}

    def fake_post(*_args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return Response()

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.post", fake_post)

    crawler.get_new_high_data("2026-07-14", timeout=1600)

    assert captured["timeout"] == 60


def test_ths_hot_rank_raises_when_browser_unavailable(monkeypatch):
    crawler = KaipanlaCrawler()

    def fail_driver(*_args, **_kwargs):
        raise RuntimeError("driver missing")

    monkeypatch.setattr("selenium.webdriver.Chrome", fail_driver)

    try:
        crawler.get_ths_hot_rank(timeout=1)
    except RuntimeError as exc:
        assert "同花顺热榜抓取失败" in str(exc)
    else:
        raise AssertionError("expected ths hot rank failure")


def test_stock_call_auction_tick_raises_on_empty_http_body(monkeypatch):
    crawler = KaipanlaCrawler()
    captured = {}

    class Response:
        text = ""

        def raise_for_status(self):
            return None

    def fake_get(*_args, **kwargs):
        captured["params"] = kwargs.get("params")
        return Response()

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.get", fake_get)

    try:
        crawler.get_stock_call_auction_tick("002498", date="2026-01-16", timeout=1)
    except RuntimeError as exc:
        assert "竞价tick" in str(exc)
    else:
        raise AssertionError("expected stock call auction tick failure")
    assert captured["params"]["pos"] == "0"


def test_stock_call_auction_tick_parses_list_of_detail_strings(monkeypatch):
    crawler = KaipanlaCrawler()

    class Response:
        text = '{"rc":0}'

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "rc": 0,
                "data": {
                    "details": [
                        "09:15:00,5.55,108,0,4",
                        "09:25:09,5.60,200,0,4",
                        "09:30:00,5.61,300,0,4",
                    ]
                },
            }

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.get", lambda *args, **kwargs: Response())

    result = crawler.get_stock_call_auction_tick("002498", date="2026-01-16", timeout=1)

    assert result["stock_code"] == "0.002498"
    assert list(result["data"]["time"]) == ["09:15:00"]
    assert list(result["data"]["price"]) == [5.55]
    assert list(result["data"]["volume"]) == [108]


def test_stock_call_auction_tick_retries_transient_timeout(monkeypatch):
    crawler = KaipanlaCrawler()
    calls = {"count": 0}

    class Response:
        text = '{"rc":0}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"rc": 0, "data": {"details": ["09:15:00,5.55,108,0,4"]}}

    def fake_get(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.ReadTimeout("temporary timeout")
        return Response()

    monkeypatch.setattr("stock_pipeline.kaipanla_crawler.requests.get", fake_get)

    result = crawler.get_stock_call_auction_tick("002498", date="2026-01-16", timeout=1)

    assert calls["count"] == 2
    assert list(result["data"]["time"]) == ["09:15:00"]
