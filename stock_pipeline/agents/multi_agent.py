from __future__ import annotations

from stock_pipeline.analysis_bridge import import_analysis_module


def __getattr__(name: str):
    return getattr(import_analysis_module("agents.multi_agent"), name)
