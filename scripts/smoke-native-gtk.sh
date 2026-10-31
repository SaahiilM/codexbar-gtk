#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

if [[ "${CODEXBAR_NATIVE_SMOKE_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_SMOKE_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication timeout; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
cleanup() {
    if [[ -n "${app_pid:-}" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT

mkdir -p "$scratch/home" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
printf '%s\n' "$1" >> "$NATIVE_CLI_LOG"
if [ "$1" = usage ] && [ "${NATIVE_DELAY_USAGE:-0}" = 1 ]; then
    : > "$NATIVE_USAGE_STARTED"
    sleep 10
fi
if [ "$1" = usage ] && [ "${NATIVE_WAIT_FOR_RELEASE:-0}" = 1 ]; then
    : > "$NATIVE_USAGE_STARTED"
    while [ ! -e "$NATIVE_USAGE_RELEASE" ]; do sleep 0.02; done
fi
if [ "$1" = usage ] && [ -n "${NATIVE_USAGE_FINISHED:-}" ]; then
    : > "$NATIVE_USAGE_FINISHED"
fi
case "$1" in
    --version) printf 'CodexBar synthetic fixture 0.82.0\n' ;;
    usage|cost|sessions) printf '[]\n' ;;
    *) printf '[]\n' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

export HOME="$scratch/home"
export XDG_RUNTIME_DIR="$scratch/runtime"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_CLI_LOG="$scratch/cli-calls"
export GTK_A11Y=none
export GTK_USE_PORTAL=0
export GDK_BACKEND=x11
export GSK_RENDERER=cairo

window_title() {
    local pattern=$1
    local deadline=$((SECONDS + 12))
    while (( SECONDS < deadline )); do
        local window
        window=$(xdotool search --onlyvisible --name "$pattern" 2>/dev/null | head -n 1 || true)
        if [[ -n "$window" ]]; then
            xdotool getwindowname "$window"
            return 0
        fi
        sleep 0.1
    done
    echo "timed out waiting for native window matching: $pattern" >&2
    return 1
}

assert_title_contains() {
    local pattern=$1 expected=$2 actual
    actual=$(window_title "$pattern")
    [[ "$actual" == *"$expected"* ]] || {
        echo "expected window title containing '$expected', got '$actual'" >&2
        exit 1
    }
}

# The primary instance exercises an invalid --page value. The legacy stack
# leaves Usage selected instead of failing the process.
"$binary" --page not-a-page >"$scratch/primary.log" 2>&1 &
app_pid=$!
assert_title_contains '^CodexBar GTK' "Usage"

# Secondary processes are forwarded through Gio to that same primary app.
"$binary" --page sessions
assert_title_contains '^CodexBar GTK' "Sessions"
"$binary" --page spend --panel --about --settings
assert_title_contains '^CodexBar GTK' "Settings"
"$binary" --about
assert_title_contains '^About CodexBar GTK' "About CodexBar GTK"
"$binary" --panel
assert_title_contains '^CodexBar GTK' "Panel"

sleep 0.3
version_calls=$(grep -c '^--version$' "$NATIVE_CLI_LOG" || true)
[[ "$version_calls" == "1" ]] || {
    echo "expected one backend controller across primary/secondary processes; saw $version_calls version calls" >&2
    exit 1
}
gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=

# `--panel` remains hidden until the first refresh completes. A second process
# can still route settings while that CLI operation is in flight, proving GTK
# is not waiting synchronously on backend work.
export NATIVE_WAIT_FOR_RELEASE=1
export NATIVE_USAGE_STARTED="$scratch/panel-usage-started"
export NATIVE_USAGE_FINISHED="$scratch/panel-usage-finished"
export NATIVE_USAGE_RELEASE="$scratch/release-panel-usage"
: > "$NATIVE_CLI_LOG"
"$binary" --panel >"$scratch/panel.log" 2>&1 &
app_pid=$!
deadline=$((SECONDS + 12))
while [[ ! -e "$NATIVE_USAGE_STARTED" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ -e "$NATIVE_USAGE_STARTED" ]] || {
    echo "panel fixture did not enter its delayed first refresh" >&2
    exit 1
}
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "panel appeared before the first refresh completed" >&2
    exit 1
fi
"$binary" --settings
assert_title_contains '^CodexBar GTK' "Settings"
: > "$NATIVE_USAGE_RELEASE"
deadline=$((SECONDS + 12))
while [[ ! -e "$NATIVE_USAGE_FINISHED" ]] && (( SECONDS < deadline )); do sleep 0.05; done
[[ -e "$NATIVE_USAGE_FINISHED" ]] || {
    echo "synthetic CLI did not finish after release" >&2
    exit 1
}
"$binary" --panel
assert_title_contains '^CodexBar GTK' "Panel"
gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=

# Start a fresh primary against a delayed fixture command, then quit from a
# secondary Gio action while that backend process is in flight. The worker
# must cancel and join it without blocking the GTK main context.
unset NATIVE_WAIT_FOR_RELEASE
unset NATIVE_USAGE_FINISHED
export NATIVE_DELAY_USAGE=1
export NATIVE_USAGE_STARTED="$scratch/usage-started"
: > "$NATIVE_CLI_LOG"
"$binary" --page usage >"$scratch/inflight.log" 2>&1 &
app_pid=$!
deadline=$((SECONDS + 12))
while [[ ! -e "$NATIVE_USAGE_STARTED" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ -e "$NATIVE_USAGE_STARTED" ]] || {
    echo "synthetic CLI did not reach the in-flight usage command" >&2
    exit 1
}
gapplication action com.steipete.CodexBarGTK quit
timeout 4 bash -c '
    process=$1
    while [[ -r "/proc/$process/stat" ]]; do
        state=$(awk "{print \$3}" "/proc/$process/stat")
        [[ "$state" == Z* ]] && exit 0
        sleep 0.05
    done
' _ "$app_pid"
wait "$app_pid"
app_pid=

printf 'native GTK command-line and cancellation smoke passed\n'
