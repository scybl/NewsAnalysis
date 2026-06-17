from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Callable

from .value_speculation import VALUE_SPECULATION_QUESTION, build_value_speculation_dossier


SYSTEM_DISCIPLINE = """通用输出纪律：
- 只能基于用户提供的 Tushare 结构化数据，不编造缺失数据。
- 所有判断都要尽量对应资料包中的证据。
- 必须说明关键数据缺口和它对判断的影响。
- 必须先区分“好公司、好价格、好时机”，不能用公司质地自动推导买入结论。
- 遇到高估值高成长标的，必须提示 PEG/Forward PE 可能掩盖兑现风险，单独说明估值幻觉。
- 必须设置前置闸门：能力圈、护城河/长期生存性、盈利收益率或估值安全边际，任一失败都要降级结论。
- 必须把仓位、触发条件、证伪条件和复核周期分开写，避免把研究观点写成确定性指令。
- 这不是投资建议，只能给研究观点、观察条件和情景推演。
"""


VALUE_SPECULATION_SYSTEM_PROMPT = f"""你是一个严谨的 A 股“价值投机”研究助手。

你的分析方法：
1. 先用价值框架判断公司是否有基本面底线和安全边际。
2. 再用行业周期、催化事件、资金面和技术趋势判断是否存在更好的交易窗口。
3. 你关注的是赔率和条件，不做确定性预测，也不直接给买入/卖出指令。

{SYSTEM_DISCIPLINE}
"""


VALUE_QUALITY_QUESTION = """请基于这份“质量成长价值投资资料包”，输出一份偏中长期的价值投资分析。

必须使用以下结构：
1. 总结论：给出 优质可跟踪 / 估值等待 / 质量存疑 / 回避 之一，并说明一句核心理由
2. 评分表：商业质量、盈利韧性、成长持续性、现金流质量、资产负债安全、治理与股东回报、估值安全边际、风险压力，每项 0-5 分
3. 公司质量：业务位置、主营构成、盈利能力和护城河线索
4. 成长与韧性：营收、利润、ROE、毛利率趋势
5. 财务安全：现金流、负债、应收、存货和审计/披露风险
6. 估值与买入前提：什么估值/业绩条件下才值得继续深入
7. 证伪信号：哪些财务或经营信号会推翻当前价值逻辑
8. 数据缺口：哪些关键数据缺失会影响判断
"""


VALUE_QUALITY_SYSTEM_PROMPT = f"""你是一个严谨的 A 股“质量成长价值投资”研究助手。

你的分析方法：
1. 重点评估公司是否具备可持续盈利能力、资本回报和长期复利基础。
2. 估值只作为安全边际，不因短期题材或资金流直接改变长期判断。
3. 必须区分“好公司”“好价格”“好时点”三件事。

{SYSTEM_DISCIPLINE}
"""


VALUE_DIVIDEND_QUESTION = """请基于这份“低估红利价值投资资料包”，输出一份偏防御和股东回报的价值投资分析。

必须使用以下结构：
1. 总结论：给出 红利底仓候选 / 等待价格 / 分红不稳 / 回避 之一，并说明一句核心理由
2. 评分表：估值便宜度、分红吸引力、盈利稳定性、现金流覆盖、资产负债安全、行业防御性、治理与回报、风险压力，每项 0-5 分
3. 低估证据：PE/PB/股息率/市值位置及其局限
4. 分红可持续性：利润、经营现金流、负债和历史分红线索
5. 防御属性：行业周期、业务稳定性、波动与回撤
6. 适合的观察方式：等待条件、复核条件、退出观察信号
7. 价值陷阱风险：低估是否来自业绩恶化、治理、流动性或行业衰退
8. 数据缺口：哪些关键数据缺失会影响判断
"""


VALUE_DIVIDEND_SYSTEM_PROMPT = f"""你是一个严谨的 A 股“低估红利价值投资”研究助手。

你的分析方法：
1. 先判断当前低估是否真实，再判断分红和现金流是否可持续。
2. 更重视安全边际、防御性和股东回报，不追逐短期题材。
3. 必须把“低估机会”和“价值陷阱”分开讨论。

{SYSTEM_DISCIPLINE}
"""


