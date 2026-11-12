#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

for tool in xvfb-run dbus-run-session xdotool gapplication gdbus xwd ffmpeg python3 grep xfwm4 xprop xwininfo; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done

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
claudeplatform_cookie_file="$scratch/claudeplatform-cookie-received"
claudeplatform_status_file="$scratch/claudeplatform-status"
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
      printf '%s\n' 'codex: enabled (Codex)' 'claude: disabled (Claude)' \
        'opendesign: disabled (OpenDesign)' \
        'siliconflow: disabled (SiliconFlow)' \
        'tripo: disabled (Tripo)' 'claudeplatform: disabled (Claude Platform)'
    else
      printf '%s\n' 'codex: disabled (Codex)' 'claude: disabled (Claude)' \
        'opendesign: disabled (OpenDesign)' \
        'siliconflow: disabled (SiliconFlow)' \
        'tripo: disabled (Tripo)' 'claudeplatform: disabled (Claude Platform)'
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
  config/login)
    cat > "$NATIVE_SETTINGS_CLAUDEPLATFORM_COOKIE_RECEIVED"
    if [ "$(cat "$NATIVE_SETTINGS_CLAUDEPLATFORM_COOKIE_RECEIVED")" = "sessionKey=synthetic-cookie-candidate" ]; then
      printf '%s\n' '{"status":"authorized"}'
    else
      exit 1
    fi
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
        version = {}
        with open(sys.argv[3], encoding="utf-8") as version_file:
            for line in version_file:
                key, separator, value = line.strip().partition("=")
                if separator:
                    version[key] = value
        latest_build = int(version["CURRENT_PROJECT_VERSION"]) + 1
        body = (
            f"MARKETING_VERSION={version['MARKETING_VERSION']}\n"
            f"CURRENT_PROJECT_VERSION={latest_build}\n"
        ).encode("ascii")
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
export NATIVE_SETTINGS_CLAUDEPLATFORM_COOKIE_RECEIVED="$claudeplatform_cookie_file"
export CODEXBAR_NATIVE_SETTINGS_CLAUDEPLATFORM_STATUS_REPORT="$claudeplatform_status_file"
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

python3 "$scratch/update_server.py" "$scratch/update-port" "$update_request_file" "$repo_root/VERSION" >"$scratch/update-server.log" 2>&1 &
update_server_pid=$!
wait_for_file "$scratch/update-port" "loopback update fixture server port"
update_port=$(cat "$scratch/update-port")
export CODEXBAR_NATIVE_TEST_UPDATE_URL="http://127.0.0.1:$update_port/VERSION"

(cd "$HOME" && exec "$binary" --settings) >"$scratch/app.log" 2>&1 &
app_pid=$!

