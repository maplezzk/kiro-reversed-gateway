#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

get_env_value() {
  local key="$1"
  grep -E "^[[:space:]]*${key}=" .env 2>/dev/null | tail -n 1 | cut -d '=' -f 2- | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'$/\1/"
}

mode="missing-env"
if [[ -f ".env" ]]; then
  mode="$(get_env_value MODE || true)"
  mode="${mode:-openai}"
fi

container_status="unknown"
if command -v docker >/dev/null 2>&1; then
  container_status="$(docker compose ps --status running --services 2>/dev/null | grep -x 'kiro-reversed-gateway' || true)"
  if [[ -n "$container_status" ]]; then
    container_status="running"
  else
    container_status="stopped"
  fi
fi

printf 'MODE=%s\n' "$mode"
printf 'DOCKER=%s\n' "$container_status"
if [[ -f ".env" ]]; then
  printf 'FORWARD_TARGET=%s\n' "$(get_env_value FORWARD_TARGET || true)"
  printf 'KIRO_RUNTIME_IP=%s\n' "$(get_env_value KIRO_RUNTIME_IP || true)"
  printf 'KIRO_MANAGEMENT_IP=%s\n' "$(get_env_value KIRO_MANAGEMENT_IP || true)"
  printf 'KIRO_Q_IP=%s\n' "$(get_env_value KIRO_Q_IP || true)"
fi
