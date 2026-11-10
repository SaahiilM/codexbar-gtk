#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

if [[ "${NATIVE_PANEL_SMOKE_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env NATIVE_PANEL_SMOKE_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication gdbus xwininfo xprop xwd ffmpeg; do
    command -v "$tool" >/dev/null || { echo "missing panel smoke dependency: $tool" >&2; exit 2; }
done
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
app_pid=
cleanup() {
    if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [[ "${NATIVE_PANEL_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic panel smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
}
trap cleanup EXIT

mkdir -p "$scratch/home/.config" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
printf '%s\n' "$1" >> "$NATIVE_CLI_LOG"
case "$1" in
    --version) printf 'CodexBar synthetic fixture 0.82.0\n' ;;
    usage)
        printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":62,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":31,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080}}}]'
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

panel_window_id() {
    xdotool search --onlyvisible --name 'CodexBar GTK.*Panel' 2>/dev/null | head -n 1 || true
}

wait_panel_state() {
    local expected=$1 deadline=$((SECONDS + 8)) current
    while (( SECONDS < deadline )); do
        current=hidden
        [[ -n "$(panel_window_id)" ]] && current=visible
        [[ "$current" == "$expected" ]] && return 0
        sleep 0.05
    done
    echo "panel did not become $expected; window=$(panel_window_id)" >&2
    cat "$scratch/app.log" >&2
    exit 1
}

set_panel_state() {
    local requested=$1 current=hidden
    [[ -n "$(panel_window_id)" ]] && current=visible
    if [[ "$requested" != "$current" ]]; then
        gapplication action com.steipete.CodexBarGTK panel
        wait_panel_state "$requested"
    fi
}

usage_calls() {
    awk '$0 == "usage" { n++ } END { print n + 0 }' "$NATIVE_CLI_LOG" 2>/dev/null
}

