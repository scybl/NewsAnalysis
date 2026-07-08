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
        self.find_queries = []

    def find(self, query, projection=None):
        self.find_queries.append(query)
        rows = []
        for bucket in self.buckets:
            if query.get("source") and bucket.get("source") != query["source"]:
                continue
            ts_code_filter = query.get("ts_code")
            if isinstance(ts_code_filter, dict) and "$in" in ts_code_filter and bucket.get("ts_code") not in ts_code_filter["$in"]:
                continue
            if isinstance(ts_code_filter, str) and bucket.get("ts_code") != ts_code_filter:
                continue
            trade_date_filter = query.get("trade_date")
            if isinstance(trade_date_filter, str) and bucket.get("trade_date") != trade_date_filter:
                continue
            if isinstance(trade_date_filter, dict):
                trade_date = str(bucket.get("trade_date") or "")
                if "$gte" in trade_date_filter and trade_date < trade_date_filter["$gte"]:
                    continue
                if "$lte" in trade_date_filter and trade_date > trade_date_filter["$lte"]:
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

    def find_one(self, query, projection=None):
        rows = self.find(query, projection)
        return rows[0] if rows else None

    def count_documents(self, query):
        total = 0
        trade_dates = set((query.get("trade_date") or {}).get("$in") or [])
        for key, doc in self.docs.items():
            if query.get("source") and key[0] != query["source"]:
                continue
            if query.get("ts_code") and key[1] != query["ts_code"]:
                continue
            if trade_dates and key[2] not in trade_dates:
                continue
            if query.get("relative_path") and doc.get("relative_path") != query["relative_path"]:
                continue
            storage_filter = query.get("storage_object")
            if isinstance(storage_filter, dict) and "$in" in storage_filter and doc.get("storage_object") not in storage_filter["$in"]:
                continue
            if isinstance(storage_filter, str) and doc.get("storage_object") != storage_filter:
                continue
            if query.get("upload_status") and doc.get("upload_status") != query["upload_status"]:
                continue
            total += 1
        return total

    def find(self, query, projection=None):
        rows = []
        for key, doc in self.docs.items():
            if query.get("source") and key[0] != query["source"]:
                continue
            if query.get("ts_code") and key[1] != query["ts_code"]:
                continue
            trade_date_filter = query.get("trade_date")
            if isinstance(trade_date_filter, dict):
                if "$gte" in trade_date_filter and key[2] < trade_date_filter["$gte"]:
                    continue
                if "$lte" in trade_date_filter and key[2] > trade_date_filter["$lte"]:
                    continue
            rows.append({"source": key[0], "ts_code": key[1], "trade_date": key[2], **doc})
        return FakeFindCursor(rows)

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

    def distinct(self, field, query):
        if field != "ts_code":
            return []
        return sorted({ts_code for source, ts_code in self.docs if not query.get("source") or source == query["source"]})


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


def test_inspect_minute_coverage_gaps_reports_missing_partial_and_unuploaded_days():
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()
    coverage.docs[("pytdx_history", "000001.SZ")] = {"ts_code": "000001.SZ"}
    day_index.docs[("pytdx_history", "000001.SZ", "20260102")] = {
        "trade_date": "20260102",
        "status": "complete",
        "row_count": 240,
        "upload_status": "uploaded",
    }
    day_index.docs[("pytdx_history", "000001.SZ", "20260105")] = {
        "trade_date": "20260105",
        "status": "partial",
        "row_count": 100,
        "upload_status": "local",
    }
    day_index.docs[("pytdx_history", "000001.SZ", "20260106")] = {
        "trade_date": "20260106",
        "status": "complete",
        "row_count": 240,
        "upload_status": "uploaded",
    }

    result = minute_cold_storage.inspect_minute_coverage_gaps(
        day_index,
        coverage,
        source="pytdx_history",
        codes=["000001.SZ"],
        reference_loader=lambda code: ["20260102", "20260105", "20260106", "20260107"],
    )

    item = result["items"][0]
    assert result["stocks_checked"] == 1
    assert result["missing_days"] == 1
    assert result["partial_days"] == 1
    assert result["unuploaded_days"] == 1
    assert item["last_indexed_date"] == "20260106"
    assert item["missing_samples"] == ["20260107"]
    assert item["tail_missing_samples"] == ["20260107"]
    assert item["partial_samples"] == ["20260105"]
    assert item["unuploaded_samples"] == ["20260105"]


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


