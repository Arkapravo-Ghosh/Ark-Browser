#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Bundle a relocatable Apple Silicon MLX-VLM runtime inside Ark Browser.app.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
source "$SCRIPT_DIR/env.sh"

BUILD_DIR="${BUILD_DIR:-$CHROMIUM_SRC/out/ArkDev}"
MLX_VLM_VERSION="${MLX_VLM_VERSION:-0.5.0}"
PYTHON_VERSION="${ARK_MLX_PYTHON_VERSION:-3.12}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir)
      [[ $# -ge 2 ]] || { echo "Error: --build-dir requires a path"; exit 1; }
      if [[ "$2" = /* ]]; then
        BUILD_DIR="$2"
      else
        BUILD_DIR="$CHROMIUM_SRC/out/$2"
      fi
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--build-dir ArkDev|ArkRelease|/absolute/path]"
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1"
      exit 1
      ;;
  esac
done

APP_BUNDLE="$BUILD_DIR/Ark Browser.app"
MLX_DIR="$APP_BUNDLE/Contents/Resources/ark-mlx"
LEGACY_MLX_DIR="$APP_BUNDLE/Contents/Frameworks/mlx"
PYTHON_DIR="$MLX_DIR/python"

echo "=== Bundling MLX-VLM runtime into Ark Browser.app ==="
echo "Target build directory: $BUILD_DIR"

[[ "$(uname -m)" == "arm64" ]] || {
  echo "Error: the current MLX runtime target requires native Apple Silicon"
  exit 1
}
[[ -d "$APP_BUNDLE" ]] || {
  echo "Error: application bundle not found at $APP_BUNDLE"
  exit 1
}
command -v uv >/dev/null 2>&1 || {
  echo "Error: uv is required to assemble the relocatable MLX runtime"
  exit 1
}

echo "1. Resolving relocatable arm64 Python $PYTHON_VERSION..."
uv python install "$PYTHON_VERSION"
PYTHON_EXE="$(uv python find "$PYTHON_VERSION")"
PYTHON_EXE="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PYTHON_EXE")"
PYTHON_SOURCE="${PYTHON_EXE:h:h}"

echo "2. Copying the self-contained Python distribution..."
rm -rf "$MLX_DIR" "$LEGACY_MLX_DIR"
mkdir -p "$MLX_DIR"
ditto "$PYTHON_SOURCE" "$PYTHON_DIR"
ln -sf "python3.12" "$PYTHON_DIR/bin/python3"
cp -f "$SCRIPT_DIR/ark_mlx_runner.py" "$MLX_DIR/ark_mlx_runner.py"
# The copied interpreter is the app's private environment.
find "$PYTHON_DIR" -name EXTERNALLY-MANAGED -delete

echo "3. Installing pinned MLX-VLM $MLX_VLM_VERSION and server dependencies..."
uv pip install --python "$PYTHON_DIR/bin/python3" --system --break-system-packages --compile-bytecode \
  "mlx-vlm==$MLX_VLM_VERSION"

# The runtime is local-only. Remove package-manager entry points that Ark never
# invokes and source caches that unnecessarily increase the signed bundle.
find "$PYTHON_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true

echo "4. Verifying MLX, Metal, MLX-VLM, and Ark's runner contract..."
ARK_MLX_RUNNER="$MLX_DIR/ark_mlx_runner.py" "$PYTHON_DIR/bin/python3" - <<'PY'
import importlib.util
import os
import platform
from types import SimpleNamespace

import mlx.core as mx
import mlx_lm
import mlx_vlm

assert platform.machine() == "arm64", platform.machine()
assert mx.metal.is_available(), "MLX Metal backend is unavailable"
assert mlx_vlm is not None
# Text-only MLX checkpoints run through MLX-LM, a dependency of MLX-VLM.
assert mlx_lm is not None

runner_path = os.environ["ARK_MLX_RUNNER"]
spec = importlib.util.spec_from_file_location("ark_mlx_runner", runner_path)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
assert runner.completion_text(SimpleNamespace(text="ark-mlx-ok")) == "ark-mlx-ok"
assert runner.completion_text("legacy-result") == "legacy-result"
assert runner.select_backend({"model_type": "llama"}) == "lm"
assert runner.select_backend(
    {"model_type": "mllama", "vision_config": {}}) == "vlm"
# MLX-VLM 0.5.0 model files hand 0-d arrays to mx.tile/mx.repeat; the runner's
# shim must make that work on whichever mlx this bundle resolved.
runner.install_mlx_compat_shims()
assert mx.tile(mx.zeros((2, 3)), (mx.array(2), 1)).shape == (4, 3)
assert mx.repeat(mx.zeros((2,)), mx.array(3), axis=0).shape == (6,)
print("MLX Metal device:", mx.device_info())
PY

echo "5. Ad-hoc signing embedded Mach-O binaries..."
while IFS= read -r native; do
  [[ "$(file -b "$native")" == Mach-O* ]] || continue
  codesign --force --sign - "$native"
done < <(find "$PYTHON_DIR" -type f \( -perm -111 -o -name '*.so' -o -name '*.dylib' \))

echo "=== Bundled MLX-VLM successfully into Ark Browser.app ==="
