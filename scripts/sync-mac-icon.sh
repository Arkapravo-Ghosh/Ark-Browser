#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Install the Icon Composer package used by the macOS application icon.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
SOURCE_DIR="$ROOT_DIR/ark.icon"
DEST_DIR="$ROOT_DIR/chromium/src/chrome/app/theme/chromium/mac/AppIcon.icon"
MAC_THEME_DIR="$ROOT_DIR/chromium/src/chrome/app/theme/chromium/mac"
ASSET_CATALOG_DIR="$MAC_THEME_DIR/Assets.xcassets/AppIcon.appiconset"
VECTOR_SOURCE="$SOURCE_DIR/Assets/vector.svg"

[[ "$(uname -s)" == "Darwin" ]] || {
  echo "Error: the Icon Composer app icon is macOS-only." >&2
  exit 1
}
[[ -f "$SOURCE_DIR/icon.json" ]] || {
  echo "Error: missing Icon Composer manifest: $SOURCE_DIR/icon.json" >&2
  exit 1
}
[[ -d "$SOURCE_DIR/Assets" ]] || {
  echo "Error: missing Icon Composer assets directory: $SOURCE_DIR/Assets" >&2
  exit 1
}
[[ -f "$VECTOR_SOURCE" ]] || {
  echo "Error: missing legacy icon artwork: $VECTOR_SOURCE" >&2
  exit 1
}
command -v rsvg-convert >/dev/null || {
  echo "Error: rsvg-convert is required (install librsvg with Homebrew)." >&2
  exit 1
}
command -v iconutil >/dev/null || {
  echo "Error: iconutil is required (install Xcode command line tools)." >&2
  exit 1
}

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
LEGACY_SVG="$TEMP_DIR/ark-app-icon.svg"
ICONSET_DIR="$TEMP_DIR/Ark.iconset"
mkdir -p "$ICONSET_DIR"

# Chromium still consumes app.icns and Assets.car. Render those legacy formats
# from the same foreground artwork used by the Icon Composer package.
python3 - "$VECTOR_SOURCE" "$LEGACY_SVG" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
match = re.search(r"<svg\b[^>]*>(.*?)</svg>", source, re.DOTALL)
if not match:
    raise SystemExit(f"Unable to read SVG artwork from {sys.argv[1]}")
inner = match.group(1).strip()
Path(sys.argv[2]).write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <rect x="72" y="72" width="880" height="880" rx="218" fill="#20251f"/>
  <g transform="translate(256 256)">
{inner}
  </g>
</svg>
''')
PY

render_png() {
  local size="$1"
  local output="$2"
  rsvg-convert -w "$size" -h "$size" "$LEGACY_SVG" -o "$output"
}

for spec in \
  "16:icon_16x16.png" \
  "32:icon_16x16@2x.png" \
  "32:icon_32x32.png" \
  "64:icon_32x32@2x.png" \
  "128:icon_128x128.png" \
  "256:icon_128x128@2x.png" \
  "256:icon_256x256.png" \
  "512:icon_256x256@2x.png" \
  "512:icon_512x512.png" \
  "1024:icon_512x512@2x.png"; do
  size="${spec%%:*}"
  filename="${spec#*:}"
  render_png "$size" "$ICONSET_DIR/$filename"
done

for spec in "16:appicon_16.png" "32:appicon_32.png" "64:appicon_64.png" \
            "128:appicon_128.png" "256:appicon_256.png" "512:appicon_512.png" \
            "1024:appicon_1024.png"; do
  size="${spec%%:*}"
  filename="${spec#*:}"
  render_png "$size" "$ASSET_CATALOG_DIR/$filename"
done

iconutil --convert icns --output "$MAC_THEME_DIR/app.icns" "$ICONSET_DIR"
python3 "$ROOT_DIR/chromium/src/tools/mac/icons/compile_car.py" -v \
  "$MAC_THEME_DIR/Assets.xcassets"

rm -rf "$DEST_DIR"
mkdir -p "${DEST_DIR:h}"
ditto "$SOURCE_DIR" "$DEST_DIR"

echo "Installed macOS Icon Composer package: $DEST_DIR"
echo "Regenerated macOS legacy icon assets: $MAC_THEME_DIR/app.icns and Assets.car"
