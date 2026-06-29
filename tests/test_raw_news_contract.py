import json
from pathlib import Path

import pytest

from stock_pipeline.raw_news import MongoRawNewsRepository
from stock_pipeline import news_search


def test_contract_copy_matches_news_crawler():
    root = Path(__file__).resolve().parents[1]
    analysis_contract = json.loads((root / "contracts" / "raw-article.news.v1.schema.json").read_text())
    crawler_contract = json.loads((root / "NewsCrawler" / "contracts" / "raw-article.news.v1.schema.json").read_text())
    assert analysis_contract == crawler_contract


def test_repository_rejects_unknown_schema_major():
    repository = MongoRawNewsRepository.__new__(MongoRawNewsRepository)
    with pytest.raises(ValueError, match="不支持"):
        repository._validate({"schema_version": "news.v2"})


def test_repository_accepts_news_v1_minor_version():
    repository = MongoRawNewsRepository.__new__(MongoRawNewsRepository)
    assert repository._validate({"schema_version": "news.v1.1"})["schema_version"] == "news.v1.1"


def test_raw_news_query_contains_time_range_and_keywords():
    repository = MongoRawNewsRepository.__new__(MongoRawNewsRepository)
    query = repository._query(["牧原"], "2026-01-01", "2026-01-31", "", "")
    text = json.dumps(query, ensure_ascii=False)
    assert "牧原" in text
    assert "2026-01-01T00:00:00" in text
    assert "2026-01-31T23:59:59Z" in text


def test_agent_news_evidence_uses_raw_repository(monkeypatch):
    class FakeRepository:
        config = type("Config", (), {"database": "news", "collection": "raw_articles"})()

        def __init__(self, **_kwargs):
            pass

        def search(self, **_kwargs):
            return ([{
                "title": "牧原股份新闻",
                "summary": "生猪价格变化",
                "content": "",
                "published_at": "2026-06-25T00:00:00Z",
                "section": "公司新闻",
                "source_name": "tonghuashun",
                "url": "https://example.com/a"
            }], 1)

        def close(self):
            pass

    monkeypatch.setattr(news_search, "MongoRawNewsRepository", FakeRepository)
    result = news_search.search_news_evidence({"name": "牧原股份"}, keywords=["牧原股份"], limit=1)
    assert result["enabled"]
    assert result["collection"] == "raw_articles"
    assert result["items"][0]["title"] == "牧原股份新闻"
