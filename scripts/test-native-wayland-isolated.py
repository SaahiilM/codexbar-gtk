#!/usr/bin/env python3
"""Run a bounded native GTK Wayland action smoke in a private Weston session.

This harness exercises app GActions and one AT-SPI action. Those are observable
GTK actions, not physical Wayland pointer/key input or KDE shell parity.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

APP_ID = "com.steipete.CodexBarGTK"
SETTING_KEY = "refreshAllProvidersOnMenuOpen"
SETTING_LABEL = "Refresh when the panel opens"
SPEND_LABEL = "Spend history range: 7 days"
AT_SPI_PROBE = r'''
import json, sys, time
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

mode, pid_text, expected = sys.argv[1:]
pid = int(pid_text)
Atspi.init()
desktop = Atspi.get_desktop(0)
seen = set()
nodes = []
def visit(node, depth=0):
    if depth > 30:
        return
    try:
        object_path = node.get_object_path()
        try:
            app = node.get_application()
            bus_name = app.get_bus_name() if app else ""
        except Exception:
            app, bus_name = None, ""
        key = (str(bus_name), str(object_path), str(node.get_name()))
        if key in seen:
            return
        seen.add(key)
        name = node.get_name() or ""
        role = node.get_role_name() or ""
        if app:
            try:
                if app.get_process_id() == pid:
                    nodes.append((node, name, role))
            except Exception:
                pass
        count = node.get_child_count()
        for index in range(min(count, 500)):
            child = node.get_child_at_index(index)
            if child is not None:
                visit(child, depth + 1)
    except Exception:
        return
for index in range(desktop.get_child_count()):
    child = desktop.get_child_at_index(index)
    if child is not None:
        visit(child)

if mode == "title":
    frames = [name for _, name, role in nodes if role in ("frame", "window")]
    matching = [name for name in frames if expected in name]
    print(json.dumps({"found": bool(matching), "titles": frames, "match": matching[0] if matching else None}))
elif mode == "checked":
    matches = []
    for node, name, role in nodes:
        if name == expected:
            try:
                checked = node.get_state_set().contains(Atspi.StateType.CHECKED)
            except Exception:
                checked = False
            matches.append({"name": name, "role": role, "checked": bool(checked)})
    print(json.dumps({"found": bool(matches), "matches": matches}))
elif mode == "activate":
    matches = [(node, role) for node, name, role in nodes
               if name == expected and role in ("check box", "switch", "toggle button")]
    if len(matches) != 1:
        print(json.dumps({"ok": False, "reason": "expected exactly one named toggle", "count": len(matches)}))
        raise SystemExit(3)
    node, role = matches[0]
    actions = node.get_action_iface()
    if actions is None or actions.get_n_actions() < 1:
        print(json.dumps({"ok": False, "reason": "toggle exposes no AT-SPI action", "role": role}))
        raise SystemExit(4)
    before = node.get_state_set().contains(Atspi.StateType.CHECKED)
    if before:
        print(json.dumps({"ok": False, "reason": "fixture toggle must start off", "role": role}))
        raise SystemExit(5)
    ok = actions.do_action(0)
    deadline = time.monotonic() + 5
    after = False
    while time.monotonic() < deadline:
        try:
            after = node.get_state_set().contains(Atspi.StateType.CHECKED)
        except Exception:
            after = False
        if after:
            break
        time.sleep(0.05)
    print(json.dumps({"ok": bool(ok and after), "role": role, "action": actions.get_action_name(0),
                      "before_checked": bool(before), "after_checked": bool(after)}))
    raise SystemExit(0 if ok and after else 6)
else:
    raise SystemExit("unknown AT-SPI probe mode")
'''


def sanitized_environment(source: dict[str, str], home: pathlib.Path,
                          runtime: pathlib.Path, wayland_display: str,
                          fake_cli: pathlib.Path,
                          private_bus_address: str) -> dict[str, str]:
    """Return a private client environment with host display/session handles removed."""
    env = dict(source)
    for key in (
        "DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SYSTEM_BUS_ADDRESS",
        "AT_SPI_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_SESSION_ID",
        "XDG_CURRENT_DESKTOP", "KDE_FULL_SESSION", "KDE_SESSION_VERSION",
        "GDK_BACKEND", "GSK_RENDERER", "GTK_A11Y", "GTK_USE_PORTAL",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    ):
        env.pop(key, None)
    env.update({
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": wayland_display,
        "DBUS_SESSION_BUS_ADDRESS": private_bus_address,
        "GDK_BACKEND": "wayland",
        "GSK_RENDERER": "cairo",
        "GTK_USE_PORTAL": "0",
        "CODEXBAR_CLI": str(fake_cli),
        "NATIVE_CLI_LOG": str(home / "cli-calls.log"),
    })
    return env


def _symlink_if_missing(path: pathlib.Path, target: pathlib.Path) -> None:
    if not path.exists() and target.exists():
        path.symlink_to(os.path.relpath(target, path.parent))


def resolve_weston(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    """Find system Weston, or rootlessly extract the apt Weston/Pixman package pair."""
    weston = shutil.which("weston")
    screenshooter = shutil.which("weston-screenshooter")
    if weston and screenshooter:
        candidates = [pathlib.Path("/usr/lib/x86_64-linux-gnu"),
                      pathlib.Path("/usr/lib/aarch64-linux-gnu"),
                      pathlib.Path("/usr/lib")]
        for libdir in candidates:
            backend = next(libdir.glob("libweston-*/headless-backend.so"), None)
            shell = libdir / "weston/kiosk-shell.so"
            if backend and shell.is_file():
                return pathlib.Path(weston), pathlib.Path(screenshooter), backend, shell

    download = root / "weston-download"
    extracted = root / "weston-root"
    download.mkdir(mode=0o700)
    extracted.mkdir(mode=0o700)
    subprocess.run(["apt-get", "download", "weston", "libweston-13-0"],
                   cwd=download, check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, text=True, timeout=120)
    debs = list(download.glob("*.deb"))
    if len(debs) < 2 or not shutil.which("dpkg-deb"):
        raise RuntimeError("rootless Weston extraction needs apt-get and dpkg-deb")
    for package in debs:
        subprocess.run(["dpkg-deb", "-x", str(package), str(extracted)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=60)
    libdirs = list((extracted / "usr/lib").glob("*linux-gnu"))
    if len(libdirs) != 1:
        raise RuntimeError("could not identify the extracted Weston library directory")
    libdir = libdirs[0]
    weston_lib = next(libdir.glob("libweston-13.so.0.*"), None)
    exec_lib = next((libdir / "weston").glob("libexec_weston.so.0.*"), None)
    if weston_lib:
        _symlink_if_missing(libdir / "libweston-13.so.0", weston_lib)
    if exec_lib:
        _symlink_if_missing(libdir / "libexec_weston.so.0", exec_lib)
    backend = libdir / "libweston-13/headless-backend.so"
    shell = libdir / "weston/kiosk-shell.so"
    weston = extracted / "usr/bin/weston"
    screenshooter = extracted / "usr/bin/weston-screenshooter"
    for path in (weston, screenshooter, backend, shell):
        if not path.is_file():
            raise RuntimeError(f"rootless Weston extraction is incomplete: {path}")
    return weston, screenshooter, backend, shell


def fake_cli_text() -> str:
    return r'''#!/bin/sh
printf '%s\n' "$*" >> "$NATIVE_CLI_LOG"
case "${1:-}" in
  --version) printf 'CodexBar synthetic fixture 0.82.0\n' ;;
  usage) printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":42,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300}}}]' ;;
  cost) printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{"priced":3,"unpriced":1},"provenance":"synthetic_history","daily":[{"date":"2026-11-09","totalCost":3.25,"totalTokens":800},{"date":"2026-11-08","totalCost":0,"totalTokens":0}],"projects":[],"models":[]}]' ;;
  sessions|hooks|plugins|providers|config|auth) printf '[]\n' ;;
  *) printf '[]\n' ;;
esac
'''


def wait_until(description: str, predicate, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {description}; last result={last!r}")


def atspi_probe(python: str, mode: str, pid: int, expected: str) -> dict:
    result = subprocess.run([python, "-c", AT_SPI_PROBE, mode, str(pid), expected],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f"AT-SPI {mode} probe failed: {result.stderr.strip()} {result.stdout.strip()}")
    return json.loads(result.stdout)


def gaction(name: str, parameter: str | None = None) -> None:
    command = ["gapplication", "action", APP_ID, name]
    if parameter is not None:
        command.append(parameter)
    subprocess.run(command, check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, text=True, timeout=10)


def capture_screen(screenshooter: pathlib.Path, env: dict[str, str],
                   capture_dir: pathlib.Path, output: pathlib.Path) -> None:
    capture_dir.mkdir(mode=0o700)
    result = subprocess.run([str(screenshooter)], cwd=capture_dir, env=env,
                            capture_output=True, text=True, timeout=15)
    candidates = list(capture_dir.glob("wayland-screenshot-*.png"))
    if result.returncode or len(candidates) != 1 or candidates[0].stat().st_size < 1000:
        raise RuntimeError(f"private Weston screenshot failed: {result.stderr.strip()} {result.stdout.strip()}")
    shutil.copyfile(candidates[0], output)
    output.chmod(0o600)


def inside_run(args) -> dict:
    binary = pathlib.Path(args.binary).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"native GTK binary is not executable: {binary}")
    artifact_dir = pathlib.Path(args.artifact_dir).resolve()
    if artifact_dir.exists():
        if not artifact_dir.is_dir() or any(artifact_dir.iterdir()):
            raise RuntimeError(f"artifact directory must be new or empty: {artifact_dir}")
    else:
        artifact_dir.mkdir(parents=True, mode=0o700)
        artifact_dir.chmod(0o700)
    python_candidates = [shutil.which("python3"), "/usr/bin/python3", sys.executable]
    python = None
    for candidate in dict.fromkeys(item for item in python_candidates if item):
        probe = subprocess.run([candidate, "-c",
            "import gi; gi.require_version('Atspi', '2.0'); from gi.repository import Atspi"],
            capture_output=True, text=True, timeout=5)
        if probe.returncode == 0:
            python = candidate
            break
    if python is None:
        raise RuntimeError("AT-SPI probe requires Python GI bindings for Atspi 2.0")
    with tempfile.TemporaryDirectory(prefix="codexbar-native-wayland-") as scratch_name:
        scratch = pathlib.Path(scratch_name)
        scratch.chmod(0o700)
        home, runtime = scratch / "home", scratch / "runtime"
        home.mkdir(mode=0o700)
        runtime.mkdir(mode=0o700)
        cli = scratch / "fake-codexbar"
        cli.write_text(fake_cli_text(), encoding="utf-8")
        cli.chmod(0o700)
        prefs = home / ".config/codexbar-gtk/settings.json"
        prefs.parent.mkdir(parents=True, mode=0o700)
        prefs.write_text(json.dumps({SETTING_KEY: False}) + "\n", encoding="utf-8")

        weston, screenshooter, backend, shell = resolve_weston(scratch)
        libdir = backend.parent.parent
        private_bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not private_bus_address:
            raise RuntimeError("runner must be started inside its private dbus-run-session")
        env = sanitized_environment(os.environ, home, runtime, "wayland-private", cli,
                                    private_bus_address)
        env.update({
            "LD_LIBRARY_PATH": str(libdir) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""),
            "WESTON_DATA_DIR": str(weston.parent.parent / "share/weston"),
            "WESTON_MODULE_MAP": f"headless-backend.so={backend};kiosk-shell.so={shell}",
        })
        # All helper processes, including gapplication and AT-SPI probes, inherit
        # the private bus and private Wayland socket rather than host handles.
        os.environ.clear()
        os.environ.update(env)
        weston_log = scratch / "weston.log"
        compositor = subprocess.Popen(
            [str(weston), "--backend=headless", "--renderer=pixman",
             "--socket=wayland-private", "--width=1280", "--height=900",
             "--shell=kiosk-shell.so", "--no-config", "--idle-time=0", "--debug",
             f"--log={weston_log}"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        app = None
        evidence = {"compositor": "rootless Weston headless Pixman",
                    "backend": "Wayland", "GDK_BACKEND": "wayland",
                    "GSK_RENDERER": "cairo", "screenshots": {}, "actions": []}
        try:
            wait_until("private Weston socket", lambda: (runtime / "wayland-private").is_socket()
                       if (runtime / "wayland-private").exists() else False)
            subprocess.run(["wayland-info"], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, check=True, timeout=10)
            # Enable an isolated AT-SPI bus and make a private fixture preference
            # observable through the real native Settings control.
            app_log = scratch / "native-app.log"
            app = subprocess.Popen([str(binary)], env=env, stdout=app_log.open("w"),
                                   stderr=subprocess.STDOUT, start_new_session=True)
            wait_until("native app D-Bus ownership", lambda: subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus", "--method",
                 "org.freedesktop.DBus.NameHasOwner", APP_ID], capture_output=True,
                text=True, timeout=3).stdout.strip() == "(true,)")
            gaction("settings")
            wait_until("native Settings window", lambda: atspi_probe(
                python, "title", app.pid, "CodexBar Settings").get("found"))
            capture_screen(screenshooter, env, scratch / "capture-settings",
                           artifact_dir / "settings.png")
            evidence["screenshots"]["settings"] = str(artifact_dir / "settings.png")

            toggled = atspi_probe(python, "activate", app.pid, SETTING_LABEL)
            wait_until("isolated Settings preference persistence", lambda:
                       json.loads(prefs.read_text(encoding="utf-8")).get(SETTING_KEY) is True)
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                "control": SETTING_LABEL, "checked_before": toggled["before_checked"],
                "checked_after": toggled["after_checked"], "persisted": True})

            gaction("dashboard")
            dashboard = wait_until("Dashboard route", lambda: atspi_probe(
                python, "title", app.pid, "CodexBar GTK — Dashboard").get("match"))
            capture_screen(screenshooter, env, scratch / "capture-dashboard",
                           artifact_dir / "dashboard.png")
            evidence["actions"].append({"kind": "GAction", "name": "app.dashboard",
                                        "observed_window": dashboard})
            evidence["screenshots"]["dashboard"] = str(artifact_dir / "dashboard.png")

            gaction("page", "'spend'")
            spend_title = wait_until("Spend route", lambda: atspi_probe(
                python, "title", app.pid, "Usage & Spend").get("match"))
            gaction("spend-range", "'7 days'")
            selected = wait_until("Spend 7-day range selection", lambda:
                next((row for row in atspi_probe(python, "checked", app.pid, SPEND_LABEL)["matches"]
                      if row["checked"]), None))
            capture_screen(screenshooter, env, scratch / "capture-spend",
                           artifact_dir / "spend-7-days.png")
            evidence["actions"].append({"kind": "GAction", "name": "app.page('spend')",
                                        "observed_window": spend_title})
            evidence["actions"].append({"kind": "GAction", "name": "app.spend-range('7 days')",
                                        "selected_accessible_control": selected["name"],
                                        "role": selected["role"], "checked": selected["checked"]})
            evidence["screenshots"]["spend_7_days"] = str(artifact_dir / "spend-7-days.png")
            evidence["limits"] = [
                "AT-SPI and GAction evidence is not physical pointer/keyboard input.",
                "Private Weston capture does not establish KDE shell placement, portal input, or host compositor parity.",
            ]
        finally:
            if app is not None and app.poll() is None:
                try:
                    gaction("quit")
                except Exception:
                    app.terminate()
                try:
                    app.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    app.kill()
                    app.wait(timeout=3)
            if compositor.poll() is None:
                compositor.send_signal(signal.SIGTERM)
                try:
                    compositor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=3)
        process_cleanup = {
            "app_exited": app is None or app.poll() is not None,
            "compositor_exited": compositor.poll() is not None,
        }
    evidence["cleanup"] = {
        **process_cleanup,
        "private_runtime_removed": not runtime.exists(),
        "synthetic_home_removed": not home.exists(),
    }
    if not all(evidence["cleanup"].values()):
        raise RuntimeError(f"isolated runner cleanup did not complete: {evidence['cleanup']}")
    evidence_path = artifact_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    evidence_path.chmod(0o600)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, help="built codexbar-gtk-native executable")
    parser.add_argument("--artifact-dir", default=None,
                        help="directory for synthetic screenshots/evidence (default: /tmp temp directory)")
    parser.add_argument("--inside-private-bus", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.artifact_dir is None:
        args.artifact_dir = tempfile.mkdtemp(prefix="codexbar-native-wayland-evidence-")
    if not args.inside_private_bus:
        command = ["dbus-run-session", "--", sys.executable, __file__,
                   "--inside-private-bus", "--binary", args.binary,
                   "--artifact-dir", args.artifact_dir]
        result = subprocess.run(command, env=os.environ.copy(), timeout=240)
        return result.returncode
    try:
        evidence = inside_run(args)
    except Exception as exc:
        print(f"isolated native Wayland smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
