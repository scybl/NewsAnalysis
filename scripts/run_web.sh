#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# 本地默认127.0.0.1
HOST="127.0.0.1"

# Linux服务器默认开放外网
if [[ "$(uname -s)" == "Linux" ]]; then
    HOST="0.0.0.0"
fi

exec .venv/bin/python -m stock_pipeline web \
    --host "${STOCK_WEB_HOST:-$HOST}" \
    --port "${STOCK_WEB_PORT:-8765}"
~                                             