wait_for_window() {
    local pattern=$1 deadline=$((SECONDS + 15)) window="" candidate map_state candidate_title confirmed_title confirmed_map_state owner_pid confirmed_owner_pid
    while [[ -z "$window" ]] && (( SECONDS < deadline )); do
        while IFS= read -r candidate; do
            [[ -n "$candidate" ]] || continue
            candidate_title=$(xprop -id "$candidate" _NET_WM_NAME WM_NAME 2>/dev/null \
                | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
            [[ "$candidate_title" =~ $pattern ]] || continue
            owner_pid=$(xprop -id "$candidate" _NET_WM_PID 2>/dev/null \
                | sed -n 's/.* = \([0-9][0-9]*\)$/\1/p')
            [[ "$owner_pid" == "$app_pid" ]] || continue
            map_state=$(xwininfo -id "$candidate" 2>/dev/null | sed -n 's/^  Map State: //p')
            if [[ "$map_state" == "IsViewable" ]]; then
                # GTK and the window manager can replace transient XIDs while
                # a native chooser maps. Require its title, owner and map state
                # to agree on a second read before returning an ID for input.
                sleep 0.05
                confirmed_title=$(xprop -id "$candidate" _NET_WM_NAME WM_NAME 2>/dev/null \
                    | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
                confirmed_map_state=$(xwininfo -id "$candidate" 2>/dev/null | sed -n 's/^  Map State: //p')
                confirmed_owner_pid=$(xprop -id "$candidate" _NET_WM_PID 2>/dev/null \
                    | sed -n 's/.* = \([0-9][0-9]*\)$/\1/p')
                if [[ "$confirmed_title" == "$candidate_title" \
                    && "$confirmed_map_state" == "IsViewable" \
                    && "$confirmed_owner_pid" == "$app_pid" ]]; then
                    window=$candidate
                    break
                fi
            fi
        done < <(xwininfo -root -tree 2>/dev/null | awk '$1 ~ /^0x[[:xdigit:]]+$/ { print $1 }')
        [[ -n "$window" ]] || sleep 0.05
    done
    [[ -n "$window" ]] || {
        cat "$scratch/app.log" >&2
        echo "window lookup diagnostics: app_pid=$app_pid pattern=$pattern" >&2
        while read -r visible_window; do
            visible_title=$(xprop -id "$visible_window" _NET_WM_NAME WM_NAME 2>/dev/null \
                | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1)
            visible_pid=$(xprop -id "$visible_window" _NET_WM_PID 2>/dev/null | tail -n 1)
            visible_state=$(xwininfo -id "$visible_window" 2>/dev/null \
                | sed -n 's/^  Map State: /map state: /p')
            printf 'candidate %s title=%q pid-property=%q %s\n' \
                "$visible_window" "$visible_title" "$visible_pid" "$visible_state" >&2
        done < <(xwininfo -root -tree 2>/dev/null | awk '$1 ~ /^0x[[:xdigit:]]+$/ { print $1 }')
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
    echo "native Settings did not persist ${key}[$index]=$expected (observed $value)" >&2
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

window_manager_has_claimed_root() {
    local check_window self_check
    check_window=$(xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null \
        | sed -n 's/.*window id # \(0x[[:xdigit:]]\+\).*/\1/p')
    [[ -n "$check_window" ]] || return 1
    self_check=$(xprop -id "$check_window" _NET_SUPPORTING_WM_CHECK 2>/dev/null \
        | sed -n 's/.*window id # \(0x[[:xdigit:]]\+\).*/\1/p')
    [[ "${self_check,,}" == "${check_window,,}" ]]
}

assert_pointer_within_window_tree() {
    local target_window=$1 description=$2 pointer_state pointer_window pointer_hex
    pointer_state=$(xdotool getmouselocation --shell 2>/dev/null || true)
    pointer_window=$(sed -n 's/^WINDOW=//p' <<<"$pointer_state")
    if [[ "$pointer_window" =~ ^0[xX][[:xdigit:]]+$ ]]; then
        pointer_hex=${pointer_window,,}
    elif [[ "$pointer_window" =~ ^[0-9]+$ ]]; then
        pointer_hex=$(printf '0x%x' "$pointer_window")
    else
        pointer_hex=
    fi
    if [[ -z "$pointer_hex" ]] || ! xwininfo -id "$target_window" -tree 2>/dev/null \
        | awk -v wanted="${pointer_hex,,}" '{ for (i = 1; i <= NF; i++) { gsub(/[()]/, "", $i); if (tolower($i) == wanted) found = 1 } } END { exit !found }'; then
        echo "native click target is outside the intended window: $description" >&2
        printf '%s\n' "$pointer_state" >&2
        xwininfo -id "$target_window" -tree >&2 || true
        return 1
    fi
}

window_size() {
    local window=$1
    xwininfo -id "$window" 2>/dev/null | awk '
        /^  Width: / { width = $2 }
        /^  Height: / { height = $2 }
        END { if (width && height) print width, height; else exit 1 }
    '
}

normalize_window_id() {
    local window_id=$1
    if [[ "$window_id" =~ ^0[xX][[:xdigit:]]+$ ]]; then
        printf '0x%x' "$((window_id))"
    elif [[ "$window_id" =~ ^[0-9]+$ ]]; then
        printf '0x%x' "$window_id"
    fi
}

window_title() {
    local window=$1
    xprop -id "$window" _NET_WM_NAME WM_NAME 2>/dev/null \
        | sed -n 's/^[^=]*= "\(.*\)"$/\1/p' | head -n 1
}

wait_for_window_size() {
    local window=$1 expected_width=$2 expected_height=$3 description=$4
    local deadline=$((SECONDS + 5)) observed=""
    while (( SECONDS < deadline )); do
        observed=$(window_size "$window" 2>/dev/null || true)
        if [[ "$observed" == "$expected_width $expected_height" ]]; then
            return 0
        fi
        sleep 0.05
    done
    printf 'native window did not reach requested size for %s (expected %sx%s, observed %s)\n' \
        "$description" "$expected_width" "$expected_height" "${observed:-unavailable}" >&2
    xwininfo -id "$window" >&2 || true
    return 1
}

resize_window_to() {
    local window=$1 width=$2 height=$3 description=$4
    xdotool windowsize "$window" "$width" "$height"
    wait_for_window_size "$window" "$width" "$height" "$description"
}

click_window_at() {
    local window=$1 x=$2 y=$3 description=${4:-window control} size width height focus
    local focus_deadline=$((SECONDS + 2))
    if [[ -n "${settings_window:-}" && "$window" == "$settings_window" ]]; then
        if ! xwininfo -id "$window" 2>/dev/null | grep -Fq 'Map State: IsViewable'; then
            # GTK may replace the top-level XID while a transient closes.
            settings_window=$(wait_for_window '^CodexBar Settings$')
            window=$settings_window
        fi
    fi
    xwininfo -id "$window" 2>/dev/null | grep -Fq 'Map State: IsViewable' || {
        echo "native click target is not viewable: $description" >&2
        return 1
    }
    size=$(window_size "$window") || {
        echo "native click target has no readable geometry: $description" >&2
        return 1
    }
    read -r width height <<<"$size"
    (( x >= 0 && y >= 0 && x < width && y < height )) || {
        printf 'native click target is outside window bounds for %s (point=%s,%s size=%s,%s)\n' \
            "$description" "$x" "$y" "$width" "$height" >&2
        return 1
    }
    xdotool windowactivate --sync "$window"
    focus=$(normalize_window_id "$(xdotool getwindowfocus 2>/dev/null || true)")
    while [[ "$focus" != "$(normalize_window_id "$window")" ]] && (( SECONDS < focus_deadline )); do
        sleep 0.05
        focus=$(normalize_window_id "$(xdotool getwindowfocus 2>/dev/null || true)")
    done
    [[ "$focus" == "$(normalize_window_id "$window")" ]] || {
        printf 'native click target did not receive focus for %s at %s,%s (target=%s focus=%s)\n' \
            "$description" "$x" "$y" "$window" "${focus:-unavailable}" >&2
        return 1
    }
    xdotool mousemove --sync --window "$window" "$x" "$y"
    # Let GTK process the motion/focus events before sending a short XTest
    # click; this keeps repeated toggles from racing the preceding response.
    sleep 0.05
    assert_pointer_within_window_tree "$window" "$description"
    xdotool mousedown --clearmodifiers 1
    sleep 0.05
    xdotool mouseup 1
    sleep 0.1
}

scroll_window_at() {
    local window=$1 x=$2 y=$3 button=$4 repeat=$5 description=$6
    local size width height
    xwininfo -id "$window" 2>/dev/null | grep -Fq 'Map State: IsViewable' || {
        echo "native scroll target is not viewable: $description" >&2
        return 1
    }
    size=$(window_size "$window") || {
        echo "native scroll target has no readable geometry: $description" >&2
        return 1
    }
    read -r width height <<<"$size"
    (( x >= 0 && y >= 0 && x < width && y < height )) || {
        printf 'native scroll target is outside window bounds for %s (point=%s,%s size=%s,%s)\n' \
            "$description" "$x" "$y" "$width" "$height" >&2
        return 1
    }
    xdotool mousemove --sync --window "$window" "$x" "$y"
    assert_pointer_within_window_tree "$window" "$description"
    xdotool click --repeat "$repeat" --delay 35 "$button"
}

dismiss_combo_popup_if_focused() {
    local focus
    focus=$(xdotool getwindowfocus 2>/dev/null || true)
    if [[ -n "${settings_window:-}" && -n "$focus" && "$focus" != "$settings_window" ]]; then
        xdotool key Escape
    fi
}

start_test_window_manager() {
    if [[ -n "$window_manager_pid" ]] && kill -0 "$window_manager_pid" 2>/dev/null; then
        local existing_deadline=$((SECONDS + 5))
        while ! window_manager_has_claimed_root && (( SECONDS < existing_deadline )); do sleep 0.05; done
        window_manager_has_claimed_root || {
            cat "$scratch/xfwm.log" >&2
            echo "Xvfb window manager process is alive but has not claimed the root window" >&2
            exit 1
        }
        return 0
    fi
    xfwm4 --replace --compositor=off >"$scratch/xfwm.log" 2>&1 &
    window_manager_pid=$!
    local deadline=$((SECONDS + 5))
    while ! window_manager_has_claimed_root && (( SECONDS < deadline )); do sleep 0.05; done
    window_manager_has_claimed_root || {
        cat "$scratch/xfwm.log" >&2
        echo "Xvfb window manager did not finish claiming the root for the native file chooser" >&2
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
    local title=$1 path=$2 button_x=$3 button_y=$4 chooser=""
    # Reuse one fully initialized test WM for all chooser actions so they all
    # run under the same verified X root owner.
    start_test_window_manager
    settings_window=$(wait_for_window '^CodexBar Settings$')
    resize_window_to "$settings_window" 1120 820 "Settings before $title chooser"
    click_window_at "$settings_window" "$button_x" "$button_y" "open $title chooser"
    chooser=$(wait_for_window "^${title}$")
    [[ "$(window_title "$chooser")" == "$title" ]] || {
        echo "native file chooser title did not match the requested action: $title" >&2
        exit 1
    }
    if [[ "$title" == "Export preferences" ]]; then
        capture_native_size "$chooser" "${NATIVE_SETTINGS_EXPORT_CHOOSER_SCREENSHOT:-}"
    fi
    if ! xdotool windowfocus --sync "$chooser" 2>/dev/null; then
        chooser=$(wait_for_window "^${title}$")
        if ! xdotool windowfocus --sync "$chooser" 2>"$scratch/chooser-focus.log"; then
            cat "$scratch/chooser-focus.log" >&2
            echo "native file chooser disappeared before it could receive keyboard focus: $title" >&2
            exit 1
        fi
    fi
    local focused_window
    focused_window=$(normalize_window_id "$(xdotool getwindowfocus 2>/dev/null || true)")
    [[ "$focused_window" == "$(normalize_window_id "$chooser")" ]] || {
        echo "native file chooser did not receive keyboard focus (title: $title)" >&2
        exit 1
    }
    # Xvfb starts without a window manager, so explicitly raise the real
    # titled chooser before pointer input. The title assertion above prevents
    # raising or interacting with the blank input-only XIDs from diagnostics.
    if ! xdotool windowraise "$chooser" 2>/dev/null; then
        chooser=$(wait_for_window "^${title}$")
        if ! xdotool windowraise "$chooser" 2>"$scratch/chooser-raise.log"; then
            cat "$scratch/chooser-raise.log" >&2
            echo "native file chooser disappeared before it could be raised: $title" >&2
            exit 1
        fi
    fi
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
        chooser=$(wait_for_window "^${title}$")
        xdotool key Return
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
        local target_name=${path##*/}
        capture_native_size "$chooser" "${NATIVE_SETTINGS_IMPORT_CHOOSER_SCREENSHOT:-}"
        # GTK's native chooser has a location entry on Ctrl+L. Address the
        # exact synthetic fixture path directly instead of deriving a row
        # coordinate from GTK's current sort order and theme-dependent row
        # height. Return asks the chooser to open/accept that exact file.
        xdotool key ctrl+l
        xdotool type --clearmodifiers --delay 1 "$path"
        if [[ "$target_name" == "preferences-import.json" ]]; then
            capture_native_size "$chooser" "${NATIVE_SETTINGS_IMPORT_SELECTED_SCREENSHOT:-}"
        else
            capture_native_size "$chooser" "${NATIVE_SETTINGS_EMPTY_IMPORT_SELECTED_SCREENSHOT:-}"
        fi
        xdotool key Return
        # The path entry can issue the response directly. Keep the existing
        # exact-path postcondition: a chooser that remains visible is failure,
        # and downstream persistence/reload assertions prove import behavior.
        local close_deadline=$((SECONDS + 5))
        while xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable' \
            && (( SECONDS < close_deadline )); do sleep 0.05; done
        if xwininfo -id "$chooser" 2>/dev/null | grep -Fq 'Map State: IsViewable'; then
            if [[ -n "${NATIVE_SETTINGS_IMPORT_AFTER_SCREENSHOT:-}" ]]; then
                capture_native_size "$chooser" "$NATIVE_SETTINGS_IMPORT_AFTER_SCREENSHOT"
            fi
            import_focus=$(normalize_window_id "$(xdotool getwindowfocus 2>/dev/null || true)")
            echo "native Import chooser remained mapped after accept (target=$path, focus=$import_focus, chooser=$chooser)" >&2
            xwininfo -id "$chooser" >&2 || true
            xwininfo -id "$chooser" -tree >&2 || true
            xprop -id "$chooser" WM_NAME WM_CLASS _NET_WM_PID 2>&1 || true
            echo "synthetic chooser-only diagnostic image: $scratch/import-chooser-failure.xwd" >&2
            xwd -silent -id "$chooser" -out "$scratch/import-chooser-failure.xwd" 2>/dev/null || true
            echo "native Import chooser did not close after selecting $target_name" >&2
            exit 1
        fi
    fi
    sleep 0.2
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
    resize_window_to "$window" 1120 820 "captured Settings page"
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
# Keep pointer input under one verified private window manager. The chooser
# path reuses this WM.
start_test_window_manager
resize_window_to "$settings_window" 1120 820 "initial Settings page"
click_window_at "$settings_window" 758 800 "fixed-coordinate control"
sleep 0.25
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_LOADING_SCREENSHOT:-}"
touch "$plugin_release_file"
wait_for_plugins_loaded 0
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_SCREENSHOT:-}"
click_window_at "$settings_window" 68 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_SCREENSHOT:-}"

# Exercise the remaining General controls using visible GTK controls and wait
# for the serialized preference write before the next pointer action.
click_window_at "$settings_window" 500 260 "fixed-coordinate control"
sleep 0.2
xdotool key Home Down Down Down Return
wait_for_preference refreshFrequency 5m
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 488 "show panel on start row"
wait_for_preference showPopupOnStart True
click_window_at "$settings_window" 500 488 "show panel on start row"
wait_for_preference showPopupOnStart False
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_ACTIONS_SCREENSHOT:-}"

# Exercise one live preference mutation and verify the durable JSON value.
click_window_at "$settings_window" 500 315 "fixed-coordinate control"
wait_for_preference refreshAllProvidersOnMenuOpen False

# Exercise the native launch-at-login switch and verify its private desktop
# entry is created atomically, then removed again through SettingsActor.
click_window_at "$settings_window" 500 432 "fixed-coordinate control"
wait_for_preference launchAtLogin True
autostart_deadline=$((SECONDS + 8))
while [[ ! -s "$autostart_file" ]] && (( SECONDS < autostart_deadline )); do sleep 0.05; done
expected_executable=$(readlink -f "$binary")
if [[ ! -s "$autostart_file" ]] || ! grep -Fx -- "Exec=\"$expected_executable\"" "$autostart_file" >/dev/null; then
    cat "$scratch/app.log" >&2
    echo "native launch-at-login switch did not write the expected executable entry" >&2
    exit 1
fi
# Do not send the off click until SettingsActor has persisted the enabled state
# and its response-settle interval has elapsed. Then require both the disabled
# preference and removal of the desktop entry; either failure remains visible.
click_window_at "$settings_window" 500 432 "fixed-coordinate control"
wait_for_preference launchAtLogin False
autostart_deadline=$((SECONDS + 8))
while [[ -e "$autostart_file" ]] && (( SECONDS < autostart_deadline )); do sleep 0.05; done
[[ ! -e "$autostart_file" ]] || {
    cat "$scratch/app.log" >&2
    echo "native launch-at-login switch did not remove its desktop entry" >&2
    exit 1
}

# Capture representative panes from the live PreferencesWindow.
click_window_at "$settings_window" 267 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_MENU_BAR_SCREENSHOT:-}"

# Exercise every Menu Bar preference through its visible GTK control and verify
# each write reaches the isolated PreferencesStore. The isolated home keeps the
# final hidden-tray value from changing the user's real preferences.
click_window_at "$settings_window" 500 142 "fixed-coordinate control"
sleep 0.2
xdotool key End Return
wait_for_preference menuBarIconStyle iconPercent
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 198 "unified icon source row"
sleep 0.2
xdotool key Home Return
wait_for_preference unifiedIconSource automatic
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 252 "fixed-coordinate control"
sleep 0.2
xdotool key End Return
wait_for_preference switcherRowsOption details
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 307 "fixed-coordinate control"
wait_for_preference showTray False
capture "$settings_window" "${NATIVE_SETTINGS_MENU_BAR_ACTIONS_SCREENSHOT:-}"

click_window_at "$settings_window" 68 800 "fixed-coordinate control"
sleep 0.3
click_window_at "$settings_window" 500 605 "fixed-coordinate control"
sleep 0.2
xdotool key Down Return
wait_for_preference preferredCurrencyCode USD
dismiss_combo_popup_if_focused

click_window_at "$settings_window" 166 800 "fixed-coordinate control"
sleep 0.3
click_window_at "$settings_window" 540 178 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PROVIDERS_SCREENSHOT:-}"
click_window_at "$settings_window" 500 234 "fixed-coordinate control"
wait_for_calls 'config disable --provider codex'
[[ "$(cat "$provider_enabled_file")" == "false" ]] || {
    echo "native provider switch did not disable the synthetic Codex provider" >&2
    exit 1
}
click_window_at "$settings_window" 500 234 "fixed-coordinate control"
wait_for_calls 'config enable --provider codex'
[[ "$(cat "$provider_enabled_file")" == "true" ]] || {
    echo "native provider switch did not re-enable the synthetic Codex provider" >&2
    exit 1
}
click_window_at "$settings_window" 500 289 "fixed-coordinate control"
sleep 0.2
xdotool key End Return
wait_for_calls 'config set-source --provider codex --source api'
dismiss_combo_popup_if_focused
[[ "$(cat "$provider_source_file")" == "api" ]] || {
    echo "native provider source selector did not reach the synthetic CLI" >&2
    exit 1
}
click_window_at "$settings_window" 500 398 "fixed-coordinate control"
xdotool type --clearmodifiers --delay 1 "$api_key_sentinel"
click_window_at "$settings_window" 777 398 "fixed-coordinate control"
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
click_window_at "$settings_window" 790 345 "fixed-coordinate control"
login_window=$(wait_for_window '^Sign in to CODEX$')
wait_for_file "$login_started_file" "synthetic login PTY start"
sleep 0.35
capture_native_size "$login_window" "${NATIVE_SETTINGS_LOGIN_PROMPT_SCREENSHOT:-}"
click_window_at "$login_window" 250 160 "fixed-coordinate control"
xdotool type --clearmodifiers --delay 1 "$login_code_sentinel"
click_window_at "$login_window" 465 205 "fixed-coordinate control"
wait_for_file "$login_complete_file" "synthetic login completion" 12
wait_for_file "$login_status_file" "GTK sign-in completion result" 5
[[ "$(cat "$login_status_file")" == "Sign-in completed." ]] || {
    echo "synthetic sign-in action did not display the completed result" >&2
    exit 1
}
sleep 0.4
capture_native_size "$login_window" "${NATIVE_SETTINGS_LOGIN_COMPLETE_SCREENSHOT:-}"
click_window_at "$login_window" 465 252 "fixed-coordinate control"
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

# Exercise the ClaudePlatform one-shot stdin flow with synthetic input. Only
# status-only dialog frames are retained; the password field is cleared on
# submit and the masked input frame is never written as an artifact.
scroll_window_at "$settings_window" 700 600 5 12 "Claude Platform provider row"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_CLAUDEPLATFORM_ROW_SCREENSHOT:-}"
click_window_at "$settings_window" 520 620 "fixed-coordinate control"
sleep 0.2
scroll_window_at "$settings_window" 700 720 5 1 "Claude Platform provider details"
sleep 0.2
capture "$settings_window" "${NATIVE_SETTINGS_CLAUDEPLATFORM_EXPANDED_SCREENSHOT:-}"
click_window_at "$settings_window" 790 693 "fixed-coordinate control"
claudeplatform_window=$(wait_for_window '^Sign in to Claude Platform$')
capture_native_size "$claudeplatform_window" "${NATIVE_SETTINGS_CLAUDEPLATFORM_PROMPT_SCREENSHOT:-}"
click_window_at "$claudeplatform_window" 220 68 "fixed-coordinate control"
xdotool type --clearmodifiers --delay 1 'sessionKey=synthetic-cookie-candidate'
click_window_at "$claudeplatform_window" 230 114 "fixed-coordinate control"
wait_for_file "$claudeplatform_cookie_file" "synthetic ClaudePlatform stdin submission"
wait_for_file "$claudeplatform_status_file" "ClaudePlatform sanitized completion status"
[[ "$(cat "$claudeplatform_status_file")" == "Claude Platform sign-in completed." ]] || {
    echo "ClaudePlatform login did not display sanitized success status" >&2
    exit 1
}
sleep 0.2
capture_native_size "$claudeplatform_window" "${NATIVE_SETTINGS_CLAUDEPLATFORM_STATUS_SCREENSHOT:-}"
for log_file in "$preferences_file" "${export_file:-$HOME/preferences-export.json}" "$NATIVE_SETTINGS_CALLS" "$scratch/app.log" "$NATIVE_SETTINGS_NOTIFICATION_LOG"; do
    if [[ -f "$log_file" ]] && grep -Fq 'synthetic-cookie-candidate' "$log_file"; then
        echo "synthetic ClaudePlatform input escaped into persisted or logged output" >&2
        exit 1
    fi
