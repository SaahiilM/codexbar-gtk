#!/usr/bin/env python3
"""Wayland smoke for B13b2 app actions using isolated synthetic fixtures."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEMP_HOME = os.environ.get("CODEXBAR_B13B2_HOME") or tempfile.mkdtemp(
    prefix="codexbar-b13b2-home-"
)
atexit.register(shutil.rmtree, TEMP_HOME, ignore_errors=True)
TYPELIB_DIR = os.path.join(
    PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu", "girepository-1.0"
)
LIB_DIR = os.path.join(PROJECT_ROOT, ".deps", "root", "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(TYPELIB_DIR) and not os.environ.get("CODEXBAR_B13B2_DEPS_READY"):
    env = os.environ.copy()
    env.update(
        {
            "HOME": TEMP_HOME,
            "XDG_CONFIG_HOME": os.path.join(TEMP_HOME, ".config"),
            "XDG_DATA_HOME": os.path.join(TEMP_HOME, ".local", "share"),
            "XDG_CACHE_HOME": os.path.join(TEMP_HOME, ".cache"),
            "CODEXBAR_B13B2_DEPS_READY": "1",
            "CODEXBAR_B13B2_HOME": TEMP_HOME,
        }
    )
    env["GI_TYPELIB_PATH"] = TYPELIB_DIR + (
        ":" + env["GI_TYPELIB_PATH"] if env.get("GI_TYPELIB_PATH") else ""
    )
    env["LD_LIBRARY_PATH"] = LIB_DIR + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)

os.environ["HOME"] = TEMP_HOME
os.environ["XDG_CONFIG_HOME"] = os.path.join(TEMP_HOME, ".config")
os.environ["XDG_DATA_HOME"] = os.path.join(TEMP_HOME, ".local", "share")
os.environ["XDG_CACHE_HOME"] = os.path.join(TEMP_HOME, ".cache")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib  # noqa: E402

from codexbar_gtk import rust_bridge  # noqa: E402
from codexbar_gtk.prefs import Preferences  # noqa: E402
from codexbar_gtk.ui import style  # noqa: E402
from codexbar_gtk.ui import app as app_module  # noqa: E402
from codexbar_gtk.updates import UpdateCheckRequest  # noqa: E402


def _write_fixture_cli(path: str) -> None:
    script = """#!/bin/sh
case "$1" in
  --version) printf 'fixture-cli 1.0\\n' ;;
  usage|cost|sessions) printf '[]\\n' ;;
  *) printf '{}\\n' ;;
esac
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o700)


def _write_fake_icon_cache(path: str, capture: str) -> None:
    script = f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {capture!r}\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o700)


