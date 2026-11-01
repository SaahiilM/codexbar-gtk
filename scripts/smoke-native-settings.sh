#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}

for tool in xvfb-run dbus-run-session xdotool gapplication gdbus xwd ffmpeg python3 grep; do
    command -v "$tool" >/dev/null || { echo "missing smoke dependency: $tool" >&2; exit 2; }
done

if [[ "${CODEXBAR_NATIVE_SETTINGS_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_SETTINGS_INNER=1 "$0" "$binary"
fi

[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
notification_pid=
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
    if [[ "${NATIVE_SETTINGS_KEEP_TMP:-0}" == "1" ]]; then
        echo "synthetic settings smoke files kept at $scratch" >&2
    else
        rm -rf "$scratch"
    fi
}
trap cleanup EXIT

python3 -c 'import dbus, gi' >/dev/null 2>&1 || {
    echo "native Settings notification smoke needs python3-dbus and python3-gi" >&2
    exit 2
}

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
    if [ "$(cat "$NATIVE_SETTINGS_HOOKS_ENABLED")" = "true" ]; then
      printf '%s\n' '{"enabled":true,"events":[{"event":"quota.warning","enabled":true,"command":"/tmp/synthetic-hook"}]}'
    else
      printf '%s\n' '{"enabled":false,"events":[{"event":"quota.warning","enabled":true,"command":"/tmp/synthetic-hook"}]}'
    fi
    ;;
  hooks/enable)
    printf '%s\n' 'true' > "$NATIVE_SETTINGS_HOOKS_ENABLED"
    ;;
  hooks/disable)
    printf '%s\n' 'false' > "$NATIVE_SETTINGS_HOOKS_ENABLED"
    ;;
  plugins/list)
    printf '%s\n' '[{"id":"fixture-plugin","name":"Synthetic Provider","version":"1.0"}]'
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

export HOME="$scratch/home"
export XDG_RUNTIME_DIR="$scratch/runtime"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_SETTINGS_CALLS="$scratch/cli-calls"
export NATIVE_SETTINGS_HOOKS_ENABLED="$scratch/hooks-enabled"
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

"$binary" --settings >"$scratch/app.log" 2>&1 &
app_pid=$!

wait_for_window() {
    local pattern=$1 deadline=$((SECONDS + 15)) window=""
    while [[ -z "$window" ]] && (( SECONDS < deadline )); do
        window=$(xdotool search --onlyvisible --name "$pattern" 2>/dev/null | head -n 1 || true)
        [[ -n "$window" ]] || sleep 0.05
    done
    [[ -n "$window" ]] || {
        cat "$scratch/app.log" >&2
        while read -r visible_window; do
            printf 'visible window %s: ' "$visible_window" >&2
            xdotool getwindowname "$visible_window" >&2 || true
        done < <(xdotool search --onlyvisible --name '.*' 2>/dev/null || true)
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

settings_window=$(wait_for_window 'CodexBar Settings')
wait_for_calls 'config providers'
wait_for_calls 'hooks list --format json'
wait_for_calls 'plugins list'
sleep 0.4
# Keep pointer-based checks independent of whether CI requested screenshots.
xdotool windowsize "$settings_window" 1120 820
sleep 0.3
capture "$settings_window" "${NATIVE_SETTINGS_GENERAL_SCREENSHOT:-}"

# Exercise one live preference mutation and verify the durable JSON value.
preferences_file="$HOME/.config/codexbar-gtk/settings.json"
xdotool mousemove --window "$settings_window" 810 315 click 1
wait_for_preference refreshAllProvidersOnMenuOpen False

# Exercise the native launch-at-login switch and verify its private desktop
# entry is created atomically, then removed again through SettingsActor.
autostart_file="$HOME/.config/autostart/codexbar-gtk.desktop"
xdotool mousemove --window "$settings_window" 810 432 click 1
autostart_deadline=$((SECONDS + 8))
while [[ ! -s "$autostart_file" ]] && (( SECONDS < autostart_deadline )); do sleep 0.05; done
expected_executable=$(readlink -f "$binary")
[[ -s "$autostart_file" ]] && grep -Fx -- "Exec=\"$expected_executable\"" "$autostart_file" >/dev/null || {
    cat "$scratch/app.log" >&2
    echo "native launch-at-login switch did not write the expected executable entry" >&2
    exit 1
}
xdotool mousemove --window "$settings_window" 810 432 click 1
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
before_dialog_windows=$(xdotool search --onlyvisible --name '.*' 2>/dev/null | sort -n || true)
xdotool mousemove --window "$settings_window" 790 333 click 1
dialog_deadline=$((SECONDS + 8))
new_dialog_windows=
while (( SECONDS < dialog_deadline )); do
    new_dialog_windows=$(comm -13 <(printf '%s\n' "$before_dialog_windows" | sed '/^$/d') \
        <(xdotool search --onlyvisible --name '.*' 2>/dev/null | sort -n || true) || true)
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
    still_open_windows=$(comm -13 <(printf '%s\n' "$before_dialog_windows" | sed '/^$/d') \
        <(xdotool search --onlyvisible --name '.*' 2>/dev/null | sort -n || true) || true)
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
printf 'native Settings synthetic CLI, Hooks enable/disable persistence, Menu Bar/currency/display/notification/time-zone controls, private notification action, preference persistence, all settings panes, central About route, and GTK lifecycle smoke passed\n'