done
[[ "$(cat "$NATIVE_SETTINGS_CLAUDEPLATFORM_COOKIE_RECEIVED")" == 'sessionKey=synthetic-cookie-candidate' ]] || {
    echo "synthetic ClaudePlatform CLI did not receive the exact stdin value" >&2
    exit 1
}
click_window_at "$claudeplatform_window" 430 114 "close synthetic Claude Platform dialog"
claudeplatform_close_deadline=$((SECONDS + 5))
while xdotool getwindowname "$claudeplatform_window" >/dev/null 2>&1 \
    && (( SECONDS < claudeplatform_close_deadline )); do sleep 0.05; done
! xdotool getwindowname "$claudeplatform_window" >/dev/null 2>&1 || {
    echo "synthetic Claude Platform dialog did not close after completion" >&2
    exit 1
}
sleep 0.2
if [[ "${NATIVE_SETTINGS_CLAUDEPLATFORM_ONLY:-0}" == "1" ]]; then
    gapplication action com.steipete.CodexBarGTK quit
    wait "$app_pid"
    app_pid=
    printf 'native ClaudePlatform synthetic stdin login and joined shutdown smoke passed\n'
    exit 0
fi
click_window_at "$settings_window" 365 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_DISPLAY_SCREENSHOT:-}"
click_window_at "$settings_window" 500 142 "fixed-coordinate control"
wait_for_preference usageBarsShowUsed False
click_window_at "$settings_window" 500 197 "fixed-coordinate control"
sleep 0.2
xdotool key End Return
wait_for_preference resetTimesOption both
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 498 "fixed-coordinate control"
sleep 0.2
xdotool key End Return
wait_for_preference workdayTickAppearance highContrast
dismiss_combo_popup_if_focused
click_window_at "$settings_window" 500 552 "fixed-coordinate control"
wait_for_preference quotaBurndownEnabled False
click_window_at "$settings_window" 500 252 "fixed-coordinate control"
wait_for_preference paceVisible False
click_window_at "$settings_window" 500 307 "fixed-coordinate control"
wait_for_preference hidePersonalInfo True
click_window_at "$settings_window" 746 443 "fixed-coordinate control"
xdotool key ctrl+a
xdotool type --clearmodifiers 6
xdotool key Return
wait_for_preference weeklyProgressWorkDays 6
click_window_at "$settings_window" 746 689 "fixed-coordinate control"
xdotool key ctrl+a
xdotool type --clearmodifiers 70
xdotool key Return
wait_for_array_preference quotaWarningThresholds 0 70
click_window_at "$settings_window" 746 744 "fixed-coordinate control"
xdotool key ctrl+a
xdotool type --clearmodifiers 85
xdotool key Return
wait_for_array_preference quotaWarningThresholds 1 85
capture "$settings_window" "${NATIVE_SETTINGS_DISPLAY_ACTIONS_SCREENSHOT:-}"
click_window_at "$settings_window" 463 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_NOTIFICATIONS_SCREENSHOT:-}"
click_window_at "$settings_window" 500 142 "fixed-coordinate control"
wait_for_preference sessionQuotaNotificationsEnabled False
click_window_at "$settings_window" 500 197 "fixed-coordinate control"
wait_for_preference quotaWarningNotificationsEnabled False
click_window_at "$settings_window" 500 252 "fixed-coordinate control"
wait_for_preference limitResetNotificationsEnabled False
click_window_at "$settings_window" 500 307 "fixed-coordinate control"
wait_for_preference predictivePaceNotificationsEnabled False
click_window_at "$settings_window" 800 362 "fixed-coordinate control"
notification_deadline=$((SECONDS + 8))
while ! grep -q 'CodexBar GTK test notification' "$NATIVE_SETTINGS_NOTIFICATION_LOG" 2>/dev/null \
    && (( SECONDS < notification_deadline )); do sleep 0.05; done
