from stock_pipeline.crawler_monitor import _failure_stats, _stale_finished_at, news_crawler_prometheus_metrics


def test_stale_finished_at_uses_runtime_deadline_not_cleanup_time():
    assert _stale_finished_at("2026-06-30T17:31:15Z", 300) == "2026-06-30T17:36:15Z"


def test_news_crawler_prometheus_metrics_uses_stable_labels_only():
    text = news_crawler_prometheus_metrics({
        "enabled": True,
        "summary": {
            "source_count": 2,
            "online_count": 1,
            "warning_count": 1,
            "offline_count": 0,
            "paused_count": 0,
            "running_count": 1,
            "expired_running_count": 0,
        },
        "health": [
            {
                "source_name": "guardian",
                "status": "online",
                "recent_success_rate": 1,
                "consecutive_failures": 0,
                "last_inserted_count": 4,
                "average_duration_seconds": 3.5,
                "last_success_at": "2026-07-01T08:00:00Z",
            },
            {
                "source_name": "politico_browser",
                "status": "warning",
                "recent_success_rate": 0.5,
                "consecutive_failures": 2,
                "last_failure_at": "2026-07-01T08:05:00Z",
            },
        ],
        "runs": [
            {"source_name": "guardian", "status": "succeeded", "discovered": 6, "inserted": 4, "updated": 1, "failed": 0},
            {"source_name": "politico_browser", "status": "partial", "discovered": 3, "inserted": 1, "updated": 0, "failed": 2},
        ],
        "failure_stats": {
            "failed_articles": 2,
            "warning_articles": 1,
            "archived_articles": 3,
            "codes": {"empty_response": 2},
            "by_source": {"politico_browser": {"empty_response": 2}},
        },
    })

    assert "# HELP news_crawler_up" in text
    assert "news_crawler_up 1" in text
    assert 'news_crawler_sources{state="online"} 1' in text
    assert 'news_crawler_source_status{source="guardian",status="online"} 1' in text
    assert 'news_crawler_source_recent_success_rate{source="politico_browser"} 0.5' in text
    assert 'news_crawler_recent_runs{source="guardian",status="succeeded"} 1' in text
    assert 'news_crawler_recent_inserted_articles{source="guardian"} 4' in text
    assert 'news_crawler_recent_failure_codes{code="empty_response"} 2' in text
    assert 'news_crawler_recent_failure_codes_by_source{source="politico_browser",code="empty_response"} 2' in text
    assert "https://" not in text
    assert "title or content not found" not in text


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
