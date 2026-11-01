#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
if [[ "${CODEXBAR_NATIVE_USAGE_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_USAGE_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication timeout; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

native_usage_tmp=$(mktemp -d)
chmod 700 "$native_usage_tmp"
cleanup() {
    if [[ -n "${native_usage_app_pid:-}" ]] && kill -0 "$native_usage_app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        kill "$native_usage_app_pid" 2>/dev/null || true
        wait "$native_usage_app_pid" 2>/dev/null || true
    fi
    rm -rf "$native_usage_tmp"
}
trap cleanup EXIT

mkdir -p "$native_usage_tmp/runtime" "$native_usage_tmp/config" "$native_usage_tmp/data" "$native_usage_tmp/cache"
chmod 700 "$native_usage_tmp/runtime"
native_usage_today=$(date -u +%Y-%m-%d)
native_usage_yesterday=$(date -u -d 'yesterday' +%Y-%m-%d)

cat > "$native_usage_tmp/fake-codexbar" <<'CLI'
#!/bin/sh
set -eu
case "${1-}" in
  --version)
    printf '%s\n' 'CodexBar synthetic fixture 0.82.0'
    : > "$NATIVE_USAGE_VERSION_DONE"
    ;;
  usage)
    printf '%s\n' '[]'
    : > "$NATIVE_USAGE_USAGE_DONE"
    ;;
  cost)
    if [ -e "$NATIVE_USAGE_FAIL_COST" ]; then
      : > "$NATIVE_USAGE_COST_FAILURE_DONE"
      exit 1
    fi
    if [ -e "$NATIVE_USAGE_EMPTY_COST" ]; then
      printf '%s\n' '[]'
      : > "$NATIVE_USAGE_COST_DONE"
      exit 0
    fi
    printf '[{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{"priced":3,"unpriced":1},"historyCoverageIsEstablished":false,"provenance":"synthetic_history","daily":[{"date":"%s","totalCost":3.25,"totalTokens":800},{"date":"%s","totalCost":1.5,"totalTokens":null},{"date":"%s","totalCost":0,"totalTokens":0}],"projects":[{"name":"Synthetic Workspace","totalCost":12.5,"totalTokens":1200}],"models":[{"name":"Synthetic Model","cost":12.5,"totalTokens":1200}]},{"provider":"claude","currencyCode":"USD","totalCost":6.25,"totalTokens":400,"sessionCostUSD":0.5,"sessionTokens":40,"daily":[{"date":"%s","totalCost":2.0,"totalTokens":350}]}]\n' \
      "$NATIVE_USAGE_TODAY" "$NATIVE_USAGE_TODAY" "$NATIVE_USAGE_YESTERDAY" "$NATIVE_USAGE_TODAY"
    : > "$NATIVE_USAGE_COST_DONE"
    ;;
  sessions)
    if [ -e "$NATIVE_USAGE_FAIL_SESSIONS" ]; then
      : > "$NATIVE_USAGE_SESSION_FAILURE_DONE"
      exit 1
    fi
    if [ -e "$NATIVE_USAGE_DELAY_SESSIONS" ] && [ ! -e "$NATIVE_USAGE_RELEASE_SESSIONS" ]; then
      : > "$NATIVE_USAGE_SESSION_STARTED"
      while [ ! -e "$NATIVE_USAGE_RELEASE_SESSIONS" ]; do sleep 0.03; done
    fi
    if [ -e "$NATIVE_USAGE_EMPTY_SESSIONS" ]; then
      printf '%s\n' '[]'
      : > "$NATIVE_USAGE_SESSION_DONE"
      exit 0
    fi
    printf '%s\n' '[{"id":"synthetic-running","provider":"codex","state":"running","projectName":"Synthetic Workspace","cwd":"/tmp/synthetic-workspace","pid":81,"startedAt":"2026-10-31T09:00:00Z","lastActivityAt":"2026-10-31T09:30:00Z","host":"fixture"},{"id":"synthetic-recent","provider":"claude","state":"completed","projectName":"Synthetic Notes","cwd":"/tmp/synthetic-notes","pid":82,"startedAt":"2026-10-30T09:00:00Z","lastActivityAt":"2026-10-30T09:20:00Z","host":"fixture"}]'
    : > "$NATIVE_USAGE_SESSION_DONE"
    ;;
  *) printf '%s\n' '[]' ;;
esac
CLI
chmod 700 "$native_usage_tmp/fake-codexbar"

