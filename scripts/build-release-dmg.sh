#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Build an optimized, production-ready macOS DMG installer for Ark Browser.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/env.sh"

BUILD_DIR="${BUILD_DIR:-$CHROMIUM_SRC/out/ArkRelease}"
export PATH="$CHROMIUM_SRC/buildtools/mac:$DEPOT_TOOLS:$PATH"
GN_BIN="$CHROMIUM_SRC/buildtools/mac/gn"
if [[ ! -x "$GN_BIN" ]]; then
  GN_BIN="gn"
fi
APP_NAME="Ark Browser"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
DIST_DIR="$ROOT_DIR/dist"
DMG_NAME="${DMG_NAME:-Ark-Browser-Release.dmg}"
DMG_PATH="$DIST_DIR/$DMG_NAME"
VOLUME_NAME="Ark Browser"
DO_BUILD=false
SETUP_ONLY=false

# Parse command line flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--build)
      DO_BUILD=true
      shift
      ;;
    -s|--setup-only)
      SETUP_ONLY=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [options]"
      echo ""
      echo "Options:"
      echo "  -b, --build       Compile the release binary before packaging DMG"
      echo "  -s, --setup-only  Initialize out/ArkRelease/args.gn and run gn gen only"
      echo "  -h, --help        Show this help message"
      echo ""
      echo "Environment variables:"
      echo "  BUILD_DIR         Build output directory (default: chromium/src/out/ArkRelease)"
      echo "  DMG_NAME          Output DMG filename (default: Ark-Browser-Release.dmg)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run '$0 --help' for usage."
      exit 1
      ;;
  esac
done

echo "=================================================="
echo "   Ark Browser — Production DMG Release Builder   "
echo "=================================================="
echo "Target Build Directory: $BUILD_DIR"
echo "Output DMG Path:        $DMG_PATH"
echo ""

# Ensure release configuration exists in BUILD_DIR
if [[ ! -f "$BUILD_DIR/args.gn" ]]; then
  echo "1. Initializing release build configuration in $BUILD_DIR/args.gn..."
  mkdir -p "$BUILD_DIR"
  cat << 'EOF' > "$BUILD_DIR/args.gn"
is_debug = false
is_component_build = false
symbol_level = 0
dcheck_always_on = false
generate_about_credits = true
EOF
  echo "   Running $GN_BIN gen --root=\"$CHROMIUM_SRC\" $BUILD_DIR..."
  "$GN_BIN" gen --root="$CHROMIUM_SRC" "$BUILD_DIR"
elif [[ ! -f "$BUILD_DIR/build.ninja" ]]; then
  echo "1. Generating ninja build files in $BUILD_DIR..."
  "$GN_BIN" gen --root="$CHROMIUM_SRC" "$BUILD_DIR"
fi

if [[ "$SETUP_ONLY" == true ]]; then
  echo ""
  echo "Setup completed for $BUILD_DIR."
  echo "You can now build using: autoninja -C \"$BUILD_DIR\" chrome"
  exit 0
fi

# Optional build step
if [[ "$DO_BUILD" == true ]]; then
  echo ""
  echo "2. Compiling production target (chrome) in $BUILD_DIR..."
  autoninja -C "$BUILD_DIR" chrome
fi

# Validate application bundle
if [[ ! -d "$APP_BUNDLE" ]]; then
  echo ""
  echo "Error: Application bundle not found at:"
  echo "  $APP_BUNDLE"
  echo ""
  echo "Please compile the release build first using:"
  echo "  source scripts/env.sh"
  echo "  autoninja -C \"$BUILD_DIR\" chrome"
  echo ""
  echo "Or re-run this script with the --build flag:"
  echo "  $0 --build"
  exit 1
fi

# Verify this is a non-component release build
if [[ -n $(ls "$BUILD_DIR"/*.dylib 2>/dev/null) ]]; then
  echo "Warning: Loose .dylib files detected in $BUILD_DIR."
  echo "Make sure is_component_build = false in $BUILD_DIR/args.gn for a true monolithic release build."
fi

mkdir -p "$DIST_DIR"

STAGE_DIR="$(mktemp -d -t ark_release_stage_XXXXXX)"
HYBRID_DMG="$(mktemp -t ark_release_hybrid_XXXXXX).dmg"

cleanup() {
  rm -rf "$STAGE_DIR"
  rm -f "$HYBRID_DMG"
}
trap cleanup EXIT

echo ""
echo "3. Staging $APP_NAME.app..."
ditto "$APP_BUNDLE" "$STAGE_DIR/$APP_NAME.app"

# In a monolithic release build, Ark Browser Framework contains all compiled code.
# Strip local / debug symbols from the staged bundle to ensure minimal footprint.
echo "4. Stripping local symbols from staged binaries..."
MAIN_BIN="$STAGE_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME"
if [[ -f "$MAIN_BIN" ]]; then
  strip -x "$MAIN_BIN" 2>/dev/null || true
fi

FRAMEWORK_DIR="$STAGE_DIR/$APP_NAME.app/Contents/Frameworks"
if [[ -d "$FRAMEWORK_DIR" ]]; then
  find "$FRAMEWORK_DIR" -type f -perm +111 -exec strip -x {} + 2>/dev/null || true
fi

echo "5. Ad-hoc codesigning staged bundle..."
ENTITLEMENTS="$CHROMIUM_SRC/chrome/app/app-entitlements.plist"
if [[ -f "$ENTITLEMENTS" ]]; then
  codesign --force --deep --sign - --entitlements "$ENTITLEMENTS" "$STAGE_DIR/$APP_NAME.app"
else
  codesign --force --deep --sign - "$STAGE_DIR/$APP_NAME.app"
fi

echo "6. Creating /Applications shortcut..."
ln -s /Applications "$STAGE_DIR/Applications"

ICON_SRC="$CHROMIUM_SRC/chrome/app/theme/chromium/mac/app.icns"
if [[ -f "$ICON_SRC" ]]; then
  echo "7. Applying volume icon..."
  cp "$ICON_SRC" "$STAGE_DIR/.VolumeIcon.icns"
  if command -v SetFile >/dev/null 2>&1; then
    SetFile -a C "$STAGE_DIR" || true
  fi
fi

echo "8. Generating compressed disk image ($DMG_NAME)..."
rm -f "$DMG_PATH"

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
echo "=================================================="
echo "       Release DMG Created Successfully!          "
echo "=================================================="
echo "DMG File:     $DMG_PATH"
echo "DMG Size:     $(du -sh "$DMG_PATH" | cut -f1)"
echo "App Size:     $(du -sh "$STAGE_DIR/$APP_NAME.app" | cut -f1)"
echo ""
echo "Mount and test with:"
echo "  open \"$DMG_PATH\""