grep -q 'CodexBar GTK test notification' "$NATIVE_SETTINGS_NOTIFICATION_LOG" || {
    cat "$scratch/app.log" "$scratch/notifications.log" >&2
    echo "Settings test-notification button did not reach the private notification service" >&2
    exit 1
}
capture "$settings_window" "${NATIVE_SETTINGS_NOTIFICATION_ACTION_SCREENSHOT:-}"
click_window_at "$settings_window" 562 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_SPEND_SCREENSHOT:-}"
click_window_at "$settings_window" 500 142 "fixed-coordinate control"
wait_for_preference costUsageEnabled False
click_window_at "$settings_window" 500 278 "fixed-coordinate control"
sleep 0.2
xdotool key Home Down Return
wait_for_nonempty_preference costUsageBucketTimeZone
dismiss_combo_popup_if_focused
capture "$settings_window" "${NATIVE_SETTINGS_SPEND_ACTION_SCREENSHOT:-}"
click_window_at "$settings_window" 660 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_SCREENSHOT:-}"
click_window_at "$settings_window" 500 160 "fixed-coordinate control"
wait_for_calls 'hooks disable'
[[ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" == "false" ]] || {
    echo "native Hooks switch did not persist disabled state through the synthetic CLI" >&2
    exit 1
}
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_ACTIONS_SCREENSHOT:-}"
click_window_at "$settings_window" 500 160 "fixed-coordinate control"
wait_for_calls 'hooks enable'
[[ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" == "true" ]] || {
    echo "native Hooks switch did not persist enabled state through the synthetic CLI" >&2
    exit 1
}
click_window_at "$settings_window" 758 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_SCREENSHOT:-}"
click_window_at "$settings_window" 856 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ADVANCED_SCREENSHOT:-}"

