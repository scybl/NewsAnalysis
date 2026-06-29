from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

from .config import PROJECT_ROOT


DEFAULT_ANALYSIS_PROJECT_DIR = PROJECT_ROOT.parent / "Analysis"
ANALYSIS_PACKAGE = "stock_analysis_module"


def analysis_project_dir() -> Path:
    configured = os.getenv("STOCK_ANALYSIS_PROJECT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_ANALYSIS_PROJECT_DIR


def ensure_analysis_project_path() -> None:
    project_dir = analysis_project_dir()
    path = str(project_dir)
    if project_dir.exists() and path not in sys.path:
        sys.path.insert(0, path)


def import_analysis_module(name: str) -> ModuleType:
    ensure_analysis_project_path()
    return importlib.import_module(f"{ANALYSIS_PACKAGE}.{name}")


def analysis_project_available() -> bool:
    ensure_analysis_project_path()
    try:
        importlib.import_module(ANALYSIS_PACKAGE)
    except ImportError:
        return False
    return True


def require_analysis_project() -> None:
    if not analysis_project_available():
        raise RuntimeError(
            "分析项目不可用：请设置 STOCK_ANALYSIS_PROJECT_DIR，"
            f"或确认独立分析项目存在于 {DEFAULT_ANALYSIS_PROJECT_DIR}。"
        )
