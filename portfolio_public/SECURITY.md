# Security Policy

This public portfolio package must never contain production secrets, source code, deployment scripts, or real datasets.

## Public-Safe Content

- Architecture notes.
- Sanitized API examples.
- Static screenshots or static preview pages.
- Mock data with fake IDs and dates.
- High-level diagrams and interview notes.

## Forbidden Content

- `.env` files, private keys, cookies, tokens, app keys, secret keys, sign keys, or access tokens.
- Real server IPs, SSH usernames, internal deployment paths, or production hostnames.
- Python backend modules, crawler code, Docker Compose files, shell deployment scripts, or MongoDB migration scripts.
- Real MongoDB dumps, Baidu Netdisk object indexes, stock datasets, raw news datasets, cache files, logs, sessions, and reports.
- Any file copied from `local_data`, `cache`, `logs`, `reports`, `sessions`, or production secure directories.

## Review Before Publishing

Before copying this package into a public repository, run the private repository safety check:

```bash
.venv/bin/python scripts/verify_portfolio_public.py
```

If the check fails, do not publish the package.
