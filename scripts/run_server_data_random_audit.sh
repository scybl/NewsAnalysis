#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OUTPUT="${1:-reports/server-data-random-audit-$(date -u +%Y%m%dT%H%M%SZ).md}"
SAMPLE_SIZE="${SAMPLE_SIZE:-20}"
COLD_READ_SAMPLES="${COLD_READ_SAMPLES:-0}"
SEED="${SEED:-}"

cd "${ROOT_DIR}"
mkdir -p "$(dirname "${OUTPUT}")"

echo "[server-data-random-audit] 项目目录：${ROOT_DIR}"
echo "[server-data-random-audit] 输出文件：${OUTPUT}"
echo "[server-data-random-audit] 每类抽样：${SAMPLE_SIZE}"
echo "[server-data-random-audit] 冷备份取回样本：${COLD_READ_SAMPLES}"

ARGS=(--output "/app/${OUTPUT}" --sample-size "${SAMPLE_SIZE}" --cold-read-samples "${COLD_READ_SAMPLES}")
if [[ -n "${SEED}" ]]; then
  ARGS+=(--seed "${SEED}")
fi

if command -v docker >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
  echo "[server-data-random-audit] 使用 Docker Compose 服务：web"
  docker compose -f "${COMPOSE_FILE}" exec -T web python scripts/server_data_random_audit.py "${ARGS[@]}"
  echo
  echo "报告已写入：${ROOT_DIR}/${OUTPUT}"
else
  echo "[server-data-random-audit] 未检测到 Docker Compose，使用本机 Python"
  LOCAL_ARGS=(--output "${OUTPUT}" --sample-size "${SAMPLE_SIZE}" --cold-read-samples "${COLD_READ_SAMPLES}")
  if [[ -n "${SEED}" ]]; then
    LOCAL_ARGS+=(--seed "${SEED}")
  fi
  python scripts/server_data_random_audit.py "${LOCAL_ARGS[@]}"
  echo
  echo "报告已写入：${ROOT_DIR}/${OUTPUT}"
fi
