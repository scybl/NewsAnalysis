import math

import pytest

from stock_pipeline.composite_client import FallbackStockClient, ValidatingStockClient
from stock_pipeline.tushare_client import TushareError, TushareResult


class FakeClient:
    def __init__(self, source_name, responses):
        self.source_name = source_name
        self.responses = responses
        self.calls = []

    def query(self, api_name, params=None, fields=""):
        self.calls.append((api_name, params or {}, fields))
        response = self.responses.get(api_name, [])
        if isinstance(response, Exception):
            raise response
        return TushareResult(api_name=api_name, fields=sorted({key for row in response for key in row}), records=list(response))


def test_validating_client_fills_missing_daily_fields_from_validator():
    primary = FakeClient(
        "akshare",
        {
            "daily": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260717",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "vol": 100.0,
                    "amount": None,
                    "source": "akshare",
                }
            ]
        },
    )
    validator = FakeClient(
        "eastmoney",
        {
            "daily": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260717",
                    "amount": 1020000.0,
                    "pct_chg": 1.2,
                    "source": "eastmoney",
                }
            ]
        },
    )

    rows = ValidatingStockClient(primary, [validator]).query("daily", {"ts_code": "000001.SZ"}).records

    assert rows[0]["amount"] == 1020000.0
    assert rows[0]["pct_chg"] == 1.2
    assert rows[0]["source"] == "akshare+validated:eastmoney"


def test_validating_client_adds_missing_trade_dates_and_sorts_newest_first():
    primary = FakeClient(
        "akshare",
        {
            "daily": [
                {"trade_date": "20260716", "open": 9, "high": 10, "low": 8, "close": 9.5, "vol": 10, "amount": 95, "source": "akshare"}
            ]
        },
    )
    validator = FakeClient(
        "eastmoney",
        {
            "daily": [
                {"trade_date": "20260717", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 20, "amount": 210, "source": "eastmoney"}
            ]
        },
    )

    rows = ValidatingStockClient(primary, [validator]).query("daily").records

    assert [row["trade_date"] for row in rows] == ["20260717", "20260716"]
    assert rows[0]["source"] == "eastmoney"


def test_validating_client_treats_nan_inf_and_text_nan_as_missing():
    primary = FakeClient(
        "akshare",
        {
            "daily_basic": [
                {"trade_date": "20260717", "close": math.nan, "turnover_rate": float("inf"), "pe": "nan", "source": "akshare"}
            ]
        },
    )
    validator = FakeClient(
        "eastmoney",
        {"daily_basic": [{"trade_date": "20260717", "close": 10.2, "turnover_rate": 3.4, "pe": 12.5, "source": "eastmoney"}]},
    )

    row = ValidatingStockClient(primary, [validator]).query("daily_basic").records[0]

    assert row["close"] == 10.2
    assert row["turnover_rate"] == 3.4
    assert row["pe"] == 12.5


def test_validating_client_uses_validator_when_primary_is_empty():
    primary = FakeClient("akshare", {"stock_basic": []})
    validator = FakeClient("eastmoney", {"stock_basic": [{"ts_code": "000001.SZ", "name": "平安银行", "list_date": "19910403"}]})

    result = ValidatingStockClient(primary, [validator]).query("stock_basic", {"ts_code": "000001.SZ"})

    assert result.records[0]["name"] == "平安银行"
    assert primary.calls
    assert validator.calls


def test_validating_client_does_not_call_validator_for_non_required_populated_dataset():
    primary = FakeClient("akshare", {"forecast": [{"end_date": "20261231", "type": "预增"}]})
    validator = FakeClient("eastmoney", {"forecast": [{"end_date": "20261231", "type": "预减"}]})

    rows = ValidatingStockClient(primary, [validator]).query("forecast").records

    assert rows == [{"end_date": "20261231", "type": "预增"}]
    assert validator.calls == []


def test_validating_client_returns_empty_primary_for_safe_empty_api_even_when_validator_fails():
    primary = FakeClient("akshare", {"suspend_d": []})
    validator = FakeClient("eastmoney", {"suspend_d": TushareError("upstream disconnected")})

    result = ValidatingStockClient(primary, [validator]).query("suspend_d")

    assert result.records == []


def test_fallback_client_raises_combined_source_errors_when_every_source_fails():
    primary = FakeClient("akshare", {"daily": TushareError("empty frame")})
    fallback = FakeClient("eastmoney", {"daily": TushareError("timeout")})

    with pytest.raises(TushareError, match="akshare: empty frame; eastmoney: timeout"):
        FallbackStockClient(primary, [fallback]).query("daily")
