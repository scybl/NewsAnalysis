from __future__ import annotations

from statistics import mean
from typing import Any


VALUE_SPECULATION_QUESTION = """请基于这份“价值投机资料包”，输出一份可执行的价值投机分析。

必须使用以下结构：
1. 总结论：给出 观察 / 等待 / 小仓试错 / 回避 之一，并说明一句核心理由
2. 评分表：价值基础、估值吸引力、业绩趋势、行业周期、催化强度、资金确认、技术时机、风险压力，每项 0-5 分
3. 价值基础：公司质地、盈利能力、现金流、负债和分红
4. 投机触发：行业、财报、公告、资金面、技术面可能触发点
5. 赔率分析：上行/中性/下行情景，每个情景写触发条件和观察信号
6. 交易计划：观察条件、试仓条件、加仓条件、减仓条件、退出条件
7. 数据缺口：哪些关键数据缺失会影响判断

要求：
- 不要编造资料包中没有的数据。
- 不能直接给买入/卖出指令，只能给研究框架和条件。
- 价格判断必须围绕条件和风险，不承诺收益。
"""


def build_value_speculation_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    market = dossier.get("market", {})
    financials = dossier.get("financials", {})
    industry = dossier.get("industry", {})
    events = dossier.get("shareholders_and_events", {})

    technical = _technical_signals(market.get("technical_snapshot", {}), market.get("daily_basic_recent", []))
    valuation = _valuation_signals(market.get("valuation_snapshot", {}), market.get("daily_basic_recent", []))
    earnings = _earnings_signals(financials)
    capital = _capital_flow_signals(market.get("moneyflow_recent", []), market.get("margin_recent", []), events)
    industry_signals = _industry_signals(industry)
    catalysts = _catalyst_signals(financials, dossier.get("announcements", []), events)
    risks = _risk_flags(dossier, valuation, earnings, capital, technical)
    scores = _scores(valuation, earnings, capital, technical, industry_signals, catalysts, risks)

    return {
        "ts_code": dossier.get("ts_code"),
        "company": dossier.get("company", {}),
        "framework": "value_speculation",
        "decision_helper": {
            "rating_hint": _rating_hint(scores),
            "score_summary": scores,
            "core_view": _core_view(scores, valuation, earnings, capital, technical),
        },
        "value_basis": {
            "valuation": valuation,
            "earnings_quality": earnings,
            "dividend": financials.get("dividend", [])[:8],
            "audit": financials.get("audit", [])[:8],
            "main_business": financials.get("main_business", [])[:16],
        },
        "speculation_triggers": {
            "catalysts": catalysts,
            "capital_flow": capital,
            "technical_timing": technical,
            "announcements": dossier.get("announcements", [])[:30],
        },
        "industry_cycle": industry_signals,
        "shareholder_structure": {
            "top10_holders": events.get("top10_holders", [])[:20],
            "top10_floatholders": events.get("top10_floatholders", [])[:20],
            "holder_number": events.get("holder_number", [])[:12],
            "pledge_stat": events.get("pledge_stat", [])[:12],
            "block_trade": events.get("block_trade", [])[:20],
        },
        "risk_flags": risks,
        "scenario_template": _scenario_template(scores),
        "data_quality": dossier.get("data_quality", {}),
    }


