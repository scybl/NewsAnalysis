import pytest

from stock_pipeline import kaipanla


class FakeKaipanlaCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection):
        items = [doc for doc in self.docs if not query or doc.get("feature") == query.get("feature")]
        return FakeCursor(items)

    def find_one(self, query, projection):
        candidates = query["$or"]
        for doc in self.docs:
            if any(doc.get(key) == value for condition in candidates for key, value in condition.items()):
                return doc
        return None

    def create_index(self, *_args, **_kwargs):
        return None


class FakeCursor:
    def __init__(self, items):
        self.items = items

    def sort(self, *_args, **_kwargs):
        self.items = sorted(self.items, key=lambda item: item.get("saved_at", ""), reverse=True)
        return self

    def limit(self, value):
        self.items = self.items[:value]
        return self

    def __iter__(self):
        return iter(self.items)


class FakeContext:
    def __init__(self, collection):
        self.collection = collection

    def __enter__(self):
        return self.collection

    def __exit__(self, *_args):
        return False


def test_list_kaipanla_records_reads_mongodb_only(monkeypatch):
    collection = FakeKaipanlaCollection(
        [
            {
                "record_id": "daily:1",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260628_210000",
                "run_id": "run-1",
                "path": "mongodb://market/kaipanla_results/daily_data/1",
                "ok": True,
                "params": {},
                "storage": "mongodb",
            }
        ]
    )
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    result = kaipanla.list_kaipanla_records(feature="daily_data")

    assert result["count"] == 1
    assert result["items"][0]["storage"] == "mongodb"
    assert result["data_dir"] == f"mongodb://{kaipanla.DEFAULT_DB}/{kaipanla.KAIPANLA_COLLECTION}"
    assert "storage_fallback" not in result


def test_read_kaipanla_record_does_not_fallback_to_local_paths(monkeypatch, tmp_path):
    collection = FakeKaipanlaCollection([])
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))
    local_record = tmp_path / "local_data" / "kaipanla" / "daily_data" / "record.json"
    local_record.parent.mkdir(parents=True)
    local_record.write_text('{"ok": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="开盘啦记录不存在"):
        kaipanla.read_kaipanla_record(str(local_record))


def test_read_kaipanla_record_returns_mongodb_document(monkeypatch):
    collection = FakeKaipanlaCollection(
        [
            {
                "record_id": "daily:1",
                "schema": "kaipanla.result.v1",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260628_210000",
                "run_id": "run-1",
                "path": "mongodb://market/kaipanla_results/daily_data/1",
                "payload": {"ok": True},
            }
        ]
    )
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    record = kaipanla.read_kaipanla_record("daily:1")

    assert record["storage"] == "mongodb"
    assert record["payload"] == {"ok": True}
