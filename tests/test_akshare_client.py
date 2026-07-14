from __future__ import annotations

from types import SimpleNamespace

from stock_pipeline.akshare_client import AkshareClient
from stock_pipeline.composite_client import FallbackStockClient, ValidatingStockClient
from stock_pipeline.tushare_client import TushareError, TushareResult


class FakeFrame:
    empty = False

    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class FakeAk:
    def stock_zh_a_hist(self, symbol, period, start_date, end_date, adjust, timeout):
        assert symbol == "000001"
        assert period == "daily"
        return FakeFrame(
            [
                {
                    "日期": "2024-01-02",
                    "开盘": 9.39,
                    "收盘": 9.21,
                    "最高": 9.42,
                    "最低": 9.21,
                    "成交量": 1158366,
                    "成交额": 1075742252.45,
                    "涨跌幅": -1.92,
                    "涨跌额": -0.18,
                    "换手率": 0.6,
                }
            ]
        )

    def stock_profit_sheet_by_report_em(self, symbol):
        assert symbol == "SZ000001"
        return FakeFrame(
            [
                {
                    "REPORT_DATE": "2024-12-31 00:00:00",
                    "NOTICE_DATE": "2025-03-15 00:00:00",
                    "TOTAL_OPERATE_INCOME": 146695000000.0,
                    "OPERATE_INCOME": 146695000000.0,
                    "OPERATE_PROFIT": 55206000000.0,
                    "TOTAL_PROFIT": 54738000000.0,
                    "NETPROFIT": 44508000000.0,
                    "PARENT_NETPROFIT": 44508000000.0,
                    "BASIC_EPS": 2.15,
                    "DILUTED_EPS": 2.15,
                }
            ]
        )

    def stock_individual_fund_flow(self, stock, market):
        assert stock == "000001"
        assert market == "sz"
        return FakeFrame(
            [
                {
                    "日期": "2024-01-02",
                    "收盘价": "10.2",
                    "涨跌幅": "1.5",
                    "主力净流入-净额": "1000",
                    "主力净流入-净占比": "2.5",
                    "超大单净流入-净额": "300",
                    "大单净流入-净额": "700",
                    "中单净流入-净额": "-200",
                    "小单净流入-净额": "-800",
                }
            ]
        )

    def stock_dividend_cninfo(self, symbol):
        assert symbol == "000001"
        return FakeFrame(
            [
                {
                    "实施方案公告日期": "1992-03-14",
                    "分红类型": "年度分红",
                    "送股比例": 5,
                    "转增比例": 0,
                    "派息比例": 2,
                    "股权登记日": "1992-03-20",
                    "除权日": "1992-03-23",
                    "派息日": "NaT",
                    "实施方案分红说明": "10派2元送5股",
                    "报告时间": "1991年报",
                }
            ]
        )

    def stock_zh_a_gdhs_detail_em(self, symbol):
        assert symbol == "000001"
        return FakeFrame(
            [
                {
                    "股东户数统计截止日": "2024-03-31",
                    "股东户数公告日期": "2024-04-20",
                    "股东户数-本次": 50000,
                    "股东户数-上次": 52000,
                    "股东户数-增减": -2000,
                    "股东户数-增减比例": -3.8,
                    "户均持股数量": 10000,
                    "户均持股市值": 120000,
                    "总股本": 1000000000,
                    "总市值": 12000000000,
                }
            ]
        )

    def stock_zh_a_gbjg_em(self, symbol):
        assert symbol == "000001.SZ"
        return FakeFrame(
            [
                {
                    "变更日期": "2024-03-31",
                    "总股本": 1000000000,
                    "流通受限股份": 100000,
                    "已流通股份": 999900000,
                    "已上市流通A股": 999800000,
                    "变动原因": "定期报告",
                }
            ]
        )

    def stock_main_stock_holder(self, stock):
        assert stock == "000001"
        return FakeFrame(
            [
                {
                    "截至日期": "2024-03-31",
                    "公告日期": "2024-04-20",
                    "股东名称": "测试股东",
                    "持股数量": 123456,
                    "持股比例": 1.23,
                    "股东总数": 50000,
                    "平均持股数": 10000,
                }
            ]
        )


