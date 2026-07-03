from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from .dedupe import DedupeService
from .models import CrawlIssue, CrawlResult, NewsCrawlRequest
from .observer import RunObserver
from .provider import NewsProvider
from .provider import ArticleSkipped
from .provider import ProviderFailure
from .repository import CrawlRunRepository, NewsRepository


class TaskExecutor:
    def __init__(
        self,
        news_repository: NewsRepository | None,
        run_repository: CrawlRunRepository | None,
        dedupe: DedupeService,
        observer: RunObserver,
        retries: int = 2,
        sleep_fn=time.sleep,
        monotonic_fn=time.monotonic,
    ):
        self.news_repository = news_repository
        self.run_repository = run_repository
        self.dedupe = dedupe
        self.observer = observer
        self.retries = max(1, retries)
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def execute(self, provider: NewsProvider, request: NewsCrawlRequest) -> CrawlResult:
        result = CrawlResult(source_name=provider.name, run_id=uuid.uuid4().hex)
        deadline = _deadline(self.monotonic_fn(), request.max_runtime_seconds)
        if self.run_repository:
            self.run_repository.start(result)
        self.observer.on_run_started(result)
        current_page_key = None
        current_page_stats = _empty_page_stats()
        stopped_groups = set()
        try:
            for ref in provider.discover(request):
                _raise_if_timed_out(deadline, self.monotonic_fn, provider.name)
                page_key = _page_key(ref)
                if page_key != current_page_key:
                    _finalize_page_boundary(request, result, current_page_key, current_page_stats, stopped_groups)
                    current_page_key = page_key
                    current_page_stats = _empty_page_stats()
                if _should_skip_page(request, page_key, stopped_groups):
                    result.metrics["auto_skipped_existing_page_refs"] = int(result.metrics.get("auto_skipped_existing_page_refs", 0)) + 1
                    continue
                if self.run_repository and self.run_repository.is_cancel_requested(result.run_id):
                    result.status = "cancelled"
                    break
                if request.max_articles and result.discovered >= request.max_articles:
                    break
                result.discovered += 1
                current_page_stats["discovered"] += 1
                cold_existing = self._find_cold_ref(ref)
                if cold_existing:
                    result.skipped += 1
                    current_page_stats["existing"] += 1
                    result.metrics["cold_duplicate"] = int(result.metrics.get("cold_duplicate", 0)) + 1
                    self.observer.on_article_duplicated(ref, _duplicate_reason(cold_existing, self.dedupe.keys_for_ref(ref)))
                    continue
                article = self._fetch_with_retry(provider, ref, result, deadline)
                _raise_if_timed_out(deadline, self.monotonic_fn, provider.name)
                if article is None:
                    continue
                result.fetched += 1
                current_page_stats["fetched"] += 1
                if request.since and article.published_at < request.since:
                    result.skipped += 1
                    result.metrics["outside_time_range"] = int(result.metrics.get("outside_time_range", 0)) + 1
                    continue
                if request.until and article.published_at > request.until:
                    result.skipped += 1
                    result.metrics["outside_time_range"] = int(result.metrics.get("outside_time_range", 0)) + 1
                    continue
                keys = self.dedupe.keys_for(article)
                if request.dry_run or not self.news_repository:
                    result.skipped += 1
                    continue
                existing = self.news_repository.find_existing_by_keys(keys)
                outcome = self.news_repository.upsert_article(article, keys)
                if outcome == "inserted":
                    result.inserted += 1
                    current_page_stats["inserted"] += 1
                    self.observer.on_article_inserted(article)
                else:
                    result.updated += 1
                    current_page_stats["existing"] += 1
                    result.metrics["duplicate"] = int(result.metrics.get("duplicate", 0)) + 1
                    self.observer.on_article_duplicated(article, _duplicate_reason(existing, keys))
                if request.request_delay_seconds > 0:
                    self.sleep_fn(request.request_delay_seconds)
                    _raise_if_timed_out(deadline, self.monotonic_fn, provider.name)
            _finalize_page_boundary(request, result, current_page_key, current_page_stats, stopped_groups)
            if result.status != "cancelled":
                result.status = "succeeded" if not result.errors else "partial"
        except CrawlRunTimeout as exc:
            result.failed += 1
            result.metrics["timeout"] = int(result.metrics.get("timeout", 0)) + 1
            result.errors.append(CrawlIssue("timeout", str(exc), retryable=True))
            result.status = "failed"
            self.observer.on_provider_failed(provider.name, result.errors[-1])
        except AutoPausedSource:
            result.status = "failed"
            if result.errors:
                self.observer.on_provider_failed(provider.name, result.errors[-1])
        except Exception as exc:  # provider discovery failure
            issue, pause_source = _issue_from_exception(exc, retryable=False, classify_unknown=False)
            _record_error(result, issue)
            if pause_source:
                self._pause_source(provider.name, issue, result.run_id)
            result.status = "failed"
            self.observer.on_provider_failed(provider.name, issue)
        finally:
            result.finished_at = datetime.now(timezone.utc)
            if self.run_repository:
                self.run_repository.finish(result)
                self.run_repository.update_health(provider.name)
            self.observer.on_run_finished(result)
        return result

    def _fetch_with_retry(self, provider, ref, result, deadline):
        for attempt in range(1, self.retries + 1):
            try:
                _raise_if_timed_out(deadline, self.monotonic_fn, provider.name)
                return provider.fetch(ref)
            except ArticleSkipped as exc:
                result.skipped += 1
                result.metrics[exc.code] = int(result.metrics.get(exc.code, 0)) + 1
                result.warnings.append(CrawlIssue(exc.code, str(exc), ref.url, retryable=False))
                return None
            except Exception as exc:
                issue, pause_source = _issue_from_exception(exc, article_url=ref.url, retryable=True, classify_unknown=True)
                if pause_source:
                    _record_error(result, issue)
                    self._pause_source(provider.name, issue, result.run_id)
                    raise AutoPausedSource(str(exc)) from exc
                if issue.retryable and attempt < self.retries:
                    result.metrics["retry"] = int(result.metrics.get("retry", 0)) + 1
                    self.sleep_fn(min(2 ** (attempt - 1), 4))
                    _raise_if_timed_out(deadline, self.monotonic_fn, provider.name)
                    continue
                _record_error(result, issue)
                return None

    def _pause_source(self, source_name: str, issue: CrawlIssue, run_id: str) -> None:
        if self.run_repository and hasattr(self.run_repository, "pause_source"):
            self.run_repository.pause_source(source_name, issue.message, run_id=run_id, issue_code=issue.code)

    def _find_cold_ref(self, ref):
        if not self.news_repository or not hasattr(self.news_repository, "find_cold_by_keys"):
            return None
        keys = self.dedupe.keys_for_ref(ref)
        if not keys.query_keys():
            return None
        return self.news_repository.find_cold_by_keys(keys)