export XDG_RUNTIME_DIR="$native_usage_tmp/runtime"
export XDG_CONFIG_HOME="$native_usage_tmp/config"
export XDG_DATA_HOME="$native_usage_tmp/data"
export XDG_CACHE_HOME="$native_usage_tmp/cache"
export CODEXBAR_CLI="$native_usage_tmp/fake-codexbar"
export NATIVE_USAGE_TODAY="$native_usage_today"
export NATIVE_USAGE_YESTERDAY="$native_usage_yesterday"
export NATIVE_USAGE_USAGE_DONE="$native_usage_tmp/usage-done"
export NATIVE_USAGE_COST_DONE="$native_usage_tmp/cost-done"
export NATIVE_USAGE_SESSION_DONE="$native_usage_tmp/session-done"
export NATIVE_USAGE_VERSION_DONE="$native_usage_tmp/version-done"
export NATIVE_USAGE_SESSION_STARTED="$native_usage_tmp/session-started"
export NATIVE_USAGE_DELAY_SESSIONS="$native_usage_tmp/delay-sessions"
export NATIVE_USAGE_RELEASE_SESSIONS="$native_usage_tmp/release-sessions"
export NATIVE_USAGE_FAIL_COST="$native_usage_tmp/fail-cost"
export NATIVE_USAGE_FAIL_SESSIONS="$native_usage_tmp/fail-sessions"
export NATIVE_USAGE_EMPTY_COST="$native_usage_tmp/empty-cost"
export NATIVE_USAGE_EMPTY_SESSIONS="$native_usage_tmp/empty-sessions"
export NATIVE_USAGE_COST_FAILURE_DONE="$native_usage_tmp/cost-failure-done"
export NATIVE_USAGE_SESSION_FAILURE_DONE="$native_usage_tmp/session-failure-done"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=x11 GSK_RENDERER=cairo
touch "$NATIVE_USAGE_DELAY_SESSIONS"

"$binary" --page spend >"$native_usage_tmp/app.log" 2>&1 &
native_usage_app_pid=$!

wait_file() {
    local file=$1 deadline=$((SECONDS + 15))
    while [[ ! -e "$file" ]] && (( SECONDS < deadline )); do sleep 0.05; done
    [[ -e "$file" ]] || { cat "$native_usage_tmp/app.log" >&2; echo "timed out waiting for fixture: $file" >&2; exit 1; }
}

window_for() {
    local pattern=$1 deadline=$((SECONDS + 12)) window=""
    while [[ -z "$window" ]] && (( SECONDS < deadline )); do
        window=$(xdotool search --onlyvisible --name "$pattern" 2>/dev/null | head -n 1 || true)
        [[ -n "$window" ]] || sleep 0.05
    done
    [[ -n "$window" ]] || { cat "$native_usage_tmp/app.log" >&2; echo "native window not found: $pattern" >&2; exit 1; }
    printf '%s\n' "$window"
}

assert_window() {
    local pattern=$1 expected=$2 window actual
    window=$(window_for "$pattern")
    actual=$(xdotool getwindowname "$window")
    [[ "$actual" == *"$expected"* ]] || { echo "expected '$expected' in window title, got '$actual'" >&2; exit 1; }
}

capture_window() {
    local window=$1 output=$2
    [[ -n "$output" ]] || return 0
    command -v xwd >/dev/null || { echo "missing screenshot dependency: xwd" >&2; exit 2; }
    command -v ffmpeg >/dev/null || { echo "missing screenshot dependency: ffmpeg" >&2; exit 2; }
    mkdir -p "$(dirname "$output")"
    xdotool windowsize "$window" 1080 820
    sleep 0.25
    xwd -silent -id "$window" -out "$native_usage_tmp/page.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$native_usage_tmp/page.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "native screenshot is empty: $output" >&2; exit 1; }
}

