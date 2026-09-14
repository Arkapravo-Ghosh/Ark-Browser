# Ark Browser

Ark Browser is an AI-powered desktop browser built directly on Chromium. It combines fast, standard-compliant browsing with an integrated, non-overlapping AI sidebar and workspace assistant, giving users complete ownership of their browsing data, API credentials, and choice of cloud or local models.

[![Latest Release](https://img.shields.io/github/v/release/Arkapravo-Ghosh/Ark-Browser?style=flat-square&color=blue)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-macOS%20(Apple%20Silicon)-brightgreen.svg)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)

---

## Download & Installation

### Latest macOS Release (Apple Silicon / arm64)

[![Download for macOS](https://img.shields.io/badge/Download-macOS%20(Apple%20Silicon%20DMG)-2ea44f?logo=apple&style=for-the-badge)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-PreRelease.dmg)

- 💿 **[Download Latest DMG (.dmg)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-PreRelease.dmg)** — Official macOS installer disk image.
- 📦 **[Download Application Archive (.zip)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-mac-arm64.zip)** — Compressed application bundle.
- 📋 **[All Releases & Changelog](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)** — Full release notes, checksums, and assets.

---

### macOS First-Launch & Security Instructions

When downloading Ark Browser using a web browser and dragging `Ark Browser.app` to `/Applications`, macOS Gatekeeper may intercept the first launch with:

> **"Ark Browser.app" Not Opened**<br>
> *Apple could not verify "Ark Browser.app" is free of malware that may harm your Mac or compromise your privacy.*

#### Why this happens
Browsers tag all downloaded files with a `com.apple.quarantine` extended attribute. Because Ark Browser is an independent open-source project signed with developer credentials rather than an Apple-notarized commercial certificate from Apple's paid program, macOS Gatekeeper blocks quarantined downloads until authorized by the user.

#### How to Open (One-Time Setup)

Choose either method to open the browser for the first time:

- **Method A: macOS System Settings (GUI)**
  1. Open **System Settings > Privacy & Security**.
  2. Scroll down to the **Security** section.
  3. Locate: `Ark Browser.app was blocked from use because it is not from an identified developer`.
  4. Click **Open Anyway** and enter your macOS login password.

- **Method B: Terminal (Instant)**
  Open Terminal and run the following command to remove the quarantine flag attached by your browser:
  ```bash
  xattr -cr "/Applications/Ark Browser.app"
  ```
  You can now launch Ark Browser directly from `/Applications` or Spotlight without warnings.

#### Keychain Authorization ("Ark Browser Safe Storage")
On the very first launch, macOS may prompt:
> *"Ark Browser wants to use your confidential information stored in 'Ark Browser Safe Storage' in your keychain."*

Enter your Mac login password and click **Always Allow**. This binds the safe storage encryption key to the official Apple Development signature (`G2UDNDU45G`) so Keychain grants access across all future launches and updates without prompting again.

#### Seamless Automatic Updates
Once installed, future updates are delivered directly inside the browser at **`ark://settings/help`**. The internal updater automatically removes quarantine attributes in the background before swapping the app bundle, so in-browser updates relaunch immediately without Gatekeeper or Keychain prompts.

---

## Key Features & Current Status

### Implemented Features (Current Release)
- **Non-Overlapping AI Sidebar**: Toggling the sidebar smoothly animates and squeezes the browsing content area instead of overlaying it, ensuring complete visibility of active web pages.
- **Ergonomic Toolbar Toggle**: Positioned at the extreme right of the main toolbar, directly adjacent to the side panel.
- **New Tab Experience (`ark://newtab`)**: Clean workspace page with quick Web/Ask AI mode switching, auto-expanding draft composer, and dark/light theme synchronization.
- **Native `ark://` Scheme**: Full internal URL routing for `ark://newtab/`, `ark://settings/`, `ark://credits/`, `ark://history/`, `ark://bookmarks/`, and `ark://downloads/`.
- **Privacy-Focused Settings (`ark://settings`)**: Local profile settings with Google sync dependencies, sign-in interception bubbles, and remote telemetry hooks stripped out.
- **Ark Branding & Viridian Design System**: Custom application icons, "About Ark Browser" UI, and styling.
- **In-Browser Update Infrastructure**: Background updater checking `release/version.json`, downloading `.zip` archives, verifying SHA-256 digests, stripping quarantine, and performing atomic bundle replacement with restart capability.
- **Apple Development Code Signing**: Stable code signature ensuring persistent macOS Keychain authorization across updates.

### Pending / Upcoming Capabilities (Roadmap)
- **Local On-Device Inference**: Bundled, pinned `llama.cpp` integration in an isolated utility process for running local GGUF models with Metal on macOS Apple Silicon; hard resource admission favors slower safe execution or rejection over instability.
- **Model Manager**: Separate Local and Cloud tabs with a search bar on each, friendly Hugging Face catalogue/download flow, and model-wise Edit/preset/expert settings.
- **Local AI Data Root**: Ark AI configuration, SQLite databases, model files, and artifacts under `$HOME/.arkbrowser` (future Windows: `%USERPROFILE%\.arkbrowser`); secrets remain in the OS credential vault.
- **Cloud Model Connectors**: Secure bring-your-own-credential support for OpenAI, Anthropic, Amazon Bedrock, Azure OpenAI/Foundry, Together AI, Hugging Face Inference Providers, Cloudflare Workers AI, and custom OpenAI-compatible endpoints.
- **Built-in Browser MCP Tools**: First-party new/existing-tab navigation, bounded page inspection and route discovery, viewport/region/full-page screenshots, and scoped cursor click/fill interaction.
- **Page Context Engine**: One-click attachment of the active tab DOM (readability extracted) or user-selected text into chat prompts.
- **Full Chat Interface**: Multi-turn conversations, code syntax highlighting, streaming cancellation, conversation naming/deletion, and local SQLite persistence.
- **Cross-Platform Distribution**: Automated build and packaging pipelines for Windows (`.exe`/`.msi`) and Linux (`.deb`/`.tar.gz`).

---

## Developer Documentation

### Repository & Submodule Layout

```text
Ark-Browser/
├── chromium/
│   ├── .gclient               Local Chromium checkout configuration
│   └── src/                   Ark Chromium fork submodule (branch: ark-browser)
├── config/
│   └── dev.gn                 Development GN build configuration
├── depot_tools/               Pinned Chromium development tools submodule
├── docs/                      Architecture, specs, and implementation guides
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

Building Chromium requires an Apple Silicon Mac (M1/M2/M3/M4) with at least 16 GB RAM and 100 GB+ free disk space.

#### 1. Environment Setup

Clone the repository with submodules and source environment helpers:

```zsh
git clone --recurse-submodules https://github.com/Arkapravo-Ghosh/Ark-Browser.git
cd Ark-Browser
source scripts/env.sh
```

#### 2. Sync Dependencies

Sync gclient dependencies and run Chromium hooks:

```zsh
cd "$CHROMIUM_ROOT"
gclient sync
gclient runhooks
```

#### 3. Compile Development Build

Compile the `chrome` target using autoninja:

```zsh
cd "$CHROMIUM_SRC"
autoninja -C out/ArkDev chrome
```

#### 4. Launch Development Build

Launch with an isolated local development user profile:

```zsh
open "$CHROMIUM_SRC/out/ArkDev/Ark Browser.app" --args \
  --user-data-dir="$ARK_ROOT/dev-profile"
```

#### 5. Run Automated CDP Smoke Tests

Execute the automated Chrome DevTools Protocol smoke test suite:

```zsh
python3 tests/smoke_ui.py
```
Test results and screenshots are saved to `test-results/`.

#### 6. Monolithic Production Packaging

Build the optimized, signed release DMG and ZIP archives (~160 MB compressed, ~1 GB installed):

```zsh
./scripts/build-release-dmg.sh --build
```
This configures `out/ArkRelease` with `is_debug = false`, `is_component_build = false`, and `symbol_level = 0`, bundles the local `llama.cpp`/Metal runtime, then signs with the local Apple Development certificate.

#### 7. Publishing Releases

Publish a new version bump and upload release assets to GitHub Releases:

```zsh
python3 scripts/publish-release.py -v <next-version> --build
```

For comprehensive engineering specifications and the pending AI implementation roadmap, see [docs/](docs/). The detailed local-runtime, model-management, chat/context, MCP, agent, and multimodal design begins at [docs/ai-engine/](docs/ai-engine/).

The developer bootstrap model manager is available at `scripts/ark-model-manager.py`. It can search Hugging Face, resolve immutable revisions, resume downloads, verify SHA-256, and install into `$HOME/.arkbrowser`; see [the local model download guide](docs/11-local-model-download-guide.md).

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
Ark Browser is built upon the [Chromium](https://www.chromium.org/) open-source project. Chromium and bundled third-party libraries remain subject to their respective open-source licenses (including BSD-3-Clause, MIT, Apache-2.0, and others) as detailed in `about:credits` or `ark://credits/`.
