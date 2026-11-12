#!/usr/bin/env python3
"""Run a bounded native GTK Wayland action smoke in a private Weston session.

This harness exercises app GActions and one AT-SPI action. Those are observable
GTK actions, not physical Wayland pointer/key input or KDE shell parity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

APP_ID = "com.steipete.CodexBarGTK"
SETTING_KEY = "refreshAllProvidersOnMenuOpen"
SETTING_LABEL = "Refresh when the panel opens"
SPEND_LABEL = "7 days"
SPEND_RANGES = ("7 days", "30 days", "90 days", "All")
HEATMAP_MODES = ("Daily", "Weekly", "Cumulative")
NOTIFICATION_CONTROLS = (
    "Session quota notifications",
    "Quota warning notifications",
    "Limit reset notifications",
    "Pace warnings",
)
HOST_SESSION_KEYS = (
    "DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SYSTEM_BUS_ADDRESS",
    "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE",
    "AT_SPI_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_SESSION_ID",
    "XDG_CURRENT_DESKTOP", "XDG_DESKTOP_PORTAL_DIR", "KDE_FULL_SESSION", "KDE_SESSION_VERSION",
    "SESSION_MANAGER", "DESKTOP_STARTUP_ID", "GIO_LAUNCHED_DESKTOP_FILE",
    "GIO_LAUNCHED_DESKTOP_FILE_PID",
    "NO_AT_BRIDGE",
)
HOST_HANDLE_PARTS = re.compile(r"DISPLAY|WAYLAND|XAUTHORITY|DBUS|AT_SPI|"
                              r"XDG_SESSION|XDG_RUNTIME|XDG_DESKTOP_PORTAL|PORTAL_BUS|"
                              r"KDE_|SESSION_MANAGER|DESKTOP_STARTUP_ID|"
                              r"GIO_LAUNCHED_DESKTOP_FILE")
AT_SPI_PROBE = r'''
import json, sys, time
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

mode, pid_text, expected = sys.argv[1:]
pid = int(pid_text)
Atspi.init()
desktop = Atspi.get_desktop(0)
nodes = []
apps = []
app_details = []
tree_errors = []
for index in range(min(desktop.get_child_count(), 100)):
    try:
        app = desktop.get_child_at_index(index)
        app_name = app.get_name() or ""
        app_pid = int(app.get_process_id())
        apps.append({"name": app_name, "pid": app_pid})
        if app_pid != pid:
            continue
        detail = {"name": app_name, "pid": app_pid}
        try:
            detail["role"] = app.get_role_name()
            detail["child_count"] = app.get_child_count()
            detail["children"] = []
            for child_index in range(min(detail["child_count"], 50)):
                child = app.get_child_at_index(child_index)
                detail["children"].append({"name": child.get_name(),
                                            "role": child.get_role_name()})
        except Exception as error:
            detail["tree_error"] = f"{type(error).__name__}: {error}"
            tree_errors.append(detail["tree_error"])
        app_details.append(detail)
        queue = [(app, 0, f"app[{index}]")]
        while queue and len(nodes) < 3000:
            node, depth, path = queue.pop(0)
            if depth > 30:
                continue
            try:
                name = node.get_name() or ""
                role = node.get_role_name() or ""
                nodes.append((node, name, role, path))
                for child_index in range(min(node.get_child_count(), 200)):
                    child = node.get_child_at_index(child_index)
                    if child is not None:
                        queue.append((child, depth + 1, f"{path}/{role}[{child_index}]:{name}"))
            except Exception as error:
                tree_errors.append(f"{type(error).__name__}: {error}")
    except Exception:
        pass

if mode == "title":
    frames = [name for _, name, role, _ in nodes if role in ("frame", "window")]
    matching = [name for name in frames if expected in name]
    print(json.dumps({"found": bool(matching), "titles": frames,
                      "matching_apps": [app for app in apps if app["pid"] == pid],
                      "app_details": app_details, "tree_errors": tree_errors[-20:],
                      "visible_apps": apps[:60],
                      "match": matching[0] if matching else None}))
elif mode in ("states", "snapshot"):
    matches = []
    for node, name, role, path in nodes:
        if expected in name:
            state_set = None
            try:
                state_set = node.get_state_set()
                states = sorted(state.value_nick for state in state_set.get_states())
                checked = state_set.contains(Atspi.StateType.CHECKED)
            except Exception:
                states = []
                checked = False
            entry = {"name": name, "role": role, "checked": bool(checked),
                     "states": states, "path": path,
                     "identity": f"{pid}:{path}:{role}:{name}",
                     "pid": int(node.get_process_id())}
            if mode == "snapshot":
                action_iface = node.get_action_iface()
                entry["action_count"] = action_iface.get_n_actions() if action_iface else 0
                try:
                    entry["showing"] = state_set.contains(Atspi.StateType.SHOWING)
                    entry["visible"] = state_set.contains(Atspi.StateType.VISIBLE)
                    entry["enabled"] = state_set.contains(Atspi.StateType.ENABLED)
                    entry["selected"] = state_set.contains(Atspi.StateType.SELECTED)
                    entry["pressed"] = state_set.contains(Atspi.StateType.PRESSED)
                except Exception:
                    pass
            matches.append(entry)
    print(json.dumps({"found": bool(matches), "matches": matches,
                      "app_details": app_details, "tree_errors": tree_errors[-20:]}))
elif mode == "activate":
    matches = [(node, role, path) for node, name, role, path in nodes
               if name == expected and role in ("check box", "switch", "toggle button",
                                                "button", "push button", "page tab", "tab")]
    if len(matches) != 1:
        print(json.dumps({"ok": False, "reason": "expected exactly one named toggle", "count": len(matches)}))
        raise SystemExit(3)
    node, role, path = matches[0]
    actions = node.get_action_iface()
    if actions is None or actions.get_n_actions() < 1:
        print(json.dumps({"ok": False, "reason": "toggle exposes no AT-SPI action", "role": role}))
        raise SystemExit(4)
    state = node.get_state_set()
    before_checked = state.contains(Atspi.StateType.CHECKED)
    before_pressed = state.contains(Atspi.StateType.PRESSED)
    before = before_checked if role in ("check box", "switch") else before_pressed
    toggling_role = role in ("check box", "switch", "toggle button")
    ok = actions.do_action(0)
    deadline = time.monotonic() + 5
    after = before
    after_checked = before_checked
    after_pressed = before_pressed
    while toggling_role and time.monotonic() < deadline:
        try:
            state = node.get_state_set()
            after_checked = state.contains(Atspi.StateType.CHECKED)
            after_pressed = state.contains(Atspi.StateType.PRESSED)
            after = after_checked if role in ("check box", "switch") else after_pressed
        except Exception:
            after = False
        if after != before:
            break
        time.sleep(0.05)
    print(json.dumps({"ok": bool(ok and (after != before if toggling_role else True)), "role": role,
                      "pid": pid, "path": path,
                      "identity": f"{pid}:{path}:{role}:{expected}",
                      "action": actions.get_action_name(0),
                      "before_checked": bool(before_checked),
                      "after_checked": bool(after_checked) if role != "toggle button" else None,
                      "before_pressed": bool(before_pressed),
                      "after_pressed": bool(after) if role == "toggle button" else None,
                      "changed": bool(after != before), "action_succeeded": bool(ok)}))
    raise SystemExit(0 if ok and (after != before if toggling_role else True) else 6)
else:
    raise SystemExit("unknown AT-SPI probe mode")
'''


def sanitized_environment(source: dict[str, str], home: pathlib.Path,
                          runtime: pathlib.Path, wayland_display: str,
                          fake_cli: pathlib.Path,
                          private_bus_address: str) -> dict[str, str]:
    """Return a private client environment with host display/session handles removed."""
    env = dict(source)
    for key in tuple(env):
        if HOST_HANDLE_PARTS.search(key):
            env.pop(key, None)
    for key in (
        "DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SYSTEM_BUS_ADDRESS",
        "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE",
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
        "GTK_A11Y": "atspi",
        "GTK_USE_PORTAL": "0",
        "CODEXBAR_CLI": str(fake_cli),
        "NATIVE_CLI_LOG": str(home / "cli-calls.log"),
        "NATIVE_HOOKS_STATE_FILE": str(home / "hooks-enabled"),
    })
    return env


def private_bus_environment(source: dict[str, str]) -> dict[str, str]:
    """Drop inherited display/session handles before creating the private bus."""
    env = dict(source)
    for key in tuple(env):
        if HOST_HANDLE_PARTS.search(key):
            env.pop(key, None)
    return env


def _write_failure_evidence(artifact_dir: pathlib.Path, message: str,
                            error_type: str, details: dict | None = None) -> None:
    """Leave a small synthetic-only failure record for local and CI diagnosis."""
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = artifact_dir / "failure-evidence.json"
        path.write_text(json.dumps({"status": "failed", "error_type": error_type,
                                    "message": message[:2000],
                                    "details": details or {}}, indent=2) + "\n",
                        encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


def _write_failure_log(artifact_dir: pathlib.Path, name: str, content: str) -> None:
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = artifact_dir / name
        path.write_text(content[-12_000:], encoding="utf-8", errors="replace")
        path.chmod(0o600)
    except OSError:
        pass


def stop_owned_process_group(process: subprocess.Popen, grace: float = 2.0) -> None:
    """Stop only the process group created for this private runner and reap it."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # The wrapper may have exited while one of its descendants ignored TERM.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def run_owned_process_group(command: list[str], *, env: dict[str, str],
                            timeout: float, stdout, stderr) -> subprocess.CompletedProcess:
    """Run a private wrapper and clean its entire inherited process group on failure."""
    process = subprocess.Popen(command, env=env, stdout=stdout, stderr=stderr,
                               start_new_session=True)
    try:
        return_code = process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        stop_owned_process_group(process)
        raise
    if return_code != 0:
        # On failures, dbus-run-session may have left descendants behind.
        stop_owned_process_group(process)
    return subprocess.CompletedProcess(command, return_code)


