# Ark Browser

Ark Browser is an AI-powered desktop browser built on Chromium. It is designed to combine everyday browsing with an integrated AI assistant while letting users choose where their models run.

> Ark Browser is in early development. The first native WebUI foundation is implemented; the app bundle remains Chromium while Ark packaging and AI services are developed.

## Current UI foundation

The new tab opens an Ark workspace with ordinary web search, browser shortcuts, a draft composer, model setup previews, advanced parameter descriptions, and an About page. Light/dark appearance and responsive layouts are included. AI sending and model connections are not available yet.

Built-in pages use `ark://`, including `ark://settings/`, `ark://history/`, and `ark://ark-chat/`. Chromium's canonical internal origins and security boundaries are preserved behind the alias. Policy and extension new-tab overrides, plus private browsing landing pages, retain their normal behavior.

UI source lives in `product/ui`; native controllers and a buildable resource snapshot live in the Chromium fork. See [product development and limitations](product/README.md).

## Planned capabilities

- AI chat in a resizable right sidebar, expandable into a full browser tab.
- AI chat directly on the new tab page.
- Cloud model connections for OpenAI, Anthropic, Amazon Bedrock, Together AI, and compatible custom endpoints.
- Hugging Face model discovery, download management, and local inference.
- Per-model advanced settings with clear descriptions for generation and performance parameters.
- Explicit page and selected-text context controls.
- Ark-controlled browser releases and updates.
- Ark Browser branding with clear Chromium attribution on the About page.

## Repository layout

```text
Ark-Browser/
├── chromium/
│   ├── .gclient       Local Chromium checkout configuration
│   └── src/           Ark Chromium fork submodule
├── depot_tools/       Pinned Chromium development tools submodule
├── product/           Ark-owned product configuration and assets
│   ├── ui/            Ark WebUI source and initial artwork
│   ├── tests/         Compiled-browser smoke checks
│   └── config/dev.gn  Development build configuration
└── scripts/env.sh     zsh environment helper
```

Chromium's own `DEPS` and `gclient` workflow continue to manage its platform-specific source dependencies. The `chromium/src` submodule points to the Ark fork, where browser-level product changes are developed.

## Building on macOS

Chromium builds require substantial disk space, memory, and build time. Install Xcode and its command-line tools first. Refer to Chromium's [macOS build instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/mac_build_instructions.md) for current host requirements.

Clone the repository and initialize the pinned source and tooling:

```zsh
git clone --recurse-submodules https://github.com/Arkapravo-Ghosh/Ark-Browser.git
cd Ark-Browser
source scripts/env.sh
```

Fetch Chromium's pinned dependencies and run its setup hooks:

```zsh
cd "$CHROMIUM_ROOT"
gclient sync
gclient runhooks
```

Synchronize the product UI, then generate and compile the development build:

```zsh
python3 "$ARK_ROOT/scripts/sync-product-ui.py"
cd "$CHROMIUM_SRC"
mkdir -p out/Ark
cp "$ARK_ROOT/product/config/dev.gn" out/Ark/args.gn
gn gen out/Ark
autoninja -C out/Ark chrome
```

Launch with an isolated development profile:

```zsh
open "$CHROMIUM_SRC/out/Ark/Chromium.app" --args \
  --user-data-dir="$ARK_ROOT/product/dev-profile"
```

The application bundle remains `Chromium.app` until Ark's branding and packaging changes are complete. Do not use a personal Chrome or Chromium profile for development builds.

The existing successful development output is `out/ArkDev`; use that directory instead of `out/Ark` to rebuild it incrementally without changing its GN arguments. Test from the workspace root with `python3 product/tests/smoke_ui.py` (Python `websockets` required). Screenshots and test output go to `product/test-results/`.

## Source repositories

- Ark workspace: [Arkapravo-Ghosh/Ark-Browser](https://github.com/Arkapravo-Ghosh/Ark-Browser)
- Ark Chromium fork: [Arkapravo-Ghosh/Ark-Browser-Chromium](https://github.com/Arkapravo-Ghosh/Ark-Browser-Chromium)
- Chromium upstream: [chromium/chromium](https://github.com/chromium/chromium)

## Attribution

Copyright © 2026 Arkapravo Ghosh for Ark Browser. Ark Browser is based on the Chromium open-source project. Chromium and bundled third-party components remain subject to their respective licenses and notices. Ark-specific licensing terms will be published with the first distributable release.
