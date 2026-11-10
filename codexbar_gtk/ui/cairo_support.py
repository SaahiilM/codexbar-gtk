"""Make sure PyGObject can hand out ``cairo.Context`` objects.

Some distributions ship PyGObject without the ``python3-gi-cairo`` bridge, which
breaks ``Gtk.Snapshot.append_cairo``. When the bridge is missing we try to load a
vendored copy from the private dependency prefix created by
``scripts/bootstrap-deps.sh`` before giving up.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys

_LOADED = False


def _candidate_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [
        os.path.join(here, "..", "..", ".deps"),
        # The user install keeps its private bridge next to the copied package.
        os.path.join(here, "..", "..", "deps"),
        os.path.join(here, "..", "deps"),
        os.path.join(here, "deps"),
        os.path.expanduser("~/.local/share/codexbar-gtk/deps"),
        os.path.expanduser("~/.local/lib/codexbar-gtk/deps"),
    ]
    patterns = []
    for root in roots:
        patterns.append(os.path.join(root, "_gi_cairo*.so"))
        patterns.append(os.path.join(root, "gi", "_gi_cairo*.so"))
    paths: list[str] = []
    for pattern in patterns:
        paths.extend(sorted(glob.glob(pattern)))
    return paths


def ensure_cairo_support() -> bool:
    """Return True when cairo support is available."""
    global _LOADED
    if _LOADED:
        return True

    try:
        import gi._gi_cairo  # type: ignore  # noqa: F401

        _LOADED = True
        return True
    except ImportError:
        pass

    for path in _candidate_paths():
        try:
            spec = importlib.util.spec_from_file_location("gi._gi_cairo", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules["gi._gi_cairo"] = module
            _LOADED = True
            return True
        except Exception:
            continue

    return False


ensure_cairo_support()
HAS_CAIRO = ensure_cairo_support()