def _symlink_if_missing(path: pathlib.Path, target: pathlib.Path) -> None:
    if not path.exists() and target.exists():
        path.symlink_to(os.path.relpath(target, path.parent))


def resolve_weston(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path,
                                                pathlib.Path, pathlib.Path, pathlib.Path]:
    """Find system Weston, or rootlessly extract the apt Weston/Pixman package pair."""
    weston = shutil.which("weston")
    screenshooter = shutil.which("weston-screenshooter")
    if weston and screenshooter:
        candidates = [pathlib.Path("/usr/lib/x86_64-linux-gnu"),
                      pathlib.Path("/usr/lib/aarch64-linux-gnu"),
                      pathlib.Path("/usr/lib")]
        for libdir in candidates:
            backend = next(libdir.glob("libweston-*/headless-backend.so"), None)
            shell = libdir / "weston/desktop-shell.so"
            desktop_client = pathlib.Path("/usr/libexec/weston-desktop-shell")
            keyboard_client = pathlib.Path("/usr/libexec/weston-keyboard")
            if backend and shell.is_file() and desktop_client.is_file() and keyboard_client.is_file():
                return (pathlib.Path(weston), pathlib.Path(screenshooter), backend,
                        shell, desktop_client, keyboard_client)

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
    shell = libdir / "weston/desktop-shell.so"
    desktop_client = extracted / "usr/libexec/weston-desktop-shell"
    keyboard_client = extracted / "usr/libexec/weston-keyboard"
    weston = extracted / "usr/bin/weston"
    screenshooter = extracted / "usr/bin/weston-screenshooter"
    for path in (weston, screenshooter, backend, shell, desktop_client, keyboard_client):
        if not path.is_file():
            raise RuntimeError(f"rootless Weston extraction is incomplete: {path}")
    return weston, screenshooter, backend, shell, desktop_client, keyboard_client


