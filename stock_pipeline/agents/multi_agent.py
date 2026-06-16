from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from ..analysis_frameworks import get_analysis_framework
from ..collector import StockDataCollector
from ..deepseek_client import DeepSeekClient, DeepSeekError
from ..dossier import build_dossier
from ..pattern_learning import build_similarity_learning
from ..news_search import search_related_news
from ..stock_storage import (
    LOCAL_DATA_DIR,
    build_local_stock_payload,
    current_dir,
    stock_exists,
    sync_stock_data,
)
from ..tushare_client import TushareClient, TushareError
from ..utils import ensure_dir, read_json, timestamp, today_yyyymmdd, write_json, years_ago_yyyymmdd
from ..analysis_frameworks import build_all_analysis_dossiers


MODE_CONFIG: dict[str, dict[str, Any]] = {
    "oversold_rebound": {
        "label": "超跌反弹",
        "time_horizon": "1-20 个交易日",
        "required_datasets": ["daily", "daily_basic", "moneyflow", "stk_limit"],
        "secondary_datasets": ["sw_daily", "anns_d", "margin_detail"],
        "agents": ["oversold_detector", "volume_agent", "moneyflow_agent", "sentiment_agent", "fundamental_floor_agent", "risk_auditor"],
        "max_fetch_rounds": 2,
        "agent_max_tokens": 1400,
        "critic_max_tokens": 0,
        "enable_critic_review": False,
        "enable_revision_round": False,
        "context_profile": "minimal",
        "template_overrides": {
            "tradingagents": {
                "agents": ["market_analyst", "news_analyst", "sentiment_analyst", "trader", "aggressive_risk_analyst"],
                "agent_max_tokens": 1400,
                "critic_max_tokens": 0,
                "enable_critic_review": False,
                "enable_revision_round": False,
                "context_profile": "minimal",
            },
            "finrobot": {
                "agents": ["news_summary_agent", "major_takeaways_agent", "risk_section_agent"],
                "agent_max_tokens": 1200,
                "critic_max_tokens": 0,
                "enable_critic_review": False,
                "enable_revision_round": False,
                "context_profile": "minimal",
            },
        },
    },
    "value_speculation": {
        "label": "价值投机",
        "time_horizon": "1-6 个月",
        "required_datasets": ["daily_basic", "fina_indicator", "income", "cashflow", "moneyflow", "anns_d"],
        "secondary_datasets": ["daily", "margin_detail", "top10_holders", "stk_holdernumber", "index_member_all", "sw_daily"],
        "agents": ["value_floor_agent", "valuation_agent", "industry_cycle_agent", "catalyst_agent", "moneyflow_agent", "technical_timing_agent", "risk_auditor"],
        "max_fetch_rounds": 2,
        "agent_max_tokens": 1900,
        "critic_max_tokens": 1400,
        "enable_critic_review": True,
        "enable_revision_round": True,
        "context_profile": "focused",
        "template_overrides": {
            "tradingagents": {
                "agents": [
                    "market_analyst",
                    "news_analyst",
                    "fundamental_analyst",
                    "bull_researcher",
                    "bear_researcher",
                    "trader",
                    "neutral_risk_analyst",
                    "portfolio_manager",
                ],
                "agent_max_tokens": 1900,
                "critic_max_tokens": 1400,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "focused",
            },
            "finrobot": {
                "agents": ["investment_update_agent", "valuation_overview_agent", "risk_section_agent", "major_takeaways_agent"],
                "agent_max_tokens": 1600,
                "critic_max_tokens": 1200,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "focused",
            },
        },
    },
    "value_quality": {
        "label": "质量成长价值",
        "time_horizon": "1-3 年",
        "required_datasets": ["income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz"],
        "secondary_datasets": ["index_member_all", "sw_daily", "top10_holders", "fina_audit"],
        "agents": ["business_quality_agent", "financial_trend_agent", "cashflow_agent", "industry_position_agent", "valuation_margin_agent", "risk_auditor"],
        "max_fetch_rounds": 2,
        "agent_max_tokens": 2200,
        "critic_max_tokens": 1600,
        "enable_critic_review": True,
        "enable_revision_round": True,
        "context_profile": "deep",
        "template_overrides": {
            "tradingagents": {
                "agents": [
                    "fundamental_analyst",
                    "moat_governance_agent",
                    "bull_researcher",
                    "bear_researcher",
                    "research_manager",
                    "conservative_risk_analyst",
                    "portfolio_manager",
                ],
                "agent_max_tokens": 2200,
                "critic_max_tokens": 1600,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "deep",
            },
            "finrobot": {
                "agents": [
                    "company_overview_agent",
                    "investment_update_agent",
                    "competitor_analysis_agent",
                    "risk_section_agent",
                    "major_takeaways_agent",
                ],
                "agent_max_tokens": 1800,
                "critic_max_tokens": 1400,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "deep",
            },
        },
    },
    "value_dividend": {
        "label": "低估红利价值",
        "time_horizon": "6 个月-3 年",
        "required_datasets": ["dividend", "cashflow", "balancesheet", "fina_indicator", "daily_basic"],
        "secondary_datasets": ["repurchase", "pledge_stat", "top10_holders", "fina_audit"],
        "agents": ["cheapness_agent", "dividend_sustainability_agent", "cashflow_coverage_agent", "balance_sheet_agent", "governance_agent", "risk_auditor"],
        "max_fetch_rounds": 2,
        "agent_max_tokens": 1800,
        "critic_max_tokens": 1400,
        "enable_critic_review": True,
        "enable_revision_round": True,
        "context_profile": "focused",
        "template_overrides": {
            "tradingagents": {
                "agents": [
                    "fundamental_analyst",
                    "news_analyst",
                    "moat_governance_agent",
                    "research_manager",
                    "conservative_risk_analyst",
                    "portfolio_manager",
                ],
                "agent_max_tokens": 1800,
                "critic_max_tokens": 1400,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "focused",
            },
            "finrobot": {
                "agents": ["company_overview_agent", "valuation_overview_agent", "risk_section_agent", "major_takeaways_agent"],
                "agent_max_tokens": 1500,
                "critic_max_tokens": 1200,
                "enable_critic_review": True,
                "enable_revision_round": True,
                "context_profile": "focused",
            },
        },
    },
}


AGENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "native": {"label": "项目原生专题组"},
    "tradingagents": {
        "label": "TradingAgents 风格投研交易团队",
        "agents": [
            "market_analyst",
            "news_analyst",
            "fundamental_analyst",
            "sentiment_analyst",
            "moat_governance_agent",
            "bull_researcher",
            "bear_researcher",
            "research_manager",
            "trader",
            "aggressive_risk_analyst",
            "neutral_risk_analyst",
            "conservative_risk_analyst",
            "portfolio_manager",
        ],
        "debate_agents": ["bull_researcher", "bear_researcher"],
        "risk_agents": ["aggressive_risk_analyst", "neutral_risk_analyst", "conservative_risk_analyst"],
    },
    "finrobot": {
        "label": "FinRobot 风格投研报告团队",
        "agents": [
            "company_overview_agent",
            "investment_update_agent",
            "valuation_overview_agent",
            "risk_section_agent",
            "competitor_analysis_agent",
            "news_summary_agent",
            "major_takeaways_agent",
        ],
        "debate_agents": ["investment_update_agent", "risk_section_agent"],
        "risk_agents": ["risk_section_agent"],
    },
}


DATASET_NEEDS: dict[str, str] = {
    "daily": "日线走势、涨跌幅、K 线和成交量",
    "weekly": "周线趋势",
    "monthly": "月线趋势",
    "daily_basic": "估值、换手率、量比和市值",
    "moneyflow": "资金流入流出",
    "margin_detail": "融资融券变化",
    "stk_limit": "涨跌停价格和短线情绪边界",
    "income": "利润表和收入利润趋势",
    "balancesheet": "资产负债结构",
    "cashflow": "现金流质量",
    "fina_indicator": "ROE、毛利率、负债率等财务指标",
    "dividend": "分红与股东回报",
    "repurchase": "回购记录",
    "fina_mainbz": "主营业务结构",
    "top10_holders": "前十大股东结构",
    "stk_holdernumber": "股东户数和筹码分散程度",
    "pledge_stat": "股权质押风险",
    "fina_audit": "审计意见",
    "anns_d": "公告和事件催化",
    "index_member_all": "行业归属",
    "sw_daily": "行业指数走势",
}


AGENT_SPECS: dict[str, dict[str, Any]] = {
    "oversold_detector": {"role": "超跌检测员", "focus": "只判断跌幅、回撤、均线偏离和止跌修复，不讨论长期价值。", "slice_keys": ["oversold_state", "market_context"]},
    "volume_agent": {"role": "成交量分析员", "focus": "专注量价关系、换手率、成交额、缩量/放量和异常交易活跃度。", "slice_keys": ["oversold_state", "market_context"]},
    "moneyflow_agent": {"role": "资金流分析员", "focus": "专注近 5/20 日资金净流入、大小单、融资融券和资金确认。", "slice_keys": ["capital_flow", "speculation_triggers", "market_context"]},
    "sentiment_agent": {"role": "情绪与催化分析员", "focus": "专注行业情绪、涨跌停、公告催化、回购增持和短线事件。", "slice_keys": ["catalysts", "speculation_triggers", "industry_cycle", "market_context"]},
    "fundamental_floor_agent": {"role": "基本面底线分析员", "focus": "只判断是否存在明显财务雷和基本面底线，不做长线完整估值。", "slice_keys": ["fundamental_floor", "financial_quality", "balance_sheet_safety", "risk_flags"]},
    "value_floor_agent": {"role": "价值底线分析员", "focus": "判断公司是否有基本面底线，排除纯题材和价值陷阱。", "slice_keys": ["value_basis", "financial_quality", "balance_sheet_safety", "risk_flags"]},
    "valuation_agent": {"role": "估值分析员", "focus": "专注 PE/PB/PS/股息率、市值和相对估值位置。", "slice_keys": ["valuation", "value_basis"]},
    "industry_cycle_agent": {"role": "行业周期分析员", "focus": "专注行业指数趋势、周期位置、供需线索和外部行业变量；对未进入资料包的数据必须标为外部假设。", "slice_keys": ["industry_cycle", "catalysts", "speculation_triggers", "risk_flags"]},
    "catalyst_agent": {"role": "催化事件分析员", "focus": "专注财报、公告、回购、分红、订单、行业趋势等催化。", "slice_keys": ["catalysts", "speculation_triggers", "dividend_and_return"]},
    "technical_timing_agent": {"role": "技术时机分析员", "focus": "专注 MA20/MA60/MA120/MA250、趋势确认和失效位置。", "slice_keys": ["speculation_triggers", "oversold_state", "market_context"]},
    "business_quality_agent": {"role": "商业质量分析员", "focus": "专注主营业务、行业位置、收入来源、护城河线索。", "slice_keys": ["business_quality", "industry_cycle"]},
    "financial_trend_agent": {"role": "财务趋势分析员", "focus": "专注营收、净利润、ROE、毛利率、净利率和趋势持续性。", "slice_keys": ["financial_quality", "profit_and_cashflow_stability"]},
    "cashflow_agent": {"role": "现金流分析员", "focus": "专注经营现金流、利润含金量、自由现金流线索和现金流风险。", "slice_keys": ["financial_quality", "profit_and_cashflow_stability", "dividend_and_return"]},
    "industry_position_agent": {"role": "行业位置分析员", "focus": "专注行业归属、行业指数、行业 beta、行业景气和公司相对位置。", "slice_keys": ["industry_cycle", "business_quality", "market_context"]},
    "valuation_margin_agent": {"role": "安全边际分析员", "focus": "专注估值是否给长期跟踪留出安全边际，而不是短期交易。", "slice_keys": ["valuation", "business_quality", "financial_quality"]},
    "cheapness_agent": {"role": "低估分析员", "focus": "专注 PE/PB/股息率是否真的便宜，以及便宜的原因。", "slice_keys": ["valuation", "dividend_and_return"]},
    "dividend_sustainability_agent": {"role": "分红持续性分析员", "focus": "专注历史分红、利润稳定性、现金流覆盖和分红可持续性。", "slice_keys": ["dividend_and_return", "profit_and_cashflow_stability"]},
    "cashflow_coverage_agent": {"role": "现金流覆盖分析员", "focus": "专注经营现金流能否覆盖利润、分红和负债压力。", "slice_keys": ["profit_and_cashflow_stability", "balance_sheet_safety", "dividend_and_return"]},
    "balance_sheet_agent": {"role": "资产负债分析员", "focus": "专注负债率、流动性、货币资金、应收、存货和偿债风险。", "slice_keys": ["balance_sheet_safety", "financial_quality"]},
    "governance_agent": {"role": "治理风险分析员", "focus": "专注质押、股东结构、回购、审计意见和治理风险。", "slice_keys": ["shareholder_structure", "dividend_and_return", "risk_flags"]},
    "risk_auditor": {"role": "风险审计员", "focus": "只负责找漏洞、反证、数据缺口和证伪条件，不负责寻找机会。", "slice_keys": ["risk_flags", "data_quality", "valuation", "financial_quality", "market_context"]},
    "market_analyst": {"role": "市场分析师", "focus": "对应 TradingAgents Market Analyst，先看价格趋势、成交活跃度、市场状态和交易时机，只给市场层面的证据。", "slice_keys": ["speculation_triggers", "oversold_state", "market_context", "capital_flow"]},
    "news_analyst": {"role": "新闻分析师", "focus": "对应 TradingAgents News Analyst，梳理公告、事件、行业新闻和催化强弱，区分已验证资料与外部假设。", "slice_keys": ["catalysts", "industry_cycle", "speculation_triggers", "risk_flags"]},
    "fundamental_analyst": {"role": "基本面分析师", "focus": "参考 TradingAgents 的基本面分析角色，整合利润表、资产负债、现金流、行业位置和经营质量。", "slice_keys": ["value_basis", "financial_quality", "balance_sheet_safety", "business_quality", "industry_cycle"]},
    "technical_analyst": {"role": "技术面分析师", "focus": "参考 TradingAgents 的技术分析角色，专注趋势、均线、量价、回撤和交易时机，不替代基本面结论。", "slice_keys": ["speculation_triggers", "oversold_state", "market_context"]},
    "sentiment_analyst": {"role": "情绪与消息分析师", "focus": "参考 TradingAgents 的情绪分析角色，评估公告、资金流、涨跌停、行业催化和市场风险偏好。", "slice_keys": ["catalysts", "capital_flow", "speculation_triggers", "industry_cycle", "market_context"]},
    "moat_governance_agent": {"role": "隐形护城河与治理分析师", "focus": "专门挖掘财报不易直接体现的隐形变量：成本曲线、技术成熟度、管理层质量、接班风险、股权结构、同行短期追赶难度和护城河可持续性。必须区分已验证证据、新闻线索和待验证假设。", "slice_keys": ["hidden_condition_context", "news_context", "business_quality", "shareholder_structure", "risk_flags", "data_quality"]},
    "bull_researcher": {"role": "多头研究员", "focus": "参考 TradingAgents 的 Bull Researcher，只构建最强正向 thesis，并明确该 thesis 成立所需证据。", "slice_keys": ["value_basis", "valuation", "catalysts", "business_quality", "dividend_and_return"]},
    "bear_researcher": {"role": "空头研究员", "focus": "参考 TradingAgents 的 Bear Researcher，只构建最强反向 thesis，主动寻找价值陷阱、财务雷和情绪过热。", "slice_keys": ["risk_flags", "data_quality", "financial_quality", "balance_sheet_safety", "valuation"]},
    "research_manager": {"role": "研究经理", "focus": "对应 TradingAgents Research Manager，裁决多空辩论，明确哪一边证据更硬、哪些假设还没有被验证。", "slice_keys": ["value_basis", "valuation", "risk_flags", "decision_helper", "data_quality"]},
    "trader": {"role": "交易员", "focus": "对应 TradingAgents Trader，将研究结论转成观察、试错、等待或回避动作，并给出触发条件。", "slice_keys": ["speculation_triggers", "market_context", "valuation", "risk_flags", "decision_helper"]},
    "aggressive_risk_analyst": {"role": "激进风控分析师", "focus": "对应 TradingAgents Aggressive Analyst，站在收益机会角度评估可承受风险和进攻条件。", "slice_keys": ["catalysts", "capital_flow", "valuation", "market_context"]},
    "neutral_risk_analyst": {"role": "中性风控分析师", "focus": "对应 TradingAgents Neutral Analyst，平衡收益与风险，检查结论是否被单边叙事带偏。", "slice_keys": ["decision_helper", "data_quality", "risk_flags", "market_context"]},
    "conservative_risk_analyst": {"role": "保守风控分析师", "focus": "对应 TradingAgents Conservative Analyst，优先找最大亏损来源、财务雷、流动性风险和证伪条件。", "slice_keys": ["risk_flags", "balance_sheet_safety", "data_quality", "financial_quality"]},
    "portfolio_manager": {"role": "组合经理", "focus": "对应 TradingAgents Portfolio Manager，整合研究经理、交易员和三类风控意见，输出最终仓位倾向和置信度折扣。", "slice_keys": ["decision_helper", "valuation", "risk_flags", "market_context", "data_quality"]},
    "risk_manager": {"role": "风险经理", "focus": "参考 TradingAgents 的风险管理团队，负责仓位风险、证伪条件、数据缺口和最终结论的置信度折扣。", "slice_keys": ["risk_flags", "data_quality", "market_context", "valuation", "financial_quality"]},
    "trade_decision_agent": {"role": "交易决策官", "focus": "参考 TradingAgents 的 Trader，综合基本面、技术面、多空辩论和风控意见，输出观察/试错/回避的研究动作。", "slice_keys": ["valuation", "speculation_triggers", "risk_flags", "market_context", "decision_helper"]},
    "company_overview_agent": {"role": "公司概览 Agent", "focus": "对应 FinRobot Equity company overview，提炼业务、行业位置、收入来源和核心跟踪变量。", "slice_keys": ["business_quality", "industry_cycle", "value_basis"]},
    "investment_update_agent": {"role": "投资更新 Agent", "focus": "对应 FinRobot investment overview，评估近期事件对原投资 thesis 的强化、削弱或破坏。", "slice_keys": ["catalysts", "value_basis", "financial_quality", "decision_helper"]},
    "valuation_overview_agent": {"role": "估值概览 Agent", "focus": "对应 FinRobot valuation overview，做横向行业估值、纵向历史估值和安全边际判断。", "slice_keys": ["valuation", "financial_quality", "dividend_and_return", "profit_and_cashflow_stability"]},
    "risk_section_agent": {"role": "风险章节 Agent", "focus": "对应 FinRobot risks section，集中输出投资报告中的核心风险、触发条件和需要删除/保留的假设。", "slice_keys": ["risk_flags", "balance_sheet_safety", "data_quality", "shareholder_structure"]},
    "competitor_analysis_agent": {"role": "竞争分析 Agent", "focus": "对应 FinRobot competitor analysis，在资料允许范围内评估行业位置、竞争格局和相对优势。", "slice_keys": ["business_quality", "industry_cycle", "market_context"]},
    "news_summary_agent": {"role": "新闻摘要 Agent", "focus": "对应 FinRobot news summary，压缩公告和新闻为影响投资 thesis 的事件摘要。", "slice_keys": ["catalysts", "speculation_triggers", "risk_flags"]},
    "major_takeaways_agent": {"role": "核心结论 Agent", "focus": "对应 FinRobot major takeaways，整合前序章节为简洁、可执行、可证伪的投研结论。", "slice_keys": ["decision_helper", "valuation", "risk_flags", "data_quality"]},
    "data_cot_agent": {"role": "Data-CoT 数据链分析师", "focus": "参考 FinRobot 的 Data-CoT Agent，先审计资料完整性、数据口径、关键缺失和可用证据范围。", "slice_keys": ["data_quality", "market_context", "financial_quality", "valuation"]},
    "concept_cot_agent": {"role": "Concept-CoT 概念链分析师", "focus": "参考 FinRobot 的 Concept-CoT Agent，从商业模式、行业位置、催化和风险中提炼投资概念。", "slice_keys": ["business_quality", "industry_cycle", "catalysts", "value_basis"]},
    "valuation_cot_agent": {"role": "Valuation-CoT 估值链分析师", "focus": "参考 FinRobot 的估值分析流程，评估估值分位、安全边际、盈利质量和股东回报。", "slice_keys": ["valuation", "financial_quality", "dividend_and_return", "profit_and_cashflow_stability"]},
    "risk_cot_agent": {"role": "Risk-CoT 风险链分析师", "focus": "参考 FinRobot 的风险审查流程，集中审计财务、治理、行业周期和数据不足导致的结论不可靠。", "slice_keys": ["risk_flags", "balance_sheet_safety", "data_quality", "shareholder_structure"]},
    "thesis_cot_agent": {"role": "Thesis-CoT 投资论点分析师", "focus": "参考 FinRobot 的 Thesis-CoT Agent，综合前序证据形成可证伪的投资 thesis 和跟踪路径。", "slice_keys": ["value_basis", "valuation", "business_quality", "risk_flags", "decision_helper"]},
}


