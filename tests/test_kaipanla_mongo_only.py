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

    def update_many(self, query, update):
        matched = 0
        modified = 0
        values = query.get("record_id", {}).get("$in", []) if isinstance(query.get("record_id"), dict) else []
        updates = update.get("$set", {}) if isinstance(update, dict) else {}
        for doc in self.docs:
            if values and doc.get("record_id") not in values:
                continue
            matched += 1
            doc.update(updates)
            modified += 1

        Result = type("Result", (), {"matched_count": matched, "modified_count": modified})
        return Result()

    def update_one(self, query, update, upsert=False):
        updates = update.get("$set", {}) if isinstance(update, dict) else {}
        for doc in self.docs:
            if all(self._matches(doc, {key: value}) for key, value in query.items()):
                doc.update(updates)
                Result = type("Result", (), {"matched_count": 1, "modified_count": 1, "upserted_id": None})
                return Result()
        if upsert:
            self.docs.append(dict(updates))
            Result = type("Result", (), {"matched_count": 0, "modified_count": 0, "upserted_id": updates.get("record_id")})
            return Result()
        Result = type("Result", (), {"matched_count": 0, "modified_count": 0, "upserted_id": None})
        return Result()

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


def test_save_kaipanla_record_writes_trade_date(monkeypatch):
    collection = FakeKaipanlaCollection([])
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    result = kaipanla.save_kaipanla_record(
        {
            "feature": "sector_strength_history",
            "saved_at": "20260701_120000",
            "run_id": "run-1",
            "payload": {
                "ok": True,
                "params": {"start_date": "2026-06-30", "end_date": "2026-06-30"},
                "result": {"row_count": 1},
            },
        }
    )

    assert result["storage"] == "mongodb"
    assert collection.docs[0]["trade_date"] == "20260630"


def test_save_kaipanla_record_prefers_payload_trade_date(monkeypatch):
    collection = FakeKaipanlaCollection([])
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    kaipanla.save_kaipanla_record(
        {
            "feature": "realtime_market_mood",
            "saved_at": "20260701_120000",
            "run_id": "run-1",
            "payload": {
                "ok": True,
                "trade_date": "2026-06-30",
                "params": {"timeout": 20},
                "result": {},
            },
        }
    )

    assert collection.docs[0]["trade_date"] == "20260630"


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


def test_kaipanla_daily_overview_extracts_temperature_kpis(monkeypatch):
    collection = FakeKaipanlaCollection(
        [
            {
                "record_id": "daily:1",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260630_012447",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/daily_data/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"type": "series", "index": ["涨停数", "跌停数", "炸板"], "values": [105, 37, 103]}},
            },
            {
                "record_id": "limit:1",
                "feature": "consecutive_limit_up",
                "label": "连板梯队详情",
                "category": "连板梯队",
                "saved_at": "20260630_012451",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/consecutive_limit_up/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"date": "2026-06-30", "max_consecutive": 0, "ladder": {}}},
            },
            {
                "record_id": "market-limit:1",
                "feature": "market_limit_up_ladder",
                "label": "全市场连板梯队",
                "category": "连板梯队",
                "saved_at": "20260630_012451",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/market_limit_up_ladder/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"date": "2026-06-30", "statistics": {"max_consecutive": 5}}},
            },
            {
                "record_id": "high:1",
                "feature": "new_high_data",
                "label": "百日新高",
                "category": "核心数据",
                "saved_at": "20260630_012452",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/new_high_data/1",
                "ok": True,
                "params": {"end_date": "2026-06-30"},
                "payload": {"result": 148},
            },
            {
                "record_id": "withdrawal:1",
                "feature": "sharp_withdrawal",
                "label": "大幅回撤",
                "category": "传统接口",
                "saved_at": "20260630_012453",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/sharp_withdrawal/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"type": "dataframe", "rows": [{"回撤幅度(%)": -13.34, "总数": 3}], "row_count": 3}},
            },
        ]
    )
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    overview = kaipanla.kaipanla_daily_overview("2026-06-30")
    kpis = {item["label"]: item["value"] for item in overview["kpis"]}

    assert kpis["最高连板"] == 5
    assert kpis["百日新高"] == 148
    assert kpis["大幅回撤"] == 3


