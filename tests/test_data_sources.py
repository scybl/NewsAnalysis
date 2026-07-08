from stock_pipeline.data_sources import data_source_snapshot


def test_data_source_snapshot_exposes_three_market_dimensions():
    snapshot = data_source_snapshot()

    provider_keys = {item["key"] for item in snapshot["providers"]}
    assert {"stock_data", "market_data", "news_data"}.issubset(provider_keys)
    providers_by_key = {item["key"]: item for item in snapshot["providers"]}
    assert providers_by_key["tushare"]["status"] == "archived"
    assert providers_by_key["stock_data"]["label"] == "股票资料包"
    assert providers_by_key["market_data"]["label"] == "市场行情"
    assert providers_by_key["news_data"]["label"] == "市场新闻"

    for item in snapshot["types"]:
        assert "key" not in item
        assert "Tushare" not in item["providers"]
        assert "Tushare" not in item["priority"]
        assert item["primary_provider"] != "Tushare"

    labels = {item["label"]: item for item in snapshot["types"]}
    stock_profile = labels["股票基础信息"]
    daily_quote = labels["个股日行情"]
    minute_quote = labels["分时行情"]
    news_item = labels["新闻"]

    assert stock_profile["label"] == "股票基础信息"
    assert stock_profile["primary_provider"] == "股票资料包"
    assert daily_quote["primary_provider"] == "股票资料包"
    assert minute_quote["primary_provider"] == "市场行情"
    assert news_item["primary_provider"] == "市场新闻"