def fake_cli_text() -> str:
    return r'''#!/bin/sh
printf '%s\n' "$*" >> "$NATIVE_CLI_LOG"
case "${1:-}" in
  --version) printf 'CodexBar synthetic fixture 0.82.0\n' ;;
  usage) printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":42,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300}}}]' ;;
  cost) printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{"priced":3,"unpriced":1},"provenance":"synthetic_history","daily":[{"date":"2026-11-09","totalCost":3.25,"totalTokens":800},{"date":"2026-11-08","totalCost":0,"totalTokens":0}],"projects":[],"models":[]}]' ;;
  sessions)
    mode=success
    if [ -n "${NATIVE_SESSIONS_MODE_FILE:-}" ] && [ -f "$NATIVE_SESSIONS_MODE_FILE" ]; then
      mode=$(cat "$NATIVE_SESSIONS_MODE_FILE")
    fi
    case "$mode" in
      loading) printf '%s\n' "sessions-fixture-$mode-start" >> "$NATIVE_CLI_LOG"; sleep 2; printf '%s\n' "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '%s\n' '[{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":10,"host":"fixture"}]' ;;
      success) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '%s\n' '[{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":10,"host":"fixture"}]' ;;
      empty) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '[]\n' ;;
      error) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf 'synthetic session scan failure\n' >&2; exit 7 ;;
      *) printf 'unsupported synthetic sessions mode\n' >&2; exit 8 ;;
    esac ;;
  hooks)
    case "${2:-}" in
      enable) printf 'true\n' > "$NATIVE_HOOKS_STATE_FILE" ;;
      disable) printf 'false\n' > "$NATIVE_HOOKS_STATE_FILE" ;;
      list)
        enabled=true
        if [ -f "$NATIVE_HOOKS_STATE_FILE" ]; then
          enabled=$(cat "$NATIVE_HOOKS_STATE_FILE")
        fi
        printf '{"enabled":%s,"events":[]}\n' "$enabled"
        ;;
      *) printf 'unsupported synthetic hooks command\n' >&2; exit 8 ;;
    esac
    ;;
  plugins|providers|config|auth) printf '[]\n' ;;
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


def activate_accessible(python: str, pid: int, name: str) -> dict:
    result = atspi_probe(python, "activate", pid, name)
    if not result.get("ok"):
        raise RuntimeError(f"AT-SPI action failed closed for {name!r}: {result}")
    return result


def selected_accessible(python: str, pid: int, name: str, role: str) -> dict:
    snapshot = atspi_probe(python, "states", pid, name)
    matches = [row for row in snapshot.get("matches", [])
               if row.get("name") == name and row.get("role") == role
               and ("pressed" in row.get("states", [])
                    or "checked" in row.get("states", []))]
    if len(matches) != 1:
        raise RuntimeError(f"expected one selected {role} named {name!r}, found {matches!r}")
    return matches[0]


def selected_range_control(python: str, pid: int, expected: str) -> dict | None:
    candidates = []
    for label in SPEND_RANGES:
        rows = [row for row in atspi_probe(python, "states", pid, label).get("matches", [])
                if label in row.get("name", "") and row.get("role") == "toggle button"
                and row.get("pid") == pid]
        unique = {row["identity"]: row for row in rows}
        if len(unique) != 1:
            raise RuntimeError(f"Spend range {label!r} is not a unique AT-SPI node: {sorted(unique)}")
        candidates.extend(unique.values())
    pressed = [row for row in candidates if "pressed" in row.get("states", [])]
    if len(pressed) != 1:
        raise RuntimeError(f"expected one pressed Spend range control, observed {pressed!r}")
    selected = pressed[0]
    return selected if expected in selected["name"] else None


def wait_visible_control(python: str, pid: int, name: str, timeout: float = 12.0) -> dict:
    def visible_unique_node():
        rows = [row for row in atspi_probe(python, "snapshot", pid, name).get("matches", [])
                if row.get("name") == name and row.get("pid") == pid
                and row.get("showing") and row.get("visible")]
        identities = {row["identity"]: row for row in rows}
        if len(identities) > 1:
            raise RuntimeError(f"ambiguous visible AT-SPI control {name!r}: {sorted(identities)}")
        return next(iter(identities.values()), None)
    return wait_until(f"visible AT-SPI control {name!r}", visible_unique_node, timeout=timeout)


def wait_visible_text(python: str, pid: int, text: str, timeout: float = 12.0) -> dict:
    def visible_unique_node():
        rows = [row for row in atspi_probe(python, "snapshot", pid, text).get("matches", [])
                if text in row.get("name", "") and row.get("pid") == pid
                and row.get("showing") and row.get("visible")]
        identities = {row["identity"]: row for row in rows}
        if len(identities) > 1:
            raise RuntimeError(f"ambiguous visible AT-SPI text {text!r}: {sorted(identities)}")
        return next(iter(identities.values()), None)
    return wait_until(f"visible AT-SPI text {text!r}", visible_unique_node, timeout=timeout)


def selected_heatmap_mode(python: str, pid: int) -> dict:
    rows = []
    for mode in HEATMAP_MODES:
        matches = [row for row in atspi_probe(python, "states", pid, mode).get("matches", [])
                   if row.get("name") == mode and row.get("role") == "toggle button"
                   and row.get("pid") == pid]
        identities = {row["identity"]: row for row in matches}
        if len(identities) != 1:
            raise RuntimeError(f"heatmap control {mode!r} is not a unique node: {sorted(identities)}")
        rows.extend(identities.values())
    pressed = [row for row in rows if "pressed" in row.get("states", [])]
    if len(pressed) != 1:
        raise RuntimeError(f"expected exactly one pressed heatmap mode, observed {pressed!r}")
    return pressed[0]


def gdk_wayland_display(python: str, env: dict[str, str]) -> dict:
    probe = (
        "import json, gi; gi.require_version('Gdk','4.0'); "
        "gi.require_version('Gtk','4.0'); from gi.repository import Gdk,Gtk; "
        "Gtk.init(); d=Gdk.Display.get_default(); "
        "print(json.dumps({'gtype': d.__gtype__.name if d else None, "
        "'name': d.get_name() if d else None}))"
    )
    result = subprocess.run([python, "-c", probe], env=env,
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f"GDK display probe failed: {result.stderr.strip()}")
    display = json.loads(result.stdout)
    if "Wayland" not in str(display.get("gtype")):
        raise RuntimeError(f"GDK did not create a Wayland display: {display!r}")
    return display


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
        seeded_settings = {SETTING_KEY: False, "showTray": False}
        seeded_settings.update({key: False for key in (
            "sessionQuotaNotificationsEnabled", "quotaWarningNotificationsEnabled",
            "limitResetNotificationsEnabled", "predictivePaceNotificationsEnabled")})
        prefs.write_text(json.dumps(seeded_settings) + "\n", encoding="utf-8")
        sessions_mode_file = home / "sessions-mode"
        sessions_mode_file.write_text("success\n", encoding="utf-8")
        hooks_state_file = home / "hooks-enabled"
        hooks_state_file.write_text("true\n", encoding="utf-8")

        (weston, screenshooter, backend, shell,
         desktop_client, keyboard_client) = resolve_weston(scratch)
        libdir = backend.parent.parent
        private_bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not private_bus_address:
            raise RuntimeError("runner must be started inside its private dbus-run-session")
        env = sanitized_environment(os.environ, home, runtime, "wayland-private", cli,
                                    private_bus_address)
        env["NATIVE_SESSIONS_MODE_FILE"] = str(sessions_mode_file)
        env.update({
            "LD_LIBRARY_PATH": str(libdir) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""),
            "WESTON_DATA_DIR": str(weston.parent.parent / "share/weston"),
            "WESTON_MODULE_MAP": f"headless-backend.so={backend};desktop-shell.so={shell}",
        })
        # All helper processes, including gapplication and AT-SPI probes, inherit
        # the private bus and private Wayland socket rather than host handles.
        os.environ.clear()
        os.environ.update(env)
        weston_log = artifact_dir / "weston.log"
        weston_log.touch(mode=0o600)
        weston_log.chmod(0o600)
        weston_config = scratch / "weston.ini"
        weston_config.write_text(
            "[shell]\n"
            f"client={desktop_client}\n"
            "[input-method]\n"
            f"path={keyboard_client}\n",
            encoding="utf-8",
        )
        weston_config.chmod(0o600)
        compositor = subprocess.Popen(
            [str(weston), "--backend=headless", "--renderer=pixman",
             "--socket=wayland-private", "--width=1280", "--height=900",
             "--shell=desktop-shell.so", f"--config={weston_config}",
             "--idle-time=0", "--debug",
             f"--log={weston_log}"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        app = None
        evidence = {"compositor": "rootless Weston headless Pixman",
                    "backend": "Wayland", "GDK_BACKEND": "wayland",
                    "GSK_RENDERER": "cairo", "screenshots": {}, "actions": []}
        try:
            wait_until("private Weston socket", lambda: (runtime / "wayland-private").is_socket()
                       if (runtime / "wayland-private").exists() else False)
            private_socket = runtime / "wayland-private"
            private_socket.chmod(0o600)
            if (runtime.stat().st_mode & 0o777) != 0o700:
                raise RuntimeError("private Wayland runtime directory is not mode 700")
            if (private_socket.stat().st_mode & 0o777) != 0o600:
                raise RuntimeError("private Wayland socket is not mode 600")
            subprocess.run(["wayland-info"], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, check=True, timeout=10)
            evidence["source_commit"] = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True, text=True, check=True, timeout=5).stdout.strip()
            digest = hashlib.sha256()
            with binary.open("rb") as binary_file:
                for chunk in iter(lambda: binary_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            evidence["binary_sha256"] = digest.hexdigest()
            evidence["gdk_display"] = gdk_wayland_display(python, env)
            evidence["private_runtime_permissions"] = oct(runtime.stat().st_mode & 0o777)
            evidence["private_wayland_socket"] = str(private_socket)
            evidence["private_wayland_socket_permissions"] = oct(
                private_socket.stat().st_mode & 0o777)
            evidence["private_dbus"] = {
                "started_by": "dbus-run-session",
                "address": os.environ["DBUS_SESSION_BUS_ADDRESS"].split(",guid=", 1)[0],
            }
            private_handles = {
                "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
                "DBUS_SESSION_BUS_ADDRESS",
            }
            evidence["host_session_handles_removed"] = (
                all(key not in env for key in env if HOST_HANDLE_PARTS.search(key)
                    and key not in private_handles)
                and env.get("XDG_RUNTIME_DIR") == str(runtime)
                and env.get("WAYLAND_DISPLAY") == "wayland-private"
                and env.get("DBUS_SESSION_BUS_ADDRESS") == os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            )
            # Enable an isolated AT-SPI bus and make a private fixture preference
            # observable through the real native Settings control.
            app_log = artifact_dir / "native-app.log"
            app_log.touch(mode=0o600)
            app_log.chmod(0o600)
            app = subprocess.Popen([str(binary)], env=env, stdout=app_log.open("w"),
                                   stderr=subprocess.STDOUT)
            wait_until("native app D-Bus ownership", lambda: subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus", "--method",
                 "org.freedesktop.DBus.NameHasOwner", APP_ID], capture_output=True,
                text=True, timeout=3).stdout.strip() == "(true,)")
            gaction("dashboard")
            last_dashboard_probe = {}
            def dashboard_window_found():
                snapshot = atspi_probe(python, "title", app.pid, "CodexBar GTK — Dashboard")
                last_dashboard_probe["snapshot"] = snapshot
                return snapshot.get("match")
            dashboard = wait_until("Dashboard visible route", dashboard_window_found)
            dashboard_content = wait_until("Dashboard accessible content", lambda: [row for row in
                atspi_probe(python, "snapshot", app.pid, "Codex").get("matches", [])
                if row.get("role") not in ("frame", "window") and row.get("pid") == app.pid
                and row.get("showing") and row.get("visible")])
            capture_screen(screenshooter, env, scratch / "capture-dashboard-initial",
                           artifact_dir / "dashboard-initial.png")
            evidence["screenshots"]["dashboard_initial"] = str(artifact_dir / "dashboard-initial.png")
            evidence["actions"].append({"kind": "GAction", "name": "app.dashboard",
                                        "observed_window": dashboard,
                                        "visible_content_nodes": len(dashboard_content)})
            evidence["actions"].append({"kind": "native command-line route",
                                        "route": "default dashboard"})
            gaction("settings")
            last_settings_probe = {}
            def settings_window_found():
                snapshot = atspi_probe(python, "title", app.pid, "CodexBar Settings")
                last_settings_probe["snapshot"] = snapshot
                return snapshot if snapshot.get("found") else None
            try:
                settings_window = wait_until("native Settings window", settings_window_found)
            except RuntimeError as error:
                diagnostics = {
                    "app_alive": app.poll() is None,
                    "app_return_code": app.poll(),
                    "atspi": last_settings_probe.get("snapshot"),
                    "app_log_tail": app_log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:],
                    "weston_log_tail": weston_log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:],
                }
                diagnostics_path = artifact_dir / "failure-diagnostics.json"
                diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8")
                diagnostics_path.chmod(0o600)
                raise RuntimeError(
                    f"{error}; app_alive={app.poll() is None}; "
                    f"AT-SPI={last_settings_probe.get('snapshot')}; diagnostics={diagnostics_path}"
                ) from error
            evidence["actions"].append({"kind": "GAction", "name": "app.settings",
                                        "observed_window": settings_window["match"]})
            wait_visible_control(python, app.pid, SETTING_LABEL)
            capture_screen(screenshooter, env, scratch / "capture-settings",
                           artifact_dir / "settings.png")
            evidence["screenshots"]["settings"] = str(artifact_dir / "settings.png")

            before_settings = json.loads(prefs.read_text(encoding="utf-8"))
            toggled = activate_accessible(python, app.pid, SETTING_LABEL)
            wait_until("isolated Settings preference persistence", lambda:
                       json.loads(prefs.read_text(encoding="utf-8")).get(SETTING_KEY) is True)
            evidence["persisted_settings_json"] = json.loads(prefs.read_text(encoding="utf-8"))
            capture_screen(screenshooter, env, scratch / "capture-settings-after-toggle",
                           artifact_dir / "settings-after-toggle.png")
            evidence["screenshots"]["settings_after_toggle"] = str(
                artifact_dir / "settings-after-toggle.png")
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                "control": SETTING_LABEL, "checked_before": toggled["before_checked"],
                "checked_after": toggled["after_checked"], "persisted": True,
                "identity": toggled["identity"],
                "settings_diff": {key: [before_settings.get(key), evidence["persisted_settings_json"].get(key)]
                                  for key in evidence["persisted_settings_json"]
                                  if before_settings.get(key) != evidence["persisted_settings_json"].get(key)}})

            setting_actions = []
            notification_before = json.loads(prefs.read_text(encoding="utf-8"))
            activate_accessible(python, app.pid, "Notifications")
            for label, key in zip(NOTIFICATION_CONTROLS, (
                "sessionQuotaNotificationsEnabled", "quotaWarningNotificationsEnabled",
                "limitResetNotificationsEnabled", "predictivePaceNotificationsEnabled")):
                wait_visible_control(python, app.pid, label)
                state_before = atspi_probe(python, "states", app.pid, label)
                exact = [row for row in state_before.get("matches", []) if row["name"] == label
                         and row["role"] in ("switch", "check box")]
                if len(exact) != 1 or exact[0]["checked"]:
                    raise RuntimeError(f"{label} did not have one unchecked fixture control: {exact!r}")
                result = activate_accessible(python, app.pid, label)
                if not result["before_checked"] or result["after_checked"]:
                    raise RuntimeError(f"{label} did not visibly change to checked: {result!r}")
                wait_until(f"{key} preference persistence", lambda key=key:
                    json.loads(prefs.read_text(encoding="utf-8")).get(key) is True)
                after = json.loads(prefs.read_text(encoding="utf-8"))
                expected_settings = dict(notification_before)
                expected_settings[key] = True
                if after != expected_settings:
                    raise RuntimeError(f"{key} did not produce the exact full preference map")
                notification_before = after
                setting_actions.append({"control": label, "key": key,
                                        "checked_before": result["before_checked"],
                                        "checked_after": result["after_checked"],
                                        "identity": result["identity"],
                                        "full_settings_map_checked": True})
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                        "page": "Notifications", "controls": setting_actions})

            activate_accessible(python, app.pid, "Menu Bar")
            wait_visible_control(python, app.pid, "Show the tray icon")
            menu_before = json.loads(prefs.read_text(encoding="utf-8"))
            show_tray = activate_accessible(python, app.pid, "Show the tray icon")
            if not show_tray["before_checked"] or not show_tray["after_checked"]:
                raise RuntimeError(f"showTray did not visibly change to checked: {show_tray!r}")
            wait_until("showTray preference persistence", lambda:
                json.loads(prefs.read_text(encoding="utf-8")).get("showTray") is True)
            menu_after = json.loads(prefs.read_text(encoding="utf-8"))
            expected_menu = dict(menu_before)
            expected_menu["showTray"] = True
            if menu_after != expected_menu:
                raise RuntimeError("showTray did not produce the exact full preference map")
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                        "page": "Menu Bar", "control": "Show the tray icon",
                                        "key": "showTray", "checked_before": show_tray["before_checked"],
                                        "checked_after": show_tray["after_checked"],
                                        "identity": show_tray["identity"],
                                        "full_settings_map_checked": True})

            activate_accessible(python, app.pid, "Hooks")
            wait_visible_control(python, app.pid, "Enable hooks")
            hook_before_calls = (home / "cli-calls.log").read_text(encoding="utf-8").splitlines() \
                if (home / "cli-calls.log").exists() else []
            hook_result = activate_accessible(python, app.pid, "Enable hooks")
            if not hook_result["before_checked"] or hook_result["after_checked"]:
                raise RuntimeError(f"Hooks switch did not visibly change to disabled: {hook_result!r}")
            def hooks_disabled_call_observed():
                calls = ((home / "cli-calls.log").read_text(encoding="utf-8").splitlines()
                         if (home / "cli-calls.log").exists() else [])
                return calls if calls.count("hooks disable") > hook_before_calls.count("hooks disable") else None
            hook_calls = wait_until("synthetic hooks disable CLI call", hooks_disabled_call_observed)
            if hook_calls.count("hooks disable") - hook_before_calls.count("hooks disable") != 1:
                raise RuntimeError("Hooks action did not make exactly one disable CLI call")
            hook_cli_state = subprocess.run(
                [str(cli), "hooks", "list", "--format", "json"], env=env,
                capture_output=True, text=True, timeout=10, check=True)
            if json.loads(hook_cli_state.stdout) != {"enabled": False, "events": []}:
                raise RuntimeError(f"Hooks CLI postcondition was not disabled: {hook_cli_state.stdout!r}")
            hook_state = atspi_probe(python, "states", app.pid, "Enable hooks")
            hook_toggle = [row for row in hook_state.get("matches", [])
                           if row["name"] == "Enable hooks" and row["role"] == "switch"]
            if len(hook_toggle) != 1 or hook_toggle[0]["checked"]:
                raise RuntimeError(f"Hooks switch result was not visibly disabled: {hook_toggle!r}")
            if json.loads(prefs.read_text(encoding="utf-8")) != menu_after:
                raise RuntimeError("Hooks toggle unexpectedly changed preferences")
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                        "page": "Hooks", "control": "Enable hooks",
                                        "checked_before": hook_result["before_checked"],
                                        "checked_after": hook_result["after_checked"],
                                        "identity": hook_result["identity"],
                                        "cli_calls": [line for line in hook_calls if line == "hooks disable"],
                                        "cli_postcondition": json.loads(hook_cli_state.stdout),
                                        "preferences_unchanged": True})

            gaction("dashboard")
            dashboard = wait_until("Dashboard route after Settings", lambda: atspi_probe(
                python, "title", app.pid, "CodexBar GTK — Dashboard").get("match"))
            wait_until("Dashboard content after Settings", lambda: atspi_probe(
                python, "snapshot", app.pid, "Codex").get("matches"))
            capture_screen(screenshooter, env, scratch / "capture-dashboard",
                           artifact_dir / "dashboard.png")
            evidence["actions"].append({"kind": "GAction", "name": "app.dashboard",
                                        "observed_window": dashboard})
            evidence["screenshots"]["dashboard"] = str(artifact_dir / "dashboard.png")

            gaction("page", "'spend'")
            spend_title = wait_until("Spend route", lambda: atspi_probe(
                python, "title", app.pid, "Usage & Spend").get("match"))
            evidence["actions"].append({"kind": "GAction", "name": "app.page('spend')",
                                        "observed_window": spend_title})
            range_results = []
            for label in SPEND_RANGES:
                gaction("spend-range", f"'{label}'")
                selected = wait_until(f"Spend {label} range selection", lambda label=label:
                    selected_range_control(python, app.pid, label))
                visible_range = wait_visible_control(python, app.pid, selected["name"])
                if visible_range["identity"] != selected["identity"]:
                    raise RuntimeError(f"Spend {label} selected node was not the visible node")
                range_results.append({"value": label, "selected_control": selected["name"],
                                      "role": selected["role"], "states": selected["states"],
                                      "identity": selected["identity"], "pid": selected["pid"],
                                      "selected_by_pressed_state": True})
                if label == "7 days":
                    capture_screen(screenshooter, env, scratch / "capture-spend",
                                   artifact_dir / "spend-7-days.png")
                    evidence["screenshots"]["spend_7_days"] = str(artifact_dir / "spend-7-days.png")
            evidence["actions"].append({"kind": "GAction", "name": "app.spend-range",
                                        "selections": range_results})
            mode_results = []
            for mode in HEATMAP_MODES:
                visible_mode = wait_visible_control(python, app.pid, mode)
                before = atspi_probe(python, "states", app.pid, mode)
                before_rows = [row for row in before.get("matches", [])
                               if row["name"] == mode and row["role"] == "toggle button"]
                if len(before_rows) != 1:
                    raise RuntimeError(f"heatmap mode {mode!r} is not uniquely accessible: {before_rows!r}")
                already_selected = "pressed" in before_rows[0]["states"]
                result = ({"changed": False, "action_succeeded": None,
                           "already_selected": True} if already_selected else
                          activate_accessible(python, app.pid, mode))
                state = wait_until(f"heatmap {mode} pressed state", lambda mode=mode:
                    next((row for row in atspi_probe(python, "states", app.pid, mode)["matches"]
                          if row["name"] == mode and row["role"] == "toggle button"
                          and row.get("pid") == app.pid
                          and "pressed" in row["states"]), None))
                selected_mode = selected_heatmap_mode(python, app.pid)
                if selected_mode["name"] != mode or selected_mode["identity"] != visible_mode["identity"]:
                    raise RuntimeError(f"heatmap {mode!r} was not the unique visible pressed mode")
                mode_results.append({"mode": mode, "action_changed_state": result["changed"],
                                     "already_selected": already_selected,
                                     "role": state["role"], "states": state["states"],
                                     "identity": state["identity"], "pid": state["pid"]})
            evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                        "control_group": "Token activity heatmap",
                                        "modes": mode_results})

            gaction("page", "'sessions'")
            sessions_title = wait_until("Sessions route", lambda: atspi_probe(
                python, "title", app.pid, "Sessions").get("match"))
            sessions_statuses = []
            mode_cases = (
                ("loading", "Refreshing · showing the last successful result", 5.0),
                ("success", "1 running of 1 known sessions", 12.0),
                ("empty", "The last successful scan found no agent sessions.", 12.0),
                ("error", "Session scan failed · showing the last successful result", 12.0),
            )
            for mode, expected_text, timeout in mode_cases:
                temporary_mode_file = sessions_mode_file.with_suffix(".tmp")
                temporary_mode_file.write_text(mode + "\n", encoding="utf-8")
                temporary_mode_file.replace(sessions_mode_file)
                call_log = home / "cli-calls.log"
                sessions_calls_before = (call_log.read_text(encoding="utf-8").splitlines().count(
                    "sessions --json-v2") if call_log.exists() else 0)
                gaction("refresh")
                wait_until(f"synthetic sessions fixture {mode} started", lambda mode=mode:
                    f"sessions-fixture-{mode}-start" in call_log.read_text(encoding="utf-8").splitlines())
                visible = wait_visible_text(python, app.pid, expected_text, timeout=timeout)
                sessions_statuses.append({"fixture_mode": mode, "visible_status": visible["name"],
                                          "role": visible["role"], "pid": visible["pid"]})
                wait_until(f"synthetic sessions fixture {mode} completed", lambda mode=mode:
                    f"sessions-fixture-{mode}-done" in call_log.read_text(encoding="utf-8").splitlines())
                sessions_calls_after = call_log.read_text(encoding="utf-8").splitlines().count(
                    "sessions --json-v2")
                sessions_call_count = sessions_calls_after - sessions_calls_before
                if sessions_call_count != 1:
                    raise RuntimeError(
                        f"Sessions {mode} refresh made {sessions_call_count} CLI calls; expected exactly one")
                sessions_statuses[-1]["cli_call_count"] = sessions_call_count
                if mode == "error":
                    error_text = wait_visible_text(
                        python, app.pid, "Existing rows remain available")
                    sessions_statuses[-1]["visible_error"] = error_text["name"]
                if mode == "loading":
                    capture_screen(screenshooter, env, scratch / "capture-sessions-loading",
                                   artifact_dir / "sessions-loading.png")
                    evidence["screenshots"]["sessions_loading"] = str(artifact_dir / "sessions-loading.png")
            evidence["actions"].append({"kind": "GAction and synthetic CLI",
                                        "name": "app.page('sessions')",
                                        "observed_window": sessions_title,
                                        "states": sessions_statuses})
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
        private_env = private_bus_environment(os.environ)
        command = ["dbus-run-session", "--", sys.executable, __file__,
                   "--inside-private-bus", "--binary", args.binary,
                   "--artifact-dir", args.artifact_dir]
        with tempfile.TemporaryFile(mode="w+b") as private_stderr:
            try:
                result = run_owned_process_group(
                    command, env=private_env, stdout=subprocess.DEVNULL,
                    stderr=private_stderr, timeout=240)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                private_stderr.seek(0, os.SEEK_END)
                size = private_stderr.tell()
                private_stderr.seek(max(0, size - 12_000))
                stderr_tail = private_stderr.read().decode("utf-8", errors="replace")
                _write_failure_evidence(pathlib.Path(args.artifact_dir),
                                        "outer runner timeout or interrupt",
                                        type(error).__name__,
                                        {"stderr_tail": stderr_tail[-12_000:]})
                raise
            private_stderr.seek(0, os.SEEK_END)
            size = private_stderr.tell()
            private_stderr.seek(max(0, size - 12_000))
            stderr_tail = private_stderr.read().decode("utf-8", errors="replace")
        if result.returncode:
            _write_failure_log(pathlib.Path(args.artifact_dir), "wrapper-stderr.log",
                               stderr_tail)
            print(f"isolated native Wayland run failed (exit {result.returncode}); "
                  f"artifacts: {pathlib.Path(args.artifact_dir).resolve()}", file=sys.stderr)
            if stderr_tail:
                print("\n".join(stderr_tail.splitlines()[-80:]), file=sys.stderr)
            return result.returncode
        try:
            evidence_path = pathlib.Path(args.artifact_dir).resolve() / "evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            address = evidence["private_dbus"]["address"]
            socket_removed = False
            if address.startswith("unix:path="):
                bus_socket = pathlib.Path(address.removeprefix("unix:path=").split(",", 1)[0])
                socket_removed = not bus_socket.exists()
            evidence["cleanup"]["private_dbus_socket_removed"] = socket_removed
            evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            evidence_path.chmod(0o600)
            if not all(evidence["cleanup"].values()):
                print(f"isolated private Wayland/D-Bus cleanup did not complete: {evidence['cleanup']}",
                      file=sys.stderr)
                return 1
            print(json.dumps(evidence, indent=2))
            return 0
        except (KeyError, json.JSONDecodeError, OSError) as error:
            print(f"could not verify private D-Bus cleanup: {error}", file=sys.stderr)
            return 1
    try:
        evidence = inside_run(args)
    except Exception as exc:
        _write_failure_evidence(pathlib.Path(args.artifact_dir), str(exc),
                                type(exc).__name__)
        print(f"isolated native Wayland smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