OVERSOLD_REBOUND_QUESTION = """请基于这份“超跌反弹资料包”，输出一份短线反弹研究分析。

必须使用以下结构：
1. 总结论：给出 反弹观察 / 试错窗口 / 弱势等待 / 回避 之一，并说明一句核心理由
2. 评分表：超跌幅度、技术修复、成交配合、资金回流、行业共振、催化支撑、基本面底线、风险压力，每项 0-5 分
3. 超跌证据：近 20/60/120 日跌幅、最大回撤、均线偏离
4. 反弹触发：放量、站回均线、资金净流入、行业修复、公告/财报催化
5. 基本面底线：为什么不是纯粹下跌接刀，哪些数据能提供底线
6. 情景推演：强反弹/弱反弹/继续下跌的触发条件
7. 交易纪律：观察条件、试错条件、失效条件、风控边界
8. 数据缺口：哪些关键数据缺失会影响判断
"""


OVERSOLD_REBOUND_SYSTEM_PROMPT = f"""你是一个严谨的 A 股“超跌反弹”研究助手。

你的分析方法：
1. 先判断是否真的超跌，再判断是否已经出现反弹确认信号。
2. 超跌不是买入理由，只有基本面底线、资金回流、技术修复共同出现时才形成可研究窗口。
3. 必须明确失效条件和风险边界。

{SYSTEM_DISCIPLINE}
"""


@dataclass(frozen=True)
class AnalysisFramework:
    key: str
    label: str
    description: str
    question: str
    system_prompt: str
    dossier_builder: Callable[[dict[str, Any]], dict[str, Any]]


def list_analysis_frameworks() -> list[dict[str, str]]:
    return [
        {"key": item.key, "label": item.label, "description": item.description}
        for item in ANALYSIS_FRAMEWORKS.values()
    ]


def get_analysis_framework(key: str | None) -> AnalysisFramework:
    normalized = key or "value_speculation"
    if normalized not in ANALYSIS_FRAMEWORKS:
        supported = "、".join(item.label for item in ANALYSIS_FRAMEWORKS.values())
        raise ValueError(f"不支持的分析类型：{normalized}。可选：{supported}")
    return ANALYSIS_FRAMEWORKS[normalized]


def build_analysis_dossier(framework_key: str, dossier: dict[str, Any]) -> dict[str, Any]:
    return get_analysis_framework(framework_key).dossier_builder(dossier)


def build_all_analysis_dossiers(dossier: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: framework.dossier_builder(dossier) for key, framework in ANALYSIS_FRAMEWORKS.items()}


def build_value_quality_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    financials = dossier.get("financials", {})
    market = dossier.get("market", {})
    events = dossier.get("shareholders_and_events", {})
    quality = _quality_signals(financials)
    valuation = _valuation_signals(market.get("valuation_snapshot", {}), market.get("daily_basic_recent", []))
    safety = _safety_signals(financials, events)
    risks = _quality_risks(dossier, quality, valuation, safety)
    scores = _quality_scores(quality, valuation, safety, risks)
    return {
        "ts_code": dossier.get("ts_code"),
        "company": dossier.get("company", {}),
        "framework": "value_quality",
        "decision_helper": {
            "rating_hint": _quality_rating(scores),
            "score_summary": scores,
            "core_view": _core_view(_quality_rating(scores), scores),
        },
        "business_quality": {
            "main_business": financials.get("main_business", [])[:24],
            "industry": dossier.get("industry", {}),
            "announcements": dossier.get("announcements", [])[:30],
        },
        "financial_quality": quality,
        "valuation": valuation,
        "balance_sheet_safety": safety,
        "shareholder_structure": {
            "top10_holders": events.get("top10_holders", [])[:20],
            "holder_number": events.get("holder_number", [])[:12],
            "pledge_stat": events.get("pledge_stat", [])[:12],
        },
        "risk_flags": risks,
        "data_quality": dossier.get("data_quality", {}),
    }


