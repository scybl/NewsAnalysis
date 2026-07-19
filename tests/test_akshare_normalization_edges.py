import math
from datetime import date, datetime

from stock_pipeline.akshare_client import (
    _aggregate_hist_rows,
    _clean_value,
    _daily_hist_row,
    _daily_symbol,
    _date8,
    _em_symbol,
    _market,
    _num,
)


def test_akshare_date8_accepts_common_date_shapes_and_rejects_invalid_values():
    assert _date8(datetime(2026, 7, 19, 8, 30)) == "20260719"
    assert _date8(date(2026, 7, 19)) == "20260719"
    assert _date8("2026/07/19 00:00:00") == "20260719"
    assert _date8("2026-07-19") == "20260719"
    assert _date8("NaT") == ""
    assert _date8("bad") == ""


def test_akshare_clean_value_removes_non_json_finite_values():
    assert _clean_value(float("nan")) is None
    assert _clean_value(float("inf")) is None
    assert _clean_value("NaT") is None
    assert _clean_value(datetime(2026, 7, 19, 8, 30)) == "2026-07-19T08:30:00"
    assert _clean_value(date(2026, 7, 19)) == "2026-07-19"


def test_akshare_num_strips_commas_and_percent_signs():
    assert _num("1,234.50") == 1234.5
    assert _num("3.20%") == 3.2
    assert _num("nan") is None
    assert _num(math.inf) is None


def test_akshare_market_symbols_cover_sz_sh_and_bj_codes():
    assert _market("000001.SZ") == "sz"
    assert _market("600000.SH") == "sh"
    assert _market("430047.BJ") == "bj"
    assert _daily_symbol("600000.SH") == "sh600000"
    assert _em_symbol("000001.SZ") == "SZ000001"


def test_akshare_daily_hist_row_converts_volume_and_turnover_units():
    row = _daily_hist_row(
        "000001.SZ",
        {
            "date": "2026-07-17",
            "open": "10.1",
            "close": "10.3",
            "high": "10.5",
            "low": "10.0",
            "volume": "12,300",
            "amount": "126690",
            "turnover": "0.015",
        },
    )

    assert row["trade_date"] == "20260717"
    assert row["vol"] == 123.0
    assert row["turnover_rate"] == 1.5


def test_akshare_monthly_aggregation_sums_volume_amount_and_turnover():
    rows = [
        {"ts_code": "000001.SZ", "trade_date": "20260701", "open": 10.0, "close": 10.2, "high": 10.5, "low": 9.9, "vol": 100, "amount": 1000, "turnover_rate": 1.0},
        {"ts_code": "000001.SZ", "trade_date": "20260731", "open": 10.3, "close": 11.0, "high": 11.2, "low": 10.1, "vol": 200, "amount": 2200, "turnover_rate": 2.0},
        {"ts_code": "000001.SZ", "trade_date": "20260803", "open": 11.0, "close": 11.5, "high": 11.8, "low": 10.9, "vol": None, "amount": 500, "turnover_rate": None},
    ]

    result = _aggregate_hist_rows(rows, "monthly")

    assert [row["trade_date"] for row in result] == ["20260731", "20260803"]
    assert result[0]["open"] == 10.0
    assert result[0]["close"] == 11.0
    assert result[0]["high"] == 11.2
    assert result[0]["low"] == 9.9
    assert result[0]["vol"] == 300.0
    assert result[0]["amount"] == 3200.0
    assert result[0]["turnover_rate"] == 3.0
    assert result[1]["change"] == 0.5


def test_akshare_aggregation_skips_invalid_trade_dates():
    rows = [
        {"ts_code": "000001.SZ", "trade_date": "invalid", "open": 1, "close": 1, "high": 1, "low": 1, "vol": 1, "amount": 1},
        {"ts_code": "000001.SZ", "trade_date": "20260717", "open": 2, "close": 3, "high": 4, "low": 1, "vol": 2, "amount": 6},
    ]

    assert _aggregate_hist_rows(rows, "weekly")[0]["trade_date"] == "20260717"
