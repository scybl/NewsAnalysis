from __future__ import annotations

from stock_pipeline.analysis_bridge import import_analysis_module


def _multi_agent():
    return import_analysis_module("agents.multi_agent")


class MultiAgentRunner:
    def __new__(cls, *args, **kwargs):
        return _multi_agent().MultiAgentRunner(*args, **kwargs)


class LangGraphMultiAgentRunner:
    def __new__(cls, *args, **kwargs):
        return _multi_agent().LangGraphMultiAgentRunner(*args, **kwargs)


def list_agent_runs(*args, **kwargs):
    return _multi_agent().list_agent_runs(*args, **kwargs)


def read_agent_run(*args, **kwargs):
    return _multi_agent().read_agent_run(*args, **kwargs)


__all__ = ["LangGraphMultiAgentRunner", "MultiAgentRunner", "list_agent_runs", "read_agent_run"]
