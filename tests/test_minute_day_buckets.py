from datetime import datetime, timezone

from stock_pipeline import ths_minute


class FakeUpdateResult:
    def __init__(self, *, upserted_id=None, modified_count=0):
        self.upserted_id = upserted_id
        self.modified_count = modified_count


class FakeBucketCollection:
    name = "minute_day_buckets"

    def __init__(self):
        self.docs = {}

    def find_one(self, query, projection=None):
        return self.docs.get((query["source"], query["ts_code"], query["trade_date"]))

    def update_one(self, query, update, upsert=False):
        key = (query["source"], query["ts_code"], query["trade_date"])
        existed = key in self.docs
        self.docs[key] = update["$set"]
        return FakeUpdateResult(upserted_id=None if existed else "new", modified_count=1 if existed else 0)


def test_minute_rows_are_bucketed_by_stock_and_trade_date():
    fetched_at = datetime(2026, 6, 28, tzinfo=timezone.utc)
    rows = [
        {"source": "pytdx_history", "dataset": "pytdx_history_minutes", "ts_code": "000001.SZ", "symbol": "000001", "trade_date": "20260627", "minute": "0931", "price": 10.1, "fetched_at": fetched_at},
        {"source": "pytdx_history", "dataset": "pytdx_history_minutes", "ts_code": "000001.SZ", "symbol": "000001", "trade_date": "20260627", "minute": "0930", "price": 10.0, "fetched_at": fetched_at},
        {"source": "pytdx_history", "dataset": "pytdx_history_minutes", "ts_code": "000001.SZ", "symbol": "000001", "trade_date": "20260628", "minute": "0930", "price": 10.2, "fetched_at": fetched_at},
    ]

    buckets = ths_minute._minute_day_buckets(rows)

    assert len(buckets) == 2
    first = next(bucket for bucket in buckets if bucket["trade_date"] == "20260627")
    assert first["row_count"] == 2
    assert first["start_minute"] == "0930"
    assert first["end_minute"] == "0931"
    assert [row["minute"] for row in first["minutes"]] == ["0930", "0931"]
    assert all("ts_code" not in row for row in first["minutes"])


def test_upsert_minute_rows_uses_one_document_per_stock_day():
    collection = FakeBucketCollection()
    rows = [
        {"source": "pytdx_history", "dataset": "pytdx_history_minutes", "ts_code": "000001.SZ", "trade_date": "20260627", "minute": "0930", "price": 10.0},
        {"source": "pytdx_history", "dataset": "pytdx_history_minutes", "ts_code": "000001.SZ", "trade_date": "20260627", "minute": "0931", "price": 10.1},
    ]

    inserted, updated = ths_minute.upsert_minute_rows(collection, rows)
    inserted_again, updated_again = ths_minute.upsert_minute_rows(collection, rows)

    assert inserted == 2
    assert updated == 0
    assert inserted_again == 0
    assert updated_again == 2
    assert len(collection.docs) == 1
