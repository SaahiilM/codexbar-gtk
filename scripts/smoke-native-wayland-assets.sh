#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
binary=${CODEXBAR_NATIVE_BINARY:-"$repo_root/rust-gtk/target/debug/codexbar-gtk-native"}
output=${1:-"$repo_root/docs/rust-migration/screenshots/u08-native-dashboard-wayland.png"}

if [[ -z "${WAYLAND_DISPLAY:-}" || -z "${XDG_RUNTIME_DIR:-}" || -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    echo "run this capture from the active Wayland desktop session" >&2
    exit 2
fi
for tool in spectacle qdbus6 gdbus gapplication; do
    command -v "$tool" >/dev/null || { echo "missing Wayland smoke dependency: $tool" >&2; exit 2; }
done
[[ -x "$binary" ]] || { echo "native GTK binary not found: $binary" >&2; exit 2; }
owner=$(gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK)
[[ "$owner" == "(false,)" ]] || {
    echo "CodexBar GTK is already running in this desktop session" >&2
    exit 2
}

mkdir -p "$(dirname "$output")"
scratch=$(mktemp -d)
chmod 700 "$scratch"
cleanup() {
    if [[ -n "${app_pid:-}" ]] && kill -0 "$app_pid" 2>/dev/null; then
        gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [[ "${spectacle_started:-0}" == "1" ]]; then
        qdbus6 org.kde.spectacle /MainApplication org.qtproject.Qt.QCoreApplication.quit >/dev/null 2>&1 || true
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT
mkdir -p "$scratch/home" "$scratch/runtime"
chmod 700 "$scratch/runtime"
cat > "$scratch/fake-codexbar" <<'CLI'
#!/bin/sh
case "$1" in
    --version) printf 'CodexBar synthetic fixture 0.82.0\n'; : > "$NATIVE_VERSION_DONE" ;;
    usage)
        printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"identity":{"accountEmail":"synthetic@example.invalid"},"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":62,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300},"secondary":{"usedPercent":31,"resetsAt":"2026-11-05T18:00:00Z","windowMinutes":10080}}}]'
        : > "$NATIVE_USAGE_DONE"
        ;;
    cost|sessions) printf '[]\n' ;;
    *) printf '[]\n' ;;
esac
CLI
chmod 700 "$scratch/fake-codexbar"

export HOME="$scratch/home"
export XDG_CONFIG_HOME="$scratch/home/.config"
export XDG_DATA_HOME="$scratch/home/.local/share"
export XDG_CACHE_HOME="$scratch/home/.cache"
export CODEXBAR_CLI="$scratch/fake-codexbar"
export NATIVE_USAGE_DONE="$scratch/usage-done"
export NATIVE_VERSION_DONE="$scratch/version-done"
export GTK_USE_PORTAL=0 GDK_BACKEND=wayland GSK_RENDERER=cairo
export GDK_SCALE="${NATIVE_GTK_SCALE:-1}"

"$binary" >"$scratch/app.log" 2>&1 &
app_pid=$!
deadline=$((SECONDS + 20))
while [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_VERSION_DONE" ]] && (( SECONDS < deadline )); do
    sleep 0.05
done
if [[ ! -e "$NATIVE_USAGE_DONE" || ! -e "$NATIVE_VERSION_DONE" ]]; then
    cat "$scratch/app.log" >&2
    echo "synthetic Wayland refresh did not complete" >&2
    exit 1
fi

owner_deadline=$((SECONDS + 8))
while (( SECONDS < owner_deadline )); do
    owner=$(gdbus call --session --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk 2>/dev/null || true)
    [[ "$owner" == "(true,)" ]] && break
    sleep 0.05
done
[[ "${owner:-}" == "(true,)" ]] || {
    cat "$scratch/app.log" >&2
    echo "native Wayland tray item did not register" >&2
    exit 1
}

gapplication action com.steipete.CodexBarGTK dashboard
sleep 3
spectacle_started=1
spectacle --background --activewindow --nonotify --output "$output"
[[ -s "$output" ]] || { echo "Wayland screenshot is empty" >&2; exit 1; }
gapplication action com.steipete.CodexBarGTK quit
wait "$app_pid"
app_pid=
owner=$(gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierItem-codexbar-gtk)
[[ "$owner" == "(false,)" ]] || { echo "tray item remained registered after Wayland shutdown" >&2; exit 1; }
printf 'native Wayland synthetic dashboard smoke and capture passed: %s\n' "$output"
