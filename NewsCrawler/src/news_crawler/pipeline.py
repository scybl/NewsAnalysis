from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from .executor import TaskExecutor
from .models import CrawlResult, NewsCrawlRequest


class CrawlPipeline:
    def __init__(self, registry, executor: TaskExecutor):
        self.registry = registry
        self.executor = executor

    def run(self, request: NewsCrawlRequest, max_workers: int | None = None) -> list[CrawlResult]:
        names = request.sources or tuple(self.registry.names())
        if len(names) <= 1:
            return [self.executor.execute(self.registry.create(name), request) for name in names]
        results_by_name = {}
        with ThreadPoolExecutor(max_workers=max_workers or len(names), thread_name_prefix="news-source") as pool:
            futures = {
                pool.submit(self.executor.execute, self.registry.create(name), request): name
                for name in names
            }
            for future in as_completed(futures):
                results_by_name[futures[future]] = future.result()
        return [results_by_name[name] for name in names]
