#!/usr/bin/env bash
# Default installer for the native Rust GTK application.
#
#   ./scripts/install.sh [--prefix DIR] [--activate]
#   ./scripts/install.sh --uninstall [--prefix DIR]
#
# Default installation is additive and does not touch desktop/service
# activation. --activate explicitly writes the ownership-tracked desktop and
# user-service files; it never enables or starts the service. Rollback with
# --uninstall restores files this installer backed up when their installed
# hashes still match, and preserves user edits.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(dirname -- "$SCRIPT_DIR")"
INSTALLER="$SCRIPT_DIR/install-native.sh"
PREFIX_DIR="${PREFIX:-${HOME:?HOME must identify the installation user}/.local}"
ARTIFACT="${CODEXBAR_NATIVE_ARTIFACT:-}"
ACTIVATE=""
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) [[ $# -ge 2 ]] || { echo "--prefix requires a directory" >&2; exit 2; }; PREFIX_DIR="$2"; shift 2 ;;
    --artifact) [[ $# -ge 2 ]] || { echo "--artifact requires a path" >&2; exit 2; }; ARTIFACT="$2"; shift 2 ;;
    --activate) ACTIVATE=1; shift ;;
    --no-activate|--no-autostart) ACTIVATE=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$UNINSTALL" == "1" ]]; then
  exec "$INSTALLER" --uninstall --prefix "$PREFIX_DIR"
fi

if [[ -z "$ARTIFACT" ]]; then
  echo "==> Building native CodexBar (Rust GTK)"
  PROFILE="${PROFILE:-release}" OUT_DIR="${OUT_DIR:-$ROOT/rust-gtk/target/native}" \
    "$SCRIPT_DIR/build-native.sh"
  ARTIFACT="${OUT_DIR:-$ROOT/rust-gtk/target/native}/codexbar-gtk-native"
fi

ARGS=(--artifact "$ARTIFACT" --prefix "$PREFIX_DIR")
if [[ "$ACTIVATE" == "1" ]]; then
  ARGS+=(--activate)
elif [[ "$ACTIVATE" == "0" ]]; then
  ARGS+=(--no-activate)
fi

"$INSTALLER" "${ARGS[@]}"

if [[ -x "$PREFIX_DIR/bin/codexbar-gtk" ]]; then
  echo "Existing legacy launcher retained: $PREFIX_DIR/bin/codexbar-gtk" >&2
  echo "It was not replaced. To remove that legacy package, first roll back the native install, then use scripts/install-python.sh --uninstall." >&2
fi

echo "Native binary installed at: $PREFIX_DIR/bin/codexbar-gtk-native"
echo "Desktop/service activation: ${ACTIVATE:-preserved from manifest; first install stays inactive}"
echo "Rollback: scripts/install.sh --uninstall --prefix '$PREFIX_DIR'"
