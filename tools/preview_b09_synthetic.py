#!/usr/bin/env python3
"""Fixture-only GTK smoke for B09 provider ordering and the tray Auto lane.

    CODEXBAR_RUST_CORE=1 ./tools/preview_b09_synthetic.py

The script uses an isolated HOME, synthetic provider DTOs and a fake tray sink;
it never invokes the CodexBar CLI or reads the user's settings/account data.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
sys.path.insert(0, ROOT)

TYPELIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0")
LIB_DIR = os.path.join(ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_B09_DEPS_READY"):
    temp_home = os.environ.setdefault(
        "CODEXBAR_B09_HOME", tempfile.mkdtemp(prefix="codexbar-b09-home-")
    )
    os.environ["HOME"] = temp_home
    env = os.environ.copy()
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (
        ":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else ""
    )
    env["LD_LIBRARY_PATH"] = LIB_DIR + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    env["CODEXBAR_B09_DEPS_READY"] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

HOME = os.environ.setdefault(
    "CODEXBAR_B09_HOME", tempfile.mkdtemp(prefix="codexbar-b09-home-")
)
os.environ["HOME"] = HOME
os.environ["XDG_CONFIG_HOME"] = os.path.join(HOME, ".config")
os.environ["XDG_DATA_HOME"] = os.path.join(HOME, ".local", "share")
os.environ["XDG_CACHE_HOME"] = os.path.join(HOME, ".cache")
os.environ.setdefault("CODEXBAR_RUST_CORE", "1")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gsk, Gtk  # noqa: E402

from codexbar_gtk.controller import AppState, Controller, automatic_tray_selection  # noqa: E402
from codexbar_gtk.data import Pace, RateWindow, provider_usage_from_payload  # noqa: E402
from codexbar_gtk.history import HistoryStore  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.app import CodexBarApp  # noqa: E402
from codexbar_gtk.ui.popup import PopupContent  # noqa: E402


def synthetic_provider(provider_id: str, used: float, eta: float):
    provider = provider_usage_from_payload({"provider": provider_id, "usage": {}})
    provider.windows = [
        RateWindow(
            key="primary",
            title="Session",
            used_percent=used,
            resets_at=NOW + timedelta(hours=24),
            window_minutes=300,
        )
    ]
    provider.pace = {
        "primary": Pace(
            stage="ahead",
            expected_used_percent=10.0,
            will_last_to_reset=False,
            eta_seconds=eta,
        )
    }
    return provider


def render(widget: Gtk.Widget, path: str, width: int, height: int) -> None:
    widget.set_size_request(width, height)
    widget.set_hexpand(True)
    widget.set_vexpand(True)
    window = Gtk.Window()
    window.set_decorated(False)
    window.set_child(widget)
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
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    renderer.unrealize()
    window.destroy()


class FakeTray:
    available = True

    def __init__(self):
        self.update_args = None

    def update(self, *args):
        self.update_args = args

    def set_menu(self, _items):
        pass

    def register(self):
        pass


def main() -> int:
    if os.environ.get("CODEXBAR_RUST_CORE", "").lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("run with CODEXBAR_RUST_CORE=1")

    Adw.init()
    style.apply_theme()

    prefs = Preferences()
    prefs.set("unifiedIconSource", "automatic")
    prefs.set("providerOrder", ["claude", "codex"])
    prefs.set("hiddenProviders", ["gemini"])

    providers = [
        synthetic_provider("codex", 45.0, 2 * 60 * 60),
        synthetic_provider("claude", 70.0, 5 * 60 * 60),
        synthetic_provider("gemini", 99.0, 1 * 60 * 60),
    ]
    controller = Controller(prefs)
    ordered = controller._ordered(providers)
    assert [provider.provider_id for provider in ordered] == ["claude", "codex"]

    app = CodexBarApp()
    app.prefs = prefs
    app.tray = FakeTray()
    app._update_tray(AppState(providers=ordered))
    assert app.tray.update_args is not None
    tooltip = app.tray.update_args[2]
    assert "Provider: Codex" in tooltip, tooltip

    popup = PopupContent(lambda: None, lambda: None, lambda: None, lambda: None, history=HistoryStore())
    popup.update(AppState(providers=ordered), prefs)
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "docs", "rust-migration", "screenshots", "b09-tray-synthetic.png"
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    render(popup, output, 420, 440)

    unknown = synthetic_provider("unknown", 0.0, 60 * 60)
    unknown.windows[0].usage_known = False
    errored = synthetic_provider("errored", 100.0, 60 * 60)
    errored.error = "synthetic fixture error"
    assert automatic_tray_selection([unknown], now=NOW) is None
    assert automatic_tray_selection([errored, unknown], now=NOW) is None

    app._update_tray(AppState(providers=[unknown]))
    title, body = app.tray.update_args[1:3]
    assert "unavailable" in body.lower(), body
    assert "0%" not in body, body

    unavailable = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    unavailable.add_css_class("tray-unavailable-preview")
    unavailable.set_halign(Gtk.Align.CENTER)
    unavailable.set_valign(Gtk.Align.CENTER)
    unavailable.set_margin_start(28)
    unavailable.set_margin_end(28)
    unavailable.set_margin_top(24)
    unavailable.set_margin_bottom(24)
    title_label = Gtk.Label(label=title)
    title_label.add_css_class("title-3")
    body_label = Gtk.Label(label=body)
    body_label.add_css_class("body")
    unavailable.append(title_label)
    unavailable.append(body_label)
    unavailable_output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        ROOT,
        "docs",
        "rust-migration",
        "screenshots",
        "b09-tray-unknown-unavailable.png",
    )
    css = Gtk.CssProvider()
    css.load_from_data(
        b".tray-unavailable-preview { min-width: 360px; min-height: 160px; "
        b"padding: 24px; background-color: #202124; color: #ffffff; "
        b"border-radius: 12px; } "
        b".tray-unavailable-preview label { color: #ffffff; }"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    os.makedirs(os.path.dirname(os.path.abspath(unavailable_output)), exist_ok=True)
    render(unavailable, unavailable_output, 420, 220)
    print(
        "Rust tray Auto selected Codex for the trusted-ETA fixture; unknown-only "
        f"tray state is unavailable (no fabricated 0%): {output}, {unavailable_output}"
    )
    shutil.rmtree(HOME, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