ProgressCallback = Callable[[dict[str, Any]], None]


class EvidenceClaim(BaseModel):
    claim: str = ""
    data_path: str = ""
    strength: str = "medium"


class AgentVerdict(BaseModel):
    agent: str
    mode: str
    rating_hint: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    scores: dict[str, Any] = Field(default_factory=dict)
    key_findings: list[EvidenceClaim] = Field(default_factory=list)
    counter_evidence: list[EvidenceClaim] = Field(default_factory=list)
    reasoning_summary: str = ""
    watchlist: list[str] = Field(default_factory=list)
    invalidating_signals: list[str] = Field(default_factory=list)
    data_requests: list[dict[str, Any]] = Field(default_factory=list)


class CriticFinding(BaseModel):
    agent: str = ""
    issue: str
    severity: str = "medium"
    evidence_path: str = ""
    required_fix: str = ""


class CriticReview(BaseModel):
    findings: list[CriticFinding] = Field(default_factory=list)
    overall_risk: str = "medium"
    should_revise: bool = True
    force_rerun_agents: list[str] = Field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True)
class MultiAgentOptions:
    analysis_type: str = "value_speculation"
    allow_dynamic_fetch: bool = True
    use_llm_agents: bool = True
    reuse_agent_cache: bool = True
    years: int | None = None
    full_history: bool = True
    max_parallel_agents: int = 8
    template: str = "native"


def _mode_for_template(analysis_type: str, template: str = "native") -> dict[str, Any]:
    mode = dict(MODE_CONFIG[analysis_type])
    template_key = (template or "native").strip().lower()
    template_config = AGENT_TEMPLATES.get(template_key) or AGENT_TEMPLATES["native"]
    if template_key != "native":
        override = dict(mode.get("template_overrides", {}).get(template_key, {}))
        mode["agents"] = list(override.get("agents") or template_config["agents"])
        mode["template"] = template_key
        mode["template_label"] = template_config["label"]
        mode["debate_agents"] = list(template_config.get("debate_agents", []))
        mode["risk_agents"] = list(template_config.get("risk_agents", []))
        mode["agent_max_tokens"] = int(override["agent_max_tokens"] if "agent_max_tokens" in override else mode.get("agent_max_tokens") or 2048)
        mode["critic_max_tokens"] = int(override["critic_max_tokens"] if "critic_max_tokens" in override else mode.get("critic_max_tokens") or 1536)
        mode["enable_critic_review"] = bool(override.get("enable_critic_review", mode.get("enable_critic_review", True)))
        mode["enable_revision_round"] = bool(override.get("enable_revision_round", mode.get("enable_revision_round", True)))
        mode["context_profile"] = _text(override.get("context_profile") or mode.get("context_profile") or "focused")
    else:
        mode["template"] = "native"
        mode["template_label"] = AGENT_TEMPLATES["native"]["label"]
        mode["debate_agents"] = []
        mode["risk_agents"] = []
        mode["agent_max_tokens"] = int(mode.get("agent_max_tokens") or 2048)
        mode["critic_max_tokens"] = int(mode.get("critic_max_tokens") or 1536)
        mode["enable_critic_review"] = bool(mode.get("enable_critic_review", True))
        mode["enable_revision_round"] = bool(mode.get("enable_revision_round", True))
        mode["context_profile"] = _text(mode.get("context_profile") or "focused")
    mode["estimated_llm_calls"] = _estimated_llm_calls(mode)
    return mode


