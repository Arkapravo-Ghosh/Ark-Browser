# Ark Browser

Ark Browser is a Chromium-based desktop browser with a local-first AI assistant. It keeps ordinary browsing fast and familiar while making model-assisted work available beside the page. On Apple Silicon, local inference runs with Metal and the user chooses which installed model or cloud provider to use.

The project is intended to grow into a browser-operation assistant: MCP servers and tools will provide bounded browser capabilities, agents will combine those tools into user-approved workflows, and vision models will help understand pages and screenshots. Those capabilities are being built behind explicit permissions and confirmation; Ark must not silently navigate, click, submit, or send data on a user's behalf.

[![Latest Release](https://img.shields.io/github/v/release/Arkapravo-Ghosh/Ark-Browser?style=flat-square&color=blue)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-macOS%20(Apple%20Silicon)-brightgreen.svg)](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)

## For users

### Download

Ark currently ships for macOS on Apple Silicon (arm64):

- [Download the latest DMG](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-PreRelease.dmg)
- [Download the application ZIP](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest/download/Ark-Browser-mac-arm64.zip)
- [View releases and notes](https://github.com/Arkapravo-Ghosh/Ark-Browser/releases/latest)

Open the DMG, drag `Ark Browser.app` to `/Applications`, and launch it. This is an independently distributed build, so macOS may require **Open Anyway** in **System Settings > Privacy & Security** on first launch. The equivalent terminal command is:

```zsh
xattr -cr "/Applications/Ark Browser.app"
```

Ark checks `release/version.json` from the project's GitHub repository for updates. It downloads the arm64 ZIP, verifies its SHA-256 digest, removes download quarantine, and replaces the application bundle only after verification. Local conversations and model files remain on the machine; cloud providers are opt-in.

### What is included today

- Chromium browsing with Ark's `ark://` built-in pages.
- AI chat in the side panel and full chat page, with local conversation persistence.
- Local GGUF inference through the pinned, bundled `llama.cpp` runtime.
- Local MLX/VLM inference through a relocatable bundled Python runtime.
- A model manager for Hugging Face downloads, selection, verification, and deletion.
- Optional cloud-model connectors where the user supplies credentials.

## Technology and boundaries

Ark is split into layers so the browser remains usable if an AI runtime fails:

- **Chromium fork (`chromium/src`)**: browser, tabs, WebUI, sandboxing, networking, and macOS packaging.
- **Ark browser services (C++)**: profile-scoped AI orchestration, conversation persistence, model management, updater, and typed Mojo IPC.
- **Ark WebUI (TypeScript)**: `ark://` pages and chat/model interfaces. It talks to C++ through Mojo rather than starting a separate desktop shell.
- **Local inference**: `llama.cpp` handles GGUF models; MLX-VLM handles MLX safetensors/VLM models. Both are bundled in production and run outside the browser's main process with Metal acceleration.
- **Cloud inference**: the browser-owned Gemini adapter uses Chromium networking; the WebUI does not call provider endpoints or persist provider responses. The same service boundary is the extension point for later OpenAI-compatible endpoints such as LM Studio.
- **Storage**: conversations are stored in SQLite under `$HOME/.arkbrowser`; credentials use Chromium's OS-protected credential facilities. Incognito data is transient.
- **Release/update path**: a monolithic `ArkRelease` app is packaged as a DMG and ZIP; the ZIP and manifest power in-browser updates.

The security goal is local-first operation, explicit context attachment, isolated inference, and user confirmation before future tools or agents perform consequential browser actions. MCP, tools, agents, and vision are product direction as the interfaces mature, not a promise that every workflow is already enabled.

## Repository layout

```text
Ark-Browser/
├── chromium/src/             Ark Chromium fork (branch: ark-browser)
├── depot_tools/              Chromium build tools
├── release/version.json      Public update manifest
├── scripts/                  Build, runtime, icon, and release automation
├── tests/                    CDP smoke tests and MLX runner tests
└── ark.icon/                 macOS Icon Composer source package
```

## Development on macOS

Use an Apple Silicon Mac with Xcode Command Line Tools, Python 3, Git, `uv`, and a working Chromium checkout. Plan for at least 16 GB RAM and 120 GB of free disk space.

```zsh
git clone --recurse-submodules https://github.com/Arkapravo-Ghosh/Ark-Browser.git
cd Ark-Browser
source scripts/env.sh
cd "$CHROMIUM_ROOT"
gclient sync
gclient runhooks
cd "$CHROMIUM_SRC"
autoninja -C out/ArkDev chrome
open "out/ArkDev/Ark Browser.app" --args \
  --user-data-dir="$ARK_ROOT/dev-profile"
```

`out/ArkDev` is a component build for fast iteration. If you want to test local models, stage both runtimes into the app first:

```zsh
cd "$ARK_ROOT"
./scripts/bundle-mlx-runtime.sh --build-dir ArkDev
./scripts/build-llama-runtime.sh
./scripts/bundle-llama-runtime.sh --build-dir ArkDev
```

The development DMG builder performs that staging automatically:

```zsh
./scripts/build-dmg.sh
open dist/Ark-Browser.dmg
```

Run the browser smoke suite against a compiled build:

```zsh
python3 tests/smoke_ui.py
```

For C++ or resource changes, regenerate and rebuild with GN/autoninja from `chromium/src`:

```zsh
gn gen out/ArkDev
autoninja -C out/ArkDev chrome
```

## Scripts

Run scripts from the repository root after `source scripts/env.sh`:

| Script | Purpose |
| --- | --- |
| `env.sh` | Exports `ARK_ROOT`, Chromium paths, and `depot_tools` on `PATH`. |
| `build-llama-runtime.sh` | Configures the pinned `third_party/llama.cpp` submodule with Metal and builds `llama-cli`. |
| `bundle-llama-runtime.sh` (`--build-dir ArkDev` or `ArkRelease`) | Copies the locally built `llama-cli` into an app bundle. |
| `bundle-mlx-runtime.sh` (`--build-dir ArkDev` or `ArkRelease`) | Builds a relocatable arm64 Python environment and installs the pinned MLX-VLM runtime in the app. |
| `build-dmg.sh` | Packages an ArkDev component build as `dist/Ark-Browser.dmg`, bundling both local runtimes. |
| `build-release-dmg.sh [--build]` | Builds (when requested), signs, and packages the monolithic release app as DMG and ZIP. |
| `sync-mac-icon.sh` | Copies `ark.icon/` into Chromium and regenerates legacy macOS icon assets. |
| `generate-ark-icons.py` | Runs the Ark icon generation pipeline, including macOS icon synchronization. |
| `publish-release.py` | Computes release metadata, updates the manifest, and creates/uploads a GitHub Release through `gh`. |

The local model manager is `scripts/ark-model-manager.py`; it resolves immutable Hugging Face revisions, resumes downloads, verifies hashes, and installs models under `$HOME/.arkbrowser`.

## Production packaging and release

Build the production app from the repository root:

```zsh
source scripts/env.sh
./scripts/build-release-dmg.sh --build
```

This uses `out/ArkRelease` (`is_component_build = false`, `is_debug = false`, stripped symbols), bundles the locally compiled `llama.cpp` and MLX-VLM runtimes, signs nested macOS code, and writes release artifacts under `dist/`.

To publish a version after updating the Ark version constants in `chromium/src`:

```zsh
VERSION="<next-version>"
python3 scripts/publish-release.py -v "$VERSION" --build
```

The publisher builds when requested, computes exact sizes and SHA-256 digests, updates `release/version.json`, and uses the GitHub CLI to upload the DMG, ZIP, and manifest. Review the generated artifacts and manifest before pushing the version change. A GitHub CLI login with release permissions is required.

When `ark.icon/` changes, run `./scripts/sync-mac-icon.sh` before the build. When the pinned `third_party/llama.cpp` source changes, run `./scripts/build-llama-runtime.sh`; the bundlers then use that local build rather than Homebrew's installation.

## License

Ark Browser is free and open-source software under the [GNU Affero General Public License v3](LICENSE). Chromium and other bundled projects retain their own licenses and attributions, available from `ark://credits/`.
