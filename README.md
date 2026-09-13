# Ark Browser

Ark Browser is an AI-powered desktop browser built on Chromium. It is designed to combine fast, everyday browsing with an integrated AI assistant while keeping users in complete control of their data and where models run.

[![Latest Release](https://img.shields.io/github/v/release/Arkapravo-Ghosh/Ark-Browser?style=flat-square&color=blue)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-macOS%20(Apple%20Silicon)-brightgreen.svg)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)

---

## Download & Installation

### Latest macOS Release (Apple Silicon / arm64)

[![Download for macOS](https://img.shields.io/badge/Download-macOS%20(Apple%20Silicon%20DMG)-2ea44f?logo=apple&style=for-the-badge)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-PreRelease.dmg)

- 💿 **[Download Latest DMG (.dmg)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-PreRelease.dmg)** — Recommended installer disk image.
- 📦 **[Download Application Archive (.zip)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-mac-arm64.zip)** — Portable application bundle archive.
- 📋 **[All Releases & Changelog](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)** — Release notes and checksums.

---

### macOS First-Launch & Security Instructions

When you download Ark Browser using a web browser and drag it to `/Applications`, macOS Gatekeeper may display a security prompt on initial launch:

> **"Ark Browser.app" Not Opened**  
> *Apple could not verify "Ark Browser.app" is free of malware that may harm your Mac or compromise your privacy.*

#### Why this happens
Web browsers tag all downloaded files with a `com.apple.quarantine` extended attribute. Because Ark Browser is an independent open-source project signed with developer credentials rather than an Apple-notarized commercial certificate, macOS Gatekeeper blocks quarantined downloads until authorized by the user.

#### How to Open (One-Time Setup)

Choose either of the following methods to open the browser for the first time:

- **Method A: macOS System Settings (GUI)**
  1. Open **System Settings > Privacy & Security**.
  2. Scroll down to the **Security** section.
  3. You will see: `Ark Browser.app was blocked from use because it is not from an identified developer`.
  4. Click **Open Anyway** and enter your macOS login password.

- **Method B: Terminal (Instant)**
  Open Terminal and run the following command to remove the quarantine flag attached by your browser:
  ```bash
  xattr -cr "/Applications/Ark Browser.app"
  ```
  You can now launch Ark Browser directly from `/Applications` or Spotlight without warnings.

#### Keychain Authorization ("Ark Browser Safe Storage")
On the very first launch, macOS may prompt for access to `"Ark Browser Safe Storage"` in your Keychain. Enter your Mac login password and click **Always Allow**. This permanently authorizes the browser to encrypt and store local profile keys securely.

#### Seamless Automatic Updates
Once installed, future updates are delivered directly inside the browser at **`ark://settings/help`**. The internal updater automatically removes quarantine flags in the background before swapping the app bundle, so in-browser updates relaunch immediately without Gatekeeper or Keychain prompts.

---

## Key Features & Current Foundation

### 1. Integrated AI Sidebar (Right-Docked & Non-Overlapping)
- **Content Squeeze**: When the AI sidebar is toggled open, it smoothly animates and squeezes the browsing web contents instead of overlaying them, ensuring full visibility of web pages while chatting.
- **Ergonomic Toolbar Toggle**: The Ark AI sidebar button is positioned at the **extreme right** of the toolbar, directly adjacent to the side panel.

### 2. Workspace & New Tab Experience (`ark://newtab`)
- **Unified Mode Switcher**: Easily switch between standard **Web** navigation and **Ask AI** mode.
- **Ask AI Mode**: Querying in Ask AI mode automatically prepares the draft and opens the AI sidebar.
- **Draft Composer**: Accessible in both the new tab page and the sidebar, with an auto-expanding, clean text area free of awkward manual resize handles.
- **Theme Synchronization**: WebUI pages automatically synchronize with system and browser appearance preferences (light/dark mode).

### 3. Native Settings & Privacy Focus (`ark://settings`)
- **Your Profile**: Settings sections are tailored for local profiles; Google sync dependencies and "Google Services" options have been removed from both Settings and the profile avatar menu.
- **Standalone Settings**: Google's AI configuration panels have been removed in favor of Ark's upcoming native model orchestration.
- **Browser Sign-In Disallowed by Default**: Protects privacy and keeps browsing local without intrusive account prompts or account interception bubbles.
- **Ark Browser Branding**: Settings left navigation and the "About Ark Browser" page feature official Ark Browser logos.

### 4. Native `ark://` Scheme
- Built-in pages use `ark://`, including `ark://newtab/`, `ark://settings/`, `ark://history/`, `ark://bookmarks/`, `ark://downloads/`, and `ark://ark-chat/`.
- Aliases map seamlessly to Chromium internal security and WebUI boundaries.

---

## Planned Capabilities

- **Cloud Model Integrations**: Bring-your-own-key support for OpenAI, Anthropic, Amazon Bedrock, Together AI, and custom OpenAI-compatible endpoints.
- **Local On-Device Inference**: Hugging Face model discovery, verified GGUF download management, and local offline inference via llama.cpp / ONNX.
- **Page Context & Memory**: Explicit controls for attaching page content, selected text, and session history.
- **Release Channels**: Dedicated automated build and release distribution for macOS, Linux, and Windows.

---

## Developer Documentation

### Repository Layout

```text
Ark-Browser/
├── chromium/
│   ├── .gclient               Local Chromium checkout configuration
│   └── src/                   Ark Chromium fork submodule (branch: ark-browser)
├── config/
│   └── dev.gn                 Development GN build configuration
├── depot_tools/               Pinned Chromium development tools submodule
├── release/
│   └── version.json           Live update manifest consumed by ark://settings/help
├── scripts/
│   ├── build-dmg.sh           Development component DMG packaging script
│   ├── build-release-dmg.sh   Production monolithic DMG & ZIP packaging script
│   ├── env.sh                 zsh environment configuration helper
│   ├── generate-ark-icons.py  Generates application icons from Ark SVGs
│   └── publish-release.py     Automated version bump and GitHub Release publisher
└── tests/
    └── smoke_ui.py            Compiled-browser CDP smoke tests
```

---

### Building on macOS

Chromium builds require substantial disk space (100 GB+), RAM, and build time. Install Xcode and command-line tools first.

#### 1. Environment Setup

Clone the repository with submodules:

```zsh
git clone --recurse-submodules https://github.com/Arkapravo-Ghosh/Ark-Browser.git
cd Ark-Browser
source scripts/env.sh
```

#### 2. Fetch Dependencies

Sync dependencies and generate gclient hooks:

```zsh
cd "$CHROMIUM_ROOT"
gclient sync
gclient runhooks
```

#### 3. Compile Development Build

Compile the `chrome` target:

```zsh
cd "$CHROMIUM_SRC"
autoninja -C out/ArkDev chrome
```

#### 4. Launch Ark Browser

Launch with an isolated development user profile:

```zsh
open "$CHROMIUM_SRC/out/ArkDev/Ark Browser.app" --args \
  --user-data-dir="$ARK_ROOT/dev-profile"
```

#### 5. Automated UI Verification

Run the automated CDP smoke tests from the workspace root:

```zsh
python3 tests/smoke_ui.py
```

Test results and screenshots are saved to `test-results/`.

#### 6. Packaging & DMG Distribution

##### Development DMG Installer
For quick local testing of component development builds:
```zsh
./scripts/build-dmg.sh
```
Packages `dist/Ark-Browser.dmg` directly from `out/ArkDev`.

##### Production Release DMG & ZIP
For generating an optimized, signed release installer matching Google Chrome and Edge sizing (~1 GB installed, ~160 MB compressed DMG/ZIP):
```zsh
./scripts/build-release-dmg.sh --build
```
This automatically configures `out/ArkRelease` with:
- `is_debug = false`
- `is_component_build = false` (monolithic framework, zero loose component dylibs)
- `symbol_level = 0` (stripped DWARF debug symbols)
- `dcheck_always_on = false`
and produces both `dist/Ark-Browser-Release.dmg` and `dist/Ark-Browser-mac-arm64.zip`.

#### 7. Publishing Releases & Updates

Ark Browser features an integrated update infrastructure connected to GitHub Releases:

1. Build, hash, and publish a release in a single command:
   ```zsh
   python3 scripts/publish-release.py -v 155.0.8049.0-alpha.0.0.8 --build
   ```
   This command:
   - Builds the production DMG & ZIP via `scripts/build-release-dmg.sh`.
   - Computes the exact file sizes and SHA-256 hashes.
   - Automatically updates `release/version.json`.
   - Creates the GitHub Release via `gh release create` and uploads release assets.

2. In-Browser Update Checks:
   - Navigating to `ark://settings/help` queries `release/version.json`.
   - macOS arm64 installs are checked automatically against release assets.
   - Windows installs are forward-compatible with future `.exe` releases.
   - Linux builds cleanly delegate updates to system package managers with all update check errors suppressed.

---

## Source Repositories

- **Main Repository**: [Arkapravo-Ghosh/Ark-Browser](https://github.com/Arkapravo-Ghosh/Ark-Browser)
- **Chromium Fork**: [Arkapravo-Ghosh/Ark-Browser-Chromium](https://github.com/Arkapravo-Ghosh/Ark-Browser-Chromium) (branch `ark-browser`)

---

## License

Ark Browser is free and open-source software licensed under the **GNU Affero General Public License Version 3 (AGPLv3)**.

```text
Copyright (C) 2026 Arkapravo Ghosh.

Ark Browser is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Ark Browser is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
```

See the full [LICENSE](LICENSE) file for details.

### Third-Party Licenses & Chromium Attribution
Ark Browser is built on top of the [Chromium](https://www.chromium.org/) open-source project. Chromium and bundled third-party libraries remain subject to their respective open-source licenses (including BSD-3-Clause, MIT, Apache-2.0, and others) as detailed in `about:credits` or `ark://credits/`.
