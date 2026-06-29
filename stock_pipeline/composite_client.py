from __future__ import annotations

from typing import Any

from .tushare_client import TushareError, TushareResult


class FallbackStockClient:
    """Primary client with same-key fallback clients.

    The collector only sees one `query(api_name)` interface, so fallback data is
    stored under the same dataset key instead of duplicating source-specific
    keys such as `akshare_daily`.
    """

    def __init__(self, primary: Any, fallbacks: list[Any] | None = None):
        self.primary = primary
        self.fallbacks = fallbacks or []
        fallback_names = [getattr(client, "source_name", client.__class__.__name__) for client in self.fallbacks]
        self.source_name = " + ".join([getattr(primary, "source_name", primary.__class__.__name__), *fallback_names])

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        errors: list[str] = []
        empty_primary: TushareResult | None = None
        try:
            result = self.primary.query(api_name, params, fields)
            if result.records:
                return result
            empty_primary = result
        except TushareError as exc:
            errors.append(f"{getattr(self.primary, 'source_name', 'primary')}: {exc}")

        for client in self.fallbacks:
            try:
                result = client.query(api_name, params, fields)
                if result.records:
                    return result
            except TushareError as exc:
                errors.append(f"{getattr(client, 'source_name', client.__class__.__name__)}: {exc}")
                continue

        if empty_primary is not None:
            return empty_primary
        if errors:
            raise TushareError("; ".join(errors))
        return TushareResult(api_name=api_name, fields=[], records=[])
