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

backend_url="$(get_env_value BACKEND_API_URL || true)"
if [[ -z "$backend_url" ]]; then
  fail "MODE=hybrid 需要配置 BACKEND_API_URL。"
fi

missing=()
[[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing+=("KIRO_RUNTIME_IP")
[[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing+=("KIRO_MANAGEMENT_IP")
if [[ ${#missing[@]} -gt 0 ]]; then
  fail "MODE=hybrid 需要配置官方上游 IP，缺少: ${missing[*]}"
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
        result.append('MODE=hybrid')
        seen = True
    else:
        result.append(line)
if not seen:
    result.append('MODE=hybrid')
path.write_text('\n'.join(result) + '\n')
PY

printf '\033[32m[INFO]\033[0m 已切换到混合模式。\n'
