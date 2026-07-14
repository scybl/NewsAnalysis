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
    an empty/error dataset so validator/fallback clients can fill the gap.
    """

    source_name = "AkShare"

    def __init__(self, timeout: float = 20.0, pause: float = 0.2):
        self.timeout = timeout
        self.pause = pause
        self._hist_daily_cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
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
            if api_name == "daily_basic":
                return _result(api_name, self._daily_basic(ts_code, start_date, end_date))
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
        try:
            df = self.ak.stock_zh_a_hist(
                symbol=_symbol(ts_code),
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust="",
                timeout=self.timeout,
            )
        except Exception:
            fallback_rows = self._hist_from_daily(ts_code, period, start_date, end_date)
            if fallback_rows:
                return fallback_rows
            raise
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

    def _hist_from_daily(self, ts_code: str, period: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        cache = getattr(self, "_hist_daily_cache", None)
        if cache is None:
            cache = {}
            self._hist_daily_cache = cache
        cache_key = (ts_code, start_date, end_date)
        if cache_key not in cache:
            df = self.ak.stock_zh_a_daily(symbol=_daily_symbol(ts_code), start_date=start_date, end_date=end_date, adjust="")
            rows = [_daily_hist_row(ts_code, row) for row in _records(df)]
            rows = [row for row in rows if row.get("trade_date")]
            rows.sort(key=lambda item: str(item.get("trade_date") or ""))
            cache[cache_key] = rows
        rows = [dict(row) for row in cache[cache_key]]
        if period == "daily":
            return _with_period_change(rows)
        if period in {"weekly", "monthly"}:
            return _aggregate_hist_rows(rows, period)
        return []

    def _daily_basic(self, ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": row.get("ts_code"),
                "trade_date": row.get("trade_date"),
                "close": row.get("close"),
                "turnover_rate": row.get("turnover_rate"),
                "source": "akshare_stock_zh_a_hist_daily_basic",
            }
            for row in self._hist(ts_code, "daily", start_date, end_date)
            if row.get("trade_date")
        ]

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
                    "ann_date": _date8(_pick(row, "公告日期", "NOTICE_DATE")),
                    "total_revenue": _num(_pick(row, "营业总收入", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME")),
                    "revenue": _num(_pick(row, "营业收入", "OPERATE_INCOME", "TOTAL_OPERATE_INCOME")),
                    "oper_cost": _num(_pick(row, "营业成本", "OPERATE_COST", "TOTAL_OPERATE_COST")),
                    "operate_profit": _num(_pick(row, "营业利润", "OPERATE_PROFIT")),
                    "total_profit": _num(_pick(row, "利润总额", "TOTAL_PROFIT")),
                    "n_income": _num(_pick(row, "净利润", "NETPROFIT", "PARENT_NETPROFIT")),
                    "n_income_attr_p": _num(_pick(row, "归属于母公司股东的净利润", "PARENT_NETPROFIT")),
                    "basic_eps": _num(_pick(row, "基本每股收益", "BASIC_EPS")),
                    "diluted_eps": _num(_pick(row, "稀释每股收益", "DILUTED_EPS")),
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
                    "ann_date": _date8(_pick(row, "公告日期", "NOTICE_DATE")),
                    "total_assets": _num(_pick(row, "资产总计", "TOTAL_ASSETS")),
                    "total_liab": _num(_pick(row, "负债合计", "TOTAL_LIABILITIES")),
                    "total_hldr_eqy_exc_min_int": _num(_pick(row, "归属于母公司股东权益合计", "TOTAL_PARENT_EQUITY", "TOTAL_EQUITY")),
                    "total_hldr_eqy_inc_min_int": _num(_pick(row, "所有者权益合计", "TOTAL_EQUITY")),
                    "money_cap": _num(_pick(row, "货币资金", "MONETARYFUNDS", "MONETARY_FUND")),
                    "accounts_receiv": _num(_pick(row, "应收账款", "ACCOUNTS_RECE", "ACCOUNTS_RECEIVABLE")),
                    "inventories": _num(_pick(row, "存货", "INVENTORY", "INVENTORIES")),
                    "fix_assets": _num(_pick(row, "固定资产", "FIXED_ASSET", "FIX_ASSET")),
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
                    "ann_date": _date8(_pick(row, "公告日期", "NOTICE_DATE")),
                    "net_profit": _num(_pick(row, "净利润", "NETPROFIT")),
                    "n_cashflow_act": _num(_pick(row, "经营活动产生的现金流量净额", "NETCASH_OPERATE")),
                    "n_cashflow_inv_act": _num(_pick(row, "投资活动产生的现金流量净额", "NETCASH_INVEST")),
                    "n_cash_flows_fnc_act": _num(_pick(row, "筹资活动产生的现金流量净额", "NETCASH_FINANCE")),
                    "c_cash_equ_end_period": _num(_pick(row, "期末现金及现金等价物余额", "END_CCE")),
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


def _daily_symbol(ts_code: str) -> str:
    return f"{_market(ts_code)}{_symbol(ts_code)}"


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


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value) not in {"", "NaT", "nan", "None"}:
            return value
    return None


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


def _daily_hist_row(ts_code: str, row: dict[str, Any]) -> dict[str, Any]:
    turnover = _num(row.get("turnover"))
    return {
        "ts_code": ts_code,
        "trade_date": _date8(row.get("date")),
        "open": _num(row.get("open")),
        "close": _num(row.get("close")),
        "high": _num(row.get("high")),
        "low": _num(row.get("low")),
        "vol": _divide(_num(row.get("volume")), 100),
        "amount": _num(row.get("amount")),
        "pct_chg": None,
        "change": None,
        "turnover_rate": turnover * 100 if turnover is not None else None,
        "source": "akshare_stock_zh_a_daily",
    }


def _with_period_change(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_close: float | None = None
    result = []
    for row in rows:
        item = dict(row)
        close = _num(item.get("close"))
        if close is not None and previous_close:
            change = close - previous_close
            item["change"] = round(change, 6)
            item["pct_chg"] = round(change / previous_close * 100, 6)
        if close is not None:
            previous_close = close
        result.append(item)
    return result


def _aggregate_hist_rows(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = _period_key(str(row.get("trade_date") or ""), period)
        if key is None:
            continue
        groups.setdefault(key, []).append(row)
    aggregated = []
    for key in sorted(groups):
        items = sorted(groups[key], key=lambda item: str(item.get("trade_date") or ""))
        first = items[0]
        last = items[-1]
        turnover_values = [_num(item.get("turnover_rate")) for item in items]
        aggregated.append(
            {
                "ts_code": last.get("ts_code"),
                "trade_date": last.get("trade_date"),
                "open": first.get("open"),
                "close": last.get("close"),
                "high": _max_value(item.get("high") for item in items),
                "low": _min_value(item.get("low") for item in items),
                "vol": _sum_values(item.get("vol") for item in items),
                "amount": _sum_values(item.get("amount") for item in items),
                "pct_chg": None,
                "change": None,
                "turnover_rate": _sum_values(value for value in turnover_values if value is not None),
                "source": f"akshare_stock_zh_a_daily_aggregated_{period}",
            }
        )
    return _with_period_change(aggregated)


def _period_key(trade_date: str, period: str) -> tuple[Any, ...] | None:
    try:
        parsed = datetime.strptime(trade_date, "%Y%m%d")
    except ValueError:
        return None
    if period == "weekly":
        iso = parsed.isocalendar()
        return (iso.year, iso.week)
    if period == "monthly":
        return (parsed.year, parsed.month)
    return None


def _divide(value: float | None, divisor: float) -> float | None:
    return value / divisor if value is not None else None


def _sum_values(values: Any) -> float | None:
    total = 0.0
    seen = False
    for value in values:
        number = _num(value)
        if number is None:
            continue
        total += number
        seen = True
    return total if seen else None


def _max_value(values: Any) -> float | None:
    numbers = [_num(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return max(numbers) if numbers else None


def _min_value(values: Any) -> float | None:
    numbers = [_num(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return min(numbers) if numbers else None
