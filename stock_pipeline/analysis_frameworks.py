from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis_bridge import import_analysis_module


VALUE_SPECULATION_QUESTION = "请基于资料包生成价值投机分析。"
VALUE_QUALITY_QUESTION = "请基于资料包生成质量成长价值分析。"
VALUE_DIVIDEND_QUESTION = "请基于资料包生成低估红利价值分析。"
OVERSOLD_REBOUND_QUESTION = "请基于资料包生成超跌反弹分析。"


@dataclass(frozen=True)
class AnalysisFramework:
    key: str
    label: str
    description: str
    question: str
    system_prompt: str = ""
    dossier_builder: object | None = None


ANALYSIS_FRAMEWORKS: dict[str, AnalysisFramework] = {
    "value_speculation": AnalysisFramework(
        key="value_speculation",
        label="价值投机",
        description="价值底线 + 催化/资金/技术时机，偏赔率和交易计划。",
        question=VALUE_SPECULATION_QUESTION,
    ),
    "value_quality": AnalysisFramework(
        key="value_quality",
        label="质量成长价值",
        description="偏中长期，评估公司质量、成长韧性和估值安全边际。",
        question=VALUE_QUALITY_QUESTION,
    ),
    "value_dividend": AnalysisFramework(
        key="value_dividend",
        label="低估红利价值",
        description="偏防御，评估低估、分红、现金流和价值陷阱风险。",
        question=VALUE_DIVIDEND_QUESTION,
    ),
    "oversold_rebound": AnalysisFramework(
        key="oversold_rebound",
        label="超跌反弹",
        description="偏短线，评估超跌程度、修复信号、资金回流和失效条件。",
        question=OVERSOLD_REBOUND_QUESTION,
    ),
}


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
    module = import_analysis_module("analysis_frameworks")
    return module.build_analysis_dossier(framework_key, dossier)


def build_all_analysis_dossiers(dossier: dict[str, Any]) -> dict[str, dict[str, Any]]:
    module = import_analysis_module("analysis_frameworks")
    return module.build_all_analysis_dossiers(dossier)
