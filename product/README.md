# Ark product layer

Copyright © 2026 Arkapravo Ghosh. Chromium and bundled third-party components retain their existing copyrights and licenses.

`ui/` owns Ark's new-tab and chat workspace: TypeScript, HTML, CSS, the initial Ark mark, and the WebUI resource build definition. It uses local fonts and assets, Chromium's WebUI toolchain, and a typed Mojo interface. The native WebUI approach keeps React and Python out of the privileged browser runtime because neither is needed for these surfaces.

## What works

- New tabs open the Ark workspace, except policy/extension overrides and private/guest landing pages.
- `ark://ark-chat/` opens the workspace. Hash routes `#home`, `#chat`, `#models`, `#advanced`, and `#about` share one document.
- `ark://settings/`, `ark://history/`, `ark://downloads/`, `ark://bookmarks/`, `ark://version/`, and other built-in hosts resolve through Chromium's existing controllers. The omnibox displays `ark://` for canonical Chromium pages as well.
- Web search/address entry uses the current profile's Chromium autocomplete classifier and selected search engine. This small field permits HTTP(S) results; the native address bar remains available for all browser URLs.
- The Ark logo button sits at the extreme right of the toolbar and toggles a 420 px Ark AI side panel that smoothly squeezes the web contents.
- New-tab Web and Ask AI modes share one input. Ask AI stores the prompt in the current conversation, opens the sidebar, and continues there.
- Composer drafts are stored through a profile-scoped C++ service in SQLite at `ArkAI/conversations.sqlite3`. Off-the-record profiles use a separate in-memory database.
- Model pages describe all five planned cloud connections and the planned Hugging Face/local path. Advanced options explain all 17 specified parameters. Sending, credentials, downloads, and parameter editing are unavailable.
- Light, dark, and system appearance; narrow-window navigation; focus indicators; reduced-motion support; confirmation dialog keyboard behavior; and Chromium/copyright attribution.

The `ark://` scheme is a user-facing alias, normalized to canonical `chrome://` URLs before Chromium handles navigation. Existing WebUI origins, resource URLs, Mojo bindings, CSP, security checks, and extension/policy handlers keep their Chromium semantics. Developer tools may therefore report the canonical `chrome://` origin. This is deliberate, not a new privileged renderer scheme.

This is an integrated UI and storage foundation, not completion of M2. Message generation/streaming, conversation history controls, providers, Hugging Face downloads, local inference, model presets, page attachments, Actor tool adaptation, application/bundle branding, and Ark updates remain implementation work. Model settings are currently inside the workspace, not embedded in Chromium's settings router. The UI copy is English; localization and a screen-reader audit remain release work.

## Build and verify

The fork contains a checked-in snapshot of `ui/` under `chrome/browser/resources/ark/`. This keeps a standalone Chromium fork build reproducible without depending on files outside its checkout. Edit `product/ui`, then synchronize before building. The sync command only updates the five explicitly owned resource files and does not delete unrelated fork files.

```zsh
python3 scripts/sync-product-ui.py
python3 scripts/sync-product-ui.py --check
source scripts/env.sh
cd "$CHROMIUM_SRC"
gn gen out/ArkDev
autoninja -C out/ArkDev chrome
```

Keep the snapshot changes with the fork commit, and the product source with the coordinating root commit. `--check` fails if either copy has drifted. The fork's `chrome/browser/ark` feature definition, WebUI controller/Mojo contract, URL integration, and native build plumbing remain maintained directly in the fork.

```zsh
# From the workspace root, using Python with websockets installed:
python3 product/tests/smoke_ui.py

# Visible native app, always with an isolated development profile:
open chromium/src/out/ArkDev/Chromium.app --args \
  --user-data-dir="$PWD/product/dev-profile" ark://newtab/
```

The smoke test starts its own headless compiled browser with disposable profiles, checks the UI and native navigation through DevTools, and writes screenshots, a JSON result, and browser logs to ignored `product/test-results/`. It uses a local HTTP fixture and blocks HTTPS in test tabs. Chromium itself may still attempt inherited background services; this does not claim a completed network/privacy audit. Python's `websockets` package is a test dependency, not a browser runtime dependency.

The `ArkUI` feature is enabled by default. `--disable-features=ArkUI` disables the workspace and restores Chromium's new tab while leaving `ark://` built-in navigation available. Extension and policy new-tab overrides retain priority.
