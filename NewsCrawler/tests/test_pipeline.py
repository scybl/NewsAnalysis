from datetime import datetime, timezone
import threading

from news_crawler.dedupe import DedupeService
from news_crawler.executor import TaskExecutor, _issue_code
from news_crawler.models import ArticleRef, NewsArticle, NewsCrawlRequest, ProviderCapabilities
from news_crawler.observer import LoggingRunObserver
from news_crawler.pipeline import CrawlPipeline
from news_crawler.registry import ProviderRegistry
from news_crawler.provider import ArticleSkipped


class FakeProvider:
    name = "fake"
    capabilities = ProviderCapabilities(frozenset({"en"}))

    def discover(self, request):
        yield ArticleRef(self.name, "https://example.com/a", "1")

    def fetch(self, ref):
        return NewsArticle(
            source_name=self.name,
            external_id=ref.external_id,
            url=ref.url,
            title="Example",
            content="body " * 30,
            published_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )


def test_dry_run_pipeline_needs_no_database():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)
    executor = TaskExecutor(None, None, DedupeService(), LoggingRunObserver())
    results = CrawlPipeline(registry, executor).run(
        NewsCrawlRequest(sources=("fake",), dry_run=True)
    )
    assert results[0].status == "succeeded"
    assert results[0].fetched == 1
    assert results[0].skipped == 1


class MemoryRepository:
    def __init__(self, cancel=False):
        self.documents = {}
        self.cancel = cancel
        self.health_updates = []

    def start(self, result):
        return None

    def finish(self, result):
        return None

    def is_cancel_requested(self, _run_id):
        return self.cancel

    def update_health(self, source_name):
        self.health_updates.append(source_name)

    def find_existing_by_keys(self, keys):
        return self.documents.get(keys.article_id)

    def upsert_article(self, article, keys):
        outcome = "updated" if keys.article_id in self.documents else "inserted"
        self.documents[keys.article_id] = {"article_id": keys.article_id}
        return outcome


def test_executor_honors_cancel_and_updates_health():
    repository = MemoryRepository(cancel=True)
    result = TaskExecutor(repository, repository, DedupeService(), LoggingRunObserver()).execute(
        FakeProvider(), NewsCrawlRequest()
    )
    assert result.status == "cancelled"
    assert repository.health_updates == ["fake"]


def test_executor_inserts_and_then_updates_duplicate():
    repository = MemoryRepository()
    executor = TaskExecutor(repository, repository, DedupeService(), LoggingRunObserver())
    first = executor.execute(FakeProvider(), NewsCrawlRequest())
    second = executor.execute(FakeProvider(), NewsCrawlRequest())
    assert first.inserted == 1
    assert second.updated == 1


def test_latest_crawl_continues_when_page_still_has_insertions():
    def article_for(external_id):
        return NewsArticle(
            source_name="paged",
            external_id=external_id,
            url=f"https://example.com/{external_id}",
            title=f"Title {external_id}",
            content="body " * 30,
            published_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )

    class PagedProvider:
        name = "paged"
        capabilities = ProviderCapabilities(frozenset({"en"}))

        def __init__(self):
            self.fetched = []

        def discover(self, request):
            for page, ids in [(1, ["a", "b"]), (2, ["c", "d"]), (3, ["e"])]:
                for external_id in ids:
                    yield ArticleRef(
                        self.name,
                        f"https://example.com/{external_id}",
                        external_id,
                        metadata={"crawl_group": "main", "crawl_page": page},
                    )

        def fetch(self, ref):
            self.fetched.append(ref.external_id)
            return article_for(ref.external_id)

    repository = MemoryRepository()
    dedupe = DedupeService()
    existing = dedupe.keys_for(article_for("d"))
    repository.documents[existing.article_id] = {"article_id": existing.article_id}
    provider = PagedProvider()

    result = TaskExecutor(repository, repository, dedupe, LoggingRunObserver()).execute(
        provider,
        NewsCrawlRequest(max_pages=3, stop_after_existing_page=True),
    )

    assert provider.fetched == ["a", "b", "c", "d", "e"]
    assert result.inserted == 4
    assert result.updated == 1
    assert "auto_existing_boundary_pages" not in result.metrics
    assert "auto_skipped_existing_page_refs" not in result.metrics


