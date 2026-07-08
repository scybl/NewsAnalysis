# Data Governance Design

The project treats data as a managed asset. The important question is not only "can data be fetched", but also "what exists, what is missing, where is it stored, and can it be restored quickly".

## Data Classes

| Data class | Storage strategy | Reason |
| --- | --- | --- |
| Stock metadata | Hot storage | Small, frequently queried. |
| Daily K-line data | Hot storage | Used by frontend and analysis workflows. |
| Historical minute data | Cold backup plus coverage index | Large, low-frequency access. |
| News articles | Hot storage with source health | Search and evidence retrieval. |
| Audit reports | Generated documents | Human-readable operations review. |

## Coverage Tracking

Coverage tracking records the expected and observed date ranges for a stock. It can answer:

- Does this stock have daily data?
- Does this stock have minute data?
- Which dates are missing?
- Has a cold backup object been uploaded?
- When was the latest health check?

## Gap Handling

The system records gaps explicitly rather than assuming a job succeeded. This protects against:

- Server restarts during crawling.
- I/O contention during cold backup.
- Provider outages.
- Partial uploads.
- Trading-day-specific missing data.

## Cold Backup Principles

- Archive by retrieval unit, not by giant opaque bundle.
- Keep enough metadata hot to know where cold data lives.
- Avoid requiring full archive extraction for a single stock.
- Keep recent data hot until it is complete enough to archive.
- Clean uploaded local cold objects when safe to reduce disk pressure.

## Public Portfolio Redaction

The public package documents these principles but excludes object names, provider-specific crawling details, database indexes, server paths, and production scripts.