def build_value_dividend_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    financials = dossier.get("financials", {})
    market = dossier.get("market", {})
    events = dossier.get("shareholders_and_events", {})
    valuation = _valuation_signals(market.get("valuation_snapshot", {}), market.get("daily_basic_recent", []))
    quality = _quality_signals(financials)
    dividend = _dividend_signals(financials)
    safety = _safety_signals(financials, events)
    risks = _dividend_risks(dossier, quality, valuation, dividend, safety)
    scores = _dividend_scores(quality, valuation, dividend, safety, risks)
    return {
        "ts_code": dossier.get("ts_code"),
        "company": dossier.get("company", {}),
        "framework": "value_dividend",
        "decision_helper": {
            "rating_hint": _dividend_rating(scores),
            "score_summary": scores,
            "core_view": _core_view(_dividend_rating(scores), scores),
        },
        "valuation": valuation,
        "dividend_and_return": dividend,
        "profit_and_cashflow_stability": quality,
        "balance_sheet_safety": safety,
        "defensive_context": {
            "industry": dossier.get("industry", {}),
            "technical_snapshot": market.get("technical_snapshot", {}),
            "daily_basic_recent": market.get("daily_basic_recent", [])[:40],
        },
        "shareholder_structure": {
            "top10_holders": events.get("top10_holders", [])[:20],
            "holder_number": events.get("holder_number", [])[:12],
            "repurchase": events.get("repurchase", [])[:12],
        },
        "risk_flags": risks,
        "data_quality": dossier.get("data_quality", {}),
    }


def build_oversold_rebound_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    market = dossier.get("market", {})
    financials = dossier.get("financials", {})
    events = dossier.get("shareholders_and_events", {})
    technical = _oversold_technical_signals(market.get("technical_snapshot", {}), market.get("daily_basic_recent", []))
    capital = _capital_signals(market.get("moneyflow_recent", []), market.get("margin_recent", []))
    catalysts = _short_term_catalysts(financials, dossier.get("announcements", []), events)
    quality = _quality_signals(financials)
    risks = _oversold_risks(dossier, technical, capital, quality)
    scores = _oversold_scores(technical, capital, catalysts, quality, risks, dossier.get("industry", {}))
    return {
        "ts_code": dossier.get("ts_code"),
        "company": dossier.get("company", {}),
        "framework": "oversold_rebound",
        "decision_helper": {
            "rating_hint": _oversold_rating(scores),
            "score_summary": scores,
            "core_view": _core_view(_oversold_rating(scores), scores),
        },
        "oversold_state": technical,
        "capital_flow": capital,
        "catalysts": catalysts,
        "fundamental_floor": {
            "financial_quality": quality,
            "valuation": _valuation_signals(market.get("valuation_snapshot", {}), market.get("daily_basic_recent", [])),
        },
        "market_context": {
            "daily_recent": market.get("daily_recent", [])[:80],
            "daily_basic_recent": market.get("daily_basic_recent", [])[:80],
            "industry": dossier.get("industry", {}),
        },
        "risk_flags": risks,
        "data_quality": dossier.get("data_quality", {}),
    }


ANALYSIS_FRAMEWORKS: dict[str, AnalysisFramework] = {
    "value_speculation": AnalysisFramework(
        key="value_speculation",
        label="价值投机",
        description="价值底线 + 催化/资金/技术时机，偏赔率和交易计划。",
        question=VALUE_SPECULATION_QUESTION,
        system_prompt=VALUE_SPECULATION_SYSTEM_PROMPT,
        dossier_builder=build_value_speculation_dossier,
    ),
    "value_quality": AnalysisFramework(
        key="value_quality",
        label="质量成长价值",
        description="偏中长期，评估公司质量、成长韧性和估值安全边际。",
        question=VALUE_QUALITY_QUESTION,
        system_prompt=VALUE_QUALITY_SYSTEM_PROMPT,
        dossier_builder=build_value_quality_dossier,
    ),
    "value_dividend": AnalysisFramework(
        key="value_dividend",
        label="低估红利价值",
        description="偏防御，评估低估、分红、现金流和价值陷阱风险。",
        question=VALUE_DIVIDEND_QUESTION,
        system_prompt=VALUE_DIVIDEND_SYSTEM_PROMPT,
        dossier_builder=build_value_dividend_dossier,
    ),
    "oversold_rebound": AnalysisFramework(
        key="oversold_rebound",
        label="超跌反弹",
        description="偏短线，评估超跌程度、修复信号、资金回流和失效条件。",
        question=OVERSOLD_REBOUND_QUESTION,
        system_prompt=OVERSOLD_REBOUND_SYSTEM_PROMPT,
        dossier_builder=build_oversold_rebound_dossier,
    ),
}


