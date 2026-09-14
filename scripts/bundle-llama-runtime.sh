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
LLAMA_LIB_DIR="$FRAMEWORKS_DIR/llama"

echo "=== Bundling llama.cpp runtime into Ark Browser.app ==="
echo "Target build directory: $BUILD_DIR"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Error: Application bundle not found at $APP_BUNDLE"
  exit 1
fi

mkdir -p "$MACOS_DIR"
mkdir -p "$LLAMA_LIB_DIR/libexec"

if ! command -v brew >/dev/null 2>&1; then
  echo "Error: Homebrew is required to locate the llama.cpp runtime dependencies"
  exit 1
fi

LLAMA_PREFIX="$(brew --prefix llama.cpp)"
GGML_PREFIX="$(brew --prefix ggml)"
OPENSSL_PREFIX="$(brew --prefix openssl@3)"

if [[ ! -d "$LLAMA_PREFIX" ]]; then
  echo "Error: llama.cpp not found at $LLAMA_PREFIX"
  exit 1
fi

echo "1. Copying llama-cli binary..."
rm -f "$MACOS_DIR/llama-cli"
cp -f "$LLAMA_PREFIX/bin/llama-cli" "$MACOS_DIR/llama-cli"
chmod 755 "$MACOS_DIR/llama-cli"

echo "2. Copying llama and ggml libraries..."
rm -f "$LLAMA_LIB_DIR"/*.dylib(N) "$LLAMA_LIB_DIR/libexec"/*.so(N)
cp -fP "$LLAMA_PREFIX/lib"/*.dylib "$LLAMA_LIB_DIR/" 2>/dev/null || true
cp -fP "$GGML_PREFIX/lib"/*.dylib "$LLAMA_LIB_DIR/" 2>/dev/null || true
cp -fP "$OPENSSL_PREFIX/lib"/libssl*.dylib "$LLAMA_LIB_DIR/" 2>/dev/null || true
cp -fP "$OPENSSL_PREFIX/lib"/libcrypto*.dylib "$LLAMA_LIB_DIR/" 2>/dev/null || true

echo "3. Copying Metal and Apple Silicon CPU backends..."
cp -fP "$GGML_PREFIX/libexec"/*.so "$LLAMA_LIB_DIR/libexec/" 2>/dev/null || true

echo "4. Updating rpaths for self-contained execution..."
install_name_tool -add_rpath "@executable_path/../Frameworks/llama" "$MACOS_DIR/llama-cli" 2>/dev/null || true

# Change Homebrew linkage to the libraries copied into the app bundle.
for binary in "$MACOS_DIR/llama-cli"; do
  install_name_tool -change "$GGML_PREFIX/lib/libggml.0.dylib" "@rpath/libggml.0.dylib" "$binary" 2>/dev/null || true
  install_name_tool -change "$GGML_PREFIX/lib/libggml-base.0.dylib" "@rpath/libggml-base.0.dylib" "$binary" 2>/dev/null || true
  install_name_tool -change "$OPENSSL_PREFIX/lib/libssl.3.dylib" "@rpath/libssl.3.dylib" "$binary" 2>/dev/null || true
  install_name_tool -change "$OPENSSL_PREFIX/lib/libcrypto.3.dylib" "@rpath/libcrypto.3.dylib" "$binary" 2>/dev/null || true
done

echo "5. Ad-hoc signing bundled binaries..."
codesign --force --sign - "$MACOS_DIR/llama-cli"
for lib in "$LLAMA_LIB_DIR"/*.dylib; do
  codesign --force --sign - "$lib" 2>/dev/null || true
done
for so in "$LLAMA_LIB_DIR/libexec"/*.so; do
  codesign --force --sign - "$so" 2>/dev/null || true
done

echo "=== Bundled llama.cpp successfully into Ark Browser.app ==="
