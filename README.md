# Ark Browser

Ark Browser is an AI-powered desktop browser built on Chromium. It is designed to combine fast, everyday browsing with an integrated AI assistant while keeping users in complete control of their data and where models run.

> **Status**: Ark Browser is in active development. Native WebUI foundations, side panel orchestration, custom settings, and Ark branding are implemented. The development application builds as `Ark Browser.app`.

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

## Repository Layout

```text
Ark-Browser/
├── chromium/
│   ├── .gclient          Local Chromium checkout configuration
│   └── src/              Ark Chromium fork submodule (branch: ark-browser)
├── config/
│   └── dev.gn            Development GN build configuration
├── depot_tools/          Pinned Chromium development tools submodule
├── tests/
│   └── smoke_ui.py       Compiled-browser CDP smoke tests
└── scripts/
    ├── env.sh            zsh environment configuration helper
    └── generate-ark-icons.py  Generates application icons from the Ark SVG
```

---

## Building on macOS

Chromium builds require substantial disk space (100 GB+), RAM, and build time. Install Xcode and command-line tools first.

### 1. Environment Setup

Clone the repository with submodules:

```zsh
git clone --recurse-submodules https://github.com/Arkapravo-Ghosh/Ark-Browser.git
cd Ark-Browser
source scripts/env.sh
```

### 2. Fetch Dependencies

Sync dependencies and generate gclient hooks:

```zsh
cd "$CHROMIUM_ROOT"
gclient sync
gclient runhooks
```

### 3. Compile Development Build

Compile the `chrome` target:

```zsh
cd "$CHROMIUM_SRC"
autoninja -C out/ArkDev chrome
```

### 4. Launch Ark Browser

Launch with an isolated development user profile:

```zsh
open "$CHROMIUM_SRC/out/ArkDev/Ark Browser.app" --args \
  --user-data-dir="$ARK_ROOT/dev-profile"
```

### 5. Automated UI Verification

Run the automated CDP smoke tests from the workspace root:

```zsh
python3 tests/smoke_ui.py
```

Test results and screenshots are saved to `test-results/`.

### 6. Packaging & DMG Distribution

#### Development DMG Installer
For quick local testing of component development builds:
```zsh
./scripts/build-dmg.sh
```
Packages `dist/Ark-Browser.dmg` directly from `out/ArkDev`.

#### Production Release DMG Installer
For generating an optimized, minimal-footprint release installer matching Google Chrome and Edge sizing (~1 GB installed, ~250 MB compressed DMG):
```zsh
./scripts/build-release-dmg.sh --build
```
This automatically configures `out/ArkRelease` with:
- `is_debug = false`
- `is_component_build = false` (monolithic framework, zero loose component dylibs)
- `symbol_level = 0` (stripped DWARF debug symbols)
- `dcheck_always_on = false`
and packages `dist/Ark-Browser-Release.dmg`.

---

## Source Repositories

- **Main Repository**: [Arkapravo-Ghosh/Ark-Browser](https://github.com/Arkapravo-Ghosh/Ark-Browser)
- **Chromium Fork**: [Arkapravo-Ghosh/Ark-Browser-Chromium](https://github.com/Arkapravo-Ghosh/Ark-Browser-Chromium) (branch `ark-browser`)

---

## Attribution & License

Copyright © 2026 Arkapravo Ghosh for Ark Browser.
Ark Browser is based on the Chromium open-source project. Chromium and bundled third-party components remain subject to their respective licenses and notices. Ark-specific licensing terms will be published with the first distributable release.