class AutoPausedSource(RuntimeError):
    pass


class CrawlRunTimeout(TimeoutError):
    pass


def _record_error(result: CrawlResult, issue: CrawlIssue) -> None:
    result.failed += 1
    result.metrics[issue.code] = int(result.metrics.get(issue.code, 0)) + 1
    result.errors.append(issue)


def _issue_from_exception(
    exc: Exception,
    *,
    article_url: str | None = None,
    retryable: bool,
    classify_unknown: bool,
) -> tuple[CrawlIssue, bool]:
    if isinstance(exc, ProviderFailure):
        return CrawlIssue(exc.code, str(exc), article_url, retryable=exc.retryable), exc.pause_source
    if getattr(exc, "pause_source", False):
        code = str(getattr(exc, "issue_code", "credential_expired") or "credential_expired")
        return CrawlIssue(code, str(exc), article_url, retryable=False), True
    code = _issue_code(exc) if classify_unknown else "provider_error"
    return CrawlIssue(code, str(exc), article_url, retryable=retryable), False


def _deadline(now: float, max_runtime_seconds: float) -> float | None:
    if max_runtime_seconds <= 0:
        return None
    return now + max_runtime_seconds


def _raise_if_timed_out(deadline: float | None, monotonic_fn, source_name: str) -> None:
    if deadline is not None and monotonic_fn() >= deadline:
        raise CrawlRunTimeout(f"{source_name} crawl exceeded max runtime")


def _duplicate_reason(existing, keys) -> str:
    if not existing:
        return "upsert_match"
    for key, value in keys.query_keys().items():
        if existing.get(key) == value:
            return key
    return "unknown"


def _empty_page_stats() -> dict[str, int]:
    return {"discovered": 0, "fetched": 0, "inserted": 0, "existing": 0}


def _page_key(ref) -> tuple[str, int] | None:
    metadata = getattr(ref, "metadata", {}) or {}
    page = metadata.get("crawl_page")
    if page is None:
        return None
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        return None
    group = str(metadata.get("crawl_group") or getattr(ref, "section", "") or "default")
    return group, page_number


def _should_skip_page(request: NewsCrawlRequest, page_key: tuple[str, int] | None, stopped_groups: set[str]) -> bool:
    if not request.stop_after_existing_page or request.mode != "latest" or page_key is None:
        return False
    group, page = page_key
    return page > 1 and group in stopped_groups


def _finalize_page_boundary(
    request: NewsCrawlRequest,
    result: CrawlResult,
    page_key: tuple[str, int] | None,
    page_stats: dict[str, int],
    stopped_groups: set[str],
) -> None:
    if not request.stop_after_existing_page or request.mode != "latest" or page_key is None:
        return
    if not page_stats.get("fetched"):
        return
    result.metrics["auto_pages_fetched"] = int(result.metrics.get("auto_pages_fetched", 0)) + 1
    if page_stats.get("existing", 0) > 0 and page_stats.get("inserted", 0) == 0:
        group, page = page_key
        stopped_groups.add(group)
        result.metrics["auto_existing_boundary_pages"] = int(result.metrics.get("auto_existing_boundary_pages", 0)) + 1
        result.metrics[f"auto_stop_after_page:{group}"] = page


def _issue_code(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return "rate_limited"
    if "cookie expired" in message or "api key" in message or "unauthorized" in message or "401" in message:
        return "credential_expired"
    if "title or content not found" in message or "time not found" in message:
        return "extraction_missing"
    if "404" in message or "not found" in message:
        return "stale_link"
    if "timeout" in name or "timed out" in message:
        return "timeout"
    if "403" in message or "anti-bot" in message or "captcha" in message or "blocked" in message or "cloudflare" in message:
        return "blocked"
    if "connection" in message or "remote end closed" in message:
        return "network_error"
    return "parser_error"