def _valuation_signals(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    latest = snapshot or (history[0] if history else {})
    pe_ttm = _num(latest.get("pe_ttm") or latest.get("pe"))
    pb = _num(latest.get("pb"))
    dividend_yield = _num(latest.get("dv_ttm"))
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
            "ps_ttm": _num(latest.get("ps_ttm")),
            "dividend_yield_ttm": dividend_yield,
            "total_mv": _num(latest.get("total_mv")),
            "circ_mv": latest.get("circ_mv"),
        },
        "relative_position": {
            "pe_vs_recent_avg": _ratio_vs_avg(pe_ttm, pe_series),
            "pb_vs_recent_avg": _ratio_vs_avg(pb, pb_series),
        },
        "signals": [
            *_flag(pe_ttm is not None and 0 < pe_ttm <= 15, "PE_TTM 处于相对低估区间"),
            *_flag(pb is not None and pb <= 1.5, "PB 偏低，账面估值具备一定安全边际"),
            *_flag(dividend_yield is not None and dividend_yield >= 3, "股息率具备防御性吸引力"),
            *_flag(pe_ttm is not None and pe_ttm > 60, "PE_TTM 偏高，对业绩兑现要求较高"),
        ],
    }


def _quality_signals(financials: dict[str, Any]) -> dict[str, Any]:
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
    net_margin = _num(latest_indicator.get("netprofit_margin"))
    latest_cash = cashflow_recent[0] if cashflow_recent else {}
    operating_cashflow = _num(latest_cash.get("n_cashflow_act"))
    net_profit = _num(latest_cash.get("net_profit") or latest_income.get("n_income_attr_p") or latest_income.get("n_income"))
    return {
        "latest_income": latest_income,
        "latest_indicator": latest_indicator,
        "recent_income": income_recent[:12],
        "recent_cashflow": cashflow_recent[:12],
        "recent_indicators": indicator_recent[:12],
        "derived": {
            "revenue_yoy": revenue_yoy,
            "netprofit_yoy": netprofit_yoy,
            "roe": roe,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "operating_cashflow_to_profit": _safe_div(operating_cashflow, net_profit),
            "roe_series_avg": _series_avg(trend.get("roe_series", []), "roe"),
            "gross_margin_series_avg": _series_avg(trend.get("gross_margin_series", []), "grossprofit_margin"),
        },
        "signals": [
            *_flag(roe is not None and roe >= 10, "ROE 较高，资产盈利能力较好"),
            *_flag(revenue_yoy is not None and revenue_yoy > 0, "营收同比为正，成长仍有支撑"),
            *_flag(netprofit_yoy is not None and netprofit_yoy > 0, "净利润同比为正，盈利趋势偏积极"),
            *_flag(operating_cashflow is not None and net_profit is not None and operating_cashflow >= net_profit, "经营现金流覆盖利润，盈利质量较好"),
            *_flag(revenue_yoy is not None and revenue_yoy < -5, "营收明显下滑，成长韧性承压"),
            *_flag(netprofit_yoy is not None and netprofit_yoy < -10, "净利润明显下滑，盈利质量需要复核"),
        ],
    }


