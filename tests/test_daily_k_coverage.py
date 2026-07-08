from stock_pipeline.daily_k_coverage import inspect_daily_k_coverage_gaps, refresh_daily_k_coverage


class FakeCursor(list):
    pass


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []
        self.indexes = []

    def distinct(self, field, query=None):
        query = query or {}
        values = []
        seen = set()
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            value = _get(doc, field)
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def find(self, query=None, projection=None):
        query = query or {}
        rows = []
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            rows.append(_project(doc, projection))
        return FakeCursor(rows)

    def update_one(self, query, update, upsert=False):
        self.updates.append({"query": query, "update": update, "upsert": upsert})

    def create_index(self, spec, unique=False):
        self.indexes.append({"spec": spec, "unique": unique})


def test_daily_k_coverage_reports_internal_missing_day():
    rows = FakeCollection(
        [
            _daily_row("000001.SZ", "20260702"),
            _daily_row("000001.SZ", "20260706"),
            _daily_row("000002.SZ", "20260702"),
            _daily_row("000002.SZ", "20260703"),
            _daily_row("000002.SZ", "20260706"),
        ]
    )
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20200101"), _metadata("000002.SZ", list_date="20200101")])

    result = inspect_daily_k_coverage_gaps(
        rows,
        metadata,
        codes=["000001.SZ"],
        start_date="20260702",
        end_date="20260706",
    )

    item = result["items"][0]
    assert item["status"] == "needs_backfill"
    assert item["missing_samples"] == ["20260703"]
    assert item["internal_missing_samples"] == ["20260703"]
    assert item["tail_missing_samples"] == []
    assert item["latest_complete_date"] == "20260702"
    assert result["stocks_with_missing"] == 1


def test_daily_k_coverage_reports_tail_missing_days():
    rows = FakeCollection(
        [
            _daily_row("000001.SZ", "20260702"),
            _daily_row("000002.SZ", "20260702"),
            _daily_row("000002.SZ", "20260703"),
            _daily_row("000002.SZ", "20260706"),
        ]
    )
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20200101"), _metadata("000002.SZ", list_date="20200101")])

    result = inspect_daily_k_coverage_gaps(
        rows,
        metadata,
        codes=["000001.SZ"],
        start_date="20260702",
        end_date="20260706",
    )

    item = result["items"][0]
    assert item["missing_samples"] == ["20260703", "20260706"]
    assert item["internal_missing_samples"] == []
    assert item["tail_missing_samples"] == ["20260703", "20260706"]
    assert item["latest_indexed_date"] == "20260702"


def test_refresh_daily_k_coverage_persists_summary():
    rows = FakeCollection(
        [
            _daily_row("000001.SZ", "20260702"),
            _daily_row("000001.SZ", "20260706"),
            _daily_row("000002.SZ", "20260702"),
            _daily_row("000002.SZ", "20260703"),
            _daily_row("000002.SZ", "20260706"),
        ]
    )
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20200101"), _metadata("000002.SZ", list_date="20200101")])
    coverage = FakeCollection()

    result = refresh_daily_k_coverage(
        rows,
        metadata,
        coverage,
        codes=["000001.SZ"],
        start_date="20260702",
        end_date="20260706",
    )

    assert result["missing_days"] == 1
    assert coverage.updates
    update = coverage.updates[0]
    assert update["query"] == {"ts_code": "000001.SZ"}
    assert update["upsert"] is True
    assert update["update"]["$set"]["internal_missing_samples"] == ["20260703"]
    assert update["update"]["$set"]["collection"] == "stock_daily_coverage"


def test_daily_k_coverage_respects_listing_date():
    rows = FakeCollection(
        [
            _daily_row("000001.SZ", "20260706"),
            _daily_row("000002.SZ", "20260702"),
            _daily_row("000002.SZ", "20260703"),
            _daily_row("000002.SZ", "20260706"),
        ]
    )
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20260706"), _metadata("000002.SZ", list_date="20200101")])

    result = inspect_daily_k_coverage_gaps(
        rows,
        metadata,
        codes=["000001.SZ"],
        start_date="20260702",
        end_date="20260706",
    )

    item = result["items"][0]
    assert item["status"] == "ok"
    assert item["first_expected_date"] == "20260706"
    assert item["missing_days"] == 0


def _daily_row(ts_code, trade_date):
    return {"ts_code": ts_code, "snapshot": "current", "dataset": "daily", "trade_date": trade_date, "row": {"trade_date": trade_date}}


def _metadata(ts_code, *, list_date):
    return {"ts_code": ts_code, "metadata": {"ts_code": ts_code, "stock_basic": {"name": ts_code, "list_date": list_date}}}


def _matches(doc, query):
    for key, expected in query.items():
        value = _get(doc, key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$gte" in expected and value < expected["$gte"]:
                return False
            if "$lte" in expected and value > expected["$lte"]:
                return False
            continue
        if value != expected:
            return False
    return True


def _get(doc, dotted_key):
    value = doc
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _project(doc, projection):
    if not projection:
        return dict(doc)
    out = {}
    for key, enabled in projection.items():
        if not enabled or key == "_id":
            continue
        value = _get(doc, key)
        if value is not None:
            _assign(out, key, value)
    return out


def _assign(doc, dotted_key, value):
    target = doc
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
