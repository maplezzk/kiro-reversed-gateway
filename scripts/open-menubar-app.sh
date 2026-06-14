#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_DIR="tools/macos-menubar/build/Kiro Gateway Menu.app"
EXECUTABLE_PATH="$APP_DIR/Contents/MacOS/KiroGatewayMenu"

if [[ ! -x "$EXECUTABLE_PATH" ]]; then
  ./scripts/build-menubar-app.sh
fi

# 确保打开的是最新构建，避免旧实例还挂在菜单栏/后台。
pkill -f "/Kiro Gateway Menu.app/Contents/MacOS/KiroGatewayMenu" 2>/dev/null || true
sleep 0.3
open "$APP_DIR"
sleep 1

if pgrep -f "/Kiro Gateway Menu.app/Contents/MacOS/KiroGatewayMenu" >/dev/null 2>&1; then
  echo "菜单栏工具已启动。请在 macOS 右上角查找 Kiro Gateway 图标。"
else
  echo "菜单栏工具启动失败。" >&2
  exit 1
fi
