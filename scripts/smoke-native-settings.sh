#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

for tool in xvfb-run dbus-run-session xdotool gapplication gdbus xwd ffmpeg python3 grep xfwm4 xprop xwininfo; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done
xdotool version >/dev/null 2>&1 || {
    echo "xdotool was found but could not run; check its runtime library dependencies" >&2
    exit 2
}

if [[ "${CODEXBAR_NATIVE_SETTINGS_INNER:-}" != "1" ]]; then
    run_runtime=$(mktemp -d)
    chmod 700 "$run_runtime"
    cleanup_run_runtime() {
        if command -v findmnt >/dev/null 2>&1; then
            while IFS= read -r mounted_path; do
                if command -v fusermount3 >/dev/null 2>&1; then
                    fusermount3 -u "$mounted_path" >/dev/null 2>&1 || true
                elif command -v fusermount >/dev/null 2>&1; then
                    fusermount -u "$mounted_path" >/dev/null 2>&1 || true
                fi
            done < <(findmnt -rn -o TARGET | awk -v prefix="${run_runtime%/}/" 'index($0, prefix) == 1 { print length($0), $0 }' | sort -rn | cut -d' ' -f2-)
        fi
        rm -rf "$run_runtime"
    }
    trap cleanup_run_runtime EXIT
    run_status=0
    xvfb-run -a env XDG_RUNTIME_DIR="$run_runtime" GTK_USE_PORTAL=0 \
        dbus-run-session -- env CODEXBAR_NATIVE_SETTINGS_INNER=1 \
        XDG_RUNTIME_DIR="$run_runtime" GTK_USE_PORTAL=0 "$0" "$binary" || run_status=$?
    cleanup_run_runtime
    trap - EXIT
    exit "$run_status"
fi

