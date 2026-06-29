from __future__ import annotations

from pathlib import Path

from .analysis_bridge import import_analysis_module


INITIAL_QUESTION = "请基于这份个股资料包生成股票分析。"


def session_path_for(code: str, root: Path, analysis_type: str = "general") -> Path:
    module = import_analysis_module("analyst")
    return module.session_path_for(code, root, analysis_type)


class StockAnalyst:
    def __init__(self, *args, **kwargs):
        module = import_analysis_module("analyst")
        self._inner = module.StockAnalyst(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