def _safety_signals(financials: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
    latest_indicator = financials.get("financial_trends", {}).get("latest_indicator", {})
    balance_recent = financials.get("balance_recent", [])
    latest_balance = balance_recent[0] if balance_recent else {}
    debt_to_assets = _num(latest_indicator.get("debt_to_assets"))
    current_ratio = _num(latest_indicator.get("current_ratio"))
    receivables = _num(latest_balance.get("accounts_receiv"))
    inventories = _num(latest_balance.get("inventories"))
    total_assets = _num(latest_balance.get("total_assets"))
    pledge = events.get("pledge_stat", [])
    latest_pledge = pledge[0] if pledge else {}
    pledge_ratio = _num(latest_pledge.get("pledge_ratio"))
    return {
        "latest_balance": latest_balance,
        "pledge_stat": pledge[:12],
        "derived": {
            "debt_to_assets": debt_to_assets,
            "current_ratio": current_ratio,
            "receivables_to_assets": _safe_div(receivables, total_assets),
            "inventories_to_assets": _safe_div(inventories, total_assets),
            "pledge_ratio": pledge_ratio,
        },
        "signals": [
            *_flag(debt_to_assets is not None and debt_to_assets <= 55, "资产负债率较稳健"),
            *_flag(current_ratio is not None and current_ratio >= 1.2, "流动比率具备一定安全垫"),
            *_flag(pledge_ratio is not None and pledge_ratio >= 30, "股权质押比例较高，需要关注强平和治理风险"),
            *_flag(debt_to_assets is not None and debt_to_assets >= 75, "资产负债率较高，需要结合行业属性复核"),
        ],
    }


def _dividend_signals(financials: dict[str, Any]) -> dict[str, Any]:
    dividend = financials.get("dividend", [])
    recent_cash_div = [_num(row.get("cash_div")) for row in dividend[:8]]
    recent_cash_div = [value for value in recent_cash_div if value is not None]
    return {
        "dividend_recent": dividend[:16],
        "audit": financials.get("audit", [])[:12],
        "derived": {
            "cash_dividend_records": len(recent_cash_div),
            "avg_cash_dividend_recent": round(mean(recent_cash_div), 4) if recent_cash_div else None,
        },
        "signals": [
            *_flag(len(recent_cash_div) >= 3, "近年存在多次现金分红记录"),
            *_flag(len(recent_cash_div) == 0, "资料包中未看到明确现金分红记录"),
        ],
    }


def _oversold_technical_signals(snapshot: dict[str, Any], valuation_history: list[dict[str, Any]]) -> dict[str, Any]:
    latest = snapshot.get("latest", {})
    close = _num(latest.get("close"))
    moving = snapshot.get("moving_average", {})
    returns = snapshot.get("return_pct", {})
    ma20 = _num(moving.get("ma20"))
    ma60 = _num(moving.get("ma60"))
    ma120 = _num(moving.get("ma120"))
    drawdown = _num(snapshot.get("max_drawdown_pct_recent"))
    turnover_values = [_num(row.get("turnover_rate")) for row in valuation_history[:20]]
    turnover_values = [value for value in turnover_values if value is not None]
    return {
        "latest": latest,
        "returns": returns,
        "moving_average": moving,
        "max_drawdown_pct_recent": drawdown,
        "derived": {
            "below_ma20_pct": _distance_pct(close, ma20),
            "below_ma60_pct": _distance_pct(close, ma60),
            "below_ma120_pct": _distance_pct(close, ma120),
            "above_ma20": close is not None and ma20 is not None and close >= ma20,
            "above_ma60": close is not None and ma60 is not None and close >= ma60,
            "avg_turnover_20d": round(mean(turnover_values), 3) if turnover_values else None,
        },
        "signals": [
            *_flag(_num(returns.get("20d")) is not None and _num(returns.get("20d")) <= -8, "近 20 日跌幅较大，具备短线超跌特征"),
            *_flag(_num(returns.get("60d")) is not None and _num(returns.get("60d")) <= -15, "近 60 日跌幅较大，存在阶段性修复空间"),
            *_flag(drawdown is not None and drawdown <= -25, "近期最大回撤较深，超跌程度较高"),
            *_flag(close is not None and ma20 is not None and close >= ma20, "股价站回 MA20，短线修复信号出现"),
            *_flag(close is not None and ma60 is not None and close < ma60, "股价仍低于 MA60，中期弱势未扭转"),
        ],
    }


def _capital_signals(moneyflow: list[dict[str, Any]], margin: list[dict[str, Any]]) -> dict[str, Any]:
    net_values = [_money_net(row) for row in moneyflow[:20]]
    net_values = [value for value in net_values if value is not None]
    five_day_net = round(sum(net_values[:5]), 2) if net_values else None
    twenty_day_net = round(sum(net_values[:20]), 2) if net_values else None
    latest_margin = margin[0] if margin else {}
    earlier_margin = margin[min(len(margin) - 1, 20)] if margin else {}
    margin_change = None
    if _num(latest_margin.get("rzrqye")) is not None and _num(earlier_margin.get("rzrqye")) is not None:
        margin_change = _num(latest_margin.get("rzrqye")) - _num(earlier_margin.get("rzrqye"))
    return {
        "moneyflow_recent": moneyflow[:20],
        "margin_recent": margin[:12],
        "derived": {
            "five_day_net_mf_amount": five_day_net,
            "twenty_day_net_mf_amount": twenty_day_net,
            "margin_balance_change_approx": margin_change,
        },
        "signals": [
            *_flag(five_day_net is not None and five_day_net > 0, "近 5 日资金净流入，短线资金回流"),
            *_flag(twenty_day_net is not None and twenty_day_net > 0, "近 20 日资金净流入，反弹确认度提高"),
            *_flag(five_day_net is not None and five_day_net < 0, "近 5 日资金仍净流出，反弹缺少资金确认"),
        ],
    }


def _short_term_catalysts(financials: dict[str, Any], announcements: list[dict[str, Any]], events: dict[str, Any]) -> dict[str, Any]:
    titles = [str(row.get("title") or "") for row in announcements[:30]]
    keywords = ("回购", "增持", "业绩预告", "业绩快报", "重组", "中标", "订单", "重大合同", "分红")
    return {
        "express_recent": financials.get("express_recent", [])[:8],
        "forecast_recent": financials.get("forecast_recent", [])[:8],
        "repurchase": events.get("repurchase", [])[:8],
        "announcement_keywords": [title for title in titles if any(word in title for word in keywords)],
        "signals": [
            *_flag(bool(financials.get("forecast_recent")), "存在业绩预告，可作为短线验证线索"),
            *_flag(bool(events.get("repurchase")), "存在回购记录，可能形成价格支撑"),
            *_flag(any("增持" in title or "回购" in title for title in titles), "公告中存在增持/回购相关线索"),
        ],
    }


def _quality_risks(dossier: dict[str, Any], quality: dict[str, Any], valuation: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, str]]:
    risks = _base_risks(dossier, quality, valuation, safety)
    derived = quality.get("derived", {})
    _append(risks, _num(derived.get("roe")) is not None and _num(derived.get("roe")) < 5, "medium", "ROE 偏弱", "资产盈利能力不足，长期复利基础偏弱。")
    return risks


