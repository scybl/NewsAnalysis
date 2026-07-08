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
DEPLOY_SSH_CONNECT_TIMEOUT="${DEPLOY_SSH_CONNECT_TIMEOUT:-10}"
DEPLOY_SSH_ALIVE_INTERVAL="${DEPLOY_SSH_ALIVE_INTERVAL:-15}"
DEPLOY_SSH_ALIVE_COUNT_MAX="${DEPLOY_SSH_ALIVE_COUNT_MAX:-3}"
DEPLOY_PROTECT_RUNNING_JOBS="${DEPLOY_PROTECT_RUNNING_JOBS:-1}"
DEPLOY_FORCE_RESTART="${DEPLOY_FORCE_RESTART:-0}"
DEPLOY_SKIP_RESTART="${DEPLOY_SKIP_RESTART:-0}"
DEPLOY_BUILD_WHEN_PROTECTED="${DEPLOY_BUILD_WHEN_PROTECTED:-1}"
DEPLOY_PROTECTED_PROCESS_REGEX="${DEPLOY_PROTECTED_PROCESS_REGEX:-python .*stock_pipeline market minute-cold|stock_pipeline market minute-cold|bdpan .* upload|minute-cold-stock-year-upload}"
DEPLOY_PROTECTED_TASK_STATUSES="${DEPLOY_PROTECTED_TASK_STATUSES:-queued running stopping}"
SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(
  -p "${DEPLOY_PORT}"
  -o "ConnectTimeout=${DEPLOY_SSH_CONNECT_TIMEOUT}"
  -o "ServerAliveInterval=${DEPLOY_SSH_ALIVE_INTERVAL}"
  -o "ServerAliveCountMax=${DEPLOY_SSH_ALIVE_COUNT_MAX}"
)
RSYNC_SSH="ssh -p ${DEPLOY_PORT} -o ConnectTimeout=${DEPLOY_SSH_CONNECT_TIMEOUT} -o ServerAliveInterval=${DEPLOY_SSH_ALIVE_INTERVAL} -o ServerAliveCountMax=${DEPLOY_SSH_ALIVE_COUNT_MAX}"

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
echo "[1/8] Preparing upload tree from Git-tracked files..."
rsync -a --from0 --files-from=<(git ls-files -z) ./ "${STAGING_DIR}/"
echo "[1/8] Upload tree ready: $(find "${STAGING_DIR}" -type f | wc -l | tr -d ' ') files, $(du -sh "${STAGING_DIR}" | awk '{print $1}')"

REMOTE_SYNC_PATH="${DEPLOY_PATH}"
if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  REMOTE_SYNC_PATH="${DEPLOY_STAGING_PATH}"
  echo "[2/8] Creating remote staging path ${REMOTE_SYNC_PATH} and deploy path ${DEPLOY_PATH}..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_SYNC_PATH}' && sudo -n install -d '${DEPLOY_PATH}'"
else
  echo "[2/8] Creating remote deploy path ${DEPLOY_PATH}..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}'"
fi
echo "[2/8] Remote path is ready."

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

echo "[3/8] Uploading files to ${SSH_TARGET}:${REMOTE_SYNC_PATH}/..."
rsync -az --delete --progress --stats -e "${RSYNC_SSH}" "${RSYNC_EXCLUDES[@]}" "${STAGING_DIR}/" "${SSH_TARGET}:${REMOTE_SYNC_PATH}/"
echo "[3/8] Upload complete."

if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  echo "[4/8] Copying staged files into sudo-owned deploy path..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "sudo -n rsync -a --delete --exclude '.env' --exclude 'cache/' --exclude 'local_data/' --exclude 'logs/' --exclude 'reports/' --exclude 'sessions/' '${REMOTE_SYNC_PATH}/' '${DEPLOY_PATH}/'"
else
  echo "[4/8] Sudo copy not needed."
fi

