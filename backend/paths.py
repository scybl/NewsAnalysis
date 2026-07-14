from __future__ import annotations

from pathlib import Path

from stock_pipeline.config import PROJECT_ROOT


FRONTEND_ADMIN_DIR: Path = PROJECT_ROOT / "frontend" / "admin"
STATIC_DIR: Path = FRONTEND_ADMIN_DIR
AGENT_OPENAPI_PATH: Path = FRONTEND_ADMIN_DIR / "agent-openapi.json"
