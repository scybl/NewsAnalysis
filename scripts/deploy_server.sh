#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_CONFIG="${DEPLOY_CONFIG:-${ROOT_DIR}/.deploy.env}"

if [[ -f "${DEPLOY_CONFIG}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${DEPLOY_CONFIG}"
  set +a
fi

if [[ -z "${DEPLOY_HOST:-}" ]]; then
  echo "DEPLOY_HOST is required. Copy .deploy.env.sample to .deploy.env and configure it first." >&2
  exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/newsanalysis}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:${PUBLIC_WEB_PORT:-8765}/api/health}"
DEPLOY_HEALTH_RETRIES="${DEPLOY_HEALTH_RETRIES:-30}"
SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "${DEPLOY_PORT}")
RSYNC_SSH="ssh -p ${DEPLOY_PORT}"

cd "${ROOT_DIR}"

RELEASE_VERSION="$(git rev-parse --short HEAD 2>/dev/null || printf unknown)"
if [[ -n "$(git status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
  RELEASE_VERSION="${RELEASE_VERSION}-dirty"
fi
RELEASE_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STAGING_DIR="$(mktemp -d)"
trap 'rm -rf -- "${STAGING_DIR}"' EXIT

echo "Deploying ${RELEASE_VERSION} to ${SSH_TARGET}:${DEPLOY_PATH}"

# Build the upload tree only from files already tracked by Git. Modified
# tracked files are included; new files must be staged before deployment.
rsync -a --from0 --files-from=<(git ls-files -z) ./ "${STAGING_DIR}/"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}'"

RSYNC_EXCLUDES=(
  --exclude ".git/"
  --exclude ".env"
  --exclude ".deploy.env"
  --exclude ".ssh/"
  --exclude ".aws/"
  --exclude "*.pem"
  --exclude "*.key"
  --exclude "*.p12"
  --exclude "*.pfx"
  --exclude "*.db"
  --exclude "*.sqlite*"
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

rsync -az --delete -e "${RSYNC_SSH}" "${RSYNC_EXCLUDES[@]}" "${STAGING_DIR}/" "${SSH_TARGET}:${DEPLOY_PATH}/"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && test -f .env || cp .env.deploy.sample .env"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && RELEASE_VERSION='${RELEASE_VERSION}' RELEASE_TIME='${RELEASE_TIME}' docker compose -f docker-compose.prod.yml up -d --build"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"

echo "Waiting for ${DEPLOY_HEALTH_URL}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "for attempt in \$(seq 1 '${DEPLOY_HEALTH_RETRIES}'); do if curl --fail --silent --show-error '${DEPLOY_HEALTH_URL}' >/dev/null; then exit 0; fi; sleep 2; done; echo 'Health check failed: ${DEPLOY_HEALTH_URL}' >&2; cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml logs --tail=100 web >&2; exit 1"

echo "Deployed ${RELEASE_VERSION} to ${SSH_TARGET}:${DEPLOY_PATH}"
