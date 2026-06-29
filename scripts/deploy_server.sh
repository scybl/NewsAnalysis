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
DEPLOY_USE_SUDO="${DEPLOY_USE_SUDO:-0}"
DEPLOY_STAGING_PATH="${DEPLOY_STAGING_PATH:-/home/${DEPLOY_USER}/.newsanalysis-deploy}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:${PUBLIC_WEB_PORT:-8765}/api/health}"
DEPLOY_HEALTH_RETRIES="${DEPLOY_HEALTH_RETRIES:-30}"
DEPLOY_CLEAN="${DEPLOY_CLEAN:-0}"
DEPLOY_CLEAN_DRY_RUN="${DEPLOY_CLEAN_DRY_RUN:-0}"
DEPLOY_CLEAN_KEEP="${DEPLOY_CLEAN_KEEP:-.env cache local_data logs reports sessions}"
DEPLOY_BACKUP_ROOT="${DEPLOY_BACKUP_ROOT:-${DEPLOY_PATH%/}.backups}"
SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "${DEPLOY_PORT}")
RSYNC_SSH="ssh -p ${DEPLOY_PORT}"

cd "${ROOT_DIR}"

RELEASE_VERSION="$(git rev-parse --short HEAD 2>/dev/null || printf unknown)"
if [[ -n "$(git status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
  RELEASE_VERSION="${RELEASE_VERSION}-dirty"
fi
RELEASE_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RELEASE_STAMP="${RELEASE_TIME//[:]/-}"
STAGING_DIR="$(mktemp -d)"
trap 'rm -rf -- "${STAGING_DIR}"' EXIT

echo "Deploying ${RELEASE_VERSION} to ${SSH_TARGET}:${DEPLOY_PATH}"

# Build the upload tree only from files already tracked by Git. Modified
# tracked files are included; new files must be staged before deployment.
rsync -a --from0 --files-from=<(git ls-files -z) ./ "${STAGING_DIR}/"

REMOTE_SYNC_PATH="${DEPLOY_PATH}"
if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  REMOTE_SYNC_PATH="${DEPLOY_STAGING_PATH}"
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_SYNC_PATH}' && sudo -n install -d '${DEPLOY_PATH}'"
else
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}'"
fi

REMOTE_BACKUP_PATH="${DEPLOY_BACKUP_ROOT%/}/$(basename "${DEPLOY_PATH}")-${RELEASE_STAMP}"
if [[ "${DEPLOY_CLEAN}" == "1" ]]; then
  echo "Clean deploy mode enabled. Non-whitelisted remote items will be moved to ${REMOTE_BACKUP_PATH}"
  if [[ "${DEPLOY_CLEAN_DRY_RUN}" == "1" ]]; then
    echo "Dry-run mode: remote files will only be listed, not moved, and deployment will stop after the clean preview."
  fi
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "DEPLOY_PATH='${DEPLOY_PATH}' BACKUP_PATH='${REMOTE_BACKUP_PATH}' KEEP_NAMES='${DEPLOY_CLEAN_KEEP}' DRY_RUN='${DEPLOY_CLEAN_DRY_RUN}' USE_SUDO='${DEPLOY_USE_SUDO}' bash -lc '
      set -euo pipefail
      if [[ ! -d \"\${DEPLOY_PATH}\" ]]; then
        echo \"Remote deploy path does not exist yet: \${DEPLOY_PATH}\"
        exit 0
      fi
      if [[ \"\${DRY_RUN}\" != \"1\" ]]; then
        if [[ \"\${USE_SUDO}\" == \"1\" ]]; then
          sudo -n mkdir -p \"\${BACKUP_PATH}\"
        else
          mkdir -p \"\${BACKUP_PATH}\"
        fi
      fi
      while IFS= read -r -d \"\" item; do
        name=\"\$(basename \"\${item}\")\"
        keep=0
        for allowed in \${KEEP_NAMES}; do
          if [[ \"\${name}\" == \"\${allowed}\" ]]; then
            keep=1
            break
          fi
        done
        if [[ \"\${keep}\" == \"1\" ]]; then
          echo \"keep: \${name}\"
          continue
        fi
        echo \"quarantine: \${name} -> \${BACKUP_PATH}/\"
        if [[ \"\${DRY_RUN}\" != \"1\" ]]; then
          if [[ \"\${USE_SUDO}\" == \"1\" ]]; then
            sudo -n mv \"\${item}\" \"\${BACKUP_PATH}/\"
          else
            mv \"\${item}\" \"\${BACKUP_PATH}/\"
          fi
        fi
      done < <(find \"\${DEPLOY_PATH}\" -mindepth 1 -maxdepth 1 -print0)
    '"
  if [[ "${DEPLOY_CLEAN_DRY_RUN}" == "1" ]]; then
    echo "Clean deploy dry-run finished. Re-run with DEPLOY_CLEAN=1 DEPLOY_CLEAN_DRY_RUN=0 to deploy."
    exit 0
  fi
fi

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

rsync -az --delete -e "${RSYNC_SSH}" "${RSYNC_EXCLUDES[@]}" "${STAGING_DIR}/" "${SSH_TARGET}:${REMOTE_SYNC_PATH}/"

if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "sudo -n rsync -a --delete --exclude '.env' --exclude 'cache/' --exclude 'local_data/' --exclude 'logs/' --exclude 'reports/' --exclude 'sessions/' '${REMOTE_SYNC_PATH}/' '${DEPLOY_PATH}/'"
fi

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && test -f .env || cp .env.deploy.sample .env"
if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "sudo -n chown '${DEPLOY_USER}' '${DEPLOY_PATH}/.env' && sudo -n chmod 600 '${DEPLOY_PATH}/.env'"
fi
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && RELEASE_VERSION='${RELEASE_VERSION}' RELEASE_TIME='${RELEASE_TIME}' docker compose -f docker-compose.prod.yml up -d --build"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"

echo "Waiting for ${DEPLOY_HEALTH_URL}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "for attempt in \$(seq 1 '${DEPLOY_HEALTH_RETRIES}'); do if curl --fail --silent --show-error '${DEPLOY_HEALTH_URL}' >/dev/null; then exit 0; fi; sleep 2; done; echo 'Health check failed: ${DEPLOY_HEALTH_URL}' >&2; cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml logs --tail=100 web >&2; exit 1"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}'; for attempt in \$(seq 1 20); do if docker compose -f docker-compose.prod.yml exec -T news-crawler news-crawler health >/dev/null 2>&1; then exit 0; fi; sleep 3; done; echo 'NewsCrawler health check failed' >&2; docker compose -f docker-compose.prod.yml logs --tail=100 news-crawler >&2; exit 1"

echo "Deployed ${RELEASE_VERSION} to ${SSH_TARGET}:${DEPLOY_PATH}"
