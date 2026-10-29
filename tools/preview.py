#!/usr/bin/env python3
"""Render synthetic/local UI state to PNG files.

    ./tools/preview.py [output-dir]

The widgets are drawn through a Gtk.Snapshot and rasterized with cairo. Run on
an available X11/Wayland display; use xvfb-run for a virtual X display when
needed. If local GTK typelibs were bootstrapped into `.deps/`, this script
restarts itself with the same library paths used by `run.sh`.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The no-root bootstrap puts Debian packages in .deps/. Set loader variables
# before importing PyGObject; LD_LIBRARY_PATH is read by the dynamic loader at
# process startup, so re-exec instead of changing it only inside this process.
TYPELIB_DIR = os.path.join(
    ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0"
)
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

from gi.repository import Adw, Gdk, GLib, Gsk, Gtk  # noqa: E402

from codexbar_gtk.cli import CodexBarCLI  # noqa: E402
from codexbar_gtk.controller import AppState  # noqa: E402
from codexbar_gtk.data import (  # noqa: E402
    provider_usage_from_payload,
    spend_from_payloads,
)
from codexbar_gtk.history import HistoryStore  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.cards import ProviderCard, StatTile  # noqa: E402
from codexbar_gtk.ui.popup import PopupContent  # noqa: E402
from codexbar_gtk.ui.sessions import SessionsView  # noqa: E402
from codexbar_gtk.ui.spend import SpendView  # noqa: E402


def render(widget: Gtk.Widget, path: str, width: int, height: int) -> None:
    """Draw a widget into a PNG file.

    The widget is mapped into an off-screen window first: a widget that was
    never allocated cannot be snapshotted.
    """
    import cairo
    import time

    widget.set_size_request(width, height)
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
    paintable = Gtk.WidgetPaintable.new(widget)
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        print(f"could not render {path}")
        window.destroy()
        return
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    context_cairo = cairo.Context(surface)
    node.draw(context_cairo)
    surface.write_to_png(path)
    print(f"wrote {path}")
    window.destroy()


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/codexbar-gtk-preview"
    os.makedirs(outdir, exist_ok=True)

    Adw.init()
    style.apply_theme()

    prefs = Preferences()
    cli = CodexBarCLI()
    state = AppState(
        providers=[provider_usage_from_payload(p) for p in cli.usage()],
        spend=spend_from_payloads(cli.cost(provider="both")),
    )
    history = HistoryStore()

    # A single provider card.
    if state.providers:
        card = ProviderCard(state.providers[0], history=history)
        render(card, os.path.join(outdir, "card.png"), 420, 260)

    # The compact panel.
    popup = PopupContent(
        lambda: None,
        lambda: None,
        lambda: None,
        lambda: None,
        history=history,
        on_check_updates=lambda: None,
        on_restart=lambda: None,
    )
    popup.update(state, prefs)
    render(popup, os.path.join(outdir, "popup.png"), 420, 400)

    # A dashboard-like composition.
    dashboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    dashboard.set_size_request(880, -1)
    dashboard.add_css_class("cb-dash-grid")
    tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    tiles.set_homogeneous(True)
    highest = max((p.max_used_percent for p in state.providers), default=0.0)
    credits = sum(p.credits_remaining or 0 for p in state.providers)
    for label, value, icon in (
        ("Providers", str(len(state.providers)), "network-server-symbolic"),
        ("Highest usage", f"{highest:.0f}%", "utilities-system-monitor-symbolic"),
        ("Credits", f"{credits:,.0f}", "emblem-money-symbolic"),
        (
            "Local spend",
            f"${state.spend.total_cost:,.2f}" if state.spend else "—",
            "document-open-recent-symbolic",
        ),
    ):
        tiles.append(StatTile(label, value, "", icon))
    dashboard.append(tiles)
    for provider in state.providers:
        dashboard.append(ProviderCard(provider, history=history))
    render(dashboard, os.path.join(outdir, "dashboard.png"), 900, 640)

    # The sessions page.
    sessions = SessionsView()
    sessions.update(state.sessions)
    render(sessions, os.path.join(outdir, "sessions.png"), 900, 420)

    # The spending page.
    spend = SpendView(prefs)
    spend.update(state.spend)
    render(spend, os.path.join(outdir, "spend.png"), 900, 560)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
