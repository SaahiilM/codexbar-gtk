#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
LAUNCHER="$ROOT/scripts/run-native.sh"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/target/debug" "$TMP/target/release"

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_args() {
  local expected="$1" actual
  actual="$(cat "$TMP/argv")"
  [[ "$actual" == "$expected" ]] || fail "argv mismatch: expected [$expected], got [$actual]"
}

cat > "$TMP/fake-native" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$NATIVE_TEST_ARGV"
FAKE
chmod +x "$TMP/fake-native"

# Explicit binary override forwards every argument boundary, including spaces
# and leading dashes, and does not inspect Python/GI/PyO3 environment settings.
env -u PYTHONPATH -u PYTHONHOME -u GI_TYPELIB_PATH -u PYO3_PYTHON -u LD_LIBRARY_PATH \
  CODEXBAR_NATIVE_BINARY="$TMP/fake-native" \
  NATIVE_TEST_ARGV="$TMP/argv" \
  "$LAUNCHER" --settings --about --panel --page 'usage pages' -- '--literal' 'two words'
assert_args $'--settings\n--about\n--panel\n--page\nusage pages\n--\n--literal\ntwo words'

# Existing debug binary is selected without invoking Cargo.
cp "$TMP/fake-native" "$TMP/target/debug/codexbar-gtk-native"
chmod +x "$TMP/target/debug/codexbar-gtk-native"
cat > "$TMP/bin/cargo" <<'CARGO'
#!/usr/bin/env bash
echo invoked > "$NATIVE_TEST_CARGO_CALLED"
exit 99
CARGO
chmod +x "$TMP/bin/cargo"
PATH="$TMP/bin:$PATH" CARGO_TARGET_DIR="$TMP/target" \
  NATIVE_TEST_ARGV="$TMP/argv" \
  NATIVE_TEST_CARGO_CALLED="$TMP/cargo-called" \
  "$LAUNCHER" --page spend
assert_args $'--page\nspend'
[[ ! -e "$TMP/cargo-called" ]] || fail "Cargo was invoked despite an existing binary"

# A broken explicit override fails as given instead of silently selecting or
# building a different binary.
if CODEXBAR_NATIVE_BINARY="$TMP/missing-native" CARGO_TARGET_DIR="$TMP/target" \
  "$LAUNCHER" >"$TMP/bad-override.out" 2>&1; then
  fail "invalid explicit binary unexpectedly succeeded"
fi
grep -Fq 'CODEXBAR_NATIVE_BINARY is not an executable file' "$TMP/bad-override.out" || fail "invalid override error is unclear"

# Missing-binary reporting is deterministic when auto-build is disabled.
if CODEXBAR_NATIVE_NO_BUILD=1 CARGO_TARGET_DIR="$TMP/empty-target" \
  "$LAUNCHER" >"$TMP/no-build.out" 2>&1; then
  fail "missing-binary invocation unexpectedly succeeded"
fi
grep -Fq 'codexbar-gtk-native not found' "$TMP/no-build.out" || fail "missing-binary error is unclear"

# Auto-build uses the selected target directory and invokes Cargo with a
# manifest path that remains valid when the selected target path contains spaces.
mkdir -p "$TMP/build target"
cat > "$TMP/bin/cargo" <<'CARGO'
#!/usr/bin/env bash
set -eu
[[ "$*" == *"--manifest-path $NATIVE_TEST_REPO/rust-gtk/Cargo.toml"* ]] || exit 31
mkdir -p "$NATIVE_TEST_TARGET/debug"
cp "$NATIVE_TEST_FAKE" "$NATIVE_TEST_TARGET/debug/codexbar-gtk-native"
chmod +x "$NATIVE_TEST_TARGET/debug/codexbar-gtk-native"
CARGO
chmod +x "$TMP/bin/cargo"
PATH="$TMP/bin:$PATH" CARGO_TARGET_DIR="$TMP/build target" \
  NATIVE_TEST_REPO="$ROOT" NATIVE_TEST_TARGET="$TMP/build target" \
  NATIVE_TEST_FAKE="$TMP/fake-native" NATIVE_TEST_ARGV="$TMP/argv" \
  "$LAUNCHER" --page sessions \
  >"$TMP/build.out" 2>&1
assert_args $'--page\nsessions'
grep -Fq 'building codexbar-gtk-native (debug)' "$TMP/build.out" || fail "build path was not announced"

# Missing build tool fails with actionable guidance rather than a shell error.
if env PATH="/usr/bin:/bin" CODEXBAR_NATIVE_NO_BUILD=0 \
  CARGO_TARGET_DIR="$TMP/empty-target" "$LAUNCHER" >"$TMP/no-cargo.out" 2>&1; then
  fail "missing-Cargo invocation unexpectedly succeeded"
fi
grep -Fq 'cargo is required to build codexbar-gtk-native' "$TMP/no-cargo.out" || fail "missing-Cargo error is unclear"

echo "PASS: native launcher binary selection, build fallback, argv forwarding and fail-closed errors"
