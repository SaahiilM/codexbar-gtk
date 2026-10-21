#!/usr/bin/env bash
# Install CodexBar (GTK) for the current user.
#
#   ./scripts/install.sh              install and enable autostart
#   ./scripts/install.sh --no-autostart
#   ./scripts/install.sh --uninstall
#
# The app is installed to ~/.local/bin/codexbar-gtk, the launcher entry to
# ~/.local/share/applications and a systemd user service to
# ~/.config/systemd/user/codexbar-gtk.service.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="${PREFIX}/bin"
APP_DIR="${PREFIX}/share/codexbar-gtk"
DATA_DIR="${PREFIX}/share/applications"
ICON_DIR="${PREFIX}/share/icons/hicolor/scalable/apps"
UNIT_DIR="${HOME}/.config/systemd/user"
AUTOSTART_DIR="${HOME}/.config/autostart"
CONFIG_DIR="${HOME}/.config/codexbar-gtk"

AUTOSTART=1
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

uninstall() {
  rm -f "${BIN_DIR}/codexbar-gtk"
  rm -rf "${APP_DIR}"
  rm -f "${DATA_DIR}/codexbar-gtk.desktop"
  rm -f "${ICON_DIR}/codexbar-gtk.svg"
  rm -f "${UNIT_DIR}/codexbar-gtk.service"
  rm -f "${AUTOSTART_DIR}/codexbar-gtk.desktop"
  systemctl --user disable --now codexbar-gtk.service 2>/dev/null || true
  echo "CodexBar removed."
}

if [[ "$UNINSTALL" == "1" ]]; then
  uninstall
  exit 0
fi

echo "==> Installing CodexBar (GTK)"
mkdir -p "${BIN_DIR}" "${APP_DIR}" "${DATA_DIR}" "${ICON_DIR}" "${UNIT_DIR}" "${CONFIG_DIR}"

# Launcher ------------------------------------------------------------------
cat > "${BIN_DIR}/codexbar-gtk" <<EOF
#!/usr/bin/env bash
# CodexBar (GTK) launcher
export PYTHONPATH="${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
if [[ -d "${ROOT}/.deps/root/usr/lib/x86_64-linux-gnu/girepository-1.0" ]]; then
  export GI_TYPELIB_PATH="${ROOT}/.deps/root/usr/lib/x86_64-linux-gnu/girepository-1.0\${GI_TYPELIB_PATH:+:\$GI_TYPELIB_PATH}"
  export LD_LIBRARY_PATH="${ROOT}/.deps/root/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
fi
export GDK_BACKEND="\${GDK_BACKEND:-x11}"
exec python3 -m codexbar_gtk "\$@"
EOF
chmod +x "${BIN_DIR}/codexbar-gtk"

# Application code ----------------------------------------------------------
rm -rf "${APP_DIR}/codexbar_gtk"
cp -r "${ROOT}/codexbar_gtk" "${APP_DIR}/codexbar_gtk"
find "${APP_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# Icon ----------------------------------------------------------------------
python3 - "$ICON_DIR" <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("PREFIX", ""), "share/codexbar-gtk"))
icon_dir = sys.argv[1]
os.makedirs(icon_dir, exist_ok=True)
template = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <defs>
    <clipPath id="cb-rounded">
      <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5"/>
    </clipPath>
  </defs>
  <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5" fill="#ffffff" fill-opacity="0.16"/>
  <g clip-path="url(#cb-rounded)">
    <rect x="2.5" y="6.5" width="13" height="11" fill="#10A37F"/>
  </g>
  <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5" fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.4"/>
</svg>
"""
with open(os.path.join(icon_dir, "codexbar-gtk.svg"), "w", encoding="utf-8") as handle:
    handle.write(template)
PY

# Desktop entry -------------------------------------------------------------
cat > "${DATA_DIR}/codexbar-gtk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CodexBar
GenericName=AI coding quota monitor
Comment=Show usage limits for OpenAI Codex, Claude Code and more
Exec="${BIN_DIR}/codexbar-gtk"
Icon=codexbar-gtk
Terminal=false
Categories=Utility;Development;
Keywords=codex;claude;usage;quota;limits;
StartupNotify=false
EOF

# systemd user service ------------------------------------------------------
# The service starts before plasmashell so that the tray item is registered
# before Plasma creates its StatusNotifierItem host. Plasma only shows tray
# items that already existed when the host came up.
cat > "${UNIT_DIR}/codexbar-gtk.service" <<EOF
[Unit]
Description=CodexBar (GTK) — AI coding quota monitor
PartOf=graphical-session.target
Before=plasma-plasmashell.service
After=dbus.service

[Service]
Type=simple
ExecStart="${BIN_DIR}/codexbar-gtk"
Restart=on-failure
RestartSec=5
Slice=app.slice

[Install]
WantedBy=graphical-session.target
EOF

if [[ "$AUTOSTART" == "1" ]]; then
  systemctl --user daemon-reload
  systemctl --user enable codexbar-gtk.service >/dev/null 2>&1 || true

  mkdir -p "${AUTOSTART_DIR}"
  cat > "${AUTOSTART_DIR}/codexbar-gtk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CodexBar
Exec="${BIN_DIR}/codexbar-gtk"
X-GNOME-Autostart-enabled=true
Terminal=false
EOF
fi

echo "==> Installed."
echo "    launcher : ${BIN_DIR}/codexbar-gtk"
echo "    app code : ${APP_DIR}"
echo "    settings : ${CONFIG_DIR}/settings.json"
echo
echo "Start it with:  ${BIN_DIR}/codexbar-gtk"
echo "Open settings :  ${BIN_DIR}/codexbar-gtk --settings"
