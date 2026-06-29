from __future__ import annotations

from stock_pipeline.eastmoney_client import EastmoneyClient


class FakeEastmoneyClient(EastmoneyClient):
    def __init__(self):
        super().__init__(timeout=1, pause=0)

    def _kline(self, ts_code, start_date, end_date, api_name):
        return [{"ts_code": ts_code, "trade_date": "20260625", "close": 12.0}]

    def _kline_with_fqt(self, ts_code, start_date, end_date, api_name, fqt):
        close = 12.0 if fqt == "1" else 10.0
        return [{"ts_code": ts_code, "trade_date": "20260625", "close": close}]

    def _curl_json(self, url, params, *, safe=","):
        if "np-anotice" in url:
            return {
                "data": {
                    "list": [
                        {
                            "notice_date": "2026-06-25 00:00:00",
                            "title": "示例公告",
                            "columns": [{"column_name": "公司公告"}],
                        }
                    ],
                    "total_hits": 1,
                }
            }
        return {"data": {"klines": ["2026-06-25,100,20,30,40,10,1,2,3,4,5,12,0.5"]}}

    def _json(self, url, params, *, referer="https://quote.eastmoney.com/"):
        if "CompanyManagement" in url:
            return {
                "gglb": [
                    {
                        "PERSON_NAME": "高管A",
                        "POSITION": "总经理",
                        "SALARY": 1000000,
                        "HOLD_NUM": 2000,
                        "SEX": "男",
                        "HIGH_DEGREE": "硕士",
                        "AGE": "45",
                        "INCUMBENT_TIME": "2025-01-01至今",
                    }
                ],
                "cgbd": [],
            }
        if "np-anotice" in url:
            return {
                "data": {
                    "list": [
                        {
                            "notice_date": "2026-06-25 00:00:00",
                            "title": "示例公告",
                            "columns": [{"column_name": "公司公告"}],
                        }
                    ],
                    "total_hits": 1,
                }
            }
        return {"data": {"f116": 100000000, "f117": 80000000, "f162": 1234, "f167": 250, "f10": 321}}

    def _org_basic(self, ts_code):
        return {
            "SECURITY_NAME_ABBR": "平安银行",
            "ORG_NAME": "平安银行股份有限公司",
            "FORMERNAME": "深发展A→S深发展A→平安银行",
            "CHAIRMAN": "张三",
            "PRESIDENT": "李四",
            "SECRETARY": "王五",
            "ACCOUNT_FIRM": "示例会计师事务所",
        }

    def _datacenter(self, report_name, filter_text, page_size=80, sort_columns="", sort_types=""):
        fixtures = {
            "RPTA_WEB_RZRQ_GGMX": [{"DATE": "2026-06-25 00:00:00", "RZYE": 1, "RQYE": 2, "RZMRE": 3, "RZCHE": 4, "RZJME": 5, "RQYL": 6, "RQMCL": 7, "RQCHL": 8, "RZRQYE": 9}],
            "RPT_F10_EH_HOLDERS": [{"END_DATE": "2026-03-31 00:00:00", "HOLDER_NAME": "股东A", "HOLD_NUM": 100, "HOLD_NUM_RATIO": 10, "HOLDER_RANK": 1}],
            "RPT_F10_EH_FREEHOLDERS": [{"END_DATE": "2026-03-31 00:00:00", "UPDATE_DATE": "2026-04-20 00:00:00", "HOLDER_NAME": "流通股东A", "HOLD_NUM": 80, "FREE_HOLDNUM_RATIO": 8, "HOLDER_RANK": 1}],
            "RPT_F10_EH_HOLDERNUM": [{"END_DATE": "2026-03-31 00:00:00", "NOTICE_DATE": "2026-04-20 00:00:00", "HOLDER_TOTAL_NUM": 1234}],
            "RPT_SHAREBONUS_DET": [{"REPORT_DATE": "2025-12-31 00:00:00", "NOTICE_DATE": "2026-06-01 00:00:00", "PRETAX_BONUS_RMB": 3.6, "ASSIGN_PROGRESS": "实施分配"}],
            "RPT_PUBLIC_OP_NEWPREDICT": [{"REPORT_DATE": "2026-06-30 00:00:00", "NOTICE_DATE": "2026-04-01 00:00:00", "PREDICT_TYPE": "预增"}],
            "RPT_LICO_FN_CPD": [{"REPORTDATE": "2026-03-31 00:00:00", "NOTICE_DATE": "2026-04-25 00:00:00", "TOTAL_OPERATE_INCOME": 1, "PARENT_NETPROFIT": 2}],
            "RPT_F10_FN_MAINOP": [{"REPORT_DATE": "2025-12-31 00:00:00", "ITEM_NAME": "主营", "MAIN_BUSINESS_INCOME": 1}],
            "RPT_LIFT_STAGE": [{"FREE_DATE": "2026-01-01 00:00:00", "FREE_SHARES": 10, "FREE_RATIO": 1}],
            "RPT_DATA_BLOCKTRADE": [{"TRADE_DATE": "2026-06-25 00:00:00", "DEAL_PRICE": 10, "DEAL_VOLUME": 100, "DEAL_AMT": 1000}],
            "RPTA_APP_ACCUMDETAILS": [{"NOTICE_DATE": "2026-06-20 00:00:00", "HOLDER_NAME": "股东A", "PF_NUM": 1000, "PF_HOLD_RATIO": 2.5, "PF_TSR": 1.2, "PF_ORG": "机构A", "PF_START_DATE": "2026-06-01 00:00:00", "UNFREEZE_DATE": "2027-06-01 00:00:00", "UNFREEZE_STATE": "未解押"}],
            "RPT_SUSPEND_DATE": [{"SUSPEND_START_DATE": "2026-06-25 00:00:00"}],
            "RPT_CUSTOM_SUSPEND_DATA_INTERFACE": [{"SECURITY_CODE": "000001", "SUSPEND_START_DATE": "2026-06-25 00:00:00", "SUSPEND_START_TIME": "2026-06-25 09:30:00", "SUSPEND_END_TIME": "2026-06-25 10:30:00", "SUSPEND_EXPIRE": "盘中停牌", "SUSPEND_REASON": "交易异常波动"}],
        }
        return fixtures.get(report_name, [])


