from __future__ import annotations

from stock_pipeline import stock_storage


class _FakeClient:
    def __init__(self, rows_by_dataset):
        self.rows_by_dataset = rows_by_dataset
        self.queries = []

    def query(self, api_name, params, fields=""):
        self.queries.append((api_name, params))
        return type("Result", (), {"records": self.rows_by_dataset.get(api_name, []), "fields": []})()


def test_sync_daily_market_refreshes_low_quality_existing_daily(monkeypatch):
    full_data = {
        "datasets": {
            "stock_basic": [{"ts_code": "001326.SZ", "name": "联域股份"}],
            "daily": [
                {
                    "ts_code": "001326.SZ",
                    "trade_date": "20260710",
                    "open": 53.29,
                    "close": 53.81,
                    "high": 56.92,
                    "low": 52.2,
                    "vol": 16208.0,
                    "amount": None,
                    "source": "tencent_qfq_fallback",
                }
            ],
            "daily_basic": [
                {
                    "ts_code": "001326.SZ",
                    "trade_date": "20260710",
                    "close": 53.81,
                    "turnover_rate": None,
                    "source": "tencent_fallback",
                }
            ],
            "adj_factor": [{"ts_code": "001326.SZ", "trade_date": "20260710", "adj_factor": 1.0}],
            "stk_limit": [{"ts_code": "001326.SZ", "trade_date": "20260710", "up_limit": 59.19, "down_limit": 48.43}],
        },
        "date_range": {"start_date": "20231109", "end_date": "20260710", "full_history": True},
    }
    client = _FakeClient(
        {
            "daily": [
                {
                    "ts_code": "001326.SZ",
                    "trade_date": "20260710",
                    "open": 53.29,
                    "close": 53.81,
                    "high": 56.92,
                    "low": 52.2,
                    "vol": 16208.0,
                    "amount": 88343021.0,
                    "pct_chg": -0.09,
                    "change": -0.05,
                    "source": "eastmoney",
                }
            ],
            "daily_basic": [
                {
                    "ts_code": "001326.SZ",
                    "trade_date": "20260710",
                    "close": 53.81,
                    "turnover_rate": 6.75,
                    "pe": 61.59,
                    "source": "eastmoney",
                }
            ],
            "adj_factor": [{"ts_code": "001326.SZ", "trade_date": "20260710", "adj_factor": 1.0, "source": "eastmoney_qfq_ratio"}],
            "stk_limit": [{"ts_code": "001326.SZ", "trade_date": "20260710", "up_limit": 59.2, "down_limit": 48.42, "source": "eastmoney_estimated"}],
        }
    )

    monkeypatch.setattr(stock_storage, "ensure_current_layout", lambda _code: None)
    monkeypatch.setattr(stock_storage, "read_current_full_data", lambda _code: full_data)
    monkeypatch.setattr(stock_storage, "read_current_metadata", lambda _code: {"ts_code": "001326.SZ"})
    monkeypatch.setattr(stock_storage, "build_dossier", lambda data: {"daily": len(data["datasets"]["daily"])})
    monkeypatch.setattr(stock_storage, "_build_optional_analysis_dossiers", lambda _dossier: {})
    saved = {}

    def fake_save(ts_code, data, metadata, **_kwargs):
        saved["ts_code"] = ts_code
        saved["data"] = data
        saved["metadata"] = metadata
        return {"ok": True, "dataset_rows": sum(len(rows) for rows in data["datasets"].values())}

    monkeypatch.setattr(stock_storage, "_save_stock_package_safe", fake_save)

    result = stock_storage.sync_daily_market_for_stock(client, "001326.SZ", "20260710")

    assert result["status"] == "updated"
    assert "daily_low_quality" in result["quality_reasons"]
    assert "daily_basic_low_quality" in result["quality_reasons"]
    assert saved["data"]["datasets"]["daily"][0]["source"] == "eastmoney"
    assert saved["data"]["datasets"]["daily"][0]["amount"] == 88343021.0
    assert saved["data"]["datasets"]["daily_basic"][0]["turnover_rate"] == 6.75


