#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Automate building, hashing, updating release/version.json, and publishing Ark Browser releases."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION_JSON_PATH = ROOT / 'release/version.json'
DEFAULT_DMG = ROOT / 'dist/Ark-Browser-Release.dmg'
DEFAULT_ZIP = ROOT / 'dist/Ark-Browser-mac-arm64.zip'
REPO_SLUG = 'Arkapravo-Ghosh/Ark-Browser'


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hex digest of a file in chunks."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if VERSION_JSON_PATH.exists():
        try:
            return json.loads(VERSION_JSON_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "name": "Ark Browser",
        "version": "",
        "release_tag": "",
        "release_date": "",
        "release_notes_url": "",
        "platforms": {
            "mac_arm64": {"url": "", "sha256": "", "size": 0},
            "mac_x64": {"url": "", "sha256": "", "size": 0},
            "win_x64": {"url": "", "sha256": "", "size": 0},
            "win_arm64": {"url": "", "sha256": "", "size": 0}
        }
    }


def save_manifest(data: dict) -> None:
    VERSION_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERSION_JSON_PATH.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--version', required=True,
                        help='Release version tag (e.g. 155.0.8049.0-alpha.0.0.1)')
    parser.add_argument('-b', '--build', action='store_true',
                        help='Run ./scripts/build-release-dmg.sh --build before publishing')
    parser.add_argument('--dmg', type=Path, default=DEFAULT_DMG,
                        help=f'Path to the release DMG (default: {DEFAULT_DMG})')
    parser.add_argument('-n', '--notes', type=str, default='',
                        help='Release notes text or path to release notes markdown file')
    parser.add_argument('--title', type=str, default='',
                        help='Release title (defaults to "Ark Browser <version>")')
    parser.add_argument('--no-upload', action='store_true',
                        help='Skip uploading to GitHub; only build and update release/version.json')
    parser.add_argument('--draft', action='store_true',
                        help='Create the GitHub release as a draft')
    parser.add_argument('--prerelease', action='store_true', default=True,
                        help='Mark release as pre-release (default: True)')
    args = parser.parse_args()

    version_tag = args.version.strip()
    release_title = args.title.strip() or f"Ark Browser {version_tag}"

    print("==================================================")
    print(f"   Publishing Ark Browser Release: {version_tag}")
    print("==================================================")

    # 1. Optionally compile & package the DMG
    if args.build:
        print("\n1. Building production DMG via scripts/build-release-dmg.sh...")
        build_script = ROOT / 'scripts/build-release-dmg.sh'
        subprocess.run(['/bin/zsh', str(build_script), '--build'], cwd=ROOT, check=True)

    dmg_path = args.dmg.resolve()
    if not dmg_path.exists():
        print(f"\nError: Release DMG not found at {dmg_path}", file=sys.stderr)
        print("Run with --build or compile first using ./scripts/build-release-dmg.sh --build", file=sys.stderr)
        sys.exit(1)

    # 2. Analyze artifacts
    print(f"\n2. Analyzing artifacts...")
    zip_path = DEFAULT_ZIP.resolve()
    if not zip_path.exists():
        app_bundle = ROOT / 'chromium/src/out/ArkRelease/Ark Browser.app'
        if app_bundle.exists():
            print("   Packaging Ark-Browser-mac-arm64.zip via ditto...")
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(app_bundle), str(zip_path)], check=True)

    dmg_file_size = os.path.getsize(dmg_path)
    dmg_sha256 = compute_sha256(dmg_path)
    print(f"   DMG:  {dmg_path.name} ({dmg_file_size:,} bytes, {dmg_file_size / (1024 * 1024):.1f} MB)")
    print(f"         SHA256: {dmg_sha256}")

    target_zip_name = 'Ark-Browser-mac-arm64.zip'
    has_zip = zip_path.exists()
    if has_zip:
        zip_file_size = os.path.getsize(zip_path)
        zip_sha256 = compute_sha256(zip_path)
        print(f"   ZIP:  {zip_path.name} ({zip_file_size:,} bytes, {zip_file_size / (1024 * 1024):.1f} MB)")
        print(f"         SHA256: {zip_sha256}")

    # 3. Update release/version.json
    print("\n3. Updating release/version.json...")
    manifest = load_manifest()
    manifest['name'] = 'Ark Browser'
    manifest['version'] = version_tag
    manifest['release_tag'] = version_tag
    manifest['channel'] = 'stable'
    manifest['release_date'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest['prerelease'] = bool(args.prerelease)
    manifest['release_notes_url'] = f"https://github.com/{REPO_SLUG}/releases/tag/{version_tag}"

    target_dmg_name = 'Ark-Browser-PreRelease.dmg' if args.prerelease else 'Ark-Browser-Release.dmg'

    if 'platforms' not in manifest:
        manifest['platforms'] = {}

    # Target mac_arm64: prioritize ZIP for smooth in-browser extraction
    if has_zip:
        manifest['platforms']['mac_arm64'] = {
            'url': f"https://github.com/{REPO_SLUG}/releases/download/{version_tag}/{target_zip_name}",
            'sha256': zip_sha256,
            'size': zip_file_size
        }
    else:
        manifest['platforms']['mac_arm64'] = {
            'url': f"https://github.com/{REPO_SLUG}/releases/download/{version_tag}/{target_dmg_name}",
            'sha256': dmg_sha256,
            'size': dmg_file_size
        }

    # Ensure Windows entries exist gracefully
    if 'win_x64' not in manifest['platforms']:
        manifest['platforms']['win_x64'] = {'url': '', 'sha256': '', 'size': 0}
    if 'win_arm64' not in manifest['platforms']:
        manifest['platforms']['win_arm64'] = {'url': '', 'sha256': '', 'size': 0}

    save_manifest(manifest)
    print(f"   Successfully updated {VERSION_JSON_PATH}")

    # 4. Handle release notes
    notes_text = args.notes
    if notes_text and Path(notes_text).is_file():
        notes_text = Path(notes_text).read_text(encoding='utf-8')
    elif not notes_text:
        notes_text = f"## Ark Browser {version_tag}\n\nAutomated release build."

    # 5. Upload to GitHub Releases
    if args.no_upload:
        print("\nSkipping GitHub upload (--no-upload specified).")
        print("Updated release/version.json is ready to commit.")
        return

    gh_bin = shutil.which('gh')
    if not gh_bin:
        print("\nNote: GitHub CLI ('gh') is not installed or not in PATH.")
        print(f"You can manually create the release at:")
        print(f"  https://github.com/{REPO_SLUG}/releases/new?tag={version_tag}")
        print(f"Upload assets:")
        print(f"  - {target_dmg_name}")
        if has_zip:
            print(f"  - {target_zip_name}")
        print(f"  - {VERSION_JSON_PATH}")
        return

    print(f"\n4. Uploading release to GitHub via gh CLI ({REPO_SLUG})...")
    # Prepare asset file with clean target filename
    upload_dmg_path = dmg_path.parent / target_dmg_name
    if upload_dmg_path.resolve() != dmg_path.resolve():
        shutil.copyfile(dmg_path, upload_dmg_path)

    upload_files = [str(upload_dmg_path)]
    if has_zip:
        upload_files.append(str(zip_path))
    upload_files.append(str(VERSION_JSON_PATH))

    cmd = [
        gh_bin, 'release', 'create', version_tag,
        *upload_files,
        '--title', release_title,
        '--notes', notes_text,
    ]
    if args.draft:
        cmd.append('--draft')
    if args.prerelease:
        cmd.append('--prerelease')

    try:
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"   Release created successfully!\n   {res.stdout.strip()}")
        else:
            if "already exists" in res.stderr:
                print(f"   Release tag {version_tag} already exists. Uploading assets to existing release...")
                upload_cmd = [gh_bin, 'release', 'upload', version_tag, *upload_files, '--clobber']
                subprocess.run(upload_cmd, cwd=ROOT, check=True)
                print(f"   Uploaded assets to {version_tag} successfully!")
            else:
                print(f"   gh release create output:\n{res.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"   Error running gh CLI: {e}", file=sys.stderr)

    print("\nRelease publish sequence finished!")


if __name__ == '__main__':
    main()
