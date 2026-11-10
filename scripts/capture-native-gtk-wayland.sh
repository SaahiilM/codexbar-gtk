#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${CODEXBAR_NATIVE_BINARY:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
output=${1:-"$repo_root/docs/rust-migration/screenshots/u01-native-bootstrap-wayland.png"}

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
        echo "Spectacle already has a session service; close it before capturing the native bootstrap" >&2
        exit 2
    fi
fi
command -v gdbus >/dev/null || { echo "missing gdbus to check the app's single-instance service" >&2; exit 2; }
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }
mkdir -p "$(dirname "$output")"

owner=$(gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
if [[ "$owner" != "(false,)" ]]; then
    echo "CodexBar GTK is already registered on this desktop session; close it before capturing the native bootstrap" >&2
    exit 2
fi

scratch=$(mktemp -d)
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/home" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
printf '%s\n' "$*" >> "$NATIVE_CLI_LOG"
case "$1" in
    --version)
        printf 'CodexBar synthetic fixture 0.82.0\n'
        : > "$NATIVE_REFRESH_COMPLETE"
        ;;
    usage|cost|sessions) printf '[]\n' ;;
    *) printf '[]\n' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

export HOME="$scratch/home"
export XDG_RUNTIME_DIR
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_CLI_LOG="$scratch/cli-calls"
export NATIVE_REFRESH_COMPLETE="$scratch/refresh-complete"
export GTK_A11Y=none GTK_USE_PORTAL=0 GDK_BACKEND=wayland GSK_RENDERER=cairo

"$binary" --panel >"$scratch/app.log" 2>&1 &
app_pid=$!
cleanup() {
    gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
    wait "$app_pid" 2>/dev/null || true
    if [[ "${spectacle_started:-0}" == "1" ]]; then
        qdbus6 org.kde.spectacle /MainApplication org.qtproject.Qt.QCoreApplication.quit >/dev/null 2>&1 || true
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT

deadline=$((SECONDS + 20))
while [[ ! -e "$NATIVE_REFRESH_COMPLETE" ]] && (( SECONDS < deadline )); do sleep 0.05; done
if [[ ! -e "$NATIVE_REFRESH_COMPLETE" ]]; then
    cat "$scratch/app.log" >&2
    echo "synthetic backend refresh did not reach its final version request" >&2
    exit 1
fi
sleep 5
version_calls=$(grep -c '^--version$' "$NATIVE_CLI_LOG" || true)
if [[ "$version_calls" != "1" ]]; then
    cat "$scratch/app.log" >&2
    echo "expected one backend controller across the primary and capture-route processes; saw $version_calls version calls" >&2
    exit 1
fi
if command -v spectacle >/dev/null; then
    # Spectacle asks KWin for the compositor capture, which works on KDE
    # Wayland where the wlr-screencopy protocol may not be exposed.
    spectacle_started=1
    spectacle --background --activewindow --nonotify --output "$output"
else
    grim "$output"
fi

rm -rf "$scratch"
printf 'captured synthetic native GTK Wayland UI: %s\n' "$output"
