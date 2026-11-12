#!/usr/bin/env bash
# Default source-tree launcher for the native Rust GTK application.
# Arguments are passed unchanged; the launcher fails clearly if native startup
# cannot proceed and never falls back to Python.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$SCRIPT_DIR/scripts/run-native.sh" "$@"
