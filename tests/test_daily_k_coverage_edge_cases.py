from stock_pipeline.daily_k_coverage import inspect_daily_k_coverage_gaps, refresh_daily_k_coverage


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def distinct(self, field, query=None):
        values = []
        seen = set()
        for doc in self.docs:
            if not _matches(doc, query or {}):
                continue
            value = _get(doc, field)
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def find(self, query=None, projection=None):
        return [_project(doc, projection) for doc in self.docs if _matches(doc, query or {})]

    def update_one(self, query, update, upsert=False):
        self.updates.append({"query": query, "update": update, "upsert": upsert})


def test_daily_k_coverage_falls_back_to_row_codes_when_metadata_is_empty():
    rows = FakeCollection([_daily("000001.SZ", "20260717"), _daily("000002.SZ", "20260717")])
    metadata = FakeCollection()

    result = inspect_daily_k_coverage_gaps(rows, metadata, start_date="20260717", end_date="20260717")

    assert result["stocks_checked"] == 2
    assert [item["ts_code"] for item in result["items"]] == ["000001.SZ", "000002.SZ"]


def test_daily_k_coverage_uses_daily_range_start_before_listing_metadata():
    rows = FakeCollection([_daily("000001.SZ", "20200102"), _daily("000001.SZ", "20260717"), _daily("000002.SZ", "20200102"), _daily("000002.SZ", "20260717")])
    metadata = FakeCollection(
        [
            {
                "ts_code": "000001.SZ",
                "metadata": {
                    "ts_code": "000001.SZ",
                    "stock_basic": {"list_date": "20210101"},
                    "daily_date_range": {"start_date": "20200102"},
                },
            }
        ]
    )

    item = inspect_daily_k_coverage_gaps(rows, metadata, codes=["000001.SZ"], start_date="20200101", end_date="20260717")["items"][0]

    assert item["first_expected_date"] == "20200102"
    assert item["latest_complete_date"] == "20260717"
    assert item["status"] == "ok"


def test_daily_k_coverage_reports_no_reference_dates_and_can_persist_it():
    rows = FakeCollection([])
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20200101")])
    coverage = FakeCollection()

    result = refresh_daily_k_coverage(rows, metadata, coverage, codes=["000001.SZ"], start_date="20260717", end_date="20260717")

    assert result["stocks_without_reference"] == 1
    assert result["items"][0]["status"] == "no_reference_dates"
    assert coverage.updates[0]["query"] == {"ts_code": "000001.SZ"}
    assert coverage.updates[0]["update"]["$set"]["status"] == "no_reference_dates"


def test_daily_k_coverage_limit_and_max_samples_keep_large_gap_report_small():
    market_rows = [_daily("000002.SZ", f"202607{day:02d}") for day in range(1, 10)]
    rows = FakeCollection([*_daily_rows_for_reference(market_rows), _daily("000001.SZ", "20260701")])
    metadata = FakeCollection([_metadata("000001.SZ", list_date="20200101"), _metadata("000003.SZ", list_date="20200101")])

    result = inspect_daily_k_coverage_gaps(
        rows,
        metadata,
        start_date="20260701",
        end_date="20260709",
        limit=1,
        max_samples=3,
    )

    assert result["stocks_checked"] == 1
    assert result["items"][0]["ts_code"] == "000001.SZ"
    assert result["items"][0]["missing_days"] == 8
    assert result["items"][0]["missing_samples"] == ["20260702", "20260703", "20260704"]


def test_daily_k_coverage_ignores_invalid_codes_and_dates_from_collections():
    rows = FakeCollection([_daily("bad-code", "20260717"), _daily("000001.SZ", "not-a-date"), _daily("000001.SZ", "20260717")])
    metadata = FakeCollection([{"ts_code": "bad", "metadata": {"ts_code": "bad"}}, _metadata("000001.SZ", list_date="20200101")])

    result = inspect_daily_k_coverage_gaps(rows, metadata, start_date="20260717", end_date="20260717")

    assert result["stocks_checked"] == 1
    assert result["items"][0]["ts_code"] == "000001.SZ"
    assert result["items"][0]["status"] == "ok"


def _daily_rows_for_reference(rows):
    return list(rows)


def _daily(ts_code, trade_date):
    return {"ts_code": ts_code, "snapshot": "current", "dataset": "daily", "trade_date": trade_date}


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
    return {key: _get(doc, key) for key, enabled in projection.items() if enabled and _get(doc, key) is not None}