wait_usage_calls() {
    local target=$1 deadline=$((SECONDS + 8)) count
    while (( SECONDS < deadline )); do
        count=$(usage_calls)
        (( count >= target )) && break
        sleep 0.05
    done
    count=$(usage_calls)
    [[ "$count" == "$target" ]] || {
        echo "expected $target synthetic usage calls, saw $count" >&2
        cat "$scratch/app.log" >&2
        exit 1
    }
    sleep 0.3
    count=$(usage_calls)
    [[ "$count" == "$target" ]] || {
        echo "synthetic usage calls were not stable at $target (saw $count)" >&2
        exit 1
    }
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

capture_panel() {
    local output=$1 window_id
    [[ -n "$output" ]] || return 0
    window_id=$(panel_window_id)
    [[ -n "$window_id" ]] || { echo "cannot capture hidden panel" >&2; exit 1; }
    mkdir -p "$(dirname "$output")"
    xwd -silent -id "$window_id" -out "$scratch/panel.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/panel.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "panel screenshot is empty: $output" >&2; exit 1; }
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
    cat "$scratch/app.log" >&2
    echo "native SNI did not acquire its private session-bus name" >&2
    exit 1
}

run_matrix() {
    local preference=$1 screenshot_suffix=$2 method initial expected_refresh expected_visible
    local baseline target window_id focus
    mkdir -p "$HOME/.config/codexbar-gtk"
    printf '{"refreshAllProvidersOnMenuOpen":%s}\n' "$preference" > "$HOME/.config/codexbar-gtk/settings.json"
    : > "$NATIVE_CLI_LOG"
    "$binary" --page usage >"$scratch/app.log" 2>&1 &
    app_pid=$!
    wait_for_tray_name

    local deadline=$((SECONDS + 15))
    while (( SECONDS < deadline )); do
        if [[ $(grep -c '^usage$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] \
            && [[ $(grep -c '^cost$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] \
            && [[ $(grep -c '^sessions$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]]; then
            break
        fi
        sleep 0.05
    done
    [[ $(grep -c '^usage$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] \
        && [[ $(grep -c '^cost$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] \
        && [[ $(grep -c '^sessions$' "$NATIVE_CLI_LOG" 2>/dev/null || true) -ge 1 ]] || {
        echo "synthetic initial refresh did not complete" >&2
        cat "$scratch/app.log" >&2
        exit 1
    }
    sleep 0.2
    : > "$NATIVE_CLI_LOG"

    for initial in hidden visible; do
        for method in Activate SecondaryActivate ContextMenu; do
            set_panel_state "$initial"
            baseline=$(usage_calls)
            case "$method:$initial" in
                Activate:hidden) expected_visible=visible; expected_refresh=$([[ "$preference" == true ]] && echo 1 || echo 0) ;;
                Activate:visible) expected_visible=hidden; expected_refresh=0 ;;
                SecondaryActivate:hidden|ContextMenu:hidden) expected_visible=visible; expected_refresh=$([[ "$preference" == true ]] && echo 1 || echo 0) ;;
                SecondaryActivate:visible|ContextMenu:visible) expected_visible=visible; expected_refresh=$([[ "$preference" == true ]] && echo 1 || echo 0) ;;
            esac
            gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk \
                --object-path /StatusNotifierItem --method "org.kde.StatusNotifierItem.$method" 31 47 >/dev/null
            wait_panel_state "$expected_visible"
            target=$((baseline + expected_refresh))
            wait_usage_calls "$target"

            if [[ -n "${NATIVE_PANEL_SCREENSHOT_DIR:-}" && "$screenshot_suffix" == enabled && "$initial:$method" == hidden:Activate ]]; then
                window_id=$(panel_window_id)
                assert_panel_bottom_right "$window_id"
                capture_panel "$NATIVE_PANEL_SCREENSHOT_DIR/u04-panel-activate-open-native-xvfb.png"
                xdotool windowfocus --sync "$window_id"
                focus=$(xdotool getwindowfocus)
                [[ "$focus" == "$window_id" ]] || {
                    echo "panel did not receive focus before Escape: focused $focus, expected $window_id" >&2
                    exit 1
                }
                xdotool key Escape
                wait_panel_state hidden
            fi
            if [[ -n "${NATIVE_PANEL_SCREENSHOT_DIR:-}" && "$screenshot_suffix" == enabled && "$initial:$method" == hidden:ContextMenu ]]; then
                assert_panel_bottom_right "$(panel_window_id)"
                capture_panel "$NATIVE_PANEL_SCREENSHOT_DIR/u04-panel-context-open-native-xvfb.png"
            fi
        done
    done

    # Context invocations while visible are idempotent. Confirm all methods
    # still preserve visible state before closing through the focused panel.
    set_panel_state visible
    window_id=$(panel_window_id)
    for method in SecondaryActivate ContextMenu; do
        baseline=$(usage_calls)
        gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk \
            --object-path /StatusNotifierItem --method "org.kde.StatusNotifierItem.$method" 79 83 >/dev/null
        wait_panel_state visible
        if [[ "$preference" == true ]]; then target=$((baseline + 1)); else target=$baseline; fi
        wait_usage_calls "$target"
        [[ "$(panel_window_id)" == "$window_id" ]] || {
            echo "$method replaced the visible panel window instead of ensuring it open" >&2
            exit 1
        }
    done
    xdotool windowfocus --sync "$window_id"
    focus=$(xdotool getwindowfocus)
    [[ "$focus" == "$window_id" ]] || {
        echo "panel did not receive focus before Escape: focused $focus, expected $window_id" >&2
        exit 1
    }
    xdotool key Escape
    wait_panel_state hidden
    gapplication action com.steipete.CodexBarGTK quit
    wait "$app_pid"
    app_pid=
    echo "SNI matrix passed for refreshAllProvidersOnMenuOpen=$preference"
}

run_matrix true enabled
run_matrix false disabled
