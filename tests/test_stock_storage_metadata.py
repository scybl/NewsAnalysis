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
