#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec .venv/bin/python -m stock_pipeline web --host "${STOCK_WEB_HOST:-127.0.0.1}" --port "${STOCK_WEB_PORT:-8765}"
