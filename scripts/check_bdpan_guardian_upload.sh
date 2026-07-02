#!/usr/bin/env bash
set -euo pipefail

BUNDLE_NAME="${1:-guardian_articles_oldest_8000_20260701T232312Z}"
PID_FILE="/tmp/bdpan-upload-${BUNDLE_NAME}.pid"
LOG_FILE="/tmp/bdpan-upload-${BUNDLE_NAME}.log"
REMOTE_ROOT="NewsAnalysis/guardian_cold/${BUNDLE_NAME}"
BDPAN_BIN="${BDPAN_BIN:-/opt/NewsAnalysis/scripts/bdpan}"

if [[ -s "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
elif pgrep -f "bdpan upload .*${BUNDLE_NAME}" >/dev/null; then
  pid="$(pgrep -f "bdpan upload .*${BUNDLE_NAME}" | head -1)"
else
  pid=""
fi

if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  echo "process: running pid=$pid"
else
  echo "process: not-running"
fi

echo "log: $LOG_FILE"
if [[ -f "$LOG_FILE" ]]; then
  tail -40 "$LOG_FILE"
fi

echo
echo "remote root:"
"$BDPAN_BIN" ls "$REMOTE_ROOT" | sed -n '1,80p'

echo
echo "remote latest sample:"
"$BDPAN_BIN" ls "$REMOTE_ROOT/objects/guardian/2026/05" --order time --desc | sed -n '1,40p' || true