echo "[5/8] Ensuring remote .env exists..."
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && test -f .env || cp .env.deploy.sample .env"
if [[ "${DEPLOY_USE_SUDO}" == "1" ]]; then
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "sudo -n chown '${DEPLOY_USER}' '${DEPLOY_PATH}/.env' && sudo -n chmod 600 '${DEPLOY_PATH}/.env'"
fi
echo "[5/8] Remote .env is ready."

if [[ "${DEPLOY_SKIP_RESTART}" == "1" ]]; then
  echo "[6/8] Building Docker images without restarting running containers..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && RELEASE_VERSION='${RELEASE_VERSION}' RELEASE_TIME='${RELEASE_TIME}' docker compose -f docker-compose.prod.yml build"
  echo "[7/8] Reading Docker service status..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"
  echo "[8/8] Restart skipped by DEPLOY_SKIP_RESTART=1."
  echo "Uploaded and built ${RELEASE_VERSION}, but did not activate it because restart was explicitly disabled."
  echo "To activate the new image later, run: qiangzhitongbu"
  exit 0
fi

if [[ "${DEPLOY_PROTECT_RUNNING_JOBS}" == "1" && "${DEPLOY_FORCE_RESTART}" != "1" ]]; then
  echo "[6/8] Checking protected long-running jobs before container restart..."
  set +e
  PROTECTED_JOBS="$(
    ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && PROTECTED_REGEX='${DEPLOY_PROTECTED_PROCESS_REGEX}' PROTECTED_TASK_STATUSES='${DEPLOY_PROTECTED_TASK_STATUSES}' python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path

