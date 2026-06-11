#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOY_HOST:-}" ]]; then
  echo "DEPLOY_HOST is required, for example: DEPLOY_HOST=1.2.3.4 $0" >&2
  exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/newsanalysis}"
DEPLOY_COPY_ENV="${DEPLOY_COPY_ENV:-1}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "${DEPLOY_PORT}")
RSYNC_SSH="ssh -p ${DEPLOY_PORT}"

cd "${ROOT_DIR}"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}'"

RSYNC_EXCLUDES=(
  --exclude ".git/"
  --exclude ".venv/"
  --exclude ".pip-cache/"
  --exclude "__pycache__/"
  --exclude "*.pyc"
  --exclude ".DS_Store"
  --exclude "cache/"
  --exclude "local_data/"
  --exclude "logs/"
  --exclude "reports/"
  --exclude "sessions/"
)

if [[ "${DEPLOY_COPY_ENV}" != "1" ]]; then
  RSYNC_EXCLUDES+=(--exclude ".env")
fi

rsync -az --delete -e "${RSYNC_SSH}" "${RSYNC_EXCLUDES[@]}" ./ "${SSH_TARGET}:${DEPLOY_PATH}/"

if [[ "${DEPLOY_COPY_ENV}" == "1" ]]; then
  if [[ ! -f ".env" ]]; then
    echo "Local .env not found. Create it first or set DEPLOY_COPY_ENV=0 and configure .env on the server." >&2
    exit 1
  fi
  scp -P "${DEPLOY_PORT}" .env "${SSH_TARGET}:${DEPLOY_PATH}/.env"
fi

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && test -f .env || cp .env.deploy.sample .env"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml up -d --build"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"

echo "Deployed to ${SSH_TARGET}:${DEPLOY_PATH}"
