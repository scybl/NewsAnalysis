# Feature Walkthrough

This walkthrough is written for hiring reviewers. It focuses on user-visible outcomes rather than private implementation details.

## 1. Data Platform Overview

The home experience presents the project as a financial data platform rather than a single crawler script. It surfaces stock datasets, news evidence, market snapshots, and operational health in one place.

What this demonstrates:

- Product framing around data assets.
- Cross-domain data integration.
- Separation between user-facing reading and admin-only operations.

## 2. System Governance

The governance view combines operations status, random data audits, and audit logs.

Typical cards include:

- Long-running task status.
- Heavy I/O blockers.
- Latest crawler result.
- Data random audit outcome.
- Recent warnings and failures.

What this demonstrates:

- Observability for personal infrastructure.
- Practical handling of stuck jobs and interrupted tasks.
- Clear task states instead of opaque terminal logs.

## 3. Stock Storage Status

Each stock can be reviewed as a data asset:

- Hot daily data coverage.
- Cold minute data coverage.
- Last health check time.
- Gap status.
- Local cache availability.

What this demonstrates:

- Data completeness as a first-class product feature.
- Recovery planning after interrupted crawls.
- Read-time separation between hot and cold storage.

## 4. Cold Backup Strategy

Historical minute data is treated as cold data. It is archived into per-stock, time-bounded objects and indexed so one stock can be restored without unpacking a giant archive.

What this demonstrates:

- Storage cost control.
- Retrieval-oriented archive design.
- Separation between hot analysis data and cold historical payloads.

## 5. Access and Security

The admin console groups access and security into one operational area:

- Registered users.
- Archived accounts.
- System credentials.
- Read-only access.

What this demonstrates:

- Practical role separation.
- Safer portfolio/demo access.
- Avoiding direct secret exposure in frontend code.

## 6. Interview Demo Script

Suggested 5-minute flow:

1. Show the data platform overview.
2. Open system governance and explain task status.
3. Open stock storage status and explain gap tracking.
4. Show a sanitized audit report.
5. Explain why public portfolio materials exclude core source code.