def test_kaipanla_daily_overview_counts_broken_limit_up_rows(monkeypatch):
    broken_rows = [{"股票代码": f"000{index:03d}", "股票名称": f"炸板{index}"} for index in range(24)]
    collection = FakeKaipanlaCollection(
        [
            {
                "record_id": "daily:1",
                "feature": "daily_data",
                "label": "交易日完整数据",
                "category": "核心数据",
                "saved_at": "20260630_012447",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/daily_data/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"type": "series", "index": ["涨停数", "跌停数"], "values": [168, 20]}},
            },
            {
                "record_id": "broken:1",
                "feature": "historical_broken_limit_up",
                "label": "历史反包板",
                "category": "连板梯队",
                "saved_at": "20260630_012454",
                "run_id": "run",
                "path": "mongodb://market/kaipanla_results/historical_broken_limit_up/1",
                "ok": True,
                "params": {"date": "2026-06-30"},
                "payload": {"result": {"date": "2026-06-30", "stocks": broken_rows}},
            },
        ]
    )
    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))

    overview = kaipanla.kaipanla_daily_overview("2026-06-30")
    kpis = {item["label"]: item["value"] for item in overview["kpis"]}

    assert kpis["炸板"] == 24


def test_repair_kaipanla_overview_history_saves_valid_live_records_and_archives_old(monkeypatch):
    old_docs = [
        {
            "record_id": "limit:old",
            "feature": "consecutive_limit_up",
            "saved_at": "20260630_012451",
            "run_id": "old",
            "ok": True,
            "params": {"date": "2026-06-30"},
            "payload": {"result": {"date": "2026-06-30", "max_consecutive": 0, "ladder": {}}},
        },
        {
            "record_id": "high:old",
            "feature": "new_high_data",
            "saved_at": "20260630_012452",
            "run_id": "old",
            "ok": True,
            "params": {"end_date": "2026-06-30"},
            "payload": {"result": 0},
        },
    ]
    collection = FakeKaipanlaCollection(old_docs)
    saved = []

    def fake_run(feature, params, *, save, run_id="", trade_date=""):
        assert save is False
        payloads = {
            "consecutive_limit_up": {"date": "2026-06-30", "max_consecutive": 3, "ladder": {3: [{"股票名称": "兴业股份"}]}},
            "market_limit_up_ladder": {"date": "2026-06-30", "statistics": {"max_consecutive": 3}},
            "new_high_data": 148,
            "sharp_withdrawal": {"type": "dataframe", "rows": [{"总数": 3, "回撤幅度(%)": -13.34}], "row_count": 3},
        }
        return {"ok": True, "feature": {"key": feature}, "params": params, "result": payloads[feature]}

    def fake_save(feature, payload, *, run_id):
        saved.append((feature, payload, run_id))
        return {"path": f"mongodb://market/kaipanla_results/{feature}/new", "run_id": run_id}

    monkeypatch.setattr(kaipanla, "_kaipanla_collection", lambda database=kaipanla.DEFAULT_DB: FakeContext(collection))
    monkeypatch.setattr(kaipanla, "run_kaipanla_feature", fake_run)
    monkeypatch.setattr(kaipanla, "save_kaipanla_result", fake_save)

    result = kaipanla.repair_kaipanla_overview_history("2026-06-30")

    assert result["ok"] is True
    assert result["archived"] == 2
    assert [item[0] for item in saved] == kaipanla.KAIPANLA_OVERVIEW_REPAIR_FEATURES
    assert all(doc["archived"] is True for doc in old_docs)
    assert {item["label"]: item["value"] for item in result["kpis"]} == {
        "涨停": "-",
        "跌停": "-",
        "炸板": "-",
        "最高连板": 3,
        "百日新高": 148,
        "大幅回撤": 3,
    }


def test_kaipanla_batch_replaces_default_dates_for_daily_runs(monkeypatch):
    calls = []

    def fake_run(feature, params, *, save, run_id, trade_date=""):
        calls.append((feature, params, save, run_id, trade_date))
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
    assert calls[0][4] == "2026-06-29"
    assert calls[1][1]["start_date"] == "2026-06-29"
    assert calls[1][1]["end_date"] == "2026-06-29"


def test_kaipanla_batch_limits_ndays_to_trade_date_for_daily_runs(monkeypatch):
    calls = []

    def fake_run(feature, params, *, save, run_id, trade_date=""):
        calls.append((feature, params, save, run_id, trade_date))
        return {"saved": {"path": f"mongodb://market/kaipanla_results/{feature}"}}

    monkeypatch.setattr(kaipanla, "run_kaipanla_feature", fake_run)

    result = kaipanla.run_kaipanla_batch(["sector_strength_ndays"], {}, run_id="run-1", trade_date="20260629")

    assert result["ok"] is True
    assert calls[0][1]["end_date"] == "2026-06-29"
    assert calls[0][1]["num_days"] == 1
    assert calls[0][4] == "2026-06-29"


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
