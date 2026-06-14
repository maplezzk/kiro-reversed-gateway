#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker 未安装或不在 PATH 中。" >&2
  exit 1
fi

if docker compose ps --services --status running | grep -qx 'kiro-reversed-gateway'; then
  docker compose restart kiro-reversed-gateway
else
  docker compose up -d kiro-reversed-gateway
fi

docker compose ps kiro-reversed-gateway
