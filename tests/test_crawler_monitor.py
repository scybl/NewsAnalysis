from stock_pipeline.crawler_monitor import _failure_stats, _stale_finished_at


def test_stale_finished_at_uses_runtime_deadline_not_cleanup_time():
    assert _stale_finished_at("2026-06-30T17:31:15Z", 300) == "2026-06-30T17:36:15Z"


def test_failure_stats_groups_empty_and_connection_closed_items():
    stats = _failure_stats([
        {
            "run_id": "run-1",
            "source_name": "tonghuashun",
            "started_at": "2026-06-26T10:00:00Z",
            "failed": 2,
            "errors": [
                {
                    "code": "parser_error",
                    "message": "article title or content not found",
                    "article_url": "https://example.com/empty",
                },
                {
                    "code": "parser_error",
                    "message": "Remote end closed connection without response",
                    "article_url": "https://example.com/closed",
                },
            ],
        }
    ])

    assert stats["failed_runs"] == 1
    assert stats["failed_articles"] == 2
    assert stats["codes"] == {"empty_response": 1, "connection_closed": 1}
    assert stats["items"][0]["article_url"] == "https://example.com/empty"
    assert stats["items"][1]["code"] == "connection_closed"


def test_failure_stats_item_limit_does_not_change_scanned_runs():
    runs = [
        {
            "run_id": f"run-{index}",
            "source_name": "tonghuashun",
            "started_at": f"2026-06-26T10:{index:02d}:00Z",
            "failed": 1,
            "errors": [{"code": "parser_error", "message": "article title or content not found"}],
        }
        for index in range(5)
    ]

    stats = _failure_stats(runs, item_limit=2)

    assert stats["runs_scanned"] == 5
    assert stats["failed_articles"] == 5
    assert stats["codes"] == {"empty_response": 5}
    assert len(stats["items"]) == 1
    assert stats["items"][0]["count"] == 5


def test_failure_stats_groups_same_error_with_different_urls():
    runs = [
        {
            "run_id": f"run-{index}",
            "source_name": "tonghuashun",
            "started_at": f"2026-06-26T10:{index:02d}:00Z",
            "failed": 1,
            "errors": [
                {
                    "code": "stale_link",
                    "message": f"404 Client Error: Not Found for url: https://m.10jqka.com.cn/hks/202606{index:02d}/c6774355{index}.shtml",
                    "article_url": f"https://m.10jqka.com.cn/hks/202606{index:02d}/c6774355{index}.shtml",
                }
            ],
        }
        for index in range(3)
    ]

    stats = _failure_stats(runs)

    assert stats["failed_articles"] == 3
    assert stats["codes"] == {"stale_link": 3}
    assert len(stats["items"]) == 1
    assert stats["items"][0]["count"] == 3
    assert len(stats["items"][0]["sample_urls"]) == 3


def test_failure_stats_hides_archived_urls():
    stats = _failure_stats(
        [
            {
                "run_id": "run-1",
                "source_name": "tonghuashun",
                "started_at": "2026-06-26T10:00:00Z",
                "failed": 2,
                "errors": [
                    {"code": "stale_link", "message": "404 Client Error", "article_url": "https://example.com/a"},
                    {"code": "stale_link", "message": "404 Client Error", "article_url": "https://example.com/b"},
                ],
            }
        ],
        archived_urls={"https://example.com/a"},
    )

    assert stats["failed_articles"] == 1
    assert stats["archived_articles"] == 1
    assert stats["items"][0]["sample_urls"] == ["https://example.com/b"]
