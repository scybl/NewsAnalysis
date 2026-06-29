from datetime import datetime, timezone
import sys
import uuid

from news_crawler.dedupe import DedupeService
from news_crawler.models import CrawlResult, NewsArticle
from news_crawler.mongo_repository import MongoNewsRepository


def main(uri: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    repository = MongoNewsRepository(
        uri,
        "news_crawler_integration",
        f"raw_articles_{suffix}",
        f"crawl_runs_{suffix}",
        f"source_health_{suffix}",
        f"checkpoints_{suffix}",
    )
    try:
        repository.ensure_indexes()
        article = NewsArticle(
            source_name="integration",
            external_id="article-1",
            url="https://example.com/integration",
            title="Integration test",
            content="integration content " * 20,
            published_at=datetime.now(timezone.utc),
        )
        keys = DedupeService().keys_for(article)
        assert repository.upsert_article(article, keys) == "inserted"
        assert repository.upsert_article(article, keys) == "updated"
        result = CrawlResult(source_name="integration", run_id=uuid.uuid4().hex)
        repository.start(result)
        assert repository.request_cancel(result.run_id)
        assert repository.is_cancel_requested(result.run_id)
        result.status = "succeeded"
        result.inserted = 1
        result.finished_at = datetime.now(timezone.utc)
        repository.finish(result)
        health = repository.update_health("integration")
        assert health["status"] == "online"
        repository.save_checkpoint("integration", "cursor", {"page": 2})
        assert repository.load_checkpoint("integration", "cursor") == {"page": 2}
        assert repository.get_run(result.run_id)["inserted"] == 1
        print("mongo_integration_ok")
    finally:
        repository.client.drop_database("news_crawler_integration")
        repository.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mongodb://127.0.0.1:27018/")