def _dividend_risks(dossier: dict[str, Any], quality: dict[str, Any], valuation: dict[str, Any], dividend: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, str]]:
    risks = _base_risks(dossier, quality, valuation, safety)
    _append(risks, dividend.get("derived", {}).get("cash_dividend_records", 0) == 0, "medium", "分红记录缺失", "资料包中缺少明确现金分红记录，红利逻辑需要复核。")
    return risks


def _oversold_risks(dossier: dict[str, Any], technical: dict[str, Any], capital: dict[str, Any], quality: dict[str, Any]) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    returns = technical.get("returns", {})
    cap = capital.get("derived", {})
    q = quality.get("derived", {})
    _append(risks, _num(returns.get("20d")) is not None and _num(returns.get("20d")) < -20, "medium", "跌势剧烈", "短期跌幅过大，可能仍处于趋势释放阶段。")
    _append(risks, _num(cap.get("five_day_net_mf_amount")) is not None and _num(cap.get("five_day_net_mf_amount")) < 0, "medium", "资金未确认", "短线资金仍净流出，反弹可靠性不足。")
    _append(risks, _num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) < -10, "high", "业绩承压", "净利润明显下滑，反弹可能缺少基本面底线。")
    _append(risks, bool(dossier.get("data_quality", {}).get("fetch_errors")), "low", "数据缺口", "部分接口未成功，短线判断需要人工复核。")
    return risks


def _base_risks(dossier: dict[str, Any], quality: dict[str, Any], valuation: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    q = quality.get("derived", {})
    v = valuation.get("latest", {})
    s = safety.get("derived", {})
    _append(risks, _num(q.get("revenue_yoy")) is not None and _num(q.get("revenue_yoy")) < -5, "high", "营收下滑", "营收同比明显下滑，价值判断需要更高安全边际。")
    _append(risks, _num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) < -10, "high", "利润下滑", "净利润明显下滑，可能侵蚀价值基础。")
    _append(risks, _num(q.get("operating_cashflow_to_profit")) is not None and _num(q.get("operating_cashflow_to_profit")) < 0.6, "medium", "现金流偏弱", "经营现金流对利润覆盖不足。")
    _append(risks, _num(v.get("pe_ttm")) is not None and _num(v.get("pe_ttm")) > 60, "medium", "估值偏高", "PE_TTM 偏高，对业绩兑现要求较高。")
    _append(risks, _num(s.get("debt_to_assets")) is not None and _num(s.get("debt_to_assets")) >= 75, "medium", "负债较高", "资产负债率较高，需要结合行业属性复核。")
    _append(risks, bool(dossier.get("data_quality", {}).get("fetch_errors")), "low", "数据缺口", "部分接口未成功，分析完整性受影响。")
    return risks


