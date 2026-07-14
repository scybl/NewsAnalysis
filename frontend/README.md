# Frontend

`frontend/` contains browser-facing assets and admin UI code.

Current app:

| Path | Purpose |
| --- | --- |
| `frontend/admin/` | ValueScope DataHub admin console, including HTML, CSS, and browser JavaScript. |

Rules:

- Keep UI copy, page layout, navigation, and browser-only behavior here.
- Call backend APIs instead of reading MongoDB, local files, or cold-storage objects directly.
- Add static contract tests under `tests/` when changing page structure, labels, or route assumptions.
