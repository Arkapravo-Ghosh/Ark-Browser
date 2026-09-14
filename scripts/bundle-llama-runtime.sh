#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Bundle the legacy llama.cpp CLI runtime, libraries, and Metal backend inside Ark Browser.app.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/env.sh"

BUILD_DIR="${BUILD_DIR:-$CHROMIUM_SRC/out/ArkDev}"
APP_BUNDLE="$BUILD_DIR/Ark Browser.app"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir)
      [[ $# -ge 2 ]] || { echo "Error: --build-dir requires a directory name or path"; exit 1; }
      if [[ "$2" = /* ]]; then
        BUILD_DIR="$2"
      else
        BUILD_DIR="$CHROMIUM_SRC/out/$2"
      fi
      APP_BUNDLE="$BUILD_DIR/Ark Browser.app"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--build-dir ArkDev|ArkRelease|/absolute/build/path]"
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1"
      exit 1
      ;;
  esac
done

MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
FRAMEWORKS_DIR="$APP_BUNDLE/Contents/Frameworks"

echo "=== Bundling llama.cpp runtime into Ark Browser.app ==="
echo "Target build directory: $BUILD_DIR"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Error: Application bundle not found at $APP_BUNDLE"
  exit 1
fi

mkdir -p "$MACOS_DIR"

LOCAL_BUILD_DIR="${LLAMA_BUILD_DIR:-$ROOT_DIR/third_party/llama.cpp/build-ark}"
LOCAL_CLI="$LOCAL_BUILD_DIR/bin/llama-cli"
if [[ ! -x "$LOCAL_CLI" ]]; then
  echo "llama.cpp build not found; compiling the pinned submodule..."
  "$SCRIPT_DIR/build-llama-runtime.sh"
fi

echo "1. Copying llama-cli binary..."
rm -f "$MACOS_DIR/llama-cli"
cp -f "$LOCAL_CLI" "$MACOS_DIR/llama-cli"
chmod 755 "$MACOS_DIR/llama-cli"
echo "2. Using statically linked CPU and Metal backends from the local build."
echo "3. Ad-hoc signing bundled binary..."
codesign --force --sign - "$MACOS_DIR/llama-cli"

echo "=== Bundled llama.cpp successfully into Ark Browser.app ==="