def _quality_scores(quality: dict[str, Any], valuation: dict[str, Any], safety: dict[str, Any], risks: list[dict[str, str]]) -> dict[str, int]:
    q = quality.get("derived", {})
    v = valuation.get("latest", {})
    s = safety.get("derived", {})
    return {
        "business_quality": _clamp(2 + _point(_num(q.get("roe")) is not None and _num(q.get("roe")) >= 10) + _point(_num(q.get("gross_margin")) is not None and _num(q.get("gross_margin")) >= 20)),
        "earnings_resilience": _clamp(2 + _point(_num(q.get("revenue_yoy")) is not None and _num(q.get("revenue_yoy")) > 0) + _point(_num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) > 0)),
        "growth_sustainability": _clamp(2 + _point(_num(q.get("revenue_yoy")) is not None and _num(q.get("revenue_yoy")) >= 5) + _point(_num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) >= 5)),
        "cashflow_quality": _clamp(2 + _point(_num(q.get("operating_cashflow_to_profit")) is not None and _num(q.get("operating_cashflow_to_profit")) >= 0.8)),
        "balance_sheet_safety": _clamp(2 + _point(_num(s.get("debt_to_assets")) is not None and _num(s.get("debt_to_assets")) <= 55) + _point(_num(s.get("current_ratio")) is not None and _num(s.get("current_ratio")) >= 1.2)),
        "governance_return": _clamp(2 + _point(_num(s.get("pledge_ratio")) is not None and _num(s.get("pledge_ratio")) < 20)),
        "valuation_margin": _clamp(2 + _point(_num(v.get("pe_ttm")) is not None and 0 < _num(v.get("pe_ttm")) <= 25) + _point(_num(v.get("pb")) is not None and _num(v.get("pb")) <= 2.5)),
        "risk_pressure": _risk_score(risks),
    }


def _dividend_scores(quality: dict[str, Any], valuation: dict[str, Any], dividend: dict[str, Any], safety: dict[str, Any], risks: list[dict[str, str]]) -> dict[str, int]:
    q = quality.get("derived", {})
    v = valuation.get("latest", {})
    d = dividend.get("derived", {})
    s = safety.get("derived", {})
    return {
        "valuation_cheapness": _clamp(2 + _point(_num(v.get("pe_ttm")) is not None and 0 < _num(v.get("pe_ttm")) <= 15) + _point(_num(v.get("pb")) is not None and _num(v.get("pb")) <= 1.5)),
        "dividend_attractiveness": _clamp(1 + _point(_num(v.get("dividend_yield_ttm")) is not None and _num(v.get("dividend_yield_ttm")) >= 3) + _point(_num(d.get("cash_dividend_records")) is not None and _num(d.get("cash_dividend_records")) >= 3)),
        "earnings_stability": _clamp(2 + _point(_num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) >= 0)),
        "cashflow_coverage": _clamp(2 + _point(_num(q.get("operating_cashflow_to_profit")) is not None and _num(q.get("operating_cashflow_to_profit")) >= 0.8)),
        "balance_sheet_safety": _clamp(2 + _point(_num(s.get("debt_to_assets")) is not None and _num(s.get("debt_to_assets")) <= 60)),
        "industry_defensiveness": 2,
        "governance_return": _clamp(2 + _point(_num(d.get("cash_dividend_records")) is not None and _num(d.get("cash_dividend_records")) >= 3)),
        "risk_pressure": _risk_score(risks),
    }


