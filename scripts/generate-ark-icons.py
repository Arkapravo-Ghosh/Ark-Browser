#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Generate all application icon assets and brand logos from product/ui/ark.svg."""

import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'chromium/src'
SVG_SOURCE = ROOT / 'product/ui/ark.svg'

MAC_APPICON_SVG_CONTENT = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="16" stdDeviation="16" flood-color="#000000" flood-opacity="0.35"/>
    </filter>
  </defs>
  <rect x="100" y="100" width="824" height="824" rx="185" fill="#292f29" filter="url(#shadow)"/>
  <g transform="translate(100, 100) scale(12.875)">
    <path d="M15 46 29 17h7l14 29h-9l-3-7H27l3-7h5l-3-8-10 22Z" fill="#f4f3eb"/>
    <circle cx="48" cy="17" r="4" fill="#d7e59a"/>
  </g>
</svg>'''

MAC_ICON_COMPOSER_FG = '''<svg width="1024" height="1024" viewBox="0 0 1024 1024" fill="none" xmlns="http://www.w3.org/2000/svg">
  <g transform="scale(16)">
    <path d="M15 46 29 17h7l14 29h-9l-3-7H27l3-7h5l-3-8-10 22Z" fill="#f4f3eb"/>
    <circle cx="48" cy="17" r="4" fill="#d7e59a"/>
  </g>
</svg>'''

def render_png(svg_path: Path, output_path: Path, width: int, height: int):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'rsvg-convert',
        '-w', str(width),
        '-h', str(height),
        str(svg_path),
        '-o', str(output_path)
    ], check=True)

def main():
    print(f"Generating icon assets from {SVG_SOURCE}...")

    temp_dir = ROOT / 'product/test-results'
    temp_dir.mkdir(parents=True, exist_ok=True)
    mac_appicon_svg = temp_dir / 'ark_mac_appicon.svg'
    mac_appicon_svg.write_text(MAC_APPICON_SVG_CONTENT)

    # 1. Generate temp iconset for iconutil to build app.icns using standard macOS HIG squircle
    temp_iconset = temp_dir / 'ark.iconset'
    if temp_iconset.exists():
        shutil.rmtree(temp_iconset)
    temp_iconset.mkdir(parents=True, exist_ok=True)

    iconset_specs = [
        ('icon_16x16.png', 16),
        ('icon_16x16@2x.png', 32),
        ('icon_32x32.png', 32),
        ('icon_32x32@2x.png', 64),
        ('icon_128x128.png', 128),
        ('icon_128x128@2x.png', 256),
        ('icon_256x256.png', 256),
        ('icon_256x256@2x.png', 512),
        ('icon_512x512.png', 512),
        ('icon_512x512@2x.png', 1024),
    ]

    for name, size in iconset_specs:
        render_png(mac_appicon_svg, temp_iconset / name, size, size)

    # 2. Update Assets.xcassets/AppIcon.appiconset with correctly sized macOS squircle icons
    mac_theme_dir = SRC / 'chrome/app/theme/chromium/mac'
    appiconset_dir = mac_theme_dir / 'Assets.xcassets/AppIcon.appiconset'
    appicon_sizes = [16, 32, 64, 128, 256, 512, 1024]
    for s in appicon_sizes:
        target = appiconset_dir / f'appicon_{s}.png'
        render_png(mac_appicon_svg, target, s, s)
    print(f"Updated AppIcon.appiconset with sizes: {appicon_sizes}")

    # 3. Update Assets.xcassets/Icon.iconset
    icon_iconset_dir = mac_theme_dir / 'Assets.xcassets/Icon.iconset'
    render_png(mac_appicon_svg, icon_iconset_dir / 'icon_256x256.png', 256, 256)
    render_png(mac_appicon_svg, icon_iconset_dir / 'icon_256x256@2x.png', 512, 512)
    print("Updated Icon.iconset with 256 and 512 PNGs")

    # 4. Update AppIcon.icon package for modern macOS 26+ layered Icon Composer
    appicon_pkg = mac_theme_dir / 'AppIcon.icon'
    appicon_assets = appicon_pkg / 'Assets'
    if appicon_pkg.exists():
        shutil.rmtree(appicon_pkg)
    appicon_assets.mkdir(parents=True, exist_ok=True)
    (appicon_assets / 'ark_fg.svg').write_text(MAC_ICON_COMPOSER_FG)

    icon_json = {
        "fill": {
            "solid": "srgb:0.16078,0.18431,0.16078,1.00000"
        },
        "groups": [
            {
                "layers": [
                    {
                        "glass": False,
                        "hidden": False,
                        "image-name": "ark_fg.svg",
                        "name": "ark_fg"
                    }
                ]
            }
        ]
    }
    (appicon_pkg / 'icon.json').write_text(json.dumps(icon_json, indent=2) + '\n')
    print("Configured AppIcon.icon with ark_fg.svg and sRGB #292f29 background")

    # 5. Run compile_car.py to compile Assets.car
    subprocess.run([
        'python3',
        str(SRC / 'tools/mac/icons/compile_car.py'),
        '-v',
        str(mac_theme_dir / 'Assets.xcassets')
    ], cwd=SRC, check=True)
    print(f"Compiled Assets.car ({ (mac_theme_dir / 'Assets.car').stat().st_size } bytes)")

    # 6. Compile multi-resolution app.icns with iconutil (overriding actool's partial icns)
    app_icns_path = mac_theme_dir / 'app.icns'
    subprocess.run(['iconutil', '-c', 'icns', str(temp_iconset), '-o', str(app_icns_path)], check=True)
    print(f"Generated multi-res {app_icns_path} ({app_icns_path.stat().st_size} bytes)")

    # 7. Update product_logo in default_100_percent and default_200_percent
    theme_100 = SRC / 'chrome/app/theme/default_100_percent/chromium'
    theme_200 = SRC / 'chrome/app/theme/default_200_percent/chromium'
    render_png(SVG_SOURCE, theme_100 / 'product_logo_16.png', 16, 16)
    render_png(SVG_SOURCE, theme_100 / 'product_logo_32.png', 32, 32)
    render_png(SVG_SOURCE, theme_200 / 'product_logo_16.png', 32, 32)
    render_png(SVG_SOURCE, theme_200 / 'product_logo_32.png', 64, 64)

    # 8. Update product_logo in chrome/app/theme/chromium
    theme_cr = SRC / 'chrome/app/theme/chromium'
    for s in [16, 24, 48, 64, 128, 256]:
        render_png(SVG_SOURCE, theme_cr / f'product_logo_{s}.png', s, s)
    shutil.copy(SVG_SOURCE, theme_cr / 'product_logo.svg')

    # 9. Update ui/webui/resources/images/chrome_logo_dark.svg
    webui_logo = SRC / 'ui/webui/resources/images/chrome_logo_dark.svg'
    shutil.copy(SVG_SOURCE, webui_logo)
    print("Updated Chromium product logos and WebUI logo to Ark SVG")

    # Clean up temp iconset
    shutil.rmtree(temp_iconset, ignore_errors=True)
    print("Icon generation complete!")

if __name__ == '__main__':
    main()