wait_file "$NATIVE_USAGE_USAGE_DONE"
wait_file "$NATIVE_USAGE_COST_DONE"
wait_file "$NATIVE_USAGE_SESSION_STARTED"
spend_window=$(window_for 'CodexBar GTK.*Usage & Spend')
capture_window "$spend_window" "${NATIVE_USAGE_LOADING_SCREENSHOT:-}"
gapplication action com.steipete.CodexBarGTK page "'sessions'"
assert_window 'CodexBar GTK.*Sessions' "Sessions"
sessions_window=$(window_for 'CodexBar GTK.*Sessions')
capture_window "$sessions_window" "${NATIVE_USAGE_SESSIONS_LOADING_SCREENSHOT:-}"
touch "$NATIVE_USAGE_RELEASE_SESSIONS"
wait_file "$NATIVE_USAGE_SESSION_DONE"
wait_file "$NATIVE_USAGE_VERSION_DONE"
sleep 0.4
sessions_window=$(window_for 'CodexBar GTK.*Sessions')
capture_window "$sessions_window" "${NATIVE_USAGE_SESSIONS_SUCCESS_SCREENSHOT:-}"
gapplication action com.steipete.CodexBarGTK page "'spend'"
assert_window 'CodexBar GTK.*Usage & Spend' "Usage & Spend"
sleep 0.25
spend_window=$(window_for 'CodexBar GTK.*Usage & Spend')
capture_window "$spend_window" "${NATIVE_USAGE_SUCCESS_SCREENSHOT:-}"
today_epoch=$(date -u -d "$NATIVE_USAGE_TODAY" +%s)
first_visible_epoch=$((today_epoch - 364 * 86400))
first_weekday=$(date -u -d "@$first_visible_epoch" +%w)
grid_start_epoch=$((first_visible_epoch - first_weekday * 86400))
today_index=$(((today_epoch - grid_start_epoch) / 86400))
heatmap_x=$((54 + (today_index / 7) * 15 + 5))
heatmap_y=$((481 + (today_index % 7) * 15 + 5))
xdotool mousemove --window "$spend_window" "$heatmap_x" "$heatmap_y"
sleep 0.4
capture_window "$spend_window" "${NATIVE_USAGE_TOOLTIP_SCREENSHOT:-}"
xdotool windowfocus --sync "$spend_window"
for _ in $(seq 1 14); do xdotool key Tab; done
xdotool key Right
assert_window 'CodexBar GTK.*Usage & Spend' "Usage & Spend"
gapplication action com.steipete.CodexBarGTK spend-range "'7 days'"
assert_window 'CodexBar GTK.*Usage & Spend' "Usage & Spend"

# Page routing remains on Gio's central app.page action.
gapplication action com.steipete.CodexBarGTK page "'sessions'"
assert_window 'CodexBar GTK.*Sessions' "Sessions"
touch "$NATIVE_USAGE_FAIL_COST" "$NATIVE_USAGE_FAIL_SESSIONS"
rm -f "$NATIVE_USAGE_COST_FAILURE_DONE" "$NATIVE_USAGE_SESSION_FAILURE_DONE"
gapplication action com.steipete.CodexBarGTK refresh
wait_file "$NATIVE_USAGE_COST_FAILURE_DONE"
wait_file "$NATIVE_USAGE_SESSION_FAILURE_DONE"
sleep 0.4
sessions_window=$(window_for 'CodexBar GTK.*Sessions')
capture_window "$sessions_window" "${NATIVE_USAGE_SESSIONS_FAILURE_SCREENSHOT:-}"

gapplication action com.steipete.CodexBarGTK page "'spend'"
assert_window 'CodexBar GTK.*Usage & Spend' "Usage & Spend"
sleep 0.25
spend_window=$(window_for 'CodexBar GTK.*Usage & Spend')
capture_window "$spend_window" "${NATIVE_USAGE_PARTIAL_SCREENSHOT:-}"

rm -f "$NATIVE_USAGE_FAIL_SESSIONS"
touch "$NATIVE_USAGE_EMPTY_SESSIONS"
rm -f "$NATIVE_USAGE_SESSION_DONE"
gapplication action com.steipete.CodexBarGTK refresh
wait_file "$NATIVE_USAGE_SESSION_DONE"
sleep 0.4
gapplication action com.steipete.CodexBarGTK page "'sessions'"
assert_window 'CodexBar GTK.*Sessions' "Sessions"
sessions_window=$(window_for 'CodexBar GTK.*Sessions')
capture_window "$sessions_window" "${NATIVE_USAGE_SESSIONS_EMPTY_SCREENSHOT:-}"

rm -f "$NATIVE_USAGE_FAIL_COST"
touch "$NATIVE_USAGE_EMPTY_COST"
rm -f "$NATIVE_USAGE_COST_DONE"
gapplication action com.steipete.CodexBarGTK refresh
wait_file "$NATIVE_USAGE_COST_DONE"
sleep 0.4
gapplication action com.steipete.CodexBarGTK page "'spend'"
assert_window 'CodexBar GTK.*Usage & Spend' "Usage & Spend"
spend_window=$(window_for 'CodexBar GTK.*Usage & Spend')
capture_window "$spend_window" "${NATIVE_USAGE_EMPTY_SCREENSHOT:-}"

# The stable Settings action and the central dashboard back route stay reachable.
gapplication action com.steipete.CodexBarGTK settings
assert_window '^CodexBar Settings' "CodexBar Settings"
gapplication action com.steipete.CodexBarGTK dashboard
assert_window 'CodexBar GTK.*Dashboard' "Dashboard"
gapplication action com.steipete.CodexBarGTK quit
wait "$native_usage_app_pid"
native_usage_app_pid=
printf 'native Spend/Sessions synthetic refresh, retained-error, central-navigation and GTK lifecycle smoke passed\n'
