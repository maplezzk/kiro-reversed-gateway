#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2
  exit 1
}

get_env_value() {
  local key="$1"
  grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | cut -d '=' -f 2- | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'$/\1/"
}

if [[ ! -f ".env" ]]; then
  fail ".env 不存在，请先 cp .env.example .env 并完成配置。"
fi

forward_target="$(get_env_value FORWARD_TARGET || true)"
forward_target="${forward_target:-auto}"
missing=()
case "$forward_target" in
  auto)
    [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing+=("KIRO_RUNTIME_IP")
    [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing+=("KIRO_MANAGEMENT_IP")
    ;;
  runtime)
    [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing+=("KIRO_RUNTIME_IP")
    ;;
  management)
    [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing+=("KIRO_MANAGEMENT_IP")
    ;;
  q)
    [[ -n "$(get_env_value KIRO_Q_IP || true)" ]] || missing+=("KIRO_Q_IP")
    ;;
  random)
    [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing+=("KIRO_RUNTIME_IP")
    [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing+=("KIRO_MANAGEMENT_IP")
    [[ -n "$(get_env_value KIRO_Q_IP || true)" ]] || missing+=("KIRO_Q_IP")
    ;;
  *)
    fail "FORWARD_TARGET 只能是 auto/runtime/management/q/random，当前值: $forward_target"
    ;;
esac

if [[ ${#missing[@]} -gt 0 ]]; then
  fail "MODE=forward 需要配置官方上游 IP。当前 FORWARD_TARGET=$forward_target，缺少: ${missing[*]}"
fi

python3 - <<'PY'
from pathlib import Path

path = Path('.env')
text = path.read_text()
lines = text.splitlines()
seen = False
result: list[str] = []
for line in lines:
    if line.strip().startswith('MODE='):
        result.append('MODE=forward')
        seen = True
    else:
        result.append(line)
if not seen:
    result.append('MODE=forward')
path.write_text('\n'.join(result) + '\n')
PY

printf '\033[32m[INFO]\033[0m 已切换到官方直连转发模式。\n'