class FallbackDailyAk(FakeAk):
    def stock_zh_a_hist(self, symbol, period, start_date, end_date, adjust, timeout):
        raise RuntimeError("eastmoney hist disconnected")

    def stock_zh_a_daily(self, symbol, start_date, end_date, adjust):
        assert symbol == "sz000001"
        self.daily_calls = getattr(self, "daily_calls", 0) + 1
        return FakeFrame(
            [
                {
                    "date": "2024-01-02",
                    "open": 9.0,
                    "high": 9.5,
                    "low": 8.9,
                    "close": 9.2,
                    "volume": 10000.0,
                    "amount": 92000.0,
                    "outstanding_share": 1000000.0,
                    "turnover": 0.01,
                },
                {
                    "date": "2024-01-03",
                    "open": 9.2,
                    "high": 9.8,
                    "low": 9.1,
                    "close": 9.6,
                    "volume": 20000.0,
                    "amount": 192000.0,
                    "outstanding_share": 1000000.0,
                    "turnover": 0.02,
                },
            ]
        )


def test_akshare_moneyflow_uses_existing_dataset_fields(monkeypatch):
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("moneyflow", {"ts_code": "000001.SZ"})

    assert result.api_name == "moneyflow"
    assert result.records == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20240102",
            "close": 10.2,
            "pct_chg": 1.5,
            "net_mf_amount": 1000.0,
            "net_mf_vol": None,
            "buy_elg_amount": 300.0,
            "buy_lg_amount": 700.0,
            "buy_md_amount": -200.0,
            "buy_sm_amount": -800.0,
            "net_mf_ratio": 2.5,
            "source": "akshare_stock_individual_fund_flow",
        }
    ]


def test_akshare_daily_falls_back_to_daily_api_with_amount_and_turnover():
    client = object.__new__(AkshareClient)
    client.ak = FallbackDailyAk()
    client.pause = 0
    client.timeout = 1

    result = client.query("daily", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"})

    assert result.records[0]["vol"] == 100.0
    assert result.records[0]["amount"] == 92000.0
    assert result.records[0]["turnover_rate"] == 1.0
    assert result.records[1]["change"] == 0.4
    assert result.records[1]["pct_chg"] == 4.347826


def test_akshare_weekly_falls_back_to_aggregated_daily_api():
    client = object.__new__(AkshareClient)
    client.ak = FallbackDailyAk()
    client.pause = 0
    client.timeout = 1

    result = client.query("weekly", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"})

    assert result.records == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20240103",
            "open": 9.0,
            "close": 9.6,
            "high": 9.8,
            "low": 8.9,
            "vol": 300.0,
            "amount": 284000.0,
            "pct_chg": None,
            "change": None,
            "turnover_rate": 3.0,
            "source": "akshare_stock_zh_a_daily_aggregated_weekly",
        }
    ]


