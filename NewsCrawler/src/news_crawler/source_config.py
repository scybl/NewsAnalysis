from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    enabled: bool = True
    timeout_seconds: float = 20
    max_retries: int = 2
    request_delay_seconds: float = 0


class SourceConfigStore:
    def __init__(self, values: dict[str, SourceConfig] | None = None):
        self._values = dict(values or {})

    def get(self, source_name: str) -> SourceConfig:
        return self._values.get(source_name, SourceConfig())
