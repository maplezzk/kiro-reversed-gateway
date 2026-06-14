#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_NAME="Kiro Gateway Menu"
BUILD_DIR="tools/macos-menubar/build"
APP_DIR="$BUILD_DIR/${APP_NAME}.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
EXECUTABLE="KiroGatewayMenu"
SOURCE="tools/macos-menubar/Sources/KiroGatewayMenu.swift"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "这个菜单栏工具只能在 macOS 上构建。" >&2
  exit 1
fi

if ! command -v swiftc >/dev/null 2>&1; then
  echo "找不到 swiftc。请先安装 Xcode 或 Command Line Tools。" >&2
  exit 1
fi

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

swiftc "$SOURCE" \
  -parse-as-library \
  -O \
  -framework AppKit \
  -o "$MACOS_DIR/$EXECUTABLE"

cat > "$CONTENTS_DIR/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$EXECUTABLE</string>
  <key>CFBundleIdentifier</key>
  <string>dev.kiro-reversed.gateway-menu</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
EOF

chmod +x "$MACOS_DIR/$EXECUTABLE"

echo "已构建: $APP_DIR"
echo "启动: open '$APP_DIR'"