def test_akshare_daily_fallback_is_cached_for_period_aggregation():
    ak = FallbackDailyAk()
    client = object.__new__(AkshareClient)
    client.ak = ak
    client.pause = 0
    client.timeout = 1

    for api_name in ["daily", "weekly", "monthly"]:
        client.query(api_name, {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"})

    assert ak.daily_calls == 1


def test_akshare_daily_basic_uses_hist_turnover_rate():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    client.timeout = 1
    result = client.query("daily_basic", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"})

    assert result.records == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20240102",
            "close": 9.21,
            "turnover_rate": 0.6,
            "source": "akshare_stock_zh_a_hist_daily_basic",
        }
    ]


def test_akshare_income_maps_current_em_uppercase_fields():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("income", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20241231"})

    row = result.records[0]
    assert row["end_date"] == "20241231"
    assert row["ann_date"] == "20250315"
    assert row["total_revenue"] == 146695000000.0
    assert row["n_income"] == 44508000000.0
    assert row["basic_eps"] == 2.15


def test_akshare_dividend_handles_missing_dates():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("dividend", {"ts_code": "000001.SZ"})

    assert result.records[0]["pay_date"] == ""
    assert result.records[0]["end_date"] == "19911231"
    assert result.records[0]["cash_div"] == 2.0


def test_akshare_holder_number_uses_existing_key():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("stk_holdernumber", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20241231"})

    assert result.api_name == "stk_holdernumber"
    assert result.records[0]["end_date"] == "20240331"
    assert result.records[0]["holder_num"] == 50000.0


def test_akshare_share_float_uses_existing_key():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("share_float", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20241231"})

    assert result.api_name == "share_float"
    assert result.records[0]["float_date"] == "20240331"
    assert result.records[0]["float_share"] == 999900000.0


def test_akshare_top_holders_uses_existing_key():
    client = object.__new__(AkshareClient)
    client.ak = FakeAk()
    client.pause = 0
    result = client.query("top10_holders", {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20241231"})

    assert result.api_name == "top10_holders"
    assert result.records[0]["holder_name"] == "测试股东"
    assert result.records[0]["hold_ratio"] == 1.23


def test_fallback_client_keeps_same_api_key():
    primary = SimpleNamespace(
        source_name="primary",
        query=lambda api_name, params, fields: TushareResult(api_name=api_name, fields=[], records=[]),
    )
    fallback = SimpleNamespace(
        source_name="akshare",
        query=lambda api_name, params, fields: TushareResult(api_name=api_name, fields=["trade_date"], records=[{"trade_date": "20240102"}]),
    )
    result = FallbackStockClient(primary, [fallback]).query("daily", {"ts_code": "000001.SZ"})

    assert result.api_name == "daily"
    assert result.records == [{"trade_date": "20240102"}]


def test_fallback_client_keeps_primary_empty_when_fallback_fails():
    primary = SimpleNamespace(
        source_name="primary",
        query=lambda api_name, params, fields: TushareResult(api_name=api_name, fields=[], records=[]),
    )

    def fail(api_name, params, fields):
        raise TushareError("upstream disconnected")

    fallback = SimpleNamespace(source_name="akshare", query=fail)
    result = FallbackStockClient(primary, [fallback]).query("moneyflow", {"ts_code": "000001.SZ"})

    assert result.api_name == "moneyflow"
    assert result.records == []


def test_validating_client_uses_akshare_primary_and_fills_missing_fields():
    primary = SimpleNamespace(
        source_name="akshare",
        query=lambda api_name, params, fields: TushareResult(
            api_name=api_name,
            fields=["end_date", "total_revenue", "n_income", "source"],
            records=[{"end_date": "20241231", "total_revenue": None, "n_income": 10, "source": "akshare"}],
        ),
    )
    validator = SimpleNamespace(
        source_name="eastmoney",
        query=lambda api_name, params, fields: TushareResult(
            api_name=api_name,
            fields=["end_date", "total_revenue", "n_income", "source"],
            records=[{"end_date": "20241231", "total_revenue": 100, "n_income": 11, "source": "eastmoney"}],
        ),
    )

    result = ValidatingStockClient(primary, [validator]).query("income", {"ts_code": "000001.SZ"})

    assert result.records == [{"end_date": "20241231", "total_revenue": 100, "n_income": 10, "source": "akshare+validated:eastmoney"}]


def test_validating_client_keeps_safe_empty_optional_dataset_when_primary_fails():
    def fail(api_name, params, fields):
        raise TushareError("akshare unsupported")

    primary = SimpleNamespace(source_name="akshare", query=fail)
    validator = SimpleNamespace(
        source_name="eastmoney",
        query=lambda api_name, params, fields: TushareResult(api_name=api_name, fields=[], records=[]),
    )

    result = ValidatingStockClient(primary, [validator]).query("suspend_d", {"ts_code": "000001.SZ"})

    assert result.api_name == "suspend_d"
    assert result.records == []
