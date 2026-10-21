#!/usr/bin/env bash
# Launcher for the CodexBar GTK front-end.
#
#   ./run.sh              start the app
#   ./run.sh --settings   start it and open the settings window
#
# The script also wires up the private typelib prefix created by
# scripts/bootstrap-deps.sh when the system does not provide Gtk-4.0 / Adw-1.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SCRIPT_DIR}"
PREFIX="${ROOT}/.deps"

TYPELIB_DIR="${PREFIX}/root/usr/lib/x86_64-linux-gnu/girepository-1.0"
LIB_DIR="${PREFIX}/root/usr/lib/x86_64-linux-gnu"

if [[ -d "$TYPELIB_DIR" ]]; then
  export GI_TYPELIB_PATH="${TYPELIB_DIR}${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
  export LD_LIBRARY_PATH="${LIB_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export GDK_BACKEND="${GDK_BACKEND:-x11}"

exec python3 -m codexbar_gtk "$@"
