# Interview Notes

## One-Minute Pitch

ValueScope DataHub is a personal data collection, governance, and display platform for A-share research data. It collects market and news data, stores daily data hot in MongoDB, archives heavy minute data into cold backup, tracks data gaps, exposes an admin console, and supplies curated datasets for downstream ValueScope analysis.

## Why It Is More Than a Script

- It has multiple data domains: stocks, market dimensions, news, cold backup, and audit logs.
- It is positioned as the data layer for downstream ValueScope analysis rather than as the primary analysis engine.
- It distinguishes hot data from cold data.
- It has operational safety around long-running jobs.
- It includes data quality and gap tracking.
- It has frontend workflows for governance rather than only terminal commands.
- It has tests across API, integration, frontend contracts, regression, and performance baselines.

## Engineering Tradeoffs

| Decision | Tradeoff |
| --- | --- |
| MongoDB hot storage | Flexible documents and fast iteration, with explicit indexes and audits needed for discipline. |
| Cold backup for minute data | Saves server disk, but requires coverage indexes and restore workflows. |
| Native frontend | Fewer build dependencies, but more manual UI consistency work. |
| Separate NewsCrawler service | Cleaner ownership, with a contract boundary to maintain. |
| Safe sync vs force sync | Protects long-running jobs, while still allowing emergency activation. |

## What To Show in a Screen Share

- Task registry and operations snapshot.
- Data audit report generation.
- Daily K-line coverage and gap records.
- Cold backup index and restore path at a high level.
- Tests that protect UI/backend contracts.

## What Not To Share Publicly

- Real provider code.
- Production credentials.
- Server paths or IPs.
- Full MongoDB schema/index details.
- Baidu Netdisk upload implementation.
- Raw datasets or cold backup object keys.
