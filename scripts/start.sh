#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-443}"
HOST="${HOST:-}"
NO_TLS="${NO_TLS:-false}"
SKIP_INSTALL="${SKIP_INSTALL:-false}"

show_help() {
  cat <<'EOF'
Usage: ./scripts/start.sh [options]

Options:
  --host HOST       监听地址，默认读取 .env 或 0.0.0.0
  --port PORT       监听端口，默认 443
  --no-tls          使用 HTTP 调试模式
  --skip-install    跳过 pip install -r requirements.txt
  -h, --help        显示帮助

Environment overrides:
  PYTHON_BIN=python3.12
  VENV_DIR=.venv
  PORT=443
  HOST=0.0.0.0
  NO_TLS=true
  SKIP_INSTALL=true
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

    warn "证书已生成。macOS 需要信任证书后 Kiro 才能正常连接："
    warn "sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/cert.pem"
  fi
fi

ARGS=("main.py" "--port" "$PORT")
if [[ -n "$HOST" ]]; then
  ARGS+=("--host" "$HOST")
fi
if [[ "$NO_TLS" == "true" ]]; then
  ARGS+=("--no-tls")
fi

info "启动 kiro-reversed-gateway"
info "端口: $PORT"
if [[ "$NO_TLS" == "true" ]]; then
  info "模式: HTTP 调试模式"
  exec python "${ARGS[@]}"
fi

if [[ "$PORT" -lt 1024 && "$(id -u)" -ne 0 ]]; then
  warn "端口 $PORT 需要 root 权限，切换 sudo 启动。"
  exec sudo -E "$VENV_DIR/bin/python" "${ARGS[@]}"
fi

exec python "${ARGS[@]}"
