# DataHub

`datahub/` is the boundary for the data middle platform: collection adapters, storage models, coverage indexes, cold-backup indexes, quality checks, and exports used by ValueScope analysis.

The active compatibility implementation still lives under `stock_pipeline/` while the project is migrated safely.

Responsibilities:

| Data domain | Current compatibility modules |
| --- | --- |
| Stock hot data and packages | `stock_pipeline/stock_storage.py`, `stock_pipeline/daily_k_coverage.py`, `stock_pipeline/stock_storage_repair.py` |
| Stock volume/price metadata | `stock_pipeline/stock_volume_price_metadata.py`, `scripts/export_stock_volume_price_metadata.py` |
| Minute cold data | `stock_pipeline/minute_storage.py`, `stock_pipeline/minute_cold_storage.py`, `stock_pipeline/ths_minute.py` |
| Market data | `stock_pipeline/kaipanla.py`, `stock_pipeline/kaipanla_crawler.py` |
| News read model | `stock_pipeline/raw_news.py`, `stock_pipeline/news_library.py`, `stock_pipeline/crawler_monitor.py` |
| Data quality and audit | `stock_pipeline/data_quality.py`, `stock_pipeline/data_random_audit.py`, `stock_pipeline/ops_status.py` |

Rules:

- DataHub modules own MongoDB collection contracts and cold-backup indexes.
- New stock and market data paths should not depend on Tushare unless the provider is explicitly re-enabled.
- News acquisition stays in `NewsCrawler/`; DataHub reads its MongoDB outputs.
