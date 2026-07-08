#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OUTPUT="${1:-reports/server-data-audit-$(date -u +%Y%m%dT%H%M%SZ).md}"

cd "${ROOT_DIR}"
mkdir -p "$(dirname "${OUTPUT}")"

echo "[server-data-audit] 项目目录：${ROOT_DIR}"
echo "[server-data-audit] 输出文件：${OUTPUT}"

if command -v docker >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
  echo "[server-data-audit] 使用 Docker Compose 服务：web"
  docker compose -f "${COMPOSE_FILE}" exec -T web python scripts/server_data_audit.py --output "/app/${OUTPUT}"
  echo
  echo "报告已写入：${ROOT_DIR}/${OUTPUT}"
else
  echo "[server-data-audit] 未检测到 Docker Compose，使用本机 Python"
  python scripts/server_data_audit.py --output "${OUTPUT}"
  echo
  echo "报告已写入：${ROOT_DIR}/${OUTPUT}"
fi
