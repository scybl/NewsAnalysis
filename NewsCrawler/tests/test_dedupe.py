from datetime import datetime, timedelta, timezone

from news_crawler.dedupe import DedupeService, canonicalize_url
from news_crawler.models import NewsArticle
from news_crawler.mongo_repository import _iso


def test_canonicalize_url_removes_tracking_and_www():
    assert canonicalize_url("https://www.example.com/a/?utm_source=x") == "https://example.com/a"


def test_article_id_is_stable_for_same_external_id():
    article = NewsArticle(
        source_name="guardian",
        external_id="business/1",
        url="https://example.com/a",
        title="A useful title",
        content="content " * 30,
        published_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )
    assert DedupeService().keys_for(article).article_id == DedupeService().keys_for(article).article_id


def test_storage_time_is_normalized_to_utc():
    value = datetime(2026, 6, 25, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    assert _iso(value) == "2026-06-25T02:00:00Z"
