#!/usr/bin/env python3
"""Run a bounded native GTK Wayland action smoke in a private Weston session.

This harness exercises app GActions and AT-SPI actions/selections. Those are
observable GTK operations, not physical Wayland input or KDE shell parity.
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
RESIDUAL_SETTINGS = (
    ("Display", "Show used instead of remaining", "usageBarsShowUsed", True, "switch"),
    ("Display", "Project usage at reset", "quotaBurndownEnabled", False, "switch"),
    ("Usage & Spend", "Enable local cost scans", "costUsageEnabled", False, "switch"),
    ("Display", "Reset time format", "resetTimesOption", "absolute", "combo"),
    ("Display", "Workday ticks", "workdayTickAppearance", "highContrast", "combo"),
    ("Menu Bar", "Icon style", "menuBarIconStyle", "iconPercent", "combo"),
    ("Menu Bar", "Icon shows", "unifiedIconSource", "first", "combo"),
    ("Menu Bar", "Provider rows", "switcherRowsOption", "details", "combo"),
    ("Usage & Spend", "Statistics time zone", "costUsageBucketTimeZone", "Africa/Abidjan", "combo"),
)
RESIDUAL_OPTION_LABELS = {
    ("resetTimesOption", "absolute"): "Absolute time",
    ("workdayTickAppearance", "highContrast"): "High contrast",
    ("menuBarIconStyle", "iconPercent"): "Icon and percentage",
    ("unifiedIconSource", "first"): "First enabled provider",
    ("switcherRowsOption", "details"): "Quota details",
}
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

args = sys.argv[1:]
mode, pid_text, expected = args[:3]
expected_identity = args[3] if len(args) > 3 else None
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
        while queue and len(nodes) < 10000:
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
            try:
                node_pid = int(node.get_process_id())
            except Exception:
                continue
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
                     "pid": node_pid}
            if mode == "snapshot":
                try:
                    action_iface = node.get_action_iface()
                    entry["action_count"] = action_iface.get_n_actions() if action_iface else 0
                    selection_iface = node.get_selection_iface()
                    entry["selection_available"] = selection_iface is not None
                    entry["child_count"] = node.get_child_count()
                    entry["selected_child_count"] = (
                        selection_iface.get_n_selected_children() if selection_iface else 0)
                    entry["showing"] = state_set.contains(Atspi.StateType.SHOWING)
                    entry["visible"] = state_set.contains(Atspi.StateType.VISIBLE)
                    entry["enabled"] = state_set.contains(Atspi.StateType.ENABLED)
                    entry["selected"] = state_set.contains(Atspi.StateType.SELECTED)
                    entry["pressed"] = state_set.contains(Atspi.StateType.PRESSED)
                    # A ComboRow's accessible combobox may not itself implement
                    # Action or Selection while its child button/popup does.
                    # Keep this same-process subtree traversal shallow and bounded.
                    def describe(child, child_path, depth):
                        if depth > 8:
                            return []
                        try:
                            child_name = child.get_name() or ""
                            child_role = child.get_role_name() or ""
                            child_states = child.get_state_set()
                            child_actions = child.get_action_iface()
                            child_selection = child.get_selection_iface()
                            child_count = min(child.get_child_count(), 40)
                            action_names = []
                            if child_actions:
                                for action_index in range(min(child_actions.get_n_actions(), 12)):
                                    action_names.append(child_actions.get_action_name(action_index))
                            relations = []
                            try:
                                for relation in child.get_relation_set()[:12]:
                                    relation_targets = []
                                    for target_index in range(min(relation.get_n_targets(), 12)):
                                        target = relation.get_target(target_index)
                                        relation_targets.append({"name": target.get_name() or "",
                                                                 "role": target.get_role_name() or ""})
                                    relations.append({"type": relation.get_relation_type().value_nick,
                                                      "targets": relation_targets})
                            except Exception as relation_error:
                                relations = [{"error": f"{type(relation_error).__name__}: {relation_error}"}]
                            result = {"name": child_name, "role": child_role,
                                      "path": child_path,
                                      "identity": f"{pid}:{child_path}:{child_role}:{child_name}",
                                      "pid": int(child.get_process_id()),
                                      "states": sorted(s.value_nick for s in child_states.get_states()),
                                      "action_names": action_names,
                                      "selection_available": child_selection is not None,
                                      "child_count": child_count,
                                      "relations": relations}
                            if depth < 8:
                                descendants = []
                                for nested_index in range(child_count):
                                    nested = child.get_child_at_index(nested_index)
                                    if nested is not None:
                                        descendants.extend(describe(
                                            nested, f"{child_path}/{child_role}[{nested_index}]:{child_name}", depth + 1))
                                if descendants:
                                    result["children"] = descendants
                            return [result]
                        except Exception as child_error:
                            return [{"path": child_path,
                                     "error": f"{type(child_error).__name__}: {child_error}"}]
                    entry["subtree"] = []
                    for child_index in range(min(node.get_child_count(), 40)):
                        child = node.get_child_at_index(child_index)
                        if child is not None:
                            entry["subtree"].extend(describe(
                                child, f"{path}/{role}[{child_index}]:{name}", 1))
                except Exception:
                    entry["action_count"] = 0
            matches.append(entry)
    print(json.dumps({"found": bool(matches), "matches": matches,
                      "app_details": app_details, "tree_errors": tree_errors[-20:]}))
elif mode == "tree":
    rows = []
    for node, name, role, path in nodes:
        try:
            node_pid = int(node.get_process_id())
            state_set = node.get_state_set()
            states = sorted(state.value_nick for state in state_set.get_states())
            action_iface = node.get_action_iface()
            action_count = action_iface.get_n_actions() if action_iface else 0
        except Exception:
            node_pid, states, action_count = pid, [], 0
        rows.append({"name": name, "role": role, "path": path,
                     "pid": node_pid, "states": states,
                     "action_count": action_count})
    print(json.dumps({"rows": rows[:800], "app_details": app_details,
                      "tree_errors": tree_errors[-20:]}))
elif mode == "activate":
    matches = [(node, role, path) for node, name, role, path in nodes
               if name == expected and role in ("check box", "switch", "toggle button",
                                                "button", "push button", "page tab", "tab",
                                                "combo box")
               and (expected_identity is None
                    or f"{pid}:{path}:{role}:{name}" == expected_identity)]
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
elif mode == "select-child":
    expected_identity = args[3]
    expected_option = args[4]
    matches = [(node, path) for node, name, role, path in nodes
               if name == expected and role == "combo box"
               and f"{pid}:{path}:{role}:{name}" == expected_identity]
    if len(matches) != 1:
        print(json.dumps({"ok": False, "reason": "expected one exact combo box",
                          "count": len(matches)}))
        raise SystemExit(3)
    combo, path = matches[0]
    state = combo.get_state_set()
    selection = combo.get_selection_iface()
    if (int(combo.get_process_id()) != pid
            or not state.contains(Atspi.StateType.SHOWING)
            or not state.contains(Atspi.StateType.VISIBLE)
            or selection is None):
        print(json.dumps({"ok": False, "reason": "combo is not a visible same-PID Selection control",
                          "pid": int(combo.get_process_id()),
                          "selection_available": selection is not None,
                          "states": sorted(s.value_nick for s in state.get_states())}))
        raise SystemExit(4)
    children = []
    for index in range(min(combo.get_child_count(), 1000)):
        child = combo.get_child_at_index(index)
        children.append((index, child, child.get_name() or "", child.get_role_name() or ""))
    candidates = [(index, child, role) for index, child, name, role in children
                  if name == expected_option]
    if len(candidates) != 1:
        print(json.dumps({"ok": False, "reason": "expected one exact option child",
                          "count": len(candidates),
                          "child_names": [{"name": name, "role": role}
                                          for _, _, name, role in children[:80]]}))
        raise SystemExit(5)
    index, child, option_role = candidates[0]
    before = bool(selection.is_child_selected(index))
    ok = bool(before or selection.select_child(index))
    deadline = time.monotonic() + 5
    after = False
    while ok and time.monotonic() < deadline:
        after = bool(selection.is_child_selected(index))
        if after:
            break
        time.sleep(0.05)
    print(json.dumps({"ok": bool(ok and after), "pid": pid,
                      "combo_identity": expected_identity, "option": expected_option,
                      "option_role": option_role, "option_index": index,
                      "already_selected": before, "selected_after": after,
                      "action": "Atspi.Selection.select_child"}))
    raise SystemExit(0 if ok and after else 6)
elif mode == "select-visible-option":
    expected_option = args[3]
    candidates = []
    for node, name, role, path in nodes:
        if name != expected_option:
            continue
        try:
            node_pid = int(node.get_process_id())
            states = node.get_state_set()
            if node_pid != pid or not (states.contains(Atspi.StateType.VISIBLE)
                                       and states.contains(Atspi.StateType.SHOWING)
                                       and states.contains(Atspi.StateType.SENSITIVE)):
                continue
            candidates.append((node, role, path, states))
        except Exception:
            continue
    selected = []
    for node, role, path, states in candidates:
        # The parent address is encoded by the child's accessible path. Find
        # the unique same-PID Selection container whose child list owns it.
        for parent, _, parent_role, parent_path in nodes:
            try:
                selection = parent.get_selection_iface()
                if selection is None or not path.startswith(parent_path + "/"):
                    continue
                child_index = next((i for i in range(min(parent.get_child_count(), 1000))
                                    if parent.get_child_at_index(i) == node), None)
                if child_index is not None:
                    selected.append((node, role, path, parent, parent_role, parent_path,
                                     child_index, selection, states))
            except Exception:
                continue
    if len(selected) != 1:
        print(json.dumps({"ok": False, "reason": "expected one visible option in a same-PID Selection container",
                          "visible_option_nodes": [{"role": role, "path": path}
                                                   for _, role, path, _ in candidates],
                          "selection_candidates": [{"role": row[4], "path": row[5],
                                                     "index": row[6]} for row in selected]}))
        raise SystemExit(4)
    node, role, path, parent, parent_role, parent_path, child_index, selection, states = selected[0]
    before = bool(selection.is_child_selected(child_index))
    ok = bool(before or selection.select_child(child_index))
    deadline = time.monotonic() + 3
    after = False
    while ok and time.monotonic() < deadline:
        after = bool(selection.is_child_selected(child_index))
        if after:
            break
        time.sleep(0.05)
    print(json.dumps({"ok": bool(ok and after), "pid": pid, "option": expected_option,
                      "option_role": role, "option_identity": f"{pid}:{path}:{role}:{expected_option}",
                      "option_states": sorted(s.value_nick for s in states.get_states()),
                      "selection_container_role": parent_role,
                      "selection_container_path": parent_path,
                      "selection_child_index": child_index,
                      "selection_before": before, "selection_after": after,
                      "action": "Atspi.Selection.select_child"}))
    raise SystemExit(0 if ok and after else 5)
else:
    raise SystemExit("unknown AT-SPI probe mode")
'''


def sanitized_environment(source: dict[str, str], home: pathlib.Path,
                          runtime: pathlib.Path, wayland_display: str,
                          fake_cli: pathlib.Path,
                          private_bus_address: str,
                          diagnostic_dir: pathlib.Path) -> dict[str, str]:
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
        "NATIVE_CHOOSER_DIAGNOSTIC_DIR": str(diagnostic_dir),
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
      loading) printf '%s\n' "sessions-fixture-$mode-start" >> "$NATIVE_CLI_LOG"; sleep 15; printf '%s\n' "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '%s\n' '[{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":10,"host":"fixture"}]' ;;
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


def atspi_probe(python: str, mode: str, pid: int, expected: str,
                *extra_args: str) -> dict:
    command = [python, "-c", AT_SPI_PROBE, mode, str(pid), expected]
    command.extend(extra_args)
    result = subprocess.run(command,
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


def activate_accessible(python: str, pid: int, name: str,
                        expected_identity: str | None = None) -> dict:
    result = atspi_probe(python, "activate", pid, name, expected_identity)
    if not result.get("ok"):
        raise RuntimeError(f"AT-SPI action failed closed for {name!r}: {result}")
    return result


def select_combo_option(python: str, pid: int, row: dict, option: str) -> dict:
    """Select the exact visible same-PID child through AT-SPI Selection."""
    result = atspi_probe(python, "select-child", pid, row["name"], row["identity"], option)
    if not result.get("ok") or result.get("pid") != pid:
        raise RuntimeError(f"AT-SPI combo selection failed closed for {option!r}: {result}")
    result["combo_identity"] = row["identity"]
    return result


def select_open_popup_option(python: str, pid: int, option_label: str,
                             control_name: str) -> tuple[dict, dict]:
    try:
        visible = wait_until(
            f"visible same-PID {option_label!r} popup option",
            lambda: next((row for row in atspi_probe(
                python, "snapshot", pid, option_label).get("matches", [])
                if row.get("name") == option_label and row.get("pid") == pid
                and row.get("showing") and row.get("visible")), None),
            timeout=3)
    except RuntimeError as error:
        option_nodes = atspi_probe(python, "snapshot", pid, option_label).get("matches", [])
        control_nodes = atspi_probe(python, "snapshot", pid, control_name).get("matches", [])
        control_nodes = [row for row in control_nodes if row.get("role") == "combo box"]
        tree = atspi_probe(python, "tree", pid, "")
        visible_rows = [row for row in tree.get("rows", []) if row.get("pid") == pid
                        and {"showing", "visible"}.issubset(set(row.get("states", [])))]
        relevant = [row for row in visible_rows
                    if row.get("name") in {option_label, "Reset time format", "Countdown",
                                            "Absolute time", "Both"}
                    or row.get("role") in ("menu", "menu item", "list", "list item", "combo box")]
        failure = RuntimeError(f"{error}; named option nodes={option_nodes!r}; "
                               f"opened control subtrees={control_nodes[:3]!r}; "
                               f"relevant visible same-PID tree={relevant[:80]!r}")
        raise failure from error
    selection = atspi_probe(python, "select-visible-option", pid, option_label)
    if not selection.get("ok") or selection.get("pid") != pid:
        raise RuntimeError(f"visible popup option selection failed for {option_label!r}: {selection}")
    return visible, selection


def combo_activation_child(row: dict) -> dict | None:
    candidates = []
    pending = list(row.get("subtree", []))
    while pending:
        child = pending.pop(0)
        pending.extend(child.get("children", []))
        states = set(child.get("states", []))
        if (child.get("role") in ("button", "push button", "toggle button")
                and child.get("pid") == row.get("pid")
                and states.intersection({"showing"}) and states.intersection({"visible"})
                and "sensitive" in states and child.get("action_names")):
            candidates.append(child)
    if len(candidates) > 1:
        raise RuntimeError(f"ambiguous same-PID combo popup trigger: {candidates!r}")
    return candidates[0] if candidates else None


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


def wait_visible_control(python: str, pid: int, name: str,
                         expected_roles: tuple[str, ...],
                         expected_context: str,
                         timeout: float = 12.0,
                         allow_selection: bool = False) -> dict:
    last_candidates = []
    def visible_unique_node():
        snapshot = atspi_probe(python, "snapshot", pid, name)
        named_rows = [row for row in snapshot.get("matches", [])
                if row.get("name") == name and row.get("pid") == pid
                and row.get("role") in expected_roles]
        for row in named_rows:
            if row.get("role") == "combo box" and row.get("action_count", 0) == 0 \
                    and not row.get("selection_available"):
                row["activation_child"] = combo_activation_child(row)
        last_candidates[:] = [{key: row.get(key) for key in
                               ("identity", "path", "role", "showing", "visible", "action_count",
                                "selection_available", "activation_child")}
                              for row in named_rows[:8]]
        rows = [row for row in named_rows
                if f":{expected_context}/panel[" in row.get("path", "")
                and row.get("showing") and row.get("visible")
                and (row.get("action_count", 0) > 0
                     or (allow_selection and (row.get("selection_available")
                                              or row.get("activation_child"))))]
        visible_candidates = [row for row in named_rows
                              if f":{expected_context}/panel[" in row.get("path", "")
                              and row.get("showing") and row.get("visible")]
        unsupported_combos = [row for row in visible_candidates
                              if row.get("role") == "combo box"
                              and row.get("action_count", 0) == 0
                              and not row.get("selection_available")
                              and not row.get("activation_child")]
        if allow_selection and unsupported_combos:
            error = RuntimeError("visible GTK combo exposes neither AT-SPI AccessibleAction "
                                 "nor Selection interface")
            error.contract_details = [
                {key: row.get(key) for key in
                 ("name", "pid", "identity", "path", "role", "action_count",
                  "selection_available", "activation_child", "subtree")}
                for row in unsupported_combos]
            raise error
        identities = {row["identity"]: row for row in rows}
        if len(identities) > 1:
            raise RuntimeError(f"ambiguous visible actionable AT-SPI control {name!r}: "
                               f"{sorted(identities)}")
        return next(iter(identities.values()), None)
    try:
        return wait_until(f"visible AT-SPI control {name!r}", visible_unique_node,
                          timeout=timeout)
    except RuntimeError as error:
        if hasattr(error, "contract_details"):
            raise
        raise RuntimeError(f"{error}; same-PID named candidates={last_candidates!r}") from error


def wait_visible_action(python: str, pid: int, name: str,
                        roles: tuple[str, ...], timeout: float = 8.0,
                        context: str | None = None) -> dict:
    """Find one visible, same-process actionable node by exact accessible name."""
    last = []
    def locate():
        snapshot = atspi_probe(python, "snapshot", pid, name)
        matches = [row for row in snapshot.get("matches", [])
                   if row.get("name") == name and row.get("pid") == pid
                   and row.get("role") in roles and row.get("showing")
                   and row.get("visible") and "sensitive" in row.get("states", [])
                   and row.get("action_count", 0) > 0
                   and (context is None or f":{context}/" in row.get("path", ""))]
        last[:] = matches
        unique = {row["identity"]: row for row in matches}
        if len(unique) > 1:
            raise RuntimeError(f"ambiguous visible action {name!r}: {sorted(unique)}")
        return next(iter(unique.values()), None)
    try:
        return wait_until(f"visible action {name!r}", locate, timeout=timeout)
    except RuntimeError as error:
        tree = atspi_probe(python, "tree", pid, "")
        rows = [row for row in tree.get("rows", []) if row.get("pid") == pid]
        raise RuntimeError(f"{error}; candidates={last!r}; same_pid_atspi_tree={rows!r}; "
                           f"tree_errors={tree.get('tree_errors')!r}") from error


def chooser_helper(python: str, mode: str, pid: int, title: str, path: pathlib.Path) -> str:
    helper = pathlib.Path(__file__).with_name("select-native-file-chooser.py")
    result = subprocess.run([python, str(helper), mode, str(pid), title, str(path)],
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f"chooser helper {mode} failed: {result.stderr.strip()} {result.stdout.strip()}")
    return result.stdout.strip()


def wait_visible_text(python: str, pid: int, text: str, timeout: float = 12.0,
                      context: str | None = None) -> dict:
    def visible_unique_node():
        rows = [row for row in atspi_probe(python, "snapshot", pid, text).get("matches", [])
                if text in row.get("name", "") and row.get("pid") == pid
                and row.get("showing") and row.get("visible")
                and (context is None or f":{context}/" in row.get("path", ""))]
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


def run_advanced_preferences(python: str, pid: int, prefs: pathlib.Path,
                             autostart: pathlib.Path, home: pathlib.Path,
                             cli_log: pathlib.Path, evidence: dict,
                             screenshooter: pathlib.Path, env: dict[str, str],
                             scratch: pathlib.Path, artifact_dir: pathlib.Path) -> None:
    """Exercise portable preferences and reset through live native GTK actions."""
    gaction("settings")
    settings_window = wait_until("native Settings window", lambda: atspi_probe(
        python, "title", pid, "CodexBar Settings").get("match"))
    evidence["actions"].append({"kind": "GAction", "name": "app.settings",
                                "observed_window": settings_window})
    try:
        page = wait_visible_action(python, pid, "Advanced", ("page tab", "tab", "button"))
    except RuntimeError:
        diagnostic = atspi_probe(python, "tree", pid, "")
        tree_path = artifact_dir / "advanced-atspi-tree.json"
        tree_path.write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")
        tree_path.chmod(0o600)
        raise RuntimeError(f"Advanced control unavailable; same-PID accessibility tree saved to {tree_path}")
    activated = activate_accessible(python, pid, "Advanced", page["identity"])
    selected = wait_until("Advanced page selected state", lambda: next((row for row in
        atspi_probe(python, "states", pid, "Advanced").get("matches", [])
        if row.get("name") == "Advanced" and row.get("role") == "page tab"
        and row.get("pid") == pid and "selected" in row.get("states", [])), None))
    evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                "control": "Advanced", "identity": activated["identity"],
                                "selected_state": selected["states"]})

    def click(name: str, context: str | None = "Advanced") -> dict:
        node = wait_visible_action(python, pid, name,
                                   ("button", "push button", "toggle button"),
                                   context=context)
        result = activate_accessible(python, pid, name, node["identity"])
        return {"name": name, "identity": result["identity"],
                "action": result["action"], "action_succeeded": result["action_succeeded"]}

    def dialog_closed(title: str) -> bool:
        snapshot = atspi_probe(python, "snapshot", pid, title)
        return not any(row.get("name") == title and row.get("role") == "dialog"
                       and row.get("pid") == pid and row.get("showing")
                       for row in snapshot.get("matches", []))

    def dialog_visible(title: str) -> dict | None:
        snapshot = atspi_probe(python, "snapshot", pid, title)
        rows = [row for row in snapshot.get("matches", [])
                if row.get("name") == title and row.get("role") == "dialog"
                and row.get("pid") == pid and row.get("showing") and row.get("visible")]
        if len(rows) > 1:
            raise RuntimeError(f"ambiguous app-owned visible dialog {title!r}: {rows!r}")
        return rows[0] if rows else None

    def file_call_count(prefix: str) -> int:
        if not cli_log.exists():
            return 0
        return sum(line.split(" ", 1)[0] == prefix
                   for line in cli_log.read_text(encoding="utf-8").splitlines())

    # Save chooser starts in the synthetic HOME with its real default filename.
    exported = home / "preferences-export.json"
    export_action = click("Export…")
    wait_until("app-owned Export chooser", lambda: dialog_visible("Export preferences"))
    capture_screen(screenshooter, env, scratch / "capture-advanced-export-chooser",
                   artifact_dir / "advanced-export-chooser.png")
    save_result = chooser_helper(python, "save", pid, "Export preferences", exported)
    wait_until("Export chooser closure", lambda: dialog_closed("Export preferences"))
    exported_document = json.loads(exported.read_text(encoding="utf-8"))
    if exported_document.get("version") != 1 or not isinstance(
            exported_document.get("preferences"), dict):
        raise RuntimeError(f"native Save produced invalid portable JSON: {exported_document!r}")
    if exported_document["preferences"].get("refreshFrequency") != "5m":
        raise RuntimeError("portable export did not contain the seeded selected preference")
    export_status = wait_visible_text(python, pid, "Preferences exported.", context="Advanced")
    evidence["portable_export"] = exported_document
    evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                "control": export_action, "chooser": save_result,
                                "dialog_closed": True, "valid_portable_json": True,
                                "visible_result": export_status["name"]})
    capture_screen(screenshooter, env, scratch / "capture-advanced-export",
                   artifact_dir / "advanced-export.png")
    evidence["screenshots"]["advanced_export"] = str(artifact_dir / "advanced-export.png")

    imported = home / "synthetic-preferences-import.json"
    before = json.loads(prefs.read_text(encoding="utf-8"))
    autostart_bytes = autostart.read_bytes()
    plugins_before = file_call_count("plugins")
    import_action = click("Import…")
    wait_until("app-owned Import chooser", lambda: dialog_visible("Import preferences"))
    capture_screen(screenshooter, env, scratch / "capture-advanced-import-chooser",
                   artifact_dir / "advanced-import-chooser.png")
    evidence["screenshots"]["advanced_import_chooser"] = str(
        artifact_dir / "advanced-import-chooser.png")
    try:
        row_selection = chooser_helper(python, "select", pid, "Import preferences", imported)
    except RuntimeError:
        capture_screen(screenshooter, env, scratch / "capture-advanced-import-selection-failure",
                       artifact_dir / "advanced-import-selection-failure.png")
        raise
    capture_screen(screenshooter, env, scratch / "capture-advanced-import-selected",
                   artifact_dir / "advanced-import-selected.png")
    evidence["screenshots"]["advanced_import_selected"] = str(
        artifact_dir / "advanced-import-selected.png")
    import_accept = chooser_helper(python, "accept", pid, "Import preferences", imported)
    wait_until("Import chooser closure", lambda: dialog_closed("Import preferences"))
    expected = rust_default_preferences()
    expected.update(before)
    expected.update({"refreshFrequency": "2m", "preferredCurrencyCode": "EUR"})
    try:
        wait_until("imported preference overlay", lambda:
                   json.loads(prefs.read_text(encoding="utf-8")) == expected)
    except RuntimeError as error:
        actual = json.loads(prefs.read_text(encoding="utf-8"))
        actual_path = artifact_dir / "valid-import-actual-preferences.json"
        actual_path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        actual_path.chmod(0o600)
        fixture_path = artifact_dir / "valid-import-fixture.json"
        shutil.copyfile(imported, fixture_path)
        fixture_path.chmod(0o600)
        raise RuntimeError(f"{error}; actual_full_preferences={actual!r}; "
                           f"fixture={fixture_path}") from error
    if autostart.read_bytes() != autostart_bytes:
        raise RuntimeError("valid import changed synthetic autostart bytes")
    if "futureSyntheticPreference" in json.loads(prefs.read_text(encoding="utf-8")):
        raise RuntimeError("valid import persisted an unknown imported key")
    wait_until("Plugins fresh query after valid import",
               lambda: file_call_count("plugins") > plugins_before)
    import_status = wait_visible_text(
        python, pid, "Settings loaded from the shared CodexBar services.", context="Advanced")
    capture_screen(screenshooter, env, scratch / "capture-advanced-import-result",
                   artifact_dir / "advanced-import-result.png")
    evidence["screenshots"]["advanced_import_result"] = str(
        artifact_dir / "advanced-import-result.png")
    evidence["valid_import_full_map"] = json.loads(prefs.read_text(encoding="utf-8"))
    evidence["actions"].append({"kind": "AT-SPI chooser actions",
        "control": import_action, "selected_row": row_selection,
        "accept_response": import_accept, "dialog_closed": True,
        "overlay_exact": True, "unknown_import_key_omitted": True,
        "autostart_bytes_unchanged": True,
        "visible_result": import_status["name"],
        "plugins_queries_before": plugins_before,
        "plugins_queries_after": file_call_count("plugins")})

    empty = home / "synthetic-empty-preferences-import.json"
    unchanged = json.loads(prefs.read_text(encoding="utf-8"))
    plugins_before_empty = file_call_count("plugins")
    empty_import_action = click("Import…")
    wait_until("second app-owned Import chooser", lambda: dialog_visible("Import preferences"))
    empty_row = chooser_helper(python, "select", pid, "Import preferences", empty)
    empty_accept = chooser_helper(python, "accept", pid, "Import preferences", empty)
    wait_until("empty Import chooser closure", lambda: dialog_closed("Import preferences"))
    wait_until("Plugins reload after empty import",
               lambda: file_call_count("plugins") > plugins_before_empty)
    empty_import_status = wait_visible_text(
        python, pid, "Settings loaded from the shared CodexBar services.", context="Advanced")
    capture_screen(screenshooter, env, scratch / "capture-advanced-empty-import-result",
                   artifact_dir / "advanced-empty-import-result.png")
    evidence["screenshots"]["advanced_empty_import_result"] = str(
        artifact_dir / "advanced-empty-import-result.png")
    if json.loads(prefs.read_text(encoding="utf-8")) != unchanged:
        raise RuntimeError("empty import changed the full preferences map")
    if autostart.read_bytes() != autostart_bytes:
        raise RuntimeError("empty import changed synthetic autostart bytes")
    evidence["actions"].append({"kind": "AT-SPI chooser actions",
        "control": empty_import_action, "selected_row": empty_row,
        "accept_response": empty_accept, "dialog_closed": True,
        "full_preferences_map_unchanged": True,
        "visible_result": empty_import_status["name"],
        "plugins_queries_before": plugins_before_empty,
        "plugins_queries_after": file_call_count("plugins")})

    reset = click("Reset…")
    reset_title = "Reset all preferences?"
    reset_dialog = wait_until("Reset confirmation dialog", lambda: dialog_visible(reset_title))
    capture_screen(screenshooter, env, scratch / "capture-reset-cancel-dialog",
                   artifact_dir / "advanced-reset-cancel-dialog.png")
    evidence["screenshots"]["reset_cancel_confirmation"] = str(
        artifact_dir / "advanced-reset-cancel-dialog.png")
    before_cancel = json.loads(prefs.read_text(encoding="utf-8"))
    cancel = wait_visible_action(python, pid, "Cancel", ("button", "push button"))
    cancel_result = activate_accessible(python, pid, "Cancel", cancel["identity"])
    wait_until("reset Cancel response and closure", lambda: dialog_closed(reset_title))
    if json.loads(prefs.read_text(encoding="utf-8")) != before_cancel:
        raise RuntimeError("Reset Cancel changed the complete preference map")
    if autostart.read_bytes() != autostart_bytes:
        raise RuntimeError("Reset Cancel changed synthetic autostart bytes")
    evidence["actions"].append({"kind": "AT-SPI MessageDialog response",
        "opened_by": reset, "dialog": reset_dialog, "response": "cancel",
        "identity": cancel_result["identity"], "dialog_closed": True,
        "full_preferences_map_unchanged": True})

    reset_again = click("Reset…")
    reset_dialog_confirm = wait_until("second Reset confirmation dialog",
                                      lambda: dialog_visible(reset_title))
    capture_screen(screenshooter, env, scratch / "capture-reset-confirm-dialog",
                   artifact_dir / "advanced-reset-confirm-dialog.png")
    evidence["screenshots"]["reset_confirm_confirmation"] = str(
        artifact_dir / "advanced-reset-confirm-dialog.png")
    confirm = wait_visible_action(python, pid, "Reset", ("button", "push button"))
    confirm_result = activate_accessible(python, pid, "Reset", confirm["identity"])
    wait_until("Reset confirmation closure", lambda: dialog_closed(reset_title))
    default_map = rust_default_preferences()
    wait_until("reset persisted Rust default preferences", lambda:
               json.loads(prefs.read_text(encoding="utf-8")) == default_map)
    reset_status = wait_visible_text(
        python, pid, "Settings loaded from the shared CodexBar services.", context="Advanced")
    if autostart.read_bytes() != autostart_bytes:
        raise RuntimeError("Reset Confirm changed synthetic autostart bytes")
    evidence["reset_default_map"] = default_map
    evidence["final_preferences_json"] = json.loads(prefs.read_text(encoding="utf-8"))
    evidence["actions"].append({"kind": "AT-SPI MessageDialog response",
        "opened_by": reset_again, "response": "reset",
        "dialog": reset_dialog_confirm,
        "identity": confirm_result["identity"], "dialog_closed": True,
        "full_default_map_checked": True, "autostart_bytes_unchanged": True,
        "visible_result": reset_status["name"]})
    capture_screen(screenshooter, env, scratch / "capture-advanced-reset",
                   artifact_dir / "advanced-reset.png")
    evidence["screenshots"]["advanced_reset"] = str(artifact_dir / "advanced-reset.png")
    evidence["synthetic_autostart"] = {"path_in_temporary_home": str(autostart),
                                         "sha256": hashlib.sha256(autostart_bytes).hexdigest(),
                                         "same_after_all_actions": True}
    evidence["limits"] = [
        "AT-SPI actions exercise accessible GTK controls and chooser responses, not physical Wayland input.",
        "Private Weston does not establish KDE shell, portal input, or host compositor parity.",
    ]


def run_residual_settings(python: str, pid: int, prefs: pathlib.Path,
                          evidence: dict, screenshooter: pathlib.Path,
                          env: dict[str, str], scratch: pathlib.Path,
                          artifact_dir: pathlib.Path) -> None:
    """Exercise still-open conventional Settings controls through visible AT-SPI nodes."""
    gaction("settings")
    title = wait_until("native Settings window", lambda: atspi_probe(
        python, "title", pid, "CodexBar Settings").get("match"))
    evidence["actions"].append({"kind": "GAction", "name": "app.settings",
                                "observed_window": title})
    results = []
    screenshots = {
        "Display": (scratch / "capture-settings-display",
                    artifact_dir / "settings-display.png"),
        "Menu Bar": (scratch / "capture-settings-menu-bar",
                     artifact_dir / "settings-menu-bar.png"),
        "Usage & Spend": (scratch / "capture-settings-usage-spend",
                          artifact_dir / "settings-usage-spend.png"),
    }
    captured = set()
    active_page = None
    before_map = json.loads(prefs.read_text(encoding="utf-8"))
    current_map = dict(before_map)

    def capture_page(page: str) -> None:
        capture_dir, output = screenshots[page]
        capture_screen(screenshooter, env, capture_dir, output)
        evidence["screenshots"][page.lower().replace(" & ", "-").replace(" ", "-")] = str(output)
        captured.add(page)

    def open_page(page: str) -> None:
        nonlocal active_page
        if active_page == page:
            return
        if active_page is not None and active_page not in captured:
            capture_page(active_page)
        tab = wait_visible_control(python, pid, page,
                                   ("page tab", "tab", "button"), "CodexBar Settings")
        activated = activate_accessible(python, pid, page, tab["identity"])
        selected = wait_until(f"{page} selected page state", lambda: next((row for row in
            atspi_probe(python, "states", pid, page).get("matches", [])
            if row.get("name") == page and row.get("pid") == pid
            and row.get("identity") == tab["identity"]
            and "selected" in row.get("states", [])), None))
        results.append({"kind": "AT-SPI page navigation", "page": page,
                        "identity": activated["identity"],
                        "selected_state": selected["states"]})
        active_page = page

    for page, label, key, value, kind in RESIDUAL_SETTINGS:
        option_label = RESIDUAL_OPTION_LABELS.get((key, value), value)
        open_page(page)
        expected_roles = (("check box", "switch") if kind == "switch" else
                          ("combo box", "button", "push button"))
        try:
            control = wait_visible_control(python, pid, label, expected_roles, page,
                                           allow_selection=(kind == "combo"))
        except RuntimeError as error:
            if kind != "combo":
                raise
            if page not in captured:
                capture_page(page)
            gap = getattr(error, "contract_details", [])
            completed = [{"page": item["page"], "control": item["control"],
                          "key": item["key"], "value": item["value"]}
                         for item in results if item.get("kind") == "AT-SPI preference action"]
            failure = RuntimeError(str(error))
            failure.details = {
                "scenario": "settings-residual",
                "accessibility_contract_gap": gap,
                "completed_settings_controls": completed,
                "persisted_settings_json": json.loads(prefs.read_text(encoding="utf-8")),
                "binary_sha256": evidence.get("binary_sha256"),
                "source_commit": evidence.get("source_commit"),
                "host_session_handles_removed": evidence.get("host_session_handles_removed"),
                "screenshots": evidence.get("screenshots", {}),
            }
            raise failure from error
        before_control = atspi_probe(python, "states", pid, label)
        same_control = [row for row in before_control.get("matches", [])
                        if row.get("identity") == control["identity"]
                        and row.get("pid") == pid]
        if len(same_control) != 1:
            raise RuntimeError(f"{label!r} lacks one exact same-PID visible control: {same_control!r}")
        if kind == "switch":
            desired_before = not value
            if same_control[0].get("checked") is not desired_before:
                raise RuntimeError(f"{label!r} fixture state is not {desired_before}: {same_control[0]!r}")
            action = activate_accessible(python, pid, label, control["identity"])
            if action.get("before_checked") is not desired_before or action.get("after_checked") is not value:
                raise RuntimeError(f"{label!r} did not visibly toggle to {value}: {action!r}")
        else:
            if control.get("selection_available"):
                selection = select_combo_option(python, pid, control, option_label)
                action = {"selection": selection}
            elif control.get("action_count", 0) > 0:
                opened = activate_accessible(python, pid, label, control["identity"])
                option_snapshot, selection = select_open_popup_option(python, pid,
                                                                      option_label, label)
                action = {"accessible_activation": opened,
                          "visible_popup_option": option_snapshot,
                          "selection": selection}
            elif control.get("activation_child"):
                child = control["activation_child"]
                opened = activate_accessible(python, pid, child["name"], child["identity"])
                option_snapshot, selection = select_open_popup_option(python, pid,
                                                                      option_label, label)
                action = {"accessible_child_activation": opened,
                          "visible_popup_option": option_snapshot,
                          "selection": selection}
            else:
                raise RuntimeError(f"combo {label!r} exposed no usable accessible UI operation")

        expected_map = dict(current_map)
        expected_map[key] = value
        wait_until(f"{key} exact isolated preference map", lambda expected_map=expected_map:
                   json.loads(prefs.read_text(encoding="utf-8")) == expected_map)
        current_map = expected_map
        results.append({"kind": "AT-SPI preference action", "page": page,
                        "control": label, "key": key, "value": value,
                        "control_identity": control["identity"], "control_role": control["role"],
                        "pid": pid, "action": action, "full_settings_map_checked": True})

    if active_page is not None and active_page not in captured:
        capture_page(active_page)
    final_map = json.loads(prefs.read_text(encoding="utf-8"))
    if final_map != current_map:
        raise RuntimeError("residual Settings batch final full preference map changed unexpectedly")
    evidence["actions"].extend(results)
    evidence["persisted_settings_json"] = final_map
    evidence["settings_diff"] = {key: [before_map.get(key), final_map.get(key)]
                                 for key in final_map if before_map.get(key) != final_map.get(key)}
    evidence["limits"] = [
        "AT-SPI AccessibleAction and visible selection evidence is not physical Wayland pointer/keyboard input.",
        "Private Weston does not establish KDE shell placement, portal input, or host compositor parity.",
    ]


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


def register_synthetic_recent_files(python: str, env: dict[str, str], home: pathlib.Path,
                                    paths: list[pathlib.Path]) -> list[str]:
    """Expose synthetic fixtures in the private GTK Recent list for accessible row selection."""
    script = (
        "import gi,sys; gi.require_version('Gtk','4.0'); "
        "from gi.repository import Gtk; Gtk.init(); "
        "manager=Gtk.RecentManager.get_default(); "
        "results=[manager.add_item(__import__('pathlib').Path(p).as_uri()) for p in sys.argv[1:]]; "
        "print('\\n'.join('1' if item else '0' for item in results)); "
        "raise SystemExit(0 if all(results) else 2)"
    )
    result = subprocess.run([python, "-c", script, *(str(path) for path in paths)],
                            env=env, cwd=home, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f"could not register private synthetic GTK Recent fixtures: "
                           f"{result.stderr.strip()} {result.stdout.strip()}")
    return result.stdout.splitlines()


def rust_default_preferences() -> dict:
    """Read the canonical Rust defaults as the exact reset/import baseline."""
    path = pathlib.Path(__file__).resolve().parents[1] / "rust-core/src/preferences.rs"
    source = path.read_text(encoding="utf-8")
    block = source.split("pub fn default_values()", 1)[1].split("json!({", 1)[1].split(
        "\n    });", 1)[0]
    block = block.rstrip().removesuffix(",")
    return json.loads("{" + block + "\n}")


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
        seeded_settings = ({"refreshFrequency": "5m", "preferredCurrencyCode": "USD",
                            "usageBarsShowUsed": False, "launchAtLogin": False,
                            "showTray": False}
                           if args.scenario == "advanced" else
                           ({**rust_default_preferences(),
                             "refreshFrequency": "5m", "preferredCurrencyCode": "USD",
                             "showTray": False, "usageBarsShowUsed": False,
                             "resetTimesOption": "countdown", "workdayTickAppearance": "subtle",
                             "quotaBurndownEnabled": True, "menuBarIconStyle": "meter",
                             "unifiedIconSource": "highest", "switcherRowsOption": "progress",
                             "costUsageEnabled": True, "costUsageBucketTimeZone": ""}
                            if args.scenario == "settings-residual" else
                           {SETTING_KEY: False, "showTray": False}))
        if args.scenario == "matrix":
            seeded_settings.update({key: False for key in (
                "sessionQuotaNotificationsEnabled", "quotaWarningNotificationsEnabled",
                "limitResetNotificationsEnabled", "predictivePaceNotificationsEnabled")})
        prefs.write_text(json.dumps(seeded_settings) + "\n", encoding="utf-8")
        autostart = None
        if args.scenario == "advanced":
            autostart = home / ".config/autostart/codexbar-gtk.desktop"
            autostart.parent.mkdir(parents=True, mode=0o700)
            autostart.write_bytes(b"[Desktop Entry]\nType=Application\nName=Synthetic marker\n")
            autostart.chmod(0o600)
        sessions_mode_file = home / "sessions-mode"
        sessions_mode_file.write_text("success\n", encoding="utf-8")
        hooks_state_file = home / "hooks-enabled"
        hooks_state_file.write_text("true\n", encoding="utf-8")
        imported_fixture = home / "synthetic-preferences-import.json"
        imported_fixture.write_text(json.dumps({"version": 1, "preferences": {
            "refreshFrequency": "2m", "preferredCurrencyCode": "EUR",
            "futureSyntheticPreference": "ignored"}}) + "\n", encoding="utf-8")
        imported_fixture.chmod(0o600)
        empty_import_fixture = home / "synthetic-empty-preferences-import.json"
        empty_import_fixture.write_text('{"version":1,"preferences":{}}\n', encoding="utf-8")
        empty_import_fixture.chmod(0o600)

        (weston, screenshooter, backend, shell,
         desktop_client, keyboard_client) = resolve_weston(scratch)
        libdir = backend.parent.parent
        private_bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not private_bus_address:
            raise RuntimeError("runner must be started inside its private dbus-run-session")
        env = sanitized_environment(os.environ, home, runtime, "wayland-private", cli,
                                    private_bus_address, artifact_dir / "chooser-diagnostics")
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
            if args.scenario == "advanced":
                recent_results = register_synthetic_recent_files(
                    python, env, home, [imported_fixture, empty_import_fixture])
                evidence["synthetic_recent_fixture_registration"] = {
                    "filenames": [path.name for path in (imported_fixture, empty_import_fixture)],
                    "private_gtk_recent_manager_added": recent_results,
                    "home_is_temporary": True}
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
            app = subprocess.Popen([str(binary)], env=env,
                                   cwd=home if args.scenario == "advanced" else None,
                                   stdout=app_log.open("w"),
                                   stderr=subprocess.STDOUT)
            wait_until("native app D-Bus ownership", lambda: subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus", "--method",
                 "org.freedesktop.DBus.NameHasOwner", APP_ID], capture_output=True,
                text=True, timeout=3).stdout.strip() == "(true,)")
            if args.scenario == "advanced":
                run_advanced_preferences(
                    python, app.pid, prefs, autostart, home, home / "cli-calls.log",
                    evidence, screenshooter, env, scratch, artifact_dir)
            elif args.scenario == "settings-residual":
                run_residual_settings(python, app.pid, prefs, evidence,
                                      screenshooter, env, scratch, artifact_dir)
            else:
                gaction("dashboard")
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
                setting_control = wait_visible_control(
                    python, app.pid, SETTING_LABEL, ("check box", "switch"), "General")
                capture_screen(screenshooter, env, scratch / "capture-settings",
                               artifact_dir / "settings.png")
                evidence["screenshots"]["settings"] = str(artifact_dir / "settings.png")

                before_settings = json.loads(prefs.read_text(encoding="utf-8"))
                toggled = activate_accessible(python, app.pid, SETTING_LABEL,
                                              setting_control["identity"])
                if toggled["before_checked"] or not toggled["after_checked"]:
                    raise RuntimeError(f"{SETTING_LABEL} did not change from unchecked to checked: {toggled!r}")
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
                notification_tab = wait_visible_control(
                    python, app.pid, "Notifications", ("page tab", "tab", "button"),
                    "CodexBar Settings")
                activate_accessible(python, app.pid, "Notifications", notification_tab["identity"])
                for label, key in zip(NOTIFICATION_CONTROLS, (
                    "sessionQuotaNotificationsEnabled", "quotaWarningNotificationsEnabled",
                    "limitResetNotificationsEnabled", "predictivePaceNotificationsEnabled")):
                    notification_control = wait_visible_control(
                        python, app.pid, label, ("check box", "switch"), "Notifications")
                    state_before = atspi_probe(python, "states", app.pid, label)
                    exact = [row for row in state_before.get("matches", []) if row["name"] == label
                             and row["role"] in ("switch", "check box")
                             and row["identity"] == notification_control["identity"]]
                    if len(exact) != 1 or exact[0]["checked"]:
                        raise RuntimeError(f"{label} did not have one unchecked fixture control: {exact!r}")
                    result = activate_accessible(python, app.pid, label,
                                                 notification_control["identity"])
                    if result["before_checked"] or not result["after_checked"]:
                        raise RuntimeError(f"{label} did not visibly change from unchecked to checked: {result!r}")
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

                menu_tab = wait_visible_control(
                    python, app.pid, "Menu Bar", ("page tab", "tab", "button"),
                    "CodexBar Settings")
                activate_accessible(python, app.pid, "Menu Bar", menu_tab["identity"])
                tray_control = wait_visible_control(
                    python, app.pid, "Show the tray icon", ("check box", "switch"), "Menu Bar")
                menu_before = json.loads(prefs.read_text(encoding="utf-8"))
                show_tray = activate_accessible(python, app.pid, "Show the tray icon",
                                                tray_control["identity"])
                if show_tray["before_checked"] or not show_tray["after_checked"]:
                    raise RuntimeError(f"showTray did not visibly change from unchecked to checked: {show_tray!r}")
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

                hooks_tab = wait_visible_control(
                    python, app.pid, "Hooks", ("page tab", "tab", "button"),
                    "CodexBar Settings")
                activate_accessible(python, app.pid, "Hooks", hooks_tab["identity"])
                hooks_control = wait_visible_control(
                    python, app.pid, "Enable hooks", ("check box", "switch"), "Hooks")
                hook_before_calls = (home / "cli-calls.log").read_text(encoding="utf-8").splitlines() \
                    if (home / "cli-calls.log").exists() else []
                hook_result = activate_accessible(python, app.pid, "Enable hooks",
                                                  hooks_control["identity"])
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
                               if row["name"] == "Enable hooks"
                               and row["role"] in ("switch", "check box")
                               and row["identity"] == hooks_control["identity"]]
                if len(hook_toggle) != 1 or hook_toggle[0]["checked"]:
                    raise RuntimeError(f"Hooks switch result was not visibly disabled: {hook_toggle!r}")
                if json.loads(prefs.read_text(encoding="utf-8")) != menu_after:
                    raise RuntimeError("Hooks toggle unexpectedly changed preferences")
                evidence["persisted_settings_json_after_settings_matrix"] = menu_after
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
                    visible_range = wait_visible_control(
                        python, app.pid, selected["name"], ("toggle button",),
                        "CodexBar GTK — Usage & Spend")
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
                    visible_mode = wait_visible_control(
                        python, app.pid, mode, ("toggle button",),
                        "CodexBar GTK — Usage & Spend")
                    before = atspi_probe(python, "states", app.pid, mode)
                    before_rows = [row for row in before.get("matches", [])
                                   if row["name"] == mode and row["role"] == "toggle button"]
                    if len(before_rows) != 1:
                        raise RuntimeError(f"heatmap mode {mode!r} is not uniquely accessible: {before_rows!r}")
                    already_selected = "pressed" in before_rows[0]["states"]
                    result = ({"changed": False, "action_succeeded": None,
                               "already_selected": True} if already_selected else
                              activate_accessible(python, app.pid, mode, visible_mode["identity"]))
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

                # Daily was initially selected when the page first opened. Return
                # to it after Weekly and Cumulative have both been selected so the
                # evidence proves the return action as well as the initial state.
                daily_control = wait_visible_control(
                    python, app.pid, "Daily", ("toggle button",),
                    "CodexBar GTK — Usage & Spend")
                daily_return = activate_accessible(
                    python, app.pid, "Daily", daily_control["identity"])
                if not daily_return["changed"]:
                    raise RuntimeError("final Daily return action did not change the selected heatmap mode")
                daily_state = wait_until("heatmap Daily final return pressed state", lambda:
                    next((row for row in atspi_probe(python, "states", app.pid, "Daily")["matches"]
                          if row["name"] == "Daily" and row["role"] == "toggle button"
                          and row.get("pid") == app.pid and "pressed" in row["states"]), None))
                selected_mode = selected_heatmap_mode(python, app.pid)
                if selected_mode["name"] != "Daily" or selected_mode["identity"] != daily_control["identity"]:
                    raise RuntimeError("Daily was not the unique visible pressed mode after return action")
                evidence["actions"].append({"kind": "AT-SPI AccessibleAction.DoAction",
                                            "control_group": "Token activity heatmap",
                                            "final_return": {"mode": "Daily", "changed": True,
                                                             "role": daily_state["role"],
                                                             "states": daily_state["states"],
                                                             "identity": daily_state["identity"],
                                                             "pid": daily_state["pid"]}})

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
                    if mode == "loading":
                        capture_screen(screenshooter, env, scratch / "capture-sessions-loading",
                                       artifact_dir / "sessions-loading.png")
                        wait_visible_text(python, app.pid,
                                          "Refreshing · showing the last successful result")
                        evidence["screenshots"]["sessions_loading"] = str(
                            artifact_dir / "sessions-loading.png")
                    sessions_statuses.append({"fixture_mode": mode, "visible_status": visible["name"],
                                              "role": visible["role"], "pid": visible["pid"]})
                    wait_until(f"synthetic sessions fixture {mode} completed", lambda mode=mode:
                        f"sessions-fixture-{mode}-done" in call_log.read_text(encoding="utf-8").splitlines())
                    # Keep each result capture tied to the visible assertion above
                    # and to the completed synthetic scan, rather than the loading
                    # frame or a neighbouring refresh state.
                    if mode in ("success", "empty", "error"):
                        capture_screen(screenshooter, env, scratch / f"capture-sessions-{mode}",
                                       artifact_dir / f"sessions-{mode}.png")
                        evidence["screenshots"][f"sessions_{mode}"] = str(
                            artifact_dir / f"sessions-{mode}.png")
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
    parser.add_argument("--scenario", choices=("matrix", "advanced", "settings-residual"), default="matrix",
                        help="isolated acceptance slice (default: existing matrix)")
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
                   "--artifact-dir", args.artifact_dir,
                   "--scenario", args.scenario]
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
                                type(exc).__name__, getattr(exc, "details", None))
        print(f"isolated native Wayland smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
