#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
if [[ "${CODEXBAR_NATIVE_SETTINGS_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_SETTINGS_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication timeout xwd ffmpeg; do
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
    if [[ "${NATIVE_SETTINGS_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic settings smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
}
trap cleanup EXIT

mkdir -p "$scratch/home" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$NATIVE_SETTINGS_CALLS"
case "${1-}/${2-}" in
  --version/*) printf '%s\n' 'CodexBar synthetic fixture 0.82.0' ;;
  usage/*|cost/*|sessions/*) printf '%s\n' '[]' ;;
  config/providers)
    printf '%s\n' 'codex: enabled (Codex)' 'claude: disabled (Claude)'
    ;;
  hooks/list)
    printf '%s\n' '{"enabled":true,"events":[{"event":"quota.warning","enabled":true,"command":"/tmp/synthetic-hook"}]}'
    ;;
  plugins/list)
    printf '%s\n' '[{"id":"fixture-plugin","name":"Synthetic Provider","version":"1.0"}]'
    ;;
  *) printf '%s\n' '[]' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

export HOME="$scratch/home"
export XDG_RUNTIME_DIR="$scratch/runtime"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_SETTINGS_CALLS="$scratch/cli-calls"
export CODEXBAR_NATIVE_SETTINGS_ICON_REPORT=1
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=x11 GSK_RENDERER=cairo

"$binary" --settings >"$scratch/app.log" 2>&1 &
app_pid=$!

wait_for_window() {
    local pattern=$1 deadline=$((SECONDS + 15)) window=""
    while [[ -z "$window" ]] && (( SECONDS < deadline )); do
        window=$(xdotool search --onlyvisible --name "$pattern" 2>/dev/null | head -n 1 || true)
        [[ -n "$window" ]] || sleep 0.05
    done
    [[ -n "$window" ]] || { cat "$scratch/app.log" >&2; echo "native settings window not found: $pattern" >&2; exit 1; }
    printf '%s\n' "$window"
}

wait_for_calls() {
    local expected=$1 deadline=$((SECONDS + 15))
    while ! rg -q -- "$expected" "$NATIVE_SETTINGS_CALLS" 2>/dev/null && (( SECONDS < deadline )); do sleep 0.05; done
    rg -q -- "$expected" "$NATIVE_SETTINGS_CALLS" || { cat "$scratch/app.log" >&2; echo "synthetic CLI call did not arrive: $expected" >&2; exit 1; }
}

capture() {
    local window=$1 output=$2
    [[ -n "$output" ]] || return 0
    mkdir -p "$(dirname "$output")"
    xdotool windowsize "$window" 1120 820
    sleep 0.3
    if [[ "${NATIVE_SETTINGS_DEBUG:-0}" == "1" ]] && command -v xwininfo >/dev/null; then
        xwininfo -id "$window" >&2
    fi
    xwd -silent -id "$window" -out "$scratch/settings.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/settings.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "native Settings screenshot is empty: $output" >&2; exit 1; }
}

settings_window=$(wait_for_window 'CodexBar Settings')
wait_for_calls 'config providers'
wait_for_calls 'hooks list --format json'
wait_for_calls 'plugins list'
sleep 0.4
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_SCREENSHOT:-}"

# Exercise one live preference mutation and verify the durable JSON value.
preferences_file="$HOME/.config/codexbar-gtk/settings.json"
xdotool mousemove --window "$settings_window" 810 315 click 1
preference_deadline=$((SECONDS + 8))
while (( SECONDS < preference_deadline )); do
    preference_value=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))' \
        "$preferences_file" refreshAllProvidersOnMenuOpen 2>/dev/null || true)
    [[ "$preference_value" == "False" ]] && break
    sleep 0.05
done
[[ "${preference_value:-}" == "False" ]] || {
    cat "$scratch/app.log" >&2
    echo "native preference control did not persist through SettingsActor" >&2
    exit 1
}

# Capture representative panes from the live PreferencesWindow.
xdotool mousemove --window "$settings_window" 166 800 click 1
sleep 0.3
xdotool mousemove --window "$settings_window" 540 178 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PROVIDERS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 365 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_DISPLAY_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 463 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_NOTIFICATIONS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 562 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_SPEND_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 660 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 758 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 856 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 1052 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ABOUT_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 955 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ACKNOWLEDGEMENTS_SCREENSHOT:-}"

if [[ "${NATIVE_SETTINGS_SKIP_ABOUT:-0}" != "1" ]]; then
    # The app action keeps the dashboard and Settings as separate central routes.
    gapplication action com.steipete.CodexBarGTK about
    about_window=$(wait_for_window '^About CodexBar GTK')
    [[ "$(xdotool getwindowname "$about_window")" == *"About CodexBar GTK"* ]] || {
        echo "central About action did not open the native About window" >&2
        exit 1
    }
    capture "$about_window" "${NATIVE_SETTINGS_CENTRAL_ABOUT_SCREENSHOT:-}"
fi

gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=
if rg -q 'Adwaita-CRITICAL' "$scratch/app.log"; then
    cat "$scratch/app.log" >&2
    echo "libadwaita emitted a critical during Settings smoke" >&2
    exit 1
fi
if [[ "${CODEXBAR_NATIVE_SETTINGS_ICON_REPORT:-}" == "1" ]]; then
    icon_report_count=$(rg -c '^native-settings-icon:' "$scratch/app.log" || true)
    [[ "$icon_report_count" == "11" ]] || {
        cat "$scratch/app.log" >&2
        echo "native settings did not report one runtime-resolved icon decision per page" >&2
        exit 1
    }
    rg '^native-settings-icon:' "$scratch/app.log"
fi
printf 'native Settings synthetic CLI, preference persistence, settings panes, central About route, and GTK lifecycle smoke passed\n'
