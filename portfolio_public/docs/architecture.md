# Architecture

ValueScope / NewsAnalysis is organized as a financial data platform with clear ownership boundaries between collection, storage, governance, operations, and presentation.

## System Layers

```mermaid
flowchart TB
  sources["Market and News Sources"]
  crawler["Collection Workers"]
  hot["MongoDB Hot Storage"]
  cold["Cold Backup"]
  index["Coverage and Health Indexes"]
  api["Web API"]
  ui["Admin and Research UI"]
  audit["Audit Reports and Random Checks"]

  sources --> crawler
  crawler --> hot
  hot --> index
  hot --> api
  index --> api
  hot --> cold
  cold --> api
  api --> ui
  audit --> ui
  hot --> audit
  index --> audit
```

## Design Goals

- Keep frequently accessed daily data hot in MongoDB.
- Move heavy historical minute data into cold storage while preserving fast per-stock retrieval.
- Track coverage and gaps so interrupted crawls can be resumed without guessing.
- Make long-running jobs visible in the UI, including progress, status, resource level, and latest event.
- Separate portfolio visibility from production implementation.

## Ownership Boundaries

| Area | Responsibility |
| --- | --- |
| NewsCrawler | Collect and normalize news into a stable news document contract. |
| Stock pipeline | Maintain stock metadata, daily rows, minute coverage, and cold backup references. |
| Web API | Serve stock, news, governance, account, and audit views. |
| Admin UI | Present operational status and allow controlled actions for the owner. |
| Cold backup | Store low-frequency historical objects outside the hot database. |

## Production Code Visibility

The public portfolio package intentionally describes architecture at a high level. It does not include implementation details that would allow a third party to reproduce the crawler, storage, or deployment system.
