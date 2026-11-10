#!/usr/bin/env bash
# Fetch GTK4/libadwaita typelibs and the PyGObject Cairo bridge without root.
#
# Ubuntu may ship GTK4 without the Gtk-4.0 / Adw-1 typelibs or PyGObject's Cairo
# bridge. This script downloads the .deb packages and unpacks them into a private
# prefix. The launcher's cairo_support adapter loads the bridge from that prefix.
#
# If your distribution already provides the typelibs (or you installed them with
# sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi-cairo) you do not
# need this at all.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PREFIX="${ROOT}/.deps"
cd "$ROOT"

PACKAGES=(
  gir1.2-gtk-4.0
  gir1.2-adw-1
  libadwaita-1-0
  gir1.2-graphene-1.0
  gir1.2-gdkpixbuf-2.0
  gir1.2-pango-1.0
  gir1.2-harfbuzz-0.0
  python3-gi-cairo
)

if python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.getcwd())
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw  # noqa: F401
    from codexbar_gtk.ui.cairo_support import HAS_CAIRO
    if not HAS_CAIRO:
        raise ImportError("PyGObject Cairo bridge is unavailable")
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

# cairo_support and install.sh look for the bridge at the private prefix root.
# Debian places it under python3/dist-packages/gi in the package archive.
bridge_found=0
while IFS= read -r -d '' bridge; do
  cp -a "$bridge" "$PREFIX/"
  bridge_found=1
done < <(find "$PREFIX/root" -type f -name '_gi_cairo*.so' -print0)
if [[ "$bridge_found" != "1" ]]; then
  echo "python3-gi-cairo did not provide an _gi_cairo extension" >&2
  exit 1
fi

echo "==> Done. The launcher picks these up automatically."
