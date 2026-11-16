#!/usr/bin/env bash
# Build the native Rust GTK binary as a prebuilt artifact. Does NOT install.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PROFILE="${PROFILE:-release}" # release|debug
OUT_DIR="${OUT_DIR:-$ROOT/rust-gtk/target/native}"
TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/rust-gtk/target}"
if [[ "$TARGET_DIR" != /* ]]; then TARGET_DIR="$ROOT/$TARGET_DIR"; fi
case "$PROFILE" in release|debug) ;; *) echo "PROFILE must be release or debug" >&2; exit 1;; esac
BUILD_ARGS=()
[[ "$PROFILE" != "release" ]] || BUILD_ARGS+=(--release)
cargo build --manifest-path "$ROOT/rust-gtk/Cargo.toml" --locked --bin codexbar-gtk-native --target-dir "$TARGET_DIR" "${BUILD_ARGS[@]}"
SRC="$TARGET_DIR/$PROFILE/codexbar-gtk-native"
mkdir -p "$OUT_DIR"
TMP="$(mktemp "$OUT_DIR/.codexbar-gtk-native.XXXXXX")"
cp -a "$SRC" "$TMP"; chmod +x "$TMP"
mv -f "$TMP" "$OUT_DIR/codexbar-gtk-native"
sha256sum "$OUT_DIR/codexbar-gtk-native" > "$OUT_DIR/codexbar-gtk-native.sha256"
echo "artifact: $OUT_DIR/codexbar-gtk-native (profile=$PROFILE)"
