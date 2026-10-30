#!/usr/bin/env python3
"""Wayland fixture smoke for B13a spend/tray drawing in both backend modes.

Set ``GDK_BACKEND=wayland`` and ``CODEXBAR_RUST_CORE=0`` or ``1`` before
running. It captures the presented window with Spectacle, not an offscreen
GTK render, and uses only an isolated HOME plus a synthetic CLI.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.environ.get("CODEXBAR_B13_APP_ROOT", PROJECT_ROOT)
sys.path.insert(0, APP_ROOT)

TYPELIB_DIR = os.path.join(PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0")
LIB_DIR = os.path.join(PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
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
atexit.register(shutil.rmtree, HOME, ignore_errors=True)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from codexbar_gtk import rust_bridge  # noqa: E402
from codexbar_gtk.cli import CodexBarCLI  # noqa: E402
from codexbar_gtk.controller import Controller  # noqa: E402
from codexbar_gtk.history import HistoryStore  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import cairo_support  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.app import CodexBarApp  # noqa: E402
from codexbar_gtk.ui.cards import MiniBarChart  # noqa: E402
from codexbar_gtk.ui.spend import SpendHeatmap  # noqa: E402
from codexbar_gtk.ui.window import MainWindow  # noqa: E402

DRAW_CALLBACKS = {"heatmap": [], "chart": []}
_heatmap_draw = SpendHeatmap._draw
_chart_draw = MiniBarChart._draw


def _observe_heatmap_draw(self, area, context, width, height) -> None:
    _values, levels = self._series()
    DRAW_CALLBACKS["heatmap"].append(
        {
            "width": width,
            "height": height,
            "active_cells": sum(level > 0 for level in levels),
            "tokens": sum(value for value in self._values.values() if value > 0),
        }
    )
    _heatmap_draw(self, area, context, width, height)


def _observe_chart_draw(self, area, context, width, height) -> None:
    DRAW_CALLBACKS["chart"].append(
        {
            "width": width,
            "height": height,
            "known_positive": sum(
                value is not None and value > 0 for _label, value in self.entries
            ),
            "unknown": sum(value is None for _label, value in self.entries),
        }
    )
    _chart_draw(self, area, context, width, height)


SpendHeatmap._draw = _observe_heatmap_draw
MiniBarChart._draw = _observe_chart_draw


def drawing_callbacks_have_data() -> bool:
    return any(
        event["width"] > 0 and event["height"] > 0 and event["active_cells"] > 0
        for event in DRAW_CALLBACKS["heatmap"]
    ) and any(
        event["width"] > 0 and event["height"] > 0 and event["known_positive"] > 0
        for event in DRAW_CALLBACKS["chart"]
    )


def children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def row_cost_text(box: Gtk.Box, row_name: str) -> str | None:
    for row in children(box):
        if not isinstance(row, Gtk.Box):
            continue
        labels = [child for child in children(row) if isinstance(child, Gtk.Label)]
        if labels and labels[0].get_text() == row_name:
            return labels[-1].get_text()
    return None


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
    {"name": "unknown-cost-project", "totalTokens": 40},
    {"name": "known-zero-project", "totalCost": 0, "totalTokens": 0}
  ],
  "models": [
    {"modelName": "synthetic-model", "cost": 2.0, "totalTokens": 100},
    {"name": "unknown-cost-model", "totalTokens": 5},
    {"name": "known-zero-model", "cost": 0, "totalTokens": 0},
    {"name": "fallback-zero-model", "cost": 0, "totalCost": 3, "totalTokens": 10}
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


def capture_presented_window(window: Gtk.Window, path: str) -> None:
    if not shutil.which("spectacle"):
        raise RuntimeError("Spectacle is required for a Wayland compositor capture")
    window.present()
    context = GLib.MainContext.default()
    for _ in range(80):
        while context.pending():
            context.iteration(False)
        if drawing_callbacks_have_data():
            break
        time.sleep(0.01)
    result = subprocess.run(
        [
            "spectacle",
            "--activewindow",
            "--background",
            "--nonotify",
            "--no-shadow",
            "--output",
            path,
        ],
        check=False,
        timeout=20,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Spectacle active-window capture failed ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    if not os.path.isfile(path) or os.path.getsize(path) < 10_000:
        raise RuntimeError("Spectacle did not create a full active-window screenshot")


def main() -> int:
    if os.environ.get("GDK_BACKEND") != "wayland":
        raise RuntimeError("set GDK_BACKEND=wayland to verify the live Wayland path")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("GTK smoke requires the existing Wayland compositor")
    if not cairo_support.HAS_CAIRO:
        raise RuntimeError("PyGObject Cairo bridge is unavailable; draw callbacks would be blank")
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PROJECT_ROOT,
        "docs",
        "rust-migration",
        "screenshots",
        f"b13-spend-tray-{rust_bridge.backend_name()}-wayland.png",
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    Adw.init()
    style.apply_theme()
    display = Gdk.Display.get_default()
    if display is None or type(display).__name__ != "GdkWaylandDisplay":
        raise RuntimeError(f"GTK selected {type(display).__name__ if display else 'no display'}, not Wayland")

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
    application = Gtk.Application(application_id="com.codexbar.B13Smoke")
    application.register(None)
    main_window = MainWindow(
        application,
        prefs,
        history,
        rust_presentation=rust_bridge.extension() is not None,
    )
    main_window.set_default_size(980, 1200)
    main_window.show_page("spend")
    main_window.present()

    app = CodexBarApp()
    app.prefs = prefs
    app.controller = controller
    app.tray = FakeTray()
    app.main_window = main_window
    app._notify = lambda *_args, **_kwargs: None
    controller.subscribe(app._on_state)
    controller.start()
    if controller.uses_rust_controller != (rust_bridge.extension() is not None):
        raise RuntimeError("controller backend did not match the explicitly selected smoke mode")

    context = GLib.MainContext.default()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if controller.uses_rust_controller:
            controller.poll()
        while context.pending():
            context.iteration(False)
        rust_projection_ready = not controller.uses_rust_controller or (
            app._rust_spend_view_model is not None and app._rust_tray_summary is not None
        )
        if (
            controller.state.last_updated is not None
            and not controller.state.refreshing
            and rust_projection_ready
            and drawing_callbacks_have_data()
        ):
            break
        time.sleep(0.01)
    if controller.state.last_updated is None:
        raise RuntimeError("fixture refresh did not reach the presented GTK window")
    if controller.state.spend is None or controller.state.spend.total_cost != 42.5:
        raise RuntimeError("synthetic spend data did not reach the GTK window")

    spend = app._rust_spend_view_model
    tray = app._rust_tray_summary
    if controller.uses_rust_controller:
        if spend is None or tray is None:
            raise RuntimeError("Rust spend/tray projection did not return to GTK")
        if spend.get("selected_range") != "7 days" or spend.get("display_currency") != "USD":
            raise RuntimeError("GTK facade projection ignored the shared spend preferences")
        if spend.get("total", {}).get("display_amount") != 42.5:
            raise RuntimeError("GTK spend projection did not preserve the known total")
        unknown_project = next(
            (row for row in spend.get("projects", []) if row.get("name") == "unknown-cost-project"),
            None,
        )
        unknown_model = next(
            (row for row in spend.get("models", []) if row.get("name") == "unknown-cost-model"),
            None,
        )
        for label, row in (("project", unknown_project), ("model", unknown_model)):
            if row is None:
                raise RuntimeError(f"fixture unknown-cost {label} row is missing from the Rust DTO")
            if row.get("source_cost") is not None or row.get("display_cost") is not None or row.get("cost_known"):
                raise RuntimeError(f"unknown-cost {label} was coerced in the Rust DTO: {row!r}")
        known_zero_project = next(
            (row for row in spend.get("projects", []) if row.get("name") == "known-zero-project"),
            None,
        )
        known_zero_model = next(
            (row for row in spend.get("models", []) if row.get("name") == "known-zero-model"),
            None,
        )
        fallback_zero_model = next(
            (row for row in spend.get("models", []) if row.get("name") == "fallback-zero-model"),
            None,
        )
        for label, row in (("project", known_zero_project), ("model", known_zero_model)):
            if row is None or row.get("source_cost") != 0.0 or row.get("display_cost") != 0.0 or not row.get("cost_known"):
                raise RuntimeError(f"known-zero {label} was not preserved in the Rust DTO: {row!r}")
        if (
            fallback_zero_model is None
            or fallback_zero_model.get("source_cost") != 3.0
            or fallback_zero_model.get("display_cost") != 3.0
            or not fallback_zero_model.get("cost_known")
        ):
            raise RuntimeError(f"cost=0/totalCost=3 fallback changed in the Rust DTO: {fallback_zero_model!r}")
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
        if not app.tray.update_args or "Weekly: unavailable" not in app.tray.update_args[2]:
            raise RuntimeError("tray adapter did not render the Rust summary DTO")
    elif (
        main_window.spend_view.time_range.get_active_text() != "7 days"
        or not app.tray.update_args
        or "Provider: Codex" not in app.tray.update_args[2]
    ):
        raise RuntimeError("Python GTK did not render the selected range and synthetic provider")

    if main_window.spend_view.total_tile.value_label.get_text() != "≥ $42.50":
        raise RuntimeError(
            "GTK spend tile did not render the fixture partial amount: "
            + repr(main_window.spend_view.total_tile.value_label.get_text())
        )
    for label, box, name in (
        ("project", main_window.spend_view.projects_box, "unknown-cost-project"),
        ("model", main_window.spend_view.models_box, "unknown-cost-model"),
    ):
        cost_text = row_cost_text(box, name)
        if cost_text != "unpriced":
            raise RuntimeError(
                f"unknown-cost {label} did not render unavailable in {rust_bridge.backend_name()} mode: "
                f"{cost_text!r}"
            )
    for label, box, name in (
        ("project", main_window.spend_view.projects_box, "known-zero-project"),
        ("model", main_window.spend_view.models_box, "known-zero-model"),
    ):
        cost_text = row_cost_text(box, name)
        if cost_text != "$0":
            raise RuntimeError(
                f"known-zero {label} did not render as $0 in {rust_bridge.backend_name()} mode: "
                f"{cost_text!r}"
            )
    fallback_zero_cost = row_cost_text(main_window.spend_view.models_box, "fallback-zero-model")
    if fallback_zero_cost != "$3":
        raise RuntimeError(
            f"cost=0/totalCost=3 did not retain its fallback in {rust_bridge.backend_name()} mode: "
            f"{fallback_zero_cost!r}"
        )
    print(
        f"spend_rows backend={rust_bridge.backend_name()} "
        f"unknown_project:{row_cost_text(main_window.spend_view.projects_box, 'unknown-cost-project')} "
        f"unknown_model:{row_cost_text(main_window.spend_view.models_box, 'unknown-cost-model')} "
        f"known_zero_project:{row_cost_text(main_window.spend_view.projects_box, 'known-zero-project')} "
        f"known_zero_model:{row_cost_text(main_window.spend_view.models_box, 'known-zero-model')} "
        f"cost_fallback_model:{row_cost_text(main_window.spend_view.models_box, 'fallback-zero-model')}"
    )
    heatmap = main_window.spend_view.heatmap
    chart = main_window.spend_view.chart
    if not heatmap._values or sum(heatmap._values.values()) <= 0:
        raise RuntimeError("heatmap has no synthetic token activity")
    if not any(value is not None and value > 0 for _label, value in chart.entries):
        raise RuntimeError("daily chart has no known positive cost series")
    if not any(
        event["width"] > 0 and event["height"] > 0 and event["active_cells"] > 0
        for event in DRAW_CALLBACKS["heatmap"]
    ):
        raise RuntimeError(f"heatmap callback drew no active cells: {DRAW_CALLBACKS['heatmap']}")
    if not any(
        event["width"] > 0 and event["height"] > 0 and event["known_positive"] > 0
        for event in DRAW_CALLBACKS["chart"]
    ):
        raise RuntimeError(f"chart callback drew no positive bars: {DRAW_CALLBACKS['chart']}")

    capture_presented_window(main_window, output)
    main_window.destroy()
    controller.stop()
    if controller._rust_controller is not None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not controller._rust_controller.shutdown_complete():
            time.sleep(0.01)
        if not controller._rust_controller.shutdown_complete():
            raise RuntimeError("Rust controller shutdown did not join")
    elif controller._thread is not None:
        controller._thread.join(timeout=5)
        if controller._thread.is_alive():
            raise RuntimeError("Python fixture controller did not stop")
    application.quit()
    print(
        f"backend={rust_bridge.backend_name()} display={display.get_name()} "
        f"cairo={cairo_support.HAS_CAIRO} heatmap_draws={DRAW_CALLBACKS['heatmap']} "
        f"chart_draws={DRAW_CALLBACKS['chart']} screenshot={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