class MultiAgentRunner:
    def __init__(
        self,
        client: TushareClient | None = None,
        llm_client: DeepSeekClient | None = None,
        progress_callback: ProgressCallback | None = None,
    ):
        self.client = client
        self.llm_client = llm_client
        self.progress_callback = progress_callback

    def run(self, code: str, options: MultiAgentOptions | None = None) -> dict[str, Any]:
        opts = options or MultiAgentOptions()
        framework = get_analysis_framework(opts.analysis_type)
        mode = _mode_for_template(framework.key, opts.template)
        self._progress("start", f"进入 {mode['label']} 模式，准备分析 {code}。")

        if self.client and not stock_exists(code):
            self._progress("tushare_sync", "本地没有数据，开始通过 Tushare 同步基础资料包。")
            sync_stock_data(self.client, code, years=opts.years, full_history=opts.full_history)
            self._progress("tushare_sync", "基础资料包同步完成。")
        if not stock_exists(code):
            raise FileNotFoundError(f"本地还没有 {code} 的数据，请先更新本地数据。")

        base_dir = current_dir(code)
        run_id = f"{timestamp()}_{framework.key}"
        run_dir = ensure_dir(base_dir / "agent_runs" / run_id)
        self._progress("prepare", f"创建运行目录：{run_dir}。")

        write_json(run_dir / "run_manifest.json", _run_manifest(code, framework.key, mode, run_id, opts))
        full_data = read_json(base_dir / "full_data.json")
        dossier = read_json(base_dir / "dossier.json")
        _write_run_manifest(run_dir, code, framework.key, mode, run_id, opts, full_data)
        data_profile = _data_profile(full_data, mode)
        write_json(run_dir / "data_profile.json", data_profile)
        write_json(run_dir / "mode_context.json", _mode_context(framework.key, mode, dossier))
        self._progress(
            "data_profile",
            f"已读取本地资料包，关键缺失 {len(data_profile.get('missing_required', []))} 个，次要缺失 {len(data_profile.get('missing_secondary', []))} 个。",
            {"missing_required": data_profile.get("missing_required", []), "missing_secondary": data_profile.get("missing_secondary", [])},
        )

        data_requests = _build_data_requests(framework.key, mode, full_data)
        broker_result = _broker_data_requests(data_requests, full_data)
        write_json(run_dir / "data_requests.json", broker_result)
        self._progress(
            "data_broker",
            f"数据请求检查完成，批准补数 {len(broker_result.get('approved_requests', []))} 个。",
            {"approved_requests": broker_result.get("approved_requests", [])},
        )

        fetch_result = {"enabled": bool(opts.allow_dynamic_fetch and self.client), "fetch_results": [], "fetch_errors": [], "rebuilt": False}
        if opts.allow_dynamic_fetch and self.client and broker_result["approved_requests"]:
            fetch_result = self._fetch_and_rebuild(code, broker_result["approved_requests"], run_dir, opts)
            if fetch_result.get("rebuilt"):
                full_data = read_json(base_dir / "full_data.json")
                dossier = read_json(base_dir / "dossier.json")
                data_profile = _data_profile(full_data, mode)
                write_json(run_dir / "data_profile.json", data_profile)
        else:
            self._progress("tushare_fetch", "没有需要执行的动态补数，继续使用当前资料包。")
        write_json(run_dir / "tushare_fetch_results.json", fetch_result)

        hypotheses = _hypotheses(framework.key, mode)
        write_json(run_dir / "hypotheses.json", hypotheses)
        self._progress("hypotheses", f"已建立 {len(hypotheses.get('hypotheses', []))} 条初始假设。")

        analysis_dossier = read_json(base_dir / f"{framework.key}_dossier.json") if (base_dir / f"{framework.key}_dossier.json").exists() else {}
        hidden_context = _hidden_condition_context(dossier, full_data)
        news_context = search_related_news(_company_identity(dossier, full_data), limit=12, days=60)
        write_json(run_dir / "hidden_condition_context.json", hidden_context)
        write_json(run_dir / "news_context.json", news_context)
        learning_context = self._build_learning_context(full_data, framework.key, run_dir)
        memory_context = _load_decision_memory(data_profile["ts_code"], base_dir)
        write_json(run_dir / "decision_memory_context.json", memory_context)
        if learning_context:
            analysis_dossier = {**analysis_dossier, "learning_context": learning_context}
        analysis_dossier = {**analysis_dossier, "hidden_condition_context": hidden_context, "news_context": news_context}
        if memory_context.get("entries"):
            analysis_dossier = {**analysis_dossier, "decision_memory": memory_context}
        agent_results = _run_staged_specialists(
            framework.key,
            mode,
            dossier,
            analysis_dossier,
            full_data,
            broker_result,
            fetch_result,
            self.llm_client if opts.use_llm_agents else None,
            self.progress_callback,
            opts.max_parallel_agents,
            run_dir,
            opts.reuse_agent_cache,
        )
        agent_results = _validate_agent_results(agent_results)
        agents_dir = ensure_dir(run_dir / "agents")
        for result in agent_results:
            write_json(agents_dir / f"{result['agent']}.json", result)

        self._progress("debate", "专题 agent 已完成，开始观点会议和置信度收敛。")
        debate = _debate(agent_results, analysis_dossier.get("decision_helper", {}))
        agent_data_requests = _collect_agent_data_requests(agent_results)
        confidence_trace = _confidence_trace(agent_results, debate, framework.key)
        conversation = _agent_conversation(framework.key, mode, data_profile, broker_result, fetch_result, hypotheses, learning_context, agent_results, debate, confidence_trace)
        final_report = _final_report(code, framework.key, mode, data_profile, broker_result, fetch_result, hypotheses, learning_context, agent_results, debate, confidence_trace, agent_data_requests, memory_context, analysis_dossier)

        write_json(run_dir / "debate_council.json", debate)
        write_json(run_dir / "confidence_trace.json", confidence_trace)
        write_json(run_dir / "agent_data_requests.json", agent_data_requests)
        write_json(run_dir / "agent_conversation.json", conversation)
        (run_dir / "final_report.md").write_text(final_report, encoding="utf-8")
        (base_dir / f"multi_agent_{framework.key}.md").write_text(final_report, encoding="utf-8")
        _store_decision_memory(base_dir, data_profile["ts_code"], framework.key, mode, run_id, confidence_trace, debate)
        self._progress("done", f"多 Agent 分析完成，最终提示：{confidence_trace['final_rating']}，置信度 {confidence_trace['final_confidence']}。")

        return {
            "ok": True,
            "ts_code": data_profile["ts_code"],
            "analysis_type": framework.key,
            "analysis_label": framework.label,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "final_report_path": str(run_dir / "final_report.md"),
            "latest_report_path": str(base_dir / f"multi_agent_{framework.key}.md"),
            "answer": final_report,
            "rating_hint": confidence_trace["final_rating"],
            "confidence": confidence_trace["final_confidence"],
            "agent_conversation": conversation,
            "agent_results": agent_results,
            "learning_context": learning_context,
            "decision_memory": memory_context,
            "data_requests": broker_result,
            "agent_data_requests": agent_data_requests,
            "fetch_result": fetch_result,
            "agent_runs": list_agent_runs(code, framework.key),
        }

    def _progress(self, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
        if not self.progress_callback:
            return
        self.progress_callback({"time": timestamp(), "stage": stage, "message": message, "details": details or {}})

    def _build_learning_context(self, full_data: dict[str, Any], analysis_type: str, run_dir: Path) -> dict[str, Any]:
        try:
            context = build_similarity_learning(full_data, analysis_type)
            write_json(run_dir / "similarity_learning.json", context)
            distribution = context.get("outcome_distribution", {}).get("distribution", {})
            self._progress(
                "pattern_learning",
                (
                    f"历史相似走势学习完成，找到 {len(context.get('similar_cases', []))} 个相似窗口；"
                    f"结局概率：价值修复 {distribution.get('value_repair', 0)}%，"
                    f"价值陷阱 {distribution.get('value_trap', 0)}%，"
                    f"长期横盘 {distribution.get('long_flat', 0)}%。"
                ),
                {
                    "market_regime": context.get("market_regime", {}),
                    "outcome_distribution": context.get("outcome_distribution", {}),
                    "failure_case_matches": context.get("failure_case_matches", []),
                },
            )
            return context
        except Exception as exc:  # noqa: BLE001 - learning context should not block core analysis
            context = {
                "version": "phase1_euclidean_v1",
                "analysis_type": analysis_type,
                "error": str(exc),
                "similar_cases": [],
                "outcome_distribution": {
                    "sample_size": 0,
                    "distribution": {"value_repair": 0, "value_trap": 0, "long_flat": 0},
                    "uncertainty_level": "high",
                    "interpretation": "历史学习模块异常，不能形成结局概率。",
                },
                "failure_case_matches": [],
                "warnings": [f"历史学习模块执行失败：{exc}"],
            }
            write_json(run_dir / "similarity_learning.json", context)
            self._progress("pattern_learning_error", f"历史相似走势学习失败：{exc}", {"error": str(exc)})
            return context

    def _fetch_and_rebuild(
        self,
        code: str,
        approved_requests: list[dict[str, Any]],
        run_dir: Path,
        opts: MultiAgentOptions,
    ) -> dict[str, Any]:
        assert self.client is not None
        ts_code = _normalize_from_full_data_or_code(code)
        base_dir = current_dir(ts_code)
        full_data = read_json(base_dir / "full_data.json")
        datasets = full_data.setdefault("datasets", {})
        raw_dir = ensure_dir(base_dir / "raw")
        collector = StockDataCollector(self.client)
        specs = {spec.api_name: spec for spec in collector._build_specs(ts_code, *_date_range(full_data, opts))}
        fetch_results: list[dict[str, Any]] = []
        fetch_errors: list[dict[str, Any]] = []
        changed: list[str] = []

        for request in approved_requests:
            dataset = request["dataset"]
            try:
                self._progress("tushare_fetch", f"开始通过 Tushare 补抓 {dataset}。", {"dataset": dataset})
                if dataset == "sw_daily":
                    records = collector._collect_industry_daily(datasets.get("index_member_all", []), *_date_range(full_data, opts), raw_dir, fetch_errors)
                    fields = list(records[0].keys()) if records else []
                else:
                    spec = specs.get(dataset)
                    if not spec:
                        raise RuntimeError(f"没有配置 Tushare 接口映射：{dataset}")
                    result = self.client.query(spec.api_name, spec.params, spec.fields)
                    records = result.records
                    if spec.client_filter_ts_code:
                        records = [row for row in records if row.get("ts_code") == ts_code]
                    fields = result.fields
                    write_json(raw_dir / f"{dataset}.json", {"fields": fields, "records": records})
                datasets[dataset] = records
                changed.append(dataset)
                fetch_results.append({"dataset": dataset, "rows": len(records), "fields": fields})
                self._progress("tushare_fetch", f"Tushare 补抓 {dataset} 完成，返回 {len(records)} 行。", {"dataset": dataset, "rows": len(records)})
            except (TushareError, RuntimeError) as exc:
                fetch_errors.append({"dataset": dataset, "error": str(exc)})
                self._progress("tushare_fetch_error", f"Tushare 补抓 {dataset} 失败：{exc}", {"dataset": dataset, "error": str(exc)})

        if changed:
            self._progress("rebuild", f"补数完成，开始重建资料包和 {len(changed)} 个分析资料包。", {"changed_datasets": changed})
            full_data["fetch_errors"] = _merge_fetch_errors(full_data.get("fetch_errors", []), fetch_errors)
            write_json(base_dir / "full_data.json", full_data)
            dossier = build_dossier(full_data)
            write_json(base_dir / "dossier.json", dossier)
            for key, analysis_dossier in build_all_analysis_dossiers(dossier).items():
                write_json(base_dir / f"{key}_dossier.json", analysis_dossier)
            _update_metadata_after_rebuild(base_dir, full_data, changed, fetch_errors)
            self._progress("rebuild", "资料包重建完成。", {"changed_datasets": changed})

        result = {
            "enabled": True,
            "fetch_results": fetch_results,
            "fetch_errors": fetch_errors,
            "changed_datasets": changed,
            "rebuilt": bool(changed),
            "rebuilt_files": [str(base_dir / "full_data.json"), str(base_dir / "dossier.json")] if changed else [],
        }
        write_json(run_dir / "dossier_rebuild.json", result)
        return result


class LangGraphMultiAgentRunner(MultiAgentRunner):
    def run(self, code: str, options: MultiAgentOptions | None = None) -> dict[str, Any]:
        opts = options or MultiAgentOptions()
        graph = StateGraph(dict)
        graph.add_node("prepare", self._prepare_graph_state)
        graph.add_node("initial_agents", self._initial_agents_node)
        graph.add_node("critic_review", self._critic_review_node)
        graph.add_node("revised_agents", self._revised_agents_node)
        graph.add_node("finalize", self._finalize_graph_state)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "initial_agents")
        graph.add_edge("initial_agents", "critic_review")
        graph.add_edge("critic_review", "revised_agents")
        graph.add_edge("revised_agents", "finalize")
        graph.add_edge("finalize", END)
        compiled = graph.compile()
        return compiled.invoke({"code": code, "opts": opts})

    def _prepare_graph_state(self, state: dict[str, Any]) -> dict[str, Any]:
        code = _text(state["code"])
        opts: MultiAgentOptions = state["opts"]
        framework = get_analysis_framework(opts.analysis_type)
        mode = _mode_for_template(framework.key, opts.template)
        self._progress("langgraph_prepare", f"LangGraph 引擎进入 {mode['label']} 模式，准备分析 {code}。")

        if self.client and not stock_exists(code):
            self._progress("tushare_sync", "本地没有数据，开始通过 Tushare 同步基础资料包。")
            sync_stock_data(self.client, code, years=opts.years, full_history=opts.full_history)
            self._progress("tushare_sync", "基础资料包同步完成。")
        if not stock_exists(code):
            raise FileNotFoundError(f"本地还没有 {code} 的数据，请先更新本地数据。")

        base_dir = current_dir(code)
        run_id = f"{timestamp()}_{framework.key}_langgraph"
        run_dir = ensure_dir(base_dir / "agent_runs" / run_id)
        full_data = read_json(base_dir / "full_data.json")
        dossier = read_json(base_dir / "dossier.json")
        write_json(run_dir / "run_manifest.json", {**_run_manifest(code, framework.key, mode, run_id, opts), "engine": "langgraph", "data_fingerprint": _data_fingerprint(full_data)})
        data_profile = _data_profile(full_data, mode)
        write_json(run_dir / "data_profile.json", data_profile)
        write_json(run_dir / "mode_context.json", _mode_context(framework.key, mode, dossier))
        self._progress(
            "data_profile",
            f"已读取本地资料包，关键缺失 {len(data_profile.get('missing_required', []))} 个，次要缺失 {len(data_profile.get('missing_secondary', []))} 个。",
            {"missing_required": data_profile.get("missing_required", []), "missing_secondary": data_profile.get("missing_secondary", [])},
        )

        data_requests = _build_data_requests(framework.key, mode, full_data)
        broker_result = _broker_data_requests(data_requests, full_data)
        write_json(run_dir / "data_requests.json", broker_result)

        fetch_result = {"enabled": bool(opts.allow_dynamic_fetch and self.client), "fetch_results": [], "fetch_errors": [], "rebuilt": False}
        if opts.allow_dynamic_fetch and self.client and broker_result["approved_requests"]:
            fetch_result = self._fetch_and_rebuild(code, broker_result["approved_requests"], run_dir, opts)
            if fetch_result.get("rebuilt"):
                full_data = read_json(base_dir / "full_data.json")
                dossier = read_json(base_dir / "dossier.json")
                data_profile = _data_profile(full_data, mode)
                write_json(run_dir / "data_profile.json", data_profile)
        else:
            self._progress("tushare_fetch", "没有需要执行的动态补数，继续使用当前资料包。")
        write_json(run_dir / "tushare_fetch_results.json", fetch_result)

        hypotheses = _hypotheses(framework.key, mode)
        write_json(run_dir / "hypotheses.json", hypotheses)
        analysis_dossier = read_json(base_dir / f"{framework.key}_dossier.json") if (base_dir / f"{framework.key}_dossier.json").exists() else {}
        hidden_context = _hidden_condition_context(dossier, full_data)
        news_context = search_related_news(_company_identity(dossier, full_data), limit=12, days=60)
        write_json(run_dir / "hidden_condition_context.json", hidden_context)
        write_json(run_dir / "news_context.json", news_context)
        learning_context = self._build_learning_context(full_data, framework.key, run_dir)
        memory_context = _load_decision_memory(data_profile["ts_code"], base_dir)
        write_json(run_dir / "decision_memory_context.json", memory_context)
        if learning_context:
            analysis_dossier = {**analysis_dossier, "learning_context": learning_context}
        analysis_dossier = {**analysis_dossier, "hidden_condition_context": hidden_context, "news_context": news_context}
        if memory_context.get("entries"):
            analysis_dossier = {**analysis_dossier, "decision_memory": memory_context}
        return {
            **state,
            "engine": "langgraph",
            "framework": framework,
            "mode": mode,
            "base_dir": base_dir,
            "run_id": run_id,
            "run_dir": run_dir,
            "full_data": full_data,
            "dossier": dossier,
            "data_profile": data_profile,
            "broker_result": broker_result,
            "fetch_result": fetch_result,
            "hypotheses": hypotheses,
            "analysis_dossier": analysis_dossier,
            "learning_context": learning_context,
            "memory_context": memory_context,
        }

    def _initial_agents_node(self, state: dict[str, Any]) -> dict[str, Any]:
        framework = state["framework"]
        opts: MultiAgentOptions = state["opts"]
        self._progress("initial_agents", "开始第一轮专题 agent 分析。")
        agent_results = _run_staged_specialists(
            framework.key,
            state["mode"],
            state["dossier"],
            state["analysis_dossier"],
            state["full_data"],
            state["broker_result"],
            state["fetch_result"],
            self.llm_client if opts.use_llm_agents else None,
            self.progress_callback,
            opts.max_parallel_agents,
            state["run_dir"],
            opts.reuse_agent_cache,
        )
        agent_results = _validate_agent_results(agent_results)
        agents_dir = ensure_dir(state["run_dir"] / "agents" / "initial")
        for result in agent_results:
            write_json(agents_dir / f"{result['agent']}.json", result)
        return {**state, "initial_agent_results": agent_results, "agent_results": agent_results}

    def _critic_review_node(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state["mode"].get("enable_critic_review", True):
            review = {
                "findings": [],
                "overall_risk": "low",
                "should_revise": False,
                "summary": "当前分析模式使用轻量流程，跳过反方审计。",
                "skipped": True,
            }
            write_json(state["run_dir"] / "critic_review.json", review)
            self._progress("critic_review", "当前模式跳过反方审计，直接进入最终汇总。")
            return {**state, "critic_review": review}
        self._progress("critic_review", "开始反方审计：检查证据链、数据缺口和评分一致性。")
        review = _critic_review(
            self.llm_client,
            state["framework"].key,
            state["mode"],
            state["dossier"],
            state["analysis_dossier"],
            state["data_profile"],
            state["broker_result"],
            state["fetch_result"],
            state["initial_agent_results"],
        )
        write_json(state["run_dir"] / "critic_review.json", review)
        self._progress("critic_review", f"反方审计完成，发现 {len(review.get('findings', []))} 个问题。", {"overall_risk": review.get("overall_risk")})
        return {**state, "critic_review": review}

    def _revised_agents_node(self, state: dict[str, Any]) -> dict[str, Any]:
        review = state.get("critic_review") or {}
        if not state["mode"].get("enable_revision_round", True):
            self._progress("revised_agents", "当前模式关闭二轮修正，沿用第一轮结果进入最终汇总。")
            return state
        if not review.get("should_revise", True):
            return state
        framework = state["framework"]
        opts: MultiAgentOptions = state["opts"]
        self._progress("revised_agents", "将反方审计意见写入上下文，开始第二轮修正分析。")
        revised_dossier = {**state["analysis_dossier"], "critic_context": review}
        force_agents = _agents_forced_by_critic(review)
        revised_results = _run_staged_specialists(
            framework.key,
            state["mode"],
            state["dossier"],
            revised_dossier,
            state["full_data"],
            state["broker_result"],
            state["fetch_result"],
            self.llm_client if opts.use_llm_agents else None,
            self.progress_callback,
            opts.max_parallel_agents,
            state["run_dir"],
            opts.reuse_agent_cache,
            force_agents,
            state.get("initial_agent_results", []),
        )
        revised_results = _validate_agent_results(_merge_revisions(revised_results, review))
        agents_dir = ensure_dir(state["run_dir"] / "agents" / "revised")
        for result in revised_results:
            write_json(agents_dir / f"{result['agent']}.json", result)
        return {**state, "analysis_dossier": revised_dossier, "agent_results": revised_results}

    def _finalize_graph_state(self, state: dict[str, Any]) -> dict[str, Any]:
        framework = state["framework"]
        agent_results = state["agent_results"]
        debate = _debate(agent_results, state["analysis_dossier"].get("decision_helper", {}))
        agent_data_requests = _collect_agent_data_requests(agent_results)
        confidence_trace = _confidence_trace(agent_results, debate, framework.key)
        conversation = _agent_conversation(
            framework.key,
            state["mode"],
            state["data_profile"],
            state["broker_result"],
            state["fetch_result"],
            state["hypotheses"],
            state["learning_context"],
            agent_results,
            debate,
            confidence_trace,
        )
        final_report = _final_report(
            state["code"],
            framework.key,
            state["mode"],
            state["data_profile"],
            state["broker_result"],
            state["fetch_result"],
            state["hypotheses"],
            state["learning_context"],
            agent_results,
            debate,
            confidence_trace,
            agent_data_requests,
            state.get("memory_context", {}),
            state["analysis_dossier"],
        )
        write_json(state["run_dir"] / "debate_council.json", debate)
        write_json(state["run_dir"] / "confidence_trace.json", confidence_trace)
        write_json(state["run_dir"] / "agent_data_requests.json", agent_data_requests)
        write_json(state["run_dir"] / "agent_conversation.json", conversation)
        (state["run_dir"] / "final_report.md").write_text(final_report, encoding="utf-8")
        (state["base_dir"] / f"multi_agent_{framework.key}.md").write_text(final_report, encoding="utf-8")
        _store_decision_memory(state["base_dir"], state["data_profile"]["ts_code"], framework.key, state["mode"], state["run_id"], confidence_trace, debate)
        self._progress("done", f"LangGraph 多 Agent 分析完成，最终提示：{confidence_trace['final_rating']}，置信度 {confidence_trace['final_confidence']}。")
        return {
            "ok": True,
            "engine": "langgraph",
            "template": state["mode"].get("template", "native"),
            "template_label": state["mode"].get("template_label", ""),
            "estimated_llm_calls": state["mode"].get("estimated_llm_calls", 0),
            "agent_max_tokens": state["mode"].get("agent_max_tokens"),
            "critic_max_tokens": state["mode"].get("critic_max_tokens"),
            "context_profile": state["mode"].get("context_profile", "focused"),
            "ts_code": state["data_profile"]["ts_code"],
            "analysis_type": framework.key,
            "analysis_label": framework.label,
            "run_id": state["run_id"],
            "run_dir": str(state["run_dir"]),
            "final_report_path": str(state["run_dir"] / "final_report.md"),
            "latest_report_path": str(state["base_dir"] / f"multi_agent_{framework.key}.md"),
            "answer": final_report,
            "rating_hint": confidence_trace["final_rating"],
            "confidence": confidence_trace["final_confidence"],
            "agent_conversation": conversation,
            "learning_context": state["learning_context"],
            "decision_memory": state.get("memory_context", {}),
            "critic_review": state.get("critic_review", {}),
            "agent_results": agent_results,
            "initial_agent_results": state.get("initial_agent_results", []),
            "data_requests": state["broker_result"],
            "agent_data_requests": agent_data_requests,
            "fetch_result": state["fetch_result"],
            "agent_runs": list_agent_runs(state["code"], framework.key),
        }


def list_agent_runs(code: str, analysis_type: str | None = None) -> list[dict[str, str]]:
    root = current_dir(code) / "agent_runs"
    if not root.exists():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        manifest_path = path / "run_manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        run_type = manifest.get("analysis_type") or _analysis_type_from_run_id(path.name)
        if analysis_type and run_type != analysis_type:
            continue
        report_path = path / "final_report.md"
        items.append(
            {
                "run_id": path.name,
                "analysis_type": run_type,
                "analysis_label": MODE_CONFIG.get(run_type, {}).get("label", run_type),
                "engine": manifest.get("engine", "legacy"),
                "template": manifest.get("template", "native"),
                "template_label": manifest.get("template_label", ""),
                "created_at": manifest.get("created_at", path.name[:15]),
                "run_dir": str(path),
                "final_report_path": str(report_path),
            }
        )
    return items


def read_agent_run(code: str, run_id: str) -> dict[str, Any]:
    run_dir = current_dir(code) / "agent_runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"找不到多 Agent 运行记录：{run_id}")
    report_path = run_dir / "final_report.md"
    if not report_path.exists():
        raise FileNotFoundError(f"多 Agent 运行记录缺少最终报告：{run_id}")
    manifest = read_json(run_dir / "run_manifest.json") if (run_dir / "run_manifest.json").exists() else {}
    conversation_path = run_dir / "agent_conversation.json"
    agent_requests_path = run_dir / "agent_data_requests.json"
    confidence_path = run_dir / "confidence_trace.json"
    confidence_trace = read_json(confidence_path) if confidence_path.exists() else {}
    agent_results = _read_agent_results_from_run(run_dir)
    analysis_type = _text(manifest.get("analysis_type")) or next((key for key in MODE_CONFIG if run_id.endswith(f"_{key}")), "")
    try:
        analysis_label = get_analysis_framework(analysis_type).label
    except Exception:
        analysis_label = MODE_CONFIG.get(analysis_type, {}).get("label") or analysis_type or "多 Agent 分析"
    return {
        "ok": True,
        "ts_code": _text(manifest.get("ts_code")) or code,
        "analysis_type": analysis_type,
        "analysis_label": analysis_label,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest": manifest,
        "agent_results": agent_results,
        "agent_conversation": read_json(conversation_path) if conversation_path.exists() else [],
        "agent_data_requests": read_json(agent_requests_path) if agent_requests_path.exists() else [],
        "learning_context": read_json(run_dir / "similarity_learning.json") if (run_dir / "similarity_learning.json").exists() else {},
        "rating_hint": confidence_trace.get("final_rating"),
        "confidence": confidence_trace.get("final_confidence"),
        "answer": report_path.read_text(encoding="utf-8"),
        "final_report_path": str(report_path),
    }


def _read_agent_results_from_run(run_dir: Path) -> list[dict[str, Any]]:
    for folder_name in ("revised", "initial"):
        agents_dir = run_dir / "agents" / folder_name
        if not agents_dir.exists():
            continue
        items: list[dict[str, Any]] = []
        for path in sorted(agents_dir.glob("*.json")):
            try:
                item = read_json(path)
            except Exception:
                continue
            if isinstance(item, dict):
                item.setdefault("agent", path.stem)
                if item.get("agent") == "moat_governance_agent":
                    item["domain_label"] = _moat_governance_label(item)
                items.append(_calibrate_agent_confidence(item))
        if items:
            return items
    return []


def _run_manifest(code: str, analysis_type: str, mode: dict[str, Any], run_id: str, opts: MultiAgentOptions) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "ts_code": _normalize_from_full_data_or_code(code),
        "analysis_type": analysis_type,
        "analysis_label": mode["label"],
        "created_at": timestamp(),
        "time_horizon": mode["time_horizon"],
        "template": mode.get("template", opts.template),
        "template_label": mode.get("template_label", ""),
        "agents": mode["agents"],
        "allow_dynamic_fetch": opts.allow_dynamic_fetch,
        "use_llm_agents": opts.use_llm_agents,
        "reuse_agent_cache": opts.reuse_agent_cache,
        "max_parallel_agents": opts.max_parallel_agents,
        "max_fetch_rounds": mode["max_fetch_rounds"],
        "estimated_llm_calls": mode.get("estimated_llm_calls", 0),
        "agent_max_tokens": mode.get("agent_max_tokens"),
        "critic_max_tokens": mode.get("critic_max_tokens"),
        "enable_critic_review": mode.get("enable_critic_review", True),
        "enable_revision_round": mode.get("enable_revision_round", True),
        "context_profile": mode.get("context_profile", "focused"),
    }


