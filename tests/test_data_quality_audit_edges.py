from stock_pipeline.data_quality import audit_collection_completeness


def test_audit_caps_financial_audit_year_at_2024_even_for_newer_market_data():
    audit = audit_collection_completeness(
        {
            "date_range": {"end_date": "20260719"},
            "datasets": {
                "income": [{"end_date": "20241231"}],
                "balancesheet": [{"end_date": "20241231"}],
                "cashflow": [{"end_date": "20241231"}],
                "fina_indicator": [{"end_date": "20241231"}],
            },
        }
    )

    assert audit["audit_until_year"] == 2024


def test_audit_marks_empty_event_datasets_as_low_severity_not_high():
    audit = audit_collection_completeness({"date_range": {"end_date": "20241231"}, "datasets": {}})
    warnings = {item["dataset"]: item for item in audit["warnings"]}

    assert warnings["suspend_d"]["severity"] == "low"
    assert warnings["pledge_detail"]["severity"] == "low"
    assert warnings["daily"]["severity"] == "medium"


def test_audit_warns_when_announcements_land_exactly_on_page_boundary():
    audit = audit_collection_completeness(
        {
            "date_range": {"end_date": "20241231"},
            "datasets": {
                "anns_d": [{"ann_date": f"2024{i % 12 + 1:02d}01", "title": str(i)} for i in range(100)],
            },
        }
    )

    warning = [item for item in audit["warnings"] if item["dataset"] == "anns_d" and "分页整数边界" in item["message"]]
    assert warning
    assert warning[0]["rows"] == 100


def test_audit_uses_dataset_specific_date_keys_for_pledge_and_suspend_ranges():
    audit = audit_collection_completeness(
        {
            "date_range": {"end_date": "20241231"},
            "datasets": {
                "pledge_detail": [{"start_date": "2023-01-02"}, {"release_date": "2024-02-03"}],
                "suspend_d": [{"resume_date": "2024-03-04"}],
            },
        }
    )

    assert audit["dataset_ranges"]["pledge_detail"]["first_date"] == "20230102"
    assert audit["dataset_ranges"]["pledge_detail"]["last_date"] == "20240203"
    assert audit["dataset_ranges"]["suspend_d"]["last_date"] == "20240304"


def test_audit_ignores_nat_nan_and_malformed_dates_in_ranges():
    audit = audit_collection_completeness(
        {
            "date_range": {"end_date": "20241231"},
            "datasets": {
                "daily": [{"trade_date": "NaT"}, {"trade_date": "nan"}, {"trade_date": "bad-date"}, {"trade_date": "2024-01-02"}],
            },
        }
    )

    assert audit["dataset_ranges"]["daily"]["first_date"] == "20240102"
    assert audit["dataset_ranges"]["daily"]["last_date"] == "20240102"
    assert audit["dataset_ranges"]["daily"]["years"] == ["2024"]