[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
notification_pid=
update_server_pid=
window_manager_pid=
cleanup() {
    if [[ -n "${app_pid:-}" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [[ -n "${notification_pid:-}" ]] && kill -0 "$notification_pid" 2>/dev/null; then
        kill "$notification_pid" 2>/dev/null || true
        wait "$notification_pid" 2>/dev/null || true
    fi
    if [[ -n "${update_server_pid:-}" ]] && kill -0 "$update_server_pid" 2>/dev/null; then
        kill "$update_server_pid" 2>/dev/null || true
        wait "$update_server_pid" 2>/dev/null || true
    fi
    if [[ -n "${window_manager_pid:-}" ]] && kill -0 "$window_manager_pid" 2>/dev/null; then
        kill "$window_manager_pid" 2>/dev/null || true
        wait "$window_manager_pid" 2>/dev/null || true
    fi
    if [[ "${NATIVE_SETTINGS_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic settings smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
}
trap cleanup EXIT

wait_for_file() {
    local path=$1 description=$2
    local seconds=${3:-8}
    local deadline=$((SECONDS + seconds))
    while [[ ! -e "$path" ]] && (( SECONDS < deadline )); do sleep 0.05; done
    [[ -e "$path" ]] || { cat "$scratch/app.log" >&2; echo "timed out waiting for $description" >&2; exit 1; }
}

python3 -c 'import dbus, gi' >/dev/null 2>&1 || {
    echo "native Settings notification smoke needs python3-dbus and python3-gi" >&2
    exit 2
}

runtime_root=${XDG_RUNTIME_DIR:-"$scratch/runtime"}
mkdir -p "$scratch/home" "$runtime_root"
chmod 700 "$runtime_root"
plugins_mode_file="$scratch/plugins-mode"
hooks_mode_file="$scratch/hooks-mode"
provider_enabled_file="$scratch/provider-codex-enabled"
provider_source_file="$scratch/provider-codex-source"
plugin_requested_file="$scratch/plugins-requested"
plugin_release_file="$scratch/plugins-release"
plugin_loaded_file="$scratch/plugins-loaded"
api_key_file="$scratch/api-key-value"
api_key_received_file="$scratch/api-key-received"
login_code_file="$scratch/login-code-value"
login_started_file="$scratch/login-started"
login_complete_file="$scratch/login-complete"
login_status_file="$scratch/login-status"
plugins_request_count_file="$scratch/plugins-request-count"
hooks_served_file="$scratch/hooks-served-mode"
update_request_file="$scratch/update-requested"
printf '%s\n' 'loading' > "$plugins_mode_file"
printf '%s\n' 'populated' > "$hooks_mode_file"
printf '%s\n' 'true' > "$provider_enabled_file"
printf '%s\n' 'auto' > "$provider_source_file"
printf '%s\n' '0' > "$plugins_request_count_file"
api_key_sentinel="synthetic-$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
login_code_sentinel="fixture-$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
printf '%s' "$api_key_sentinel" > "$api_key_file"
printf '%s' "$login_code_sentinel" > "$login_code_file"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
set -eu
case "${1-}/${2-}" in
  config/set-api-key)
    printf '%s %s --provider %s --api-key [redacted]\n' "$1" "$2" "${4-}" >> "$NATIVE_SETTINGS_CALLS"
    ;;
  auth/login|login/)
    # PTY output and submitted codes stay inside the transient LoginActor flow.
    ;;
  *) printf '%s\n' "$*" >> "$NATIVE_SETTINGS_CALLS" ;;
esac
case "${1-}/${2-}" in
  --version/*) printf '%s\n' 'CodexBar synthetic fixture 0.82.0' ;;
  usage/*|cost/*|sessions/*) printf '%s\n' '[]' ;;
  config/providers)
    if [ "$(cat "$NATIVE_SETTINGS_PROVIDER_ENABLED")" = "true" ]; then
      printf '%s\n' 'codex: enabled (Codex)' 'claude: disabled (Claude)'
    else
      printf '%s\n' 'codex: disabled (Codex)' 'claude: disabled (Claude)'
    fi
    ;;
  config/enable|config/disable)
    if [ "${4-}" = "codex" ]; then
      printf '%s\n' "$2" | sed 's/^enable$/true/;s/^disable$/false/' > "$NATIVE_SETTINGS_PROVIDER_ENABLED"
    fi
    printf '%s\n' '{"ok":true}'
    ;;
  config/set-source)
    if [ "${4-}" = "codex" ] && [ "${5-}" = "--source" ]; then
      printf '%s\n' "${6-}" > "$NATIVE_SETTINGS_PROVIDER_SOURCE"
    fi
    printf '%s\n' '{"ok":true}'
    ;;
  config/set-api-key)
    if [ "${5-}" = "--api-key" ] && [ "${6-}" = "$(cat "$NATIVE_SETTINGS_API_KEY_FILE")" ]; then
      : > "$NATIVE_SETTINGS_API_KEY_RECEIVED"
    fi
    printf '%s\n' '{"ok":true}'
    ;;
  auth/login|login/)
    : > "$NATIVE_SETTINGS_LOGIN_STARTED"
    printf '%s\n' 'Paste code here'
    if IFS= read -r code && [ "$code" = "$(cat "$NATIVE_SETTINGS_LOGIN_CODE_FILE")" ]; then
      : > "$NATIVE_SETTINGS_LOGIN_COMPLETE"
      printf '%s\n' 'Successfully logged in'
    else
      printf '%s\n' 'Synthetic login did not complete' >&2
      exit 1
    fi
    ;;
  hooks/list)
    hooks_mode=$(cat "$NATIVE_SETTINGS_HOOKS_MODE")
    printf '%s\n' "$hooks_mode" > "$NATIVE_SETTINGS_HOOKS_SERVED_MODE"
    case "$hooks_mode" in
      error) printf '%s\n' 'synthetic hooks fixture failure' >&2; exit 1 ;;
      empty) printf '%s\n' "{\"enabled\":$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED"),\"events\":[]}" ;;
      *)
    if [ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" = "true" ]; then
      printf '%s\n' '{"enabled":true,"events":[{"event":"quota.warning","enabled":true,"command":"/tmp/synthetic-hook"}]}'
    else
      printf '%s\n' '{"enabled":false,"events":[{"event":"quota.warning","enabled":true,"command":"/tmp/synthetic-hook"}]}'
    fi
        ;;
    esac
    ;;
  hooks/enable)
    printf '%s\n' 'true' > "$NATIVE_SETTINGS_HOOKS_ENABLED"
    ;;
  hooks/disable)
    printf '%s\n' 'false' > "$NATIVE_SETTINGS_HOOKS_ENABLED"
    ;;
  plugins/list)
    count=$(cat "$NATIVE_SETTINGS_PLUGIN_REQUEST_COUNT")
    count=$((count + 1))
    printf '%s\n' "$count" > "$NATIVE_SETTINGS_PLUGIN_REQUEST_COUNT"
    : > "$NATIVE_SETTINGS_PLUGIN_REQUESTED"
    case "$(cat "$NATIVE_SETTINGS_PLUGINS_MODE")" in
      loading)
        while [ ! -e "$NATIVE_SETTINGS_PLUGIN_RELEASE" ]; do sleep 0.05; done
        printf '%s\n' '[{"id":"fixture-plugin","name":"Synthetic Provider","version":"1.0"}]'
        ;;
      empty) printf '%s\n' '[]' ;;
      error) : > "$NATIVE_SETTINGS_PLUGIN_LOADED"; printf '%s\n' 'synthetic plugin fixture failure' >&2; exit 1 ;;
      *) printf '%s\n' '[{"id":"fixture-plugin","name":"Synthetic Provider","version":"1.0"}]' ;;
    esac
    : > "$NATIVE_SETTINGS_PLUGIN_LOADED"
    ;;
  *) printf '%s\n' '[]' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

cat > "$scratch/notifications.py" <<'PY'
import sys

import dbus
import dbus.service
import gi

gi.require_version("GLib", "2.0")
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName("org.freedesktop.Notifications", bus=bus)


class Notifications(dbus.service.Object):
    def __init__(self):
        super().__init__(bus, "/org/freedesktop/Notifications")

    @dbus.service.method("org.freedesktop.Notifications", in_signature="", out_signature="as")
    def GetCapabilities(self):
        return ["body"]

    @dbus.service.method("org.freedesktop.Notifications", in_signature="", out_signature="ssss")
    def GetServerInformation(self):
        return ["Synthetic", "CodexBar GTK fixture", "1.0", "1.2"]

    @dbus.service.method(
        "org.freedesktop.Notifications",
        in_signature="susssasa{sv}i",
        out_signature="u",
    )
    def Notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout):
        with open(sys.argv[1], "a", encoding="utf-8") as output:
            output.write(f"{app_name}\t{summary}\t{body}\n")
        return dbus.UInt32(1)

    @dbus.service.method("org.freedesktop.Notifications", in_signature="u", out_signature="")
    def CloseNotification(self, notification_id):
        return None


Notifications()
GLib.MainLoop().run()
PY

cat > "$scratch/update_server.py" <<'PY'
import http.server
import sys


class QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"MARKETING_VERSION=0.82.0\nCURRENT_PROJECT_VERSION=68\n"
        if self.path != "/VERSION":
            self.send_error(404)
            return
        with open(sys.argv[2], "a", encoding="ascii") as requests:
            requests.write("VERSION\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
with open(sys.argv[1], "w", encoding="ascii") as port_file:
    port_file.write(str(server.server_port))
server.serve_forever()
PY

export HOME="$scratch/home"
export XDG_RUNTIME_DIR="$runtime_root"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
preferences_file="$XDG_CONFIG_HOME/codexbar-gtk/settings.json"
autostart_file="$XDG_CONFIG_HOME/autostart/codexbar-gtk.desktop"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_SETTINGS_CALLS="$scratch/cli-calls"
export NATIVE_SETTINGS_HOOKS_ENABLED="$scratch/hooks-enabled"
export NATIVE_SETTINGS_HOOKS_MODE="$hooks_mode_file"
export NATIVE_SETTINGS_HOOKS_SERVED_MODE="$hooks_served_file"
export NATIVE_SETTINGS_PLUGINS_MODE="$plugins_mode_file"
export NATIVE_SETTINGS_PLUGIN_REQUESTED="$plugin_requested_file"
export NATIVE_SETTINGS_PLUGIN_RELEASE="$plugin_release_file"
export NATIVE_SETTINGS_PLUGIN_LOADED="$plugin_loaded_file"
export NATIVE_SETTINGS_PLUGIN_REQUEST_COUNT="$plugins_request_count_file"
export NATIVE_SETTINGS_PROVIDER_ENABLED="$provider_enabled_file"
export NATIVE_SETTINGS_PROVIDER_SOURCE="$provider_source_file"
export NATIVE_SETTINGS_API_KEY_FILE="$api_key_file"
export NATIVE_SETTINGS_API_KEY_RECEIVED="$api_key_received_file"
export NATIVE_SETTINGS_LOGIN_CODE_FILE="$login_code_file"
export NATIVE_SETTINGS_LOGIN_STARTED="$login_started_file"
export NATIVE_SETTINGS_LOGIN_COMPLETE="$login_complete_file"
export CODEXBAR_NATIVE_SETTINGS_LOGIN_STATUS_REPORT="$login_status_file"
export NATIVE_SETTINGS_NOTIFICATION_LOG="$scratch/notifications"
export CODEXBAR_NATIVE_SETTINGS_ICON_REPORT=1
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=x11 GSK_RENDERER=cairo
printf '%s\n' 'true' > "$NATIVE_SETTINGS_HOOKS_ENABLED"

python3 "$scratch/notifications.py" "$NATIVE_SETTINGS_NOTIFICATION_LOG" >"$scratch/notifications.log" 2>&1 &
notification_pid=$!
notification_deadline=$((SECONDS + 8))
while ! gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.freedesktop.Notifications 2>/dev/null \
    | grep -q '(true,)' && (( SECONDS < notification_deadline )); do sleep 0.05; done
gdbus call --session --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.GetServerInformation >/dev/null || {
    cat "$scratch/notifications.log" >&2
    echo "synthetic Settings notification service did not acquire the private bus name" >&2
    exit 1
}

python3 "$scratch/update_server.py" "$scratch/update-port" "$update_request_file" >"$scratch/update-server.log" 2>&1 &
update_server_pid=$!
wait_for_file "$scratch/update-port" "loopback update fixture server port"
update_port=$(cat "$scratch/update-port")
export CODEXBAR_NATIVE_TEST_UPDATE_URL="http://127.0.0.1:$update_port/VERSION"

(cd "$HOME" && "$binary" --settings) >"$scratch/app.log" 2>&1 &
app_pid=$!

wait_for_window() {
    local pattern=$1 deadline=$((SECONDS + 15)) window="" candidate map_state
    while [[ -z "$window" ]] && (( SECONDS < deadline )); do
        while IFS= read -r candidate; do
            [[ -n "$candidate" ]] || continue
            map_state=$(xwininfo -id "$candidate" 2>/dev/null | sed -n 's/^  Map State: //p')
            if [[ "$map_state" == "IsViewable" ]]; then
                window=$candidate
                break
            fi
        done < <(xdotool search --name "$pattern" 2>/dev/null || true)
        [[ -n "$window" ]] || sleep 0.05
    done
    [[ -n "$window" ]] || {
        cat "$scratch/app.log" >&2
        while read -r visible_window; do
            printf 'mapped window %s: ' "$visible_window" >&2
            xdotool getwindowname "$visible_window" >&2 || true
            xwininfo -id "$visible_window" 2>/dev/null | sed -n 's/^  Map State: /map state: /p' >&2 || true
        done < <(xdotool search --name '.*' 2>/dev/null || true)
        if command -v xwininfo >/dev/null 2>&1; then
            xwininfo -root -tree >&2 || true
        fi
        echo "native settings window not found: $pattern" >&2
        exit 1
    }
    printf '%s\n' "$window"
}

wait_for_calls() {
    local expected=$1 deadline=$((SECONDS + 15))
    while ! grep -q -- "$expected" "$NATIVE_SETTINGS_CALLS" 2>/dev/null && (( SECONDS < deadline )); do sleep 0.05; done
    grep -q -- "$expected" "$NATIVE_SETTINGS_CALLS" || { cat "$scratch/app.log" >&2; echo "synthetic CLI call did not arrive: $expected" >&2; exit 1; }
}

wait_for_preference() {
    local key=$1 expected=$2 deadline=$((SECONDS + 8)) value=""
    while (( SECONDS < deadline )); do
        value=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))' \
            "$preferences_file" "$key" 2>/dev/null || true)
        if [[ "$value" == "$expected" ]]; then
            # The serialized store updates before the GTK actor's response has
            # necessarily reached the owning widget. Let that response settle
            # before the next synthetic pointer action.
            sleep 0.2
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/app.log" >&2
    echo "native Settings did not persist $key=$expected (observed $value)" >&2
    exit 1
}

wait_for_array_preference() {
    local key=$1 index=$2 expected=$3 deadline=$((SECONDS + 8)) value=""
    while (( SECONDS < deadline )); do
        value=$(python3 -c 'import json,sys; values=json.load(open(sys.argv[1])).get(sys.argv[2], []); print(values[int(sys.argv[3])] if len(values) > int(sys.argv[3]) else "")' \
            "$preferences_file" "$key" "$index" 2>/dev/null || true)
        if [[ "$value" == "$expected" ]]; then
            sleep 0.2
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/app.log" >&2
    echo "native Settings did not persist $key[$index]=$expected (observed $value)" >&2
    exit 1
}

wait_for_plugins_loaded() {
    local previous_count=$1 deadline=$((SECONDS + 12)) count=""
    while (( SECONDS < deadline )); do
        count=$(cat "$plugins_request_count_file" 2>/dev/null || printf '0')
        if (( count > previous_count )) && [[ -e "$plugin_loaded_file" ]]; then
            sleep 0.25
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/app.log" >&2
    echo "native Settings did not finish loading the synthetic plugin fixture" >&2
    exit 1
}

start_test_window_manager() {
    [[ -n "$window_manager_pid" ]] && kill -0 "$window_manager_pid" 2>/dev/null && return 0
    xfwm4 --replace --compositor=off >"$scratch/xfwm.log" 2>&1 &
    window_manager_pid=$!
    local deadline=$((SECONDS + 5))
    while ! xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id' \
        && (( SECONDS < deadline )); do sleep 0.05; done
    xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id' || {
        cat "$scratch/xfwm.log" >&2
        echo "Xvfb window manager did not start for the native file chooser" >&2
        exit 1
    }
}

stop_test_window_manager() {
    if [[ -n "$window_manager_pid" ]] && kill -0 "$window_manager_pid" 2>/dev/null; then
        kill "$window_manager_pid" 2>/dev/null || true
        wait "$window_manager_pid" 2>/dev/null || true
    fi
    window_manager_pid=
}

select_chooser_path() {
    local title=$1 path=$2 chooser=""
    start_test_window_manager
    chooser=$(wait_for_window "^${title}$")
    [[ "$(xdotool getwindowname "$chooser")" == "$title" ]] || {
        echo "native file chooser title did not match the requested action: $title" >&2
        exit 1
    }
    sleep 0.35
    if [[ "$title" == "Export preferences" ]]; then
        capture_native_size "$chooser" "${NATIVE_SETTINGS_EXPORT_CHOOSER_SCREENSHOT:-}"
    fi
    xdotool windowfocus --sync "$chooser"
    local focused_window
    focused_window=$(xdotool getwindowfocus 2>/dev/null || true)
    [[ "$focused_window" == "$chooser" ]] || {
        echo "native file chooser did not receive keyboard focus (title: $title)" >&2
        exit 1
    }
    # Xvfb starts without a window manager, so explicitly raise the real
    # titled chooser before pointer input. The title assertion above prevents
    # raising or interacting with the blank input-only XIDs from diagnostics.
    xdotool windowraise "$chooser"
    sleep 0.1
    if [[ -n "${NATIVE_SETTINGS_CHOOSER_ROOT_SCREENSHOT:-}" ]]; then
        capture_root_debug "$NATIVE_SETTINGS_CHOOSER_ROOT_SCREENSHOT"
    fi
    if [[ "$title" == "Export preferences" ]]; then
        [[ "${path%/*}" == "$HOME" && "${path##*/}" == "preferences-export.json" ]] || {
            echo "synthetic export target must match the visible chooser's default filename and home folder" >&2
            exit 1
        }
        # The visible Save chooser starts in the isolated HOME and already has
        # preferences-export.json selected in its Name field.
        xdotool mousemove --window "$chooser" 770 389 click 1
        sleep 0.25
        if [[ -n "${NATIVE_SETTINGS_CHOOSER_AFTER_SCREENSHOT:-}" ]]; then
            capture_root_debug "$NATIVE_SETTINGS_CHOOSER_AFTER_SCREENSHOT"
        fi
        local close_deadline=$((SECONDS + 5))
        while xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable' \
            && (( SECONDS < close_deadline )); do sleep 0.05; done
        if xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable'; then
            capture_native_size "$chooser" "${NATIVE_SETTINGS_EXPORT_AFTER_SCREENSHOT:-}"
            echo "native Save chooser did not close after selecting the default export filename" >&2
            exit 1
        fi
    else
        [[ "${path%/*}" == "$HOME" && -s "$path" ]] || {
            echo "synthetic import target must be a present fixture in the isolated HOME" >&2
            exit 1
        }
        # Force a fresh directory enumeration after the preceding Save
        # chooser, then select the visible synthetic fixture row.
        xdotool key ctrl+l
        xdotool type --clearmodifiers --delay 1 "${HOME%/*}"
        xdotool key Return
        xdotool key Tab
        sleep 0.3
        xdotool key ctrl+l
        xdotool type --clearmodifiers --delay 1 "$HOME"
        xdotool key Return
        xdotool key Tab
        sleep 1.5
        capture_native_size "$chooser" "${NATIVE_SETTINGS_IMPORT_CHOOSER_SCREENSHOT:-}"
        local target_name=${path##*/} row_index=-1 row_y
        local -a listed_json_files=()
        mapfile -t listed_json_files < <(find "$HOME" -maxdepth 1 -type f -name '*.json' -printf '%f\n' | LC_ALL=C sort)
        for index in "${!listed_json_files[@]}"; do
            if [[ "${listed_json_files[$index]}" == "$target_name" ]]; then
                row_index=$index
                break
            fi
        done
        (( row_index >= 0 )) || {
            echo "synthetic import fixture is absent from isolated HOME after chooser navigation: $target_name" >&2
            exit 1
        }
        row_y=$((95 + row_index * 36))
        xdotool mousemove --window "$chooser" 300 "$row_y" click 1
        sleep 0.2
        if [[ "$target_name" == "preferences-import.json" ]]; then
            capture_native_size "$chooser" "${NATIVE_SETTINGS_IMPORT_SELECTED_SCREENSHOT:-}"
        else
            capture_native_size "$chooser" "${NATIVE_SETTINGS_EMPTY_IMPORT_SELECTED_SCREENSHOT:-}"
        fi
        xdotool mousemove --window "$chooser" 762 355 click 1
        local close_deadline=$((SECONDS + 5))
        while xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable' \
            && (( SECONDS < close_deadline )); do sleep 0.05; done
        if xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable'; then
            if [[ -n "${NATIVE_SETTINGS_IMPORT_AFTER_SCREENSHOT:-}" ]]; then
                capture_native_size "$chooser" "$NATIVE_SETTINGS_IMPORT_AFTER_SCREENSHOT"
            fi
            echo "native Import chooser did not close after selecting $target_name" >&2
            exit 1
        fi
    fi
    sleep 0.2
    stop_test_window_manager
}

