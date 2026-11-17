#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
fixtures=${CODEXBAR_SMOKE_FIXTURES:-"$repo_root/rust-smoke-fixtures/target/release/codexbar-smoke-fixtures"}

if [[ "${CODEXBAR_NATIVE_SMOKE_INNER:-}" != "1" ]]; then
    fixtures=$("$repo_root/scripts/build-rust-smoke-fixtures.sh")
    session_home=$(mktemp -d)
    mkdir -m 700 "$session_home/runtime"
    status=0
    printf 'GTK private bus bootstrap: time=%s HOME=%q runtime=%q (paths exported before dbus-run-session)\n' \
        "$(date +%s.%N)" "$session_home" "$session_home/runtime" >&2
    xvfb-run -a env HOME="$session_home" XDG_RUNTIME_DIR="$session_home/runtime" \
        XDG_CONFIG_HOME="$session_home/.config" XDG_DATA_HOME="$session_home/.local/share" \
        XDG_CACHE_HOME="$session_home/.cache" \
        CODEXBAR_SMOKE_PRIVATE_HOME="$session_home" CODEXBAR_SMOKE_PRIVATE_RUNTIME="$session_home/runtime" \
        CODEXBAR_SMOKE_FIXTURES="$fixtures" dbus-run-session -- env \
        CODEXBAR_NATIVE_SMOKE_INNER=1 "$0" "$binary" || status=$?
    rm -rf "$session_home"
    exit "$status"
fi

for tool in xdotool gapplication gdbus timeout xwininfo xprop; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done

xdotool_binary=$(command -v xdotool)
xdotool() {
    timeout --signal=TERM --kill-after=1s 10s "$xdotool_binary" "$@"
}
if [[ -n "${NATIVE_GTK_TRAY_PANEL_SCREENSHOT:-}${NATIVE_GTK_TRAY_DASHBOARD_SCREENSHOT:-}" ]]; then
    for tool in xwd ffmpeg; do
        command -v "$tool" >/dev/null || { echo "missing screenshot dependency: $tool" >&2; exit 2; }
    done
fi
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }
if [[ "${CODEXBAR_NATIVE_SMOKE_INNER:-}" == "1" ]] && \
    [[ "${HOME:-}" != "${CODEXBAR_SMOKE_PRIVATE_HOME:-}" || \
       "${XDG_RUNTIME_DIR:-}" != "${CODEXBAR_SMOKE_PRIVATE_RUNTIME:-}" ]]; then
    echo "GTK inner smoke requires HOME and XDG_RUNTIME_DIR to match the private paths exported before D-Bus activation" >&2
    exit 2
fi

