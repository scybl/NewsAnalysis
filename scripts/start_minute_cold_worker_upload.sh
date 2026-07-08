#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE="${MINUTE_COLD_WORKER_SERVICE:-minute-cold-worker}"
SOURCE="${MINUTE_COLD_SOURCE:-pytdx_history}"
LOG_FILE="${MINUTE_COLD_UPLOAD_LOG:-/app/logs/minute-cold-stock-year-upload.log}"
PID_FILE="${MINUTE_COLD_UPLOAD_PID:-/app/logs/minute-cold-stock-year-upload.pid}"

echo "[minute-cold-worker] ensuring worker service is running..."
docker compose -f "${COMPOSE_FILE}" --profile cold-worker up -d "${SERVICE}"

echo "[minute-cold-worker] checking existing upload process..."
if docker compose -f "${COMPOSE_FILE}" exec -T "${SERVICE}" sh -lc "test -f '${PID_FILE}' && kill -0 \$(cat '${PID_FILE}') 2>/dev/null"; then
  echo "[minute-cold-worker] upload already running: pid=$(docker compose -f "${COMPOSE_FILE}" exec -T "${SERVICE}" sh -lc "cat '${PID_FILE}'")"
  echo "[minute-cold-worker] tail with: docker compose -f ${COMPOSE_FILE} exec -T ${SERVICE} tail -f ${LOG_FILE}"
  exit 0
fi

echo "[minute-cold-worker] starting upload source=${SOURCE}..."
docker compose -f "${COMPOSE_FILE}" exec -T "${SERVICE}" sh -lc "
  mkdir -p /app/logs
  nohup python -u -m stock_pipeline market minute-cold export-stock-year-upload --source '${SOURCE}' >> '${LOG_FILE}' 2>&1 &
  echo \$! > '${PID_FILE}'
  echo started pid=\$(cat '${PID_FILE}')
"

echo "[minute-cold-worker] tail with: docker compose -f ${COMPOSE_FILE} exec -T ${SERVICE} tail -f ${LOG_FILE}"