wait_for_nonempty_preference() {
    local key=$1 deadline=$((SECONDS + 8)) value=""
    while (( SECONDS < deadline )); do
        value=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
            "$preferences_file" "$key" 2>/dev/null || true)
        if [[ -n "$value" && "$value" != "None" ]]; then
            sleep 0.2
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/app.log" >&2
    echo "native Settings did not persist a nonempty $key value" >&2
    exit 1
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

capture_native_size() {
    local window=$1 output=$2
    [[ -n "$output" ]] || return 0
    mkdir -p "$(dirname "$output")"
    xwd -silent -id "$window" -out "$scratch/window.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/window.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "native GTK window screenshot is empty: $output" >&2; exit 1; }
}

capture_root_debug() {
    local output=$1
    [[ -n "$output" ]] || return 0
    mkdir -p "$(dirname "$output")"
    xwd -silent -root -out "$scratch/root.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/root.xwd" -frames:v 1 "$output"
    [[ -s "$output" ]] || { echo "native GTK root screenshot is empty: $output" >&2; exit 1; }
}

settings_window=$(wait_for_window 'CodexBar Settings')
wait_for_calls 'config providers'
wait_for_calls 'hooks list --format json'
wait_for_calls 'plugins list'
wait_for_file "$plugin_requested_file" "initial synthetic Plugins request"
sleep 0.4
# Keep pointer-based checks independent of whether CI requested screenshots.
xdotool windowsize "$settings_window" 1120 820
sleep 0.3
xdotool mousemove --window "$settings_window" 758 800 click 1
sleep 0.25
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_LOADING_SCREENSHOT:-}"
touch "$plugin_release_file"
wait_for_plugins_loaded 0
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 68 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_SCREENSHOT:-}"

