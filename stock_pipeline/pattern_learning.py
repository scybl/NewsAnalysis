from __future__ import annotations

from typing import Any

from .analysis_bridge import import_analysis_module


def build_similarity_learning(*args, **kwargs) -> dict[str, Any]:
    module = import_analysis_module("pattern_learning")
    return module.build_similarity_learning(*args, **kwargs)
