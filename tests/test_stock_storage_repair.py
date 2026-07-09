from stock_pipeline import stock_storage_repair


def _storage_item(*, health="warning", daily_missing=1, minute_missing=0, cold_uploaded=10, cold_indexed=10):
    return {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "health_status": health,
        "health_message": "日K缺口 1 天",
        "daily_coverage": {
            "missing_days": daily_missing,
            "partial_days": 0,
            "internal_missing_samples": ["20260703"],
            "tail_missing_samples": [],
            "missing_samples": ["20260703"],
        },
        "minute_coverage": {"missing_days": minute_missing, "partial_days": 0},
        "cold_backup": {"uploaded_days": cold_uploaded, "indexed_days": cold_indexed},
    }


def test_repair_stock_storage_issue_fills_daily_samples_and_reports_remaining(monkeypatch, tmp_path):
    snapshots = [
        {"items": [_storage_item(minute_missing=2, cold_uploaded=8, cold_indexed=10)]},
        {"items": [_storage_item(daily_missing=0, minute_missing=2, cold_uploaded=8, cold_indexed=10)]},
    ]
    repairs = []

    monkeypatch.setattr(stock_storage_repair, "stock_storage_status_snapshot", lambda **_: snapshots.pop(0))
    monkeypatch.setattr(
        stock_storage_repair,
        "sync_daily_market_for_stock",
        lambda _client, code, date: repairs.append((code, date)) or {"ok": True, "ts_code": code, "target_date": date, "status": "updated"},
    )
    monkeypatch.setattr(stock_storage_repair, "_refresh_daily_k_coverage_safe", lambda codes, _date: {"ok": True, "codes": codes})

    result = stock_storage_repair.repair_stock_storage_issue(object(), "000001.SZ", report_path=tmp_path / "reports.jsonl")

    assert repairs == [("000001.SZ", "20260703")]
    assert result["status"] == "partially_repaired"
    assert result["resolved"] is False
    assert result["report"]["report_id"].startswith("stock_storage_")
    assert "minute_missing" in {item["code"] for item in result["issues_after"]}
    assert (tmp_path / "reports.jsonl").read_text(encoding="utf-8")


def test_repair_stock_storage_issue_skips_normal_stock(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_storage_repair, "stock_storage_status_snapshot", lambda **_: {"items": [_storage_item(health="ok", daily_missing=0)]})
    monkeypatch.setattr(
        stock_storage_repair,
        "sync_daily_market_for_stock",
        lambda *_: (_ for _ in ()).throw(AssertionError("normal stocks should not be repaired")),
    )

    result = stock_storage_repair.repair_stock_storage_issue(object(), "000001.SZ", report_path=tmp_path / "reports.jsonl")

    assert result["status"] == "ok"
    assert result["resolved"] is True
    assert not (tmp_path / "reports.jsonl").exists()


def test_run_stock_storage_health_check_samples_and_reports_checks(monkeypatch):
    monkeypatch.setattr(
        stock_storage_repair,
        "list_local_stock_summaries",
        lambda: {
            "items": [
                {"ts_code": "000001.SZ"},
                {"ts_code": "000002.SZ"},
                {"ts_code": "000003.SZ"},
            ]
        },
    )
    monkeypatch.setattr(stock_storage_repair, "_refresh_daily_k_coverage_safe", lambda codes, _date: {"ok": True, "stocks_checked": len(codes)})
    monkeypatch.setattr(
        stock_storage_repair,
        "compare_minute_cold_backup_samples",
        lambda **kwargs: {
            "ok": True,
            "status": "ok",
            "sample_size": kwargs["sample_size"],
            "checked_count": kwargs["sample_size"],
            "differences": 0,
            "samples": [],
        },
    )
    monkeypatch.setattr(
        stock_storage_repair,
        "stock_storage_status_snapshot",
        lambda **kwargs: {
            "items": [
                {"ts_code": kwargs["codes"][0], "name": "样本", "health_status": "warning", "health_message": "日K缺口 1 天"},
                {"ts_code": kwargs["codes"][1], "name": "样本2", "health_status": "ok", "health_message": ""},
            ]
        },
    )

    result = stock_storage_repair.run_stock_storage_health_check(sample_size=2, seed=7)

    assert result["candidate_count"] == 3
    assert result["checked_count"] == 2
    assert result["abnormal_count"] == 1
    assert "日K覆盖是否存在缺口或部分异常" in result["checks"]
    assert "冷备份取回后与新抓同日分时数据是否一致" in result["checks"]
    assert result["coverage_refresh"]["stocks_checked"] == 2
    assert result["cold_compare"]["status"] == "ok"