def test_sync_daily_market_skips_existing_high_quality_daily(monkeypatch):
    full_data = {
        "datasets": {
            "daily": [
                {
                    "ts_code": "001326.SZ",
                    "trade_date": "20260710",
                    "open": 53.29,
                    "close": 53.81,
                    "high": 56.92,
                    "low": 52.2,
                    "vol": 16208.0,
                    "amount": 88343021.0,
                    "source": "eastmoney",
                }
            ],
            "daily_basic": [{"ts_code": "001326.SZ", "trade_date": "20260710", "turnover_rate": 6.75, "source": "eastmoney"}],
            "adj_factor": [{"ts_code": "001326.SZ", "trade_date": "20260710", "adj_factor": 1.0}],
            "stk_limit": [{"ts_code": "001326.SZ", "trade_date": "20260710", "up_limit": 59.2, "down_limit": 48.42}],
        }
    }
    client = _FakeClient({"daily": []})
    monkeypatch.setattr(stock_storage, "ensure_current_layout", lambda _code: None)
    monkeypatch.setattr(stock_storage, "read_current_full_data", lambda _code: full_data)

    result = stock_storage.sync_daily_market_for_stock(client, "001326.SZ", "20260710")

    assert result["status"] == "skipped"
    assert result["reason"] == "target_date_exists"
    assert client.queries == []


def test_merge_trade_date_rows_prefers_richer_market_row():
    rows = stock_storage._merge_trade_date_rows(
        [
            {
                "trade_date": "20260710",
                "close": 53.81,
                "amount": None,
                "source": "tencent_qfq_fallback",
            }
        ],
        [
            {
                "trade_date": "20260710",
                "close": 53.81,
                "amount": 88343021.0,
                "source": "eastmoney",
            }
        ],
    )

    assert rows[0]["source"] == "eastmoney"
    assert rows[0]["amount"] == 88343021.0


def test_sync_daily_market_batch_resumes_from_checkpoint(monkeypatch):
    synced = []
    checkpoints = []
    monkeypatch.setattr(stock_storage, "list_local_stock_codes", lambda: ["000001.SZ", "000002.SZ", "000003.SZ"])
    monkeypatch.setattr(
        stock_storage,
        "sync_daily_market_for_stock",
        lambda _client, ts_code, _date: synced.append(ts_code) or {"ok": True, "ts_code": ts_code, "status": "updated"},
    )
    monkeypatch.setattr(stock_storage, "_refresh_daily_k_coverage_safe", lambda codes, date: {"codes": list(codes), "date": date})

    result = stock_storage.sync_daily_market_for_existing_stocks(
        _FakeClient({}),
        target_date="20260714",
        checkpoint=lambda details: checkpoints.append(details),
        resume_checkpoint={"details": {"stage": "before_stock", "current": 2}},
    )

    assert synced == ["000002.SZ", "000003.SZ"]
    assert [item["ts_code"] for item in result["items"]] == ["000002.SZ", "000003.SZ"]
    assert result["resumed"] is True
    assert result["updated"] == 2
    assert checkpoints[0]["current"] == 2


def test_sync_daily_market_batch_reports_not_ok_when_stock_fails(monkeypatch):
    monkeypatch.setattr(stock_storage, "list_local_stock_codes", lambda: ["000001.SZ"])

    def fail_stock(*_args, **_kwargs):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(stock_storage, "sync_daily_market_for_stock", fail_stock)
    monkeypatch.setattr(stock_storage, "_refresh_daily_k_coverage_safe", lambda codes, date: {"codes": list(codes), "date": date})

    result = stock_storage.sync_daily_market_for_existing_stocks(_FakeClient({}), target_date="20260714")

    assert result["ok"] is False
    assert result["failed"] == 1
    assert result["items"][0]["error"] == "upstream timeout"
