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
  --version)
    printf '%s\n' 'CodexBar synthetic fixture 0.82.0'
    : > "$NATIVE_VERSION_DONE"
    ;;
  usage)
    cat <<'JSON'
[{"provider":"codex","source":"synthetic","pace":{"primary":{"stage":"slightlyAhead","deltaPercent":18}},"credits":{"remaining":25.5,"creditsAvailable":true,"unit":"credits","events":[{"id":"fixture-credit-1","date":"2026-10-29","service":"synthetic","creditsUsed":8.5},{"id":"fixture-credit-2","date":"2026-10-30","service":"synthetic","creditsUsed":3.25}]},"usage":{"identity":{"accountEmail":"synthetic@example.invalid"},"updatedAt":"2026-10-31T12:00:00Z","primary":{"usedPercent":72.5,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":0,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080},"details":[{"title":"Synthetic model usage","chart":{"kind":"bars","title":"Tokens by model","unit":"tokens","points":[{"label":"Model A","value":220},{"label":"Model B","value":145},{"label":"Model C","value":80}]}}],"codexResetCredits":{"credits":[{"status":"available","title":"Synthetic reset credit","expiresAt":"2026-11-01T18:00:00Z"}]},"providerCost":{"used":12.5,"limit":100,"currencyCode":"USD","period":"This month","balance":25,"resetsAt":"2026-11-30T00:00:00Z"}}},{"provider":"claude","source":"synthetic","usage":{"extraRateWindows":[{"id":"unknown","title":"Unknown usage","usageKnown":false,"window":{"usedPercent":0,"windowMinutes":300}}]}}]
JSON
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
export NATIVE_VERSION_DONE="$scratch/version-done"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=x11 GSK_RENDERER=cairo
mkdir -p "$HOME/.config/codexbar-gtk"
history_now=$(date +%s)
printf '{"t":%s,"p":"codex","w":"primary","u":40}\n{"t":%s,"p":"codex","w":"primary","u":55}\n' \
  "$((history_now - 1800))" "$((history_now - 900))" \
  > "$HOME/.config/codexbar-gtk/history.jsonl"

"$binary" >"$scratch/app.log" 2>&1 &
app_pid=$!
deadline=$((SECONDS + 15))
while [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_COST_DONE" || ! -e "$NATIVE_SESSIONS_DONE" || ! -e "$NATIVE_VERSION_DONE" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
[[ -e "$NATIVE_USAGE_DONE" && -e "$NATIVE_COST_DONE" && -e "$NATIVE_SESSIONS_DONE" && -e "$NATIVE_VERSION_DONE" ]] || {
    cat "$scratch/app.log" >&2
    echo "synthetic refresh did not complete" >&2
    exit 1
}

window=""
window_deadline=$((SECONDS + 10))
while [[ -z "$window" ]] && (( SECONDS < window_deadline )); do
    window=$(xdotool search --onlyvisible --name 'CodexBar GTK' 2>/dev/null | head -n 1 || true)
    [[ -n "$window" ]] || sleep 0.05
done
[[ -n "$window" ]] || { cat "$scratch/app.log" >&2; echo "native dashboard window did not appear" >&2; exit 1; }
window_title=$(xdotool getwindowname "$window")
[[ "$window_title" == *Dashboard* ]] || { echo "expected dashboard window, got '$window_title'" >&2; exit 1; }
sleep 0.5
if [[ -n "${NATIVE_DASHBOARD_SCREENSHOT:-}" ]]; then
    command -v xwd >/dev/null || { echo "missing screenshot dependency: xwd" >&2; exit 2; }
    command -v ffmpeg >/dev/null || { echo "missing screenshot dependency: ffmpeg" >&2; exit 2; }
    mkdir -p "$(dirname "$NATIVE_DASHBOARD_SCREENSHOT")"
    xdotool windowsize "$window" 1120 930
    sleep 0.3
    xwd -silent -id "$window" -out "$scratch/dashboard.xwd"
    ffmpeg -nostdin -y -loglevel error -f xwd_pipe -i "$scratch/dashboard.xwd" \
        -frames:v 1 "$NATIVE_DASHBOARD_SCREENSHOT"
    [[ -s "$NATIVE_DASHBOARD_SCREENSHOT" ]] || { echo "dashboard screenshot is empty" >&2; exit 1; }
fi
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
