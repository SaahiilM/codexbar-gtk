#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${1:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
if [[ "${CODEXBAR_NATIVE_DASHBOARD_SMOKE_INNER:-}" != "1" ]]; then
    exec xvfb-run -a dbus-run-session -- env CODEXBAR_NATIVE_DASHBOARD_SMOKE_INNER=1 "$0" "$binary"
fi

for tool in xdotool gapplication timeout; do
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
    rm -rf "$scratch"
}
trap cleanup EXIT
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

export HOME="$scratch/home"
export XDG_RUNTIME_DIR="$scratch/runtime"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_USAGE_DONE="$scratch/usage-done"
export NATIVE_COST_DONE="$scratch/cost-done"
export NATIVE_SESSIONS_DONE="$scratch/sessions-done"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=x11 GSK_RENDERER=cairo

"$binary" >"$scratch/app.log" 2>&1 &
app_pid=$!
deadline=$((SECONDS + 15))
while [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ -e "$NATIVE_USAGE_DONE" && -e "$NATIVE_COST_DONE" && -e "$NATIVE_SESSIONS_DONE" ]] || {
    cat "$scratch/app.log" >&2
    echo "synthetic refresh did not complete" >&2
    exit 1
}

window=$(xdotool search --onlyvisible --name 'CodexBar GTK' 2>/dev/null | head -n 1 || true)
[[ -n "$window" ]] || { cat "$scratch/app.log" >&2; echo "native dashboard window did not appear" >&2; exit 1; }
window_title=$(xdotool getwindowname "$window")
[[ "$window_title" == *Dashboard* ]] || { echo "expected dashboard window, got '$window_title'" >&2; exit 1; }
gapplication action com.steipete.CodexBarGTK refresh
sleep 0.25
gapplication action com.steipete.CodexBarGTK settings
deadline=$((SECONDS + 5))
while [[ "$(xdotool getwindowname "$window" 2>/dev/null || true)" != *Settings* ]] && (( SECONDS < deadline )); do sleep 0.05; done
window_title=$(xdotool getwindowname "$window" 2>/dev/null || true)
[[ "$window_title" == *Settings* ]] || {
    cat "$scratch/app.log" >&2
    echo "dashboard Settings action did not open the settings placeholder" >&2
    exit 1
}
gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=
printf 'native dashboard synthetic refresh and GTK lifecycle smoke passed\n'
