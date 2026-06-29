from stock_pipeline.kaipanla_crawler import KaipanlaCrawler


def test_sector_strength_dataframe_normalizes_compact_dates(monkeypatch):
    crawler = KaipanlaCrawler()

    monkeypatch.setattr(
        crawler,
        "get_sector_strength_history",
        lambda *_args, **_kwargs: {
            "success": True,
            "history_data": [
                {"date": "20260518", "strength": 12, "time": "15:00", "is_historical": True},
                {"date": "2026-05-19", "strength": 8, "time": "15:00", "is_historical": True},
            ],
        },
    )

    frame = crawler.get_sector_strength_dataframe("801346", "2026-05-18", "2026-05-19")

    assert list(frame["date"].dt.strftime("%Y-%m-%d")) == ["2026-05-18", "2026-05-19"]
    assert list(frame["strength"]) == [12, 8]