def _oversold_scores(technical: dict[str, Any], capital: dict[str, Any], catalysts: dict[str, Any], quality: dict[str, Any], risks: list[dict[str, str]], industry: dict[str, Any]) -> dict[str, int]:
    returns = technical.get("returns", {})
    derived = technical.get("derived", {})
    cap = capital.get("derived", {})
    q = quality.get("derived", {})
    industry_returns = industry.get("industry_daily_snapshot", {}).get("return_pct", {})
    return {
        "oversold_degree": _clamp(1 + _point(_num(returns.get("20d")) is not None and _num(returns.get("20d")) <= -8) + _point(_num(returns.get("60d")) is not None and _num(returns.get("60d")) <= -15) + _point(_num(technical.get("max_drawdown_pct_recent")) is not None and _num(technical.get("max_drawdown_pct_recent")) <= -25)),
        "technical_repair": _clamp(1 + _point(bool(derived.get("above_ma20"))) + _point(bool(derived.get("above_ma60")))),
        "volume_confirmation": _clamp(2 + _point(_num(derived.get("avg_turnover_20d")) is not None and _num(derived.get("avg_turnover_20d")) >= 2)),
        "capital_return": _clamp(2 + _point(_num(cap.get("five_day_net_mf_amount")) is not None and _num(cap.get("five_day_net_mf_amount")) > 0) + _point(_num(cap.get("twenty_day_net_mf_amount")) is not None and _num(cap.get("twenty_day_net_mf_amount")) > 0)),
        "industry_resonance": _clamp(2 + _point(_num(industry_returns.get("20d")) is not None and _num(industry_returns.get("20d")) > 0)),
        "catalyst_support": _clamp(1 + len(catalysts.get("signals", []))),
        "fundamental_floor": _clamp(2 + _point(_num(q.get("netprofit_yoy")) is not None and _num(q.get("netprofit_yoy")) >= 0) + _point(_num(q.get("operating_cashflow_to_profit")) is not None and _num(q.get("operating_cashflow_to_profit")) >= 0.8)),
        "risk_pressure": _risk_score(risks),
    }


def _quality_rating(scores: dict[str, int]) -> str:
    positive = sum(value for key, value in scores.items() if key != "risk_pressure")
    risk = scores.get("risk_pressure", 0)
    if risk >= 4 or positive <= 16:
        return "回避"
    if positive >= 25 and risk <= 2:
        return "优质可跟踪"
    if positive >= 21:
        return "估值等待"
    return "质量存疑"


def _dividend_rating(scores: dict[str, int]) -> str:
    positive = sum(value for key, value in scores.items() if key != "risk_pressure")
    risk = scores.get("risk_pressure", 0)
    if risk >= 4 or positive <= 15:
        return "回避"
    if positive >= 24 and risk <= 2:
        return "红利底仓候选"
    if positive >= 19:
        return "等待价格"
    return "分红不稳"


def _oversold_rating(scores: dict[str, int]) -> str:
    positive = sum(value for key, value in scores.items() if key != "risk_pressure")
    risk = scores.get("risk_pressure", 0)
    if risk >= 4 or positive <= 14:
        return "回避"
    if positive >= 24 and risk <= 3:
        return "试错窗口"
    if positive >= 18:
        return "反弹观察"
    return "弱势等待"


def _core_view(rating: str, scores: dict[str, int]) -> str:
    parts = [f"评级提示：{rating}"]
    parts.extend(f"{key} {value}/5" for key, value in scores.items())
    return "；".join(parts)


def _risk_score(risks: list[dict[str, str]]) -> int:
    return _clamp(sum(2 if item.get("level") == "high" else 1 for item in risks))


def _series_avg(series: list[dict[str, Any]], field: str) -> float | None:
    values = [_num(row.get(field)) for row in series]
    values = [value for value in values if value is not None]
    return round(mean(values), 4) if values else None


def _money_net(row: dict[str, Any]) -> float | None:
    explicit = _num(row.get("net_mf_amount"))
    if explicit is not None:
        return explicit
    buy = sum(_num(row.get(key)) or 0 for key in ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"))
    sell = sum(_num(row.get(key)) or 0 for key in ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount"))
    return buy - sell


def _distance_pct(value: float | None, base: float | None) -> float | None:
    if value is None or base in (None, 0):
        return None
    return round((value / base - 1) * 100, 2)


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
