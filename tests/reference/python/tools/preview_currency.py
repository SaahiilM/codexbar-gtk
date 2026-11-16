#!/usr/bin/env python3
"""Present the spend widget with synthetic data and Rust-opt-in currency."""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TYPELIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0")
LIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_PREVIEW_DEPS_READY"):
    env = os.environ.copy()
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else "")
    env["LD_LIBRARY_PATH"] = LIB_DIR + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["CODEXBAR_PREVIEW_DEPS_READY"] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from codexbar_gtk import currency, rust_bridge
from codexbar_gtk.data import spend_from_payloads
from codexbar_gtk.prefs import Preferences
from codexbar_gtk.ui import style
from codexbar_gtk.ui.spend import SpendView


def main() -> int:
    if rust_bridge.backend_name() != "rust":
        raise SystemExit("Run with CODEXBAR_RUST_CORE=1 after building the Rust extension")
    prefs_path = os.path.join(tempfile.mkdtemp(prefix="codexbar-b06-prefs-"), "settings.json")
    prefs = Preferences(prefs_path)
    prefs.set("preferredCurrencyCode", "EUR")
    Adw.init()
    style.apply_theme()
    summary = spend_from_payloads([{
        "provider": "codex", "currencyCode": "USD",
        "totals": {"totalCost": 42.5, "totalTokens": 13500, "coverage": {"priced": 3}},
        "sessionCostUSD": 6.25, "last30DaysCostUSD": 42.5,
        "daily": [{"date": "2026-10-28", "totalCost": 15.0, "totalTokens": 4000},
                  {"date": "2026-10-29", "totalCost": 27.5, "totalTokens": 9500}],
        "projects": [{"name": "synthetic-project", "totalCost": 42.5, "totalTokens": 13500}],
        "models": [{"model": "fixture-model", "cost": 42.5, "tokens": 13500}],
    }])
    widget = SpendView(prefs)
    widget.update(summary)
    widget.set_size_request(900, 560)
    window = Gtk.Window()
    window.set_decorated(False)
    window.set_child(widget)
    window.present()
    context = GLib.MainContext.default()
    for _ in range(60):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
    print(f"presented synthetic EUR SpendView; EUR conversion={currency.convert(42.5, 'USD', 'EUR')}; backend={rust_bridge.backend_name()}; capture this window with a desktop screenshot tool", flush=True)
    for _ in range(600):
        while context.pending():
            context.iteration(False)
        time.sleep(0.1)
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