def _write_run_manifest(run_dir: Path, code: str, analysis_type: str, mode: dict[str, Any], run_id: str, opts: MultiAgentOptions, full_data: dict[str, Any]) -> None:
    write_json(run_dir / "run_manifest.json", {**_run_manifest(code, analysis_type, mode, run_id, opts), "data_fingerprint": _data_fingerprint(full_data)})


def _data_fingerprint(full_data: dict[str, Any]) -> str:
    datasets = full_data.get("datasets", {})
    payload = {
        "ts_code": full_data.get("ts_code"),
        "date_range": full_data.get("date_range", {}),
        "dataset_rows": {name: len(rows) for name, rows in sorted(datasets.items())},
        "latest_rows": {
            name: rows[:3]
            for name, rows in sorted(datasets.items())
            if isinstance(rows, list) and rows
        },
        "fetch_errors": full_data.get("fetch_errors", []),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _company_identity(dossier: dict[str, Any], full_data: dict[str, Any]) -> dict[str, Any]:
    company = dossier.get("company", {})
    stock_basic = company.get("stock_basic") or {}
    stock_company = company.get("stock_company") or {}
    industry_rows = dossier.get("industry", {}).get("sw_classification") or full_data.get("datasets", {}).get("index_member_all", [])
    industry = ""
    if industry_rows and isinstance(industry_rows, list):
        industry = _text(industry_rows[0].get("industry_name") or industry_rows[0].get("index_name") or industry_rows[0].get("l2_name") or industry_rows[0].get("l1_name"))
    return {
        "ts_code": stock_basic.get("ts_code") or full_data.get("ts_code"),
        "symbol": stock_basic.get("symbol"),
        "name": stock_basic.get("name") or stock_company.get("name") or stock_company.get("com_name"),
        "industry": stock_basic.get("industry") or industry,
        "area": stock_basic.get("area") or stock_company.get("province"),
    }


def _hidden_condition_context(dossier: dict[str, Any], full_data: dict[str, Any]) -> dict[str, Any]:
    company = _company_identity(dossier, full_data)
    name = _text(company.get("name"))
    industry = _text(company.get("industry"))
    focus = [
        "公司是否有同行短期难以追赶的成本曲线、技术、渠道、品牌、牌照或组织能力。",
        "管理层是否长期优秀，是否存在接班风险、关键人物退休或控制权变化。",
        "优势是否能被财报间接验证，例如毛利率、费用率、ROE、现金流、产能利用率和同行差异。",
        "如果使用资料包外变量，必须写成待验证假设并生成数据请求。",
    ]
    if "牧原" in name or "养殖" in industry or "农业" in industry:
        focus.extend(
            [
                "重点核验单头猪养殖成本是否真的领先，以及领先来自育种、饲料、疫病控制、规模化还是管理系统。",
                "重点核验秦英林相关管理层与接班叙事：退休传闻、家族持股、治理结构和关键人风险。",
                "重点核验能繁母猪、猪肉现货、远期合约、饲料价格、疫病和天气对周期位置的影响。",
            ]
        )
    return {
        "company": company,
        "focus_questions": focus,
        "suggested_external_datasets": [
            {"dataset": "peer_cost_curve", "need": "同行成本曲线、单位成本、毛利率和产能效率对比", "priority": "high"},
            {"dataset": "management_succession", "need": "管理层变动、接班安排、控制权和关键人风险新闻", "priority": "high"},
            {"dataset": "industry_cycle_external", "need": "行业价格、库存、期货结构、供需和天气扰动", "priority": "medium"},
        ],
    }


def _load_decision_memory(ts_code: str, base_dir: Path, same_limit: int = 5, cross_limit: int = 3) -> dict[str, Any]:
    same_entries = _read_jsonl(base_dir / "decision_memory.jsonl")
    global_entries = _read_jsonl(LOCAL_DATA_DIR / "agent_memory" / "global_decisions.jsonl")
    same = [item for item in reversed(same_entries) if item.get("ts_code") == ts_code][:same_limit]
    cross = [item for item in reversed(global_entries) if item.get("ts_code") != ts_code][:cross_limit]
    entries = same + cross
    lessons = []
    for item in entries:
        lessons.append(
            {
                "scope": "same_stock" if item.get("ts_code") == ts_code else "cross_stock",
                "ts_code": item.get("ts_code"),
                "analysis_type": item.get("analysis_type"),
                "rating_hint": item.get("rating_hint"),
                "confidence": item.get("confidence"),
                "summary": item.get("summary"),
                "created_at": item.get("created_at"),
            }
        )
    return {
        "enabled": True,
        "same_stock_count": len(same),
        "cross_stock_count": len(cross),
        "entries": lessons,
        "instruction": "参考过去同股和跨股票结论，但不要机械复用；若新证据推翻旧判断，应明确说明调整原因。",
    }


def _store_decision_memory(
    base_dir: Path,
    ts_code: str,
    analysis_type: str,
    mode: dict[str, Any],
    run_id: str,
    confidence_trace: dict[str, Any],
    debate: dict[str, Any],
) -> None:
    entry = {
        "created_at": timestamp(),
        "ts_code": ts_code,
        "analysis_type": analysis_type,
        "template": mode.get("template", "native"),
        "template_label": mode.get("template_label", ""),
        "run_id": run_id,
        "rating_hint": confidence_trace.get("final_rating"),
        "confidence": confidence_trace.get("final_confidence"),
        "directional_score": confidence_trace.get("directional_score"),
        "vote_summary": confidence_trace.get("vote_summary", {}),
        "summary": _decision_memory_summary(debate, confidence_trace),
        "status": "pending_outcome_review",
    }
    _append_jsonl(base_dir / "decision_memory.jsonl", entry)
    _append_jsonl(LOCAL_DATA_DIR / "agent_memory" / "global_decisions.jsonl", entry)


def _decision_memory_summary(debate: dict[str, Any], confidence_trace: dict[str, Any]) -> str:
    agreements = [_text(item) for item in (debate.get("agreements") or [])[:2]]
    conflicts = [_text(item) for item in (debate.get("conflicts") or [])[:2]]
    parts = [f"最终提示：{_text(confidence_trace.get('final_rating'))}，置信度 {confidence_trace.get('final_confidence')}。"]
    if agreements:
        parts.append("主要共识：" + "；".join(agreements))
    if conflicts:
        parts.append("主要分歧：" + "；".join(conflicts))
    return "".join(parts)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except json.JSONDecodeError:
            continue
    return rows


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")


def _data_profile(full_data: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    datasets = full_data.get("datasets", {})
    rows = {name: len(records) for name, records in datasets.items()}
    missing_required = [name for name in mode["required_datasets"] if not rows.get(name)]
    missing_secondary = [name for name in mode["secondary_datasets"] if not rows.get(name)]
    return {
        "ts_code": full_data.get("ts_code"),
        "date_range": full_data.get("date_range", {}),
        "dataset_rows": rows,
        "missing_required": missing_required,
        "missing_secondary": missing_secondary,
        "fetch_errors": full_data.get("fetch_errors", []),
    }


def _mode_context(analysis_type: str, mode: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_type": analysis_type,
        "time_horizon": mode["time_horizon"],
        "data_priorities": {"required": mode["required_datasets"], "secondary": mode["secondary_datasets"]},
        "company": dossier.get("company", {}),
        "data_quality": dossier.get("data_quality", {}),
    }


def _build_data_requests(analysis_type: str, mode: dict[str, Any], full_data: dict[str, Any]) -> list[dict[str, Any]]:
    datasets = full_data.get("datasets", {})
    requests = []
    for dataset in mode["required_datasets"]:
        if not datasets.get(dataset):
            requests.append(_data_request(analysis_type, dataset, "high", True))
    for dataset in mode["secondary_datasets"]:
        if not datasets.get(dataset):
            requests.append(_data_request(analysis_type, dataset, "medium", False))
    return requests


def _data_request(analysis_type: str, dataset: str, priority: str, blocking: bool) -> dict[str, Any]:
    return {
        "request_id": f"req_{analysis_type}_{dataset}",
        "requested_by": "data_profiler",
        "mode": analysis_type,
        "need": DATASET_NEEDS.get(dataset, dataset),
        "dataset": dataset,
        "fields": [],
        "date_range": {"source": "current_data_range"},
        "priority": priority,
        "blocking": blocking,
    }


def _broker_data_requests(requests: list[dict[str, Any]], full_data: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    approved = []
    rejected = []
    for request in requests:
        dataset = request["dataset"]
        if full_data.get("datasets", {}).get(dataset):
            rejected.append({**request, "reason": "本地数据已存在"})
            continue
        if dataset in seen:
            rejected.append({**request, "reason": "重复请求"})
            continue
        seen.add(dataset)
        approved.append(request)
    return {
        "approved_requests": approved,
        "rejected_requests": rejected,
        "request_deduplication": {"input": len(requests), "approved": len(approved), "rejected": len(rejected)},
        "tushare_jobs": [{"dataset": request["dataset"], "priority": request["priority"], "blocking": request["blocking"]} for request in approved],
    }


def _hypotheses(analysis_type: str, mode: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "oversold_rebound": [
            "H1: 股票已经出现阶段性超跌，但反弹尚需资金和成交确认。",
            "H2: 行业共振和公告催化可能提供短线修复动力。",
            "H3: 下跌可能来自基本面恶化，需警惕下跌中继。",
        ],
        "value_speculation": [
            "H1: 公司存在一定价值底线，可进一步评估交易赔率。",
            "H2: 催化和资金确认决定是否具备中线窗口。",
            "H3: 低估可能来自基本面恶化，需排除价值陷阱。",
        ],
        "value_quality": [
            "H1: 公司可能具备长期复利质量，需验证盈利韧性和现金流。",
            "H2: 公司质量一般但估值可能给出等待价值。",
            "H3: 低估可能来自增长失速或治理风险。",
        ],
        "value_dividend": [
            "H1: 当前估值和分红可能具备防御价值。",
            "H2: 分红是否可持续取决于利润和现金流覆盖。",
            "H3: 高股息可能来自价值陷阱，需要审计负债和治理风险。",
        ],
    }
    return {
        "mode": analysis_type,
        "time_horizon": mode["time_horizon"],
        "hypotheses": mapping.get(analysis_type, []),
        "initial_confidence": 0.5,
    }


def _agent_cache_for_current_data(
    full_data: dict[str, Any],
    analysis_type: str,
    mode: dict[str, Any],
    current_run_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    ts_code = _text(full_data.get("ts_code"))
    if not ts_code:
        return {}
    root = current_dir(ts_code) / "agent_runs"
    if not root.exists():
        return {}
    current_fingerprint = _data_fingerprint(full_data)
    template = _text(mode.get("template") or "native")
    cached: dict[str, dict[str, Any]] = {}
    current_run_dir = current_run_dir.resolve() if current_run_dir else None
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        if current_run_dir and path.resolve() == current_run_dir:
            continue
        manifest_path = path / "run_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = read_json(manifest_path)
        except Exception:
            continue
        if manifest.get("analysis_type") != analysis_type:
            continue
        if _text(manifest.get("template") or "native") != template:
            continue
        if manifest.get("data_fingerprint") != current_fingerprint:
            continue
        for agents_dir in (path / "agents" / "revised", path / "agents" / "initial", path / "agents"):
            if not agents_dir.exists():
                continue
            for agent_path in sorted(agents_dir.glob("*.json")):
                if agent_path.stem in cached:
                    continue
                try:
                    item = read_json(agent_path)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item.setdefault("agent", agent_path.stem)
                item["cached_from_run_id"] = path.name
                item["cached_from_path"] = str(agent_path)
                item["cache_reason"] = "same_data_fingerprint"
                cached[_text(item.get("agent")) or agent_path.stem] = item
            if cached:
                break
    return cached


def _agents_forced_by_critic(review: dict[str, Any]) -> set[str]:
    agents = set(AGENT_SPECS)
    forced: set[str] = set()
    for value in review.get("force_rerun_agents", []) if isinstance(review.get("force_rerun_agents"), list) else []:
        agent = _text(value)
        if agent in agents:
            forced.add(agent)
    for finding in review.get("findings", []):
        if not isinstance(finding, dict):
            continue
        agent = _text(finding.get("agent"))
        if agent in agents:
            forced.add(agent)
    return forced


def _mark_cached_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    item = dict(result)
    item["cached_agent_result"] = True
    item.setdefault("cache_reason", "same_data_fingerprint")
    item.setdefault("source", result.get("source") or "cached_agent")
    return item


def _run_staged_specialists(
    analysis_type: str,
    mode: dict[str, Any],
    dossier: dict[str, Any],
    analysis_dossier: dict[str, Any],
    full_data: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    llm_client: DeepSeekClient | None = None,
    progress_callback: ProgressCallback | None = None,
    max_parallel_agents: int = 8,
    run_dir: Path | None = None,
    reuse_agent_cache: bool = True,
    force_agents: set[str] | None = None,
    fallback_agent_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cached_agent_results = _agent_cache_for_current_data(full_data, analysis_type, mode, run_dir) if reuse_agent_cache else {}
    if cached_agent_results:
        _emit_progress(
            progress_callback,
            "agent_cache_ready",
            f"发现同数据版本缓存，可复用 {len(cached_agent_results)} 个 agent 结果。",
            {"agents": sorted(cached_agent_results)},
        )
    fallback_by_agent = {
        _text(item.get("agent")): item
        for item in (fallback_agent_results or [])
        if isinstance(item, dict) and item.get("agent")
    }
    stages = [(stage, agents) for stage, agents in _template_execution_stages(mode) if agents]
    if len(stages) <= 1:
        return _run_specialists(
            analysis_type,
            mode,
            dossier,
            analysis_dossier,
            full_data,
            broker_result,
            fetch_result,
            llm_client,
            progress_callback,
            max_parallel_agents,
            cached_agent_results,
            force_agents,
            fallback_by_agent,
        )

    all_results: list[dict[str, Any]] = []
    staged_dossier = dict(analysis_dossier)
    for stage_name, agents in stages:
        _emit_progress(
            progress_callback,
            f"agent_stage_{stage_name}",
            f"开始阶段：{_stage_label(stage_name)}，运行 {len(agents)} 个 agent。",
            {"stage": stage_name, "agents": agents},
        )
        stage_mode = {**mode, "agents": agents}
        stage_results = _run_specialists(
            analysis_type,
            stage_mode,
            dossier,
            {**staged_dossier, "prior_agent_results": all_results, "current_stage": stage_name},
            full_data,
            broker_result,
            fetch_result,
            llm_client,
            progress_callback,
            min(max_parallel_agents, max(1, len(agents))),
            cached_agent_results,
            force_agents,
            fallback_by_agent,
        )
        for result in stage_results:
            result["stage"] = stage_name
        all_results.extend(stage_results)
        staged_dossier["prior_agent_results"] = all_results
        _emit_progress(
            progress_callback,
            f"agent_stage_{stage_name}_done",
            f"{_stage_label(stage_name)}完成，累计 {len(all_results)} 个 agent 结果。",
            {"stage": stage_name, "completed": len(stage_results)},
        )
    return all_results


def _template_execution_stages(mode: dict[str, Any]) -> list[tuple[str, list[str]]]:
    template = mode.get("template")
    agents = list(mode.get("agents") or [])
    if template == "tradingagents":
        return [
            ("analysts", [agent for agent in agents if agent in {"market_analyst", "news_analyst", "fundamental_analyst", "sentiment_analyst", "moat_governance_agent"}]),
            ("bull_bear_debate", [agent for agent in agents if agent in {"bull_researcher", "bear_researcher"}]),
            ("research_decision", [agent for agent in agents if agent in {"research_manager", "trader"}]),
            ("risk_debate", [agent for agent in agents if agent in {"aggressive_risk_analyst", "neutral_risk_analyst", "conservative_risk_analyst"}]),
            ("portfolio_decision", [agent for agent in agents if agent in {"portfolio_manager"}]),
        ]
    if template == "finrobot":
        return [
            ("company_context", [agent for agent in agents if agent in {"company_overview_agent", "news_summary_agent"}]),
            ("research_sections", [agent for agent in agents if agent in {"investment_update_agent", "valuation_overview_agent", "competitor_analysis_agent"}]),
            ("risk_and_takeaways", [agent for agent in agents if agent in {"risk_section_agent", "major_takeaways_agent"}]),
        ]
    return [("single_pass", agents)]


def _stage_label(stage: str) -> str:
    return {
        "analysts": "资料分析师阶段",
        "bull_bear_debate": "多空辩论阶段",
        "research_decision": "研究经理与交易员阶段",
        "risk_debate": "风控辩论阶段",
        "portfolio_decision": "组合经理裁决阶段",
        "company_context": "公司与新闻背景阶段",
        "research_sections": "研报章节阶段",
        "risk_and_takeaways": "风险与核心结论阶段",
        "single_pass": "专题并行阶段",
    }.get(stage, stage)


def _estimated_llm_calls(mode: dict[str, Any]) -> int:
    agent_count = len(mode.get("agents") or [])
    if not agent_count:
        return 0
    calls = agent_count
    if mode.get("enable_critic_review", True):
        calls += 1
    if mode.get("enable_critic_review", True) and mode.get("enable_revision_round", True):
        calls += agent_count
    return calls


def _run_specialists(
    analysis_type: str,
    mode: dict[str, Any],
    dossier: dict[str, Any],
    analysis_dossier: dict[str, Any],
    full_data: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    llm_client: DeepSeekClient | None = None,
    progress_callback: ProgressCallback | None = None,
    max_parallel_agents: int = 8,
    cached_agent_results: dict[str, dict[str, Any]] | None = None,
    force_agents: set[str] | None = None,
    fallback_by_agent: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    decision = analysis_dossier.get("decision_helper", {})
    base_scores = decision.get("score_summary", {})
    risk_flags = analysis_dossier.get("risk_flags", [])
    data_profile = _data_profile(full_data, mode)
    agents = list(mode["agents"])
    cached_agent_results = cached_agent_results or {}
    force_agents = force_agents or set()
    fallback_by_agent = fallback_by_agent or {}
    worker_count = max(1, min(len(agents), max_parallel_agents or 1))
    _emit_progress(
        progress_callback,
        "agent_pool_start",
        f"开始并行运行 {len(agents)} 个专题 agent，并发数 {worker_count}。",
        {"agents": agents, "max_parallel_agents": worker_count},
    )

    def run_one(index: int, agent: str) -> tuple[int, dict[str, Any]]:
        spec = AGENT_SPECS.get(agent, {"role": agent})
        if agent not in force_agents:
            cached = cached_agent_results.get(agent) or fallback_by_agent.get(agent)
            if cached:
                result = _mark_cached_agent_result(cached)
                _emit_progress(
                    progress_callback,
                    "agent_cache_hit",
                    f"{spec.get('role', agent)} 数据未变化，复用历史结果。",
                    {"agent": agent, "cached_from_run_id": result.get("cached_from_run_id"), "cache_reason": result.get("cache_reason")},
                )
                return index, result
        elif fallback_by_agent.get(agent) or cached_agent_results.get(agent):
            _emit_progress(
                progress_callback,
                "agent_cache_bypass",
                f"{spec.get('role', agent)} 被反方审计点名，跳过缓存并重新运行。",
                {"agent": agent},
            )
        source = "DeepSeek 专家" if llm_client else "规则回退"
        _emit_progress(progress_callback, "agent_start", f"开始运行 {spec.get('role', agent)}（{source}）。", {"agent": agent, "source": source})
        fallback = _agent_result(agent, analysis_type, base_scores, risk_flags, data_profile, broker_result, fetch_result, decision)
        try:
            if llm_client:
                result = _llm_agent_result(llm_client, agent, analysis_type, mode, dossier, analysis_dossier, data_profile, broker_result, fetch_result, fallback)
            else:
                result = _apply_agent_guardrails(fallback, analysis_type, dossier, analysis_dossier)
        except Exception as exc:  # noqa: BLE001 - keep the whole council alive
            result = _apply_agent_guardrails(
                {
                    **fallback,
                    "llm_error": str(exc),
                    "reasoning_summary": f"{fallback['reasoning_summary']} 专题 agent 执行异常，已回退到规则化结果。",
                },
                analysis_type,
                dossier,
                analysis_dossier,
            )
        if result.get("llm_error"):
            _emit_progress(progress_callback, "agent_error", f"{spec.get('role', agent)} 调用失败，已回退：{result['llm_error']}", {"agent": agent, "error": result["llm_error"]})
        else:
            _emit_progress(progress_callback, "agent_done", f"{spec.get('role', agent)} 完成，评级提示：{result.get('rating_hint')}，置信度 {result.get('confidence')}。", {"agent": agent, "rating_hint": result.get("rating_hint"), "confidence": result.get("confidence")})
        return index, result

    ordered: list[dict[str, Any] | None] = [None] * len(agents)
    if worker_count == 1:
        for index, agent in enumerate(agents):
            result_index, result = run_one(index, agent)
            ordered[result_index] = result
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(run_one, index, agent) for index, agent in enumerate(agents)]
            for future in as_completed(futures):
                result_index, result = future.result()
                ordered[result_index] = result
    _emit_progress(progress_callback, "agent_pool_done", "专题 agent 并行运行完成，进入观点会议。", {"agents": agents})
    return [item for item in ordered if item is not None]


def _validate_agent_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for result in results:
        try:
            item = AgentVerdict.model_validate(result).model_dump()
            item.update({key: value for key, value in result.items() if key not in item})
            validated.append(_calibrate_agent_confidence(item))
        except ValidationError as exc:
            fallback = dict(result)
            fallback["schema_error"] = str(exc)
            fallback["confidence"] = _clamp_float(_num(fallback.get("confidence")) or 0.4)
            fallback.setdefault("counter_evidence", []).append(
                {"claim": "agent 输出结构未完全通过校验，结论置信度需要折扣。", "data_path": "agent.schema", "strength": "high"}
            )
            validated.append(_calibrate_agent_confidence(fallback))
    return validated


def _calibrate_agent_confidence(result: dict[str, Any]) -> dict[str, Any]:
    item = dict(result)
    llm_confidence = _clamp_float(_num(item.get("llm_confidence") if item.get("llm_confidence") is not None else item.get("confidence")) or 0.5)
    direction = _rating_direction(_text(item.get("rating_hint")))
    findings = item.get("key_findings") or item.get("findings") or []
    counters = item.get("counter_evidence") or []
    data_requests = item.get("data_requests") or []
    scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}

    opinion_strength = _opinion_strength(direction, scores, item.get("agent"))
    evidence_confidence = _evidence_confidence(findings, counters, data_requests, scores, item)
    system_confidence = _clamp_float(evidence_confidence * 0.66 + opinion_strength * 0.26 + llm_confidence * 0.08)

    item["llm_confidence"] = llm_confidence
    item["opinion_strength"] = round(opinion_strength, 3)
    item["evidence_confidence"] = round(evidence_confidence, 3)
    item["system_confidence"] = round(system_confidence, 3)
    item["confidence"] = item["system_confidence"]
    item["confidence_components"] = {
        "llm_confidence": item["llm_confidence"],
        "opinion_strength": item["opinion_strength"],
        "evidence_confidence": item["evidence_confidence"],
        "system_confidence": item["system_confidence"],
    }
    return item


def _opinion_strength(direction: dict[str, Any], scores: dict[str, Any], agent: str | None = None) -> float:
    score = abs(float(direction.get("score") or 0))
    base = 0.38 if score == 0 else 0.58 + min(0.28, score * 0.14)
    numeric_scores = [_num(value) for value in scores.values()]
    numeric_scores = [value for value in numeric_scores if value is not None]
    if numeric_scores:
        extremity = sum(abs(value - 3.0) for value in numeric_scores) / len(numeric_scores)
        base += min(0.16, extremity * 0.08)
    if agent == "moat_governance_agent":
        base = max(base, 0.48)
    return _clamp_float(base, 0.18, 0.94)


def _evidence_confidence(
    findings: list[Any],
    counters: list[Any],
    data_requests: list[Any],
    scores: dict[str, Any],
    result: dict[str, Any],
) -> float:
    confidence = 0.38
    confidence += min(0.36, sum(_claim_strength_value(item) for item in findings))
    confidence -= min(0.28, sum(_claim_strength_value(item) * 0.85 for item in counters))
    confidence -= min(0.22, sum(_request_penalty(item) for item in data_requests))
    if result.get("schema_error"):
        confidence -= 0.16
    if result.get("llm_error"):
        confidence -= 0.10
    if scores:
        numeric_scores = [_num(value) for value in scores.values()]
        numeric_scores = [value for value in numeric_scores if value is not None]
        if numeric_scores:
            confidence += min(0.14, (sum(abs(value - 3.0) for value in numeric_scores) / len(numeric_scores)) * 0.07)
    return _clamp_float(confidence, 0.12, 0.92)


def _claim_strength_value(item: Any) -> float:
    if not isinstance(item, dict):
        return 0.04
    strength = _text(item.get("strength")).lower()
    if strength == "high":
        return 0.16
    if strength == "low":
        return 0.05
    return 0.10


def _request_penalty(item: Any) -> float:
    if not isinstance(item, dict):
        return 0.02
    penalty = 0.015
    if item.get("priority") == "high":
        penalty += 0.025
    if item.get("blocking"):
        penalty += 0.08
    return penalty


def _critic_review(
    llm_client: DeepSeekClient | None,
    analysis_type: str,
    mode: dict[str, Any],
    dossier: dict[str, Any],
    analysis_dossier: dict[str, Any],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    agent_results: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback = _fallback_critic_review(data_profile, broker_result, fetch_result, agent_results)
    if not llm_client:
        return fallback
    profile = _text(mode.get("context_profile") or "focused")
    context = {
        "mode": analysis_type,
        "mode_label": mode.get("label"),
        "company": _compact_company(dossier.get("company", {})),
        "data_profile": _compact_data_profile(data_profile, mode),
        "decision_helper": _limit_nested_records(analysis_dossier.get("decision_helper", {}), 10 if profile == "deep" else 6),
        "risk_flags": _limit_nested_records(analysis_dossier.get("risk_flags", []), 5 if profile == "deep" else 3),
        "data_requests": _compact_broker_result(broker_result, 5),
        "fetch_result": _compact_fetch_result(fetch_result, 5),
        "agent_results": _compact_agent_history(agent_results, 8 if profile == "deep" else 6),
    }
    system_prompt = """你是 A 股投研多 Agent 系统的反方审计员。

你的任务不是重新写报告，而是找出第一轮 agent 结论中的证据缺口、逻辑跳跃、数据口径错误、过度自信和互相矛盾。
只输出 JSON，不输出 Markdown。"""
    user_prompt = f"""请审计这些 agent 输出，并返回 JSON 对象：

字段：
- findings: 数组，每项包含 agent/issue/severity/evidence_path/required_fix
- overall_risk: low/medium/high
- should_revise: 布尔值，是否需要第二轮修正
- force_rerun_agents: 数组，只填写必须跳过缓存并重新分析的 agent key；没有则为空数组
- summary: 一句话中文总结

要求：
- findings 最多返回 5 条，只保留最关键的问题
- 若某个 agent 需要重新拉取或重新分析，请把它的 agent key 写入 force_rerun_agents
- 用词简洁，不要复述上下文

上下文：
{json.dumps(context, ensure_ascii=False)}
"""
    try:
        answer = llm_client.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            max_tokens=max(800, int(mode.get("critic_max_tokens") or 1536)),
        )
        parsed = _parse_json_object(answer)
        review = CriticReview.model_validate(parsed).model_dump()
        if not review["findings"]:
            return {**fallback, "summary": review.get("summary") or fallback["summary"], "overall_risk": review.get("overall_risk") or fallback["overall_risk"]}
        return review
    except (DeepSeekError, RuntimeError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        return {**fallback, "llm_error": str(exc)}


def _fallback_critic_review(
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    agent_results: list[dict[str, Any]],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for dataset in data_profile.get("missing_required", []):
        findings.append(
            {
                "agent": "data_quality",
                "issue": f"关键数据集 {dataset} 缺失，相关结论需要降权。",
                "severity": "high",
                "evidence_path": f"full_data.datasets.{dataset}",
                "required_fix": "补充数据或在最终报告中明确标记为数据缺口。",
            }
        )
    if broker_result.get("approved_requests") and not fetch_result.get("rebuilt"):
        findings.append(
            {
                "agent": "data_broker",
                "issue": "存在已批准的数据请求但资料包未重建，说明补数未执行或无权限。",
                "severity": "medium",
                "evidence_path": "data_requests.approved_requests",
                "required_fix": "最终结论需要体现补数失败对置信度的影响。",
            }
        )
    for result in agent_results:
        if float(result.get("confidence") or 0) > 0.82 and len(result.get("counter_evidence") or []) == 0:
            findings.append(
                {
                    "agent": _text(result.get("agent")),
                    "issue": "高置信度结论缺少反证列表，可能过度自信。",
                    "severity": "medium",
                    "evidence_path": "agent.counter_evidence",
                    "required_fix": "补充反证或下调置信度。",
                }
            )
        if result.get("llm_error") or result.get("schema_error"):
            findings.append(
                {
                    "agent": _text(result.get("agent")),
                    "issue": "agent 运行或结构化输出异常，已回退到规则结果。",
                    "severity": "medium",
                    "evidence_path": "agent.llm_error",
                    "required_fix": "在二轮修正中降低该 agent 权重。",
                }
            )
    severity_order = {"low": 1, "medium": 2, "high": 3}
    max_severity = max((severity_order.get(item["severity"], 2) for item in findings), default=1)
    overall = "high" if max_severity >= 3 else "medium" if max_severity == 2 else "low"
    return CriticReview(
        findings=[CriticFinding.model_validate(item) for item in findings],
        overall_risk=overall,
        should_revise=bool(findings),
        summary=f"规则审计发现 {len(findings)} 个需要修正或降权的问题。",
    ).model_dump()


def _merge_revisions(agent_results: list[dict[str, Any]], review: dict[str, Any]) -> list[dict[str, Any]]:
    findings = review.get("findings") or []
    by_agent: dict[str, list[dict[str, Any]]] = {}
    global_findings: list[dict[str, Any]] = []
    for finding in findings:
        agent = _text(finding.get("agent")) if isinstance(finding, dict) else ""
        if agent in {"", "data_quality", "data_broker", "system"}:
            global_findings.append(finding)
        else:
            by_agent.setdefault(agent, []).append(finding)
    revised = []
    for result in agent_results:
        agent = _text(result.get("agent"))
        related = by_agent.get(agent, []) + global_findings
        item = dict(result)
        if related:
            penalty = min(0.18, 0.04 * len(related))
            item["confidence"] = _clamp_float((_num(item.get("confidence")) or 0.5) - penalty)
            item["critic_findings"] = related
            item["revision_notes"] = [
                f"反方审计：{_text(finding.get('issue'))} 修正要求：{_text(finding.get('required_fix'))}"
                for finding in related
                if isinstance(finding, dict)
            ]
            counter = list(item.get("counter_evidence") or [])
            counter.extend(
                {
                    "claim": _text(finding.get("issue")),
                    "data_path": _text(finding.get("evidence_path")),
                    "strength": _text(finding.get("severity") or "medium"),
                }
                for finding in related
                if isinstance(finding, dict)
            )
            item["counter_evidence"] = counter
        revised.append(item)
    return revised


def _agent_result(
    agent: str,
    analysis_type: str,
    scores: dict[str, Any],
    risk_flags: list[dict[str, Any]],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    risk_pressure = _num(scores.get("risk_pressure")) or 0
    missing_required = data_profile.get("missing_required", [])
    high_risks = [risk for risk in risk_flags if risk.get("level") == "high"]
    confidence = _clamp_float(0.62 - len(missing_required) * 0.08 - len(high_risks) * 0.08 - risk_pressure * 0.025)
    if fetch_result.get("rebuilt"):
        confidence = _clamp_float(confidence + 0.06)
    rating = decision.get("rating_hint") or _rating_from_scores(scores)
    defensive_agents = {"bear_researcher", "risk_manager", "risk_cot_agent", "conservative_risk_analyst", "risk_section_agent"}
    if agent in defensive_agents and _rating_direction(rating)["score"] > 0:
        rating = "谨慎观察"
    if agent == "bull_researcher" and _rating_direction(rating)["score"] < 0 and not high_risks:
        rating = "积极观察"
    findings = _findings_for_agent(agent, analysis_type, scores, data_profile, broker_result, fetch_result)
    counter = _counter_for_agent(agent, missing_required, risk_flags, broker_result)
    data_requests = list(broker_result.get("approved_requests", []))
    if agent == "moat_governance_agent":
        data_requests.extend(
            [
                {"dataset": "peer_cost_curve", "need": "同行成本曲线、单位成本、毛利率和产能效率对比", "priority": "high", "blocking": False},
                {"dataset": "management_succession", "need": "管理层接班、控制权、关键人变动和市场争议新闻", "priority": "high", "blocking": False},
                {"dataset": "industry_cycle_external", "need": "行业价格、库存、期货结构、天气和供需扰动", "priority": "medium", "blocking": False},
            ]
        )
    result = {
        "agent": agent,
        "mode": analysis_type,
        "rating_hint": rating,
        "confidence": confidence,
        "scores": scores,
        "key_findings": findings,
        "counter_evidence": counter,
        "reasoning_summary": _reasoning_summary(agent, rating, findings, counter, confidence),
        "watchlist": _watchlist(analysis_type),
        "invalidating_signals": _invalidating_signals(analysis_type),
        "data_requests": data_requests,
    }
    if agent == "moat_governance_agent":
        result["domain_label"] = _moat_governance_label(result)
    return result


def _llm_agent_result(
    llm_client: DeepSeekClient,
    agent: str,
    analysis_type: str,
    mode: dict[str, Any],
    dossier: dict[str, Any],
    analysis_dossier: dict[str, Any],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    spec = AGENT_SPECS.get(agent, {"role": agent, "focus": "基于资料包进行专业分析。", "slice_keys": []})
    profile = _text(mode.get("context_profile") or "focused")
    prior_limit = 2 if profile == "minimal" else 4 if profile == "focused" else 6
    critic_limit = 0 if profile == "minimal" else 3 if profile == "focused" else 5
    context = {
        "mode": analysis_type,
        "mode_label": mode["label"],
        "time_horizon": mode["time_horizon"],
        "agent": agent,
        "agent_role": spec["role"],
        "agent_focus": spec["focus"],
        "company": _compact_company(dossier.get("company", {})),
        "data_profile": _compact_data_profile(data_profile, mode),
        "data_requests": _compact_broker_result(broker_result, 5),
        "fetch_result": _compact_fetch_result(fetch_result, 5),
        "data_unit_notes": {
            "moneyflow.net_mf_amount": "Tushare moneyflow 资金流金额单位为万元；报告中必须换算成亿元并结合流通市值/总市值占比判断强弱。",
            "daily_basic.total_mv": "Tushare daily_basic 总市值单位为万元。",
            "daily_basic.circ_mv": "Tushare daily_basic 流通市值单位为万元。",
        },
        "quantitative_checks": _limit_nested_records(_quantitative_checks(dossier, analysis_dossier), 10 if profile == "deep" else 6),
        "analysis_slice": _agent_analysis_slice(analysis_dossier, spec.get("slice_keys", [])),
        "learning_context": _compact_learning_context(analysis_dossier.get("learning_context", {}), profile),
        "prior_agent_results": _compact_agent_history(analysis_dossier.get("prior_agent_results", []), prior_limit),
        "current_stage": analysis_dossier.get("current_stage", ""),
        "critic_context": _compact_critic_context(analysis_dossier.get("critic_context", {}), profile) if critic_limit else {},
        "raw_dossier_slice": _agent_raw_slice(dossier, agent, analysis_type),
    }
    system_prompt = f"""你是 A 股投研多 Agent 系统中的「{spec['role']}」。

你的职责边界：
- {spec['focus']}
- 只基于输入资料判断，不编造缺失数据。
- 主动指出反证、数据缺口和证伪条件。
- 涉及资金流金额时，必须遵守输入中的 data_unit_notes 和 quantitative_checks，不得把万元口径误写成元/万元级结论。
- 涉及猪价、能繁母猪、成本、行业供需等资料包外变量时，必须标记为外部假设或写入 data_requests，不得当作已验证证据。
- 输出可审计的结构化推理摘要，不输出隐藏思维链。
- 结论要短，不要复述输入资料；每条 finding/counter 只保留最关键的证据。
- 这不是投资建议，只能给研究观点和观察条件。
"""
    user_prompt = f"""请完成本 agent 的独立分析，并只输出 JSON 对象，不要 Markdown。

必须包含这些字段：
- agent: 字符串
- mode: 字符串
- rating_hint: 字符串
- confidence: 0 到 1 的数字
- scores: 对象，可沿用输入评分或给出本 agent 专属评分
- key_findings: 数组，每项含 claim/data_path/strength
- counter_evidence: 数组，每项含 claim/data_path/strength
- reasoning_summary: 一句话中文摘要，控制在 60 字内
- watchlist: 数组
- invalidating_signals: 数组
- data_requests: 数组，若需要补数据则写结构化请求，否则为空数组

输入上下文 JSON：
{json.dumps(context, ensure_ascii=False)}
"""
    try:
        answer = llm_client.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            max_tokens=max(1000, int(mode.get("agent_max_tokens") or 2048)),
        )
        parsed = _parse_json_object(answer)
        return _apply_agent_guardrails(_normalize_llm_agent_result(parsed, fallback), analysis_type, dossier, analysis_dossier)
    except (DeepSeekError, RuntimeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _apply_agent_guardrails({
            **fallback,
            "llm_error": str(exc),
            "reasoning_summary": f"{fallback['reasoning_summary']} LLM 专业 agent 调用失败，已回退到规则化结果。",
        }, analysis_type, dossier, analysis_dossier)


def _normalize_llm_agent_result(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(fallback)
    result.update(
        {
            "agent": _text(fallback["agent"]),
            "mode": _text(fallback["mode"]),
            "rating_hint": _text(parsed.get("rating_hint") or fallback["rating_hint"]),
            "confidence": _clamp_float(_num(parsed.get("confidence")) if _num(parsed.get("confidence")) is not None else fallback["confidence"]),
            "scores": parsed.get("scores") if isinstance(parsed.get("scores"), dict) else fallback["scores"],
            "key_findings": _evidence_list(parsed.get("key_findings"), fallback["key_findings"]),
            "counter_evidence": _evidence_list(parsed.get("counter_evidence"), fallback["counter_evidence"]),
            "reasoning_summary": _text(parsed.get("reasoning_summary") or fallback["reasoning_summary"]),
            "watchlist": _text_list(parsed.get("watchlist")) or fallback["watchlist"],
            "invalidating_signals": _text_list(parsed.get("invalidating_signals")) or fallback["invalidating_signals"],
            "data_requests": _data_request_list(parsed.get("data_requests")) or fallback.get("data_requests", []),
            "source": "llm_agent",
        }
    )
    return result


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("LLM output is not a JSON object")
    return parsed


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("claim", "message", "title", "name", "need", "dataset", "reason", "summary"):
            item = value.get(key)
            if item is not None:
                text = _text(item)
                if text:
                    return text
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _text_list(values: Any, limit: int | None = None) -> list[str]:
    if not isinstance(values, list):
        return []
    selected = values[:limit] if limit is not None else values
    return [text for text in (_text(item) for item in selected) if text]


def _join_text(values: Any, sep: str = ", ", limit: int | None = None) -> str:
    return sep.join(_text_list(values, limit))


def _evidence_list(values: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return fallback
    evidence = []
    for item in values:
        if isinstance(item, dict):
            claim = _text(item.get("claim") or item.get("message") or item.get("title") or item)
            evidence.append(
                {
                    "claim": claim,
                    "data_path": _text(item.get("data_path") or item.get("path") or ""),
                    "strength": _text(item.get("strength") or item.get("level") or "medium") or "medium",
                }
            )
        else:
            evidence.append({"claim": _text(item), "data_path": "", "strength": "medium"})
    return [item for item in evidence if item["claim"]] or fallback


def _data_request_list(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    requests = []
    for index, item in enumerate(values):
        if isinstance(item, dict):
            dataset = _text(item.get("dataset") or item.get("api_name") or item.get("need") or f"unknown_{index + 1}")
            requests.append(
                {
                    **item,
                    "dataset": dataset,
                    "need": _text(item.get("need") or dataset),
                    "priority": _text(item.get("priority") or "medium") or "medium",
                    "blocking": bool(item.get("blocking", False)),
                }
            )
        else:
            text = _text(item)
            if text:
                requests.append({"dataset": text, "need": text, "priority": "medium", "blocking": False})
    return requests


def _compact_company(company: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(company, dict):
        return {}
    keep = ("ts_code", "name", "industry", "area", "market", "list_date")
    return {key: company.get(key) for key in keep if company.get(key) not in (None, "", [])}


def _compact_data_profile(data_profile: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    rows = data_profile.get("dataset_rows", {}) if isinstance(data_profile, dict) else {}
    required = mode.get("required_datasets", [])
    secondary = mode.get("secondary_datasets", [])
    return {
        "ts_code": data_profile.get("ts_code"),
        "date_range": data_profile.get("date_range", {}),
        "required_dataset_rows": {name: rows.get(name, 0) for name in required},
        "secondary_dataset_rows": {name: rows.get(name, 0) for name in secondary[:6]},
        "missing_required": list(data_profile.get("missing_required", [])[:6]),
        "missing_secondary": list(data_profile.get("missing_secondary", [])[:6]),
        "fetch_errors": _text_list(data_profile.get("fetch_errors"), 3),
    }


def _compact_broker_result(broker_result: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    return {
        "approved_requests": _limit_nested_records(_data_request_list(broker_result.get("approved_requests")), limit),
        "rejected_requests": _limit_nested_records(_data_request_list(broker_result.get("rejected_requests")), min(3, limit)),
        "request_deduplication": broker_result.get("request_deduplication", {}),
        "tushare_jobs": _limit_nested_records(broker_result.get("tushare_jobs", []), limit),
    }


def _compact_fetch_result(fetch_result: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    changed = []
    for item in fetch_result.get("fetch_results", [])[:limit]:
        if not isinstance(item, dict):
            continue
        changed.append(
            {
                "dataset": _text(item.get("dataset")),
                "ok": bool(item.get("ok", False)),
                "rows": item.get("rows"),
                "error": _text(item.get("error")),
            }
        )
    return {
        "enabled": bool(fetch_result.get("enabled", False)),
        "rebuilt": bool(fetch_result.get("rebuilt", False)),
        "changed_datasets": changed,
        "fetch_errors": _text_list(fetch_result.get("fetch_errors"), 3),
    }


def _compact_agent_history(agent_results: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    items = []
    for item in agent_results[:limit]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "agent": _text(item.get("agent")),
                "stage": _text(item.get("stage")),
                "rating_hint": _text(item.get("rating_hint")),
                "confidence": _num(item.get("confidence")),
                "reasoning_summary": _text(item.get("reasoning_summary")),
                "key_findings": _limit_nested_records(item.get("key_findings", []), 2),
                "counter_evidence": _limit_nested_records(item.get("counter_evidence", []), 2),
            }
        )
    return items


def _compact_learning_context(learning_context: dict[str, Any], profile: str) -> dict[str, Any]:
    if not isinstance(learning_context, dict):
        return {}
    limit = 2 if profile == "minimal" else 4 if profile == "focused" else 6
    summary = _text(learning_context.get("summary"))
    distribution = learning_context.get("distribution", {})
    similar = learning_context.get("similar_cases", [])
    return {
        "summary": summary,
        "distribution": distribution,
        "similar_cases": _limit_nested_records(similar, limit),
    }


def _compact_critic_context(review: dict[str, Any], profile: str) -> dict[str, Any]:
    if not isinstance(review, dict):
        return {}
    limit = 3 if profile == "minimal" else 5
    return {
        "overall_risk": review.get("overall_risk"),
        "summary": _text(review.get("summary")),
        "findings": _limit_nested_records(review.get("findings", []), limit),
    }


def _collect_agent_data_requests(agent_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in agent_results:
        agent = _text(result.get("agent"))
        for request in _data_request_list(result.get("data_requests", [])):
            dataset = _text(request.get("dataset"))
            need = _text(request.get("need") or dataset)
            key = (dataset, need)
            if not dataset or key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    **request,
                    "requested_by": agent or request.get("requested_by") or "agent",
                    "status": "external_watch_item" if dataset.startswith("unknown_") else "pending_broker_review",
                }
            )
    return requests


def _quantitative_checks(dossier: dict[str, Any], analysis_dossier: dict[str, Any]) -> dict[str, Any]:
    market = dossier.get("market", {})
    valuation = market.get("valuation_snapshot", {})
    circ_mv = _num(valuation.get("circ_mv"))
    total_mv = _num(valuation.get("total_mv"))
    capital = _capital_flow_section(analysis_dossier)
    derived = capital.get("derived", {})
    moneyflow = capital.get("moneyflow_recent") or market.get("moneyflow_recent", [])
    five_day = _num(derived.get("five_day_net_mf_amount"))
    twenty_day = _num(derived.get("twenty_day_net_mf_amount"))
    if five_day is None or twenty_day is None:
        net_values = [_money_net(row) for row in moneyflow[:20]]
        net_values = [value for value in net_values if value is not None]
        if five_day is None and net_values:
            five_day = round(sum(net_values[:5]), 2)
        if twenty_day is None and net_values:
            twenty_day = round(sum(net_values[:20]), 2)
    return {
        "unit_basis": {
            "moneyflow_amount": "万元",
            "daily_basic_total_mv": "万元",
            "daily_basic_circ_mv": "万元",
        },
        "market_value": {
            "circ_mv_wan": circ_mv,
            "total_mv_wan": total_mv,
            "circ_mv_yi": _wan_to_yi(circ_mv),
            "total_mv_yi": _wan_to_yi(total_mv),
        },
        "moneyflow": {
            "five_day_net_mf_amount_wan": five_day,
            "twenty_day_net_mf_amount_wan": twenty_day,
            "five_day_net_mf_amount_yi": _wan_to_yi(five_day),
            "twenty_day_net_mf_amount_yi": _wan_to_yi(twenty_day),
            "five_day_vs_circ_mv_pct": _pct_of(five_day, circ_mv),
            "twenty_day_vs_circ_mv_pct": _pct_of(twenty_day, circ_mv),
            "five_day_strength": _flow_strength(_pct_of(five_day, circ_mv)),
            "twenty_day_strength": _flow_strength(_pct_of(twenty_day, circ_mv)),
        },
    }


def _capital_flow_section(analysis_dossier: dict[str, Any]) -> dict[str, Any]:
    if isinstance(analysis_dossier.get("capital_flow"), dict):
        return analysis_dossier["capital_flow"]
    speculation = analysis_dossier.get("speculation_triggers", {})
    if isinstance(speculation, dict) and isinstance(speculation.get("capital_flow"), dict):
        return speculation["capital_flow"]
    return {}


def _apply_agent_guardrails(
    result: dict[str, Any],
    analysis_type: str,
    dossier: dict[str, Any],
    analysis_dossier: dict[str, Any],
) -> dict[str, Any]:
    guarded = dict(result)
    if guarded.get("agent") == "moneyflow_agent":
        checks = _quantitative_checks(dossier, analysis_dossier).get("moneyflow", {})
        five_strength = checks.get("five_day_strength")
        twenty_strength = checks.get("twenty_day_strength")
        if not isinstance(guarded.get("key_findings"), list):
            guarded["key_findings"] = []
        for finding in guarded.get("key_findings", []):
            if not isinstance(finding, dict):
                continue
            claim = _text(finding.get("claim"))
            if "近5" in claim and "资金" in claim and five_strength:
                finding["strength"] = five_strength
            if "近20" in claim and "资金" in claim and twenty_strength:
                finding["strength"] = twenty_strength
        guarded.setdefault("key_findings", []).insert(
            0,
            {
                "claim": (
                    "资金流口径校验："
                    f"近5日净额 {checks.get('five_day_net_mf_amount_yi')} 亿元，占流通市值 {checks.get('five_day_vs_circ_mv_pct')}%；"
                    f"近20日净额 {checks.get('twenty_day_net_mf_amount_yi')} 亿元，占流通市值 {checks.get('twenty_day_vs_circ_mv_pct')}%。"
                    "Tushare moneyflow 金额单位为万元，资金强弱按市值占比校准。"
                ),
                "data_path": "quantitative_checks.moneyflow",
                "strength": "high",
            }
        )
    if guarded.get("agent") == "moat_governance_agent":
        guarded["domain_label"] = _moat_governance_label(guarded)
    if _mentions_external_industry_assumption(guarded):
        guarded.setdefault("counter_evidence", []).append(
            {
                "claim": "涉及猪价、能繁母猪、成本或行业供需等外部变量时，如资料包未包含对应数据，应视为外部假设而非已验证证据。",
                "data_path": "guardrails.external_industry_assumption",
                "strength": "medium",
            }
        )
        guarded.setdefault("data_requests", []).append(
            {
                "dataset": "external_industry_data",
                "need": "猪价、能繁母猪、养殖成本、生猪期货、收储或行业政策等外部周期变量",
                "priority": "medium",
                "blocking": False,
                "reason": "agent 使用了资料包外行业周期变量，需要后续接入 Tushare 或外部数据源校验。",
            }
        )
    guarded["rating_direction"] = _rating_direction(_text(guarded.get("rating_hint")))
    return guarded


def _moat_governance_label(result: dict[str, Any]) -> str:
    scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
    moat = _num(scores.get("moat_strength"))
    technology = _num(scores.get("technology_moat"))
    governance = _num(scores.get("governance_quality"))
    succession = _num(scores.get("succession_risk_inverted"))
    positive_scores = [value for value in (moat, technology, governance) if value is not None]
    base = sum(positive_scores) / len(positive_scores) if positive_scores else None
    if base is None:
        moat_label = "护城河待验证"
    elif base >= 4:
        moat_label = "护城河较强"
    elif base >= 3:
        moat_label = "护城河中等"
    else:
        moat_label = "护城河偏弱"
    if succession is not None and succession <= 2:
        return f"{moat_label} · 接班风险高"
    if governance is not None and governance < 3:
        return f"{moat_label} · 治理待改善"
    return f"{moat_label} · 治理较稳"


def _mentions_external_industry_assumption(result: dict[str, Any]) -> bool:
    text = json.dumps(
        {
            "summary": result.get("reasoning_summary"),
            "findings": result.get("key_findings"),
            "watchlist": result.get("watchlist"),
        },
        ensure_ascii=False,
        default=str,
    )
    return any(token in text for token in ("猪价", "能繁母猪", "完全成本", "供需", "期货"))


def _wan_to_yi(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number / 10000, 2)


def _pct_of(value: Any, denominator: Any) -> float | None:
    number = _num(value)
    base = _num(denominator)
    if number is None or not base:
        return None
    return round(number / base * 100, 3)


def _flow_strength(ratio_pct: float | None) -> str:
    if ratio_pct is None:
        return "medium"
    abs_ratio = abs(ratio_pct)
    if abs_ratio >= 2:
        return "high"
    if abs_ratio >= 0.5:
        return "medium"
    return "low"


def _money_net(row: dict[str, Any]) -> float | None:
    explicit = _num(row.get("net_mf_amount"))
    if explicit is not None:
        return explicit
    buy = sum(_num(row.get(key)) or 0 for key in ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"))
    sell = sum(_num(row.get(key)) or 0 for key in ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount"))
    return buy - sell


def _agent_analysis_slice(analysis_dossier: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    if not keys:
        selected = {
            "decision_helper": analysis_dossier.get("decision_helper", {}),
            "risk_flags": analysis_dossier.get("risk_flags", []),
            "data_quality": analysis_dossier.get("data_quality", {}),
        }
        if analysis_dossier.get("learning_context"):
            selected["learning_context"] = analysis_dossier.get("learning_context", {})
        if analysis_dossier.get("decision_memory"):
            selected["decision_memory"] = analysis_dossier.get("decision_memory", {})
        if analysis_dossier.get("prior_agent_results"):
            selected["prior_agent_results"] = analysis_dossier.get("prior_agent_results", [])
        return _limit_nested_records(selected)
    selected = {key: analysis_dossier.get(key) for key in keys if key in analysis_dossier}
    selected["decision_helper"] = analysis_dossier.get("decision_helper", {})
    selected["risk_flags"] = analysis_dossier.get("risk_flags", [])
    selected["data_quality"] = analysis_dossier.get("data_quality", {})
    if analysis_dossier.get("learning_context"):
        selected["learning_context"] = analysis_dossier.get("learning_context", {})
    if analysis_dossier.get("decision_memory"):
        selected["decision_memory"] = analysis_dossier.get("decision_memory", {})
    if analysis_dossier.get("prior_agent_results"):
        selected["prior_agent_results"] = analysis_dossier.get("prior_agent_results", [])
    return _limit_nested_records(selected)


def _agent_raw_slice(dossier: dict[str, Any], agent: str, analysis_type: str) -> dict[str, Any]:
    market = dossier.get("market", {})
    financials = dossier.get("financials", {})
    events = dossier.get("shareholders_and_events", {})
    industry = dossier.get("industry", {})
    compact_market = {
        "technical_snapshot": market.get("technical_snapshot"),
        "daily_recent": market.get("daily_recent", [])[:40],
        "daily_basic_recent": market.get("daily_basic_recent", [])[:30],
        "moneyflow_recent": market.get("moneyflow_recent", [])[:25],
        "margin_recent": market.get("margin_recent", [])[:20],
        "limit_recent": market.get("limit_recent", [])[:20],
    }
    compact_financials = {
        "income_recent": financials.get("income_recent", [])[:10],
        "cashflow_recent": financials.get("cashflow_recent", [])[:10],
        "indicator_recent": financials.get("indicator_recent", [])[:10],
        "main_business": financials.get("main_business", [])[:12],
        "dividend": financials.get("dividend", [])[:12],
        "audit": financials.get("audit", [])[:8],
        "financial_trends": financials.get("financial_trends", {}),
    }
    compact_events = {
        "top10_holders": events.get("top10_holders", [])[:12],
        "pledge_stat": events.get("pledge_stat", [])[:12],
    }
    compact_industry = _limit_nested_records(industry, 12)
    compact_announcements = dossier.get("announcements", [])[:20]
    mapping = {
        "oversold_detector": {"market": {"technical_snapshot": market.get("technical_snapshot"), "daily_recent": market.get("daily_recent", [])[:80]}},
        "volume_agent": {"market": {"daily_recent": market.get("daily_recent", [])[:80], "daily_basic_recent": market.get("daily_basic_recent", [])[:80]}},
        "moneyflow_agent": {"market": {"moneyflow_recent": market.get("moneyflow_recent", [])[:60], "margin_recent": market.get("margin_recent", [])[:60]}},
        "sentiment_agent": {"announcements": dossier.get("announcements", [])[:40], "industry": industry, "market": {"limit_recent": market.get("limit_recent", [])[:40]}},
        "industry_cycle_agent": {"industry": industry, "announcements": dossier.get("announcements", [])[:40], "market": {"daily_recent": market.get("daily_recent", [])[:40]}},
        "business_quality_agent": {"financials": {"main_business": financials.get("main_business", [])[:24]}, "industry": industry},
        "financial_trend_agent": {"financials": {"income_recent": financials.get("income_recent", [])[:12], "indicator_recent": financials.get("indicator_recent", [])[:12], "financial_trends": financials.get("financial_trends", {})}},
        "cashflow_agent": {"financials": {"cashflow_recent": financials.get("cashflow_recent", [])[:12], "income_recent": financials.get("income_recent", [])[:12]}},
        "dividend_sustainability_agent": {"financials": {"dividend": financials.get("dividend", [])[:24], "cashflow_recent": financials.get("cashflow_recent", [])[:12]}},
        "governance_agent": {"events": {"top10_holders": events.get("top10_holders", [])[:20], "pledge_stat": events.get("pledge_stat", [])[:20]}, "financials": {"audit": financials.get("audit", [])[:12]}},
        "risk_auditor": {"data_quality": dossier.get("data_quality", {}), "market": compact_market, "financials": compact_financials, "events": compact_events},
        "market_analyst": {"market": compact_market, "industry": compact_industry},
        "news_analyst": {"announcements": compact_announcements, "industry": compact_industry},
        "fundamental_analyst": {"financials": compact_financials, "events": compact_events, "industry": compact_industry},
        "sentiment_analyst": {"announcements": compact_announcements, "market": {"limit_recent": compact_market["limit_recent"], "moneyflow_recent": compact_market["moneyflow_recent"]}},
        "moat_governance_agent": {"financials": compact_financials, "events": compact_events, "industry": compact_industry, "announcements": compact_announcements[:12]},
        "bull_researcher": {"market": compact_market, "financials": compact_financials, "announcements": compact_announcements[:12]},
        "bear_researcher": {"market": compact_market, "financials": compact_financials, "events": compact_events, "announcements": compact_announcements[:12]},
        "research_manager": {"market": compact_market, "financials": compact_financials, "industry": compact_industry},
        "trader": {"market": compact_market, "announcements": compact_announcements[:10]},
        "aggressive_risk_analyst": {"market": compact_market, "announcements": compact_announcements[:10], "data_quality": dossier.get("data_quality", {})},
        "neutral_risk_analyst": {"market": compact_market, "financials": compact_financials, "data_quality": dossier.get("data_quality", {})},
        "conservative_risk_analyst": {"financials": compact_financials, "events": compact_events, "data_quality": dossier.get("data_quality", {})},
        "portfolio_manager": {"market": compact_market, "financials": compact_financials, "industry": compact_industry, "data_quality": dossier.get("data_quality", {})},
    }
    fallback = {"market": compact_market, "financials": compact_financials, "events": compact_events, "industry": compact_industry}
    return _limit_nested_records(mapping.get(agent, fallback))


def _limit_nested_records(value: Any, limit: int = 40) -> Any:
    if isinstance(value, list):
        return [_limit_nested_records(item, limit) for item in value[:limit]]
    if isinstance(value, dict):
        return {key: _limit_nested_records(item, limit) for key, item in value.items()}
    return value


def _emit_progress(callback: ProgressCallback | None, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
    if callback:
        callback({"time": timestamp(), "stage": stage, "message": message, "details": details or {}})


def _findings_for_agent(
    agent: str,
    analysis_type: str,
    scores: dict[str, Any],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
) -> list[dict[str, Any]]:
    findings = [
        {"claim": f"{agent} 完成 {analysis_type} 模式评估", "data_path": "analysis_dossier.decision_helper.score_summary", "strength": "medium"},
        {"claim": f"当前资料包覆盖 {len(data_profile.get('dataset_rows', {}))} 个数据集", "data_path": "full_data.datasets", "strength": "high"},
    ]
    if scores:
        best_key, best_value = max(scores.items(), key=lambda item: _num(item[1]) or -1)
        findings.append({"claim": f"相对优势评分：{best_key}={best_value}/5", "data_path": f"decision_helper.score_summary.{best_key}", "strength": "medium"})
    if fetch_result.get("rebuilt"):
        findings.append({"claim": "分析过程中已完成动态补数并重建资料包", "data_path": "tushare_fetch_results.changed_datasets", "strength": "high"})
    elif broker_result.get("approved_requests"):
        findings.append({"claim": "存在关键数据缺口，已形成数据请求", "data_path": "data_requests.approved_requests", "strength": "medium"})
    return findings


def _counter_for_agent(agent: str, missing_required: list[str], risk_flags: list[dict[str, Any]], broker_result: dict[str, Any]) -> list[dict[str, Any]]:
    counter = []
    for dataset in missing_required[:3]:
        counter.append({"claim": f"缺少关键数据集 {dataset}，会压低 {agent} 的结论置信度", "data_path": f"full_data.datasets.{dataset}", "strength": "high"})
    for risk in risk_flags[:3]:
        counter.append({"claim": f"{risk.get('title')}: {risk.get('message')}", "data_path": "analysis_dossier.risk_flags", "strength": risk.get("level", "medium")})
    if broker_result.get("approved_requests"):
        counter.append({"claim": "仍需确认补数请求是否成功，否则最终报告应保留数据缺口", "data_path": "data_requests.approved_requests", "strength": "medium"})
    return counter


def _rating_direction(rating_hint: str) -> dict[str, Any]:
    text = rating_hint.strip()
    if any(token in text for token in ("高风险", "风险较高", "风险很高", "高危")):
        return {"direction": "negative", "label": "回避", "score": -2}
    if any(token in text for token in ("强烈回避", "坚决回避", "卖出")):
        return {"direction": "negative", "label": "回避", "score": -2}
    if any(token in text for token in ("回避", "规避", "谨慎回避")):
        return {"direction": "negative", "label": "回避", "score": -2}
    if any(token in text for token in ("偏谨慎", "谨慎", "等待", "弱价值底线", "价值底线弱", "证据不足", "无明确止跌", "未见止跌", "缺乏止跌", "反弹基础薄弱", "时机尚未成熟", "不支持超跌反弹")):
        return {"direction": "negative", "label": "谨慎观察", "score": -1}
    if any(token in text for token in ("强烈积极", "高确定", "强买入")):
        return {"direction": "positive", "label": "积极", "score": 2}
    if any(token in text for token in ("积极", "小仓", "试错", "买入", "机会")):
        return {"direction": "positive", "label": "积极观察", "score": 1}
    return {"direction": "neutral", "label": "观察", "score": 0}


def _agent_vote_weight(agent: str) -> float:
    return {
        "risk_auditor": 1.35,
        "risk_manager": 1.45,
        "trade_decision_agent": 1.35,
        "research_manager": 1.35,
        "portfolio_manager": 1.45,
        "trader": 1.25,
        "conservative_risk_analyst": 1.35,
        "neutral_risk_analyst": 1.15,
        "aggressive_risk_analyst": 1.05,
        "bear_researcher": 1.2,
        "bull_researcher": 1.15,
        "thesis_cot_agent": 1.35,
        "risk_cot_agent": 1.35,
        "data_cot_agent": 1.2,
        "major_takeaways_agent": 1.35,
        "risk_section_agent": 1.3,
        "valuation_overview_agent": 1.15,
        "investment_update_agent": 1.15,
        "technical_timing_agent": 1.2,
        "moneyflow_agent": 1.1,
        "industry_cycle_agent": 1.1,
        "valuation_agent": 1.0,
        "value_floor_agent": 1.0,
        "catalyst_agent": 1.0,
    }.get(agent, 1.0)


def _final_direction_from_score(score: float, negative_votes: int, positive_votes: int, rule_vote: dict[str, Any] | None) -> dict[str, Any]:
    rule_negative = bool(rule_vote and rule_vote.get("score", 0) < 0)
    if score <= -1.2:
        return {"direction": "negative", "label": "回避", "score": score}
    if score <= -0.35:
        return {"direction": "negative", "label": "谨慎回避" if negative_votes > positive_votes else "谨慎观察", "score": score}
    if rule_negative and negative_votes >= positive_votes:
        return {"direction": "negative", "label": "谨慎观察", "score": score}
    if score >= 1.2:
        return {"direction": "positive", "label": "积极", "score": score}
    if score >= 0.35:
        return {"direction": "positive", "label": "积极观察", "score": score}
    return {"direction": "neutral", "label": "观察", "score": score}


def _debate(agent_results: list[dict[str, Any]], decision_helper: dict[str, Any] | None = None) -> dict[str, Any]:
    agreements = []
    conflicts = []
    weak = []
    votes = []
    total_weight = 0.0
    weighted_score = 0.0
    for item in agent_results:
        direction = _rating_direction(_text(item.get("rating_hint")))
        confidence = _clamp_float(_num(item.get("confidence")) if _num(item.get("confidence")) is not None else 0.5)
        weight = confidence * _agent_vote_weight(_text(item.get("agent")))
        votes.append({"agent": item.get("agent"), "rating_hint": item.get("rating_hint"), **direction, "confidence": confidence, "weight": round(weight, 3)})
        weighted_score += direction["score"] * weight
        total_weight += weight
        if confidence < 0.45:
            weak.append(f"{item['agent']} 置信度偏低，需要更多数据或人工复核。")

    rule_vote = None
    if decision_helper and decision_helper.get("rating_hint"):
        rule_direction = _rating_direction(_text(decision_helper.get("rating_hint")))
        rule_weight = 0.75 + min(0.25, (_num(decision_helper.get("score_summary", {}).get("risk_pressure")) or 0) * 0.04)
        rule_vote = {"agent": "rule_decision_helper", "rating_hint": decision_helper.get("rating_hint"), **rule_direction, "confidence": 0.72, "weight": round(rule_weight, 3)}
        weighted_score += rule_direction["score"] * rule_weight
        total_weight += rule_weight

    directional_score = round(weighted_score / total_weight, 3) if total_weight else 0
    negative_votes = [vote for vote in votes if vote["score"] < 0]
    positive_votes = [vote for vote in votes if vote["score"] > 0]
    neutral_votes = [vote for vote in votes if vote["score"] == 0]
    final_direction = _final_direction_from_score(directional_score, len(negative_votes), len(positive_votes), rule_vote)

    if negative_votes and len(negative_votes) >= max(2, len(agent_results) // 2):
        agreements.append(f"多数 agent 指向谨慎/回避：{', '.join(_text(v['agent']) for v in negative_votes)}。")
    if positive_votes:
        conflicts.append(f"仍有偏积极或试错观点：{', '.join(_text(v['agent']) for v in positive_votes)}。")
    if neutral_votes and negative_votes:
        conflicts.append(f"中性观点与谨慎观点并存：{', '.join(_text(v['agent']) for v in neutral_votes)}。")
    raw_ratings = {_text(item.get("rating_hint")) for item in agent_results if item.get("rating_hint")}
    if len(raw_ratings) > 1:
        conflicts.append(f"原始评级提示存在差异：{'、'.join(sorted(raw_ratings))}")

    avg_conf = sum((_num(item.get("confidence")) or 0.5) for item in agent_results) / max(1, len(agent_results))
    alignment = max(len(negative_votes), len(positive_votes), len(neutral_votes)) / max(1, len(agent_results))
    direction_confidence = _clamp_float(avg_conf * (0.72 + alignment * 0.28) - min(0.12, len(conflicts) * 0.03))
    if rule_vote and rule_vote["score"] < 0 and final_direction["score"] >= 0:
        conflicts.append("规则底座给出回避/谨慎，但 agent 聚合未充分体现，需要人工复核。")
        direction_confidence = _clamp_float(direction_confidence - 0.08)

    return {
        "agreements": agreements,
        "conflicts": conflicts,
        "weak_evidence": weak,
        "average_confidence": round(avg_conf, 3),
        "directional_score": directional_score,
        "final_direction": final_direction,
        "direction_confidence": direction_confidence,
        "rating_votes": votes,
        "rule_vote": rule_vote,
        "vote_summary": {"negative": len(negative_votes), "neutral": len(neutral_votes), "positive": len(positive_votes)},
        "confidence_adjustments": [{"reason": "弱证据/数据缺口", "effect": "降低最终置信度"}] if weak else [],
    }


def _confidence_trace(agent_results: list[dict[str, Any]], debate: dict[str, Any], analysis_type: str) -> dict[str, Any]:
    avg = debate["average_confidence"]
    final_conf = debate.get("direction_confidence", avg)
    rating = _mode_final_rating_label(analysis_type, debate.get("final_direction", {}))
    return {
        "rounds": [
            {"round": "initial", "confidence": 0.5},
            {"round": "specialists", "confidence": avg},
            {"round": "debate", "confidence": final_conf},
        ],
        "directional_score": debate.get("directional_score", 0),
        "vote_summary": debate.get("vote_summary", {}),
        "final_confidence": final_conf,
        "final_rating": rating,
    }


def _mode_final_rating_label(analysis_type: str, final_direction: dict[str, Any]) -> str:
    label = _text(final_direction.get("label") or "观察")
    score = _num(final_direction.get("score")) or 0
    if analysis_type == "oversold_rebound":
        if score <= -1.2:
            return "高风险回避"
        if score < -0.35:
            return "等待确认"
        if score >= 0.35:
            return "可试反弹"
        return "观察反弹"
    return label


def _agent_conversation(
    analysis_type: str,
    mode: dict[str, Any],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    hypotheses: dict[str, Any],
    learning_context: dict[str, Any],
    agent_results: list[dict[str, Any]],
    debate: dict[str, Any],
    confidence_trace: dict[str, Any],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {
            "speaker": "Orchestrator",
            "role": "调度",
            "message": f"已进入 {mode['label']} 模式，时间尺度为 {mode['time_horizon']}，本轮将运行 {len(mode['agents'])} 个 agent。",
        },
        {
            "speaker": "Data Profiler",
            "role": "数据画像",
            "message": f"当前关键缺失：{_join_text(data_profile.get('missing_required', [])) or '无'}；次要缺失：{_join_text(data_profile.get('missing_secondary', [])) or '无'}。",
        },
        {
            "speaker": "Hypothesis Board",
            "role": "假设池",
            "message": "提出初始假设：" + _join_text(hypotheses.get("hypotheses", []), "；", 3),
        },
    ]
    if learning_context:
        outcome = learning_context.get("outcome_distribution", {})
        distribution = outcome.get("distribution", {})
        regime = learning_context.get("market_regime", {})
        messages.append(
            {
                "speaker": "Pattern Learning",
                "role": "历史学习",
                "message": (
                    f"市场状态：趋势 {_text(regime.get('trend') or 'unknown')}、流动性 {_text(regime.get('liquidity') or 'unknown')}；"
                    f"相似窗口 {len(learning_context.get('similar_cases', []))} 个；"
                    f"结局概率：价值修复 {distribution.get('value_repair', 0)}%，"
                    f"价值陷阱 {distribution.get('value_trap', 0)}%，"
                    f"长期横盘 {distribution.get('long_flat', 0)}%。"
                ),
            }
        )
        failure_matches = learning_context.get("failure_case_matches", [])
        if failure_matches:
            messages.append(
                {
                    "speaker": "Failure Case Library",
                    "role": "打脸案例",
                    "message": f"命中过去系统误判案例 {len(failure_matches)} 个，需要降低单一结论自信并复核失败原因。",
                }
            )
    requests = broker_result.get("approved_requests", [])
    if requests:
        messages.append(
            {
                "speaker": "Data Request Broker",
                "role": "数据请求",
                "message": f"发现 {len(requests)} 个数据请求：" + "；".join(f"{_text(item.get('dataset'))}({_text(item.get('priority'))})" for item in requests[:4]),
            }
        )
    else:
        messages.append({"speaker": "Data Request Broker", "role": "数据请求", "message": "没有发现需要阻塞分析的数据缺口。"})
    if fetch_result.get("enabled"):
        fetched = fetch_result.get("fetch_results", [])
        failed = fetch_result.get("fetch_errors", [])
        messages.append(
            {
                "speaker": "Tushare Fetcher",
                "role": "补数",
                "message": f"补抓成功 {len(fetched)} 个数据集，失败/权限缺口 {len(failed)} 个，资料包重建：{'是' if fetch_result.get('rebuilt') else '否'}。",
            }
        )
    else:
        messages.append({"speaker": "Tushare Fetcher", "role": "补数", "message": "本轮未启用动态补数，使用现有本地资料包继续分析。"})

    for result in agent_results:
        source = "LLM 专家" if result.get("source") == "llm_agent" else "规则回退"
        messages.append(
            {
                "speaker": result["agent"],
                "role": "专题分析",
                "message": f"({source}) {_text(result.get('reasoning_summary'))} 关键跟踪项：{_join_text(result.get('watchlist', []), ', ', 3)}。",
            }
        )
    conflicts = debate.get("conflicts", [])
    weak = debate.get("weak_evidence", [])
    messages.append(
        {
            "speaker": "Debate Council",
            "role": "观点会议",
            "message": (
                f"共识 {len(debate.get('agreements', []))} 条，分歧 {len(conflicts)} 条，弱证据 {len(weak)} 条。"
                f"方向投票：{debate.get('vote_summary', {})}，方向分数 {debate.get('directional_score')}。"
            ),
        }
    )
    messages.append(
        {
            "speaker": "Risk Auditor",
            "role": "风控",
            "message": "如果存在数据缺口、资金未确认、财务恶化或技术破位，最终结论需要降级并保留证伪条件。",
        }
    )
    messages.append(
        {
            "speaker": "Editor",
            "role": "主编",
            "message": f"最终提示为“{confidence_trace['final_rating']}”，置信度 {confidence_trace['final_confidence']}。已生成可归档报告。",
        }
    )
    return messages


def _final_report(
    code: str,
    analysis_type: str,
    mode: dict[str, Any],
    data_profile: dict[str, Any],
    broker_result: dict[str, Any],
    fetch_result: dict[str, Any],
    hypotheses: dict[str, Any],
    learning_context: dict[str, Any],
    agent_results: list[dict[str, Any]],
    debate: dict[str, Any],
    confidence_trace: dict[str, Any],
    agent_data_requests: list[dict[str, Any]] | None = None,
    decision_memory: dict[str, Any] | None = None,
    analysis_context: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"# 多 Agent 分析报告：{code}",
        "",
        f"- 分析模式：{mode['label']}（{analysis_type}）",
        f"- Agent 模板：{mode.get('template_label') or mode.get('template') or 'native'}",
        f"- 时间尺度：{mode['time_horizon']}",
        f"- 最终置信度：{confidence_trace['final_confidence']}",
        f"- 最终提示：{confidence_trace['final_rating']}",
        f"- 方向分数：{confidence_trace.get('directional_score', 0)}",
        f"- 方向投票：{confidence_trace.get('vote_summary', {})}",
        "",
        "## 初始假设",
    ]
    lines.extend(f"- {_text(item)}" for item in hypotheses.get("hypotheses", []))
    lines.extend(["", "## 数据画像"])
    lines.append(f"- 数据范围：{data_profile.get('date_range', {})}")
    lines.append(f"- 关键缺失：{_join_text(data_profile.get('missing_required', [])) or '无'}")
    lines.append(f"- 次要缺失：{_join_text(data_profile.get('missing_secondary', [])) or '无'}")
    lines.append(f"- 动态补数：{_fetch_status_text(broker_result, fetch_result)}，重建资料包：{'是' if fetch_result.get('rebuilt') else '否'}")
    if broker_result.get("approved_requests"):
        lines.extend(["", "## 数据请求"])
        lines.extend(
            f"- {_text(req.get('dataset'))}：{_text(req.get('need'))}（priority={_text(req.get('priority'))}，blocking={bool(req.get('blocking'))}）"
            for req in broker_result["approved_requests"]
        )
    if fetch_result.get("fetch_results"):
        lines.extend(["", "## Tushare 补抓结果"])
        lines.extend(f"- {item['dataset']}：{item['rows']} 行" for item in fetch_result["fetch_results"])
    if fetch_result.get("fetch_errors"):
        lines.extend(["", "## 补抓失败/权限缺口"])
        lines.extend(f"- {item.get('dataset') or item.get('api_name')}：{item.get('error')}" for item in fetch_result["fetch_errors"])
    if agent_data_requests:
        lines.extend(["", "## Agent 补充数据请求"])
        lines.extend(
            f"- {_text(req.get('requested_by'))}：{_text(req.get('dataset'))} / {_text(req.get('need'))}（{_text(req.get('status'))}）"
            for req in agent_data_requests
        )
    if learning_context:
        lines.extend(_learning_report_lines(learning_context))
    if analysis_context:
        hidden_context = analysis_context.get("hidden_condition_context") or {}
        news_context = analysis_context.get("news_context") or {}
        if hidden_context:
            lines.extend(["", "## 隐形条件检查"])
            for item in hidden_context.get("focus_questions", [])[:6]:
                lines.append(f"- {_text(item)}")
        if news_context:
            lines.extend(["", "## 相关新闻线索"])
            if news_context.get("error"):
                lines.append(f"- 新闻检索状态：{_text(news_context.get('error'))}")
            lines.append(f"- 检索关键词：{_join_text(news_context.get('keywords', []), '、', 12) or '无'}")
            for item in news_context.get("items", [])[:6]:
                lines.append(f"- {_text(item.get('time'))} {_text(item.get('title'))}（命中：{_join_text(item.get('matched_keywords', []), '、', 5) or '-'}）")
    if decision_memory and decision_memory.get("entries"):
        lines.extend(["", "## 过往决策记忆"])
        lines.append(
            f"- 已纳入同股票历史 {decision_memory.get('same_stock_count', 0)} 条，跨股票经验 {decision_memory.get('cross_stock_count', 0)} 条。"
        )
        for item in decision_memory.get("entries", [])[:5]:
            scope = "同股" if item.get("scope") == "same_stock" else "跨股"
            lines.append(f"- {scope} {_text(item.get('ts_code'))}：{_text(item.get('rating_hint'))} / 置信度 {item.get('confidence')}；{_text(item.get('summary'))}")
    lines.extend(["", "## Agent 观点"])
    for result in agent_results:
        source = "LLM 专家" if result.get("source") == "llm_agent" else "规则回退"
        lines.append(f"### {_text(result.get('agent'))}")
        lines.append(f"- 来源：{source}")
        lines.append(f"- 评级提示：{_text(result.get('rating_hint'))}")
        if result.get("stage"):
            lines.append(f"- 执行阶段：{_stage_label(_text(result.get('stage')))}")
        lines.append(f"- 方向判断：{_text(result.get('rating_direction', {}).get('label') if isinstance(result.get('rating_direction'), dict) else '')}")
        lines.append(f"- 置信度：{result.get('confidence')}")
        lines.append(f"- 推理摘要：{_text(result.get('reasoning_summary'))}")
        for finding in result.get("key_findings", [])[:3]:
            lines.append(f"- 证据：{_text(finding.get('claim') if isinstance(finding, dict) else finding)}（{_text(finding.get('strength') if isinstance(finding, dict) else 'medium')}）")
        for counter in result.get("counter_evidence", [])[:2]:
            lines.append(f"- 反证：{_text(counter.get('claim') if isinstance(counter, dict) else counter)}（{_text(counter.get('strength') if isinstance(counter, dict) else 'medium')}）")
        for note in result.get("revision_notes", [])[:2]:
            lines.append(f"- 修正记录：{_text(note)}")
        lines.append("")
    lines.extend(["## 观点会议"])
    lines.extend(f"- 共识：{_text(item)}" for item in debate.get("agreements", []) or ["暂无明确共识"])
    lines.extend(f"- 分歧：{_text(item)}" for item in debate.get("conflicts", []) or ["暂无核心分歧"])
    lines.extend(f"- 弱证据：{_text(item)}" for item in debate.get("weak_evidence", []) or ["暂无明显弱证据"])
    lines.extend(["", "## 跟踪清单"])
    for item in _watchlist(analysis_type):
        lines.append(f"- {item}")
    lines.extend(["", "## 证伪条件"])
    for item in _invalidating_signals(analysis_type):
        lines.append(f"- {item}")
    lines.extend(["", "免责声明：以上内容仅用于研究和情景推演，不构成投资建议。"])
    return "\n".join(lines)


def _learning_report_lines(learning_context: dict[str, Any]) -> list[str]:
    lines = ["", "## 历史相似走势学习"]
    if learning_context.get("error"):
        lines.append(f"- 模块状态：失败，错误信息：{_text(learning_context.get('error'))}")
        return lines

    regime = learning_context.get("market_regime", {})
    distribution = learning_context.get("outcome_distribution", {})
    probabilities = distribution.get("distribution", {})
    query_features = learning_context.get("query_features", {})
    lines.append(
        "- 市场状态："
        f"趋势={_text(regime.get('trend') or 'unknown')}，"
        f"流动性={_text(regime.get('liquidity') or 'unknown')}，"
        f"风偏={_text(regime.get('risk_appetite') or 'unknown')}，"
        f"风格={_text(regime.get('style') or 'unknown')}"
    )
    for evidence in regime.get("evidence", [])[:2]:
        lines.append(f"- Regime 证据：{_text(evidence)}")
    if query_features:
        lines.append("- 当前核心特征：" + "，".join(f"{key}={value}" for key, value in query_features.items()))
    lines.append(
        "- 结局概率："
        f"价值修复 {_text(probabilities.get('value_repair', 0))}%，"
        f"价值陷阱 {_text(probabilities.get('value_trap', 0))}%，"
        f"长期横盘 {_text(probabilities.get('long_flat', 0))}%"
    )
    lines.append(f"- 样本数量：{distribution.get('sample_size', 0)}，不确定性：{_text(distribution.get('uncertainty_level') or 'unknown')}")
    if distribution.get("interpretation"):
        lines.append(f"- 概率解读：{_text(distribution.get('interpretation'))}")
    for warning in learning_context.get("warnings", [])[:4]:
        lines.append(f"- 提醒：{_text(warning)}")

    similar_cases = learning_context.get("similar_cases", [])
    if similar_cases:
        lines.extend(["", "### Top 相似案例"])
        for case in similar_cases[:5]:
            returns = case.get("forward_returns", {})
            drawdown = case.get("forward_max_drawdown", {})
            lines.append(
                f"- {case.get('trade_date')}：相似度 {case.get('similarity')}，"
                f"结局={_outcome_label(case.get('outcome_class'))}，"
                f"后20/60/120日收益={returns.get('20d')}/{returns.get('60d')}/{returns.get('120d')}%，"
                f"后60日最大回撤={drawdown.get('60d')}%"
            )
    else:
        lines.append("- Top 相似案例：暂无可用样本。")

    failure_matches = learning_context.get("failure_case_matches", [])
    lines.extend(["", "## Failure Case Library"])
    if failure_matches:
        for item in failure_matches:
            actual = item.get("actual_outcome", {})
            postmortem = item.get("postmortem", {})
            lines.append(
                f"- {item.get('case_id') or '未命名案例'}：相似度 {item.get('failure_similarity')}，"
                f"类型={_text(item.get('failure_type')) or 'unknown'}，"
                f"实际结果={_text(actual.get('summary') if isinstance(actual, dict) else actual)}，"
                f"复盘={_text(postmortem.get('root_cause') if isinstance(postmortem, dict) else postmortem)}"
            )
    else:
        lines.append("- 暂无命中的打脸案例；后续真实复盘案例写入后，这里会自动参与提醒。")
    return lines


def _outcome_label(value: Any) -> str:
    return {
        "value_repair": "价值修复",
        "value_trap": "价值陷阱",
        "long_flat": "长期横盘",
    }.get(_text(value), _text(value) or "unknown")


def _fetch_status_text(broker_result: dict[str, Any], fetch_result: dict[str, Any]) -> str:
    if not fetch_result.get("enabled"):
        return "未启用"
    requests = broker_result.get("approved_requests", [])
    fetched = fetch_result.get("fetch_results", [])
    failed = fetch_result.get("fetch_errors", [])
    if not requests:
        return "已启用，无补数请求"
    if fetched or failed:
        return f"已执行，成功 {len(fetched)} 个，失败/权限缺口 {len(failed)} 个"
    return "已启用，未执行补抓"


def _watchlist(analysis_type: str) -> list[str]:
    return {
        "oversold_rebound": ["近 5 日资金净额", "换手率和成交额", "MA20/MA60", "行业指数 20 日表现"],
        "value_speculation": ["估值变化", "资金净流入占流通市值比例", "行业周期/猪价线索", "公告催化", "业绩预告/财报验证", "MA60"],
        "value_quality": ["ROE", "经营现金流/净利润", "毛利率", "主营业务结构", "行业景气"],
        "value_dividend": ["股息率", "现金分红", "经营现金流", "资产负债率", "质押比例"],
    }.get(analysis_type, ["数据缺口", "风险事件"])


def _invalidating_signals(analysis_type: str) -> list[str]:
    return {
        "oversold_rebound": ["继续放量下跌", "资金连续净流出", "跌破前低", "行业继续走弱"],
        "value_speculation": ["业绩继续恶化", "催化落空", "资金持续流出", "跌破中期趋势"],
        "value_quality": ["ROE 持续下滑", "现金流无法覆盖利润", "主营收入萎缩", "治理风险上升"],
        "value_dividend": ["分红减少或取消", "现金流恶化", "负债率上升", "高股息来自股价单边下跌"],
    }.get(analysis_type, ["关键数据证伪当前假设"])


def _reasoning_summary(agent: str, rating: str, findings: list[dict[str, Any]], counter: list[dict[str, Any]], confidence: float) -> str:
    if counter:
        return f"{agent} 基于 {len(findings)} 条证据给出“{rating}”，但存在 {len(counter)} 条反证，因此置信度收敛到 {confidence}。"
    return f"{agent} 基于 {len(findings)} 条证据给出“{rating}”，暂无强反证，置信度为 {confidence}。"


def _rating_from_scores(scores: dict[str, Any]) -> str:
    if not scores:
        return "观察"
    risk = _num(scores.get("risk_pressure")) or 0
    positive = sum((_num(value) or 0) for key, value in scores.items() if key != "risk_pressure")
    if risk >= 4 or positive <= 14:
        return "回避"
    if positive >= 24 and risk <= 2:
        return "积极观察"
    return "观察"


def _date_range(full_data: dict[str, Any], opts: MultiAgentOptions) -> tuple[str, str]:
    date_range = full_data.get("date_range", {})
    end_date = date_range.get("end_date") or today_yyyymmdd()
    start_date = date_range.get("start_date")
    if not start_date:
        start_date = "19900101" if opts.full_history or opts.years is None else years_ago_yyyymmdd(opts.years)
    return str(start_date), str(end_date)


def _merge_fetch_errors(existing: list[dict[str, Any]], new_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    for error in new_errors:
        api_name = error.get("dataset") or error.get("api_name")
        if api_name and any(item.get("api_name") == api_name or item.get("dataset") == api_name for item in merged):
            continue
        merged.append(error)
    return merged


def _update_metadata_after_rebuild(base_dir: Path, full_data: dict[str, Any], changed: list[str], fetch_errors: list[dict[str, Any]]) -> None:
    metadata_path = base_dir.parent / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {"ts_code": full_data.get("ts_code")}
    metadata["dynamic_fetch_updated_at"] = timestamp()
    metadata["dynamic_fetch_changed_datasets"] = changed
    metadata["dataset_rows"] = {name: len(rows) for name, rows in full_data.get("datasets", {}).items()}
    metadata["fetch_errors"] = full_data.get("fetch_errors", []) + fetch_errors
    write_json(metadata_path, metadata)


def _analysis_type_from_run_id(run_id: str) -> str:
    for key in MODE_CONFIG:
        if run_id.endswith(key):
            return key
    return ""


def _normalize_from_full_data_or_code(code: str) -> str:
    try:
        return read_json(current_dir(code) / "full_data.json").get("ts_code") or code
    except Exception:
        from ..utils import normalize_ts_code

        return normalize_ts_code(code)


def _num(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_float(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return round(max(minimum, min(maximum, value)), 3)
