#!/usr/bin/env bash
# Source-tree launcher for the native Rust GTK application.
#
# The installed native package provides PREFIX/bin/codexbar-gtk-native and
# does not need this script. Explicit Python parity remains at run-python.sh.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
BIN_NAME=codexbar-gtk-native

if [[ -n "${CODEXBAR_NATIVE_BINARY:-}" ]]; then
  BINARY="$CODEXBAR_NATIVE_BINARY"
  if [[ ! -x "$BINARY" || -d "$BINARY" ]]; then
    echo "native launcher: CODEXBAR_NATIVE_BINARY is not an executable file: $BINARY" >&2
    exit 127
  fi
  exec "$BINARY" "$@"
fi

TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/rust-gtk/target}"
if [[ "$TARGET_DIR" != /* ]]; then
  TARGET_DIR="$ROOT/$TARGET_DIR"
fi

# Prefer the developer's existing debug binary; release is useful for a
# source checkout where only a release build has been prepared.
for candidate in "$TARGET_DIR/debug/$BIN_NAME" "$TARGET_DIR/release/$BIN_NAME"; do
  if [[ -x "$candidate" && ! -d "$candidate" ]]; then
    exec "$candidate" "$@"
  fi
done

if [[ "${CODEXBAR_NATIVE_NO_BUILD:-0}" == "1" ]]; then
  echo "native launcher: $BIN_NAME not found under $TARGET_DIR (build it with scripts/build-native.sh)" >&2
  exit 127
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "native launcher: cargo is required to build $BIN_NAME; install Rust/Cargo or set CODEXBAR_NATIVE_BINARY" >&2
  exit 127
fi

echo "native launcher: building $BIN_NAME (debug)" >&2
cargo build --manifest-path "$ROOT/rust-gtk/Cargo.toml" --locked --bin "$BIN_NAME" --target-dir "$TARGET_DIR"
BINARY="$TARGET_DIR/debug/$BIN_NAME"
if [[ ! -x "$BINARY" || -d "$BINARY" ]]; then
  echo "native launcher: cargo succeeded but executable is missing: $BINARY" >&2
  exit 126
fi
exec "$BINARY" "$@"
