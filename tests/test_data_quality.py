from __future__ import annotations

from stock_pipeline.data_quality import audit_collection_completeness


def test_audit_flags_recent_only_daily_when_monthly_has_older_history():
    full_data = {
        "date_range": {"start_date": "19900101", "end_date": "20260626", "full_history": True},
        "datasets": {
            "daily": [{"trade_date": "20250102"}],
            "daily_basic": [{"trade_date": "20250102"}],
            "monthly": [{"trade_date": "19910131"}, {"trade_date": "20260625"}],
            "income": _financial_rows(2019, 2024),
            "balancesheet": _financial_rows(2019, 2024),
            "cashflow": _financial_rows(2019, 2024),
            "fina_indicator": _financial_rows(2019, 2024),
            "adj_factor": [{"trade_date": "20250102"}],
            "fina_mainbz": [{"end_date": "20241231"}],
            "anns_d": [{"ann_date": "20240101"}],
            "dividend": [{"end_date": "20231231"}],
            "top10_holders": [{"end_date": "20240331"}],
            "top10_floatholders": [{"end_date": "20240331"}],
            "stk_holdernumber": [{"end_date": "20240331"}],
        },
    }

    audit = audit_collection_completeness(full_data)

    assert audit["status"] == "partial"
    assert any(warning["dataset"] == "daily" and warning["severity"] == "high" for warning in audit["warnings"])


def test_audit_accepts_complete_recent_financial_quarters_until_2024():
    full_data = {
        "date_range": {"start_date": "19900101", "end_date": "20260626", "full_history": True},
        "datasets": {
            "daily": [{"trade_date": "19910102"}, {"trade_date": "20260625"}],
            "daily_basic": [{"trade_date": "19910102"}, {"trade_date": "20260625"}],
            "monthly": [{"trade_date": "19910131"}, {"trade_date": "20260625"}],
            "income": _financial_rows(2019, 2024),
            "balancesheet": _financial_rows(2019, 2024),
            "cashflow": _financial_rows(2019, 2024),
            "fina_indicator": _financial_rows(2019, 2024),
            "adj_factor": [{"trade_date": "19910102"}, {"trade_date": "20260625"}],
            "fina_mainbz": [{"end_date": "20241231"}],
            "anns_d": [{"ann_date": "20240101"}],
            "dividend": [{"end_date": "20231231"}],
            "top10_holders": [{"end_date": "20240331"}],
            "top10_floatholders": [{"end_date": "20240331"}],
            "stk_holdernumber": [{"end_date": "20240331"}],
        },
    }

    audit = audit_collection_completeness(full_data)

    assert not [warning for warning in audit["warnings"] if warning["severity"] == "high"]


def test_audit_ignores_pre_listing_financial_quarter_gaps():
    full_data = {
        "date_range": {"start_date": "19900101", "end_date": "20260626", "full_history": True},
        "datasets": {
            "stock_basic": [{"list_date": "20220222"}],
            "daily": [{"trade_date": "20220222"}, {"trade_date": "20260625"}],
            "daily_basic": [{"trade_date": "20220222"}, {"trade_date": "20260625"}],
            "monthly": [{"trade_date": "20220228"}, {"trade_date": "20260625"}],
            "income": [{"end_date": "20191231"}, {"end_date": "20201231"}, *_financial_rows(2022, 2024)],
            "balancesheet": [{"end_date": "20191231"}, {"end_date": "20201231"}, *_financial_rows(2022, 2024)],
            "cashflow": [{"end_date": "20191231"}, {"end_date": "20201231"}, *_financial_rows(2022, 2024)],
            "fina_indicator": [{"end_date": "20191231"}, {"end_date": "20201231"}, *_financial_rows(2022, 2024)],
            "adj_factor": [{"trade_date": "20220222"}, {"trade_date": "20260625"}],
            "fina_mainbz": [{"end_date": "20241231"}],
            "anns_d": [{"ann_date": "20240101"}],
            "dividend": [{"end_date": "20231231"}],
            "top10_holders": [{"end_date": "20240331"}],
            "top10_floatholders": [{"end_date": "20240331"}],
            "stk_holdernumber": [{"end_date": "20240331"}],
        },
    }

    audit = audit_collection_completeness(full_data)

    financial_warnings = [warning for warning in audit["warnings"] if warning["dataset"] in {"income", "balancesheet", "cashflow", "fina_indicator"}]
    assert financial_warnings == []
    assert audit["financial_coverage"]["income"]["audit_from_year"] == 2022


def _financial_rows(start_year: int, end_year: int) -> list[dict[str, str]]:
    rows = []
    for year in range(start_year, end_year + 1):
        for quarter in ("0331", "0630", "0930", "1231"):
            rows.append({"end_date": f"{year}{quarter}"})
    return rows
