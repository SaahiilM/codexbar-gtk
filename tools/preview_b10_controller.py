#!/usr/bin/env python3
"""Fixture-only GTK smoke for the B10 Rust refresh controller.

Run with ``CODEXBAR_RUST_CORE=1 tools/preview_b10_controller.py``. It creates
an isolated HOME and fake CLI, exercises the Python/GTK bridge, and writes a
synthetic panel screenshot. No real CLI, account, network or credential data
is used.
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
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_B10_DEPS_READY"):
    temp_home = tempfile.mkdtemp(prefix="codexbar-b10-home-")
    env = os.environ.copy()
    env["HOME"] = temp_home
    env["XDG_CONFIG_HOME"] = os.path.join(temp_home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(temp_home, ".local", "share")
    env["XDG_CACHE_HOME"] = os.path.join(temp_home, ".cache")
    env["CODEXBAR_B10_DEPS_READY"] = "1"
    env["CODEXBAR_B10_HOME"] = temp_home
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else "")
    env["LD_LIBRARY_PATH"] = LIB_DIR + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

HOME = os.environ.setdefault("CODEXBAR_B10_HOME", tempfile.mkdtemp(prefix="codexbar-b10-home-"))
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
from codexbar_gtk.ui.popup import PopupContent  # noqa: E402


class FakeTray:
    available = True

    def __init__(self) -> None:
        self.update_args = None

    def update(self, *args) -> None:
        self.update_args = args

    def set_menu(self, _items) -> None:
        pass

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
    "identity": {"accountEmail": "fixture@example.invalid", "loginMethod": "oauth", "plan": "Synthetic"}
  },
  "pace": {"primary": {"stage": "behind", "expectedUsedPercent": 30, "willLastToReset": False, "etaSeconds": 3600, "runOutProbability": 0.8}}
}
if args and args[0] == "usage":
    print(json.dumps([provider]))
elif args and args[0] == "cost":
    print(json.dumps([{"provider":"codex", "currencyCode":"USD", "totals":{"totalCost":42.5,"totalTokens":9000,"priced":True,"sessionCost":6.25,"sessionTokens":1000}}]))
elif args and args[0] == "sessions":
    print(json.dumps([{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic-project","cwd":"/tmp/synthetic-project","pid":42,"host":"fixture-host","startedAt":"2026-10-30T11:00:00Z","lastActivityAt":"2026-10-30T11:59:00Z"}]))
elif args == ["--version"]:
    print("fixture-cli 1.0")
else:
    print(json.dumps([]))
'''
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o755)


def render(widget: Gtk.Widget, path: str, width: int, height: int) -> None:
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
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("GTK did not produce a render node")
    renderer = Gsk.Renderer.new_for_surface(window.get_surface())
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    renderer.unrealize()
    window.destroy()


def main() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("GTK smoke requires the existing graphical session")
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "docs", "rust-migration", "screenshots", "b10-controller-synthetic.png"
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    Adw.init()
    style.apply_theme()

    prefs = Preferences(os.path.join(HOME, ".config", "codexbar-gtk", "settings.json"))
    prefs.set("refreshFrequency", "manual")
    prefs.set("unifiedIconSource", "automatic")
    prefs.set("hidePersonalInfo", True)
    fake_cli = os.path.join(HOME, "codexbar-fixture")
    write_fake_cli(fake_cli)
    history = HistoryStore(os.path.join(HOME, ".config", "codexbar-gtk", "history.jsonl"))
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
    provider = controller.state.providers[0]
    if not provider.windows[0].usage_known or provider.windows[1].usage_known:
        raise RuntimeError("known-zero/unknown quota semantics changed in the GTK bridge")
    if controller.state.spend is None or controller.state.spend.total_cost != 42.5:
        raise RuntimeError("synthetic spend DTO did not reach the GTK state")
    if len(controller.state.sessions) != 1 or len(history.read_all()) != 2:
        raise RuntimeError("sessions/history did not reach the GTK path")
    selected = controller.automatic_tray_selection(controller.state.providers)
    if selected is None or selected[0].provider_id != "codex" or selected[1].key != "primary":
        raise RuntimeError("GTK adapter did not resolve the stored B09 tray selection")

    app = CodexBarApp()
    app.prefs = prefs
    app.controller = controller
    app.tray = FakeTray()
    delivered = []
    app._notify = lambda title, message, id=None: delivered.append({"title": title, "body": message, "id": id})
    app._apply_state(controller.state)
    if not app.tray.update_args or "Provider: Codex" not in app.tray.update_args[2]:
        raise RuntimeError("real GTK tray presentation did not consume controller state")
    if not delivered or delivered[0]["title"] != "Quota warning":
        raise RuntimeError("typed Rust notification did not cross the GTK delivery adapter")

    popup = PopupContent(lambda: None, lambda: None, lambda: None, lambda: None, history=history)
    popup.update(controller.state, prefs)
    render(popup, output, 460, 480)

    controller.stop()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not controller._rust_controller.shutdown_complete():
        time.sleep(0.01)
    if not controller._rust_controller.shutdown_complete():
        raise RuntimeError("Rust controller shutdown did not join")
    print(f"fixture GTK refresh rendered: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
