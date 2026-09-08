#!/usr/bin/env zsh

export ARK_ROOT="${0:A:h:h}"
export DEPOT_TOOLS="$ARK_ROOT/depot_tools"
export CHROMIUM_ROOT="$ARK_ROOT/chromium"
export CHROMIUM_SRC="$CHROMIUM_ROOT/src"

export PATH="$DEPOT_TOOLS:$PATH"
