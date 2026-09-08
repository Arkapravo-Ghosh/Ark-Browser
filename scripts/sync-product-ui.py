#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Publish the Ark-owned WebUI snapshot into the independently buildable fork."""
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ('BUILD.gn', 'ark.html', 'ark.css', 'ark.ts', 'ark.svg')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if the fork snapshot differs')
    args = parser.parse_args()
    source = ROOT / 'product/ui'
    destination = ROOT / 'chromium/src/chrome/browser/resources/ark'
    if not (ROOT / 'chromium/src/chrome/BUILD.gn').is_file():
        parser.error('initialize the Chromium fork before syncing')
    different = [name for name in FILES if not (destination / name).is_file()
                 or (source / name).read_bytes() != (destination / name).read_bytes()]
    if args.check:
        if different:
            print('Ark UI snapshot differs: ' + ', '.join(different), file=sys.stderr)
            return 1
        print('Ark UI snapshot matches product/ui.')
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    for name in different:
        shutil.copyfile(source / name, destination / name)
    print(f'Synced {len(different)} Ark UI files into the Chromium fork.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