def _valuation_signals(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    latest = snapshot or (history[0] if history else {})
    pe_ttm = _num(latest.get("pe_ttm") or latest.get("pe"))
    pb = _num(latest.get("pb"))
    ps_ttm = _num(latest.get("ps_ttm"))
    dividend_yield = _num(latest.get("dv_ttm"))
    total_mv = _num(latest.get("total_mv"))

    pe_series = [_num(row.get("pe_ttm") or row.get("pe")) for row in history]
    pb_series = [_num(row.get("pb")) for row in history]
    pe_series = [value for value in pe_series if value and value > 0]
    pb_series = [value for value in pb_series if value and value > 0]

    return {
        "latest": {
            "trade_date": latest.get("trade_date"),
            "close": latest.get("close"),
            "pe_ttm": pe_ttm,
            "pb": pb,
            "ps_ttm": ps_ttm,
            "dividend_yield_ttm": dividend_yield,
            "total_mv": total_mv,
            "circ_mv": latest.get("circ_mv"),
        },
        "relative_position": {
            "pe_vs_recent_avg": _ratio_vs_avg(pe_ttm, pe_series),
            "pb_vs_recent_avg": _ratio_vs_avg(pb, pb_series),
        },
        "signals": [
            *_flag(pe_ttm is not None and pe_ttm > 0 and pe_ttm <= 12, "PE_TTM 处于低估区间"),
            *_flag(pb is not None and pb <= 1, "PB 低于 1，存在破净或低账面估值特征"),
            *_flag(dividend_yield is not None and dividend_yield >= 3, "股息率具备防御性吸引力"),
            *_flag(pe_ttm is not None and pe_ttm > 60, "PE_TTM 偏高，静态估值安全边际不足"),
        ],
    }


def _earnings_signals(financials: dict[str, Any]) -> dict[str, Any]:
    trend = financials.get("financial_trends", {})
    latest_income = trend.get("latest_income", {})
    latest_indicator = trend.get("latest_indicator", {})
    income_recent = financials.get("income_recent", [])
    cashflow_recent = financials.get("cashflow_recent", [])
    indicator_recent = financials.get("indicator_recent", [])

    revenue_yoy = _num(latest_indicator.get("or_yoy"))
    netprofit_yoy = _num(latest_indicator.get("netprofit_yoy"))
    roe = _num(latest_indicator.get("roe") or latest_indicator.get("roe_dt"))
    gross_margin = _num(latest_indicator.get("grossprofit_margin"))
    debt_to_assets = _num(latest_indicator.get("debt_to_assets"))

    latest_cash = cashflow_recent[0] if cashflow_recent else {}
    operating_cashflow = _num(latest_cash.get("n_cashflow_act"))
    net_profit = _num(latest_cash.get("net_profit") or latest_income.get("n_income_attr_p") or latest_income.get("n_income"))

    return {
        "latest_income": latest_income,
        "latest_indicator": latest_indicator,
        "recent_income": income_recent[:8],
        "recent_cashflow": cashflow_recent[:8],
        "recent_indicators": indicator_recent[:8],
        "derived": {
            "revenue_yoy": revenue_yoy,
            "netprofit_yoy": netprofit_yoy,
            "roe": roe,
            "gross_margin": gross_margin,
            "debt_to_assets": debt_to_assets,
            "operating_cashflow_to_profit": _safe_div(operating_cashflow, net_profit),
        },
        "signals": [
            *_flag(revenue_yoy is not None and revenue_yoy > 0, "营收同比为正，基本面存在改善迹象"),
            *_flag(netprofit_yoy is not None and netprofit_yoy > 0, "净利润同比为正，盈利趋势偏积极"),
            *_flag(roe is not None and roe >= 10, "ROE 较高，资产盈利能力较好"),
            *_flag(operating_cashflow is not None and net_profit is not None and operating_cashflow >= net_profit, "经营现金流覆盖利润，盈利质量较好"),
            *_flag(debt_to_assets is not None and debt_to_assets >= 75, "资产负债率较高，需要关注偿债和行业属性"),
            *_flag(revenue_yoy is not None and revenue_yoy < -5, "营收明显下滑，价值陷阱风险上升"),
            *_flag(netprofit_yoy is not None and netprofit_yoy < -10, "净利润明显下滑，业绩趋势承压"),
        ],
    }


def _capital_flow_signals(
    moneyflow: list[dict[str, Any]],
    margin: list[dict[str, Any]],
    events: dict[str, Any],
) -> dict[str, Any]:
    recent_money = moneyflow[:20]
    net_values = [_money_net(row) for row in recent_money]
    net_values = [value for value in net_values if value is not None]
    five_day_net = round(sum(net_values[:5]), 2) if net_values else None
    twenty_day_net = round(sum(net_values[:20]), 2) if net_values else None

    latest_margin = margin[0] if margin else {}
    earlier_margin = margin[min(len(margin) - 1, 20)] if margin else {}
    margin_balance_change = _num(latest_margin.get("rzrqye")) - _num(earlier_margin.get("rzrqye")) if _num(latest_margin.get("rzrqye")) is not None and _num(earlier_margin.get("rzrqye")) is not None else None

    holder_numbers = events.get("holder_number", [])
    holder_change = None
    if len(holder_numbers) >= 2:
        holder_change = _safe_div(_num(holder_numbers[0].get("holder_num")) - _num(holder_numbers[1].get("holder_num")), _num(holder_numbers[1].get("holder_num")))

    return {
        "moneyflow_recent": recent_money[:12],
        "margin_recent": margin[:12],
        "derived": {
            "five_day_net_mf_amount": five_day_net,
            "twenty_day_net_mf_amount": twenty_day_net,
            "margin_balance_change_approx": margin_balance_change,
            "holder_number_change_latest": holder_change,
        },
        "signals": [
            *_flag(five_day_net is not None and five_day_net > 0, "近 5 日资金净流入，短线资金认可度改善"),
            *_flag(twenty_day_net is not None and twenty_day_net > 0, "近 20 日资金净流入，资金趋势偏积极"),
            *_flag(five_day_net is not None and five_day_net < 0, "近 5 日资金净流出，短线承压"),
            *_flag(margin_balance_change is not None and margin_balance_change > 0, "融资融券余额上升，杠杆资金参与度提高"),
            *_flag(holder_change is not None and holder_change < 0, "股东户数下降，筹码可能趋于集中"),
            *_flag(holder_change is not None and holder_change > 0.05, "股东户数明显增加，筹码可能分散"),
        ],
    }


def _technical_signals(snapshot: dict[str, Any], valuation_history: list[dict[str, Any]]) -> dict[str, Any]:
    latest = snapshot.get("latest", {})
    close = _num(latest.get("close"))
    moving = snapshot.get("moving_average", {})
    returns = snapshot.get("return_pct", {})
    ma20 = _num(moving.get("ma20"))
    ma60 = _num(moving.get("ma60"))
    ma120 = _num(moving.get("ma120"))
    ma250 = _num(moving.get("ma250"))
    turnover_values = [_num(row.get("turnover_rate")) for row in valuation_history[:20]]
    turnover_values = [value for value in turnover_values if value is not None]

    return {
        "latest": latest,
        "returns": returns,
        "moving_average": moving,
        "volume_avg": snapshot.get("volume_avg", {}),
        "max_drawdown_pct_recent": snapshot.get("max_drawdown_pct_recent"),
        "derived": {
            "above_ma20": close is not None and ma20 is not None and close >= ma20,
            "above_ma60": close is not None and ma60 is not None and close >= ma60,
            "above_ma120": close is not None and ma120 is not None and close >= ma120,
            "above_ma250": close is not None and ma250 is not None and close >= ma250,
            "avg_turnover_20d": round(mean(turnover_values), 3) if turnover_values else None,
        },
        "signals": [
            *_flag(close is not None and ma20 is not None and close >= ma20, "股价站上 MA20，短线趋势改善"),
            *_flag(close is not None and ma60 is not None and close >= ma60, "股价站上 MA60，中期趋势改善"),
            *_flag(close is not None and ma20 is not None and close < ma20, "股价低于 MA20，短线仍弱"),
            *_flag(_num(returns.get("20d")) is not None and _num(returns.get("20d")) > 5, "近 20 日涨幅较强，市场关注度提升"),
            *_flag(_num(returns.get("20d")) is not None and _num(returns.get("20d")) < -8, "近 20 日跌幅较大，需防止趋势下行"),
        ],
    }


def _industry_signals(industry: dict[str, Any]) -> dict[str, Any]:
    snapshot = industry.get("industry_daily_snapshot", {})
    latest = snapshot.get("latest", {})
    returns = snapshot.get("return_pct", {})
    return {
        "classification": industry.get("sw_classification", []),
        "latest": latest,
        "returns": returns,
        "recent": industry.get("industry_daily_recent", [])[:40],
        "signals": [
            *_flag(_num(returns.get("20d")) is not None and _num(returns.get("20d")) > 3, "行业指数近 20 日走强，行业 beta 有利"),
            *_flag(_num(returns.get("60d")) is not None and _num(returns.get("60d")) > 5, "行业指数近 60 日趋势偏强"),
            *_flag(_num(returns.get("20d")) is not None and _num(returns.get("20d")) < -5, "行业指数近 20 日走弱，行业 beta 不利"),
        ],
    }


def _catalyst_signals(
    financials: dict[str, Any],
    announcements: list[dict[str, Any]],
    events: dict[str, Any],
) -> dict[str, Any]:
    express = financials.get("express_recent", [])
    forecast = financials.get("forecast_recent", [])
    repurchase = events.get("repurchase", [])
    dividend = financials.get("dividend", [])
    recent_titles = [str(row.get("title") or "") for row in announcements[:20]]
    keywords = ("回购", "分红", "业绩预告", "业绩快报", "重组", "增持", "订单", "中标", "重大合同")

    return {
        "express_recent": express[:8],
        "forecast_recent": forecast[:8],
        "repurchase": repurchase[:8],
        "dividend": dividend[:8],
        "announcement_keywords": [title for title in recent_titles if any(word in title for word in keywords)],
        "signals": [
            *_flag(bool(express), "存在业绩快报，可用于验证业绩拐点"),
            *_flag(bool(forecast), "存在业绩预告，可作为财报前催化"),
            *_flag(bool(repurchase), "存在回购记录，可能形成估值支撑"),
            *_flag(any("分红" in title for title in recent_titles) or bool(dividend), "存在分红信息，适合评估股东回报"),
            *_flag(any("重大" in title or "重组" in title for title in recent_titles), "公告中存在重大事项，需要单独核查"),
        ],
    }


def _risk_flags(
    dossier: dict[str, Any],
    valuation: dict[str, Any],
    earnings: dict[str, Any],
    capital: dict[str, Any],
    technical: dict[str, Any],
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    derived = earnings.get("derived", {})
    latest_val = valuation.get("latest", {})
    capital_derived = capital.get("derived", {})
    technical_derived = technical.get("derived", {})

    _append(flags, _num(derived.get("revenue_yoy")) is not None and _num(derived.get("revenue_yoy")) < -5, "high", "营收下滑", "营收同比明显下滑，需警惕价值陷阱。")
    _append(flags, _num(derived.get("netprofit_yoy")) is not None and _num(derived.get("netprofit_yoy")) < -10, "high", "利润下滑", "净利润同比明显下滑，安全边际可能被侵蚀。")
    _append(flags, _num(derived.get("operating_cashflow_to_profit")) is not None and _num(derived.get("operating_cashflow_to_profit")) < 0.6, "medium", "现金流偏弱", "经营现金流对利润覆盖不足。")
    _append(flags, _num(latest_val.get("pe_ttm")) is not None and _num(latest_val.get("pe_ttm")) > 60, "medium", "估值偏高", "当前 PE_TTM 偏高，对业绩兑现要求较高。")
    _append(flags, _num(capital_derived.get("twenty_day_net_mf_amount")) is not None and _num(capital_derived.get("twenty_day_net_mf_amount")) < 0, "medium", "资金流出", "近 20 日资金净流出，短线筹码压力较大。")
    _append(flags, not technical_derived.get("above_ma60"), "medium", "趋势未确认", "股价未站上 MA60，中期趋势尚未确认。")

    fetch_errors = dossier.get("data_quality", {}).get("fetch_errors", [])
    _append(flags, bool(fetch_errors), "low", "数据缺口", f"有 {len(fetch_errors)} 个接口未成功，部分判断需要人工复核。")
    return flags


def _scores(
    valuation: dict[str, Any],
    earnings: dict[str, Any],
    capital: dict[str, Any],
    technical: dict[str, Any],
    industry: dict[str, Any],
    catalysts: dict[str, Any],
    risks: list[dict[str, str]],
) -> dict[str, int]:
    val = valuation.get("latest", {})
    ern = earnings.get("derived", {})
    cap = capital.get("derived", {})
    tech = technical.get("derived", {})
    industry_returns = industry.get("returns", {})

    value_basis = 2
    value_basis += _point(_num(ern.get("roe")) is not None and _num(ern.get("roe")) >= 8)
    value_basis += _point(_num(ern.get("operating_cashflow_to_profit")) is not None and _num(ern.get("operating_cashflow_to_profit")) >= 0.8)
    value_basis += _point(_num(ern.get("netprofit_yoy")) is not None and _num(ern.get("netprofit_yoy")) >= 0)

    valuation_score = 2
    valuation_score += _point(_num(val.get("pe_ttm")) is not None and 0 < _num(val.get("pe_ttm")) <= 15)
    valuation_score += _point(_num(val.get("pb")) is not None and _num(val.get("pb")) <= 1.5)
    valuation_score += _point(_num(val.get("dividend_yield_ttm")) is not None and _num(val.get("dividend_yield_ttm")) >= 3)

    earnings_score = 2
    earnings_score += _point(_num(ern.get("revenue_yoy")) is not None and _num(ern.get("revenue_yoy")) > 0)
    earnings_score += _point(_num(ern.get("netprofit_yoy")) is not None and _num(ern.get("netprofit_yoy")) > 0)
    earnings_score -= _point(_num(ern.get("revenue_yoy")) is not None and _num(ern.get("revenue_yoy")) < -5)

    industry_score = 2
    industry_score += _point(_num(industry_returns.get("20d")) is not None and _num(industry_returns.get("20d")) > 3)
    industry_score += _point(_num(industry_returns.get("60d")) is not None and _num(industry_returns.get("60d")) > 5)

    catalyst_score = min(5, 1 + len(catalysts.get("signals", [])))

    capital_score = 2
    capital_score += _point(_num(cap.get("five_day_net_mf_amount")) is not None and _num(cap.get("five_day_net_mf_amount")) > 0)
    capital_score += _point(_num(cap.get("twenty_day_net_mf_amount")) is not None and _num(cap.get("twenty_day_net_mf_amount")) > 0)
    capital_score += _point(_num(cap.get("holder_number_change_latest")) is not None and _num(cap.get("holder_number_change_latest")) < 0)

    technical_score = 1
    technical_score += _point(bool(tech.get("above_ma20")))
    technical_score += _point(bool(tech.get("above_ma60")))
    technical_score += _point(bool(tech.get("above_ma120")))
    technical_score += _point(bool(tech.get("above_ma250")))

    risk_pressure = min(5, sum(2 if flag["level"] == "high" else 1 for flag in risks))

    return {
        "value_basis": _clamp(value_basis),
        "valuation_attractiveness": _clamp(valuation_score),
        "earnings_trend": _clamp(earnings_score),
        "industry_cycle": _clamp(industry_score),
        "catalyst_strength": _clamp(catalyst_score),
        "capital_confirmation": _clamp(capital_score),
        "technical_timing": _clamp(technical_score),
        "risk_pressure": _clamp(risk_pressure),
    }


def _rating_hint(scores: dict[str, int]) -> str:
    positive = (
        scores["value_basis"]
        + scores["valuation_attractiveness"]
        + scores["earnings_trend"]
        + scores["industry_cycle"]
        + scores["catalyst_strength"]
        + scores["capital_confirmation"]
        + scores["technical_timing"]
    )
    risk = scores["risk_pressure"]
    if risk >= 4 or positive <= 15:
        return "回避"
    if positive >= 25 and risk <= 2:
        return "小仓试错"
    if positive >= 20:
        return "观察"
    return "等待"


def _core_view(scores: dict[str, int], valuation: dict[str, Any], earnings: dict[str, Any], capital: dict[str, Any], technical: dict[str, Any]) -> str:
    parts = [
        f"评级提示：{_rating_hint(scores)}",
        f"估值吸引力 {scores['valuation_attractiveness']}/5",
        f"业绩趋势 {scores['earnings_trend']}/5",
        f"资金确认 {scores['capital_confirmation']}/5",
        f"技术时机 {scores['technical_timing']}/5",
        f"风险压力 {scores['risk_pressure']}/5",
    ]
    return "；".join(parts)


def _scenario_template(scores: dict[str, int]) -> dict[str, Any]:
    return {
        "upside": {
            "premise": "价值基础不恶化，资金和技术信号继续确认，催化事件兑现。",
            "watch": ["营收/净利润同比改善", "资金净流入持续", "股价站稳中期均线", "行业指数走强"],
        },
        "base": {
            "premise": "估值有支撑，但业绩和资金缺乏强催化，股价以震荡消化为主。",
            "watch": ["估值维持低位", "成交量没有放大", "财报没有明显超预期"],
        },
        "downside": {
            "premise": "业绩继续恶化或资金持续流出，低估值演变成价值陷阱。",
            "watch": ["营收/利润继续下滑", "跌破关键均线", "股东户数上升", "公告出现负面事项"],
        },
        "rating_hint": _rating_hint(scores),
    }


def _money_net(row: dict[str, Any]) -> float | None:
    explicit = _num(row.get("net_mf_amount"))
    if explicit is not None:
        return explicit
    buy = sum(_num(row.get(key)) or 0 for key in ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"))
    sell = sum(_num(row.get(key)) or 0 for key in ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount"))
    return buy - sell


def _ratio_vs_avg(value: float | None, series: list[float]) -> float | None:
    if value is None or not series:
        return None
    avg = mean(series)
    if avg == 0:
        return None
    return round(value / avg, 3)


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return round(a / b, 4)


def _num(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag(condition: bool, message: str) -> list[str]:
    return [message] if condition else []


def _append(flags: list[dict[str, str]], condition: bool, level: str, title: str, message: str) -> None:
    if condition:
        flags.append({"level": level, "title": title, "message": message})


def _point(condition: bool) -> int:
    return 1 if condition else 0


def _clamp(value: int) -> int:
    return max(0, min(5, value))
