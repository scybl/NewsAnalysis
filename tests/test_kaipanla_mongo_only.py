import pytest
from datetime import date

from stock_pipeline import kaipanla


class FakeKaipanlaCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection):
        if not query:
            items = list(self.docs)
        elif "$or" in query:
            items = [
                doc
                for doc in self.docs
                if all(self._matches(doc, {key: value}) for key, value in query.items() if key != "$or")
                and any(self._matches(doc, condition) for condition in query["$or"])
            ]
        else:
            items = [doc for doc in self.docs if all(self._matches(doc, {key: value}) for key, value in query.items())]
        return FakeCursor(items)

    def find_one(self, query, projection, sort=None):
        cursor = self.find(query, projection)
        if sort:
            cursor.sort(sort)
        for doc in cursor:
            return doc
        return None

    def create_index(self, *_args, **_kwargs):
        return None

    def _matches(self, doc, condition):
        for key, expected in condition.items():
            value = self._get_nested(doc, key)
            if isinstance(expected, dict):
                if "$regex" in expected and not str(value or "").startswith(expected["$regex"].lstrip("^")):
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$ne" in expected and value == expected["$ne"]:
                    return False
            elif value != expected:
                return False
        return True

    def _get_nested(self, doc, key):
        value = doc
        for part in key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


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


def test_kaipanla_daily_overview_groups_latest_records_by_trade_date(monkeypatch):
    collection = FakeKaipanlaCollection(
        [
            {
                "record_id": "daily:old",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260628_200000",
                "run_id": "run-old",
                "path": "mongodb://market/kaipanla_results/daily_data/old",
                "ok": True,
                "params": {"date": "2026-06-28"},
                "payload": {"result": {"涨停": 41, "跌停": 2}},
            },
            {
                "record_id": "daily:new",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260628_210000",
                "run_id": "run-new",
                "path": "mongodb://market/kaipanla_results/daily_data/new",
                "ok": True,
                "params": {"date": "2026-06-28"},
                "payload": {"result": {"涨停": 42, "跌停": 3}},
            },
            {
                "record_id": "sector:1",
                "feature": "sector_ranking",
                "label": "板块排行",
                "category": "板块",
                "saved_at": "20260628_205000",
                "run_id": "run-sector",
                "path": "mongodb://market/kaipanla_results/sector_ranking/1",
                "ok": True,
                "params": {"date": "20260628"},
                "payload": {"result": {"type": "dataframe", "rows": [{"板块": "机器人", "涨幅": 5.2, "日期": date(2026, 6, 28)}]}},
            },
            {
                "record_id": "etf:1",
                "feature": "all_etf_ranking",
                "label": "ETF 全量排行",
                "category": "ETF",
                "saved_at": "20260628_204500",
                "run_id": "run-etf",
                "path": "mongodb://market/kaipanla_results/all_etf_ranking/1",
                "ok": False,
                "params": {"date": "20260628"},
                "payload": {"result": {"etfs": [], "total_count": 0}},
            },
            {
                "record_id": "archived:1",
                "feature": "market_sentiment",
                "label": "市场情绪统计",
                "category": "传统接口",
                "saved_at": "20260628_220000",
                "run_id": "run-archived",
                "path": "mongodb://market/kaipanla_results/market_sentiment/archived",
                "ok": True,
                "archived": True,
                "params": {"date": "2026-06-28"},
                "payload": {"result": {"rows": [{"日期": "2026-06-28", "涨停数": 999}]}},
            },
            {
                "record_id": "detail:old-params",
                "feature": "longhubang_stock_detail",
                "label": "龙虎榜详情",
                "category": "龙虎榜",
                "saved_at": "20260628_214500",
                "run_id": "run-detail",
                "path": "mongodb://market/kaipanla_results/longhubang_stock_detail/old",
                "ok": True,
                "params": {"stock_code": "002498", "date": "2026-01-16"},
                "payload": {"result": {"stock_code": "002498", "date": "2026-01-16"}},
            },
        ]
    )
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    overview = kaipanla.kaipanla_daily_overview("2026-06-28")

    assert overview["date"] == "20260628"
    assert overview["display_date"] == "2026-06-28"
    assert overview["coverage"]["collected_features"] == 3
    assert overview["coverage"]["succeeded"] == 2
    assert overview["coverage"]["failed"] == 1
    assert {item["label"]: item["value"] for item in overview["kpis"]}["涨停"] == 42
    assert overview["sections"]["temperature"][0]["summary"] == "涨停: 42；跌停: 3"
    assert overview["sections"]["sectors"][0]["rows"][0]["板块"] == "机器人"
    assert overview["sections"]["sectors"][0]["rows"][0]["日期"] == "2026-06-28"
    assert "longhubang_stock_detail" not in {item["feature"] for item in overview["sections"]["capital"]}

    latest_overview = kaipanla.kaipanla_daily_overview("")
    assert latest_overview["date"] == "20260628"
    assert "longhubang_stock_detail" not in {item["feature"] for item in latest_overview["sections"]["capital"]}


def test_kaipanla_batch_replaces_default_dates_for_daily_runs(monkeypatch):
    calls = []

    def fake_run(feature, params, *, save, run_id):
        calls.append((feature, params, save, run_id))
        return {"saved": {"path": f"mongodb://market/kaipanla_results/{feature}"}}

    monkeypatch.setattr(kaipanla, "run_kaipanla_feature", fake_run)

    result = kaipanla.run_kaipanla_batch(
        ["market_sentiment", "sector_strength_history"],
        {
            "market_sentiment": {"date": "2026-01-16"},
            "sector_strength_history": {"start_date": "2026-01-12", "end_date": "2026-01-16"},
        },
        run_id="run-1",
        trade_date="20260629",
    )

    assert result["ok"] is True
    assert result["trade_date"] == "2026-06-29"
    assert calls[0][1]["date"] == "2026-06-29"
    assert calls[1][1]["start_date"] == "2026-01-12"
    assert calls[1][1]["end_date"] == "2026-06-29"


def test_kaipanla_overview_renders_series_as_metric_rows():
    rows = kaipanla._result_rows({"type": "series", "index": ["涨停数", "跌停数"], "values": [122, 68]})

    assert rows == [{"指标": "涨停数", "值": 122}, {"指标": "跌停数", "值": 68}]


def test_kaipanla_slim_rows_preserves_limit_up_reason():
    rows = kaipanla._slim_rows(
        [
            {
                "无关字段1": "a",
                "无关字段2": "b",
                "股票代码": "002208",
                "股票名称": "合肥城建",
                "首次封板时间": "09:36:00",
                "总市值": 5999000000,
                "涨停原因": "芯片(存储)：公司参股企业涉及存储芯片。",
            }
        ]
    )

    assert rows[0]["股票代码"] == "002208"
    assert rows[0]["涨停原因"].startswith("芯片")


def test_kaipanla_overview_normalizes_etf_array_rows():
    rows = kaipanla._result_rows(
        {
            "date": "2026-06-29",
            "etfs": [
                ["513100", "纳指ETF", 1.234, 2.56, 123456789, 1.8],
            ],
        }
    )
    slim = kaipanla._slim_rows(rows)

    assert rows[0]["ETF代码"] == "513100"
    assert rows[0]["ETF名称"] == "纳指ETF"
    assert rows[0]["涨跌幅(%)"] == 2.56
    assert slim[0]["成交额"] == 123456789
