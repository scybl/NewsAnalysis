import pytest

from stock_pipeline import stock_volume_price_metadata as metadata_module
from stock_pipeline.stock_volume_price_metadata import (
    _build_export_row,
    _volume_match_summary,
    collect_stock_volume_price_metadata,
    write_volume_price_metadata_table,
)


def test_volume_match_summary_detects_lot_to_share_factor():
    summary = _volume_match_summary(
        [
            {"trade_date": "20260708", "daily_volume": 12, "minute_volume": 1200},
            {"trade_date": "20260709", "daily_volume": 20, "minute_volume": 2000},
        ],
        tolerance=0.05,
    )

    assert summary["volume_status"] == "ok"
    assert summary["volume_checked_days"] == 2
    assert summary["volume_match_days"] == 2
    assert summary["volume_mismatch_days"] == 0
    assert summary["volume_unit_factor"] == "100"


def test_volume_match_summary_reports_mismatch_samples():
    summary = _volume_match_summary(
        [
            {"trade_date": "20260708", "daily_volume": 12, "minute_volume": 1200},
            {"trade_date": "20260709", "daily_volume": 20, "minute_volume": 500},
        ],
        tolerance=0.05,
    )

    assert summary["volume_status"] == "warning"
    assert summary["volume_checked_days"] == 2
    assert summary["volume_mismatch_days"] == 1
    assert "20260709" in summary["volume_mismatch_samples"]


def test_build_export_row_marks_clean_stock_ok():
    row = _build_export_row(
        "000001.SZ",
        {"stock_basic": {"name": "平安银行", "industry": "银行", "market": "主板", "list_date": "19910403"}},
        {"first_trade_date": "20260708", "last_trade_date": "20260709", "days": 2},
        {"expected_days": 2, "missing_days": 0, "internal_missing_days": 0, "tail_missing_days": 0},
        {"first_trade_date": "20260708", "last_trade_date": "20260709", "indexed_days": 2, "complete_days": 2, "partial_days": 0, "uploaded_days": 2, "rows": 480},
        2,
        {"volume_status": "ok", "volume_checked_days": 2, "volume_match_days": 2, "volume_mismatch_days": 0, "volume_unit_factor": "100", "volume_max_relative_error": "0"},
    )

    assert row["has_daily_k"] == "是"
    assert row["has_minute_k"] == "是"
    assert row["minute_daily_match_status"] == "ok"
    assert row["overall_status"] == "ok"


def test_build_export_row_warns_when_minute_days_do_not_match_daily():
    row = _build_export_row(
        "000001.SZ",
        {"stock_basic": {"name": "平安银行"}},
        {"first_trade_date": "20260708", "last_trade_date": "20260710", "days": 3},
        {"expected_days": 3, "missing_days": 0, "internal_missing_days": 0, "tail_missing_days": 0},
        {"first_trade_date": "20260708", "last_trade_date": "20260710", "indexed_days": 2, "complete_days": 2, "partial_days": 0, "uploaded_days": 2, "rows": 480},
        3,
        {"volume_status": "ok", "volume_checked_days": 2, "volume_match_days": 2, "volume_mismatch_days": 0},
    )

    assert row["minute_missing_vs_daily_days"] == 1
    assert row["minute_daily_match_status"] == "warning"
    assert row["overall_status"] == "warning"


def test_build_export_row_uses_daily_coverage_list_date_and_latest_indexed_date():
    row = _build_export_row(
        "000001.SZ",
        {"stock_basic": {"name": "平安银行"}},
        {},
        {
            "list_date": "19910403",
            "first_indexed_date": "20260708",
            "latest_indexed_date": "20260710",
            "indexed_days": 3,
            "expected_days": 3,
            "missing_days": 0,
        },
        {},
        0,
        {"volume_status": "unchecked", "volume_checked_days": 0},
    )

    assert row["list_date"] == "19910403"
    assert row["daily_end"] == "20260710"


