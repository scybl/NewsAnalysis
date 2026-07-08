#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

DEPLOY_CLEAN="${DEPLOY_CLEAN:-0}" \
DEPLOY_PROTECT_RUNNING_JOBS=0 \
DEPLOY_FORCE_RESTART=1 \
DEPLOY_SKIP_RESTART=0 \
scripts/deploy_server.sh "$@"