scratch=$(mktemp -d)
chmod 700 "$scratch"
stop_owned_process() {
    local pid=$1 deadline state
    [[ -n "$pid" ]] || return 0
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        deadline=$((SECONDS + 5))
        while (( SECONDS < deadline )); do
            state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)
            [[ -z "$state" || "$state" == Z* ]] && break
            sleep 0.05
        done
        state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)
        if [[ -n "$state" && "$state" != Z* ]]; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
    wait "$pid" 2>/dev/null || true
}
cleanup() {
    if [[ -n "${app_pid:-}" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        stop_owned_process "$app_pid"
    fi
    stop_owned_process "${notification_pid:-}"
    if [[ "${NATIVE_GTK_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic native GTK smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
}
trap cleanup EXIT

runtime_root=${XDG_RUNTIME_DIR:-"$scratch/runtime"}
home_root=${HOME:-"$scratch/home"}
mkdir -p "$home_root" "$runtime_root"
chmod 700 "$runtime_root"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
printf '%s\n' "$1" >> "$NATIVE_CLI_LOG"
if [ "$1" = usage ] && [ "${NATIVE_DELAY_USAGE:-0}" = 1 ]; then
    : > "$NATIVE_USAGE_STARTED"
    if [ -n "${NATIVE_CHILD_PID_FILE:-}" ]; then
        printf '%s\n' "$$" > "$NATIVE_CHILD_PID_FILE"
        exec sleep 10
    fi
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
        printf '%s\n' '[{"provider":"codex","source":"synthetic","pace":{"primary":{"stage":"slightlyAhead","deltaPercent":18}},"usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":62,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":31,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080}}}]'
        ;;
    cost|sessions) printf '[]\n' ;;
    *) printf '[]\n' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

export HOME="$home_root"
export XDG_RUNTIME_DIR="$runtime_root"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$home_root/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$home_root/.local/share}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$home_root/.cache}"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_CLI_LOG="$scratch/cli-calls"
export NATIVE_NOTIFICATION_LOG="$scratch/notifications"
export NATIVE_TERMINAL_LOG="$scratch/terminal-argv"
export NATIVE_TERMINAL_PID="$scratch/terminal.pid"
mkdir -p "$scratch/bin"
cat > "$scratch/fake-codex" <<'CODEX'
#!/bin/sh
exit 0
CODEX
cat > "$scratch/bin/konsole" <<'TERMINAL'
#!/bin/sh
printf '%s\n' "$$" > "$NATIVE_TERMINAL_PID"
printf '%s\n' "$@" > "$NATIVE_TERMINAL_LOG"
TERMINAL
chmod 700 "$scratch/fake-codex" "$scratch/bin/konsole"
export CODEX_CLI="$scratch/fake-codex"
export PATH="$scratch/bin:$PATH"
export GTK_A11Y=none
export GTK_USE_PORTAL=0
export GDK_BACKEND=x11
export GSK_RENDERER=cairo

"$fixtures" mock-notifications "$NATIVE_NOTIFICATION_LOG" >"$scratch/notifications.log" 2>&1 &
notification_pid=$!
deadline=$((SECONDS + 8))
while ! gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.freedesktop.Notifications 2>/dev/null \
    | grep -q '(true,)' \
    && (( SECONDS < deadline )); do sleep 0.05; done
gdbus call --session --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.GetServerInformation >/dev/null || {
    cat "$scratch/notifications.log" >&2
    echo "synthetic notification service did not acquire the private bus name" >&2
    exit 1
}

