#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${CODEXBAR_NATIVE_BINARY:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
output=${1:-"$repo_root/docs/rust-migration/screenshots/u04-panel-activate-open-wayland.png"}

if [[ -z "${WAYLAND_DISPLAY:-}" || -z "${XDG_RUNTIME_DIR:-}" ]]; then
    echo "run this capture from the active Wayland desktop session" >&2
    exit 2
fi
for tool in spectacle qdbus6 gdbus gapplication; do
    command -v "$tool" >/dev/null || { echo "missing capture dependency: $tool" >&2; exit 2; }
done
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }
if pgrep -x spectacle >/dev/null 2>&1; then
    echo "Spectacle already has a session service; close it before capture" >&2
    exit 2
fi
owner=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
[[ "$owner" == "(false,)" ]] || { echo "CodexBar GTK is already registered on this desktop session" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
mkdir -p "$scratch/home" "$scratch/home/.config" "$scratch/home/.local/share" "$scratch/home/.cache"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
set -eu
printf '%s\n' "${1-}" >> "$NATIVE_CLI_LOG"
case "${1-}" in
  --version) printf '%s\n' 'CodexBar synthetic fixture 0.82.0' ;;
  usage)
    printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":72.5,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":0,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080}}},{"provider":"claude","source":"synthetic","usage":{"extraRateWindows":[{"id":"unknown","title":"Unknown usage","usageKnown":false,"window":{"usedPercent":0,"windowMinutes":300}}]}},{"provider":"gemini","source":"synthetic","usage":{"primary":{"usedPercent":25,"windowMinutes":300}}},{"provider":"copilot","source":"synthetic","usage":{"primary":{"usedPercent":44,"windowMinutes":300}}},{"provider":"cursor","source":"synthetic","usage":{"primary":{"usedPercent":10,"windowMinutes":300}}},{"provider":"openai","source":"synthetic","usage":{"primary":{"usedPercent":0,"windowMinutes":300}}}]'
    : > "$NATIVE_USAGE_DONE"
    ;;
  cost) printf '%s\n' '[]'; : > "$NATIVE_COST_DONE" ;;
  sessions) printf '%s\n' '[]'; : > "$NATIVE_SESSIONS_DONE" ;;
  *) printf '%s\n' '[]' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"
export HOME="$scratch/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share" XDG_CACHE_HOME="$HOME/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_USAGE_DONE="$scratch/usage-done" NATIVE_COST_DONE="$scratch/cost-done" NATIVE_SESSIONS_DONE="$scratch/sessions-done"
export NATIVE_CLI_LOG="$scratch/cli-calls"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=wayland GSK_RENDERER=cairo

app_pid=
spectacle_started=0
spectacle_owner() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.kde.spectacle 2>/dev/null
}
cleanup() {
    gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
    if [[ -n "$app_pid" ]]; then wait "$app_pid" 2>/dev/null || true; fi
    if [[ "$spectacle_started" == "1" ]]; then
        qdbus6 org.kde.spectacle /MainApplication org.qtproject.Qt.QCoreApplication.quit >/dev/null 2>&1 || true
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT

wait_for_tray_name() {
    local deadline=$((SECONDS + 12))
    while (( SECONDS < deadline )); do
        if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk 2>/dev/null \
            | grep -q '(true,)'; then
            return 0
        fi
        sleep 0.05
    done
    cat "$scratch/app.log" >&2
    echo "native SNI did not acquire its session-bus name on Wayland" >&2
    exit 1
}

usage_calls() {
    awk '$0 == "usage" { n++ } END { print n + 0 }' "$NATIVE_CLI_LOG" 2>/dev/null
}

wait_usage_calls() {
    local target=$1 deadline=$((SECONDS + 12)) count
    while (( SECONDS < deadline )); do
        count=$(usage_calls)
        (( count >= target )) && break
        sleep 0.05
    done
    count=$(usage_calls)
    [[ "$count" == "$target" ]] || {
        echo "Wayland SNI expected $target synthetic usage calls, saw $count" >&2
        cat "$scratch/app.log" >&2
        exit 1
    }
    sleep 0.3
    [[ "$(usage_calls)" == "$target" ]] || {
        echo "Wayland synthetic usage calls were not stable at $target" >&2
        exit 1
    }
}

capture_active_window() {
    local target=$1 owner deadline
    owner=$(spectacle_owner)
    [[ "$owner" == "(false,)" ]] || { echo "Spectacle retained its Wayland D-Bus name between captures" >&2; exit 1; }
    spectacle_started=1
    spectacle --background --activewindow --nonotify --output "$target"
    [[ -s "$target" ]] || { echo "Wayland screenshot was not created: $target" >&2; exit 1; }
    qdbus6 org.kde.spectacle /MainApplication org.qtproject.Qt.QCoreApplication.quit >/dev/null 2>&1 || true
    deadline=$((SECONDS + 5))
    while (( SECONDS < deadline )); do
        owner=$(spectacle_owner)
        [[ "$owner" == "(false,)" ]] && break
        sleep 0.05
    done
    [[ "$owner" == "(false,)" ]] || { echo "Spectacle did not release its Wayland D-Bus name" >&2; exit 1; }
    spectacle_started=0
}

"$binary" --page usage >"$scratch/app.log" 2>&1 &
app_pid=$!
wait_for_tray_name
deadline=$((SECONDS + 20))
while [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
if [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" ]]; then
    cat "$scratch/app.log" >&2
    echo "synthetic panel refresh did not finish" >&2
    exit 1
fi

# Exercise the live SNI methods over the desktop session bus. GTK/GDK leaves
# surface placement to the Wayland compositor; captures show the focused
# native surface after each event but do not claim pointer or keyboard input.
: > "$NATIVE_CLI_LOG"
gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem \
    --method org.kde.StatusNotifierItem.Activate 31 47 >/dev/null
wait_usage_calls 1
[[ -d "$(dirname "$output")" ]] || mkdir -p "$(dirname "$output")"

gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem \
    --method org.kde.StatusNotifierItem.SecondaryActivate 53 61 >/dev/null
wait_usage_calls 2

gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem \
    --method org.kde.StatusNotifierItem.ContextMenu 79 83 >/dev/null
wait_usage_calls 3
sleep 1
capture_active_window "$output"

gdbus call --session --dest org.kde.StatusNotifierItem-codexbar-gtk --object-path /StatusNotifierItem \
    --method org.kde.StatusNotifierItem.Activate 31 47 >/dev/null
sleep 1
[[ "$(usage_calls)" == 3 ]] || { echo "Wayland Activate while visible unexpectedly refreshed" >&2; exit 1; }

# Exercise the central action bindings through the same session-bus actions
# that the tray and downstream native pages will use.
gapplication action com.steipete.CodexBarGTK panel
gapplication action com.steipete.CodexBarGTK panel
gapplication action com.steipete.CodexBarGTK settings
gapplication action com.steipete.CodexBarGTK page "'sessions'"
gapplication action com.steipete.CodexBarGTK about
printf 'captured synthetic SNI panel on Wayland: %s; Activate/SecondaryActivate/ContextMenu refresh counts passed; Activate-while-visible did not refresh; placement is compositor-owned\n' \
    "$output"
