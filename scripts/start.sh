#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-443}"
HOST="${HOST:-}"
NO_TLS="${NO_TLS:-false}"
CONNECT_PROXY_HOST="${CONNECT_PROXY_HOST:-127.0.0.1}"
CONNECT_PROXY_PORT="${CONNECT_PROXY_PORT:-}"
CONNECT_PROXY_ENABLED="${CONNECT_PROXY_ENABLED:-true}"

show_help() {
  cat <<'EOF'
Usage: ./scripts/start.sh [options]

Options:
  --host HOST       监听地址，默认读取 .env 或 0.0.0.0
  --port PORT       监听端口，默认 443
  --no-tls          使用 HTTP 调试模式；不会生成或使用 TLS 证书
  --skip-install    跳过 pip install -r requirements.txt
  --no-connect-proxy 不启动 Clash CONNECT 代理
  -h, --help        显示帮助

TLS:
  默认 TLS 模式下，如果 certs/cert.pem 或 certs/key.pem 不存在，脚本会自动生成一次。
  已存在证书时不会重新生成。

Environment overrides:
  PYTHON_BIN=python3.12
  VENV_DIR=.venv
  PORT=443
  HOST=0.0.0.0
  NO_TLS=true
  CONNECT_PROXY_HOST=127.0.0.1
  CONNECT_PROXY_PORT=7898
  CONNECT_PROXY_ENABLED=true
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      [[ $# -ge 2 ]] || { echo "--host requires a value" >&2; exit 1; }
      HOST="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "--port requires a value" >&2; exit 1; }
      PORT="$2"
      shift 2
      ;;
    --no-tls)
      NO_TLS="true"
      shift
      ;;
    --skip-install)
      SKIP_INSTALL="true"
      shift
      ;;
    --no-connect-proxy)
      CONNECT_PROXY_ENABLED="false"
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
  grep -E "^[[:space:]]*${key}=" .env 2>/dev/null | tail -n 1 | cut -d '=' -f 2- | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'$/\1/"
}

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    warn ".env 不存在，已从 .env.example 复制一份。请编辑 .env 后重新运行。"
    cp .env.example .env
    exit 1
  fi
  fail ".env 不存在，且找不到 .env.example"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  info "创建虚拟环境: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if [[ "$SKIP_INSTALL" != "true" ]]; then
  info "安装/更新依赖"
  python -m pip install -r requirements.txt
else
  info "跳过依赖安装: SKIP_INSTALL=true"
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

if [[ "$NO_TLS" != "true" ]]; then
  if [[ ! -f "certs/cert.pem" || ! -f "certs/key.pem" ]]; then
    warn "未找到 TLS 证书，正在生成自签名证书。"
    mkdir -p certs
    openssl req -x509 -newkey rsa:4096 \
      -keyout certs/key.pem \
      -out certs/cert.pem \
      -days 365 -nodes \
      -subj "/CN=runtime.us-east-1.kiro.dev" \
      -addext "subjectAltName=DNS:runtime.us-east-1.kiro.dev,DNS:management.us-east-1.kiro.dev,DNS:*.kiro.dev"
  fi
  trust_certificate_if_possible
fi

if [[ -z "$CONNECT_PROXY_PORT" ]]; then
  CONNECT_PROXY_PORT="$(get_env_value CONNECT_PROXY_PORT || true)"
fi
CONNECT_PROXY_PORT="${CONNECT_PROXY_PORT:-7898}"

ARGS=("main.py" "--port" "$PORT")
if [[ -n "$HOST" ]]; then
  ARGS+=("--host" "$HOST")
fi
if [[ "$NO_TLS" == "true" ]]; then
  ARGS+=("--no-tls")
fi

CONNECT_PROXY_PID=""
cleanup_connect_proxy() {
  if [[ -n "$CONNECT_PROXY_PID" ]] && kill -0 "$CONNECT_PROXY_PID" 2>/dev/null; then
    info "停止 Clash CONNECT proxy"
    kill "$CONNECT_PROXY_PID" 2>/dev/null || true
    wait "$CONNECT_PROXY_PID" 2>/dev/null || true
  fi
}

if [[ "$CONNECT_PROXY_ENABLED" == "true" && "$NO_TLS" != "true" ]]; then
  info "启动 Clash CONNECT proxy"
  info "代理端口: $CONNECT_PROXY_HOST:$CONNECT_PROXY_PORT -> 127.0.0.1:$PORT"
  python connect_proxy.py \
    --listen-host "$CONNECT_PROXY_HOST" \
    --listen-port "$CONNECT_PROXY_PORT" \
    --target-host 127.0.0.1 \
    --target-port "$PORT" &
  CONNECT_PROXY_PID="$!"
  trap cleanup_connect_proxy EXIT INT TERM
  sleep 0.2
  if ! kill -0 "$CONNECT_PROXY_PID" 2>/dev/null; then
    wait "$CONNECT_PROXY_PID" 2>/dev/null || true
    fail "Clash CONNECT proxy 启动失败，请检查 CONNECT_PROXY_PORT=$CONNECT_PROXY_PORT 是否被占用。"
  fi
elif [[ "$NO_TLS" == "true" ]]; then
  warn "HTTP 调试模式下不启动 Clash CONNECT proxy。"
fi

info "启动 kiro-reversed-gateway"
info "端口: $PORT"
if [[ "$NO_TLS" == "true" ]]; then
  info "模式: HTTP 调试模式"
  python "${ARGS[@]}"
  exit $?
fi

if [[ "$PORT" -lt 1024 && "$(id -u)" -ne 0 ]]; then
  warn "端口 $PORT 需要 root 权限，切换 sudo 启动。"
  sudo -E "$VENV_DIR/bin/python" "${ARGS[@]}"
  exit $?
fi

python "${ARGS[@]}"
