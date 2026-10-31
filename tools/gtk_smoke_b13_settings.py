#!/usr/bin/env python3
"""Wayland settings-window smoke using a synthetic CLI and private HOME."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TYPELIB_DIR = os.path.join(
    PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0"
)
LIB_DIR = os.path.join(PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_B13_SETTINGS_DEPS_READY"):
    temp_home = tempfile.mkdtemp(prefix="codexbar-b13-settings-home-")
    env = os.environ.copy()
    env["HOME"] = temp_home
    env["XDG_CONFIG_HOME"] = os.path.join(temp_home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(temp_home, ".local", "share")
    env["XDG_CACHE_HOME"] = os.path.join(temp_home, ".cache")
    env["CODEXBAR_B13_SETTINGS_DEPS_READY"] = "1"
    env["CODEXBAR_B13_SETTINGS_HOME"] = temp_home
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (
        ":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else ""
    )
    env["LD_LIBRARY_PATH"] = LIB_DIR + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

HOME = os.environ.setdefault(
    "CODEXBAR_B13_SETTINGS_HOME", tempfile.mkdtemp(prefix="codexbar-b13-settings-home-")
)
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
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui.settings import SettingsWindow  # noqa: E402


def write_fake_cli(path: str, version: str = "1.0", log_path: str | None = None) -> str:
    log_path = log_path or os.path.join(HOME, "fixture-cli.log")
    script = f'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open({log_path!r}, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"args": args, "tz": os.environ.get("TZ", "unset")}}) + "\\n")
if args == ["config", "providers"]:
    print("codex: enabled (Synthetic Codex)")
elif args == ["hooks", "list", "--format", "json"]:
    print(json.dumps({{"enabled": True, "events": [{{"event": "session-start", "executable": "fixture-hook", "enabled": True}}]}}))
elif args == ["plugins", "list", "--format", "json"]:
    print(json.dumps([{{"id": "fixture-plugin", "name": "Synthetic Plugin", "version": "1"}}]))
elif args and args[:2] == ["config", "set-source"]:
    print("source updated")
elif args and args[0] in ("usage", "cost", "sessions"):
    print("[]")
elif args == ["--version"]:
    print("fixture-cli {version} " + os.environ.get("TZ", "unset"))
else:
    print("{{}}")
'''
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o700)
    return log_path


def pump(context: GLib.MainContext, controller: Controller, predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    loop = GLib.MainLoop.new(context, False)

    def poll() -> bool:
        if controller.uses_rust_controller:
            controller.poll()
        if predicate():
            loop.quit()
            return GLib.SOURCE_REMOVE
        if time.monotonic() >= deadline:
            loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(10, poll)
    loop.run()
    return predicate()


def widget_labels(widget: Gtk.Widget) -> list[str]:
    values: list[str] = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            values.append(child.get_text())
        values.extend(widget_labels(child))
        child = child.get_next_sibling()
    return values


def iter_children(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def capture(window: Gtk.Window, destination: str) -> None:
    if not shutil.which("spectacle"):
        raise RuntimeError("Spectacle is required for a Wayland compositor screenshot")
    window.queue_draw()
    frame_loop = GLib.MainLoop.new(GLib.MainContext.default(), False)

    def finish_frame() -> bool:
        frame_loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(400, finish_frame)
    frame_loop.run()
    process = subprocess.Popen(
        [
            "spectacle",
            "--activewindow",
            "--background",
            "--nonotify",
            "--no-shadow",
            "--delay",
            "600",
            "--output",
            destination,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 20
    while process.poll() is None and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
    if process.poll() is None:
        process.kill()
        process.wait()
        raise RuntimeError("Compositor screenshot timed out")
    _stdout, stderr = process.communicate()
    if process.returncode != 0 or not os.path.isfile(destination) or os.path.getsize(destination) < 10_000:
        raise RuntimeError(f"Compositor screenshot failed: {stderr.strip()}")


def main() -> int:
    if os.environ.get("GDK_BACKEND") != "wayland" or not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("settings smoke requires the active Wayland compositor")
    backend = rust_bridge.backend_name()
    expected_backend = "rust" if os.environ.get("CODEXBAR_RUST_CORE") == "1" else "python"
    if backend != expected_backend:
        raise RuntimeError(f"expected {expected_backend} mode, selected {backend}")

    destination = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PROJECT_ROOT,
        "docs",
        "rust-migration",
        "screenshots",
        f"b13-settings-{backend}-wayland.png",
    )
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    Adw.init()
    style.apply_theme()
    display = Gdk.Display.get_default()
    if display is None or type(display).__name__ != "GdkWaylandDisplay":
        raise RuntimeError("GTK did not select the live Wayland display")

    config = os.path.join(HOME, ".config", "codexbar-gtk")
    prefs = Preferences(os.path.join(config, "settings.json"))
    fake_cli = os.path.join(HOME, "codexbar-fixture")
    log_path = write_fake_cli(fake_cli)
    replacement_cli = os.path.join(HOME, "codexbar-fixture-replacement")
    write_fake_cli(replacement_cli, "1.1", log_path)
    prefs.set("refreshFrequency", "manual")
    prefs.set("cliPath", fake_cli)
    prefs.set("costUsageBucketTimeZone", "UTC")
    prefs.set("preferredCurrencyCode", "EUR")
    history = HistoryStore(os.path.join(config, "history.jsonl"))
    controller = Controller(prefs, CodexBarCLI(fake_cli, timezone="UTC"))
    controller.history = history

    application = Adw.Application(application_id=f"com.codexbar.B13Settings{backend}")
    application.register(None)
    window = None
    notices: list[str] = []
    failures: list[BaseException] = []

    def on_activate(app: Adw.Application) -> None:
        nonlocal window
        try:
            controller.start()
            if controller.uses_rust_controller != (backend == "rust"):
                raise RuntimeError("settings smoke controller did not use the selected backend")
            window = SettingsWindow(app, prefs, controller)
            window._notify = notices.append
            window.set_default_size(900, 760)
            window.set_visible_page(window.general_page)
            GLib.idle_add(run_smoke)
        except BaseException as error:
            failures.append(error)
            app.quit()

    def run_smoke() -> bool:
        nonlocal window
        started = controller.uses_rust_controller or controller._thread is not None
        try:
            if window is None:
                raise RuntimeError("settings window was not constructed after application startup")
            currency_model = window._currency_row.get_model()
            currency_labels = [
                currency_model.get_string(index)
                for index in range(currency_model.get_n_items())
            ]
            if "EUR (€)" not in currency_labels:
                raise RuntimeError(
                    f"settings currency catalog did not include the EUR label: {currency_labels!r}"
                )
            if backend == "rust":
                currency_status = controller.status_async()
                if currency_status is None or currency_status["source"] not in {
                    "offline",
                    "cache",
                    "live",
                }:
                    raise RuntimeError("shared Rust currency source status is unavailable")

            context = GLib.MainContext.default()
            window.present()
            if not pump(
                context,
                controller,
                lambda: len(window._provider_rows) == 1
                and isinstance(window._provider_rows[0], Adw.ExpanderRow)
                and "Synthetic Codex" in window._provider_rows[0].get_title(),
                15,
            ):
                raise RuntimeError(
                    "synthetic provider settings did not render: "
                    f"rows={window._provider_rows!r} "
                    f"labels={widget_labels(window.providers_page)!r}"
                )

            # Exercise the same worker callbacks used by the entry and combo controls.
            window._set_cli_path(replacement_cli)
            if not pump(
                context,
                controller,
                lambda: prefs.get("cliPath") == replacement_cli
                and controller.state.cli_version == "fixture-cli 1.1 UTC"
                and "CLI settings applied" in notices,
                15,
            ):
                raise RuntimeError("path-only settings reconfiguration did not refresh")
            window._set_time_zone("Pacific/Chatham")
            if not pump(
                context,
                controller,
                lambda: prefs.get("costUsageBucketTimeZone") == "Pacific/Chatham"
                and controller.state.cli_version == "fixture-cli 1.1 Pacific/Chatham"
                and notices.count("CLI settings applied") >= 2,
                15,
            ):
                raise RuntimeError("timezone-only settings reconfiguration did not refresh")

            expected_timezone = next(
                index
                for index, (_label, value) in enumerate(window._time_zone_options())
                if value == "Pacific/Chatham"
            )
            if (
                window._cli_path_entry.get_text() != replacement_cli
                or window._timezone_row.get_selected() != expected_timezone
            ):
                raise RuntimeError("settings controls did not reflect the applied CLI configuration")
            window.set_visible_page(window.general_page)

            window._set_provider_source("codex", "web")
            if not pump(
                context,
                controller,
                lambda: os.path.isfile(log_path)
                and any(
                    entry.get("args", [])[:2] == ["config", "set-source"]
                    for entry in (json.loads(line) for line in open(log_path, encoding="utf-8"))
                ),
                10,
            ):
                raise RuntimeError("provider action did not reach the shared CLI facade")

            capture(window, destination)
            print(
                f"backend={backend} display={display.get_name()} provider=synthetic "
                f"cli_path={prefs.get('cliPath')} timezone={prefs.get('costUsageBucketTimeZone')} "
                f"screenshot={destination}"
            )
        except BaseException as error:
            failures.append(error)
        finally:
            if window is not None:
                window.destroy()
            if started:
                controller.stop()
                if controller._rust_controller is not None:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not controller._rust_controller.shutdown_complete():
                        time.sleep(0.01)
                    if not controller._rust_controller.shutdown_complete():
                        failures.append(RuntimeError("Rust controller did not finish shutdown"))
                elif controller._thread is not None:
                    controller._thread.join(timeout=5)
                    if controller._thread.is_alive():
                        failures.append(RuntimeError("Python fixture controller did not stop"))
            application.quit()
        return GLib.SOURCE_REMOVE

    application.connect("activate", on_activate)
    application.run([])
    if failures:
        raise failures[0]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
