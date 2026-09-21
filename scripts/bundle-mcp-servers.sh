#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Bundle official MCP servers (@modelcontextprotocol/server-memory and
# @modelcontextprotocol/server-sequential-thinking) and relocatable Node.js runtime inside Ark Browser.app.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/env.sh"

BUILD_DIR="${BUILD_DIR:-$CHROMIUM_SRC/out/ArkDev}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir)
      [[ $# -ge 2 ]] || { echo "Error: --build-dir requires a path"; exit 1; }
      if [[ "$2" = /* ]]; then
        BUILD_DIR="$2"
      else
        BUILD_DIR="$CHROMIUM_SRC/out/$2"
      fi
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--build-dir ArkDev|ArkRelease|/absolute/path]"
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1"
      exit 1
      ;;
  esac
done

APP_BUNDLE="$BUILD_DIR/Ark Browser.app"
MCP_DIR="$APP_BUNDLE/Contents/Resources/mcp"
MCP_BIN_DIR="$MCP_DIR/bin"
MCP_RUNTIME_DIR="$MCP_DIR/runtime"

echo "=== Bundling official MCP runtime into Ark Browser.app ==="
echo "Target build directory: $BUILD_DIR"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Error: application bundle not found at $APP_BUNDLE"
  exit 1
fi

echo "1. Resolving Node.js binary from environment / NVM..."
NODE_SOURCE=""
if [[ -n "${ARK_NODE_PATH:-}" && -x "$ARK_NODE_PATH" ]]; then
  NODE_SOURCE="$ARK_NODE_PATH"
elif [[ -n "${NVM_BIN:-}" && -x "$NVM_BIN/node" ]]; then
  NODE_SOURCE="$NVM_BIN/node"
elif [[ -d "${NVM_DIR:-$HOME/.nvm}/versions/node" ]]; then
  # Pick highest installed version in nvm
  NODE_SOURCE="$(find "${NVM_DIR:-$HOME/.nvm}/versions/node" -maxdepth 3 -name node -type f -perm +111 2>/dev/null | sort -V | tail -n 1 || true)"
fi
if [[ -z "$NODE_SOURCE" || ! -x "$NODE_SOURCE" ]] && command -v node >/dev/null 2>&1; then
  NODE_SOURCE="$(command -v node)"
fi

if [[ -z "$NODE_SOURCE" || ! -x "$NODE_SOURCE" ]]; then
  echo "Error: could not locate a viable Node.js binary to bundle."
  exit 1
fi

echo "   Found Node: $NODE_SOURCE ($("$NODE_SOURCE" -v))"

echo "2. Staging third_party MCP dependencies..."
THIRD_PARTY_MCP="$ROOT_DIR/third_party/mcp"
if [[ ! -d "$THIRD_PARTY_MCP/node_modules/@modelcontextprotocol/server-memory" || \
      ! -d "$THIRD_PARTY_MCP/node_modules/@modelcontextprotocol/server-sequential-thinking" ]]; then
  echo "   Installing pinned MCP packages in third_party/mcp..."
  mkdir -p "$THIRD_PARTY_MCP"
  (cd "$THIRD_PARTY_MCP" && npm init -y >/dev/null 2>&1 && npm install --save \
    @modelcontextprotocol/server-memory \
    @modelcontextprotocol/server-sequential-thinking \
    @modelcontextprotocol/sdk)
fi

echo "3. Copying Node.js binary, runner, and MCP modules into app bundle..."
rm -rf "$MCP_DIR"
mkdir -p "$MCP_BIN_DIR" "$MCP_RUNTIME_DIR"

# Copy standalone node binary
cp -f "$NODE_SOURCE" "$MCP_BIN_DIR/node"
chmod 755 "$MCP_BIN_DIR/node"

# Create a private package.json marking the bundle as commonjs
cat << 'EOF' > "$MCP_DIR/package.json"
{
  "name": "ark-mcp-runtime",
  "version": "1.0.0",
  "type": "commonjs"
}
EOF

# Copy runner script
cp -f "$SCRIPT_DIR/ark_mcp_runner.cjs" "$MCP_DIR/ark_mcp_runner.cjs"
chmod 755 "$MCP_DIR/ark_mcp_runner.cjs"

# Copy runtime packages
cp -f "$THIRD_PARTY_MCP/package.json" "$MCP_RUNTIME_DIR/package.json"
ditto "$THIRD_PARTY_MCP/node_modules" "$MCP_RUNTIME_DIR/node_modules"

echo "4. Ad-hoc signing bundled Node binary..."
codesign --force --sign - "$MCP_BIN_DIR/node"

echo "5. Verifying bundled MCP runtime via self-test..."
TEST_OUTPUT="$("$MCP_BIN_DIR/node" "$MCP_DIR/ark_mcp_runner.cjs" test)"
echo "   Test output: $TEST_OUTPUT"

if [[ "$TEST_OUTPUT" != *"\"success\":true"* ]]; then
  echo "Error: bundled MCP self-test failed."
  exit 1
fi

echo "=== Bundled official MCP runtime successfully into Ark Browser.app ==="
