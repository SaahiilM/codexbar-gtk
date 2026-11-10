#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${CODEXBAR_NATIVE_BINARY:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
output=${1:-"$repo_root/docs/rust-migration/screenshots/u02-dashboard-wayland.png"}

if [[ -z "${WAYLAND_DISPLAY:-}" || -z "${XDG_RUNTIME_DIR:-}" ]]; then
    echo "run this capture from the active Wayland desktop session" >&2
    exit 2
fi
if ! command -v spectacle >/dev/null && ! command -v grim >/dev/null; then
    echo "install Spectacle or grim for a Wayland screenshot" >&2
    exit 2
fi
if command -v spectacle >/dev/null; then
    command -v qdbus6 >/dev/null || { echo "missing qdbus6 for the KDE compositor capture" >&2; exit 2; }
    if pgrep -x spectacle >/dev/null 2>&1; then
        echo "Spectacle already has a session service; close it before capture" >&2
        exit 2
    fi
fi
command -v gdbus >/dev/null || { echo "missing gdbus to check the app's single-instance service" >&2; exit 2; }
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }
mkdir -p "$(dirname "$output")"
owner=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
[[ "$owner" == "(false,)" ]] || { echo "CodexBar GTK is already registered on this desktop session" >&2; exit 2; }

scratch=$(mktemp -d)
chmod 700 "$scratch"
mkdir -p "$scratch/home" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
set -eu
case "${1-}" in
  --version) printf '%s\n' 'CodexBar synthetic fixture 0.82.0' ;;
  usage)
    printf '%s\n' '[{"provider":"codex","source":"synthetic","pace":{"primary":{"stage":"slightlyAhead","deltaPercent":18}},"credits":{"remaining":25.5,"creditsAvailable":true,"unit":"credits"},"usage":{"identity":{"accountEmail":"synthetic@example.invalid"},"updatedAt":"2026-10-31T12:00:00Z","primary":{"usedPercent":72.5,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":0,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080},"codexResetCredits":{"credits":[{"status":"available","title":"Synthetic reset credit","expiresAt":"2026-11-01T18:00:00Z"}]},"providerCost":{"used":12.5,"limit":100,"currencyCode":"USD","period":"This month","balance":25}}},{"provider":"claude","source":"synthetic","usage":{"extraRateWindows":[{"id":"unknown","title":"Unknown usage","usageKnown":false,"window":{"usedPercent":0,"windowMinutes":300}}]}}]'
    : > "$NATIVE_USAGE_DONE"
    ;;
  cost)
    printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totals":{"totalCost":12.5,"totalTokens":1200,"priced":true}}]'
    : > "$NATIVE_COST_DONE"
    ;;
  sessions)
    printf '%s\n' '[]'
    : > "$NATIVE_SESSIONS_DONE"
    ;;
  *) printf '%s\n' '[]' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"
export HOME="$scratch/home" XDG_CONFIG_HOME="$scratch/home/.config" XDG_DATA_HOME="$scratch/home/.local/share" XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar" NATIVE_USAGE_DONE="$scratch/usage-done" NATIVE_COST_DONE="$scratch/cost-done" NATIVE_SESSIONS_DONE="$scratch/sessions-done"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=wayland GSK_RENDERER=cairo

"$binary" >"$scratch/app.log" 2>&1 &
app_pid=$!
spectacle_started=0
cleanup() {
    gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
    wait "$app_pid" 2>/dev/null || true
    if [[ "$spectacle_started" == "1" ]]; then
        qdbus6 org.kde.spectacle /MainApplication org.qtproject.Qt.QCoreApplication.quit >/dev/null 2>&1 || true
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT

deadline=$((SECONDS + 20))
while [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" ]] && (( SECONDS < deadline )); do sleep 0.05; done
if [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" ]]; then
    cat "$scratch/app.log" >&2
    echo "synthetic dashboard refresh did not finish" >&2
    exit 1
fi
sleep 3
window=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
[[ "$window" == "(true,)" ]] || { echo "native application did not register" >&2; exit 1; }
if command -v spectacle >/dev/null; then
    spectacle_started=1
    spectacle --background --activewindow --nonotify --output "$output"
else
    grim "$output"
fi
[[ -s "$output" ]] || { echo "capture did not produce a screenshot" >&2; exit 1; }
printf 'captured synthetic native dashboard: %s\n' "$output"
