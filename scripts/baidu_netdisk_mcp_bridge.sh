#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${BAIDU_NETDISK_MCP_CONFIG_DIR:-/opt/NewsAnalysis/local_data/secure/baidu_netdisk_mcp}"
SERVER_URL_FILE="$CONFIG_DIR/server_url"
AUTH_TOKEN_FILE="$CONFIG_DIR/auth_token"

if [[ ! -s "$SERVER_URL_FILE" ]]; then
  cat >&2 <<EOF
Missing Baidu Netdisk MCP server URL.

Put the official MCP endpoint copied from Baidu Netdisk Skill / WorkBuddy into:
  $SERVER_URL_FILE

Example:
  sudo install -d -m 700 -o ubuntu -g ubuntu "$CONFIG_DIR"
  printf '%s\n' 'https://official-mcp-endpoint.example/sse' | sudo tee "$SERVER_URL_FILE" >/dev/null
  sudo chmod 600 "$SERVER_URL_FILE"
EOF
  exit 2
fi

SERVER_URL="$(tr -d '\r\n' < "$SERVER_URL_FILE")"
if [[ -z "$SERVER_URL" ]]; then
  echo "Empty Baidu Netdisk MCP server URL: $SERVER_URL_FILE" >&2
  exit 2
fi

export MCP_REMOTE_NO_BROWSER=1
if [[ -s "$AUTH_TOKEN_FILE" ]]; then
  export MCP_REMOTE_AUTH_TOKEN="$(tr -d '\r\n' < "$AUTH_TOKEN_FILE")"
fi

exec npx -y mcp-remote "$SERVER_URL"
