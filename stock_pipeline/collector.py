from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tushare_client import TushareClient, TushareError
from .utils import ensure_dir, normalize_ts_code, today_yyyymmdd, write_json, years_ago_yyyymmdd


@dataclass(frozen=True)
class EndpointSpec:
    api_name: str
    params: dict[str, Any]
    fields: str = ""
    client_filter_ts_code: bool = False


def _date_params(ts_code: str, start_date: str, end_date: str) -> dict[str, Any]:
    return {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}


class StockDataCollector:
    def __init__(self, client: TushareClient):
        self.client = client

    def collect(
        self,
        code: str,
        output_dir: Path,
        years: int | None = None,
        full_history: bool = False,
    ) -> dict[str, Any]:
        ts_code = normalize_ts_code(code)
        end_date = today_yyyymmdd()
        use_full_history = full_history or years is None
        start_date = "19900101" if use_full_history else years_ago_yyyymmdd(years)
        raw_dir = ensure_dir(output_dir / "raw")

        specs = self._build_specs(ts_code, start_date, end_date)
        raw: dict[str, list[dict[str, Any]]] = {}
        errors: list[dict[str, str]] = []

        for spec in specs:
            try:
                result = self.client.query(spec.api_name, spec.params, spec.fields)
                records = result.records
                if spec.client_filter_ts_code:
                    records = [row for row in records if row.get("ts_code") == ts_code]
                raw[spec.api_name] = records
                write_json(raw_dir / f"{spec.api_name}.json", {"fields": result.fields, "records": records})
            except TushareError as exc:
                errors.append({"api_name": spec.api_name, "error": str(exc)})

        industry_rows = raw.get("index_member_all", [])
        industry_daily = self._collect_industry_daily(industry_rows, start_date, end_date, raw_dir, errors)
        if industry_daily:
            raw["sw_daily"] = industry_daily

        dossier = {
            "ts_code": ts_code,
            "date_range": {"start_date": start_date, "end_date": end_date, "full_history": use_full_history},
            "source": getattr(self.client, "source_name", "Tushare Pro"),
            "datasets": raw,
            "fetch_errors": errors,
        }
        write_json(output_dir / "full_data.json", dossier)
        return dossier

    def _build_specs(self, ts_code: str, start_date: str, end_date: str) -> list[EndpointSpec]:
        dated = lambda api: EndpointSpec(api, _date_params(ts_code, start_date, end_date))
        return [
            EndpointSpec("stock_basic", {"ts_code": ts_code}, "ts_code,symbol,name,area,industry,market,list_date,fullname,enname,exchange,act_name,act_ent_type"),
            EndpointSpec("namechange", {"ts_code": ts_code}),
            EndpointSpec("stock_company", {"ts_code": ts_code}, "ts_code,com_name,com_id,exchange,chairman,manager,secretary,reg_capital,setup_date,province,city,introduction,website,email,office,employees,main_business,business_scope"),
            EndpointSpec("stk_managers", {"ts_code": ts_code}),
            EndpointSpec("stk_rewards", {"ts_code": ts_code}),
            dated("daily"),
            dated("weekly"),
            dated("monthly"),
            dated("daily_basic"),
            dated("adj_factor"),
            dated("stk_limit"),
            dated("suspend_d"),
            dated("moneyflow"),
            dated("margin_detail"),
            EndpointSpec("income", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("balancesheet", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("cashflow", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("fina_indicator", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("express", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("forecast", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("dividend", {"ts_code": ts_code}),
            EndpointSpec("fina_mainbz", {"ts_code": ts_code}),
            EndpointSpec("fina_audit", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("disclosure_date", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("top10_holders", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("top10_floatholders", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("stk_holdernumber", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("stk_holdertrade", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("pledge_stat", {"ts_code": ts_code}),
            EndpointSpec("pledge_detail", {"ts_code": ts_code}),
            EndpointSpec("repurchase", {"start_date": start_date, "end_date": end_date}, client_filter_ts_code=True),
            EndpointSpec("share_float", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("block_trade", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
            EndpointSpec("index_member_all", {"ts_code": ts_code, "is_new": "Y"}),
            EndpointSpec("anns_d", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
        ]

    def _collect_industry_daily(
        self,
        industry_rows: list[dict[str, Any]],
        start_date: str,
        end_date: str,
        raw_dir: Path,
        errors: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not industry_rows:
            return []
        industry_code = industry_rows[0].get("l3_code") or industry_rows[0].get("l2_code") or industry_rows[0].get("l1_code")
        if not industry_code:
            return []
        try:
            result = self.client.query("sw_daily", {"ts_code": industry_code, "start_date": start_date, "end_date": end_date})
            write_json(raw_dir / "sw_daily.json", {"fields": result.fields, "records": result.records})
            return result.records
        except TushareError as exc:
            errors.append({"api_name": "sw_daily", "error": str(exc)})
            return []