def test_eastmoney_replaces_tushare_extended_datasets():
    client = FakeEastmoneyClient()
    params = {"ts_code": "000001.SZ", "start_date": "20260101", "end_date": "20260630"}
    expected_non_empty = [
        "adj_factor",
        "suspend_d",
        "moneyflow",
        "margin_detail",
        "top10_holders",
        "top10_floatholders",
        "stk_holdernumber",
        "stk_holdertrade",
        "pledge_stat",
        "pledge_detail",
        "dividend",
        "forecast",
        "express",
        "fina_mainbz",
        "fina_audit",
        "share_float",
        "block_trade",
        "namechange",
        "stk_managers",
        "anns_d",
    ]
    for api_name in expected_non_empty:
        assert client.query(api_name, params).records, api_name


def test_eastmoney_known_unstable_datasets_are_safe_empty():
    client = FakeEastmoneyClient()
    for api_name in ["repurchase", "disclosure_date", "sw_daily"]:
        assert client.query(api_name, {"ts_code": "000001.SZ"}).records == []


def test_eastmoney_daily_basic_scales_snapshot_ratios():
    client = FakeEastmoneyClient()
    rows = client.query("daily_basic", {"ts_code": "000001.SZ", "start_date": "20260601", "end_date": "20260630"}).records

    assert rows[0]["pe_ttm"] == 12.34
    assert rows[0]["pe"] == 12.34
    assert rows[0]["pb"] == 2.5
    assert rows[0]["volume_ratio"] == 3.21