def test_latest_crawl_stops_after_page_is_only_existing_articles():
    def article_for(external_id):
        return NewsArticle(
            source_name="paged",
            external_id=external_id,
            url=f"https://example.com/{external_id}",
            title=f"Title {external_id}",
            content="body " * 30,
            published_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )

    class PagedProvider:
        name = "paged"
        capabilities = ProviderCapabilities(frozenset({"en"}))

        def __init__(self):
            self.fetched = []

        def discover(self, request):
            for page, ids in [(1, ["a", "b"]), (2, ["c", "d"]), (3, ["e"])]:
                for external_id in ids:
                    yield ArticleRef(
                        self.name,
                        f"https://example.com/{external_id}",
                        external_id,
                        metadata={"crawl_group": "main", "crawl_page": page},
                    )

        def fetch(self, ref):
            self.fetched.append(ref.external_id)
            return article_for(ref.external_id)

    repository = MemoryRepository()
    dedupe = DedupeService()
    for external_id in ("c", "d"):
        existing = dedupe.keys_for(article_for(external_id))
        repository.documents[existing.article_id] = {"article_id": existing.article_id}
    provider = PagedProvider()

    result = TaskExecutor(repository, repository, dedupe, LoggingRunObserver()).execute(
        provider,
        NewsCrawlRequest(max_pages=3, stop_after_existing_page=True),
    )

    assert provider.fetched == ["a", "b", "c", "d"]
    assert result.inserted == 2
    assert result.updated == 2
    assert result.metrics["auto_existing_boundary_pages"] == 1
    assert result.metrics["auto_skipped_existing_page_refs"] == 1


def test_failure_is_structured():
    class BrokenProvider(FakeProvider):
        def fetch(self, ref):
            raise TimeoutError("timed out")

    repository = MemoryRepository()
    result = TaskExecutor(
        repository,
        repository,
        DedupeService(),
        LoggingRunObserver(),
        retries=1,
    ).execute(BrokenProvider(), NewsCrawlRequest())
    assert result.status == "partial"
    assert result.metrics["timeout"] == 1
    assert result.errors[0].code == "timeout"


def test_executor_fails_run_when_total_runtime_expires():
    clock = {"now": 0.0}

    class SlowProvider(FakeProvider):
        def fetch(self, ref):
            clock["now"] = 301.0
            return super().fetch(ref)

    repository = MemoryRepository()
    result = TaskExecutor(
        repository,
        repository,
        DedupeService(),
        LoggingRunObserver(),
        retries=1,
        monotonic_fn=lambda: clock["now"],
    ).execute(SlowProvider(), NewsCrawlRequest(max_runtime_seconds=300))

    assert result.status == "failed"
    assert result.finished_at is not None
    assert result.failed == 1
    assert result.metrics["timeout"] == 1
    assert result.errors[0].code == "timeout"


def test_failure_reason_classification_is_specific():
    assert _issue_code(RuntimeError("404 Client Error: Not Found for url")) == "stale_link"
    assert _issue_code(ValueError("article title or content not found")) == "extraction_missing"


def test_skipped_article_is_warning_without_partial_status():
    class ImageOnlyProvider(FakeProvider):
        def fetch(self, ref):
            raise ArticleSkipped("image_only", "article contains images but no extractable text")

    repository = MemoryRepository()
    result = TaskExecutor(repository, repository, DedupeService(), LoggingRunObserver()).execute(
        ImageOnlyProvider(), NewsCrawlRequest()
    )
    assert result.status == "succeeded"
    assert result.skipped == 1
    assert result.failed == 0
    assert result.warnings[0].code == "image_only"


def test_pipeline_runs_sources_in_parallel():
    barrier = threading.Barrier(2, timeout=2)

    class ParallelProvider(FakeProvider):
        def __init__(self, name):
            self.name = name

        def discover(self, request):
            barrier.wait()
            yield from super().discover(request)

    registry = ProviderRegistry()
    registry.register("one", lambda: ParallelProvider("one"))
    registry.register("two", lambda: ParallelProvider("two"))
    results = CrawlPipeline(
        registry,
        TaskExecutor(None, None, DedupeService(), LoggingRunObserver()),
    ).run(NewsCrawlRequest(sources=("one", "two"), dry_run=True))
    assert [item.source_name for item in results] == ["one", "two"]
