#!/usr/bin/env python3
"""Render the Rust-backed notification delivery path with synthetic data only."""

from __future__ import annotations

import os
import atexit
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Isolate any preference/history paths before importing application modules.
_home = tempfile.mkdtemp(prefix="codexbar-b08-home-")
atexit.register(shutil.rmtree, _home, ignore_errors=True)
os.environ["HOME"] = _home
os.environ["CODEXBAR_RUST_CORE"] = "1"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

from codexbar_gtk.controller import AppState, Controller  # noqa: E402
from codexbar_gtk.data import Pace, RateWindow, provider_usage_from_payload  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui.app import CodexBarApp  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402


class DeliveryHarness:
    def __init__(self, controller):
        self.controller = controller
        self.events = []

    def _notify(self, title, message, id=None):
        self.events.append({"title": title, "body": message, "id": id})


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/rust-migration/screenshots/b08-notifications-synthetic.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Adw.init()
    style.apply_theme()
    css = Gtk.CssProvider()
    css.load_from_data(b"window { background: #111820; color: #eef3f8; } .card { background: #253241; border: 1px solid #40546b; border-radius: 12px; } label { color: #eef3f8; }")
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    provider = provider_usage_from_payload({"provider": "codex", "usage": {}})
    provider.account_email = "fixture@example.invalid"
    provider.windows = [RateWindow(
        key="primary", title="Session", used_percent=100,
        resets_at=now + timedelta(hours=24), window_minutes=300,
    )]
    provider.pace = {"primary": Pace(
        stage="behind", delta_percent=4.0, expected_used_percent=10.0,
        will_last_to_reset=False, eta_seconds=7200.0,
    )}
    provider.reset_credits = [{"title": "Synthetic reset", "expires_at": now + timedelta(hours=22)}]
    state = AppState(providers=[provider])

    controller = Controller(Preferences(os.path.join(_home, "settings.json")), cli=object())
    delivery = DeliveryHarness(controller)
    CodexBarApp._check_notifications(delivery, state)
    if len(delivery.events) != 4:
        raise RuntimeError(
            "expected four synthetic Rust notification events, got "
            + repr([(event["title"], event["body"]) for event in delivery.events])
        )

    window = Gtk.Window()
    window.set_title("CodexBar GTK · Synthetic Notifications")
    window.set_default_size(620, 520)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    root.set_margin_top(24)
    root.set_margin_bottom(24)
    root.set_margin_start(24)
    root.set_margin_end(24)
    title = Gtk.Label(label="Notification policy preview")
    title.add_css_class("title-1")
    title.set_xalign(0)
    root.append(title)
    subtitle = Gtk.Label(label="Fixture data · Rust policy outcomes · OS delivery boundary")
    subtitle.add_css_class("dim-label")
    subtitle.set_xalign(0)
    root.append(subtitle)
    for event in delivery.events:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.add_css_class("card")
        heading = Gtk.Label(label=event["title"])
        heading.add_css_class("heading")
        heading.set_xalign(0)
        heading.set_margin_start(14)
        heading.set_margin_top(12)
        body = Gtk.Label(label=event["body"])
        body.set_xalign(0)
        body.set_wrap(True)
        body.set_margin_start(14)
        body.set_margin_end(14)
        body.set_margin_bottom(12)
        card.append(heading)
        card.append(body)
        root.append(card)
    window.set_child(root)
    window.present()
    context = GLib.MainContext.default()
    for _ in range(60):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(root).snapshot(snapshot, 620, 520)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("notification preview did not produce a render node")
    renderer = Gsk.Renderer.new_for_surface(window.get_surface())
    if renderer is None:
        raise RuntimeError("could not create a GTK renderer for the notification preview")
    viewport = Graphene.Rect().init(0, 0, 620, 520)
    renderer.render_texture(node, viewport).save_to_png(out)
    renderer.unrealize()
    print(f"wrote synthetic notification preview to {out}")
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
