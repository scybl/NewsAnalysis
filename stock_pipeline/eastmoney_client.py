from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from typing import Any

import requests

from .tushare_client import TushareError, TushareResult
from .utils import normalize_ts_code


class EastmoneyClient:
    def __init__(self, timeout: int = 30, pause: float = 0.2):
        self.source_name = "Eastmoney"
        self.timeout = timeout
        self.pause = pause

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        params = params or {}
        if api_name in {"namechange", "stk_managers", "stk_rewards", "adj_factor", "suspend_d", "moneyflow", "margin_detail", "express", "forecast", "dividend", "fina_mainbz", "fina_audit", "disclosure_date", "top10_holders", "top10_floatholders", "stk_holdernumber", "stk_holdertrade", "pledge_stat", "pledge_detail", "repurchase", "share_float", "block_trade", "anns_d", "sw_daily"}:
            return _result(api_name, [])
        ts_code = normalize_ts_code(str(params.get("ts_code") or ""))
        if api_name in {"daily", "weekly", "monthly"}:
            records = self._kline(ts_code, params.get("start_date"), params.get("end_date"), api_name)
            return _result(api_name, records)
        if api_name == "daily_basic":
            records = self._daily_basic(ts_code, params.get("start_date"), params.get("end_date"))
            return _result(api_name, records)
        if api_name == "stock_basic":
            return _result(api_name, [self._stock_basic(ts_code)])
        if api_name == "stock_company":
            return _result(api_name, [self._stock_company(ts_code)])
        if api_name == "index_member_all":
            return _result(api_name, self._industry_member(ts_code))
        if api_name == "income":
            return _result(api_name, self._income(ts_code, params.get("start_date"), params.get("end_date")))
        if api_name == "balancesheet":
            return _result(api_name, self._balance(ts_code, params.get("start_date"), params.get("end_date")))
        if api_name == "cashflow":
            return _result(api_name, self._cashflow(ts_code, params.get("start_date"), params.get("end_date")))
        if api_name == "fina_indicator":
            return _result(api_name, self._indicators(ts_code, params.get("start_date"), params.get("end_date")))
        if api_name == "stk_limit":
            return _result(api_name, self._limits(ts_code, params.get("start_date"), params.get("end_date")))
        raise TushareError(f"Eastmoney 暂未映射接口：{api_name}")

    def _kline(self, ts_code: str, start_date: Any, end_date: Any, api_name: str) -> list[dict[str, Any]]:
        try:
            payload = self._kline_payload(ts_code, start_date, end_date, api_name)
        except TushareError:
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
                    "source": "eastmoney",
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

    def _stock_basic(self, ts_code: str) -> dict[str, Any]:
        financial = self._financial_rows("RPT_DMSK_FN_INCOME", ts_code, page_size=1)
        first = financial[0] if financial else {}
        symbol, exchange = ts_code.split(".")
        return {
            "ts_code": ts_code,
            "symbol": symbol,
            "name": first.get("SECURITY_NAME_ABBR") or "",
            "fullname": first.get("SECURITY_NAME_ABBR") or "",
            "area": "",
            "industry": first.get("INDUSTRY_NAME") or "",
            "market": first.get("MARKET") or "",
            "exchange": exchange,
            "list_status": "L",
            "source": "eastmoney",
        }

    def _stock_company(self, ts_code: str) -> dict[str, Any]:
        basic = self._stock_basic(ts_code)
        return {
            "ts_code": ts_code,
            "com_name": basic.get("fullname") or basic.get("name") or "",
            "exchange": basic.get("exchange") or "",
            "province": basic.get("area") or "",
            "main_business": "",
            "business_scope": "",
            "source": "eastmoney",
        }

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

    def _kline_payload(self, ts_code: str, start_date: Any, end_date: Any, api_name: str) -> dict[str, Any]:
        data = self._curl_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {
                "secid": _secid(ts_code),
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": {"daily": "101", "weekly": "102", "monthly": "103"}[api_name],
                "fqt": "1",
                "beg": _date_param(start_date, "19900101"),
                "end": _date_param(end_date, "20500101"),
            },
        )
        return data.get("data") or {}

    def _tencent_kline(self, ts_code: str, start_date: Any, end_date: Any, api_name: str) -> list[dict[str, Any]]:
        symbol, exchange = normalize_ts_code(ts_code).split(".")
        market = "sh" if exchange == "SH" else "sz"
        period = {"daily": "day", "weekly": "week", "monthly": "month"}[api_name]
        start = _date_dash(_date_param(start_date, "19900101"))
        end = _date_dash(_date_param(end_date, "20500101"))
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        payload = self._json(
            url,
            {"param": f"{market}{symbol},{period},{start},{end},800,qfq"},
        )
        data = (payload.get("data") or {}).get(f"{market}{symbol}") or {}
        rows = data.get(f"qfq{period}") or data.get(period) or []
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
                    "source": "tencent_fallback",
                }
            )
            if close is not None:
                previous_close = close
        return parsed

    def _financial_rows(self, report_name: str, ts_code: str, page_size: int = 80) -> list[dict[str, Any]]:
        return self._datacenter(
            report_name,
            f'(SECURITY_CODE="{ts_code.split(".")[0]}")',
            page_size=page_size,
            sort_columns="REPORT_DATE",
            sort_types="-1",
        )

    def _datacenter(self, report_name: str, filter_text: str, page_size: int = 80, sort_columns: str = "", sort_types: str = "") -> list[dict[str, Any]]:
        payload = self._json(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {
                "reportName": report_name,
                "columns": "ALL",
                "filter": filter_text,
                "pageNumber": "1",
                "pageSize": str(page_size),
                "sortColumns": sort_columns,
                "sortTypes": sort_types,
            },
        )
        result = payload.get("result") or {}
        rows = result.get("data") or []
        return rows if isinstance(rows, list) else []

    def _filter_date(self, rows: list[dict[str, Any]], start_date: Any, end_date: Any) -> list[dict[str, Any]]:
        start = _date_param(start_date, "")
        end = _date_param(end_date, "99999999")
        result = []
        for row in rows:
            date = _date8(row.get("REPORT_DATE"))
            if (not start or date >= start) and date <= end:
                result.append(row)
        return result

    def _json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://quote.eastmoney.com/",
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
            return response.json()
        except json.JSONDecodeError as exc:
            raise TushareError(f"Eastmoney JSON 解析失败：{url}") from exc

    def _curl_json(self, url: str, params: dict[str, Any], *, safe: str = ",") -> dict[str, Any]:
        query = urllib.parse.urlencode(params, safe=safe)
        full_url = f"{url}?{query}"
        try:
            result = subprocess.run(
                ["curl", "-sS", "--max-time", str(max(5, int(self.timeout))), full_url],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise TushareError("系统缺少 curl，跳过 Eastmoney K 线接口。") from exc
        if self.pause:
            time.sleep(self.pause)
        body = result.stdout.strip()
        if not body:
            error = result.stderr.strip() or f"exit={result.returncode}"
            raise TushareError(f"Eastmoney 返回空响应：{url} {error}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise TushareError(f"Eastmoney JSON 解析失败：{url}") from exc


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


def _date_param(value: Any, default: str) -> str:
    text = str(value or "").strip().replace("-", "")
    return text if text else default


def _date8(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:10].replace("-", "")


def _date_dash(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


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
    return number / 100 if abs(number) > 10000 else number


def _wan(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number / 10000, 4)
