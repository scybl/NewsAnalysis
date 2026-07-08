from stock_pipeline import stock_storage
from stock_pipeline.utils import write_json


def test_list_local_stock_summaries_uses_metadata_without_full_data(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_storage, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(stock_storage, "list_mongo_stock_metadata", lambda: {})
    stock_dir = tmp_path / "000001.SZ"
    current_dir = stock_dir / "current"
    current_dir.mkdir(parents=True)
    (current_dir / "full_data.json").write_text("{not valid json", encoding="utf-8")
    write_json(
        stock_dir / "metadata.json",
        {
            "ts_code": "000001.SZ",
            "updated_at": "20260628_120000",
            "date_range": {"start_date": "20200101", "end_date": "20260628"},
            "stock_basic": {"name": "平安银行", "industry": "银行", "market": "主板"},
            "dataset_rows": {"daily": 10, "daily_basic": 10, "minute_1m": 3},
        },
    )

    summary = stock_storage.list_local_stock_summaries()

    assert summary["count"] == 1
    assert summary["total_dataset_rows"] == 23
    assert summary["total_minute_rows"] == 3
    assert summary["items"][0]["name"] == "平安银行"
    assert summary["items"][0]["industry"] == "银行"


def test_list_local_stock_summaries_prefers_daily_date_range(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_storage, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(stock_storage, "list_mongo_stock_metadata", lambda: {})
    stock_dir = tmp_path / "000001.SZ"
    current_dir = stock_dir / "current"
    current_dir.mkdir(parents=True)
    (current_dir / "full_data.json").write_text("{not valid json", encoding="utf-8")
    write_json(
        stock_dir / "metadata.json",
        {
            "ts_code": "000001.SZ",
            "updated_at": "20260702_000155",
            "date_range": {"start_date": "19900101", "end_date": "20260701"},
            "daily_date_range": {"start_date": "20200102", "end_date": "20260701"},
            "stock_basic": {"name": "平安银行"},
            "dataset_rows": {"daily": 10},
        },
    )

    summary = stock_storage.list_local_stock_summaries()

    assert summary["items"][0]["date_range"] == {"start_date": "19900101", "end_date": "20260701"}
    assert summary["items"][0]["daily_date_range"] == {"start_date": "20200102", "end_date": "20260701"}


def test_list_local_stock_summaries_uses_bulk_mongo_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_storage, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        stock_storage,
        "list_mongo_stock_metadata",
        lambda: {
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "updated_at": "20260702_000155",
                "date_range": {"start_date": "19900101", "end_date": "20260701"},
                "daily_date_range": {"start_date": "20210104", "end_date": "20260701"},
                "stock_basic": {"name": "平安银行"},
                "dataset_rows": {"daily": 10},
            }
        },
    )

    summary = stock_storage.list_local_stock_summaries()

    assert summary["items"][0]["daily_date_range"] == {"start_date": "20210104", "end_date": "20260701"}


def test_list_local_stock_summaries_does_not_query_row_ranges(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_storage, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        stock_storage,
        "list_mongo_stock_metadata",
        lambda: {
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "updated_at": "20260702_000155",
                "date_range": {"start_date": "19900101", "end_date": "20260701"},
                "stock_basic": {"name": "平安银行"},
                "dataset_rows": {"daily": 10},
            }
        },
    )
    monkeypatch.setattr(
        stock_storage,
        "read_mongo_metadata",
        lambda ts_code: (_ for _ in ()).throw(AssertionError("per-stock metadata query should not run")),
    )

    summary = stock_storage.list_local_stock_summaries()

    assert summary["count"] == 1
    assert summary["items"][0]["daily_date_range"] == {"start_date": "19900101", "end_date": "20260701"}


def test_stock_storage_status_snapshot_combines_hot_and_cold_indexes(monkeypatch):
    monkeypatch.setattr(
        stock_storage,
        "list_local_stock_summaries",
        lambda: {
            "count": 1,
            "total_dataset_rows": 260,
            "total_minute_rows": 0,
            "items": [
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "industry": "银行",
                    "market": "主板",
                    "updated_at": "20260707_210000",
                    "dataset_count": 3,
                    "dataset_rows": {"daily": 240, "income": 20},
                    "daily_date_range": {"start_date": "20250101", "end_date": "20260707"},
                    "latest_daily_date": "20260707",
                }
            ],
        },
    )
    monkeypatch.setattr(
        stock_storage,
        "_daily_coverage_by_code",
        lambda: {
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "status": "ok",
                "last_indexed_date": "20260707",
                "missing_days": 0,
                "partial_days": 0,
                "updated_at": "2026-07-07T21:10:00Z",
            }
        },
    )
    monkeypatch.setattr(
        stock_storage,
        "_minute_coverage_by_code",
        lambda: {
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "has_minute_data": True,
                "first_trade_date": "20250102",
                "last_trade_date": "20260707",
                "archived_days": 300,
                "archived_rows": 72000,
                "partial_days": 0,
                "updated_at": "2026-07-07T22:00:00Z",
            }
        },
    )
    monkeypatch.setattr(
        stock_storage,
        "_minute_upload_by_code",
        lambda: {
            "000001.SZ": {
                "indexed_days": 300,
                "uploaded_days": 300,
                "uploaded_rows": 72000,
                "uploaded_bytes": 1024,
                "last_uploaded_date": "20260707",
            }
        },
    )

    snapshot = stock_storage.stock_storage_status_snapshot()

    item = snapshot["items"][0]
    assert item["health_status"] == "ok"
    assert item["hot_storage"]["dataset_rows"] == 260
    assert item["cold_backup"]["uploaded_days"] == 300
    assert snapshot["summary"]["cold_uploaded_days"] == 300
