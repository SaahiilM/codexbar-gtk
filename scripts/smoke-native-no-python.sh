#!/usr/bin/env bash
# C02 — absent-Python runtime proof (single validated Docker path).
# PASS requires observed runtime evidence: NameHasOwner + correct PID +
# exe/hash match + CLI log delta + settings/about windows + quit exit 0.
# Missing Docker -> SKIP exit 2. Any check failing -> FAIL exit 1.
# Dry-run is never PASS. TERM/KILL is failure cleanup only.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${CODEXBAR_GTK:-$SCRIPT_DIR/..}" && pwd)"
APP_ID="com.steipete.CodexBarGTK"
BIN_NAME="codexbar-gtk-native"
ARTIFACT="${ARTIFACT:-}"
TIMEOUT="${TIMEOUT:-30}"
EVIDENCE_DIR="${SMOKE_EVIDENCE:-}"
DOCKER_IMAGE="${DOCKER_IMAGE:-codexbar-no-python:smoke}"
KEEP=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --artifact) ARTIFACT="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    --evidence-dir) EVIDENCE_DIR="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 3;;
  esac
done
pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*"; FAILS=$((FAILS+1)); }
note() { echo "[info] $*"; }
FAILS=0
resolve_artifact() {
  if [ -n "$ARTIFACT" ]; then
    if [ -x "$ARTIFACT" ] && [ -f "$ARTIFACT" ]; then return 0; fi
    echo "artifact not executable: $ARTIFACT" >&2; exit 3
  fi
  for c in "$REPO_ROOT/rust-gtk/target/release/$BIN_NAME" "$REPO_ROOT/rust-gtk/target/debug/$BIN_NAME"; do
    if [ -x "$c" ]; then ARTIFACT="$c"; return 0; fi
  done
  echo "SKIP: no native artifact found (use --artifact PATH)" >&2; exit 2
}
resolve_artifact
EVIDENCE_DIR="${EVIDENCE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/smoke-no-python.XXXXXX")}"
mkdir -p "$EVIDENCE_DIR"
WORK="$EVIDENCE_DIR/work"
mkdir -p "$WORK/home/.config/codexbar-gtk" "$WORK/home/.local/bin"
HOME_DIR="$WORK/home"
LOGFILE="$EVIDENCE_DIR/run.log"
exec > >(tee "$LOGFILE") 2>&1
note "evidence dir: $EVIDENCE_DIR"
note "artifact: $ARTIFACT"
cat > "$HOME_DIR/.local/bin/codexbar" <<'EOF'
#!/bin/sh
echo "$@" >> /work/home/cli.log 2>/dev/null || true
printf '{"ok":true,"providers":[]}\n'
exit 0
EOF
chmod +x "$HOME_DIR/.local/bin/codexbar"
printf '%s' '{"preferredCurrencyCode":"auto","refreshIntervalSeconds":300}' > "$HOME_DIR/.config/codexbar-gtk/settings.json"
chmod 600 "$HOME_DIR/.config/codexbar-gtk/settings.json"
printf '%s\n' '{"ts":"2026-11-06T00:00:00Z","provider":"synthetic","usage":0,"cost":0}' > "$HOME_DIR/.config/codexbar-gtk/history.jsonl"
EXPECTED_SHA="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
note "expected sha256: $EXPECTED_SHA"
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "RESULT: SKIP — docker unavailable. C02 NOT passed." | tee "$EVIDENCE_DIR/result.txt"; exit 2
fi
if [ $DRY -eq 1 ]; then
  echo "RESULT: SKIP — dry-run never PASS (would launch $BIN_NAME in $DOCKER_IMAGE network=none). C02 NOT passed." | tee "$EVIDENCE_DIR/result.txt"; exit 2
fi
note "--- docker build ---"
DOCKERFILE="$REPO_ROOT/scripts/native/no-python/docker/Dockerfile.runtime"
if ! docker build -t "$DOCKER_IMAGE" -f "$DOCKERFILE" "$REPO_ROOT" >"$WORK/docker-build.log" 2>&1; then
  cat "$WORK/docker-build.log"; echo "RESULT: FAIL — image build failed. C02 NOT passed." | tee "$EVIDENCE_DIR/result.txt"; exit 1
fi
pass "image built $DOCKER_IMAGE"
docker images --digests 2>/dev/null | grep codexbar-no-python >"$WORK/image-digest.txt" || true
cat "$WORK/image-digest.txt" || true
note "--- docker run ---"
bash "$REPO_ROOT/scripts/native/no-python/docker/run-container.sh" "$ARTIFACT" "$WORK" "$EXPECTED_SHA" >"$WORK/container.log" 2>&1
RUN_RC=$?
if [ "$RUN_RC" -ne 0 ]; then fail "container runner exited with status $RUN_RC"; fi
cat "$WORK/container.log"
EVIDENCE="$(grep '^EVIDENCE:' "$WORK/container.log" | sed 's/^EVIDENCE://' || true)"
CONTAINER_NAME="$(echo "$EVIDENCE" | grep -E '^container-name=' | head -1 | cut -d= -f2-)"
if [ -n "$CONTAINER_NAME" ]; then
  docker logs "$CONTAINER_NAME" >"$WORK/container-logs.txt" 2>&1 || true
  docker inspect "$CONTAINER_NAME" >"$WORK/container-inspect.json" 2>&1 || true
  echo "--- container inspect (actual ID, network none, image digest) ---"
  grep -E '"Id"|"Image"|"NetworkMode"' "$WORK/container-inspect.json" | head -10 || true