def test_archive_complete_month_upload_skips_incomplete_month(monkeypatch, tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _complete_bucket("20260627")
    bucket_collection = FakeBucketCollection([first])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()
    monkeypatch.setattr(minute_cold_storage, "_local_reference_trade_dates", lambda code: ["20260627", "20260628"])

    result = minute_cold_storage.archive_month_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
        upload=True,
        complete_months_only=True,
        closed_months_only=True,
        runner=lambda args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert result["ok"] is True
    assert result["exported_days"] == 0
    assert result["uploaded_files"] == 0
    assert result["skipped_months"] == 1
    assert day_index.docs == {}


def test_archive_complete_month_upload_writes_complete_closed_month(monkeypatch, tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _complete_bucket("20260627")
    second = _complete_bucket("20260628")
    bucket_collection = FakeBucketCollection([first, second])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()
    uploads = []
    monkeypatch.setattr(minute_cold_storage, "_local_reference_trade_dates", lambda code: ["20260627", "20260628"])

    result = minute_cold_storage.archive_month_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
        upload=True,
        complete_months_only=True,
        closed_months_only=True,
        runner=lambda args: uploads.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert result["ok"] is True
    assert result["exported_days"] == 2
    assert result["uploaded_files"] == 1
    assert result["skipped_months"] == 0
    assert uploads
    assert day_index.docs[("pytdx_history", "000001.SZ", "20260627")]["storage_object"] == "month_jsonl"
    assert day_index.docs[("pytdx_history", "000001.SZ", "20260628")]["upload_status"] == "uploaded"


def test_archive_complete_months_as_stock_year_upload_writes_year_object(monkeypatch, tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _complete_bucket("20260627")
    second = _complete_bucket("20260628")
    open_month = _complete_bucket("20260701")
    bucket_collection = FakeBucketCollection([first, second, open_month])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()
    uploads = []
    monkeypatch.setattr(minute_cold_storage, "_local_reference_trade_dates", lambda code: ["20260627", "20260628", "20260701"])

    result = minute_cold_storage.archive_complete_months_as_stock_year_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
        upload=True,
        runner=lambda args: uploads.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert result["ok"] is True
    assert result["exported_days"] == 2
    assert result["skipped_days"] == 1
    assert result["skipped_months"] == 1
    assert result["uploaded_files"] == 1
    assert result["storage_object"] == "stock_year_jsonl"
    assert uploads[0][-1] == "NewsAnalysis/cold/stock_minute/v1/objects_stock_year/pytdx_history/000001.SZ/2026.jsonl"
    assert day_index.docs[("pytdx_history", "000001.SZ", "20260627")]["storage_object"] == "stock_year_jsonl"
    assert ("pytdx_history", "000001.SZ", "20260701") not in day_index.docs


def test_archive_complete_month_upload_skips_open_month(monkeypatch, tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _complete_bucket("20260701")
    bucket_collection = FakeBucketCollection([first])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()
    monkeypatch.setattr(minute_cold_storage, "_local_reference_trade_dates", lambda code: ["20260701"])

    result = minute_cold_storage.archive_month_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
        upload=True,
        complete_months_only=True,
        closed_months_only=True,
        runner=lambda args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert result["exported_days"] == 0
    assert result["uploaded_files"] == 0
    assert result["skipped_months"] == 1
    assert day_index.docs == {}


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


def test_stock_year_object_can_return_one_trade_date(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    second = _bucket()
    second["trade_date"] = "20261228"
    second["minutes"] = [{"minute": "0930", "price": 10.2}]

    info = minute_cold_storage.write_stock_year_object(
        [_bucket(), second],
        config,
        source="pytdx_history",
        ts_code="000001.SZ",
        trade_year="2026",
    )
    path = Path(info["local_path"])

    assert info["relative_path"] == "objects_stock_year/pytdx_history/000001.SZ/2026.jsonl"
    assert info["storage_object"] == "stock_year_jsonl"
    assert info["object_trade_year"] == "2026"
    assert path.read_text(encoding="utf-8").count("\n") == 2
    rows = minute_cold_storage.read_object_day_rows(path, "20261228")
    assert rows[0]["trade_date"] == "20261228"
    assert rows[0]["minute"] == "0930"


def test_read_cached_or_downloaded_day_downloads_stock_year_object_and_reuses_cache(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    second = _bucket()
    second["trade_date"] = "20261228"
    second["minutes"] = [{"minute": "0930", "price": 10.2}]
    info = minute_cold_storage.write_stock_year_object(
        [_bucket(), second],
        config,
        source="pytdx_history",
        ts_code="000001.SZ",
        trade_year="2026",
    )
    day_index = FakeIndexCollection()
    minute_cold_storage.upsert_day_index(day_index, second, info, upload_status="uploaded")
    remote_source = Path(info["local_path"])
    cache_path = config.cache_root / info["relative_path"]
    downloads = []

    def fake_download(args):
        downloads.append(args)
        Path(args[-1]).write_bytes(remote_source.read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    rows = minute_cold_storage.read_cached_or_downloaded_day(
        day_index,
        source="pytdx_history",
        ts_code="000001.SZ",
        trade_date="20261228",
        config=config,
        runner=fake_download,
    )

    assert rows == [
        {
            "dataset": "pytdx_history_minutes",
            "minute": "0930",
            "price": 10.2,
            "source": "pytdx_history",
            "symbol": "000001",
            "trade_date": "20261228",
            "ts_code": "000001.SZ",
        }
    ]
    assert downloads == [[config.bdpan_bin, "--no-check-update", "download", info["remote_path"], str(cache_path)]]
    indexed = day_index.docs[("pytdx_history", "000001.SZ", "20261228")]
    assert indexed["cache.local_path"] == str(cache_path)
    assert indexed["cache.last_accessed_at"]

    downloads.clear()
    rows_again = minute_cold_storage.read_cached_or_downloaded_day(
        day_index,
        source="pytdx_history",
        ts_code="000001.SZ",
        trade_date="20261228",
        config=config,
        runner=fake_download,
    )

    assert rows_again == rows
    assert downloads == []


def test_archive_stock_shards_reads_each_stock_independently(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _bucket()
    second = _bucket()
    second["ts_code"] = "000002.SZ"
    second["symbol"] = "000002"
    bucket_collection = FakeBucketCollection([first, second])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()

    result = minute_cold_storage.archive_stock_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
    )

    assert result["ok"] is True
    assert result["exported_days"] == 2
    assert result["storage_object"] == "stock_jsonl"
    assert bucket_collection.find_queries == [
        {"source": "pytdx_history"},
        {"source": "pytdx_history", "ts_code": "000001.SZ"},
        {"source": "pytdx_history", "ts_code": "000002.SZ"},
    ]
    assert day_index.docs[("pytdx_history", "000001.SZ", "20260627")]["relative_path"] == "objects_stock/pytdx_history/000001.SZ.jsonl"
    assert day_index.docs[("pytdx_history", "000002.SZ", "20260627")]["relative_path"] == "objects_stock/pytdx_history/000002.SZ.jsonl"


def test_archive_stock_year_shards_reads_each_year_independently(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    first = _bucket()
    second = _bucket()
    second["trade_date"] = "20270104"
    second["minutes"] = [{"minute": "0930", "price": 11.0}]
    bucket_collection = FakeBucketCollection([first, second])
    day_index = FakeIndexCollection()
    coverage = FakeCoverageCollection()

    result = minute_cold_storage.archive_stock_year_shards(
        bucket_collection,
        day_index,
        coverage,
        query={"source": "pytdx_history"},
        config=config,
    )

    assert result["ok"] is True
    assert result["exported_days"] == 2
    assert result["uploaded_files"] == 0
    assert result["storage_object"] == "stock_year_jsonl"
    assert bucket_collection.find_queries == [
        {"source": "pytdx_history"},
        {"source": "pytdx_history", "ts_code": "000001.SZ"},
        {"source": "pytdx_history", "ts_code": "000001.SZ", "trade_date": {"$gte": "20260101", "$lte": "20261231"}},
        {"source": "pytdx_history", "ts_code": "000001.SZ", "trade_date": {"$gte": "20270101", "$lte": "20271231"}},
    ]
    first_index = day_index.docs[("pytdx_history", "000001.SZ", "20260627")]
    second_index = day_index.docs[("pytdx_history", "000001.SZ", "20270104")]
    assert first_index["relative_path"] == "objects_stock_year/pytdx_history/000001.SZ/2026.jsonl"
    assert second_index["relative_path"] == "objects_stock_year/pytdx_history/000001.SZ/2027.jsonl"
    assert first_index["object_trade_year"] == "2026"
    assert second_index["object_trade_year"] == "2027"


def test_cleanup_legacy_remote_objects_dry_run_reports_planned_paths(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    day_index = FakeIndexCollection()
    info = {
        "relative_path": "objects_stock_year/pytdx_history/000001.SZ/2026.jsonl",
        "remote_path": "NewsAnalysis/cold/stock_minute/v1/objects_stock_year/pytdx_history/000001.SZ/2026.jsonl",
        "sha256": "digest",
        "size_bytes": 100,
        "row_count": minute_cold_storage.EXPECTED_DAY_ROWS,
        "storage_object": "stock_year_jsonl",
        "object_trade_year": "2026",
    }
    minute_cold_storage.upsert_day_index(day_index, _complete_bucket("20260627"), info, upload_status="uploaded")

    result = minute_cold_storage.cleanup_legacy_remote_objects(day_index, source="pytdx_history", config=config)

    assert result["dry_run"] is True
    assert result["legacy_index_days"] == 0
    assert result["stock_year_uploaded_days"] == 1
    assert result["planned_remote_paths"] == [
        "NewsAnalysis/cold/stock_minute/v1/objects",
        "NewsAnalysis/cold/stock_minute/v1/objects_month",
        "NewsAnalysis/cold/stock_minute/v1/objects_stock",
    ]


def test_cleanup_legacy_remote_objects_execute_deletes_only_when_legacy_index_clear(tmp_path):
    config = minute_cold_storage.MinuteColdConfig(local_root=tmp_path / "archive", cache_root=tmp_path / "cache")
    day_index = FakeIndexCollection()
    deleted = []

    result = minute_cold_storage.cleanup_legacy_remote_objects(
        day_index,
        source="pytdx_history",
        config=config,
        dry_run=False,
        runner=lambda args: deleted.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert result["ok"] is True
    assert len(deleted) == 3
    assert deleted[0][-2:] == ["-f", "NewsAnalysis/cold/stock_minute/v1/objects"]


def _complete_bucket(trade_date):
    bucket = _bucket()
    bucket["trade_date"] = trade_date
    bucket["row_count"] = minute_cold_storage.EXPECTED_DAY_ROWS
    return bucket
