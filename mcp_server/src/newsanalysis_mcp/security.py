from __future__ import annotations

import time
from typing import Any, Callable


SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "ciphertext",
    "deepseek",
    "password",
    "secret",
    "token",
    "tushare",
}


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if str(key).lower() in SECRET_KEYS else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def wait_for_terminal_job(
    getter: Callable[[str], dict[str, Any]],
    job_id: str,
    *,
    timeout_seconds: float = 300,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = getter(job_id)
        if latest.get("error") is True:
            return latest
        if latest.get("status") in {"succeeded", "failed", "cancelled", "stopped"}:
            return latest
        time.sleep(max(0.2, min(10.0, float(poll_seconds))))
    return {
        "error": True,
        "status": "timeout",
        "job_id": job_id,
        "last_snapshot": latest,
    }