protected_statuses = {item.strip() for item in os.environ.get(\"PROTECTED_TASK_STATUSES\", \"queued running stopping\").split() if item.strip()}
admin_tasks_path = Path(\"local_data/admin_tasks.json\")
if admin_tasks_path.exists():
    try:
        payload = json.loads(admin_tasks_path.read_text(encoding=\"utf-8\"))
        tasks = payload.get(\"tasks\", []) if isinstance(payload, dict) else payload
        active = [
            item for item in tasks
            if isinstance(item, dict) and str(item.get(\"status\") or \"\") in protected_statuses
        ]
        if active:
            print(\"[admin tasks]\")
            for item in active[-20:]:
                print(
                    f\"{item.get('task_id', '')} status={item.get('status', '')} \"
                    f\"kind={item.get('kind', '')} title={item.get('title', '')} updated={item.get('updated_at', '')}\"
                )
    except Exception as exc:
        print(f\"[admin tasks read failed] {exc}\")

protected_regex = os.environ.get(\"PROTECTED_REGEX\", \"\")
if protected_regex:
    host_matches = subprocess.run([\"pgrep\", \"-af\", protected_regex], text=True, capture_output=True, check=False).stdout.strip()
    if host_matches:
        print(\"[host]\")
        print(host_matches)

    protected_services = [\"web\", \"minute-cold-worker\"]
    for service in protected_services:
        service_ps = subprocess.run(
            [\"docker\", \"compose\", \"-f\", \"docker-compose.prod.yml\", \"ps\", \"-q\", service],
            text=True,
            capture_output=True,
            check=False,
        )
        if not service_ps.stdout.strip():
            continue
        ps_output = subprocess.run(
            [\"docker\", \"compose\", \"-f\", \"docker-compose.prod.yml\", \"exec\", \"-T\", service, \"sh\", \"-lc\", \"ps -eo pid,args 2>/dev/null || ps aux\"],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        web_matches = \"\\n\".join(line for line in ps_output.splitlines() if re.search(protected_regex, line))
        if web_matches:
            print(f\"[{service} container]\")
            print(web_matches)

    news_services = [\"news-crawler\", \"news-crawler-guardian\"]
    for service in news_services:
        service_ps = subprocess.run(
            [\"docker\", \"compose\", \"-f\", \"docker-compose.prod.yml\", \"ps\", \"-q\", service],
            text=True,
            capture_output=True,
            check=False,
        )
        if not service_ps.stdout.strip():
            continue
        runs_query = subprocess.run(
            [\"docker\", \"compose\", \"-f\", \"docker-compose.prod.yml\", \"exec\", \"-T\", service, \"news-crawler\", \"runs\", \"--limit\", \"20\"],
            text=True,
            capture_output=True,
            check=False,
        )
        if runs_query.returncode != 0:
            continue
        try:
            rows = json.loads(runs_query.stdout or \"[]\")
        except Exception:
            rows = []
        active_runs = [
            row for row in rows
            if isinstance(row, dict) and str(row.get(\"status\") or \"\") in protected_statuses
        ]
        if active_runs:
            print(f\"[{service} active crawl_runs]\")
            for row in active_runs[:10]:
                print(
                    f\"{row.get('run_id', '')} status={row.get('status', '')} \"
                    f\"source={row.get('source_name', '')} started={row.get('started_at', '')}\"
                )
PY"
  )"
  PROTECTED_CHECK_STATUS=$?
  set -e
  if [[ "${PROTECTED_CHECK_STATUS}" != "0" ]]; then
    echo "[6/8] Protected job check failed; aborting before restart." >&2
    exit "${PROTECTED_CHECK_STATUS}"
  fi
  if [[ -n "${PROTECTED_JOBS}" ]]; then
    echo "[6/8] Protected long-running job detected. Docker containers will NOT be restarted."
    echo "${PROTECTED_JOBS}"
    if [[ "${DEPLOY_BUILD_WHEN_PROTECTED}" == "1" ]]; then
      echo "[6/8] Building images only; the running containers keep using the previous image until the next restart."
      ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && RELEASE_VERSION='${RELEASE_VERSION}' RELEASE_TIME='${RELEASE_TIME}' docker compose -f docker-compose.prod.yml build"
      echo "[7/8] Reading Docker service status..."
      ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"
      echo "[8/8] Restart skipped to protect running jobs."
      echo "Uploaded and built ${RELEASE_VERSION}, but did not activate it because protected jobs are running."
      echo "After the task finishes, run: qiangzhitongbu"
      exit 0
    fi
    echo "Deployment stopped before restart. Set DEPLOY_FORCE_RESTART=1 to override." >&2
    exit 42
  fi
fi

COMPOSE_UP_FLAGS="-d --build"
if [[ "${DEPLOY_FORCE_RESTART}" == "1" ]]; then
  COMPOSE_UP_FLAGS="${COMPOSE_UP_FLAGS} --force-recreate"
fi

if [[ "${DEPLOY_FORCE_RESTART}" == "1" ]]; then
  echo "[6/8] Rebuilding and force-recreating Docker services..."
else
  echo "[6/8] Rebuilding and starting Docker services..."
fi
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && RELEASE_VERSION='${RELEASE_VERSION}' RELEASE_TIME='${RELEASE_TIME}' docker compose -f docker-compose.prod.yml up ${COMPOSE_UP_FLAGS}"
echo "[6/8] Docker compose up finished."
echo "[7/8] Reading Docker service status..."
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml ps"

echo "[8/8] Waiting for ${DEPLOY_HEALTH_URL}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "for attempt in \$(seq 1 '${DEPLOY_HEALTH_RETRIES}'); do if curl --fail --silent --show-error '${DEPLOY_HEALTH_URL}' >/dev/null; then exit 0; fi; sleep 2; done; echo 'Health check failed: ${DEPLOY_HEALTH_URL}' >&2; cd '${DEPLOY_PATH}' && docker compose -f docker-compose.prod.yml logs --tail=100 web >&2; exit 1"
echo "[8/8] Web health check passed. Checking NewsCrawler..."
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}'; for attempt in \$(seq 1 20); do if docker compose -f docker-compose.prod.yml exec -T news-crawler news-crawler health >/dev/null 2>&1; then exit 0; fi; sleep 3; done; echo 'NewsCrawler health check failed' >&2; docker compose -f docker-compose.prod.yml logs --tail=100 news-crawler >&2; exit 1"

echo "Deployed ${RELEASE_VERSION} to ${SSH_TARGET}:${DEPLOY_PATH}"
