from __future__ import annotations

import math
from typing import Any

from .tushare_client import TushareError, TushareResult


DATE_KEY_BY_API = {
    "stock_basic": ("ts_code",),
    "stock_company": ("ts_code",),
    "daily": ("trade_date",),
    "weekly": ("trade_date",),
    "monthly": ("trade_date",),
    "daily_basic": ("trade_date",),
    "adj_factor": ("trade_date",),
    "stk_limit": ("trade_date",),
    "suspend_d": ("suspend_date",),
    "moneyflow": ("trade_date",),
    "margin_detail": ("trade_date",),
    "income": ("end_date",),
    "balancesheet": ("end_date",),
    "cashflow": ("end_date",),
    "fina_indicator": ("end_date",),
    "express": ("end_date",),
    "forecast": ("end_date",),
    "dividend": ("ann_date", "end_date"),
    "fina_mainbz": ("end_date",),
    "fina_audit": ("end_date",),
    "top10_holders": ("end_date", "holder_name"),
    "top10_floatholders": ("end_date", "holder_name"),
    "stk_holdernumber": ("end_date",),
    "stk_holdertrade": ("ann_date", "holder_name"),
    "pledge_stat": ("end_date",),
    "pledge_detail": ("ann_date", "holder_name"),
    "share_float": ("float_date",),
    "block_trade": ("trade_date",),
    "anns_d": ("ann_date", "title"),
}

REQUIRED_FIELDS_BY_API = {
    "stock_basic": ("ts_code", "name", "list_date"),
    "stock_company": ("ts_code", "com_name"),
    "daily": ("trade_date", "open", "high", "low", "close", "vol", "amount"),
    "weekly": ("trade_date", "open", "high", "low", "close", "vol", "amount"),
    "monthly": ("trade_date", "open", "high", "low", "close", "vol", "amount"),
    "daily_basic": ("trade_date", "close", "turnover_rate"),
    "moneyflow": ("trade_date", "net_mf_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount"),
    "income": ("end_date", "total_revenue", "n_income"),
    "balancesheet": ("end_date", "total_assets", "total_liab"),
    "cashflow": ("end_date", "n_cashflow_act"),
    "fina_indicator": ("end_date", "roe", "debt_to_assets"),
    "dividend": ("ann_date", "cash_div"),
    "anns_d": ("ann_date", "title", "url"),
    "stk_holdernumber": ("end_date", "holder_num"),
    "share_float": ("float_date", "float_share"),
    "top10_holders": ("end_date", "holder_name", "hold_amount", "hold_ratio"),
}

MERGEABLE_APIS = {
    "daily_basic",
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "dividend",
    "anns_d",
    "stock_basic",
    "stock_company",
    "stk_holdernumber",
    "share_float",
    "top10_holders",
}

SAFE_EMPTY_APIS = {
    "suspend_d",
    "disclosure_date",
    "pledge_stat",
    "pledge_detail",
    "repurchase",
    "sw_daily",
}


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

        empty_fallback: TushareResult | None = None
        for client in self.fallbacks:
            try:
                result = client.query(api_name, params, fields)
                if result.records:
                    return result
                if empty_fallback is None:
                    empty_fallback = result
            except TushareError as exc:
                errors.append(f"{getattr(client, 'source_name', client.__class__.__name__)}: {exc}")
                continue

        if empty_primary is not None:
            return empty_primary
        if api_name in SAFE_EMPTY_APIS and empty_fallback is not None:
            return empty_fallback
        if errors:
            raise TushareError("; ".join(errors))
        return TushareResult(api_name=api_name, fields=[], records=[])


