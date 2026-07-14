# stock_pipeline Compatibility Package

`stock_pipeline/` is the historical Python package name for NewsAnalysis and remains the deployable compatibility surface for the current server, CLI, and tests.

New development should use the layer boundaries documented in:

- `frontend/README.md`
- `backend/README.md`
- `datahub/README.md`
- `docs/LAYER_BOUNDARIES.md`

Migration policy:

- Keep existing imports working until a module is moved with a compatibility shim and tests.
- Prefer adding new UI files under `frontend/admin/`.
- Prefer routing new HTTP/task orchestration work through the backend boundary.
- Prefer putting new storage, coverage, cold-backup, and export logic behind the DataHub boundary.