def _capture_active_window(path: str) -> None:
    if not shutil.which("spectacle"):
        raise RuntimeError("Spectacle is required for Wayland compositor capture")
    env = os.environ.copy()
    # The application runs on a private fixture bus; use the existing desktop
    # bus only for KWin's compositor screenshot request.
    capture_bus = env.get("CODEXBAR_B13B2_CAPTURE_DBUS")
    if capture_bus:
        env["DBUS_SESSION_BUS_ADDRESS"] = capture_bus
    process = subprocess.run(
        [
            "spectacle",
            "--activewindow",
            "--background",
            "--new-instance",
            "--nonotify",
            "--no-shadow",
            "--delay",
            "600",
            "--output",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )
    if process.returncode or not os.path.isfile(path) or os.path.getsize(path) < 10_000:
        raise RuntimeError("Wayland compositor did not capture the active update dialog")


def main() -> int:
    if os.environ.get("GDK_BACKEND") != "wayland" or not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("B13b2 smoke requires the active Wayland compositor")
    backend = rust_bridge.backend_name()
    expected = "rust" if os.environ.get("CODEXBAR_RUST_CORE") == "1" else "python"
    if backend != expected:
        raise RuntimeError(f"expected {expected} mode, selected {backend}")
    display = Gdk.Display.get_default()
    if display is None or type(display).__name__ != "GdkWaylandDisplay":
        raise RuntimeError("GTK did not select the active Wayland display")

    config = os.path.join(TEMP_HOME, ".config", "codexbar-gtk")
    os.makedirs(config, exist_ok=True)
    fixture_cli = os.path.join(TEMP_HOME, "codexbar-fixture")
    _write_fixture_cli(fixture_cli)
    Preferences().set("cliPath", fixture_cli)
    Preferences().set("costUsageBucketTimeZone", "UTC")
    Preferences().set("refreshFrequency", "manual")
    Preferences().set("showTray", False)

    tool_dir = os.path.join(TEMP_HOME, "bin")
    os.makedirs(tool_dir, exist_ok=True)
    icon_cache_log = os.path.join(TEMP_HOME, "icon-cache-argv.txt")
    _write_fake_icon_cache(
        os.path.join(tool_dir, "gtk4-update-icon-cache"), icon_cache_log
    )
    os.environ["PATH"] = tool_dir + os.pathsep + os.environ.get("PATH", "")

    body = b"MARKETING_VERSION=0.82.0\nCURRENT_PROJECT_VERSION=48\n"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    Adw.init()
    style.apply_theme()
    # Avoid forwarding activation to an already-running real app instance.
    app_module.APP_ID = f"{app_module.APP_ID.lower()}.b13b2{backend}"
    app = app_module.CodexBarApp()
    app.prefs.set("cliPath", fixture_cli)
    app.prefs.set("costUsageBucketTimeZone", "UTC")
    app.prefs.set("refreshFrequency", "manual")
    app.prefs.set("showTray", False)
    original_check = app.controller.check_update
    request_url = f"http://127.0.0.1:{server.server_port}/VERSION"

    def check_update(request: UpdateCheckRequest):
        return original_check(
            UpdateCheckRequest(
                request.current_version,
                request.current_build,
                timeout=2.0,
                url=request_url,
            )
        )

    app.controller.check_update = check_update
    original_finish = app._finish_update_check
    app._smoke_dialog = None
    failures: list[BaseException] = []
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PROJECT_ROOT,
        "docs",
        "rust-migration",
        "screenshots",
        f"b13b2-actions-{backend}-wayland.png",
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    def finish(dialog, result):
        original_finish(dialog, result)
        app._smoke_dialog = app._update_dialog
        if (
            app._smoke_dialog is None
            or app._smoke_dialog.get_heading() != "Update available: 0.82.0 (48)"
            or "pull the latest changes" not in app._smoke_dialog.get_body()
        ):
            failures.append(RuntimeError("synthetic update result did not render in GTK"))
        else:
            print(
                f"completed_update_dialog_heading={app._smoke_dialog.get_heading()}",
                flush=True,
            )
        return GLib.SOURCE_REMOVE

    app._finish_update_check = finish
    capture_started = False

    def begin() -> bool:
        try:
            app._ensure_main_window().present()
            app._write_icons("#10A37F")
            app._check_for_updates()
        except BaseException as error:
            failures.append(error)
            app.quit()
        return GLib.SOURCE_REMOVE

    def capture_finished(error: BaseException | None = None) -> bool:
        if error is not None:
            failures.append(error)
        else:
            print(
                f"backend={backend} display={display.get_name()} "
                f"update=synthetic-current-latest icon_cache=fixture-tool "
                f"screenshot={output}"
            )
        app.quit()
        return GLib.SOURCE_REMOVE

    def capture_in_worker() -> None:
        try:
            # Leave the GTK context free to render the completed dialog first.
            time.sleep(0.5)
            _capture_active_window(output)
            GLib.idle_add(capture_finished)
        except BaseException as error:
            GLib.idle_add(capture_finished, error)

    def poll() -> bool:
        nonlocal capture_started
        dialog = app._smoke_dialog
        if (
            not capture_started
            and dialog is not None
            and dialog.get_heading().startswith("Update available:")
            and os.path.isfile(icon_cache_log)
        ):
            capture_started = True
            threading.Thread(
                target=capture_in_worker,
                name="b13b2-screenshot",
                daemon=True,
            ).start()
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(750, begin)
    GLib.timeout_add(25, poll)
    try:
        app.run([])
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    if failures:
        raise failures[0]
    if not os.path.isfile(output):
        raise RuntimeError("B13b2 smoke exited without an update screenshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
