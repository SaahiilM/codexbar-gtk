#!/usr/bin/env bash
# Private C02 installer activation/command-target proof. Does not use host GUI,
# bus, systemd, login manager or network at runtime.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREVIOUS_COMMIT=41d2fcf982aef52cd86a64cb769176b494abb63c
PREVIOUS_SOURCE=
EVIDENCE_DIR=${SMOKE_EVIDENCE:-$(mktemp -d "${TMPDIR:-/tmp}/native-service-proof.XXXXXX")}
PREVIOUS_ARTIFACT=${PREVIOUS_ARTIFACT:-}
if [[ $# -gt 1 ]]; then echo 'usage: smoke-native-service.sh [PREVIOUS_ARTIFACT]' >&2; exit 3; fi
if [[ $# == 1 ]]; then PREVIOUS_ARTIFACT=$1; fi
mkdir -p "$EVIDENCE_DIR/work" "$EVIDENCE_DIR/work/installer/scripts/native/stage"
WORK="$EVIDENCE_DIR/work"
CURRENT_TARGET="$WORK/current-target"
CURRENT_JSON="$WORK/current-cargo.json"
CARGO_NET_OFFLINE=true cargo build --locked --release --manifest-path "$ROOT/rust-gtk/Cargo.toml" \
  --target-dir "$CURRENT_TARGET" --bin codexbar-gtk-native --message-format=json-render-diagnostics > "$CURRENT_JSON"
CURRENT_ARTIFACT=$(python3 "$ROOT/scripts/native/no-python/cargo-artifact.py" --json "$CURRENT_JSON" --target codexbar-gtk-native)
if [[ -z "$PREVIOUS_ARTIFACT" ]]; then
  PREVIOUS_SOURCE="$WORK/previous-source"
  mkdir -p "$PREVIOUS_SOURCE"
  git -C "$ROOT" archive "$PREVIOUS_COMMIT" | tar -x -C "$PREVIOUS_SOURCE"
  CARGO_NET_OFFLINE=true cargo build --locked --release \
    --manifest-path "$PREVIOUS_SOURCE/rust-gtk/Cargo.toml" \
    --target-dir "$WORK/previous-target" --bin codexbar-gtk-native --message-format=json-render-diagnostics > "$WORK/previous-cargo.json"
  PREVIOUS_ARTIFACT=$(python3 "$ROOT/scripts/native/no-python/cargo-artifact.py" --json "$WORK/previous-cargo.json" --target codexbar-gtk-native)
fi
for input in "$CURRENT_ARTIFACT" "$PREVIOUS_ARTIFACT"; do [[ -x "$input" ]] || { echo "not executable: $input" >&2; exit 3; }; done
PREVIOUS_ARTIFACT=$(realpath "$PREVIOUS_ARTIFACT")
CURRENT_ARTIFACT=$(realpath "$CURRENT_ARTIFACT")
[[ $(sha256sum "$CURRENT_ARTIFACT" | awk '{print $1}') != $(sha256sum "$PREVIOUS_ARTIFACT" | awk '{print $1}') ]] || { echo 'previous and current artifacts have identical hashes' >&2; exit 3; }
cp "$ROOT/scripts/install-native.sh" "$WORK/installer/scripts/install-native.sh"
cp "$ROOT/scripts/native/render_activation.sh" "$WORK/installer/scripts/native/render_activation.sh"
cp "$ROOT/scripts/native/stage/native.desktop" "$ROOT/scripts/native/stage/native.service" "$WORK/installer/scripts/native/stage/"
cp "$ROOT/scripts/native/no-python/service-targets.sh" "$WORK/service-targets.sh"
cp "$ROOT/scripts/native/no-python/service-proof-lib.sh" "$WORK/service-proof-lib.sh"
cp "$ROOT/scripts/native/no-python/docker/service-proof.sh" "$WORK/service-proof.sh"
chmod 755 "$WORK/installer/scripts/install-native.sh"
CURRENT_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
CURRENT_MARKETING=$(sed -n 's/^MARKETING_VERSION=//p' "$ROOT/VERSION")
CURRENT_VERSION=$(sed -n 's/^CURRENT_PROJECT_VERSION=//p' "$ROOT/VERSION")
PREVIOUS_VERSION=$(sed -n 's/^CURRENT_PROJECT_VERSION=//p' "$PREVIOUS_SOURCE/VERSION" 2>/dev/null || true)
CURRENT_SOURCE_DIFF=$(git -C "$ROOT" diff HEAD --binary | sha256sum | awk '{print $1}')
CURRENT_SOURCE_TREE=$(cd "$ROOT" && git ls-files -co --exclude-standard -z | xargs -0 -r sha256sum | sha256sum | awk '{print $1}')
CURRENT_ARTIFACT_SHA=$(sha256sum "$CURRENT_ARTIFACT" | awk '{print $1}')
PREVIOUS_ARTIFACT_SHA=$(sha256sum "$PREVIOUS_ARTIFACT" | awk '{print $1}')
PREVIOUS_BUILD=${PREVIOUS_VERSION:-unknown}
{
  printf 'current-source-commit=%s\ncurrent-source-version=%s (%s)\ncurrent-source-tree-files-sha256=%s\ncurrent-working-diff-sha256=%s\ncurrent-artifact=%s\ncurrent-artifact-sha256=%s\n' \
    "$CURRENT_COMMIT" "$CURRENT_MARKETING" "$CURRENT_VERSION" "$CURRENT_SOURCE_TREE" "$CURRENT_SOURCE_DIFF" "$CURRENT_ARTIFACT" "$CURRENT_ARTIFACT_SHA"
  if [[ -n "$PREVIOUS_SOURCE" && -d "$PREVIOUS_SOURCE" ]]; then
    PREVIOUS_MARKETING=$(sed -n 's/^MARKETING_VERSION=//p' "$PREVIOUS_SOURCE/VERSION")
    printf 'previous-source-commit=%s\nprevious-source-version=%s (%s)\n' "$PREVIOUS_COMMIT" "$PREVIOUS_MARKETING" "$PREVIOUS_VERSION"
  else
    printf 'previous-source-commit=unknown (explicit PREVIOUS_ARTIFACT)\nprevious-source-version=unknown\n'
  fi
  printf 'previous-artifact=%s\nprevious-artifact-sha256=%s\n' "$PREVIOUS_ARTIFACT" "$PREVIOUS_ARTIFACT_SHA"
} > "$EVIDENCE_DIR/source-sha256.txt"
docker info >/dev/null 2>&1 || { echo 'SKIP: Docker daemon unavailable; no service proof' >&2; exit 2; }
IMAGE="codexbar-no-python:service-proof-$$"
CONTAINER="codexbar-service-proof-$$-${RANDOM}"
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  timeout --signal=TERM --kill-after=2s 8s docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  timeout --signal=TERM --kill-after=2s 8s docker image rm "$IMAGE" >/dev/null 2>&1 || true
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker build -t "$IMAGE" -f "$ROOT/scripts/native/no-python/docker/Dockerfile.runtime" "$ROOT" > "$WORK/docker-build.log"
timeout --signal=TERM --kill-after=5s 180s docker run --name "$CONTAINER" --network none \
  --volume "$CURRENT_ARTIFACT:/artifacts/current:ro" \
  --volume "$PREVIOUS_ARTIFACT:/artifacts/previous:ro" \
  --volume "$WORK:/work:ro" \
  "$IMAGE" /bin/bash /work/service-proof.sh \
  > "$EVIDENCE_DIR/run.log" 2>&1 || { cat "$EVIDENCE_DIR/run.log"; exit 1; }
cat "$EVIDENCE_DIR/run.log"
echo "Proof sequence: build $PREVIOUS_BUILD -> build $CURRENT_VERSION -> build $PREVIOUS_BUILD (command-target proof only)"
cat "$EVIDENCE_DIR/source-sha256.txt"
echo "Evidence directory: $EVIDENCE_DIR"
