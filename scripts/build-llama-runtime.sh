#!/usr/bin/env zsh
# Copyright 2026 Arkapravo Ghosh
# Build the pinned, self-contained llama.cpp CLI used by Ark Browser.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
LLAMA_SRC="$ROOT_DIR/third_party/llama.cpp"
BUILD_DIR="${LLAMA_BUILD_DIR:-$ROOT_DIR/third_party/llama.cpp/build-ark}"

if [[ ! -f "$LLAMA_SRC/CMakeLists.txt" ]]; then
  echo "Error: llama.cpp submodule is missing at $LLAMA_SRC" >&2
  echo "Run: git submodule update --init --recursive third_party/llama.cpp" >&2
  exit 1
fi

# Keep an existing build directory's generator stable. CMake does not allow
# switching generators in place, and Ninja may become available between runs.
if [[ -f "$BUILD_DIR/CMakeCache.txt" ]]; then
  CMAKE_GENERATOR="$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "$BUILD_DIR/CMakeCache.txt" | head -n 1)"
fi
if [[ -z "${CMAKE_GENERATOR:-}" ]]; then
  if command -v ninja >/dev/null 2>&1; then
    CMAKE_GENERATOR=Ninja
  else
    CMAKE_GENERATOR="Unix Makefiles"
  fi
fi

cmake -S "$LLAMA_SRC" -B "$BUILD_DIR" -G "$CMAKE_GENERATOR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_BACKEND_DL=OFF \
  -DGGML_METAL=ON \
  -DGGML_METAL_EMBED_LIBRARY=ON \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DLLAMA_BUILD_EXAMPLES=ON \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_BUILD_TOOLS=ON \
  -DLLAMA_BUILD_COMMON=ON \
  -DLLAMA_BUILD_UI=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_CURL=OFF \
  -DLLAMA_OPENSSL=OFF

cmake --build "$BUILD_DIR" --target llama-cli --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-$(sysctl -n hw.ncpu)}"

CLI="$BUILD_DIR/bin/llama-cli"
if [[ ! -x "$CLI" ]]; then
  echo "Error: llama-cli was not produced at $CLI" >&2
  exit 1
fi

echo "Built self-contained llama.cpp CLI: $CLI"
"$CLI" --version
