from pathlib import Path
from types import SimpleNamespace

from stock_pipeline import minute_cold_storage


def _bucket():
    return {
        "source": "pytdx_history",
        "dataset": "pytdx_history_minutes",
        "ts_code": "000001.SZ",
        "symbol": "000001",
        "trade_date": "20260627",
        "start_minute": "0930",
        "end_minute": "0931",
        "row_count": 2,
        "minutes": [
            {"minute": "0930", "price": 10.0, "volume": 100},
            {"minute": "0931", "price": 10.1, "volume": 120},
        ],
    }


class FakeFindCursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        return FakeFindCursor(self[:value])


class FakeBucketCollection:
    def __init__(self, buckets):
        self.buckets = buckets

    def find(self, query, projection=None):
        rows = []
        for bucket in self.buckets:
            if query.get("source") and bucket.get("source") != query["source"]:
                continue
            if query.get("ts_code") and bucket.get("ts_code") != query["ts_code"]:
                continue
            rows.append(bucket)
        return FakeFindCursor(rows)


class FakeIndexCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        key = (query["source"], query["ts_code"], query.get("trade_date", ""))
        doc = self.docs.get(key, {})
        doc.update(update.get("$set", {}))
        self.docs[key] = doc
        return SimpleNamespace(upserted_id=None, modified_count=1)

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        docs = [
            doc for key, doc in self.docs.items()
            if key[0] == match["source"] and key[1] == match["ts_code"]
        ]
        if not docs:
            return []
        return [
            {
                "first_trade_date": min(doc["trade_date"] for doc in docs),
                "last_trade_date": max(doc["trade_date"] for doc in docs),
                "days": len(docs),
                "rows": sum(doc["row_count"] for doc in docs),
                "complete_days": sum(1 for doc in docs if doc["status"] == "complete"),
                "partial_days": sum(1 for doc in docs if doc["status"] != "complete"),
                "bytes": sum(doc["size_bytes"] for doc in docs),
            }
        ]


class FakeCoverageCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        self.docs[(query["source"], query["ts_code"])] = update["$set"]


def test_write_bucket_object_uses_single_day_jsonl(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")

    info = minute_cold_storage.write_bucket_object(_bucket(), config)
    path = Path(info["local_path"])

    assert info["relative_path"] == "objects/000001.SZ/2026/06/20260627.jsonl"
    assert info["remote_path"] == "NewsAnalysis/cold/stock_minute/v1/objects/000001.SZ/2026/06/20260627.jsonl"
    assert path.read_text(encoding="utf-8").count("\n") == 2
    rows = minute_cold_storage.read_jsonl_rows(path)
    assert rows[0]["ts_code"] == "000001.SZ"
    assert rows[0]["minute"] == "0930"


def test_archive_buckets_updates_day_index_and_coverage(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()

    result = minute_cold_storage.archive_buckets(
        FakeBucketCollection([_bucket()]),
        day_index,
        coverage,
        query={"source": "pytdx_history", "ts_code": "000001.SZ"},
        config=config,
    )

    assert result["ok"] is True
    assert result["exported"] == 1
    indexed = day_index.docs[("pytdx_history", "000001.SZ", "20260627")]
    assert indexed["status"] == "partial"
    assert indexed["upload_status"] == "local"
    assert coverage.docs[("pytdx_history", "000001.SZ")]["archived_days"] == 1


def test_month_object_can_return_one_trade_date(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    second = _bucket()
    second["trade_date"] = "20260628"
    second["minutes"] = [{"minute": "0930", "price": 10.2, "volume": 80}]

    info = minute_cold_storage.write_month_object([_bucket(), second], config, ts_code="000001.SZ", trade_month="202606")
    path = Path(info["local_path"])

    assert info["relative_path"] == "objects_month/000001.SZ/2026/202606.jsonl"
    assert info["storage_object"] == "month_jsonl"
    assert path.read_text(encoding="utf-8").count("\n") == 2
    rows = minute_cold_storage.read_month_day_rows(path, "20260628")
    assert rows == [{"dataset": "pytdx_history_minutes", "minute": "0930", "price": 10.2, "source": "pytdx_history", "symbol": "000001", "trade_date": "20260628", "ts_code": "000001.SZ", "volume": 80}]


def test_stock_object_can_return_one_trade_date(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    second = _bucket()
    second["trade_date"] = "20260628"
    second["minutes"] = [{"minute": "0930", "price": 10.2}]

    info = minute_cold_storage.write_stock_object([_bucket(), second], config, source="pytdx_history", ts_code="000001.SZ")
    path = Path(info["local_path"])

    assert info["relative_path"] == "objects_stock/pytdx_history/000001.SZ.jsonl"
    assert info["storage_object"] == "stock_jsonl"
    assert path.read_text(encoding="utf-8").count("\n") == 2
    rows = minute_cold_storage.read_object_day_rows(path, "20260628")
    assert rows[0]["trade_date"] == "20260628"
    assert rows[0]["minute"] == "0930"
