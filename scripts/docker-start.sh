#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD="true"
FOLLOW_LOGS="false"

show_help() {
  cat <<'EOF'
Usage: ./scripts/docker-start.sh [options]

Options:
  --no-build       不重新构建镜像，直接启动
  --logs           启动后跟随日志
  -h, --help       显示帮助

Notes:
  - 如果后端跑在宿主机，.env 里 BACKEND_API_URL 应使用 http://host.docker.internal:<port>/v1
  - /etc/hosts 仍然在宿主机配置
  - 如果 certs/cert.pem 或 certs/key.pem 不存在，脚本会自动生成一次；已存在时不会重新生成
  - macOS 上脚本会按证书指纹自动信任；证书没变不会重复执行
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      BUILD="false"
      shift
      ;;
    --logs)
      FOLLOW_LOGS="true"
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

warn() {
  printf '\033[33m[WARN]\033[0m %s\n' "$*"
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

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    warn ".env 不存在，已从 .env.example 复制一份。请编辑 .env 后重新运行。"
    cp .env.example .env
    exit 1
  fi
  fail ".env 不存在，且找不到 .env.example"
fi

mkdir -p certs

get_env_value() {
  local key="$1"
  grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | cut -d '=' -f 2- | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'$/\1/"
}

backend_api_url="$(get_env_value BACKEND_API_URL || true)"
if [[ -z "$backend_api_url" ]]; then
  fail "BACKEND_API_URL 未配置。Docker 模式下推荐: BACKEND_API_URL=http://host.docker.internal:<port>/v1"
fi

if [[ "$backend_api_url" == http://127.0.0.1:* || "$backend_api_url" == https://127.0.0.1:* || "$backend_api_url" == http://localhost:* || "$backend_api_url" == https://localhost:* ]]; then
  fail "Docker 容器内不能用 127.0.0.1/localhost 访问宿主机后端，请改为: BACKEND_API_URL=http://host.docker.internal:<port>/v1"
fi

trust_certificate_if_possible() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi
  if ! command -v security >/dev/null 2>&1; then
    return 0
  fi
  local fingerprint_file="certs/.trusted-fingerprint"
  local fingerprint
  fingerprint="$(openssl x509 -in certs/cert.pem -noout -fingerprint -sha256 | cut -d '=' -f 2)"
  if [[ -f "$fingerprint_file" && "$(cat "$fingerprint_file")" == "$fingerprint" ]]; then
    return 0
  fi
  info "信任 macOS TLS 证书"
  sudo security add-trusted-cert -d -r trustRoot \
    -k /Library/Keychains/System.keychain certs/cert.pem
  printf '%s' "$fingerprint" > "$fingerprint_file"
}

if [[ ! -f "certs/cert.pem" || ! -f "certs/key.pem" ]]; then
  warn "未找到 TLS 证书，正在生成自签名证书。"
  openssl req -x509 -newkey rsa:4096 \
    -keyout certs/key.pem \
    -out certs/cert.pem \
    -days 365 -nodes \
    -subj "/CN=runtime.us-east-1.kiro.dev" \
    -addext "subjectAltName=DNS:runtime.us-east-1.kiro.dev,DNS:management.us-east-1.kiro.dev,DNS:*.kiro.dev"
fi
trust_certificate_if_possible

if [[ "$BUILD" == "true" ]]; then
  info "构建并启动 Docker 服务"
  docker compose up -d --build
else
  info "启动 Docker 服务"
  docker compose up -d
fi

info "服务状态"
docker compose ps

if [[ "$FOLLOW_LOGS" == "true" ]]; then
  info "跟随日志，按 Ctrl+C 退出日志查看"
  docker compose logs -f
else
  info "查看日志: ./scripts/docker-start.sh --logs 或 docker compose logs -f"
fi