# Reconfigure to the same synthetic executable through the visible CLI-path
# entry. This validates the GTK apply action without switching away from the
# synthetic provider/auth fixture.
click_window_at "$settings_window" 500 158 "fixed-coordinate control"
xdotool type --clearmodifiers --delay 1 "$CODEXBAR_CLI"
click_window_at "$settings_window" 810 158 "apply synthetic CLI path"
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
click_window_at "$settings_window" 68 800 "fixed-coordinate control"
sleep 0.25
click_window_at "$settings_window" 500 432 "fixed-coordinate control"
wait_for_preference launchAtLogin True
wait_for_file "$autostart_file" "autostart entry before import/reset" 8
click_window_at "$settings_window" 856 800 "fixed-coordinate control"
sleep 0.25

# Export through the native Save chooser and verify the resulting portable JSON.
select_chooser_path "Export preferences" "$export_file" 790 333
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
select_chooser_path "Import preferences" "$import_file" 790 388
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
select_chooser_path "Import preferences" "$empty_import_file" 790 388
wait_for_plugins_loaded "$plugins_before"
hook_mode_deadline=$((SECONDS + 8))
while [[ "$(cat "$hooks_served_file" 2>/dev/null || true)" != "empty" ]] && (( SECONDS < hook_mode_deadline )); do sleep 0.05; done
[[ "$(cat "$hooks_served_file" 2>/dev/null || true)" == "empty" ]] || {
    echo "Settings reload did not query the empty synthetic Hooks rules" >&2
    exit 1
}
click_window_at "$settings_window" 660 800 "fixed-coordinate control"
sleep 0.4
capture "$settings_window" "${NATIVE_SETTINGS_HOOKS_EMPTY_RULES_SCREENSHOT:-}"
click_window_at "$settings_window" 758 800 "fixed-coordinate control"
sleep 0.4
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_EMPTY_SCREENSHOT:-}"

# The error fixture must render the sanitized read-only error state.
printf '%s\n' 'error' > "$plugins_mode_file"
rm -f "$plugin_loaded_file"
plugins_before=$(cat "$plugins_request_count_file")
click_window_at "$settings_window" 856 800 "fixed-coordinate control"
sleep 0.25
select_chooser_path "Import preferences" "$empty_import_file" 790 388
wait_for_plugins_loaded "$plugins_before"
sleep 0.35
click_window_at "$settings_window" 758 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_PLUGINS_ERROR_SCREENSHOT:-}"

# Reset requires explicit confirmation. First cancel and prove the imported
# values remain; then confirm and verify defaults while the autostart file stays.
click_window_at "$settings_window" 856 800 "fixed-coordinate control"
sleep 0.25
click_window_at "$settings_window" 790 443 "fixed-coordinate control"
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
click_window_at "$settings_window" 790 443 "fixed-coordinate control"
wait_for_window 'Reset all preferences' >/dev/null
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

click_window_at "$settings_window" 790 333 "fixed-coordinate control"
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
click_window_at "$settings_window" 1052 800 "fixed-coordinate control"
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_ABOUT_SCREENSHOT:-}"
click_window_at "$settings_window" 955 800 "fixed-coordinate control"
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
