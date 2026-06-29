from __future__ import annotations

import math
import time
from datetime import date, datetime
from typing import Any

from .tushare_client import TushareError, TushareResult
from .utils import normalize_ts_code


class AkshareClient:
    """AkShare adapter that writes into the existing dossier dataset keys.

    AkShare is a public-data wrapper, not an authoritative database.  This
    adapter is intentionally best-effort: unstable upstream pages should produce
    an empty/error dataset rather than break the primary Eastmoney collection.
    """

    source_name = "AkShare"

    def __init__(self, timeout: float = 20.0, pause: float = 0.2):
        self.timeout = timeout
        self.pause = pause
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise TushareError("AkShare 未安装，请先安装 akshare。") from exc
        self.ak = ak

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        params = params or {}
        ts_code = _normalize_or_empty(params.get("ts_code"))
        start_date = str(params.get("start_date") or "19900101")
        end_date = str(params.get("end_date") or "20500101")
        try:
            if api_name in {"daily", "weekly", "monthly"}:
                period = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}[api_name]
                return _result(api_name, self._hist(ts_code, period, start_date, end_date))
            if api_name == "moneyflow":
                return _result(api_name, self._moneyflow(ts_code))
            if api_name == "fina_indicator":
                return _result(api_name, self._fina_indicator(ts_code, start_date, end_date))
            if api_name == "income":
                return _result(api_name, self._income(ts_code, start_date, end_date))
            if api_name == "balancesheet":
                return _result(api_name, self._balancesheet(ts_code, start_date, end_date))
            if api_name == "cashflow":
                return _result(api_name, self._cashflow(ts_code, start_date, end_date))
            if api_name == "dividend":
                return _result(api_name, self._dividend(ts_code))
            if api_name == "anns_d":
                return _result(api_name, self._announcements(ts_code, start_date, end_date))
            if api_name == "stock_basic":
                return _result(api_name, self._stock_basic(ts_code))
            if api_name == "stock_company":
                return _result(api_name, self._stock_company(ts_code))
            if api_name == "stk_holdernumber":
                return _result(api_name, self._holder_number(ts_code, start_date, end_date))
            if api_name == "share_float":
                return _result(api_name, self._share_float(ts_code, start_date, end_date))
            if api_name == "top10_holders":
                return _result(api_name, self._top_holders(ts_code, start_date, end_date))
        except Exception as exc:  # noqa: BLE001 - upstream public pages are unstable
            raise TushareError(f"AkShare {api_name} 抓取失败：{exc}") from exc
        finally:
            if self.pause:
                time.sleep(self.pause)
        raise TushareError(f"AkShare 暂未映射接口：{api_name}")

    def _hist(self, ts_code: str, period: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_zh_a_hist(
            symbol=_symbol(ts_code),
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust="",
            timeout=self.timeout,
        )
        rows = []
        for row in _records(df):
            trade_date = _date8(row.get("日期"))
            if not trade_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": _num(row.get("开盘")),
                    "close": _num(row.get("收盘")),
                    "high": _num(row.get("最高")),
                    "low": _num(row.get("最低")),
                    "vol": _num(row.get("成交量")),
                    "amount": _num(row.get("成交额")),
                    "pct_chg": _num(row.get("涨跌幅")),
                    "change": _num(row.get("涨跌额")),
                    "turnover_rate": _num(row.get("换手率")),
                    "source": "akshare_stock_zh_a_hist",
                }
            )
        return rows

    def _income(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_profit_sheet_by_report_em(symbol=_em_symbol(ts_code))
        rows = []
        for row in _records(df):
            end = _date8(row.get("报告日") or row.get("REPORT_DATE") or row.get("日期"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "ann_date": _date8(row.get("公告日期")),
                    "total_revenue": _num(row.get("营业总收入")),
                    "revenue": _num(row.get("营业收入")),
                    "oper_cost": _num(row.get("营业成本")),
                    "operate_profit": _num(row.get("营业利润")),
                    "total_profit": _num(row.get("利润总额")),
                    "n_income": _num(row.get("净利润")),
                    "n_income_attr_p": _num(row.get("归属于母公司股东的净利润")),
                    "basic_eps": _num(row.get("基本每股收益")),
                    "diluted_eps": _num(row.get("稀释每股收益")),
                    "source": "akshare_stock_profit_sheet_by_report_em",
                    "raw": _clean_raw(row),
                }
            )
        return rows

    def _balancesheet(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_balance_sheet_by_report_em(symbol=_em_symbol(ts_code))
        rows = []
        for row in _records(df):
            end = _date8(row.get("报告日") or row.get("REPORT_DATE") or row.get("日期"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "ann_date": _date8(row.get("公告日期")),
                    "total_assets": _num(row.get("资产总计")),
                    "total_liab": _num(row.get("负债合计")),
                    "total_hldr_eqy_exc_min_int": _num(row.get("归属于母公司股东权益合计")),
                    "total_hldr_eqy_inc_min_int": _num(row.get("所有者权益合计")),
                    "money_cap": _num(row.get("货币资金")),
                    "accounts_receiv": _num(row.get("应收账款")),
                    "inventories": _num(row.get("存货")),
                    "fix_assets": _num(row.get("固定资产")),
                    "source": "akshare_stock_balance_sheet_by_report_em",
                    "raw": _clean_raw(row),
                }
            )
        return rows

    def _cashflow(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_cash_flow_sheet_by_report_em(symbol=_em_symbol(ts_code))
        rows = []
        for row in _records(df):
            end = _date8(row.get("报告日") or row.get("REPORT_DATE") or row.get("日期"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "ann_date": _date8(row.get("公告日期")),
                    "n_cashflow_act": _num(row.get("经营活动产生的现金流量净额")),
                    "n_cashflow_inv_act": _num(row.get("投资活动产生的现金流量净额")),
                    "n_cash_flows_fnc_act": _num(row.get("筹资活动产生的现金流量净额")),
                    "c_cash_equ_end_period": _num(row.get("期末现金及现金等价物余额")),
                    "source": "akshare_stock_cash_flow_sheet_by_report_em",
                    "raw": _clean_raw(row),
                }
            )
        return rows

    def _moneyflow(self, ts_code: str) -> list[dict[str, Any]]:
        df = self.ak.stock_individual_fund_flow(stock=_symbol(ts_code), market=_market(ts_code))
        rows = []
        for row in _records(df):
            trade_date = _date8(row.get("日期"))
            if not trade_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "close": _num(row.get("收盘价")),
                    "pct_chg": _num(row.get("涨跌幅")),
                    "net_mf_amount": _num(row.get("主力净流入-净额")),
                    "net_mf_vol": None,
                    "buy_elg_amount": _num(row.get("超大单净流入-净额")),
                    "buy_lg_amount": _num(row.get("大单净流入-净额")),
                    "buy_md_amount": _num(row.get("中单净流入-净额")),
                    "buy_sm_amount": _num(row.get("小单净流入-净额")),
                    "net_mf_ratio": _num(row.get("主力净流入-净占比")),
                    "source": "akshare_stock_individual_fund_flow",
                }
            )
        return rows

    def _fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start_year = str(start_date or "19000101")[:4]
        df = self.ak.stock_financial_analysis_indicator(symbol=_symbol(ts_code), start_year=start_year)
        rows = []
        for row in _records(df):
            end = _date8(row.get("日期"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "eps": _num(row.get("摊薄每股收益(元)") or row.get("加权每股收益(元)")),
                    "dt_eps": _num(row.get("扣除非经常性损益后的每股收益(元)")),
                    "roe": _num(row.get("净资产收益率(%)")),
                    "roe_waa": _num(row.get("加权净资产收益率(%)")),
                    "grossprofit_margin": _num(row.get("销售毛利率(%)")),
                    "netprofit_margin": _num(row.get("销售净利率(%)")),
                    "assets_turn": _num(row.get("总资产周转率(次)")),
                    "current_ratio": _num(row.get("流动比率")),
                    "quick_ratio": _num(row.get("速动比率")),
                    "debt_to_assets": _num(row.get("资产负债率(%)")),
                    "total_assets": _num(row.get("总资产(元)")),
                    "netprofit_yoy": _num(row.get("净利润增长率(%)")),
                    "assets_yoy": _num(row.get("总资产增长率(%)")),
                    "source": "akshare_stock_financial_analysis_indicator",
                }
            )
        return rows

    def _dividend(self, ts_code: str) -> list[dict[str, Any]]:
        df = self.ak.stock_dividend_cninfo(symbol=_symbol(ts_code))
        rows = []
        for row in _records(df):
            ann_date = _date8(row.get("实施方案公告日期"))
            rows.append(
                {
                    "ts_code": ts_code,
                    "ann_date": ann_date,
                    "record_date": _date8(row.get("股权登记日")),
                    "ex_date": _date8(row.get("除权日")),
                    "pay_date": _date8(row.get("派息日")),
                    "stk_div": _num(row.get("送股比例")),
                    "stk_bo_rate": _num(row.get("转增比例")),
                    "cash_div": _num(row.get("派息比例")),
                    "div_proc": row.get("分红类型") or "",
                    "div_plan": row.get("实施方案分红说明") or "",
                    "end_date": _report_date(row.get("报告时间")),
                    "source": "akshare_stock_dividend_cninfo",
                }
            )
        return [row for row in rows if row.get("ann_date") or row.get("record_date")]

    def _announcements(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_zh_a_disclosure_report_cninfo(symbol=_symbol(ts_code), start_date=start_date, end_date=end_date)
        rows = []
        for row in _records(df):
            ann_date = _date8(row.get("公告时间"))
            rows.append(
                {
                    "ts_code": ts_code,
                    "ann_date": ann_date,
                    "title": row.get("公告标题") or "",
                    "url": row.get("公告链接") or "",
                    "source": "akshare_cninfo_disclosure",
                }
            )
        return [row for row in rows if row.get("title") or row.get("url")]

    def _stock_basic(self, ts_code: str) -> list[dict[str, Any]]:
        info = self._stock_info(ts_code)
        if not info:
            return []
        return [
            {
                "ts_code": ts_code,
                "symbol": _symbol(ts_code),
                "name": info.get("股票简称") or info.get("名称") or "",
                "industry": info.get("行业") or "",
                "market": info.get("市场") or "",
                "list_date": _date8(info.get("上市时间") or info.get("上市日期")),
                "source": "akshare_stock_individual_info_em",
            }
        ]

    def _stock_company(self, ts_code: str) -> list[dict[str, Any]]:
        info = self._stock_info(ts_code)
        if not info:
            return []
        return [
            {
                "ts_code": ts_code,
                "com_name": info.get("股票简称") or info.get("名称") or "",
                "exchange": ts_code.split(".", 1)[1],
                "industry": info.get("行业") or "",
                "main_business": info.get("主营业务") or "",
                "reg_capital": _num(info.get("总股本")),
                "source": "akshare_stock_individual_info_em",
                "raw": _clean_raw(info),
            }
        ]

    def _stock_info(self, ts_code: str) -> dict[str, Any]:
        try:
            df = self.ak.stock_individual_info_em(symbol=_symbol(ts_code), timeout=self.timeout)
        except Exception:
            return {}
        info = {}
        for row in _records(df):
            key = str(row.get("item") or row.get("项目") or row.get("指标") or "")
            value = row.get("value") if "value" in row else row.get("值")
            if key:
                info[key] = value
        return info

    def _holder_number(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_zh_a_gdhs_detail_em(symbol=_symbol(ts_code))
        rows = []
        for row in _records(df):
            end = _date8(row.get("股东户数统计截止日"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "ann_date": _date8(row.get("股东户数公告日期")),
                    "holder_num": _num(row.get("股东户数-本次")),
                    "holder_num_prev": _num(row.get("股东户数-上次")),
                    "change": _num(row.get("股东户数-增减")),
                    "change_ratio": _num(row.get("股东户数-增减比例")),
                    "avg_hold": _num(row.get("户均持股数量")),
                    "avg_mv": _num(row.get("户均持股市值")),
                    "total_share": _num(row.get("总股本")),
                    "total_mv": _num(row.get("总市值")),
                    "source": "akshare_stock_zh_a_gdhs_detail_em",
                }
            )
        return rows

    def _share_float(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_zh_a_gbjg_em(symbol=ts_code)
        rows = []
        for row in _records(df):
            date_value = _date8(row.get("变更日期"))
            if not date_value or date_value < start_date or date_value > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "float_date": date_value,
                    "ann_date": date_value,
                    "float_share": _num(row.get("已流通股份") or row.get("已上市流通A股")),
                    "total_share": _num(row.get("总股本")),
                    "limit_share": _num(row.get("流通受限股份")),
                    "change_reason": row.get("变动原因") or "",
                    "source": "akshare_stock_zh_a_gbjg_em",
                }
            )
        return rows

    def _top_holders(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        df = self.ak.stock_main_stock_holder(stock=_symbol(ts_code))
        rows = []
        for row in _records(df):
            end = _date8(row.get("截至日期"))
            if not end or end < start_date or end > end_date:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": end,
                    "ann_date": _date8(row.get("公告日期")),
                    "holder_name": row.get("股东名称") or row.get("股东") or "",
                    "hold_amount": _num(row.get("持股数量")),
                    "hold_ratio": _num(row.get("持股比例")),
                    "holder_num": _num(row.get("股东总数")),
                    "avg_hold": _num(row.get("平均持股数")),
                    "source": "akshare_stock_main_stock_holder",
                }
            )
        return [row for row in rows if row.get("holder_name")]


def _result(api_name: str, records: list[dict[str, Any]]) -> TushareResult:
    fields = sorted({key for row in records for key in row})
    return TushareResult(api_name=api_name, fields=fields, records=records)


def _normalize_or_empty(value: Any) -> str:
    try:
        return normalize_ts_code(str(value or ""))
    except ValueError:
        return ""


def _symbol(ts_code: str) -> str:
    return normalize_ts_code(ts_code).split(".", 1)[0]


def _market(ts_code: str) -> str:
    normalized = normalize_ts_code(ts_code)
    if normalized.endswith(".SH"):
        return "sh"
    if normalized.endswith(".BJ"):
        return "bj"
    return "sz"


def _em_symbol(ts_code: str) -> str:
    normalized = normalize_ts_code(ts_code)
    symbol, exchange = normalized.split(".", 1)
    return f"{exchange}{symbol}"


def _records(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", False):
        return []
    return [dict(row) for row in df.to_dict("records")]


def _clean_raw(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _clean_value(value) for key, value in row.items()}


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            return value.isoformat()
        except ValueError:
            return None
    if isinstance(value, date):
        try:
            return value.isoformat()
        except ValueError:
            return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    text = str(value)
    if text in {"NaT", "nan", "None"}:
        return None
    return value


def _date8(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        try:
            return value.strftime("%Y%m%d")
        except ValueError:
            return ""
    if isinstance(value, date):
        try:
            return value.strftime("%Y%m%d")
        except ValueError:
            return ""
    text = str(value).strip()
    if not text or text in {"NaT", "nan", "None"}:
        return ""
    digits = text[:10].replace("-", "").replace("/", "")
    return digits if len(digits) >= 8 else ""


def _report_date(value: Any) -> str:
    text = str(value or "")
    if "一季报" in text:
        return f"{text[:4]}0331" if text[:4].isdigit() else ""
    if "半年报" in text:
        return f"{text[:4]}0630" if text[:4].isdigit() else ""
    if "三季报" in text:
        return f"{text[:4]}0930" if text[:4].isdigit() else ""
    if "年报" in text:
        return f"{text[:4]}1231" if text[:4].isdigit() else ""
    return _date8(value)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result
