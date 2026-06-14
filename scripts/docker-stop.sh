#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOVE_VOLUMES="false"
show_help() {
  cat <<'EOF'
Usage: ./scripts/docker-stop.sh [options]

Options:
  --volumes      同时删除匿名卷
  -h, --help     显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volumes)
      REMOVE_VOLUMES="true"
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

info() {
  printf '\033[32m[INFO]\033[0m %s\n' "$*"
}

fail() {
  printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  fail "未找到 docker，请先安装 Docker Desktop"
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "当前 Docker 不支持 'docker compose'，请升级 Docker Desktop"
fi

info "停止 Docker 服务"
if [[ "$REMOVE_VOLUMES" == "true" ]]; then
  docker compose down -v
else
  docker compose down
fi

info "完成"
