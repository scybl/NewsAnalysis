# Backend

`backend/` is the boundary for HTTP APIs, authentication, task orchestration, and process/runtime control.

The active compatibility implementation still lives in `stock_pipeline/web.py` and related modules. New backend work should follow this boundary even when the import path remains under `stock_pipeline` during the gradual migration.

Current backend boundary modules:

| Module | Purpose |
| --- | --- |
| `backend/paths.py` | Frontend/static paths exposed by the web service. |
| `backend/auth_policy.py` | Role sets and page-level access policy. |
| `backend/fetch_registry.py` | Canonical data keys and fetch method registry. |
| `backend/credentials_registry.py` | Admin-visible credential specs and secret file locations. |

Compatibility responsibilities:

| Area | Current compatibility modules |
| --- | --- |
| HTTP routes and admin API | `stock_pipeline/web.py` |
| Accounts, sessions, credentials | `stock_pipeline/web.py`, `stock_pipeline/secret_store.py`, `stock_pipeline/totp.py` |
| Background task queue | `stock_pipeline/task_queue.py` |
| System status API | `stock_pipeline/ops_status.py` |
| CLI entrypoint | `stock_pipeline/cli.py`, `stock_pipeline/__main__.py` |

Rules:

- Backend code validates requests, enforces permissions, and returns stable API contracts.
- Heavy data work should be scheduled through the resource-aware task queue instead of running directly in request handlers.
- Backend must call DataHub modules for data access; frontend must not bypass it.
- New APIs should reference `backend/fetch_registry.py` for data keys and fetch method names instead of hard-coding route labels in handlers.
