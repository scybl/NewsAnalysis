from __future__ import annotations

STOCK_DATABASE = "stock_data"
MARKET_DATABASE = "market_data"
NEWS_DATABASE = "news"

STOCK_COLLECTIONS = {
    "packages": "stock_packages",
    "metadata": "stock_metadata",
    "rows": "stock_dataset_rows",
    "files": "stock_json_files",
    "daily_coverage": "stock_daily_coverage",
}

MARKET_COLLECTIONS = {
    "minute_buckets": "minute_day_buckets",
    "minute_payloads": "market_minute_payloads",
    "minute_day_index": "stock_minute_day_index",
    "minute_coverage": "stock_minute_coverage",
    "kaipanla_results": "kaipanla_results",
}

LEGACY_STOCK_MARKET_DATABASE = "stock_market"
LEGACY_STOCK_COLLECTIONS = {
    "packages": "local_data_stock_packages",
    "metadata": "local_data_stock_metadata",
    "rows": "local_data_stock_dataset_rows",
    "files": "local_data_json_files",
}
