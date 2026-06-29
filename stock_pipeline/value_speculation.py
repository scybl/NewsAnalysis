from __future__ import annotations

from typing import Any

from .analysis_bridge import import_analysis_module


VALUE_SPECULATION_QUESTION = "请基于这份“价值投机资料包”输出研究分析。"


def build_value_speculation_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    module = import_analysis_module("value_speculation")
    return module.build_value_speculation_dossier(dossier)
