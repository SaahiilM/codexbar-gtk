#!/usr/bin/env bash
# Private C02 installer activation/command-target proof. Does not use host GUI,
# bus, systemd, login manager or network at runtime.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREVIOUS_COMMIT=41d2fcf982aef52cd86a64cb769176b494abb63c
EVIDENCE_DIR=${SMOKE_EVIDENCE:-$(mktemp -d "${TMPDIR:-/tmp}/native-service-proof.XXXXXX")}
PREVIOUS_ARTIFACT=${PREVIOUS_ARTIFACT:-}
if [[ $# -gt 1 ]]; then echo 'usage: smoke-native-service.sh [PREVIOUS_ARTIFACT]' >&2; exit 3; fi
if [[ $# == 1 ]]; then PREVIOUS_ARTIFACT=$1; fi
mkdir -p "$EVIDENCE_DIR/work" "$EVIDENCE_DIR/work/installer/scripts/native/stage"
WORK="$EVIDENCE_DIR/work"
if [[ ! -x "$ROOT/rust-gtk/target/release/codexbar-gtk-native" ]]; then
  CARGO_NET_OFFLINE=true cargo build --locked --release --manifest-path "$ROOT/rust-gtk/Cargo.toml" --bin codexbar-gtk-native
fi
CURRENT_ARTIFACT="$ROOT/rust-gtk/target/release/codexbar-gtk-native"
if [[ -z "$PREVIOUS_ARTIFACT" ]]; then
  PREVIOUS_SOURCE="$WORK/previous-source"
  mkdir -p "$PREVIOUS_SOURCE"
  git -C "$ROOT" archive "$PREVIOUS_COMMIT" | tar -x -C "$PREVIOUS_SOURCE"
  CARGO_NET_OFFLINE=true cargo build --locked --release \
    --manifest-path "$PREVIOUS_SOURCE/rust-gtk/Cargo.toml" \
    --target-dir "$WORK/previous-target" --bin codexbar-gtk-native
  PREVIOUS_ARTIFACT="$WORK/previous-target/release/codexbar-gtk-native"
fi
for input in "$CURRENT_ARTIFACT" "$PREVIOUS_ARTIFACT"; do [[ -x "$input" ]] || { echo "not executable: $input" >&2; exit 3; }; done
PREVIOUS_ARTIFACT=$(realpath "$PREVIOUS_ARTIFACT")
[[ $(sha256sum "$CURRENT_ARTIFACT" | awk '{print $1}') != $(sha256sum "$PREVIOUS_ARTIFACT" | awk '{print $1}') ]] || { echo 'previous and current artifacts have identical hashes' >&2; exit 3; }
cp "$ROOT/scripts/install-native.sh" "$WORK/installer/scripts/install-native.sh"
cp "$ROOT/scripts/native/render_activation.sh" "$WORK/installer/scripts/native/render_activation.sh"
cp "$ROOT/scripts/native/stage/native.desktop" "$ROOT/scripts/native/stage/native.service" "$WORK/installer/scripts/native/stage/"
cp "$ROOT/scripts/native/no-python/service-targets.sh" "$WORK/service-targets.sh"
cp "$ROOT/scripts/native/no-python/docker/service-proof.sh" "$WORK/service-proof.sh"
chmod 755 "$WORK/installer/scripts/install-native.sh"
sha256sum "$CURRENT_ARTIFACT" "$PREVIOUS_ARTIFACT" "$WORK/installer/scripts/install-native.sh" > "$EVIDENCE_DIR/source-sha256.txt"
docker info >/dev/null 2>&1 || { echo 'SKIP: Docker daemon unavailable; no service proof' >&2; exit 2; }
IMAGE="codexbar-no-python:service-proof-$$"
cleanup_image() { docker image rm "$IMAGE" >/dev/null 2>&1 || true; }
trap cleanup_image EXIT INT TERM
docker build -t "$IMAGE" -f "$ROOT/scripts/native/no-python/docker/Dockerfile.runtime" "$ROOT" > "$WORK/docker-build.log"
docker run --rm --network none \
  --volume "$CURRENT_ARTIFACT:/artifacts/current:ro" \
  --volume "$PREVIOUS_ARTIFACT:/artifacts/previous:ro" \
  --volume "$WORK:/work:ro" \
  "$IMAGE" /bin/bash /work/service-proof.sh \
  > "$EVIDENCE_DIR/run.log" 2>&1 || { cat "$EVIDENCE_DIR/run.log"; exit 1; }
cat "$EVIDENCE_DIR/run.log"
echo "Previous artifact source: $PREVIOUS_COMMIT (pre-PR101 build-99 source)"
echo "Evidence directory: $EVIDENCE_DIR"
