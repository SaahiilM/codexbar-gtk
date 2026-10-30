#!/usr/bin/env python3
"""Fixture-only GTK smoke for B13a Rust spend and tray projections.

Run with ``CODEXBAR_RUST_CORE=1 python3 tools/gtk_smoke_b13_spend_tray.py``.
The script uses an isolated HOME and a synthetic CLI; it never reads a real
account, invokes a real CLI, or requests live currency rates.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TYPELIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0")
LIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_B13_DEPS_READY"):
    temp_home = tempfile.mkdtemp(prefix="codexbar-b13-home-")
    env = os.environ.copy()
    env["HOME"] = temp_home
    env["XDG_CONFIG_HOME"] = os.path.join(temp_home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(temp_home, ".local", "share")
    env["XDG_CACHE_HOME"] = os.path.join(temp_home, ".cache")
    env["CODEXBAR_B13_DEPS_READY"] = "1"
    env["CODEXBAR_B13_HOME"] = temp_home
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (
        ":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else ""
    )
    env["LD_LIBRARY_PATH"] = LIB_DIR + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

HOME = os.environ.setdefault("CODEXBAR_B13_HOME", tempfile.mkdtemp(prefix="codexbar-b13-home-"))
os.environ["HOME"] = HOME
os.environ["XDG_CONFIG_HOME"] = os.path.join(HOME, ".config")
os.environ["XDG_DATA_HOME"] = os.path.join(HOME, ".local", "share")
os.environ["XDG_CACHE_HOME"] = os.path.join(HOME, ".cache")
os.environ["CODEXBAR_RUST_CORE"] = "1"
atexit.register(shutil.rmtree, HOME, ignore_errors=True)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gsk, Gtk  # noqa: E402

from codexbar_gtk.cli import CodexBarCLI  # noqa: E402
from codexbar_gtk.controller import Controller  # noqa: E402
from codexbar_gtk.history import HistoryStore  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.app import CodexBarApp  # noqa: E402
from codexbar_gtk.ui.window import MainWindow  # noqa: E402


class FakeTray:
    available = True

    def __init__(self) -> None:
        self.update_args = None
        self.menu = []

    def update(self, *args) -> None:
        self.update_args = args

    def set_menu(self, items) -> None:
        self.menu = items

    def register(self) -> None:
        pass


def write_fake_cli(path: str) -> None:
    script = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
provider = {
  "provider": "codex", "source": "synthetic-fixture", "version": "fixture-1",
  "rateWindowLabels": {"primary": "5h", "secondary": "Weekly"},
  "usage": {
    "updatedAt": "2026-10-30T12:00:00Z",
    "primary": {"usedPercent": 64, "windowMinutes": 300, "resetsAt": "2026-10-30T17:00:00Z"},
    "secondary": {"windowMinutes": 10080},
    "identity": {"loginMethod": "fixture", "plan": "Synthetic"}
  }
}
cost = {
  "provider": "codex", "currencyCode": "USD", "totalCost": 42.5,
  "totalTokens": 9000, "priced": True, "sessionCostUSD": 6.25,
  "sessionTokens": 1000, "last30DaysCostUSD": 18.75,
  "last30DaysTokens": 4000,
  "coverage": {"priced": 3, "unpriced": 1},
  "provenance": "fixture_history", "reportingPeriod": "synthetic period",
  "daily": [
    {"date": "2026-10-30", "totalCost": 12.5, "totalTokens": 900},
    {"date": "2026-10-29", "totalTokens": 500}
  ],
  "projects": [
    {"name": "synthetic-project", "totalCost": 12.0, "totalTokens": 200},
    {"name": "unknown-cost-project", "totalTokens": 40}
  ],
  "models": [
    {"modelName": "synthetic-model", "cost": 2.0, "totalTokens": 100},
    {"name": "unknown-cost-model", "totalTokens": 5}
  ]
}
if args and args[0] == "usage":
    print(json.dumps([provider]))
elif args and args[0] == "cost":
    print(json.dumps([cost]))
elif args and args[0] == "sessions":
    print(json.dumps([]))
elif args == ["--version"]:
    print("fixture-cli 1.0")
else:
    print(json.dumps([]))
'''
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o700)


def render(widget: Gtk.Widget, path: str, width: int, height: int) -> None:
    widget.set_size_request(width, height)
    window = widget if isinstance(widget, Gtk.Window) else widget.get_root()
    if not isinstance(window, Gtk.Window):
        raise RuntimeError("GTK screenshot widget has no toplevel window")
    window.set_default_size(width, height)
    window.present()
    context = GLib.MainContext.default()
    for _ in range(60):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("GTK did not produce a render node")
    renderer = Gsk.Renderer.new_for_surface(window.get_surface())
    renderer.render_texture(node, None).save_to_png(path)
    renderer.unrealize()


def main() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("GTK smoke requires the existing graphical session")
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "docs", "rust-migration", "screenshots", "b13-spend-tray-synthetic.png"
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    Adw.init()
    style.apply_theme()

    config = os.path.join(HOME, ".config", "codexbar-gtk")
    prefs = Preferences(os.path.join(config, "settings.json"))
    prefs.set("refreshFrequency", "manual")
    prefs.set("spendTimeRange", "7 days")
    prefs.set("preferredCurrencyCode", "USD")
    prefs.set("unifiedIconSource", "automatic")
    prefs.set("menuBarIconStyle", "iconPercent")
    prefs.set("switcherRowsOption", "all")
    prefs.set("hidePersonalInfo", True)

    fake_cli = os.path.join(HOME, "codexbar-fixture")
    write_fake_cli(fake_cli)
    history = HistoryStore(os.path.join(config, "history.jsonl"))
    controller = Controller(prefs, CodexBarCLI(fake_cli, timezone="UTC"))
    controller.history = history
    controller.start()

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        controller.poll()
        if controller.state.last_updated is not None and not controller.state.refreshing:
            break
        time.sleep(0.01)
    if controller.state.last_updated is None:
        raise RuntimeError("Rust controller did not publish a successful fixture refresh")
    if len(controller.state.providers) != 1 or controller.state.providers[0].provider_id != "codex":
        raise RuntimeError("unexpected provider DTO from Rust controller")
    if controller.state.spend is None or controller.state.spend.total_cost != 42.5:
        raise RuntimeError("synthetic spend DTO did not reach the GTK state")

    application = Gtk.Application(application_id="com.codexbar.B13Smoke")
    application.register(None)
    main_window = MainWindow(application, prefs, history, rust_presentation=True)
    main_window.show_page("spend")
    main_window.present()

    app = CodexBarApp()
    app.prefs = prefs
    app.controller = controller
    app.tray = FakeTray()
    app.main_window = main_window
    app._notify = lambda *_args, **_kwargs: None
    app._apply_state(controller.state)

    context = GLib.MainContext.default()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if app._rust_spend_view_model is not None and app._rust_tray_summary is not None:
            break
        time.sleep(0.01)
    spend = app._rust_spend_view_model
    tray = app._rust_tray_summary
    if spend is None or tray is None:
        raise RuntimeError("Rust spend/tray projection did not return to GTK")
    if spend.get("selected_range") != "7 days" or spend.get("display_currency") != "USD":
        raise RuntimeError("GTK facade projection ignored the shared spend preferences")
    if spend.get("total", {}).get("display_amount") != 42.5:
        raise RuntimeError("GTK spend projection did not preserve the known total")
    if not any(row.get("source_cost") is None for row in spend.get("projects", [])):
        raise RuntimeError("unknown project cost was coerced instead of remaining unknown")
    if tray.get("unified_icon_source") != "automatic" or not tray.get("available"):
        raise RuntimeError("GTK tray did not consume the automatic B09 selection")
    if tray.get("selected_window_key") != "primary":
        raise RuntimeError("tray projection did not resolve the original selected window")
    if not any("Weekly: unavailable" in row for row in tray.get("tooltip_rows", [])):
        raise RuntimeError("unknown quota was not rendered as unavailable")
    if any("Weekly: 0%" in row for row in tray.get("tooltip_rows", [])):
        raise RuntimeError("unknown quota was incorrectly rendered as 0%")
    if not any("Weekly unavailable" in row.get("text", "") for row in tray.get("switcher_rows", [])):
        raise RuntimeError("all-windows switcher did not retain an unavailable label")
    if main_window.spend_view.total_tile.value_label.get_text() != "≥ $42.50":
        raise RuntimeError(
            "GTK spend tile did not render the Rust DTO amount: "
            + repr(main_window.spend_view.total_tile.value_label.get_text())
        )
    if not app.tray.update_args or "Weekly: unavailable" not in app.tray.update_args[2]:
        raise RuntimeError("tray adapter did not render the Rust summary DTO")

    render(main_window, output, 980, 1000)
    main_window.destroy()
    controller.stop()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not controller._rust_controller.shutdown_complete():
        time.sleep(0.01)
    if not controller._rust_controller.shutdown_complete():
        raise RuntimeError("Rust controller shutdown did not join")
    application.quit()
    print(f"fixture GTK spend/tray projection rendered: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
