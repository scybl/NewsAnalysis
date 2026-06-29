from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

import requests

from .tushare_client import TushareError, TushareResult
from .utils import normalize_ts_code


class EastmoneyClient:
    def __init__(self, timeout: int = 30, pause: float = 0.2):
        self.source_name = "Eastmoney"
        self.timeout = timeout
        self.pause = pause
        self._request_cache: dict[tuple[Any, ...], Any] = {}

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        params = params or {}
        if api_name in {"repurchase", "disclosure_date", "sw_daily"}:
            return _result(api_name, [])
        ts_code = normalize_ts_code(str(params.get("ts_code") or ""))
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        if api_name in {"daily", "weekly", "monthly"}:
            records = self._kline(ts_code, start_date, end_date, api_name)
            return _result(api_name, records)
        if api_name == "daily_basic":
            records = self._daily_basic(ts_code, start_date, end_date)
            return _result(api_name, records)
        if api_name == "adj_factor":
            return _result(api_name, self._adj_factor(ts_code, start_date, end_date))
        if api_name == "stock_basic":
            return _result(api_name, [self._stock_basic(ts_code)])
        if api_name == "namechange":
            return _result(api_name, self._namechange(ts_code))
        if api_name == "stock_company":
            return _result(api_name, [self._stock_company(ts_code)])
        if api_name == "stk_managers":
            return _result(api_name, self._stk_managers(ts_code))
        if api_name == "stk_rewards":
            return _result(api_name, self._stk_rewards(ts_code))
        if api_name == "index_member_all":
            return _result(api_name, self._industry_member(ts_code))
        if api_name == "income":
            return _result(api_name, self._income(ts_code, start_date, end_date))
        if api_name == "balancesheet":
            return _result(api_name, self._balance(ts_code, start_date, end_date))
        if api_name == "cashflow":
            return _result(api_name, self._cashflow(ts_code, start_date, end_date))
        if api_name == "fina_indicator":
            return _result(api_name, self._indicators(ts_code, start_date, end_date))
        if api_name == "stk_limit":
            return _result(api_name, self._limits(ts_code, start_date, end_date))
        if api_name == "suspend_d":
            return _result(api_name, self._suspend(ts_code, start_date, end_date))
        if api_name == "moneyflow":
            return _result(api_name, self._moneyflow(ts_code, start_date, end_date))
        if api_name == "margin_detail":
            return _result(api_name, self._margin_detail(ts_code, start_date, end_date))
        if api_name == "top10_holders":
            return _result(api_name, self._top_holders(ts_code, free_float=False, start_date=start_date, end_date=end_date))
        if api_name == "top10_floatholders":
            return _result(api_name, self._top_holders(ts_code, free_float=True, start_date=start_date, end_date=end_date))
        if api_name == "stk_holdernumber":
            return _result(api_name, self._holder_number(ts_code, start_date, end_date))
        if api_name == "stk_holdertrade":
            return _result(api_name, self._holder_trade(ts_code, start_date, end_date))
        if api_name == "pledge_stat":
            return _result(api_name, self._pledge_stat(ts_code, start_date, end_date))
        if api_name == "pledge_detail":
            return _result(api_name, self._pledge_detail(ts_code, start_date, end_date))
        if api_name == "dividend":
            return _result(api_name, self._dividend(ts_code))
        if api_name == "forecast":
            return _result(api_name, self._forecast(ts_code, start_date, end_date))
        if api_name == "express":
            return _result(api_name, self._express(ts_code, start_date, end_date))
        if api_name == "fina_mainbz":
            return _result(api_name, self._main_business(ts_code))
        if api_name == "fina_audit":
            return _result(api_name, self._fina_audit(ts_code))
        if api_name == "share_float":
            return _result(api_name, self._share_float(ts_code, start_date, end_date))
        if api_name == "block_trade":
            return _result(api_name, self._block_trade(ts_code, start_date, end_date))
        if api_name == "anns_d":
            return _result(api_name, self._announcements(ts_code, start_date, end_date))
        raise TushareError(f"Eastmoney 暂未映射接口：{api_name}")

    def _kline(self, ts_code: str, start_date: Any, end_date: Any, api_name: str) -> list[dict[str, Any]]:
        try:
            return self._kline_with_fqt(ts_code, start_date, end_date, api_name, fqt="1")
        except TushareError:
            return self._tencent_kline(ts_code, start_date, end_date, api_name)

    def _kline_with_fqt(self, ts_code: str, start_date: Any, end_date: Any, api_name: str, fqt: str) -> list[dict[str, Any]]:
        try:
            payload = self._kline_payload(ts_code, start_date, end_date, api_name, fqt=fqt)
        except TushareError:
            if fqt != "1":
                raise
            return self._tencent_kline(ts_code, start_date, end_date, api_name)
        rows = []
        for raw in (payload.get("klines") or []):
            parts = str(raw).split(",")
            if len(parts) < 11:
                continue
            date = parts[0].replace("-", "")
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": date,
                    "open": _num(parts[1]),
                    "close": _num(parts[2]),
                    "high": _num(parts[3]),
                    "low": _num(parts[4]),
                    "vol": _num(parts[5]),
                    "amount": _num(parts[6]),
                    "pct_chg": _num(parts[8]),
                    "change": _num(parts[9]),
                    "source": "eastmoney" if fqt == "1" else f"eastmoney_fqt_{fqt}",
                }
            )
        return rows

    def _daily_basic(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        try:
            payload = self._kline_payload(ts_code, start_date, end_date, "daily")
            klines = payload.get("klines") or []
        except TushareError:
            klines = []
        snapshot = self._stock_snapshot(ts_code)
        rows = []
        if klines:
            for raw in klines:
                parts = str(raw).split(",")
                if len(parts) < 11:
                    continue
                rows.append(self._daily_basic_row(ts_code, parts[0].replace("-", ""), _num(parts[2]), _num(parts[10]), snapshot, "eastmoney"))
        else:
            for row in self._tencent_kline(ts_code, start_date, end_date, "daily"):
                rows.append(self._daily_basic_row(ts_code, row.get("trade_date"), row.get("close"), None, snapshot, "tencent_fallback"))
        return rows

    def _daily_basic_row(self, ts_code: str, trade_date: Any, close: Any, turnover_rate: Any, snapshot: dict[str, Any], source: str) -> dict[str, Any]:
        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "close": close,
            "turnover_rate": turnover_rate,
            "volume_ratio": snapshot.get("volume_ratio"),
            "pe": snapshot.get("pe"),
            "pe_ttm": snapshot.get("pe_ttm"),
            "pb": snapshot.get("pb"),
            "total_mv": snapshot.get("total_mv"),
            "circ_mv": snapshot.get("circ_mv"),
            "source": source,
        }

    def _adj_factor(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        try:
            raw = {row.get("trade_date"): row for row in self._kline_with_fqt(ts_code, start_date, end_date, "daily", fqt="0")}
            adjusted = self._kline(ts_code, start_date, end_date, "daily")
        except TushareError:
            return self._tencent_adj_factor(ts_code, start_date, end_date)
        rows = []
        for row in adjusted:
            date = row.get("trade_date")
            raw_close = _num((raw.get(date) or {}).get("close"))
            adjusted_close = _num(row.get("close"))
            factor = round(adjusted_close / raw_close, 8) if raw_close and adjusted_close else None
            rows.append({"ts_code": ts_code, "trade_date": date, "adj_factor": factor, "source": "eastmoney_qfq_ratio"})
        return rows

    def _limits(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._kline(ts_code, start_date, end_date, "daily")
        ratio = 0.2 if ts_code.endswith(".SH") and ts_code.startswith("688") else 0.1
        result = []
        for row in rows:
            pre_close = _num(row.get("close")) - (_num(row.get("change")) or 0)
            if not pre_close:
                continue
            result.append(
                {
                    "ts_code": ts_code,
                    "trade_date": row.get("trade_date"),
                    "up_limit": round(pre_close * (1 + ratio), 2),
                    "down_limit": round(pre_close * (1 - ratio), 2),
                    "source": "eastmoney_estimated",
                }
            )
        return result

    def _suspend(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        dates = self._suspend_dates(start_date, end_date)
        if not dates:
            dates = [_date_dash(_date_param(end_date, "20500101"))]
        symbol = ts_code.split(".")[0]
        rows = []
        seen: set[tuple[str, str, str]] = set()
        for date in dates[:10]:
            try:
                page_rows = self._datacenter(
                    "RPT_CUSTOM_SUSPEND_DATA_INTERFACE",
                    f'(MARKET="全部")(DATETIME=\'{date}\')',
                    page_size=500,
                    sort_columns="SUSPEND_START_DATE",
                    sort_types="-1",
                )
            except TushareError:
                continue
            for row in page_rows:
                if str(row.get("SECURITY_CODE") or "") != symbol:
                    continue
                suspend_date = _date8(row.get("SUSPEND_START_DATE") or row.get("SUSPEND_START_TIME"))
                if not _date_in_range(suspend_date, start_date, end_date):
                    continue
                key = (symbol, str(row.get("SUSPEND_START_TIME") or ""), str(row.get("SUSPEND_END_TIME") or ""))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "ts_code": ts_code,
                        "suspend_date": suspend_date,
                        "resume_date": _date8(row.get("PREDICT_RESUME_DATE") or row.get("SUSPEND_END_TIME")),
                        "suspend_timing": row.get("SUSPEND_START_TIME") or "",
                        "resume_timing": row.get("SUSPEND_END_TIME") or "",
                        "suspend_type": row.get("SUSPEND_EXPIRE") or "",
                        "reason": row.get("SUSPEND_REASON") or "",
                        "source": "eastmoney_suspend_best_effort",
                    }
                )
        return sorted(rows, key=lambda item: str(item.get("suspend_date") or ""), reverse=True)

    def _suspend_dates(self, start_date: Any, end_date: Any) -> list[str]:
        rows = self._datacenter(
            "RPT_SUSPEND_DATE",
            "",
            page_size=500,
            sort_columns="SUSPEND_START_DATE",
            sort_types="-1",
        )
        result = []
        for row in rows:
            date = _date8(row.get("SUSPEND_START_DATE"))
            if _date_in_range(date, start_date, end_date):
                result.append(_date_dash(date))
        return result

    def _stock_basic(self, ts_code: str) -> dict[str, Any]:
        org = self._org_basic(ts_code)
        financial = self._financial_rows("RPT_DMSK_FN_INCOME", ts_code, page_size=1)
        first = org or (financial[0] if financial else {})
        symbol, exchange = ts_code.split(".")
        return {
            "ts_code": ts_code,
            "symbol": symbol,
            "name": first.get("SECURITY_NAME_ABBR") or "",
            "fullname": first.get("ORG_NAME") or first.get("SECURITY_NAME_ABBR") or "",
            "area": first.get("REGIONBK") or first.get("PROVINCE") or "",
            "industry": first.get("EM2016") or first.get("INDUSTRY_NAME") or "",
            "market": first.get("TRADE_MARKET") or first.get("MARKET") or "",
            "list_date": _date8(first.get("LISTING_DATE")),
            "exchange": exchange,
            "list_status": "L",
            "source": "eastmoney",
        }

    def _namechange(self, ts_code: str) -> list[dict[str, Any]]:
        row = self._org_basic(ts_code)
        names = [item.strip() for item in str(row.get("FORMERNAME") or "").replace("->", "→").split("→") if item.strip()]
        return [
            {
                "ts_code": ts_code,
                "name": name,
                "start_date": "",
                "end_date": "",
                "change_reason": "东方财富公司概况 formername",
                "source": "eastmoney_org_basic",
            }
            for name in names
        ]

    def _stock_company(self, ts_code: str) -> dict[str, Any]:
        basic = self._stock_basic(ts_code)
        org = self._org_basic(ts_code)
        return {
            "ts_code": ts_code,
            "com_name": org.get("ORG_NAME") or basic.get("fullname") or basic.get("name") or "",
            "exchange": basic.get("exchange") or "",
            "chairman": org.get("CHAIRMAN") or "",
            "manager": org.get("PRESIDENT") or "",
            "secretary": org.get("SECRETARY") or "",
            "reg_capital": org.get("REG_CAPITAL"),
            "setup_date": _date8(org.get("FOUND_DATE")),
            "province": org.get("PROVINCE") or basic.get("area") or "",
            "city": org.get("ADDRESS") or "",
            "introduction": org.get("ORG_PROFILE") or org.get("ORG_PROFIE") or "",
            "website": org.get("ORG_WEB") or "",
            "email": org.get("ORG_EMAIL") or "",
            "office": org.get("ADDRESS") or "",
            "employees": org.get("EMP_NUM"),
            "main_business": org.get("MAIN_BUSINESS") or "",
            "business_scope": org.get("BUSINESS_SCOPE") or "",
            "source": "eastmoney",
        }

    def _stk_managers(self, ts_code: str) -> list[dict[str, Any]]:
        org = self._org_basic(ts_code)
        people = [
            ("chairman", "董事长", org.get("CHAIRMAN")),
            ("manager", "总经理/行长", org.get("PRESIDENT")),
            ("secretary", "董秘", org.get("SECRETARY")),
            ("legal_person", "法定代表人", org.get("LEGAL_PERSON")),
        ]
        return [
            {"ts_code": ts_code, "name": name, "title": title, "gender": "", "lev": key, "source": "eastmoney_org_basic"}
            for key, title, name in people
            if name
        ]

    def _stk_rewards(self, ts_code: str) -> list[dict[str, Any]]:
        data = self._company_management(ts_code)
        rows = []
        for row in data.get("gglb") or []:
            rows.append(
                {
                    "ts_code": ts_code,
                    "ann_date": "",
                    "end_date": "",
                    "name": row.get("PERSON_NAME") or "",
                    "title": row.get("POSITION") or "",
                    "reward": row.get("SALARY"),
                    "hold_vol": row.get("HOLD_NUM"),
                    "gender": row.get("SEX") or "",
                    "edu": row.get("HIGH_DEGREE") or "",
                    "age": row.get("AGE"),
                    "begin_date": _date8(str(row.get("INCUMBENT_TIME") or "").split("至")[0]),
                    "source": "eastmoney_f10_company_management",
                }
            )
        return rows

    def _company_management(self, ts_code: str) -> dict[str, Any]:
        code = _em_f10_code(ts_code)
        try:
            return self._json(
                "https://emweb.securities.eastmoney.com/PC_HSF10/CompanyManagement/PageAjax",
                {"code": code},
                referer=f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanyManagement/Index?type=web&code={code}",
            )
        except TushareError:
            return {}

    def _industry_member(self, ts_code: str) -> list[dict[str, Any]]:
        rows = self._financial_rows("RPT_DMSK_FN_INCOME", ts_code, page_size=1)
        first = rows[0] if rows else {}
        name = first.get("INDUSTRY_NAME") or ""
        code = first.get("INDUSTRY_CODE") or ""
        if not name and not code:
            return []
        return [{"ts_code": ts_code, "l1_code": code, "l1_name": name, "l3_code": code, "l3_name": name, "is_new": "Y", "source": "eastmoney"}]

    def _income(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "f_ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "report_type": row.get("REPORT_TYPE_CODE") or "",
                "total_revenue": row.get("TOTAL_OPERATE_INCOME"),
                "revenue": row.get("TOTAL_OPERATE_INCOME"),
                "operate_profit": row.get("OPERATE_PROFIT"),
                "total_profit": row.get("TOTAL_PROFIT"),
                "n_income": row.get("PARENT_NETPROFIT"),
                "n_income_attr_p": row.get("PARENT_NETPROFIT"),
                "income_tax": row.get("INCOME_TAX"),
                "source": "eastmoney",
            }
            for row in self._filter_date(self._financial_rows("RPT_DMSK_FN_INCOME", ts_code), start_date, end_date)
        ]

    def _balance(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "f_ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "report_type": row.get("REPORT_TYPE_CODE") or "",
                "total_assets": row.get("TOTAL_ASSETS"),
                "total_liab": row.get("TOTAL_LIABILITIES"),
                "total_hldr_eqy_exc_min_int": row.get("TOTAL_EQUITY"),
                "money_cap": row.get("MONETARYFUNDS"),
                "accounts_receiv": row.get("ACCOUNTS_RECE"),
                "inventories": row.get("INVENTORY"),
                "total_cur_assets": row.get("TOTAL_CURRENT_ASSETS"),
                "total_cur_liab": row.get("TOTAL_CURRENT_LIAB"),
                "fix_assets": row.get("FIXED_ASSET"),
                "source": "eastmoney",
            }
            for row in self._filter_date(self._financial_rows("RPT_DMSK_FN_BALANCE", ts_code), start_date, end_date)
        ]

    def _cashflow(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "f_ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "report_type": row.get("REPORT_TYPE_CODE") or "",
                "net_profit": row.get("NETPROFIT"),
                "n_cashflow_act": row.get("NETCASH_OPERATE"),
                "n_cashflow_inv_act": row.get("NETCASH_INVEST"),
                "n_cash_flows_fnc_act": row.get("NETCASH_FINANCE"),
                "c_cash_equ_end_period": row.get("END_CCE"),
                "source": "eastmoney",
            }
            for row in self._filter_date(self._financial_rows("RPT_DMSK_FN_CASHFLOW", ts_code), start_date, end_date)
        ]

    def _indicators(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        secucode = _secucode(ts_code)
        rows = self._datacenter(
            "RPT_F10_FINANCE_MAINFINADATA",
            f'(SECUCODE="{secucode}")',
            page_size=80,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "eps": row.get("EPSJB"),
                "dt_eps": row.get("EPSXS"),
                "roe": row.get("ROEJQ"),
                "roe_dt": row.get("ROEKCJQ"),
                "roa": row.get("ZZCJLL"),
                "grossprofit_margin": row.get("XSMLL"),
                "netprofit_margin": row.get("XSJLL"),
                "debt_to_assets": row.get("ZCFZL"),
                "current_ratio": row.get("LD"),
                "quick_ratio": row.get("SD"),
                "or_yoy": row.get("TOTALOPERATEREVETZ"),
                "netprofit_yoy": row.get("PARENTNETPROFITTZ"),
                "ocfps": row.get("MGJYXJJE"),
                "source": "eastmoney",
            }
            for row in self._filter_date(rows, start_date, end_date)
        ]

    def _moneyflow(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        data = {}
        ranges = [
            (_date_param(start_date, "19900101"), _date_param(end_date, "20500101")),
            (_recent_start(end_date, years=3), _date_param(end_date, "20500101")),
            (_recent_start(end_date, years=1), _date_param(end_date, "20500101")),
            (_recent_start(end_date, days=160), _date_param(end_date, "20500101")),
        ]
        seen_ranges: set[tuple[str, str]] = set()
        for index, (beg, end) in enumerate(ranges):
            if (beg, end) in seen_ranges:
                continue
            seen_ranges.add((beg, end))
            try:
                data = self._moneyflow_payload(ts_code, beg, end)
                if ((data.get("data") or {}).get("klines") or []):
                    break
            except TushareError:
                if index < len(ranges) - 1:
                    time.sleep(2 + index * 3)
                data = {}
                continue
        return self._parse_moneyflow(ts_code, data)

    def _moneyflow_payload(self, ts_code: str, beg: str, end: str) -> dict[str, Any]:
        try:
            return self._curl_json(
                "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                {
                    "secid": _secid(ts_code),
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
                    "klt": "101",
                    "beg": beg,
                    "end": end,
                    "lmt": "1000000",
                },
            )
        except TushareError as exc:
            time.sleep(2)
            raise exc

    def _parse_moneyflow(self, ts_code: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for raw in ((data.get("data") or {}).get("klines") or []):
            parts = str(raw).split(",")
            if len(parts) < 13:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": parts[0].replace("-", ""),
                    "net_mf_amount": _num(parts[1]),
                    "buy_sm_amount": _num(parts[2]),
                    "buy_md_amount": _num(parts[3]),
                    "buy_lg_amount": _num(parts[4]),
                    "buy_elg_amount": _num(parts[5]),
                    "net_mf_vol": _num(parts[6]),
                    "buy_sm_vol": _num(parts[7]),
                    "buy_md_vol": _num(parts[8]),
                    "buy_lg_vol": _num(parts[9]),
                    "buy_elg_vol": _num(parts[10]),
                    "close": _num(parts[11]),
                    "pct_chg": _num(parts[12]),
                    "source": "eastmoney_fflow",
                }
            )
        return rows

    def _margin_detail(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPTA_WEB_RZRQ_GGMX",
            f'(SECUCODE="{_secucode(ts_code)}")',
            page_size=500,
            sort_columns="DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "trade_date": _date8(row.get("DATE")),
                "rzye": row.get("RZYE"),
                "rqye": row.get("RQYE"),
                "rzmre": row.get("RZMRE"),
                "rzche": row.get("RZCHE"),
                "rzjme": row.get("RZJME"),
                "rqyl": row.get("RQYL"),
                "rqmcl": row.get("RQMCL"),
                "rqchl": row.get("RQCHL"),
                "rzrqye": row.get("RZRQYE"),
                "source": "eastmoney_margin",
            }
            for row in self._filter_trade_date(rows, start_date, end_date, "DATE")
        ]

    def _top_holders(self, ts_code: str, *, free_float: bool, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        report = "RPT_F10_EH_FREEHOLDERS" if free_float else "RPT_F10_EH_HOLDERS"
        rows = self._datacenter(
            report,
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="END_DATE,HOLDER_RANK",
            sort_types="-1,1",
        )
        ratio_key = "FREE_HOLDNUM_RATIO" if free_float else "HOLD_NUM_RATIO"
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("UPDATE_DATE")),
                "end_date": _date8(row.get("END_DATE")),
                "holder_name": row.get("HOLDER_NAME") or "",
                "hold_amount": row.get("HOLD_NUM"),
                "hold_ratio": row.get(ratio_key) or row.get("HOLD_RATIO"),
                "holder_type": row.get("HOLDER_TYPE") or "",
                "rank": row.get("HOLDER_RANK"),
                "source": "eastmoney_freeholders" if free_float else "eastmoney_holders",
            }
            for row in self._filter_report_date(rows, start_date, end_date, "END_DATE")
        ]

    def _holder_number(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_F10_EH_HOLDERNUM",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="END_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("END_DATE")),
                "holder_num": row.get("HOLDER_TOTAL_NUM"),
                "holder_num_change": row.get("HOLDER_TOTAL_NUMCHANGE"),
                "avg_hold_amt": row.get("AVG_HOLD_AMT"),
                "source": "eastmoney_holdernum",
            }
            for row in self._filter_report_date(rows, start_date, end_date, "END_DATE")
        ]

    def _holder_trade(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        holders = self._top_holders(ts_code, free_float=False, start_date=start_date, end_date=end_date)
        return [
            {
                "ts_code": ts_code,
                "ann_date": item.get("ann_date"),
                "holder_name": item.get("holder_name"),
                "change_vol": None,
                "change_ratio": None,
                "after_share": item.get("hold_amount"),
                "after_ratio": item.get("hold_ratio"),
                "source": "eastmoney_holders_snapshot",
            }
            for item in holders
        ]

    def _pledge_detail(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPTA_APP_ACCUMDETAILS",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="NOTICE_DATE",
            sort_types="-1",
        )
        result = []
        for row in self._filter_report_date(rows, start_date, end_date, "NOTICE_DATE"):
            result.append(
                {
                    "ts_code": ts_code,
                    "ann_date": _date8(row.get("NOTICE_DATE")),
                    "holder_name": row.get("HOLDER_NAME") or "",
                    "pledge_amount": row.get("PF_NUM"),
                    "pledge_ratio": row.get("PF_HOLD_RATIO"),
                    "total_share_ratio": row.get("PF_TSR"),
                    "pledgee": row.get("PF_ORG") or "",
                    "pledgee_type": row.get("PFORG_TYPE") or "",
                    "start_date": _date8(row.get("PF_START_DATE")),
                    "end_date": _date8(row.get("UNFREEZE_DATE")),
                    "is_release": "Y" if row.get("UNFREEZE_STATE") == "已解押" else "N",
                    "release_date": _date8(row.get("ACTUAL_UNFREEZE_DATE")),
                    "status": row.get("UNFREEZE_STATE") or "",
                    "warning_state": row.get("WARNING_STATE") or "",
                    "warning_line": row.get("WARNING_LINE"),
                    "open_line": row.get("OPENLINE"),
                    "purpose": row.get("PF_PURPOSE") or row.get("PF_REASON") or "",
                    "source": "eastmoney_pledge_detail",
                }
            )
        return result

    def _pledge_stat(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        detail = self._pledge_detail(ts_code, start_date, end_date)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in detail:
            date = str(row.get("ann_date") or "")
            if date:
                grouped.setdefault(date, []).append(row)
        rows = []
        for date, items in grouped.items():
            latest = items[0]
            rows.append(
                {
                    "ts_code": ts_code,
                    "end_date": date,
                    "pledge_count": len(items),
                    "unrest_pledge": sum(_num(item.get("pledge_amount")) or 0 for item in items if item.get("is_release") != "Y"),
                    "rest_pledge": sum(_num(item.get("pledge_amount")) or 0 for item in items if item.get("is_release") == "Y"),
                    "total_share": sum(_num(item.get("pledge_amount")) or 0 for item in items),
                    "pledge_ratio": latest.get("total_share_ratio"),
                    "source": "eastmoney_pledge_detail_derived",
                }
            )
        return sorted(rows, key=lambda item: str(item.get("end_date") or ""), reverse=True)

    def _dividend(self, ts_code: str) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_SHAREBONUS_DET",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE") or row.get("PLAN_NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "div_proc": row.get("ASSIGN_PROGRESS") or "",
                "stk_div": row.get("BONUS_IT_RATIO"),
                "cash_div": row.get("PRETAX_BONUS_RMB"),
                "record_date": _date8(row.get("EQUITY_RECORD_DATE")),
                "ex_date": _date8(row.get("EX_DIVIDEND_DATE")),
                "implementation": row.get("IMPL_PLAN_PROFILE") or "",
                "source": "eastmoney_dividend",
            }
            for row in rows
        ]

    def _forecast(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_PUBLIC_OP_NEWPREDICT",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORT_DATE")),
                "type": row.get("PREDICT_TYPE") or "",
                "p_change_min": row.get("PREDICT_RATIO_LOWER") or row.get("ADD_AMP_LOWER"),
                "p_change_max": row.get("PREDICT_RATIO_UPPER") or row.get("ADD_AMP_UPPER"),
                "net_profit_min": row.get("PREDICT_AMT_LOWER"),
                "net_profit_max": row.get("PREDICT_AMT_UPPER"),
                "summary": row.get("PREDICT_CONTENT") or "",
                "change_reason": row.get("CHANGE_REASON_EXPLAIN") or "",
                "source": "eastmoney_forecast",
            }
            for row in self._filter_report_date(rows, start_date, end_date, "REPORT_DATE")
        ]

    def _express(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_LICO_FN_CPD",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="REPORTDATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": _date8(row.get("NOTICE_DATE")),
                "end_date": _date8(row.get("REPORTDATE")),
                "revenue": row.get("TOTAL_OPERATE_INCOME"),
                "n_income": row.get("PARENT_NETPROFIT"),
                "diluted_eps": row.get("BASIC_EPS"),
                "bps": row.get("BPS"),
                "yoy_net_profit": row.get("SJLTZ"),
                "yoy_sales": row.get("YSTZ"),
                "source": "eastmoney_finance_cpd",
            }
            for row in self._filter_report_date(rows, start_date, end_date, "REPORTDATE")
        ]

    def _main_business(self, ts_code: str) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_F10_FN_MAINOP",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "end_date": _date8(row.get("REPORT_DATE")),
                "bz_item": row.get("ITEM_NAME") or "",
                "bz_code": row.get("ITEM_CODE") or "",
                "bz_sales": row.get("MAIN_BUSINESS_INCOME"),
                "bz_profit": row.get("MAIN_BUSINESS_RPOFIT"),
                "bz_cost": row.get("MAIN_BUSINESS_COST"),
                "curr_type": "",
                "source": "eastmoney_mainop",
            }
            for row in rows
        ]

    def _fina_audit(self, ts_code: str) -> list[dict[str, Any]]:
        org = self._org_basic(ts_code)
        firm = org.get("ACCOUNT_FIRM")
        return [{"ts_code": ts_code, "end_date": "", "audit_result": "", "audit_fees": None, "audit_agency": firm, "source": "eastmoney_org_basic"}] if firm else []

    def _share_float(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_LIFT_STAGE",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "ann_date": "",
                "float_date": _date8(row.get("FREE_DATE")),
                "float_share": row.get("FREE_SHARES"),
                "float_ratio": row.get("FREE_RATIO"),
                "holder_name": "",
                "share_type": row.get("FREE_SHARES_TYPE") or "",
                "source": "eastmoney_lift_stage",
            }
            for row in self._filter_report_date(rows, start_date, end_date, "FREE_DATE")
        ]

    def _block_trade(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        rows = self._datacenter(
            "RPT_DATA_BLOCKTRADE",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=500,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        return [
            {
                "ts_code": ts_code,
                "trade_date": _date8(row.get("TRADE_DATE")),
                "price": row.get("DEAL_PRICE"),
                "vol": row.get("DEAL_VOLUME"),
                "amount": row.get("DEAL_AMT"),
                "buyer": row.get("BUYER_NAME") or "",
                "seller": row.get("SELLER_NAME") or "",
                "source": "eastmoney_blocktrade",
            }
            for row in self._filter_trade_date(rows, start_date, end_date, "TRADE_DATE")
        ]

    def _announcements(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        symbol = ts_code.split(".")[0]
        rows = []
        start = _date_param(start_date, "")
        for page in range(1, 501):
            payload = self._curl_json(
                "https://np-anotice-stock.eastmoney.com/api/security/ann",
                {"sr": "-1", "page_size": "100", "page_index": str(page), "ann_type": "A", "client_source": "web", "stock_list": symbol},
                safe="",
            )
            data = payload.get("data") or {}
            items = data.get("list") or []
            if not items:
                break
            oldest = ""
            for item in items:
                ann_date = _date8(item.get("notice_date") or item.get("NOTICE_DATE") or item.get("display_time") or item.get("DISPLAY_TIME"))
                oldest = ann_date if not oldest or (ann_date and ann_date < oldest) else oldest
                if not _date_in_range(ann_date, start_date, end_date):
                    continue
                rows.append(
                    {
                        "ts_code": ts_code,
                        "ann_date": ann_date,
                        "title": item.get("title") or item.get("TITLE") or "",
                        "url": item.get("attach_url") or item.get("ATTACH_URL") or item.get("url") or "",
                        "type": ",".join(str(col.get("column_name") or col.get("COLUMN_NAME") or "") for col in item.get("columns") or [] if isinstance(col, dict)),
                        "source": "eastmoney_announcement",
                    }
                )
            total = int(data.get("total_hits") or 0)
            if page * 100 >= total or (start and oldest and oldest < start):
                break
        return rows

    def _stock_snapshot(self, ts_code: str) -> dict[str, Any]:
        try:
            data = self._json(
                "https://push2.eastmoney.com/api/qt/stock/get",
                {
                    "secid": _secid(ts_code),
                    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                    "fields": "f116,f117,f162,f167,f168,f10",
                },
            ).get("data") or {}
        except Exception:
            data = {}
        return {
            "total_mv": _wan(data.get("f116")),
            "circ_mv": _wan(data.get("f117")),
            "pe_ttm": _scaled(data.get("f162")),
            "pe": _scaled(data.get("f162")),
            "pb": _scaled(data.get("f167")),
            "volume_ratio": _scaled(data.get("f10")),
        }

    def _kline_payload(self, ts_code: str, start_date: Any, end_date: Any, api_name: str, fqt: str = "1") -> dict[str, Any]:
        data = self._curl_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {
                "secid": _secid(ts_code),
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": {"daily": "101", "weekly": "102", "monthly": "103"}[api_name],
                "fqt": fqt,
                "beg": _date_param(start_date, "19900101"),
                "end": _date_param(end_date, "20500101"),
                "lmt": "1000000",
            },
        )
        return data.get("data") or {}

    def _tencent_kline(self, ts_code: str, start_date: Any, end_date: Any, api_name: str, *, adjusted: bool = True) -> list[dict[str, Any]]:
        symbol, exchange = normalize_ts_code(ts_code).split(".")
        market = "sh" if exchange == "SH" else "sz"
        period = {"daily": "day", "weekly": "week", "monthly": "month"}[api_name]
        start = _date_param(start_date, "19900101")
        cursor = _date_param(end_date, "20500101")
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        rows = []
        seen: set[str] = set()
        fq = "qfq" if adjusted else "bfq"
        key = f"qfq{period}" if adjusted else period
        for _ in range(80):
            payload = self._json(
                url,
                {"param": f"{market}{symbol},{period},{_date_dash(start)},{_date_dash(cursor)},800,{fq}"},
            )
            data = (payload.get("data") or {}).get(f"{market}{symbol}") or {}
            page_rows = data.get(key) or []
            if not page_rows:
                break
            new_rows = []
            for item in page_rows:
                date = str(item[0]).replace("-", "") if item else ""
                if not date or date in seen:
                    continue
                seen.add(date)
                new_rows.append(item)
            if not new_rows:
                break
            rows = new_rows + rows
            first_date = str(new_rows[0][0]).replace("-", "")
            if first_date <= start:
                break
            cursor = _previous_date(first_date)
        parsed = []
        previous_close = None
        for item in rows:
            if len(item) < 6:
                continue
            close = _num(item[2])
            change = close - previous_close if close is not None and previous_close else None
            pct = round(change / previous_close * 100, 4) if change is not None and previous_close else None
            parsed.append(
                {
                    "ts_code": ts_code,
                    "trade_date": str(item[0]).replace("-", ""),
                    "open": _num(item[1]),
                    "close": close,
                    "high": _num(item[3]),
                    "low": _num(item[4]),
                    "vol": _num(item[5]),
                    "amount": None,
                    "pct_chg": pct,
                    "change": change,
                    "source": "tencent_qfq_fallback" if adjusted else "tencent_raw_fallback",
                }
            )
            if close is not None:
                previous_close = close
        return parsed

    def _tencent_adj_factor(self, ts_code: str, start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        raw = {row.get("trade_date"): row for row in self._tencent_kline(ts_code, start_date, end_date, "daily", adjusted=False)}
        adjusted = self._tencent_kline(ts_code, start_date, end_date, "daily", adjusted=True)
        rows = []
        for row in adjusted:
            date = row.get("trade_date")
            raw_close = _num((raw.get(date) or {}).get("close"))
            adjusted_close = _num(row.get("close"))
            factor = round(adjusted_close / raw_close, 8) if raw_close and adjusted_close else None
            rows.append({"ts_code": ts_code, "trade_date": date, "adj_factor": factor, "source": "tencent_qfq_ratio"})
        return rows

    def _financial_rows(self, report_name: str, ts_code: str, page_size: int = 500) -> list[dict[str, Any]]:
        return self._datacenter(
            report_name,
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=page_size,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )

    def _datacenter(self, report_name: str, filter_text: str, page_size: int = 80, sort_columns: str = "", sort_types: str = "") -> list[dict[str, Any]]:
        cache_key = ("datacenter", report_name, filter_text, page_size, sort_columns, sort_types)
        if cache_key in self._request_cache:
            return list(self._request_cache[cache_key])
        rows: list[dict[str, Any]] = []
        page_size = max(1, min(500, int(page_size or 80)))
        for page in range(1, 201):
            payload = self._curl_json(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                {
                    "reportName": report_name,
                    "columns": "ALL",
                    "filter": filter_text,
                    "pageNumber": str(page),
                    "pageSize": str(page_size),
                    "sortColumns": sort_columns,
                    "sortTypes": sort_types,
                },
                safe="",
            )
            result = payload.get("result") or {}
            page_rows = result.get("data") or []
            if not isinstance(page_rows, list) or not page_rows:
                break
            rows.extend(page_rows)
            pages = int(result.get("pages") or result.get("pageTotal") or 1)
            if page >= pages or len(page_rows) < page_size:
                break
        self._request_cache[cache_key] = list(rows)
        return rows

    def _filter_date(self, rows: list[dict[str, Any]], start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        return self._filter_report_date(rows, start_date, end_date, "REPORT_DATE")

    def _filter_report_date(self, rows: list[dict[str, Any]], start_date: Any, end_date: Any, key: str) -> list[dict[str, Any]]:
        start = _date_param(start_date, "")
        end = _date_param(end_date, "99999999")
        result = []
        for row in rows:
            date = _date8(row.get(key))
            if (not start or date >= start) and date <= end:
                result.append(row)
        return result

    def _filter_trade_date(self, rows: list[dict[str, Any]], start_date: Any, end_date: Any, key: str) -> list[dict[str, Any]]:
        return self._filter_report_date(rows, start_date, end_date, key)

    def _org_basic(self, ts_code: str) -> dict[str, Any]:
        rows = self._datacenter(
            "RPT_F10_ORG_BASICINFO",
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=1,
        )
        return rows[0] if rows else {}

    def _json(self, url: str, params: dict[str, Any], *, referer: str = "https://quote.eastmoney.com/") -> dict[str, Any]:
        cache_key = ("json", url, tuple(sorted(params.items())))
        if cache_key in self._request_cache:
            return self._request_cache[cache_key]
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": referer,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.text
        except Exception as exc:
            raise TushareError(f"Eastmoney 请求失败：{url} {exc}") from exc
        finally:
            if self.pause:
                time.sleep(self.pause)
        if not body.strip():
            raise TushareError(f"Eastmoney 返回空响应：{url}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise TushareError(f"Eastmoney JSON 解析失败：{url}") from exc
        self._request_cache[cache_key] = payload
        return payload

    def _curl_json(self, url: str, params: dict[str, Any], *, safe: str = ",") -> dict[str, Any]:
        cache_key = ("curl_json", url, tuple(sorted(params.items())))
        if cache_key in self._request_cache:
            return self._request_cache[cache_key]
        query = urllib.parse.urlencode(params, safe=safe)
        full_url = f"{url}?{query}"
        body = ""
        error = ""
        for attempt in range(3):
            try:
                result = subprocess.run(
                    [
                        "curl",
                        "-sS",
                        "--max-time",
                        str(max(5, int(self.timeout))),
                        "-H",
                        "User-Agent: Mozilla/5.0",
                        "-H",
                        "Accept: application/json,text/plain,*/*",
                        "-H",
                        "Referer: https://data.eastmoney.com/",
                        full_url,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise TushareError("系统缺少 curl，跳过 Eastmoney 接口。") from exc
            if self.pause:
                time.sleep(self.pause)
            body = result.stdout.strip()
            error = result.stderr.strip() or f"exit={result.returncode}"
            if body:
                break
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
        if not body:
            if "push2his.eastmoney.com" in url:
                try:
                    response = requests.get(
                        full_url,
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Accept": "application/json,text/plain,*/*",
                            "Referer": "https://quote.eastmoney.com/",
                        },
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    body = response.text.strip()
                except Exception:
                    body = ""
            if not body:
                raise TushareError(f"Eastmoney 返回空响应：{url} {error}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TushareError(f"Eastmoney JSON 解析失败：{url}") from exc
        self._request_cache[cache_key] = payload
        return payload


def _result(api_name: str, records: list[dict[str, Any]]) -> TushareResult:
    fields = sorted({key for row in records for key in row})
    return TushareResult(api_name=api_name, fields=fields, records=records)


def _secid(ts_code: str) -> str:
    code = normalize_ts_code(ts_code)
    symbol, exchange = code.split(".")
    market = "1" if exchange == "SH" else "0"
    return f"{market}.{symbol}"


def _secucode(ts_code: str) -> str:
    return normalize_ts_code(ts_code)


def _em_f10_code(ts_code: str) -> str:
    symbol, exchange = normalize_ts_code(ts_code).split(".")
    return f"{exchange}{symbol}"


def _date_param(value: Any, default: str) -> str:
    text = str(value or "").strip().replace("-", "")
    return text if text else default


def _date8(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:10].replace("-", "")


def _date_in_range(value: Any, start_date: Any, end_date: Any) -> bool:
    date = _date8(value)
    if not date:
        return True
    start = _date_param(start_date, "")
    end = _date_param(end_date, "99999999")
    return (not start or date >= start) and date <= end


def _date_dash(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _previous_date(value: Any) -> str:
    text = _date_param(value, "")
    try:
        return (datetime.strptime(text, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return text


def _recent_start(end_date: Any, *, years: int = 0, days: int = 0) -> str:
    end = _date_param(end_date, "")
    try:
        value = datetime.strptime(end, "%Y%m%d") if end else datetime.now()
    except ValueError:
        value = datetime.now()
    if years:
        return value.replace(year=value.year - years).strftime("%Y%m%d")
    return (value - timedelta(days=days)).strftime("%Y%m%d")


def _num(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _scaled(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return number / 100


def _wan(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number / 10000, 4)
