#!/usr/bin/env bash
# Private-container installer command-target and version rollback evidence.
# Desktop Exec and service ExecStart are parsed and launched directly because
# this runtime image has no systemd manager. This is not service lifecycle.
set -euo pipefail
OLD=/artifacts/previous
CURRENT=/artifacts/current
INSTALLER=/work/installer/scripts/install-native.sh
PREFIX='/tmp/native prefix with spaces'
HOME=/tmp/home
APP_PID=
XVFB_PID=
DBUS_PID=
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "PASS: $*"; }
# shellcheck disable=SC1091
source /work/service-proof-lib.sh
trap 'exit 130' INT
trap 'exit 143' TERM
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  stop_reap "$APP_PID" || echo 'cleanup: app process did not stop within bounded grace' >&2
  stop_reap "$XVFB_PID" || echo 'cleanup: Xvfb did not stop within bounded grace' >&2
  stop_reap "$DBUS_PID" || echo 'cleanup: private D-Bus did not stop within bounded grace' >&2
  exit "$rc"
}
trap cleanup EXIT
export HOME XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share" \
  XDG_CACHE_HOME="$HOME/.cache" XDG_RUNTIME_DIR=/tmp/runtime \
  DISPLAY=:99 GDK_BACKEND=x11 GTK_A11Y=none GTK_USE_PORTAL=0 GSK_RENDERER=cairo \
  DBUS_SESSION_BUS_ADDRESS=unix:abstract=/tmp/dbus/bus \
  PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  CODEXBAR_CLI="$HOME/.local/bin/codexbar"
mkdir -p /tmp/runtime "$HOME/.config/codexbar-gtk" "$HOME/.config/systemd/user" "$HOME/.config/autostart" \
  "$HOME/.local/bin" "$PREFIX/share/applications"
chmod 700 /tmp/runtime
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --nofork >/tmp/dbus.log 2>&1 &
DBUS_PID=$!
for _ in $(seq 1 30); do
  gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.ListNames --timeout 2 >/dev/null 2>&1 && break
  sleep 0.2
done
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.ListNames --timeout 2 >/dev/null 2>&1 || fail 'private D-Bus unavailable'

