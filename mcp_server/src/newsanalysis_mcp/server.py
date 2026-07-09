from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .security import redact_secrets, wait_for_terminal_job


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        print(f"[newsanalysis-mcp] missing required env var: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


BASE_URL = _required_env("NEWSANALYSIS_BASE_URL").rstrip("/")
AGENT_TOKEN = _required_env("NEWSANALYSIS_AGENT_TOKEN")
TIMEOUT_SECONDS = float(os.environ.get("NEWSANALYSIS_MCP_TIMEOUT_SECONDS", "60"))
JOB_WAIT_SECONDS = float(os.environ.get("NEWSANALYSIS_MCP_JOB_WAIT_SECONDS", "300"))

_client = httpx.Client(
    base_url=BASE_URL,
    timeout=TIMEOUT_SECONDS,
    headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
)
_public_client = httpx.Client(base_url=BASE_URL, timeout=min(TIMEOUT_SECONDS, 15.0))


def _unwrap(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except Exception:
        return {"error": True, "status": response.status_code, "text": response.text[:2000]}
    if response.status_code >= 400:
        return {"error": True, "status": response.status_code, "body": redact_secrets(body)}
    return redact_secrets(body)


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    return _unwrap(_client.get(path, params=params or {}))


def _post(path: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    return _unwrap(_client.post(path, json=payload, headers=headers or {}))


mcp = FastMCP(
    "valuescope",
    instructions=(
        "Tools for the self-hosted ValueScope DataHub A-share data platform. "
        "The configured agent token remains subject to server-side R/B scopes. "
        "Tools never expose user credentials or admin mutation. "
        "Analysis jobs consume the server DeepSeek quota; submit them only when explicitly requested."
    ),
)


@mcp.tool()
def check_health() -> Any:
    """Public Agent Gateway health check."""
    return _unwrap(_public_client.get("/api/agent/v1/health"))


@mcp.tool()
def whoami() -> Any:
    """Return the configured token identity, scopes, expiry, and rate limit."""
    return _get("/api/agent/v1/whoami")


@mcp.tool()
def search_stocks(query: str, limit: int = 20) -> Any:
    """Search A-share stocks by code, name, pinyin, or initials."""
    result = _get("/api/agent/v1/stocks/search", {"q": query})
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        result["items"] = result["items"][: max(1, min(100, int(limit)))]
    return result


@mcp.tool()
def get_stock_status(ts_code: str) -> Any:
    """Get the local data/cache status for one A-share stock."""
    return _get(f"/api/agent/v1/stocks/{ts_code}/status")


@mcp.tool()
def get_stock_data(ts_code: str) -> Any:
    """Read the existing local stock dossier and dataset summaries."""
    return _get(f"/api/agent/v1/stocks/{ts_code}/data")


@mcp.tool()
def list_jobs(limit: int = 50) -> Any:
    """List recent analysis jobs owned by the configured agent token."""
    return _get("/api/agent/v1/jobs", {"limit": max(1, min(200, int(limit)))})


@mcp.tool()
def get_job(job_id: str) -> Any:
    """Read one agent-owned analysis job."""
    return _get(f"/api/agent/v1/jobs/{job_id}")


@mcp.tool()
def wait_for_job(job_id: str, timeout_seconds: float = 300, poll_seconds: float = 1.0) -> Any:
    """Poll a job with bounded duration until it succeeds, fails, or times out."""
    return wait_for_terminal_job(
        lambda current_job_id: _get(f"/api/agent/v1/jobs/{current_job_id}"),
        job_id,
        timeout_seconds=min(max(1.0, timeout_seconds), JOB_WAIT_SECONDS),
        poll_seconds=poll_seconds,
    )


@mcp.tool()
def submit_analysis_job(
    ts_code: str,
    analysis_type: str = "value_speculation",
    idempotency_key: str = "",
) -> Any:
    """Submit a model-consuming multi-agent analysis job (B scope required)."""
    key = idempotency_key.strip() or f"{ts_code}-{analysis_type}-{uuid.uuid4().hex}"
    return _post(
        "/api/agent/v1/analysis-jobs",
        {"ts_code": ts_code, "analysis_type": analysis_type},
        {"Idempotency-Key": key},
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