app_window_ids() {
    local pattern=$1 candidate title owner map_state
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        title=$(xprop -id "$candidate" _NET_WM_NAME WM_NAME 2>/dev/null \
            | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
        [[ "$title" =~ $pattern ]] || continue
        owner=$(xprop -id "$candidate" _NET_WM_PID 2>/dev/null \
            | sed -n 's/.* = \([0-9][0-9]*\)$/\1/p')
        [[ "$owner" == "$app_pid" ]] || continue
        map_state=$(xwininfo -id "$candidate" 2>/dev/null \
            | sed -n 's/^  Map State: //p')
        [[ "$map_state" == IsViewable ]] || continue
        printf '%s\n' "$candidate"
    done < <(xwininfo -root -tree 2>/dev/null | awk '$1 ~ /^0x[[:xdigit:]]+$/ { print $1 }')
}

has_app_window() {
    [[ -n "$(app_window_ids "$1")" ]]
}

window_title() {
    local pattern=$1 deadline=$((SECONDS + 12)) window title
    while (( SECONDS < deadline )); do
        window=$(app_window_ids "$pattern" | head -n 1 || true)
        if [[ -n "$window" ]]; then
            title=$(xprop -id "$window" _NET_WM_NAME WM_NAME 2>/dev/null \
                | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
            [[ -n "$title" ]] && { printf '%s\n' "$title"; return 0; }
        fi
        sleep 0.1
    done
    echo "timed out waiting for native window matching: $pattern" >&2
    echo "visible X11 windows:" >&2
    while IFS= read -r window; do
        title=$(xprop -id "$window" _NET_WM_NAME WM_NAME 2>/dev/null \
            | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
        printf '  %s: %s\n' "$window" "$title" >&2
    done < <(xwininfo -root -tree 2>/dev/null | awk '$1 ~ /^0x[[:xdigit:]]+$/ { print $1 }')
    if [[ -f "$scratch/primary.log" ]]; then
        echo "primary native app log:" >&2
        cat "$scratch/primary.log" >&2
    fi
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

assert_private_bus_ready() {
    local address=${DBUS_SESSION_BUS_ADDRESS:-} address_fingerprint
    [[ "$address" == unix:* ]] || {
        echo "GTK smoke did not inherit a private Unix D-Bus session address" >&2
        exit 1
    }
    if ! gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.ListNames --timeout 3 >/dev/null 2>&1; then
        echo "private GTK session bus did not answer ListNames before app launch" >&2
        exit 1
    fi
    address_fingerprint=$(printf '%s' "$address" | sha256sum | cut -c1-16)
    printf 'private GTK bus live before app launch: time=%s HOME=%q runtime=%q transport=unix address_fingerprint=%s\n' \
        "$(date +%s.%N)" "$HOME" "$XDG_RUNTIME_DIR" "$address_fingerprint"
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

wait_for_app_bus_owner() {
    local deadline=$((SECONDS + 8)) launched_at app_home app_runtime app_bus_address app_bus_transport owner_pid
    local bus_address_fingerprint app_address_fingerprint
    launched_at=$(date +%s.%N)
    bus_address_fingerprint=$(printf '%s' "${DBUS_SESSION_BUS_ADDRESS:-}" | sha256sum | cut -c1-16)
    printf 'native app launch: time=%s HOME=%q runtime=%q bus_transport=%q\n' \
        "$launched_at" "$HOME" "$XDG_RUNTIME_DIR" "${DBUS_SESSION_BUS_ADDRESS%%:*}"
    [[ "${DBUS_SESSION_BUS_ADDRESS:-}" == unix:* ]] || {
        echo "native GTK smoke did not inherit a private Unix D-Bus session address" >&2
        exit 1
    }
    if ! gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.ListNames --timeout 3 >/dev/null 2>&1; then
        echo "private session bus did not answer ListNames after native app launch" >&2
        exit 1
    fi
    while (( SECONDS < deadline )); do
        if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK --timeout 3 2>/dev/null \
            | grep -q '(true,)'; then
            owner_pid=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
                --method org.freedesktop.DBus.GetConnectionUnixProcessID com.steipete.CodexBarGTK --timeout 3 \
                | sed -n 's/^(uint32 \([0-9][0-9]*\),)$/\1/p')
            [[ "$owner_pid" == "$app_pid" ]] || {
                echo "native app D-Bus owner PID mismatch (owner=$owner_pid launched=$app_pid)" >&2
                exit 1
            }
            app_home=$(tr '\0' '\n' <"/proc/$app_pid/environ" | sed -n 's/^HOME=//p' | head -n 1)
            app_runtime=$(tr '\0' '\n' <"/proc/$app_pid/environ" | sed -n 's/^XDG_RUNTIME_DIR=//p' | head -n 1)
            app_bus_address=$(tr '\0' '\n' <"/proc/$app_pid/environ" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' | head -n 1)
            app_bus_transport=${app_bus_address%%:*}
            app_address_fingerprint=$(printf '%s' "$app_bus_address" | sha256sum | cut -c1-16)
            printf 'native app bus context: HOME=%q runtime=%q bus_transport=%q private_address_fingerprint=%s\n' \
                "$app_home" "$app_runtime" "$app_bus_transport" "$app_address_fingerprint"
            [[ "$app_home" == "$HOME" ]] || {
                echo "native app HOME differs from the isolated smoke HOME" >&2
                exit 1
            }
            [[ "$app_runtime" == "$XDG_RUNTIME_DIR" ]] || {
                echo "native app XDG_RUNTIME_DIR differs from the isolated smoke runtime" >&2
                exit 1
            }
            [[ "$app_bus_transport" == unix ]] || {
                echo "native app did not inherit a private Unix D-Bus session address" >&2
                exit 1
            }
            [[ "$app_bus_address" == "$DBUS_SESSION_BUS_ADDRESS" && \
               "$app_address_fingerprint" == "$bus_address_fingerprint" ]] || {
                echo "native app D-Bus address differs from the live private session bus" >&2
                exit 1
            }
            printf 'native app D-Bus owner live: time=%s pid=%s\n' "$(date +%s.%N)" "$owner_pid"
            return 0
        fi
        if ! kill -0 "$app_pid" 2>/dev/null; then
            break
        fi
        sleep 0.05
    done
    cat "$scratch/primary.log" >&2
    echo "private session bus stayed live but the native app never acquired its application name" >&2
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
assert_private_bus_ready
"$binary" --page not-a-page >"$scratch/primary.log" 2>&1 &
app_pid=$!
wait_for_app_bus_owner
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
panel_window=$(app_window_ids 'CodexBar GTK.*Panel' | head -n 1)
assert_panel_bottom_right "$panel_window"
capture_window "$panel_window" "${NATIVE_GTK_TRAY_PANEL_SCREENSHOT:-}"
xdotool windowfocus --sync "$panel_window"
focused_window=$(printf '0x%x' "$(xdotool getwindowfocus)")
[[ "$focused_window" == "$panel_window" ]] || {
    echo "native panel did not receive focus before Escape: focused $focused_window, expected $panel_window" >&2
    exit 1
}
xdotool key Escape
deadline=$((SECONDS + 5))
while has_app_window 'CodexBar GTK.*Panel' && (( SECONDS < deadline )); do sleep 0.05; done
if has_app_window 'CodexBar GTK.*Panel'; then
    echo "SNI activation panel did not dismiss with Escape" >&2
    exit 1
fi
tray_menu_event 3
assert_title_contains '^CodexBar GTK' "Dashboard"
dashboard_window=$(app_window_ids '^CodexBar GTK' | head -n 1)
capture_window "$dashboard_window" "${NATIVE_GTK_TRAY_DASHBOARD_SCREENSHOT:-}"
tray_menu_event 7
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
gapplication action com.steipete.CodexBarGTK login-terminal
deadline=$((SECONDS + 8))
while [[ ! -s "$NATIVE_TERMINAL_LOG" ]] && (( SECONDS < deadline )); do sleep 0.05; done
[[ -s "$NATIVE_TERMINAL_LOG" ]] || {
    cat "$scratch/primary.log" >&2
    echo "native terminal login adapter did not launch its synthetic terminal" >&2
    exit 1
}
grep -Fx -- '-e' "$NATIVE_TERMINAL_LOG" >/dev/null
grep -Fx -- "$CODEX_CLI" "$NATIVE_TERMINAL_LOG" >/dev/null
grep -Fx -- 'login' "$NATIVE_TERMINAL_LOG" >/dev/null
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
deadline=$((SECONDS + 8))
while ! grep -q 'Quota warning' "$NATIVE_NOTIFICATION_LOG" 2>/dev/null && (( SECONDS < deadline )); do
    sleep 0.05
done
grep -q 'Quota warning' "$NATIVE_NOTIFICATION_LOG" || {
    cat "$scratch/primary.log" "$scratch/notifications.log" >&2
    echo "typed quota event was not delivered through Gio on the private bus" >&2
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
[[ "$version_calls" == "4" ]] || {
    echo "expected four CLI-version probes including the SNI Activate menu-open refresh; saw $version_calls version calls" >&2
    exit 1
}
tray_menu_event 10
wait "$app_pid"
app_pid=
terminal_pid=$(cat "$NATIVE_TERMINAL_PID")
terminal_state=$(ps -o stat= -p "$terminal_pid" 2>/dev/null | awk '{print $1}' || true)
[[ -z "$terminal_state" || "$terminal_state" == Z* ]] || {
    echo "synthetic terminal child remained active after its exit: pid $terminal_pid ($terminal_state)" >&2
    exit 1
}
if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk \
    | grep -q '(true,)'; then
    echo "native tray bus name remained owned after application shutdown" >&2
    exit 1
fi
kill "$notification_pid" 2>/dev/null || true
wait "$notification_pid" 2>/dev/null || true

# In a non-systemd launch, restart releases the old tray registration, joins
# the worker and execs the same process before it registers the item again.
unset INVOCATION_ID
: > "$NATIVE_CLI_LOG"
"$binary" --page usage >"$scratch/restart.log" 2>&1 &
app_pid=$!
assert_title_contains '^CodexBar GTK' "Usage"
wait_for_tray_name
[[ $(grep -c '^--version$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] || {
    echo "restart fixture did not reach its initial native backend" >&2
    exit 1
}
gapplication action com.steipete.CodexBarGTK restart
deadline=$((SECONDS + 20))
while [[ $(grep -c '^--version$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -lt 2 ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ $(grep -c '^--version$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 2 ]] || {
    cat "$scratch/restart.log" >&2
    echo "native fallback restart did not exec a fresh backend instance" >&2
    exit 1
}
assert_title_contains '^CodexBar GTK' "Usage"
wait_for_tray_name
gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=
if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk \
    | grep -q '(true,)'; then
    echo "native tray bus name remained owned after restarted application shutdown" >&2
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
if has_app_window 'CodexBar GTK.*Panel'; then
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
if has_app_window 'CodexBar GTK.*Panel'; then
    echo "pending panel toggle did not cancel the open request" >&2
    exit 1
fi
"$binary" --panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"

# The compact panel is a separate window. Escape, toggle, central page and
# Settings/About actions all close it without changing their application APIs.
panel_window=$(app_window_ids 'CodexBar GTK.*Panel' | head -n 1)
[[ -n "$panel_window" ]] || { echo "native panel window was not visible" >&2; exit 1; }
assert_panel_bottom_right "$panel_window"
xdotool windowfocus --sync "$panel_window"
focused_window=$(printf '0x%x' "$(xdotool getwindowfocus)")
[[ "$focused_window" == "$panel_window" ]] || {
    echo "native panel did not receive focus before Escape: focused $focused_window, expected $panel_window" >&2
    exit 1
}
xdotool key Escape
deadline=$((SECONDS + 5))
while has_app_window 'CodexBar GTK.*Panel' && (( SECONDS < deadline )); do sleep 0.05; done
if has_app_window 'CodexBar GTK.*Panel'; then
    echo "Escape did not dismiss the native panel" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK page "'sessions'"
assert_title_contains '^CodexBar GTK' "Sessions"
if has_app_window 'CodexBar GTK.*Panel'; then
    echo "page navigation left the native panel visible" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK settings
assert_title_contains '^CodexBar Settings' "CodexBar Settings"
if has_app_window 'CodexBar GTK.*Panel'; then
    echo "Settings navigation left the native panel visible" >&2
    exit 1
fi

gapplication action com.steipete.CodexBarGTK panel
assert_title_contains 'CodexBar GTK.*Panel' "Panel"
gapplication action com.steipete.CodexBarGTK about
assert_title_contains '^About CodexBar GTK' "About CodexBar GTK"
if has_app_window 'CodexBar GTK.*Panel'; then
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
export NATIVE_CHILD_PID_FILE="$scratch/usage-child.pid"
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
child_pid=$(cat "$NATIVE_CHILD_PID_FILE")
if kill -0 "$child_pid" 2>/dev/null; then
    echo "synthetic CLI child remained alive after native shutdown: $child_pid" >&2
    exit 1
fi

printf 'native GTK command-line and cancellation smoke passed\n'
