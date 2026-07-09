# ValueScope DataHub Portfolio

This repository is a public portfolio package for **ValueScope DataHub**, a personal data collection, governance, and display platform for A-share market/news datasets. The collected and curated data is designed to support downstream **ValueScope** analysis.

The production source code is intentionally not included here. This package is designed for interview and portfolio review only: it explains the architecture, product decisions, data governance model, and user-visible workflows without exposing crawler implementations, storage internals, deployment scripts, credentials, or proprietary automation logic.

## What This Project Demonstrates

- A full-stack data collection and display platform for stock, market, and news workflows.
- MongoDB-backed hot storage with Baidu Netdisk cold backup for low-frequency minute data.
- Data quality checks, random audits, gap tracking, and operational reporting.
- Admin console for access/security, system governance, stock storage status, market data, news data, and task health.
- Safe deployment concepts that avoid interrupting long-running crawlers or uploads.
- Test coverage across API contracts, integration flows, frontend contracts, regression checks, and lightweight performance baselines.

## Public Package Contents

| Path | Purpose |
| --- | --- |
| `docs/architecture.md` | High-level architecture and ownership boundaries. |
| `docs/feature-walkthrough.md` | Portfolio-friendly walkthrough of key workflows. |
| `docs/data-governance.md` | Data coverage, cold backup, and quality-check design. |
| `docs/interview-notes.md` | Talking points for recruiters and engineers. |
| `api-examples/` | Sanitized API and audit response examples. |
| `mock-demo/static-preview/` | Static UI preview that does not call backend services. |
| `LICENSE` | Portfolio evaluation license. |
| `NOTICE.md` | Copyright and usage boundaries. |
| `SECURITY.md` | What is intentionally excluded from the public package. |

## What Is Not Public

The following parts remain private by design:

- Real crawler implementations and provider-specific reverse engineering.
- MongoDB schemas, indexes, and production query details beyond high-level descriptions.
- Baidu Netdisk sync implementation and cold backup object layout internals.
- Production Docker Compose, deployment scripts, secrets, server paths, and runtime data.
- Real API keys, cookies, tokens, credentials, cold backup indexes, and datasets.
- Any automation that can mutate production data.

## Tech Stack Summary

| Layer | Technologies |
| --- | --- |
| Backend | Python, custom HTTP API, CLI tasks |
| Storage | MongoDB, JSON/JSONL, local cache, cold backup |
| Market data | Eastmoney, Kaipanla, Tonghuashun, pytdx/mootdx/tdxpy, AkShare candidates |
| News data | Independent NewsCrawler service, requests/Selenium/lxml/BeautifulSoup |
| Downstream analysis supply | Data manifests, historical report compatibility, optional DeepSeek/multi-agent integration surface |
| Frontend | Native HTML, CSS, JavaScript |
| Ops | Docker Compose, GitHub Actions, audit reports, task snapshots |
| Security | TOTP, signed cookies, encrypted secret store, role-based access |

## Interview Review Flow

1. Read the architecture and governance docs in `docs/`.
2. Open `mock-demo/static-preview/index.html` for a safe static preview.
3. Inspect sanitized API examples under `api-examples/`.
4. Ask the author to screen-share private source modules during an interview if deeper review is needed.

## License

This portfolio package is published for review and evaluation only. See `LICENSE` and `NOTICE.md`.
