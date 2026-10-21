#!/usr/bin/env python3
"""Render the UI to PNG files by screenshotting a real window.

The app runs against the live compositor, so this gives an exact picture of what
the user sees (fonts, colors, spacing) without a separate design tool.

    ./tools/preview.py [output-dir]
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from codexbar_gtk.cli import CodexBarCLI  # noqa: E402
from codexbar_gtk.controller import AppState  # noqa: E402
from codexbar_gtk.data import provider_usage_from_payload, spend_from_payloads  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.cards import ProviderCard  # noqa: E402
from codexbar_gtk.ui.popup import PopupContent  # noqa: E402
from codexbar_gtk.ui.window import MainWindow  # noqa: E402
from codexbar_gtk.ui.spend import SpendView  # noqa: E402

MARKER = (255, 0, 255)

EXTRA_CSS = b"""
.preview-marker {
  background: #ff00ff;
}
"""


def capture(path: str) -> None:
    tmp = "/tmp/opencode/_preview_full.png"
    subprocess.run(["spectacle", "-b", "-n", "-o", tmp], check=False, capture_output=True)
    if not os.path.exists(tmp):
        print("screenshot failed")
        return
    from PIL import Image

    image = Image.open(tmp).convert("RGB")
    pixels = image.load()
    width, height = image.size
    xs, ys = [], []
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if pixels[x, y] == MARKER:
                xs.append(x)
                ys.append(y)
    if not xs:
        print("marker not found")
        return
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    image.crop((left, top, right, bottom)).save(path)
    print(f"wrote {path}")


def show_widget(widget: Gtk.Widget, path: str, size: tuple[int, int]) -> None:
    """Show one widget framed by magenta markers so the crop is exact."""
    strip = Gtk.Box()
    strip.set_size_request(-1, 6)
    strip.add_css_class("preview-marker")

    side = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    left = Gtk.Box()
    left.set_size_request(6, -1)
    left.add_css_class("preview-marker")
    right = Gtk.Box()
    right.set_size_request(6, -1)
    right.add_css_class("preview-marker")
    side.append(left)
    side.append(widget)
    side.append(right)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    root.append(strip)
    root.append(side)
    bottom = Gtk.Box()
    bottom.set_size_request(-1, 6)
    bottom.add_css_class("preview-marker")
    root.append(bottom)

    window = Gtk.Window()
    window.set_decorated(False)
    window.set_default_size(size[0] + 12, size[1] + 12)
    window.set_child(root)
    window.present()
    return window


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode/preview"
    os.makedirs(outdir, exist_ok=True)

    Adw.init()
    style.apply_theme()
    provider = Gtk.CssProvider()
    provider.load_from_data(EXTRA_CSS)
    display = __import__("gi.repository.Gdk", fromlist=["Gdk"]).Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    prefs = Preferences()
    cli = CodexBarCLI()
    payloads = cli.usage()
    providers = [provider_usage_from_payload(p) for p in payloads]
    state = AppState(providers=providers, spend=spend_from_payloads(cli.cost()))

    card = ProviderCard(
        providers[0],
        show_used=bool(prefs.get("usageBarsShowUsed")),
        reset_style=str(prefs.get("resetTimesOption")),
        show_pace=bool(prefs.get("paceVisible")),
        thresholds=list(prefs.get("quotaWarningThresholds") or [80, 95]),
    )
    spend = SpendView()
    spend.update(state.spend)

    popup = PopupContent(lambda: None, lambda: None, lambda: None, lambda: None)
    popup.update(state, prefs)

    app = Adw.Application(application_id="com.steipete.CodexBarGTK")
    window = MainWindow(app, prefs)
    window.update(state)
    dashboard = window.get_content()

    steps = [
        (card, os.path.join(outdir, "card.png"), (400, 260)),
        (popup, os.path.join(outdir, "popup.png"), (380, 520)),
        (dashboard, os.path.join(outdir, "dashboard.png"), (920, 680)),
        (spend, os.path.join(outdir, "spend.png"), (900, 600)),
    ]

    def run_step(index: int) -> bool:
        if index >= len(steps):
            return False
        widget, path, size = steps[index]
        window = show_widget(widget, path, size)

        def grab() -> bool:
            capture(path)
            window.destroy()
            GLib.timeout_add(400, lambda: run_step(index + 1))
            return False

        GLib.timeout_add(1200, grab)
        return False

    GLib.timeout_add(600, lambda: run_step(0))

    loop = GLib.MainLoop()
    GLib.timeout_add(30000, loop.quit)
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
