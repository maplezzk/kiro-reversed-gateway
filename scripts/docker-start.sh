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
  - 如果后端跑在宿主机，脚本会自动把 127.0.0.1/localhost 替换为 host.docker.internal
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

get_env_value() {
  local key="$1"
  grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | cut -d '=' -f 2- | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'$/\1/"
}

rewrite_env_value() {
  local key="$1"
  local value="$2"
  python3 - "$key" "$value" <<'PY'
from pathlib import Path
import sys

key = sys.argv[1]
value = sys.argv[2]
path = Path('.env')
lines = path.read_text().splitlines()
result = []
replaced = False
prefix = f"{key}="
for line in lines:
    if line.strip().startswith(prefix):
        result.append(prefix + value)
        replaced = True
    else:
        result.append(line)
if not replaced:
    result.append(prefix + value)
path.write_text('\n'.join(result) + '\n')
PY
}

normalize_backend_api_url_for_docker() {
  python3 - "$1" <<'PY'
from urllib.parse import urlparse, urlunparse
import sys

value = sys.argv[1]
parsed = urlparse(value)
if parsed.scheme not in ("http", "https") or not parsed.netloc:
    print(value)
    raise SystemExit(0)

host = parsed.hostname or ""
if host not in ("127.0.0.1", "localhost"):
    print(value)
    raise SystemExit(0)

netloc = "host.docker.internal"
if parsed.port:
    netloc = f"{netloc}:{parsed.port}"
if parsed.username:
    auth = parsed.username
    if parsed.password:
        auth = f"{auth}:{parsed.password}"
    netloc = f"{auth}@{netloc}"

print(urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)))
PY
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

mode="$(get_env_value MODE || true)"
mode="${mode:-openai}"
forward_target="$(get_env_value FORWARD_TARGET || true)"
forward_target="${forward_target:-auto}"
backend_api_url="$(get_env_value BACKEND_API_URL || true)"

if [[ "$mode" != "openai" && "$mode" != "forward" && "$mode" != "hybrid" ]]; then
  fail "MODE 只能是 openai、forward 或 hybrid，当前值: $mode"
fi

if [[ "$mode" == "openai" || "$mode" == "hybrid" ]]; then
  if [[ -z "$backend_api_url" ]]; then
    fail "MODE=$mode 时必须配置 BACKEND_API_URL。Docker 模式下推荐: BACKEND_API_URL=http://host.docker.internal:<port>/v1"
  fi
  normalized_backend_api_url="$(normalize_backend_api_url_for_docker "$backend_api_url")"
  if [[ "$normalized_backend_api_url" != "$backend_api_url" ]]; then
    info "已自动将 BACKEND_API_URL 从本机地址替换为 Docker 宿主地址: $normalized_backend_api_url"
    rewrite_env_value "BACKEND_API_URL" "$normalized_backend_api_url"
    backend_api_url="$normalized_backend_api_url"
  fi
fi

if [[ "$mode" == "forward" || "$mode" == "hybrid" ]]; then
  missing_forward_ips=()
  if [[ "$mode" == "hybrid" ]]; then
    [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing_forward_ips+=("KIRO_RUNTIME_IP")
    [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing_forward_ips+=("KIRO_MANAGEMENT_IP")
  else
    case "$forward_target" in
      auto)
        [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing_forward_ips+=("KIRO_RUNTIME_IP")
        [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing_forward_ips+=("KIRO_MANAGEMENT_IP")
        ;;
      runtime)
        [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing_forward_ips+=("KIRO_RUNTIME_IP")
        ;;
      management)
        [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing_forward_ips+=("KIRO_MANAGEMENT_IP")
        ;;
      q)
        [[ -n "$(get_env_value KIRO_Q_IP || true)" ]] || missing_forward_ips+=("KIRO_Q_IP")
        ;;
      random)
        [[ -n "$(get_env_value KIRO_RUNTIME_IP || true)" ]] || missing_forward_ips+=("KIRO_RUNTIME_IP")
        [[ -n "$(get_env_value KIRO_MANAGEMENT_IP || true)" ]] || missing_forward_ips+=("KIRO_MANAGEMENT_IP")
        [[ -n "$(get_env_value KIRO_Q_IP || true)" ]] || missing_forward_ips+=("KIRO_Q_IP")
        ;;
      *)
        fail "FORWARD_TARGET 只能是 auto/runtime/management/q/random，当前值: $forward_target"
        ;;
    esac
  fi
  if [[ ${#missing_forward_ips[@]} -gt 0 ]]; then
    fail "MODE=$mode 必须配置对应官方上游 IP。当前 FORWARD_TARGET=$forward_target，缺少: ${missing_forward_ips[*]}"
  fi
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