# Exercise the remaining General controls using visible GTK controls and wait
# for the serialized preference write before the next pointer action.
xdotool mousemove --window "$settings_window" 810 260 click 1
sleep 0.2
xdotool key Home Down Down Down Return
wait_for_preference refreshFrequency 5m
xdotool mousemove --window "$settings_window" 810 488 click 1
wait_for_preference showPopupOnStart True
xdotool mousemove --window "$settings_window" 810 488 click 1
wait_for_preference showPopupOnStart False
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_ACTIONS_SCREENSHOT:-}"

# Exercise one live preference mutation and verify the durable JSON value.
xdotool mousemove --window "$settings_window" 810 315 click 1
wait_for_preference refreshAllProvidersOnMenuOpen False

# Exercise the native launch-at-login switch and verify its private desktop
# entry is created atomically, then removed again through SettingsActor.
xdotool mousemove --window "$settings_window" 810 432 click 1
wait_for_preference launchAtLogin True
autostart_deadline=$((SECONDS + 8))
while [[ ! -s "$autostart_file" ]] && (( SECONDS < autostart_deadline )); do sleep 0.05; done
expected_executable=$(readlink -f "$binary")
[[ -s "$autostart_file" ]] && grep -Fx -- "Exec=\"$expected_executable\"" "$autostart_file" >/dev/null || {
    cat "$scratch/app.log" >&2
    echo "native launch-at-login switch did not write the expected executable entry" >&2
    exit 1
}
# Do not send the off click until SettingsActor has persisted the enabled state
# and its response-settle interval has elapsed. Then require both the disabled
# preference and removal of the desktop entry; either failure remains visible.
xdotool mousemove --window "$settings_window" 810 432 click 1
wait_for_preference launchAtLogin False
autostart_deadline=$((SECONDS + 8))
while [[ -e "$autostart_file" ]] && (( SECONDS < autostart_deadline )); do sleep 0.05; done
[[ ! -e "$autostart_file" ]] || {
    cat "$scratch/app.log" >&2
    echo "native launch-at-login switch did not remove its desktop entry" >&2
    exit 1
}