def test_compare_minute_cold_backup_samples_matches_injected_rows():
    rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.2, "volume": 200},
    ]
    result = stock_storage_repair.compare_minute_cold_backup_samples(
        day_index=object(),
        sample_docs=[{"ts_code": "000001.SZ", "trade_date": "20260703", "row_count": 2}],
        cold_reader=lambda *_: rows,
        fresh_fetcher=lambda *_: {"rows": list(rows), "succeeded_days": 1},
    )

    assert result["status"] == "ok"
    assert result["differences"] == 0
    assert result["samples"][0]["result"] == "matched"


def test_compare_minute_cold_backup_samples_reports_missing_cold_minutes():
    cold_rows = [{"minute": "09:31", "price": 10.1, "volume": 100}]
    fresh_rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.2, "volume": 200},
    ]
    result = stock_storage_repair.compare_minute_cold_backup_samples(
        day_index=object(),
        sample_docs=[{"ts_code": "000001.SZ", "trade_date": "20260703", "row_count": 1}],
        cold_reader=lambda *_: cold_rows,
        fresh_fetcher=lambda *_: {"rows": fresh_rows, "succeeded_days": 1},
    )

    sample = result["samples"][0]
    assert result["status"] == "failed"
    assert sample["result"] == "cold_missing_minutes"
    assert sample["missing_in_cold"] == ["09:32"]
    assert "最初抓取" in sample["reason"]


def test_compare_minute_cold_backup_samples_reports_value_mismatch():
    cold_rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.2, "volume": 200},
    ]
    fresh_rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.25, "volume": 200},
    ]
    result = stock_storage_repair.compare_minute_cold_backup_samples(
        day_index=object(),
        sample_docs=[{"ts_code": "000001.SZ", "trade_date": "20260703", "row_count": 2}],
        cold_reader=lambda *_: cold_rows,
        fresh_fetcher=lambda *_: {"rows": fresh_rows, "succeeded_days": 1},
    )

    sample = result["samples"][0]
    assert sample["result"] == "value_mismatch"
    assert sample["value_mismatches"][0]["minute"] == "09:32"
    assert sample["value_mismatches"][0]["fields"]["price"] == {"cold": 10.2, "fresh": 10.25}


def test_compare_minute_cold_backup_samples_reports_index_mismatch_before_fresh_diff():
    cold_rows = [{"minute": "09:31", "price": 10.1, "volume": 100}]
    fresh_rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.2, "volume": 200},
    ]
    result = stock_storage_repair.compare_minute_cold_backup_samples(
        day_index=object(),
        sample_docs=[{"ts_code": "000001.SZ", "trade_date": "20260703", "row_count": 2}],
        cold_reader=lambda *_: cold_rows,
        fresh_fetcher=lambda *_: {"rows": fresh_rows, "succeeded_days": 1},
    )

    sample = result["samples"][0]
    assert sample["result"] == "index_cold_count_mismatch"
    assert "索引记录不一致" in sample["reason"]


def test_compare_minute_cold_backup_samples_keeps_fresh_empty_as_warning():
    cold_rows = [
        {"minute": "09:31", "price": 10.1, "volume": 100},
        {"minute": "09:32", "price": 10.2, "volume": 200},
    ]
    result = stock_storage_repair.compare_minute_cold_backup_samples(
        day_index=object(),
        sample_docs=[{"ts_code": "000001.SZ", "trade_date": "20260703", "row_count": 2}],
        cold_reader=lambda *_: cold_rows,
        fresh_fetcher=lambda *_: {"rows": [], "succeeded_days": 0, "failures": [{"trade_date": "20260703", "error": "empty"}]},
    )

    sample = result["samples"][0]
    assert result["ok"] is True
    assert result["status"] == "warning"
    assert sample["result"] == "fresh_no_data"
    assert sample["fresh_failures"] == [{"trade_date": "20260703", "error": "empty"}]
