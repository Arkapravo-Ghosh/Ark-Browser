# Ark Browser

Ark Browser is an AI-powered desktop browser built on Chromium. It is designed to combine everyday browsing with an integrated AI assistant while letting users choose where their models run.

> Ark Browser is in early development. The current source builds as Chromium while Ark branding and product features are being implemented.

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

Generate and compile the development build:

```zsh
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

## Source repositories

- Ark workspace: [Arkapravo-Ghosh/Ark-Browser](https://github.com/Arkapravo-Ghosh/Ark-Browser)
- Ark Chromium fork: [Arkapravo-Ghosh/Ark-Browser-Chromium](https://github.com/Arkapravo-Ghosh/Ark-Browser-Chromium)
- Chromium upstream: [chromium/chromium](https://github.com/chromium/chromium)

## Attribution

Ark Browser is based on the Chromium open-source project. Chromium and bundled third-party components remain subject to their respective licenses and notices. Ark-specific licensing terms will be published with the first distributable release.