fi
get_ev() { echo "$EVIDENCE" | grep -E "^$1=" | head -1 | cut -d= -f2-; }
NHO="$(get_ev namehasowner)"; note "NameHasOwner: $NHO"
if printf '%s' "$NHO" | grep -q '(true,)'; then pass "NameHasOwner $APP_ID true"; else fail "NameHasOwner not true: $NHO"; fi
UNIX_PID="$(get_ev unix-pid)"; note "unix-pid: $UNIX_PID"
if printf '%s' "$UNIX_PID" | grep -qE '^[0-9]+$' && [ "$UNIX_PID" != "0" ] && [ -n "$UNIX_PID" ]; then pass "PID parsed as uint32: $UNIX_PID"; else fail "PID parse failed: '$UNIX_PID'"; fi
APP_PID="$(get_ev app-pid)"
if [ -n "$APP_PID" ] && [ "$UNIX_PID" = "$APP_PID" ]; then pass "D-Bus owner is the launched app"; else fail "D-Bus owner $UNIX_PID differs from launched app $APP_PID"; fi
EXE="$(get_ev exe)"; EXESHA="$(get_ev exe-sha)"; note "exe=$EXE sha=$EXESHA"
if [ "$EXE" = "/app/$BIN_NAME" ]; then pass "exe matches /app artifact"; else fail "exe mismatch: $EXE"; fi
if [ "$EXESHA" = "$EXPECTED_SHA" ] && [ -n "$EXESHA" ]; then pass "exe sha256 matches expected"; else fail "exe sha mismatch: $EXESHA != $EXPECTED_SHA"; fi
for k in maps-libpython maps-pyo3 maps-rustcore; do
  v="$(get_ev $k)"; note "$k=$v"
  if [ "$v" = "0" ]; then pass "$k absent on app PID"; else fail "$k=$v (must be 0)"; fi
done
for p in /usr/bin/python3 /usr/bin/python /usr/local/bin/python3; do
  if echo "$EVIDENCE" | grep -q "^python-absent=$p"; then pass "python absent at $p"; else fail "python present at $p"; fi
done
if echo "$EVIDENCE" | grep -q '^python-libdir-absent'; then pass "python libdir absent"; else fail "python libdir present"; fi
if echo "$EVIDENCE" | grep -q '^libpython-absent'; then pass "libpython absent"; else fail "libpython present"; fi
SVG="$(get_ev svg-loader)"; note "svg-loader: $SVG"
if printf '%s' "$SVG" | grep -q 'libpixbufloader-svg.so'; then note "SVG loader present (loader presence alone is not decode proof; decode is in-process via librsvg2)"; else fail "SVG loader missing"; fi
B="$(get_ev cli-before)"; A="$(get_ev cli-after)"; note "cli before=$B after=$A"
if [ -n "$B" ] && [ -n "$A" ] && [ "$A" -gt "$B" ] 2>/dev/null; then pass "Gio refresh increased CLI calls $B -> $A"; else fail "CLI calls did not increase: $B -> $A"; fi
if [ -f "$WORK/home/cli.log" ]; then cp "$WORK/home/cli.log" "$EVIDENCE_DIR/cli.log"; note "--- cli.log ---"; cat "$EVIDENCE_DIR/cli.log"; else fail "cli.log missing"; fi
if echo "$EVIDENCE" | grep -q '^settings-window=FOUND'; then pass "settings window evidenced"; else fail "settings window missing"; fi
if echo "$EVIDENCE" | grep -q '^about-window=FOUND'; then pass "about window evidenced"; else fail "about window missing"; fi
EXIT="$(get_ev app-exit)"; note "app-exit: $EXIT"
if [ "$EXIT" = "0" ]; then pass "Gio quit exit 0 within deadline"; else fail "quit exit != 0: $EXIT"; fi
if [ -f "$WORK/container-inspect.json" ]; then
  if grep -q '"NetworkMode": "none"' "$WORK/container-inspect.json"; then pass "container network=none"; else fail "container network != none"; fi
else fail "container inspect missing"; fi
if [ -n "$CONTAINER_NAME" ] && [ $KEEP -ne 1 ]; then
  docker stop -t 10 "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi
if [ $FAILS -gt 0 ]; then
  echo "RESULT: FAIL ($FAILS failing checks). C02 NOT passed." | tee "$EVIDENCE_DIR/result.txt"; exit 1
fi
echo "RESULT: PASS (runtime evidence observed; see run.log). C02 checked pending root acceptance." | tee "$EVIDENCE_DIR/result.txt"
note "evidence: $EVIDENCE_DIR"
exit $RUN_RC