# Capture representative panes from the live PreferencesWindow.
xdotool mousemove --window "$settings_window" 267 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_MENU_BAR_SCREENSHOT:-}"

# Exercise every Menu Bar preference through its visible GTK control and verify
# each write reaches the isolated PreferencesStore. The isolated home keeps the
# final hidden-tray value from changing the user's real preferences.
xdotool mousemove --window "$settings_window" 810 142 click 1
sleep 0.2
xdotool key End Return
wait_for_preference menuBarIconStyle iconPercent
xdotool mousemove --window "$settings_window" 810 198 click 1
sleep 0.2
xdotool key Home Return
wait_for_preference unifiedIconSource automatic
xdotool mousemove --window "$settings_window" 810 252 click 1
sleep 0.2
xdotool key End Return
wait_for_preference switcherRowsOption details
xdotool mousemove --window "$settings_window" 810 307 click 1
wait_for_preference showTray False
capture "$settings_window" "${NATIVE_SETTINGS_MENU_BAR_ACTIONS_SCREENSHOT:-}"

xdotool mousemove --window "$settings_window" 68 800 click 1
sleep 0.3
xdotool mousemove --window "$settings_window" 810 605 click 1
sleep 0.2
xdotool key Down Return
wait_for_preference preferredCurrencyCode USD

