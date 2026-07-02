from __future__ import annotations

from stock_pipeline.tushare_client import TushareResult
from stock_pipeline.tushare_kline import KlineBackfillConfig, fetch_all_stock_klines
from stock_pipeline.utils import read_json


class FakeTushareClient:
    source_name = "fake-tushare"

    def __init__(self):
        self.calls = []

    def query(self, api_name, params=None, fields=""):
        self.calls.append({"api_name": api_name, "params": params or {}, "fields": fields})
        if api_name == "stock_basic":
            return TushareResult(
                api_name,
                fields.split(","),
                [
                    {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "list_status": "L"},
                    {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "list_status": "L"},
                ],
            )
        if api_name == "daily":
            return TushareResult(
                api_name,
                fields.split(","),
                [
                    {
                        "ts_code": params["ts_code"],
                        "trade_date": "20240103",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.8,
                        "close": 10.5,
                        "pre_close": 10.1,
                        "change": 0.4,
                        "pct_chg": 3.96,
                        "vol": 12345.0,
                        "amount": 67890.0,
                    }
                ],
            )
        if api_name == "weekly":
            return TushareResult(api_name, fields.split(","), [{"ts_code": params["ts_code"], "trade_date": "20240105", "vol": 300.0}])
        raise AssertionError(f"unexpected api: {api_name}")


def test_fetch_all_stock_klines_writes_price_volume_records(tmp_path):
    client = FakeTushareClient()
    result = fetch_all_stock_klines(
        client,
        KlineBackfillConfig(output_dir=tmp_path, start_date="20240101", end_date="20240131", limit=1),
    )

    assert result["updated"] == 1
    payload = read_json(tmp_path / "daily" / "000001.SZ.json")
    assert payload["records"][0]["close"] == 10.5
    assert payload["records"][0]["vol"] == 12345.0
    assert payload["records"][0]["amount"] == 67890.0
    assert payload["date_range"]["actual_start_date"] == "20240103"
    assert read_json(tmp_path / "manifest.json")["rows"] == 1


def test_fetch_all_stock_klines_filters_codes_and_frequencies(tmp_path):
    client = FakeTushareClient()
    result = fetch_all_stock_klines(
        client,
        KlineBackfillConfig(
            output_dir=tmp_path,
            start_date="20240101",
            end_date="20240131",
            frequencies=("daily", "weekly"),
            codes=("600000.SH",),
        ),
    )

    assert result["stock_count"] == 1
    assert (tmp_path / "daily" / "600000.SH.json").exists()
    assert (tmp_path / "weekly" / "600000.SH.json").exists()
    assert not (tmp_path / "daily" / "000001.SZ.json").exists()


def test_fetch_all_stock_klines_skips_existing_covered_file(tmp_path):
    client = FakeTushareClient()
    fetch_all_stock_klines(
        client,
        KlineBackfillConfig(output_dir=tmp_path, start_date="20240101", end_date="20240131", limit=1),
    )
    call_count = len(client.calls)

    result = fetch_all_stock_klines(
        client,
        KlineBackfillConfig(output_dir=tmp_path, start_date="20240101", end_date="20240131", limit=1),
    )

    assert result["skipped"] == 1
    assert len(client.calls) == call_count + 1
