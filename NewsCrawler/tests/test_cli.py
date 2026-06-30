import pytest
from pathlib import Path

from news_crawler.cli import _failure_stats, _parse_category_pages


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, limit):
        return self.rows[:limit]


class FakeRuns:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def find(self, query, *_args):
        self.query = query
        rows = [
            row for row in self.rows
            if not query or row.get("source_name") == query.get("source_name")
        ]
        return FakeCursor(rows)


class FakeRepository:
    def __init__(self, rows):
        self.runs = FakeRuns(rows)


def test_failure_stats_groups_codes_sources_and_messages():
    stats = _failure_stats(FakeRepository([
        {
            "source_name": "tonghuashun",
            "failed": 2,
            "errors": [
                {"code": "parser_error", "message": "404 Client Error"},
                {"code": "parser_error", "message": "article title or content not found"},
            ],
        },
        {
            "source_name": "guardian",
            "failed": 0,
            "warnings": [{"code": "image_only", "message": "OCR produced no text"}],
        },
    ]))

    assert stats["runs_scanned"] == 2
    assert stats["failed_runs"] == 1
    assert stats["failed_articles"] == 2
    assert stats["warning_articles"] == 1
    assert stats["codes"] == {
        "stale_link": 1,
        "extraction_missing": 1,
        "warning:image_only": 1,
    }
    assert stats["by_source"]["tonghuashun"] == {
        "stale_link": 1,
        "extraction_missing": 1,
    }


def test_parse_category_pages_validates_tonghuashun_categories():
    assert _parse_category_pages("产经新闻=3, 财经要闻=10") == {
        "产经新闻": 3,
        "财经要闻": 10,
    }
    assert _parse_category_pages("金融市场=0") == {"金融市场": 1}
    with pytest.raises(ValueError, match="未知同花顺分类"):
        _parse_category_pages("不存在=2")


def test_scheduler_reloads_settings_before_each_crawl_round():
    source = (Path(__file__).resolve().parents[1] / "src" / "news_crawler" / "cli.py").read_text(encoding="utf-8")
    assert "_run_crawl(args, get_settings(), fail_on_error=False)" in source