xdotool mousemove --window "$settings_window" 166 800 click 1
sleep 0.3
xdotool mousemove --window "$settings_window" 540 178 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PROVIDERS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 234 click 1
wait_for_calls 'config disable --provider codex'
[[ "$(cat "$provider_enabled_file")" == "false" ]] || {
    echo "native provider switch did not disable the synthetic Codex provider" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 810 234 click 1
wait_for_calls 'config enable --provider codex'
[[ "$(cat "$provider_enabled_file")" == "true" ]] || {
    echo "native provider switch did not re-enable the synthetic Codex provider" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 810 289 click 1
sleep 0.2
xdotool key End Return
wait_for_calls 'config set-source --provider codex --source api'
[[ "$(cat "$provider_source_file")" == "api" ]] || {
    echo "native provider source selector did not reach the synthetic CLI" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 500 398 click 1
xdotool type --clearmodifiers --delay 1 "$api_key_sentinel"
xdotool mousemove --window "$settings_window" 777 398 click 1
wait_for_file "$api_key_received_file" "synthetic API-key Apply action"
for log_file in "$preferences_file" "$NATIVE_SETTINGS_CALLS" "$scratch/app.log" "$NATIVE_SETTINGS_NOTIFICATION_LOG"; do
    if [[ -f "$log_file" ]] && grep -Fq -- "$api_key_sentinel" "$log_file"; then
        echo "synthetic API-key fixture value escaped into persisted or logged output" >&2
        exit 1
    fi
done
capture "$settings_window" "${NATIVE_SETTINGS_PROVIDERS_ACTIONS_SCREENSHOT:-}"

# Exercise the visible sign-in button with a synthetic PTY process. The code is
# submitted through the dialog, never printed into a test log or screenshot.
xdotool mousemove --window "$settings_window" 790 345 click 1
login_window=$(wait_for_window '^Sign in to CODEX$')
wait_for_file "$login_started_file" "synthetic login PTY start"
sleep 0.35
capture_native_size "$login_window" "${NATIVE_SETTINGS_LOGIN_PROMPT_SCREENSHOT:-}"
xdotool mousemove --window "$login_window" 250 160 click 1
xdotool type --clearmodifiers --delay 1 "$login_code_sentinel"
xdotool mousemove --window "$login_window" 465 205 click 1
wait_for_file "$login_complete_file" "synthetic login completion" 12
wait_for_file "$login_status_file" "GTK sign-in completion result" 5
[[ "$(cat "$login_status_file")" == "Sign-in completed." ]] || {
    echo "synthetic sign-in action did not display the completed result" >&2
    exit 1
}
sleep 0.4
capture_native_size "$login_window" "${NATIVE_SETTINGS_LOGIN_COMPLETE_SCREENSHOT:-}"
xdotool mousemove --window "$login_window" 465 252 click 1
login_close_deadline=$((SECONDS + 5))
while xdotool getwindowname "$login_window" >/dev/null 2>&1 && (( SECONDS < login_close_deadline )); do sleep 0.05; done
! xdotool getwindowname "$login_window" >/dev/null 2>&1 || {
    echo "synthetic sign-in dialog did not close after completion" >&2
    exit 1
}
for log_file in "$preferences_file" "$NATIVE_SETTINGS_CALLS" "$scratch/app.log" "$NATIVE_SETTINGS_NOTIFICATION_LOG"; do
    if [[ -f "$log_file" ]] && grep -Fq -- "$login_code_sentinel" "$log_file"; then
        echo "synthetic login code escaped into persisted or logged output" >&2
        exit 1
    fi
done
capture "$settings_window" "${NATIVE_SETTINGS_PROVIDERS_LOGIN_COMPLETE_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 365 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_DISPLAY_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 142 click 1
wait_for_preference usageBarsShowUsed False
xdotool mousemove --window "$settings_window" 810 197 click 1
sleep 0.2
xdotool key End Return
wait_for_preference resetTimesOption both
xdotool mousemove --window "$settings_window" 810 498 click 1
sleep 0.2
xdotool key End Return
wait_for_preference workdayTickAppearance highContrast
xdotool mousemove --window "$settings_window" 810 552 click 1
wait_for_preference quotaBurndownEnabled False
xdotool mousemove --window "$settings_window" 810 252 click 1
wait_for_preference paceVisible False
xdotool mousemove --window "$settings_window" 810 307 click 1
wait_for_preference hidePersonalInfo True
xdotool mousemove --window "$settings_window" 746 443 click 1
xdotool key ctrl+a
xdotool type --clearmodifiers 6
xdotool key Return
wait_for_preference weeklyProgressWorkDays 6
xdotool mousemove --window "$settings_window" 746 689 click 1
xdotool key ctrl+a
xdotool type --clearmodifiers 70
xdotool key Return
wait_for_array_preference quotaWarningThresholds 0 70
xdotool mousemove --window "$settings_window" 746 744 click 1
xdotool key ctrl+a
xdotool type --clearmodifiers 85
xdotool key Return
wait_for_array_preference quotaWarningThresholds 1 85
capture "$settings_window" "${NATIVE_SETTINGS_DISPLAY_ACTIONS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 463 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_NOTIFICATIONS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 142 click 1
wait_for_preference sessionQuotaNotificationsEnabled False
xdotool mousemove --window "$settings_window" 810 197 click 1
wait_for_preference quotaWarningNotificationsEnabled False
xdotool mousemove --window "$settings_window" 810 252 click 1
wait_for_preference limitResetNotificationsEnabled False
xdotool mousemove --window "$settings_window" 810 307 click 1
wait_for_preference predictivePaceNotificationsEnabled False
xdotool mousemove --window "$settings_window" 800 362 click 1
notification_deadline=$((SECONDS + 8))
while ! grep -q 'CodexBar GTK test notification' "$NATIVE_SETTINGS_NOTIFICATION_LOG" 2>/dev/null \
    && (( SECONDS < notification_deadline )); do sleep 0.05; done
grep -q 'CodexBar GTK test notification' "$NATIVE_SETTINGS_NOTIFICATION_LOG" || {
    cat "$scratch/app.log" "$scratch/notifications.log" >&2
    echo "Settings test-notification button did not reach the private notification service" >&2
    exit 1
}
capture "$settings_window" "${NATIVE_SETTINGS_NOTIFICATION_ACTION_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 562 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_SPEND_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 142 click 1
wait_for_preference costUsageEnabled False
xdotool mousemove --window "$settings_window" 810 278 click 1
sleep 0.2
xdotool key Home Down Return
wait_for_nonempty_preference costUsageBucketTimeZone
capture "$settings_window" "${NATIVE_SETTINGS_SPEND_ACTION_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 660 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 160 click 1
wait_for_calls 'hooks disable'
[[ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" == "false" ]] || {
    echo "native Hooks switch did not persist disabled state through the synthetic CLI" >&2
    exit 1
}
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_ACTIONS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 810 160 click 1
wait_for_calls 'hooks enable'
[[ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" == "true" ]] || {
    echo "native Hooks switch did not persist enabled state through the synthetic CLI" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 758 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 856 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_SCREENSHOT:-}"

# Reconfigure to the same synthetic executable through the visible CLI-path
# entry. This validates the GTK apply action without switching away from the
# synthetic provider/auth fixture.
xdotool mousemove --window "$settings_window" 500 158 click 1
xdotool type --clearmodifiers --delay 1 "$CODEXBAR_CLI"
xdotool mousemove --window "$settings_window" 810 158 click 1
wait_for_preference cliPath "$CODEXBAR_CLI"
capture "$settings_window" "${NATIVE_SETTINGS_CLI_PATH_ACTIONS_SCREENSHOT:-}"

export_file="$HOME/preferences-export.json"
import_file="$HOME/preferences-import.json"
empty_import_file="$HOME/empty-preferences-import.json"
python3 - "$import_file" "$empty_import_file" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(
        {
            "version": 1,
            "preferences": {
                "preferredCurrencyCode": "EUR",
                "refreshFrequency": "2m",
                "launchAtLogin": False,
                "futureSyntheticPreference": "ignored",
            },
        },
        output,
    )
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump({"version": 1, "preferences": {}}, output)
PY

# Keep a synthetic autostart entry present across Import and Reset. Both flows
# must update persisted preferences without touching this OS integration file.
xdotool mousemove --window "$settings_window" 68 800 click 1
sleep 0.25
xdotool mousemove --window "$settings_window" 810 432 click 1
wait_for_preference launchAtLogin True
wait_for_file "$autostart_file" "autostart entry before import/reset" 8
xdotool mousemove --window "$settings_window" 856 800 click 1
sleep 0.25

# Export through the native Save chooser and verify the resulting portable JSON.
xdotool mousemove --window "$settings_window" 790 333 click 1
select_chooser_path "Export preferences" "$export_file"
wait_for_file "$export_file" "selected preferences export"
python3 - "$export_file" "$api_key_sentinel" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    document = json.load(source)
assert document["version"] == 1
assert document["preferences"]["refreshFrequency"] == "5m"
assert document["preferences"]["preferredCurrencyCode"] == "USD"
assert sys.argv[2] not in json.dumps(document)
PY
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_EXPORT_SCREENSHOT:-}"

# Import overlays known keys onto the latest map, preserves the unrelated
# Display preference, ignores the unknown key, and leaves autostart untouched.
xdotool mousemove --window "$settings_window" 790 388 click 1
select_chooser_path "Import preferences" "$import_file"
wait_for_preference refreshFrequency 2m
wait_for_preference preferredCurrencyCode EUR
wait_for_preference launchAtLogin False
[[ -s "$autostart_file" ]] || {
    echo "native Preferences import changed the autostart desktop entry" >&2
    exit 1
}
python3 - "$preferences_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    settings = json.load(source)
assert settings["usageBarsShowUsed"] is False
assert "futureSyntheticPreference" not in settings
PY
for log_file in "$preferences_file" "$export_file" "$NATIVE_SETTINGS_CALLS" "$scratch/app.log"; do
    if grep -Fq -- "$api_key_sentinel" "$log_file" || grep -Fq -- "$login_code_sentinel" "$log_file"; then
        echo "synthetic credential or login code escaped into saved or logged preferences" >&2
        exit 1
    fi
done
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_IMPORT_SCREENSHOT:-}"

# Reload the read-only hooks/plugins lists from synthetic empty fixtures.
printf '%s\n' 'empty' > "$hooks_mode_file"
printf '%s\n' 'empty' > "$plugins_mode_file"
rm -f "$hooks_served_file" "$plugin_loaded_file"
plugins_before=$(cat "$plugins_request_count_file")
xdotool mousemove --window "$settings_window" 790 388 click 1
select_chooser_path "Import preferences" "$empty_import_file"
wait_for_plugins_loaded "$plugins_before"
hook_mode_deadline=$((SECONDS + 8))
while [[ "$(cat "$hooks_served_file" 2>/dev/null || true)" != "empty" ]] && (( SECONDS < hook_mode_deadline )); do sleep 0.05; done
[[ "$(cat "$hooks_served_file" 2>/dev/null || true)" == "empty" ]] || {
    echo "Settings reload did not query the empty synthetic Hooks rules" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 660 800 click 1
sleep 0.4
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_EMPTY_RULES_SCREENSHOT:-}"
xdotool mousemove --window "$settings_window" 758 800 click 1
sleep 0.4
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_EMPTY_SCREENSHOT:-}"

# The error fixture must render the sanitized read-only error state.
printf '%s\n' 'error' > "$plugins_mode_file"
rm -f "$plugin_loaded_file"
plugins_before=$(cat "$plugins_request_count_file")
xdotool mousemove --window "$settings_window" 856 800 click 1
sleep 0.25
xdotool mousemove --window "$settings_window" 790 388 click 1
select_chooser_path "Import preferences" "$empty_import_file"
wait_for_plugins_loaded "$plugins_before"
sleep 0.35
xdotool mousemove --window "$settings_window" 758 800 click 1
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_ERROR_SCREENSHOT:-}"

# Reset requires explicit confirmation. First cancel and prove the imported
# values remain; then confirm and verify defaults while the autostart file stays.
xdotool mousemove --window "$settings_window" 856 800 click 1
sleep 0.25
xdotool mousemove --window "$settings_window" 790 443 click 1
reset_cancel_window=$(wait_for_window 'Reset all preferences')
capture_native_size "$reset_cancel_window" "${NATIVE_SETTINGS_RESET_CONFIRMATION_SCREENSHOT:-}"
xdotool key Escape
reset_cancel_deadline=$((SECONDS + 5))
while xdotool getwindowname "$reset_cancel_window" >/dev/null 2>&1 && (( SECONDS < reset_cancel_deadline )); do sleep 0.05; done
wait_for_preference refreshFrequency 2m
[[ -s "$autostart_file" ]] || {
    echo "cancelling Preferences reset changed the autostart desktop entry" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 790 443 click 1
reset_window=$(wait_for_window 'Reset all preferences')
xdotool key Tab
xdotool key Return
wait_for_preference refreshFrequency adaptive
wait_for_preference preferredCurrencyCode auto
wait_for_preference launchAtLogin False
[[ -s "$autostart_file" ]] || {
    echo "native Preferences reset changed the autostart desktop entry" >&2
    exit 1
}
for log_file in "$preferences_file" "$export_file" "$NATIVE_SETTINGS_CALLS" "$scratch/app.log"; do
    if grep -Fq -- "$api_key_sentinel" "$log_file" || grep -Fq -- "$login_code_sentinel" "$log_file"; then
        echo "synthetic credential or login code escaped into saved or logged preferences" >&2
        exit 1
    fi
done
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_RESET_SCREENSHOT:-}"

# Activate the real Gio update action; only debug builds accept this loopback
# URL override, so no public network request is involved in the smoke.
gapplication action com.steipete.CodexBarGTK check-updates
wait_for_file "$update_request_file" "loopback update-check request"
update_result_window=$(wait_for_window 'Update available')
[[ "$(xdotool getwindowname "$update_result_window")" == *"Update available"* ]] || {
    echo "update-check action did not show the expected synthetic result" >&2
    exit 1
}
capture_native_size "$update_result_window" "${NATIVE_SETTINGS_UPDATE_CHECK_SCREENSHOT:-}"
xdotool key Escape
update_dialog_deadline=$((SECONDS + 5))
while xdotool getwindowname "$update_result_window" >/dev/null 2>&1 && (( SECONDS < update_dialog_deadline )); do sleep 0.05; done
! xdotool getwindowname "$update_result_window" >/dev/null 2>&1 || {
    echo "synthetic update-result dialog did not close" >&2
    exit 1
}

xdotool mousemove --window "$settings_window" 790 333 click 1
new_dialog_windows=$(wait_for_window '^Export preferences$')
capture_native_size "$new_dialog_windows" "${NATIVE_SETTINGS_CANCEL_CHOOSER_SCREENSHOT:-}"
dialog_deadline=$((SECONDS + 8))
while (( SECONDS < dialog_deadline )); do
    new_dialog_windows=$(xdotool search --name '^Export preferences$' 2>/dev/null || true)
    [[ -n "$new_dialog_windows" ]] && break
    sleep 0.05
done
[[ -n "$new_dialog_windows" ]] || {
    cat "$scratch/app.log" >&2
    echo "native file chooser did not map a window" >&2
    exit 1
}
xdotool key Escape
dialog_deadline=$((SECONDS + 5))
still_open_windows=
while (( SECONDS < dialog_deadline )); do
    still_open_windows=
    if xwininfo -id "$new_dialog_windows" 2>/dev/null | grep -Fq 'Map State: IsViewable'; then
        still_open_windows=$new_dialog_windows
    fi
    [[ -n "$still_open_windows" ]] || break
    sleep 0.05
done
if [[ -n "$still_open_windows" ]]; then
    echo "native file chooser did not close after the cancel response" >&2
    exit 1
fi
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
app_bus_owner=$(gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
[[ "$app_bus_owner" == "(false,)" ]] || {
    echo "native Settings app kept its D-Bus name after shutdown" >&2
    exit 1
}
kill "$notification_pid" 2>/dev/null || true
wait "$notification_pid" 2>/dev/null || true
notification_pid=
notification_bus_owner=$(gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.freedesktop.Notifications)
[[ "$notification_bus_owner" == "(false,)" ]] || {
    echo "synthetic Settings notification service kept its D-Bus name after shutdown" >&2
    exit 1
}
if grep -q 'Adwaita-CRITICAL' "$scratch/app.log"; then
    cat "$scratch/app.log" >&2
    echo "libadwaita emitted a critical during Settings smoke" >&2
    exit 1
fi
if [[ "${CODEXBAR_NATIVE_SETTINGS_ICON_REPORT:-}" == "1" ]]; then
    icon_report_count=$(grep -c '^native-settings-icon:' "$scratch/app.log" || true)
    [[ "$icon_report_count" == "11" ]] || {
        cat "$scratch/app.log" >&2
        echo "native settings did not report one runtime-resolved icon decision per page" >&2
        exit 1
    }
    grep '^native-settings-icon:' "$scratch/app.log"
fi
printf 'native Settings synthetic CLI, Hooks enable/disable and launch-at-login persistence, Menu Bar/currency/display/notification/time-zone controls, private notification action, preference persistence, all settings panes, central About route, and GTK lifecycle smoke passed\n'