def test_write_volume_price_metadata_table_outputs_csv_and_markdown(tmp_path):
    rows = [
        {
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "has_daily_k": "是",
            "has_minute_k": "是",
            "overall_status": "ok",
        }
    ]
    csv_path = tmp_path / "metadata.csv"
    md_path = tmp_path / "metadata.md"

    csv_result = write_volume_price_metadata_table(rows, csv_path, output_format="csv")
    md_result = write_volume_price_metadata_table(rows, md_path, output_format="auto")

    assert csv_result["count"] == 1
    assert "股票代码" in csv_path.read_text(encoding="utf-8-sig")
    assert "000001.SZ" in csv_path.read_text(encoding="utf-8-sig")
    assert md_result["format"] == "md"
    assert "| 股票代码 |" in md_path.read_text(encoding="utf-8")


def test_collect_uses_daily_coverage_without_full_aggregate_by_default(monkeypatch):
    monkeypatch.setattr(
        metadata_module,
        "_load_stock_metadata",
        lambda collection, codes: {"000001.SZ": {"stock_basic": {"name": "平安银行"}}},
    )
    monkeypatch.setattr(
        metadata_module,
        "_load_daily_coverage",
        lambda collection, codes: {
            "000001.SZ": {
                "first_indexed_date": "20260708",
                "last_indexed_date": "20260709",
                "indexed_days": 2,
                "expected_days": 2,
                "missing_days": 0,
            }
        },
    )

    def fail_daily_aggregate(collection, codes):
        raise AssertionError("default export should not aggregate stock_dataset_rows")

    monkeypatch.setattr(metadata_module, "_aggregate_daily_summary", fail_daily_aggregate)
    monkeypatch.setattr(metadata_module, "_load_minute_coverage", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_aggregate_minute_upload", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_aggregate_hot_minute_summary", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_daily_days_in_minute_range", lambda rows, ts_code, minute: 0)
    monkeypatch.setattr(metadata_module, "_volume_sample_summary", lambda *args, **kwargs: metadata_module._empty_volume_summary("test"))

    rows = collect_stock_volume_price_metadata(_FakeDb(), _FakeDb(), volume_sample_days=0)

    assert rows[0]["ts_code"] == "000001.SZ"
    assert rows[0]["has_daily_k"] == "是"
    assert rows[0]["daily_days"] == 2


def test_collect_can_force_daily_aggregate(monkeypatch):
    calls = {"aggregate": 0}

    monkeypatch.setattr(metadata_module, "_load_stock_metadata", lambda collection, codes: {})
    monkeypatch.setattr(metadata_module, "_load_daily_coverage", lambda collection, codes: {})

    def aggregate_daily(collection, codes):
        calls["aggregate"] += 1
        return {"000001.SZ": {"first_trade_date": "20260708", "last_trade_date": "20260709", "days": 2}}

    monkeypatch.setattr(metadata_module, "_aggregate_daily_summary", aggregate_daily)
    monkeypatch.setattr(metadata_module, "_load_minute_coverage", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_aggregate_minute_upload", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_aggregate_hot_minute_summary", lambda collection, codes, source: {})
    monkeypatch.setattr(metadata_module, "_daily_days_in_minute_range", lambda rows, ts_code, minute: 0)
    monkeypatch.setattr(metadata_module, "_volume_sample_summary", lambda *args, **kwargs: metadata_module._empty_volume_summary("test"))

    rows = collect_stock_volume_price_metadata(_FakeDb(), _FakeDb(), daily_summary_mode="aggregate", volume_sample_days=0)

    assert calls["aggregate"] == 1
    assert rows[0]["daily_start"] == "20260708"


def test_collect_rejects_unknown_daily_summary_mode():
    with pytest.raises(ValueError, match="daily_summary_mode"):
        collect_stock_volume_price_metadata(_FakeDb(), _FakeDb(), daily_summary_mode="slow")


class _FakeDb(dict):
    def __getitem__(self, name):
        return object()
