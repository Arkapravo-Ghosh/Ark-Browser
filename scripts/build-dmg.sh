#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Build a mountable macOS DMG installer for Ark Browser.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/env.sh"

BUILD_DIR="$CHROMIUM_SRC/out/ArkDev"
APP_BUNDLE="$BUILD_DIR/Ark Browser.app"
DIST_DIR="$ROOT_DIR/dist"
DMG_NAME="Ark-Browser.dmg"
DMG_PATH="$DIST_DIR/$DMG_NAME"
VOLUME_NAME="Ark Browser"

echo "=== Building Ark Browser Installer (DMG) ==="

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Error: Application bundle not found at:"
  echo "  $APP_BUNDLE"
  echo ""
  echo "Please build the browser first using:"
  echo "  source scripts/env.sh"
  echo "  autoninja -C chromium/src/out/ArkDev chrome"
  exit 1
fi

mkdir -p "$DIST_DIR"

STAGE_DIR="$(mktemp -d -t ark_dmg_stage_XXXXXX)"
cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

echo "1. Staging Ark Browser.app..."
ditto "$APP_BUNDLE" "$STAGE_DIR/Ark Browser.app"

if [[ -n $(ls "$BUILD_DIR"/*.dylib 2>/dev/null) ]]; then
  echo "1b. Bundling runtime libraries for component build..."
  FRAMEWORKS_DIR="$STAGE_DIR/Ark Browser.app/Contents/Frameworks"
  mkdir -p "$FRAMEWORKS_DIR"
  cp -c "$BUILD_DIR"/*.dylib "$FRAMEWORKS_DIR/" 2>/dev/null || cp "$BUILD_DIR"/*.dylib "$FRAMEWORKS_DIR/"
  echo "1c. Signing staged bundle with ad-hoc identity..."
  codesign --force --sign - --entitlements "$CHROMIUM_SRC/chrome/app/app-entitlements.plist" "$STAGE_DIR/Ark Browser.app"
fi

echo "2. Creating /Applications shortcut..."
ln -s /Applications "$STAGE_DIR/Applications"

ICON_SRC="$CHROMIUM_SRC/chrome/app/theme/chromium/mac/app.icns"
if [[ -f "$ICON_SRC" ]]; then
  echo "3. Applying volume icon..."
  cp "$ICON_SRC" "$STAGE_DIR/.VolumeIcon.icns"
  if command -v SetFile >/dev/null 2>&1; then
    SetFile -a C "$STAGE_DIR" || true
  fi
fi

echo "4. Generating compressed disk image ($DMG_NAME)..."
rm -f "$DMG_PATH"

HYBRID_DMG="$(mktemp -t ark_hybrid_XXXXXX).dmg"
cleanup() {
  rm -rf "$STAGE_DIR"
  rm -f "$HYBRID_DMG"
}

hdiutil makehybrid \
  -hfs \
  -hfs-volume-name "$VOLUME_NAME" \
  -ov "$STAGE_DIR" \
  -o "$HYBRID_DMG"

hdiutil convert \
  -format UDZO \
  -imagekey zlib-level=9 \
  -ov "$HYBRID_DMG" \
  -o "$DMG_PATH"

echo ""
echo "=== Installer Created Successfully ==="
echo "Installer location: $DMG_PATH"
echo "Size: $(du -sh "$DMG_PATH" | cut -f1)"
echo ""
echo "You can mount and test it with:"
echo "  open \"$DMG_PATH\""
