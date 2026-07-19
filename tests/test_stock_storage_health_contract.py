import json

from stock_pipeline import stock_storage_repair


def test_daily_repair_dates_prioritizes_internal_then_tail_then_general_samples():
    daily = {
        "internal_missing_samples": ["2026-07-03", "20260704"],
        "tail_missing_samples": ["20260704", "20260705"],
        "missing_samples": ["20260706"],
    }

    assert stock_storage_repair._daily_repair_dates(daily, max_daily_days=4) == ["20260703", "20260704", "20260705", "20260706"]


def test_daily_repair_dates_caps_to_thirty_days_even_when_larger_limit_is_requested():
    daily = {"missing_samples": [f"202607{day:02d}" for day in range(1, 32)]}

    dates = stock_storage_repair._daily_repair_dates(daily, max_daily_days=99)

    assert len(dates) == 30
    assert dates[0] == "20260701"
    assert dates[-1] == "20260730"


def test_storage_issues_mark_daily_missing_repairable_only_when_sample_date_exists():
    repairable = _item(daily={"missing_days": 2, "missing_samples": ["20260703"]})
    not_repairable = _item(daily={"missing_days": 2, "missing_samples": ["bad"]})

    assert stock_storage_repair._storage_issues(repairable)[0]["repairable"] is True
    assert stock_storage_repair._storage_issues(not_repairable)[0]["repairable"] is False


def test_storage_issues_report_minute_and_cold_backup_failures_together():
    issues = stock_storage_repair._storage_issues(
        _item(
            minute={"missing_days": 3, "partial_days": 1},
            cold={"indexed_days": 10, "uploaded_days": 7},
        )
    )
    by_code = {issue["code"]: issue for issue in issues}

    assert by_code["minute_missing"]["count"] == 3
    assert by_code["minute_partial"]["count"] == 1
    assert by_code["cold_backup_pending"]["count"] == 3
    assert by_code["cold_backup_pending"]["repairable"] is False


def test_storage_issues_keep_unknown_health_message_when_no_structured_gap_exists():
    issues = stock_storage_repair._storage_issues(_item(health_status="warning", health_message="metadata mismatch"))

    assert issues == [{"code": "storage_health_unknown", "label": "metadata mismatch", "repairable": False}]


def test_status_summary_normalizes_missing_nested_sections_to_zero():
    summary = stock_storage_repair._status_summary({"ts_code": "000001.SZ", "name": "平安银行", "health_status": "ok"})

    assert summary["daily_missing_days"] == 0
    assert summary["minute_missing_days"] == 0
    assert summary["cold_uploaded_days"] == 0


def test_report_stock_storage_issue_writes_one_json_line(tmp_path):
    path = tmp_path / "reports" / "stock_storage.jsonl"

    result = stock_storage_repair.report_stock_storage_issue({"ts_code": "000001.SZ", "issues": ["daily_missing"]}, report_path=path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert result["ok"] is True
    assert rows[0]["report_id"] == result["report_id"]
    assert rows[0]["target"] == "stock_storage"
    assert rows[0]["payload"]["issues"] == ["daily_missing"]


def _item(*, daily=None, minute=None, cold=None, health_status="ok", health_message=""):
    return {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "health_status": health_status,
        "health_message": health_message,
        "daily_coverage": daily or {},
        "minute_coverage": minute or {},
        "cold_backup": cold or {},
    }