class ValidatingStockClient:
    """Primary AkShare client with validator/fallback clients.

    Public data sources are uneven: a source may return rows with missing key
    fields, while another source may have only a subset.  This client keeps the
    primary source when it is usable, fills same-key gaps from validators for
    merge-safe datasets, and falls back to a validator when the primary is empty
    or materially lower quality.
    """

    def __init__(self, primary: Any, validators: list[Any] | None = None, *, min_fill_rate: float = 0.7):
        self.primary = primary
        self.validators = validators or []
        self.min_fill_rate = min_fill_rate
        validator_names = [getattr(client, "source_name", client.__class__.__name__) for client in self.validators]
        self.source_name = " + ".join([getattr(primary, "source_name", primary.__class__.__name__), *validator_names])

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        errors: list[str] = []
        primary_result = self._query_one(self.primary, api_name, params, fields, errors)
        if primary_result is None or not primary_result.records:
            return self._first_validator_result(api_name, params, fields, errors, empty_primary=primary_result)

        best_result = primary_result
        best_score = _quality_score(api_name, primary_result.records)
        should_validate = api_name in REQUIRED_FIELDS_BY_API or best_score[1] < self.min_fill_rate
        if not should_validate:
            return primary_result

        for client in self.validators:
            validator_result = self._query_one(client, api_name, params, fields, errors)
            if validator_result is None or not validator_result.records:
                continue
            validator_score = _quality_score(api_name, validator_result.records)
            if api_name in MERGEABLE_APIS:
                merged = _merge_records(api_name, best_result.records, validator_result.records)
                merged_score = _quality_score(api_name, merged)
                if merged_score >= best_score:
                    best_result = _result(api_name, merged)
                    best_score = merged_score
                    continue
            if validator_score > best_score and best_score[1] < self.min_fill_rate:
                best_result = validator_result
                best_score = validator_score

        return best_result

    def _first_validator_result(
        self,
        api_name: str,
        params: dict[str, Any] | None,
        fields: str,
        errors: list[str],
        *,
        empty_primary: TushareResult | None,
    ) -> TushareResult:
        empty_validator: TushareResult | None = None
        for client in self.validators:
            result = self._query_one(client, api_name, params, fields, errors)
            if result is not None and result.records:
                return result
            if result is not None and empty_validator is None:
                empty_validator = result
        if empty_primary is not None:
            return empty_primary
        if api_name in SAFE_EMPTY_APIS and empty_validator is not None:
            return empty_validator
        if errors:
            raise TushareError("; ".join(errors))
        return TushareResult(api_name=api_name, fields=[], records=[])

    def _query_one(
        self,
        client: Any,
        api_name: str,
        params: dict[str, Any] | None,
        fields: str,
        errors: list[str],
    ) -> TushareResult | None:
        try:
            return client.query(api_name, params, fields)
        except TushareError as exc:
            errors.append(f"{getattr(client, 'source_name', client.__class__.__name__)}: {exc}")
            return None


def _quality_score(api_name: str, records: list[dict[str, Any]]) -> tuple[int, float, int]:
    required = REQUIRED_FIELDS_BY_API.get(api_name, ())
    if not records:
        return (0, 0.0, 0)
    if not required:
        return (1, 1.0, len(records))
    total = len(records) * len(required)
    filled = sum(1 for row in records for field in required if _present(row.get(field)))
    return (1, filled / total if total else 1.0, len(records))


def _merge_records(api_name: str, primary: list[dict[str, Any]], validator: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = DATE_KEY_BY_API.get(api_name)
    if not keys:
        return primary
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in primary:
        key = _row_key(row, keys)
        if key:
            merged[key] = dict(row)
        else:
            passthrough.append(dict(row))
    for row in validator:
        key = _row_key(row, keys)
        if not key:
            passthrough.append(dict(row))
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = dict(row)
        else:
            merged[key] = _fill_missing_values(current, row)
    return sorted(merged.values(), key=lambda row: _sort_key(api_name, row), reverse=True) + passthrough


def _fill_missing_values(primary: dict[str, Any], validator: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    filled = False
    for key, value in validator.items():
        if key == "source":
            continue
        if not _present(merged.get(key)) and _present(value):
            merged[key] = value
            filled = True
    if filled:
        source = str(merged.get("source") or "")
        validator_source = str(validator.get("source") or "")
        if validator_source and validator_source not in source:
            merged["source"] = f"{source}+validated:{validator_source}" if source else validator_source
    return merged


def _row_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, ...] | None:
    values = tuple(str(row.get(key) or "").strip() for key in keys)
    return values if all(values) else None


def _sort_key(api_name: str, row: dict[str, Any]) -> str:
    keys = DATE_KEY_BY_API.get(api_name) or ()
    for key in keys:
        if "date" in key:
            return str(row.get(key) or "")
    return "|".join(str(row.get(key) or "") for key in keys)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return False
    return str(value) not in {"", "nan", "NaT", "None"}


def _result(api_name: str, records: list[dict[str, Any]]) -> TushareResult:
    return TushareResult(api_name=api_name, fields=sorted({key for row in records for key in row}), records=records)
