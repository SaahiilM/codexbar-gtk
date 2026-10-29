#!/usr/bin/env bash
# Fetch the GTK4 / libadwaita GObject introspection data without root.
#
# Ubuntu ships the GTK4 runtime but not always the Gtk-4.0 / Adw-1 typelibs that
# PyGObject needs. This script downloads the .deb packages and unpacks them into a
# private prefix that the launcher adds to GI_TYPELIB_PATH / LD_LIBRARY_PATH.
#
# If your distribution already provides the typelibs (or you installed them with
# sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1) you do not need this at all.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PREFIX="${ROOT}/.deps"

PACKAGES=(
  gir1.2-gtk-4.0
  gir1.2-adw-1
  libadwaita-1-0
  gir1.2-graphene-1.0
  gir1.2-gdkpixbuf-2.0
  gir1.2-pango-1.0
  gir1.2-harfbuzz-0.0
)

if python3 - <<'PY'
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw  # noqa: F401
except Exception:
    raise SystemExit(1)
PY
then
  echo "GTK4 + libadwaita typelibs are already available system-wide."
  exit 0
fi

echo "==> Fetching GTK4/libadwaita typelibs into $PREFIX"
mkdir -p "$PREFIX/debs" "$PREFIX/root"
cd "$PREFIX/debs"

for pkg in "${PACKAGES[@]}"; do
  if ! ls "${pkg}"_*.deb >/dev/null 2>&1; then
    (cd "$PREFIX/debs" && apt-get download "$pkg") || {
      echo "failed to download $pkg" >&2
      exit 1
    }
  fi
done

for deb in ./*.deb; do
  dpkg-deb -x "$deb" "$PREFIX/root"
done

echo "==> Done. The launcher picks these up automatically."
