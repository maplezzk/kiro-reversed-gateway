#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
LISTEN_HOST="${CONNECT_PROXY_HOST:-127.0.0.1}"
LISTEN_PORT="${CONNECT_PROXY_PORT:-7898}"
TARGET_HOST="${GATEWAY_HOST:-127.0.0.1}"
TARGET_PORT="${GATEWAY_PORT:-443}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

exec python connect_proxy.py \
  --listen-host "$LISTEN_HOST" \
  --listen-port "$LISTEN_PORT" \
  --target-host "$TARGET_HOST" \
  --target-port "$TARGET_PORT"