# shellcheck disable=SC1091
source /work/service-targets.sh
dbus_call() { gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method "org.freedesktop.DBus.$1" "${@:2}" --timeout 3; }
name_has_owner() { dbus_call NameHasOwner "$1" 2>/dev/null | grep -q '(true,)'; }
wait_gone() {
  local name=$1
  for _ in $(seq 1 30); do name_has_owner "$name" || return 0; sleep 0.2; done
  return 1
}
cat > "$HOME/.local/bin/codexbar" <<'CLI'
#!/bin/sh
printf '%s\n' "$*" >> "$HOME/cli.log"
printf '{"ok":true,"providers":[]}\n'
CLI
chmod 755 "$HOME/.local/bin/codexbar"
: > "$HOME/cli.log"
printf '%s\n' '{"preferredCurrencyCode":"auto","refreshIntervalSeconds":300,"launchAtLogin":false,"synthetic":"service-proof"}' > "$HOME/.config/codexbar-gtk/settings.json"
printf '%s\n' '{"t":1794009600.0,"p":"synthetic","w":"primary","u":0.0}' > "$HOME/.config/codexbar-gtk/history.jsonl"
SETTINGS_SHA=$(sha256sum "$HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')
HISTORY_SHA=$(sha256sum "$HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')

DESKTOP="$PREFIX/share/applications/codexbar-gtk.desktop"
UNIT="$HOME/.config/systemd/user/codexbar-gtk.service"
printf '[Desktop Entry]\nType=Application\nName=Legacy synthetic launcher\nExec=/usr/bin/python3 -m codexbar_gtk\n' > "$DESKTOP"
printf '[Service]\nDescription=Legacy synthetic service\nExecStart=/usr/bin/python3 -m codexbar_gtk\n' > "$UNIT"
DESKTOP_ORIGINAL=$(sha256sum "$DESKTOP" | awk '{print $1}')
UNIT_ORIGINAL=$(sha256sum "$UNIT" | awk '{print $1}')

"$INSTALLER" --artifact "$OLD" --prefix "$PREFIX" --activate
MANIFEST="$PREFIX/share/codexbar-gtk/native-manifest"
[[ $(grep -c '^activated=1$' "$MANIFEST") == 1 ]] || fail 'previous install did not record activation'
[[ $(sha256sum "$DESKTOP.pre-native" | awk '{print $1}') == "$DESKTOP_ORIGINAL" ]] || fail 'desktop backup provenance mismatch'
[[ $(sha256sum "$UNIT.pre-native" | awk '{print $1}') == "$UNIT_ORIGINAL" ]] || fail 'service backup provenance mismatch'
OLD_SHA=$(sha256sum "$OLD" | awk '{print $1}')
DESKTOP_TARGET=$(desktop_exec_target "$DESKTOP") || fail 'could not parse installed desktop Exec'
UNIT_TARGET=$(service_exec_target "$UNIT") || fail 'could not parse installed service ExecStart'
[[ "$DESKTOP_TARGET" == "$PREFIX/bin/codexbar-gtk-native" && "$UNIT_TARGET" == "$DESKTOP_TARGET" ]] || fail 'activated entries do not share canonical binary identity'
ok "previous version activated; desktop and service targets agree ($DESKTOP_TARGET)"

probe_target() {
  local label=$1 target=$2 expected=$3 pid owner exe sha
  name_has_owner com.steipete.CodexBarGTK && fail "$label started while app ID already owned"
  name_has_owner org.kde.StatusNotifierItem-codexbar-gtk && fail "$label started while old SNI name owned"
  "$target" >"/tmp/$label.log" 2>&1 & pid=$!; APP_PID=$pid
  local ready=0
  for _ in $(seq 1 40); do
    if name_has_owner com.steipete.CodexBarGTK; then ready=1; break; fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  [[ $ready == 1 ]] || { cat "/tmp/$label.log" >&2; fail "$label did not acquire app bus name"; }
  owner=$(dbus_call GetConnectionUnixProcessID com.steipete.CodexBarGTK | sed -nE 's/^\(uint32 ([0-9]+),\)$/\1/p')
  [[ "$owner" == "$pid" ]] || fail "$label owner PID $owner != launched PID $pid"
  exe=$(readlink -f "/proc/$owner/exe")
  sha=$(sha256sum "/proc/$owner/exe" | awk '{print $1}')
  [[ "$exe" == "$target" && "$sha" == "$expected" ]] || fail "$label executable identity/hash mismatch ($exe $sha)"
  local calls_before calls_after
  calls_before=$(wc -l < "$HOME/cli.log")
  run_required_action "$label refresh action" gdbus call --session --dest com.steipete.CodexBarGTK --object-path /com/steipete/CodexBarGTK --method org.gtk.Actions.Activate refresh '[]' '{}' --timeout 5 >/dev/null || fail "$label refresh action call failed"
  for _ in $(seq 1 40); do
    calls_after=$(wc -l < "$HOME/cli.log")
    (( calls_after > calls_before )) && break
    kill -0 "$pid" 2>/dev/null || fail "$label exited before CLI refresh was observed"
    sleep 0.25
  done
  (( calls_after > calls_before )) || fail "$label refresh action did not increase synthetic CLI call count"
  run_required_action "$label quit action" gdbus call --session --dest com.steipete.CodexBarGTK --object-path /com/steipete/CodexBarGTK --method org.gtk.Actions.Activate quit '[]' '{}' --timeout 5 >/dev/null || fail "$label quit action call failed"
  for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  if kill -0 "$pid" 2>/dev/null; then fail "$label graceful quit timed out"; fi
  wait "$pid" || fail "$label exited nonzero"
  APP_PID=""
  wait_gone com.steipete.CodexBarGTK || fail "$label left app bus owner behind"
  wait_gone org.kde.StatusNotifierItem-codexbar-gtk || fail "$label left SNI owner behind"
  echo "EVIDENCE:$label=PASS owner-pid=$owner exe=$exe sha=$sha quit=0 app-owner=gone sni-owner=gone"
}

# Execute parsed desktop Exec target for old release, then upgrade the same
# activated prefix and launch the parsed service ExecStart target.
probe_target previous-desktop "$DESKTOP_TARGET" "$OLD_SHA"
CURRENT_SHA=$(sha256sum "$CURRENT" | awk '{print $1}')
"$INSTALLER" --artifact "$CURRENT" --prefix "$PREFIX"
[[ $(grep -c '^activated=1$' "$MANIFEST") == 1 ]] || fail 'upgrade lost activation state'
[[ $(sha256sum "$DESKTOP.pre-native" | awk '{print $1}') == "$DESKTOP_ORIGINAL" ]] || fail 'upgrade replaced desktop backup provenance'
[[ $(sha256sum "$UNIT.pre-native" | awk '{print $1}') == "$UNIT_ORIGINAL" ]] || fail 'upgrade replaced service backup provenance'
DESKTOP_TARGET=$(desktop_exec_target "$DESKTOP") || fail 'current desktop Exec parse failed'
UNIT_TARGET=$(service_exec_target "$UNIT") || fail 'current service ExecStart parse failed'
[[ "$DESKTOP_TARGET" == "$UNIT_TARGET" && "$UNIT_TARGET" == "$PREFIX/bin/codexbar-gtk-native" ]] || fail 'current activation entry identities diverged'
[[ ! -e "$HOME/.config/autostart/codexbar-gtk.desktop" ]] || fail 'installer created duplicate autostart authority'
probe_target current-service "$UNIT_TARGET" "$CURRENT_SHA"

"$INSTALLER" --artifact "$OLD" --prefix "$PREFIX"
[[ $(grep -c '^activated=1$' "$MANIFEST") == 1 ]] || fail 'rollback lost activation state'
[[ $(sha256sum "$DESKTOP.pre-native" | awk '{print $1}') == "$DESKTOP_ORIGINAL" ]] || fail 'rollback changed desktop backup provenance'
[[ $(sha256sum "$UNIT.pre-native" | awk '{print $1}') == "$UNIT_ORIGINAL" ]] || fail 'rollback changed service backup provenance'
DESKTOP_TARGET=$(desktop_exec_target "$DESKTOP") || fail 'rollback desktop Exec parse failed'
UNIT_TARGET=$(service_exec_target "$UNIT") || fail 'rollback service ExecStart parse failed'
[[ "$DESKTOP_TARGET" == "$UNIT_TARGET" ]] || fail 'rollback activation identities diverged'
probe_target rollback-desktop "$DESKTOP_TARGET" "$OLD_SHA"

# Simulate a user's edit after activation; uninstall must retain that edit and
# still restore untouched legacy files where their installed files were owned.
printf '[Service]\nDescription=user edit\nExecStart=/usr/bin/true\n' > "$UNIT"
USER_UNIT_SHA=$(sha256sum "$UNIT" | awk '{print $1}')
"$INSTALLER" --uninstall --prefix "$PREFIX"
[[ $(sha256sum "$UNIT" | awk '{print $1}') == "$USER_UNIT_SHA" ]] || fail 'uninstall overwrote edited service file'
[[ $(sha256sum "$DESKTOP" | awk '{print $1}') == "$DESKTOP_ORIGINAL" ]] || fail 'uninstall failed to restore legacy desktop'
[[ $(sha256sum "$UNIT.pre-native" | awk '{print $1}') == "$UNIT_ORIGINAL" ]] || fail 'uninstall lost original service backup provenance'
[[ ! -e "$PREFIX/bin/codexbar-gtk-native" ]] || fail 'uninstall left native binary'
[[ ! -e "$MANIFEST" ]] || fail 'uninstall left manifest'
[[ $(sha256sum "$HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}') == "$SETTINGS_SHA" ]] || fail 'settings bytes changed'
[[ $(sha256sum "$HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}') == "$HISTORY_SHA" ]] || fail 'history bytes changed'
[[ ! -e "$HOME/.config/autostart/codexbar-gtk.desktop" ]] || fail 'unexpected autostart authority exists'
echo 'EVIDENCE:activation-backup-restore=PASS legacy-desktop-restored user-edited-service-retained'
echo 'EVIDENCE:settings-history=PASS byte-preserved synthetic fixtures'
echo 'EVIDENCE:service-scope=COMMAND-TARGET proof only; no systemd manager/service lifecycle was run'
