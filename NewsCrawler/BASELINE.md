# Migration baseline

The crawler split is verified with committed offline fixtures for Tonghuashun, Guardian, and Bloomberg.

Required fields checked by tests:

- source identity and stable external ID
- canonical URL
- title and body
- publication time and timezone
- section and author where supplied

Historical MongoDB data is preserved through `news-crawler migrate-legacy`. Production operators should export collection indexes and sample counts before running that command, then compare `read`, `inserted`, `updated`, and `failed` totals printed by the migration.
