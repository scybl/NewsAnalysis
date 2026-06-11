from __future__ import annotations

from statistics import mean
from typing import Any

from .utils import limit_records, pick, sorted_records


DATE_FIELDS = ("trade_date", "ann_date", "end_date", "f_ann_date", "in_date")


def build_dossier(full_data: dict[str, Any]) -> dict[str, Any]:
    datasets = full_data.get("datasets", {})
    daily = sorted_records(datasets.get("daily", []), ("trade_date",))
    daily_basic = sorted_records(datasets.get("daily_basic", []), ("trade_date",))
    income = sorted_records(datasets.get("income", []), ("end_date", "ann_date"))
    indicators = sorted_records(datasets.get("fina_indicator", []), ("end_date", "ann_date"))
    industry = datasets.get("index_member_all", [])
    announcements = _filter_announcements(sorted_records(datasets.get("anns_d", []), ("ann_date",)))

    compact = {
        "ts_code": full_data["ts_code"],
        "date_range": full_data.get("date_range"),
        "company": {
            "stock_basic": _first(datasets.get("stock_basic", [])),
            "stock_company": _first(datasets.get("stock_company", [])),
            "name_changes": limit_records(sorted_records(datasets.get("namechange", []), DATE_FIELDS), 20),
            "managers": limit_records(sorted_records(datasets.get("stk_managers", []), DATE_FIELDS), 20, ["ann_date", "name", "gender", "lev", "title", "edu", "begin_date", "end_date"]),
            "rewards": limit_records(sorted_records(datasets.get("stk_rewards", []), DATE_FIELDS), 20, ["ann_date", "end_date", "name", "title", "reward", "hold_vol"]),
        },
        "market": {
            "technical_snapshot": _technical_snapshot(daily),
            "valuation_snapshot": _first(daily_basic),
            "daily_recent": limit_records(daily, 80, ["trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]),
            "daily_basic_recent": limit_records(daily_basic, 80, ["trade_date", "close", "turnover_rate", "volume_ratio", "pe", "pe_ttm", "pb", "ps_ttm", "dv_ttm", "total_mv", "circ_mv"]),
            "weekly_recent": limit_records(sorted_records(datasets.get("weekly", []), ("trade_date",)), 52, ["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"]),
            "monthly_recent": limit_records(sorted_records(datasets.get("monthly", []), ("trade_date",)), 36, ["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"]),
            "moneyflow_recent": limit_records(sorted_records(datasets.get("moneyflow", []), ("trade_date",)), 60, ["trade_date", "buy_sm_amount", "sell_sm_amount", "buy_md_amount", "sell_md_amount", "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount", "net_mf_amount"]),
            "margin_recent": limit_records(sorted_records(datasets.get("margin_detail", []), ("trade_date",)), 60, ["trade_date", "rzye", "rqye", "rzmre", "rqmcl", "rzche", "rqchl", "rzrqye"]),
            "limit_recent": limit_records(sorted_records(datasets.get("stk_limit", []), ("trade_date",)), 40, ["trade_date", "up_limit", "down_limit"]),
            "suspend_recent": limit_records(sorted_records(datasets.get("suspend_d", []), DATE_FIELDS), 40),
        },
        "financials": {
            "income_recent": limit_records(income, 24, _income_fields()),
            "balance_recent": limit_records(sorted_records(datasets.get("balancesheet", []), ("end_date", "ann_date")), 24, _balance_fields()),
            "cashflow_recent": limit_records(sorted_records(datasets.get("cashflow", []), ("end_date", "ann_date")), 24, _cashflow_fields()),
            "indicator_recent": limit_records(indicators, 24, _indicator_fields()),
            "financial_trends": _financial_trends(income, indicators),
            "express_recent": limit_records(sorted_records(datasets.get("express", []), DATE_FIELDS), 20),
            "forecast_recent": limit_records(sorted_records(datasets.get("forecast", []), DATE_FIELDS), 20),
            "main_business": limit_records(sorted_records(datasets.get("fina_mainbz", []), ("end_date",)), 24, ["end_date", "bz_item", "bz_sales", "bz_profit", "bz_cost", "curr_type", "update_flag"]),
            "dividend": limit_records(sorted_records(datasets.get("dividend", []), DATE_FIELDS), 24, ["ann_date", "end_date", "stk_div", "cash_div", "record_date", "ex_date", "div_proc"]),
            "audit": limit_records(sorted_records(datasets.get("fina_audit", []), DATE_FIELDS), 20),
            "disclosure_date": limit_records(sorted_records(datasets.get("disclosure_date", []), DATE_FIELDS), 20),
        },
        "shareholders_and_events": {
            "top10_holders": limit_records(sorted_records(datasets.get("top10_holders", []), ("end_date", "ann_date")), 30, ["ann_date", "end_date", "holder_name", "hold_amount", "hold_ratio", "hold_float_ratio", "hold_change"]),
            "top10_floatholders": limit_records(sorted_records(datasets.get("top10_floatholders", []), ("end_date", "ann_date")), 30, ["ann_date", "end_date", "holder_name", "hold_amount", "hold_ratio", "hold_float_ratio", "hold_change"]),
            "holder_number": limit_records(sorted_records(datasets.get("stk_holdernumber", []), ("end_date", "ann_date")), 30, ["ann_date", "end_date", "holder_num"]),
            "holder_trade": limit_records(sorted_records(datasets.get("stk_holdertrade", []), DATE_FIELDS), 40, ["ann_date", "holder_name", "holder_type", "in_de", "change_vol", "change_ratio", "after_share", "after_ratio"]),
            "pledge_stat": limit_records(sorted_records(datasets.get("pledge_stat", []), DATE_FIELDS), 20, ["end_date", "pledge_count", "unrest_pledge", "rest_pledge", "total_share", "pledge_ratio"]),
            "pledge_detail": limit_records(sorted_records(datasets.get("pledge_detail", []), DATE_FIELDS), 40, ["ann_date", "holder_name", "pledge_amount", "start_date", "end_date", "is_release", "release_date"]),
            "repurchase": limit_records(sorted_records(datasets.get("repurchase", []), DATE_FIELDS), 30, ["ann_date", "end_date", "proc", "vol", "amount", "high_limit", "low_limit"]),
            "share_float": limit_records(sorted_records(datasets.get("share_float", []), DATE_FIELDS), 30, ["ann_date", "float_date", "float_share", "float_ratio", "holder_name", "share_type"]),
            "block_trade": limit_records(sorted_records(datasets.get("block_trade", []), DATE_FIELDS), 40, ["trade_date", "price", "vol", "amount", "buyer", "seller"]),
        },
        "industry": {
            "sw_classification": industry,
            "industry_daily_snapshot": _technical_snapshot(sorted_records(datasets.get("sw_daily", []), ("trade_date",))),
            "industry_daily_recent": limit_records(sorted_records(datasets.get("sw_daily", []), ("trade_date",)), 80, ["trade_date", "name", "open", "high", "low", "close", "change", "pct_change", "vol", "amount", "pe", "pb"]),
        },
        "announcements": announcements,
        "data_quality": {
            "dataset_rows": {name: len(rows) for name, rows in datasets.items()},
            "fetch_errors": full_data.get("fetch_errors", []),
        },
    }
    compact["news_context"] = _build_news_context(compact)
    return compact


def _first(records: list[dict[str, Any]]) -> dict[str, Any]:
    return records[0] if records else {}


def _technical_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    closes = [_to_float(row.get("close")) for row in rows if _to_float(row.get("close")) is not None]
    latest = rows[0]
    snapshot = {
        "latest": pick(latest, ["trade_date", "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]),
        "return_pct": {},
        "moving_average": {},
        "volume_avg": {},
        "max_drawdown_pct_recent": None,
    }
    for window in (5, 20, 60, 120, 250):
        if len(closes) > window and closes[window] not in (None, 0):
            snapshot["return_pct"][f"{window}d"] = round((closes[0] / closes[window] - 1) * 100, 2)
        if len(closes) >= window:
            snapshot["moving_average"][f"ma{window}"] = round(mean(closes[:window]), 4)

    vols = [_to_float(row.get("vol")) for row in rows if _to_float(row.get("vol")) is not None]
    for window in (5, 20, 60):
        if len(vols) >= window:
            snapshot["volume_avg"][f"{window}d"] = round(mean(vols[:window]), 2)

    recent = closes[:250]
    if recent:
        peak = recent[-1]
        max_drawdown = 0.0
        for price in reversed(recent):
            peak = max(peak, price)
            if peak:
                max_drawdown = min(max_drawdown, price / peak - 1)
        snapshot["max_drawdown_pct_recent"] = round(max_drawdown * 100, 2)
    return snapshot


def _financial_trends(income: list[dict[str, Any]], indicators: list[dict[str, Any]]) -> dict[str, Any]:
    latest_income = _first(income)
    latest_indicator = _first(indicators)
    return {
        "latest_income": pick(latest_income, ["ann_date", "end_date", "revenue", "total_revenue", "n_income", "n_income_attr_p", "operate_profit", "basic_eps", "diluted_eps"]),
        "latest_indicator": pick(latest_indicator, ["ann_date", "end_date", "eps", "dt_eps", "roe", "roe_dt", "roa", "grossprofit_margin", "netprofit_margin", "debt_to_assets", "current_ratio", "quick_ratio", "or_yoy", "netprofit_yoy"]),
        "revenue_yoy_series": _series(income, "revenue"),
        "net_profit_yoy_series": _series(income, "n_income_attr_p"),
        "roe_series": _series(indicators, "roe"),
        "gross_margin_series": _series(indicators, "grossprofit_margin"),
    }


def _series(rows: list[dict[str, Any]], field: str, limit: int = 12) -> list[dict[str, Any]]:
    result = []
    for row in rows[:limit]:
        result.append({"end_date": row.get("end_date"), field: row.get(field)})
    return result


def _filter_announcements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keywords = ("年度报告", "年报", "半年度报告", "半年报", "季度报告", "季报", "业绩说明", "审计", "分红", "回购", "重大")
    matched = [row for row in rows if any(word in str(row.get("title", "")) for word in keywords)]
    return limit_records(matched or rows, 60, ["ann_date", "ts_code", "name", "title", "url"])


def _build_news_context(dossier: dict[str, Any]) -> dict[str, Any]:
    try:
        from .config import get_news_db_config
        from .news.context import build_news_context

        return build_news_context(get_news_db_config(), dossier)
    except Exception as exc:
        return {
            "company_news": [],
            "industry_news": [],
            "macro_news": [],
            "fetch_error": str(exc),
        }


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _income_fields() -> list[str]:
    return ["ann_date", "f_ann_date", "end_date", "report_type", "basic_eps", "total_revenue", "revenue", "operate_profit", "total_profit", "n_income", "n_income_attr_p", "ebit", "ebitda"]


def _balance_fields() -> list[str]:
    return ["ann_date", "f_ann_date", "end_date", "report_type", "total_assets", "total_liab", "total_hldr_eqy_exc_min_int", "money_cap", "accounts_receiv", "inventories", "total_cur_assets", "total_cur_liab", "total_share"]


def _cashflow_fields() -> list[str]:
    return ["ann_date", "f_ann_date", "end_date", "report_type", "net_profit", "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "free_cashflow", "c_cash_equ_end_period"]


def _indicator_fields() -> list[str]:
    return ["ann_date", "end_date", "eps", "dt_eps", "roe", "roe_dt", "roa", "grossprofit_margin", "netprofit_margin", "debt_to_assets", "current_ratio", "quick_ratio", "or_yoy", "netprofit_yoy", "ocfps", "fcff", "fcfe"]
