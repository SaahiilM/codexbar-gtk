#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

if [[ "${CODEXBAR_NATIVE_SMOKE_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_SMOKE_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication gdbus timeout xwininfo xprop; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done
if [[ -n "${NATIVE_GTK_TRAY_PANEL_SCREENSHOT:-}${NATIVE_GTK_TRAY_DASHBOARD_SCREENSHOT:-}" ]]; then
    for tool in xwd ffmpeg; do
        command -v "$tool" >/dev/null || { echo "missing screenshot dependency: $tool" >&2; exit 2; }
    done
fi
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
cleanup() {
    if [[ -n "${app_pid:-}" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [[ "${NATIVE_GTK_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic native GTK smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
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
    usage)
        printf '%s\n' '[{"provider":"codex","source":"synthetic","pace":{"primary":{"stage":"slightlyAhead","deltaPercent":18}},"usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":42,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":31,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080}}}]'
        ;;
    cost|sessions) printf '[]\n' ;;
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

capture_window() {
    local window_id=$1 output=$2
    [[ -n "$output" ]] || return 0
    mkdir -p "$(dirname "$output")"
    xdotool windowsize "$window_id" 1120 820
    sleep 0.3
    xwd -silent -id "$window_id" -out "$scratch/tray-window.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/tray-window.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "native tray runtime screenshot is empty: $output" >&2; exit 1; }
}

wait_for_tray_name() {
    local deadline=$((SECONDS + 8))
    while (( SECONDS < deadline )); do
        if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk 2>/dev/null \
            | grep -q '(true,)'; then
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/primary.log" >&2
    echo "native StatusNotifierItem name was not acquired" >&2
    exit 1
}

tray_menu_event() {
    local id=$1
    gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /MenuBar \
        --method com.canonical.dbusmenu.Event "$id" clicked "<''>" 0 >/dev/null
}

assert_panel_bottom_right() {
    local window_id=$1 panel_info root_info panel_x panel_y panel_width panel_height root_width root_height
    local area_x area_y area_width area_height expected_x expected_y dx dy deadline
    deadline=$((SECONDS + 5))
    while (( SECONDS < deadline )); do
        panel_info=$(xwininfo -id "$window_id")
        root_info=$(xwininfo -root)
        panel_x=$(sed -n 's/^[[:space:]]*Absolute upper-left X:[[:space:]]*//p' <<<"$panel_info")
        panel_y=$(sed -n 's/^[[:space:]]*Absolute upper-left Y:[[:space:]]*//p' <<<"$panel_info")
        panel_width=$(sed -n 's/^[[:space:]]*Width:[[:space:]]*//p' <<<"$panel_info")
        panel_height=$(sed -n 's/^[[:space:]]*Height:[[:space:]]*//p' <<<"$panel_info")
        root_width=$(sed -n 's/^[[:space:]]*Width:[[:space:]]*//p' <<<"$root_info")
        root_height=$(sed -n 's/^[[:space:]]*Height:[[:space:]]*//p' <<<"$root_info")
        read -r area_x area_y area_width area_height < <(xprop -root _NET_WORKAREA 2>/dev/null | sed -n 's/.*= //p' | tr ',' ' ') || true
        if [[ -z "${area_width:-}" || -z "${area_height:-}" ]]; then
            area_x=0 area_y=0 area_width=$root_width area_height=$root_height
        fi
        expected_x=$((area_x + area_width - panel_width - 12))
        expected_y=$((area_y + area_height - panel_height - 12))
        dx=$((panel_x - expected_x)); (( dx < 0 )) && dx=$((-dx))
        dy=$((panel_y - expected_y)); (( dy < 0 )) && dy=$((-dy))
        (( dx <= 2 && dy <= 2 )) && return 0
        sleep 0.05
    done
    echo "panel placement mismatch: got ($panel_x,$panel_y), expected bottom-right ($expected_x,$expected_y)" >&2
    exit 1
}

# The primary instance exercises an invalid --page value. The legacy stack
# leaves Usage selected instead of failing the process.
"$binary" --page not-a-page >"$scratch/primary.log" 2>&1 &
app_pid=$!
assert_title_contains '^CodexBar GTK' "Usage"
wait_for_tray_name
tray_introspection=$(gdbus introspect --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem)
grep -q 'Scroll' <<<"$tray_introspection" || { echo "native SNI Scroll method was not exported" >&2; exit 1; }
menu_layout=$(gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /MenuBar \
    --method com.canonical.dbusmenu.GetLayout 0 1 '@as []')
grep -q 'About CodexBar GTK' <<<"$menu_layout" || { echo "native dbusmenu About action was not exported" >&2; exit 1; }
gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem \
    --method org.kde.StatusNotifierItem.Activate 31 47 >/dev/null
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
panel_window=$(xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' | head -n 1)
assert_panel_bottom_right "$panel_window"
capture_window "$panel_window" "${NATIVE_GTK_TRAY_PANEL_SCREENSHOT:-}"
xdotool windowfocus "$panel_window"
xdotool key --window "$panel_window" Escape
deadline=$((SECONDS + 5))
while xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1 && (( SECONDS < deadline )); do sleep 0.05; done
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "SNI activation panel did not dismiss with Escape" >&2
    exit 1
fi
tray_menu_event 3
assert_title_contains '^CodexBar GTK' "Dashboard"
dashboard_window=$(xdotool search --onlyvisible --name '^CodexBar GTK' | head -n 1)
capture_window "$dashboard_window" "${NATIVE_GTK_TRAY_DASHBOARD_SCREENSHOT:-}"
tray_menu_event 7
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
tray_menu_event 8
assert_title_contains '^About CodexBar GTK' "About CodexBar GTK"
tray_menu_event 2
deadline=$((SECONDS + 8))
while [[ $(grep -c '^usage$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -lt 2 ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ $(grep -c '^usage$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 2 ]] || {
    cat "$scratch/primary.log" >&2
    echo "dbusmenu Refresh did not reach the synthetic CLI" >&2
    exit 1
}

# Secondary processes are forwarded through Gio to that same primary app.
"$binary" --page sessions
assert_title_contains '^CodexBar GTK' "Sessions"
"$binary" --page spend --panel --about --settings
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
"$binary" --about
assert_title_contains '^About CodexBar GTK' "About CodexBar GTK"
"$binary" --panel
# Settings remains visible as a separate preferences window; match the panel
# itself instead of accepting whichever application window xdotool finds first.
assert_title_contains 'CodexBar GTK.*Panel' "Panel"

sleep 0.3
version_calls=$(grep -c '^--version$' "$NATIVE_CLI_LOG" || true)
[[ "$version_calls" == "3" ]] || {
    echo "expected one controller and two tray/secondary Settings CLI-version queries; saw $version_calls version calls" >&2
    exit 1
}
tray_menu_event 10
wait "$app_pid"
app_pid=
if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk \
    | grep -q '(true,)'; then
    echo "native tray bus name remained owned after application shutdown" >&2
    exit 1
fi

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
gapplication action com.steipete.CodexBarGTK panel
"$binary" --settings
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
: > "$NATIVE_USAGE_RELEASE"
deadline=$((SECONDS + 12))
while [[ ! -e "$NATIVE_USAGE_FINISHED" ]] && (( SECONDS < deadline )); do sleep 0.05; done
[[ -e "$NATIVE_USAGE_FINISHED" ]] || {
    echo "synthetic CLI did not finish after release" >&2
    exit 1
}
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "pending panel toggle did not cancel the open request" >&2
    exit 1
fi
"$binary" --panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"

# The compact panel is a separate window. Escape, toggle, central page and
# Settings/About actions all close it without changing their application APIs.
panel_window=$(xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' | head -n 1)
[[ -n "$panel_window" ]] || { echo "native panel window was not visible" >&2; exit 1; }
assert_panel_bottom_right "$panel_window"
xdotool windowfocus "$panel_window"
xdotool key --window "$panel_window" Escape
deadline=$((SECONDS + 5))
while xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1 && (( SECONDS < deadline )); do sleep 0.05; done
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "Escape did not dismiss the native panel" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK page "'sessions'"
assert_title_contains '^CodexBar GTK' "Sessions"
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "page navigation left the native panel visible" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK settings
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "Settings navigation left the native panel visible" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK about
assert_title_contains '^About CodexBar GTK' "About CodexBar GTK"
if xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' >/dev/null 2>&1; then
    echo "About navigation left the native panel visible" >&2
    exit 1
fi

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
