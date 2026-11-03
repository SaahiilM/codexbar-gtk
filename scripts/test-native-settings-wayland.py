#!/usr/bin/env python3
"""Guarded Wayland Settings smoke using one RemoteDesktop portal connection.

Run only in the intended KDE Wayland session and in the matching transient
app scope documented in UG_GATE.md. The user must visually verify the consent
prompt before approving. This script never falls back to X11 or fake input.
"""
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
import uuid

from gi.repository import Gio, GLib

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
SESSION_IFACE = "org.freedesktop.portal.Session"
APP_ID = "codexbar-gtk-synthetic-wayland-test"
WAYLAND_SWITCH_ACTIONS = {
    "refresh-when-panel-opens": {
        "preference": "refreshAllProvidersOnMenuOpen",
        "label": "Refresh when the panel opens",
        "y_fraction": 0.40,
    },
    "show-panel-on-start": {
        "preference": "showPopupOnStart",
        "label": "Show the panel on start",
        "y_offset": 488,
    },
    "start-at-login": {
        "preference": "launchAtLogin",
        "label": "Start at login",
        "y_offset": 440,
        "requires_autostart_entry": True,
    },
    "hide-personal-info": {
        "preference": "hidePersonalInfo",
        "label": "Hide personal info",
        "y_offset": 575,
    },
}
PORTAL_DESKTOP_ENTRY = (
    "[Desktop Entry]\nType=Application\n"
    "Name=CodexBar GTK synthetic Wayland test\n"
    "Exec=/bin/true\nStartupWMClass=com.steipete.CodexBarGTK\n"
)


def guard_target(state, expected_pid, x, y, now=None):
    """Fail closed unless recent compositor evidence identifies the exact target."""
    now = time.monotonic() if now is None else now
    age = now - state.get("received", 0)
    return (
        0.15 <= age <= 0.35
        and state.get("pid") == expected_pid
        and state.get("active") is True
        and state.get("top_hit") is True
        and state.get("cursor") == [x, y]
    )


def active_target(state, expected_pid):
    """Require exact synthetic app focus for a read-only baseline capture."""
    return state.get("pid") == expected_pid and state.get("active") is True


def target_window_contains(state, x, y):
    """Check requested target lies inside the synthetic window's geometry."""
    geometry = state.get("target_geometry")
    if not isinstance(geometry, list) or len(geometry) != 4:
        return False
    gx, gy, width, height = geometry
    return width > 0 and height > 0 and gx <= x < gx + width and gy <= y < gy + height


def changed_preferences(before, after):
    """Return preference keys whose persisted values changed."""
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def switch_point_from_geometry(geometry, y_fraction=0.40, y_offset=None):
    """Choose a measured General switch row from its window-relative Y point."""
    if not isinstance(geometry, list) or len(geometry) != 4:
        raise ValueError("Settings window geometry is unavailable")
    gx, gy, width, height = geometry
    if width <= 0 or height <= 0:
        raise ValueError("Settings window geometry is invalid")
    if y_offset is None:
        if not 0.0 < y_fraction < 1.0:
            raise ValueError("General switch row fraction is invalid")
        local_y = round(height * y_fraction)
    else:
        if not isinstance(y_offset, int) or not 0 <= y_offset < height:
            raise ValueError("General switch row offset is outside the Settings window")
        local_y = y_offset
    return round(gx + width * 0.50), round(gy + local_y)


def activation_script(expected_pid):
    """Reactivate only the synthetic Settings window after consent confirmation."""
    expected_pid = int(expected_pid)
    return f'''var TARGET_PID={expected_pid};
var target=null;
var windows=workspace.stackingOrder;
for(var i=0;i<windows.length;i++){{
  if(Number(windows[i].pid)===TARGET_PID && String(windows[i].caption).indexOf("CodexBar Settings")>=0){{
    if(target){{target=null;break;}}
    target=windows[i];
  }}
}}
if(target){{
  if(target.minimized)target.minimized=false;
  workspace.activeWindow=target;
}}
var p=workspace.cursorPos,h=workspace.windowAt(p,1),top=h&&h.length?h[0]:null,a=workspace.activeWindow;
var targetState=null;
for(var j=0;j<workspace.stackingOrder.length;j++)if(Number(workspace.stackingOrder[j].pid)===TARGET_PID)targetState=workspace.stackingOrder[j];
var geometry=targetState?{{x:Number(targetState.x),y:Number(targetState.y),width:Number(targetState.width),height:Number(targetState.height)}}:null;
var state={{pid:a?Number(a.pid):0,active:!!(a&&Number(a.pid)===TARGET_PID),top_hit:!!(top&&Number(top.pid)===TARGET_PID),target_present:!!targetState,target_geometry:geometry?[geometry.x,geometry.y,geometry.width,geometry.height]:null,cursor:[Number(p.x),Number(p.y)],portal_active:false}};
callDBus("org.codexbar.U05.Guard","/org/codexbar/U05/Guard","org.codexbar.U05.Guard","Record",JSON.stringify(state));
'''


def create_portal_desktop_entry(path):
    """Create the one temporary portal identity without replacing user data."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as desktop_file:
            try:
                desktop_file.write(PORTAL_DESKTOP_ENTRY)
            except OSError:
                path.unlink(missing_ok=True)
                raise
    except FileExistsError as error:
        raise RuntimeError(f"refusing to replace existing desktop entry {path}") from error
    return True


class PortalDriver:
    """Keep portal setup and granted input on one authenticated bus connection."""
    def __init__(self, bus):
        self.bus = bus
        self.loop = GLib.MainLoop()
        self.session = None
        self.phase = "create"
        self.response = None
        self.subscription = None
        self.request_token = None
        self.sender = bus.get_unique_name().lstrip(":").replace(".", "_")

    def request(self, method, signature, args, options_index):
        token = "u05_" + uuid.uuid4().hex
        args = list(args)
        options = dict(args[options_index])
        options["handle_token"] = GLib.Variant("s", token)
        args[options_index] = options
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        self.request_token = token
        self.subscription = self.bus.signal_subscribe(
            PORTAL, "org.freedesktop.portal.Request", "Response", path,
            None, Gio.DBusSignalFlags.NONE, self.on_response)
        self.remote_call(method, signature, tuple(args))

    def remote_call(self, method, signature, args, timeout=5000):
        self.bus.call_sync(PORTAL, PORTAL_PATH, REMOTE, method,
                           GLib.Variant(signature, args), None,
                           Gio.DBusCallFlags.NONE, timeout, None)

    def on_response(self, _bus, _sender, path, _iface, _signal, params):
        code, values = params.unpack()
        self.response = (code, values)
        if self.subscription is not None:
            self.bus.signal_unsubscribe(self.subscription)
            self.subscription = None
        if code:
            self.loop.quit()
            return
        try:
            if self.phase == "create":
                self.session = values["session_handle"]
                self.phase = "select"
                self.request("SelectDevices", "(oa{sv})", (self.session, {
                    "types": GLib.Variant("u", 3),
                    "persist_mode": GLib.Variant("u", 0),
                }), 1)
            elif self.phase == "select":
                self.phase = "start"
                self.request("Start", "(osa{sv})", (self.session, "", {}), 2)
            else:
                self.phase = "approved"
                self.loop.quit()
        except Exception as error:
            print(f"portal request failed: {error}", file=sys.stderr, flush=True)
            self.loop.quit()

    def start(self):
        self.request("CreateSession", "(a{sv})", ({
            "session_handle_token": GLib.Variant("s", "u05_" + uuid.uuid4().hex),
        },), 0)
        GLib.timeout_add_seconds(300, lambda: (self.loop.quit(), False)[1])
        self.loop.run()
        if self.phase != "approved" or not self.response or self.response[0] != 0:
            raise RuntimeError("portal consent declined or timed out; no input sent")
        if self.response[1].get("devices") != 3:
            raise RuntimeError("portal did not grant pointer and keyboard only")

    def move(self, dx, dy):
        self.remote_call("NotifyPointerMotion", "(oa{sv}dd)",
                         (self.session, {}, float(dx), float(dy)))

    def click(self):
        for state in (1, 0):
            self.remote_call("NotifyPointerButton", "(oa{sv}iu)",
                             (self.session, {}, 272, state))

    def close(self):
        if self.session:
            try:
                self.bus.call_sync(PORTAL, self.session, SESSION_IFACE, "Close", None,
                                   None, Gio.DBusCallFlags.NONE, 5000, None)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--action", choices=tuple(WAYLAND_SWITCH_ACTIONS),
                        default="refresh-when-panel-opens",
                        help="allowlisted General switch action to exercise")
    parser.add_argument("--inspect-only", action="store_true",
                        help="capture the synthetic Settings window and exit without requesting portal access")
    parser.add_argument("--switch-x", type=int, help="override the geometry-derived KWin X coordinate")
    parser.add_argument("--switch-y", type=int, help="override the geometry-derived KWin Y coordinate")
    args = parser.parse_args()
    if (args.switch_x is None) != (args.switch_y is None):
        parser.error("--switch-x and --switch-y must be supplied together")
    action = WAYLAND_SWITCH_ACTIONS[args.action]
    preference_key = action["preference"]
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("XDG_RUNTIME_DIR"):
        parser.error("run inside the intended Wayland session")
    if os.environ.get("XDG_SESSION_TYPE") not in (None, "wayland"):
        parser.error("XDG_SESSION_TYPE is not Wayland")
    if not args.binary.is_file() or not os.access(args.binary, os.X_OK):
        parser.error("--binary must name an executable native GTK build")
    for tool in ("qdbus6", "systemd-run"):
        if shutil.which(tool) is None:
            parser.error(f"required KDE Wayland tool missing: {tool}")
    cgroup = pathlib.Path("/proc/self/cgroup").read_text()
    if "app-codexbar-gtk-synthetic-wayland-test.scope" not in cgroup:
        parser.error("run inside app-codexbar-gtk-synthetic-wayland-test.scope; see UG_GATE.md")
    for tool in ("spectacle",):
        if shutil.which(tool) is None:
            parser.error(f"required consent-window capture tool missing: {tool}")

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="codexbar-wayland-settings-"))
    scratch.chmod(0o700)
    app = observer = portal = None
    bus = None
    capture_status = None
    kwin_plugin = "codexbar_u05_guard_" + uuid.uuid4().hex[:12]
    focus_plugin = "codexbar_u05_focus_" + uuid.uuid4().hex[:12]
    focus_script_loaded = False
    desktop_path = pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share")) / "applications" / f"{APP_ID}.desktop"
    desktop_created = False
    desktop_parent_created = not desktop_path.parent.exists()
    try:
        # Do not replace XDG_RUNTIME_DIR: GTK and the portal must use the active
        # desktop's Wayland socket and session bus. All persistent app state is private.
        home = scratch / "home"
        (home / ".config" / "codexbar-gtk").mkdir(parents=True, mode=0o700)
        preferences = home / ".config" / "codexbar-gtk" / "settings.json"
        preferences.write_text(json.dumps({preference_key: False}) + "\n")
        fake = scratch / "codexbar"
        fake.write_text("#!/bin/sh\ncase \"${1-}\" in --version) echo 'CodexBar synthetic fixture 0.82.0';; *) echo '[]';; esac\n")
        fake.chmod(0o700)
        # Portal identifies the requester through its app-scoped systemd unit and
        # this matching temporary desktop entry. Remove only the entry we create.
        create_portal_desktop_entry(desktop_path)
        desktop_created = True
        env = os.environ.copy()
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
                   CODEXBAR_CLI=str(fake), GTK_A11Y="none", GTK_USE_PORTAL="0",
                   GDK_BACKEND="wayland", GSK_RENDERER="cairo")
        env.pop("CODEXBAR_RUST_CORE", None)
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        spectacle_owned = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "NameHasOwner", GLib.Variant("(s)", ("org.kde.spectacle",)),
            GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if spectacle_owned:
            raise RuntimeError("Spectacle is already running; refusing to use its existing session")
        owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", ("com.steipete.CodexBarGTK",)),
                              GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if owned:
            raise RuntimeError("native application ID already owned; refusing to target an existing app")
        portal_owner = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "GetNameOwner", GLib.Variant("(s)", ("org.freedesktop.impl.portal.desktop.kde",)),
            GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        portal_pid = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "GetConnectionUnixProcessID", GLib.Variant("(s)", (portal_owner,)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        app_log = (scratch / "app.log").open("wb")
        app = subprocess.Popen([str(args.binary), "--settings"], env=env, stdout=app_log,
                               stderr=subprocess.STDOUT, start_new_session=True)
        state_path = scratch / "kwin-state.json"
        observer_ready = scratch / "observer-ready"
        consent_capture = scratch / "portal-consent.png"
        settings_capture = scratch / "settings-before.png"
        capture_status = scratch / "portal-capture.json"
        observer_py = scratch / "observer.py"
        observer_py.write_text(OBSERVER_PY)
        observer = subprocess.Popen([sys.executable, str(observer_py), str(state_path), str(observer_ready),
                                     str(portal_pid), str(consent_capture), str(capture_status)],
                                    env=os.environ.copy(), stdout=subprocess.DEVNULL,
                                    stderr=(scratch / "observer.log").open("wb"), start_new_session=True)
        ready_deadline = time.monotonic() + 5
        while time.monotonic() < ready_deadline and not observer_ready.exists():
            if observer.poll() is not None:
                raise RuntimeError(f"KWin guard D-Bus observer exited; diagnostics: {scratch / 'observer.log'}")
            time.sleep(.02)
        if not observer_ready.exists():
            raise RuntimeError("KWin guard D-Bus observer did not acquire its name")
        js_path = scratch / "kwin-observer.js"
        js_path.write_text(KWIN_JS.replace("__PID__", str(app.pid)).replace("__PORTAL_PID__", str(portal_pid)).replace("__PLUGIN__", kwin_plugin))
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.loadScript", str(js_path), kwin_plugin],
                       check=True, capture_output=True, text=True)
        loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                 "org.kde.kwin.Scripting.isScriptLoaded", kwin_plugin],
                                check=True, capture_output=True, text=True).stdout.strip()
        if loaded != "true":
            raise RuntimeError(f"KWin did not load observer script {kwin_plugin}")
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.start"], check=True, capture_output=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and app.poll() is None:
            if state_path.exists() and json.loads(state_path.read_text()).get("target_present"):
                break
            time.sleep(.05)
        if not state_path.exists() or not json.loads(state_path.read_text()).get("target_present"):
            raise RuntimeError("KWin observer did not see the synthetic Settings window")
        # A script loaded into the host compositor is observational only: it does
        # not synthesize input, move the cursor, or change compositor settings.
        baseline_deadline = time.monotonic() + 5
        settings_state = json.loads(state_path.read_text())
        while time.monotonic() < baseline_deadline and not active_target(settings_state, app.pid):
            time.sleep(.02)
            if state_path.exists():
                settings_state = json.loads(state_path.read_text())
        if not active_target(settings_state, app.pid):
            raise RuntimeError("synthetic Settings was not active for baseline capture; no portal request sent")
        baseline_capture = subprocess.run(
            ["spectacle", "--background", "--activewindow", "--nonotify", "--output", str(settings_capture)],
            capture_output=True, text=True, timeout=8,
        )
        if baseline_capture.returncode != 0 or not settings_capture.is_file():
            raise RuntimeError("synthetic Settings baseline capture failed; no portal request sent")
        print(f"Synthetic Settings baseline captured at {settings_capture}; verify the requested row.", flush=True)
        if args.inspect_only:
            print("Inspection-only mode; no portal request or input sent.", flush=True)
            return 0
        print(f"Synthetic fixture and consent capture path: {scratch}", flush=True)
        print("Waiting for KDE RemoteDesktop consent prompt. Verify its synthetic test name visually; click Allow only then.", flush=True)
        portal = PortalDriver(bus)
        portal.start()
        capture_deadline = time.monotonic() + 3
        while time.monotonic() < capture_deadline and not capture_status.exists():
            time.sleep(.05)
        if not capture_status.exists():
            raise RuntimeError("portal returned without a captured approval window; no input sent")
        capture_result = json.loads(capture_status.read_text())
        if capture_result.get("exit_code") != 0 or not consent_capture.is_file():
            raise RuntimeError("portal approval window capture failed; no input sent")
        print(f"Portal approval window captured at {consent_capture}; waiting for reviewer confirmation.", flush=True)
        print("After the reviewer verifies the synthetic test name and you click Allow, enter APPROVE here.", flush=True)
        if sys.stdin.readline().strip() != "APPROVE":
            raise RuntimeError("explicit operator approval token missing; no input sent")

        def latest():
            return json.loads(state_path.read_text())

        # The operator confirmation runs in the T3 client, which becomes the
        # active window. Reactivate the exact synthetic Settings PID/title after
        # receiving APPROVE even if an earlier snapshot happened to show it active.
        focus_js_path = scratch / "kwin-focus-target.js"
        focus_js_path.write_text(activation_script(app.pid))
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.loadScript", str(focus_js_path), focus_plugin],
                       check=True, capture_output=True, text=True)
        loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                 "org.kde.kwin.Scripting.isScriptLoaded", focus_plugin],
                                check=True, capture_output=True, text=True).stdout.strip()
        if loaded != "true":
            raise RuntimeError("KWin did not load the synthetic Settings focus helper; no input sent")
        focus_script_loaded = True
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.start"], check=True, capture_output=True)

        # Wait for the Settings window to regain focus and a stable pointer after
        # consent. Never move if focus remains elsewhere or cursor samples churn.
        deadline = time.monotonic() + 5
        baseline = None
        while time.monotonic() < deadline:
            state = latest()
            age = time.monotonic() - state.get("received", 0)
            if state.get("pid") == app.pid and state.get("active") and 0.15 <= age <= 0.35:
                baseline = state
                break
            time.sleep(.02)
        if baseline is None:
            raise RuntimeError("Settings did not regain stable focus after portal consent; no input sent")
        if args.switch_x is not None:
            switch_x, switch_y = args.switch_x, args.switch_y
        else:
            point_options = (
                {"y_offset": action["y_offset"]}
                if "y_offset" in action
                else {"y_fraction": action["y_fraction"]}
            )
            switch_x, switch_y = switch_point_from_geometry(
                baseline.get("target_geometry"), **point_options
            )
        if not target_window_contains(baseline, switch_x, switch_y):
            raise RuntimeError("action coordinates are outside the synthetic Settings window; no input sent")
        print(f"Guarded Settings action '{args.action}' switch point: ({switch_x},{switch_y})", flush=True)
        baseline_preferences = json.loads(preferences.read_text())
        if baseline_preferences.get(preference_key) is not False:
            raise RuntimeError(
                f"selected preference {preference_key} did not start false; no click sent"
            )
        dx, dy = switch_x - baseline["cursor"][0], switch_y - baseline["cursor"][1]
        if abs(dx) > 1600 or abs(dy) > 1200:
            raise RuntimeError("requested pointer delta exceeds safety bound; no input sent")
        portal.move(dx, dy)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = latest()
            if guard_target(state, app.pid, switch_x, switch_y):
                break
            time.sleep(.01)
        else:
            raise RuntimeError("target/focus hit-test unstable after motion; no click sent")
        # Final adjacent snapshot check: any stale or ambiguous state suppresses click.
        if not guard_target(latest(), app.pid, switch_x, switch_y):
            raise RuntimeError("final target/focus guard failed; no click sent")
        portal.click()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                after_preferences = json.loads(preferences.read_text())
                if after_preferences.get(preference_key) is True:
                    changed = changed_preferences(baseline_preferences, after_preferences)
                    if changed != [preference_key]:
                        raise RuntimeError(
                            f"unexpected preferences changed during {args.action}: {changed}"
                        )
                    if action.get("requires_autostart_entry"):
                        autostart_entry = home / ".config" / "autostart" / "codexbar-gtk.desktop"
                        if not autostart_entry.is_file():
                            raise RuntimeError(
                                "synthetic autostart entry did not persist during start-at-login"
                            )
                    print(f"PASS: synthetic Settings preference {preference_key}=true persisted", flush=True)
                    return 0
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(.05)
        after_preferences = json.loads(preferences.read_text())
        changed = changed_preferences(baseline_preferences, after_preferences)
        raise RuntimeError(
            f"preference {preference_key} did not persist true; observed "
            f"{after_preferences.get(preference_key)!r}; changed keys={changed}"
        )
    finally:
        if portal:
            portal.close()
        if app and app.poll() is None:
            try:
                os.killpg(app.pid, signal.SIGTERM)
                app.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(app.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if observer and observer.poll() is None:
            try:
                # The observer owns the active-window Spectacle capture as a
                # child in its own process group. Stop both on every exit path.
                os.killpg(observer.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                observer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(observer.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if capture_status and capture_status.exists() and bus:
            try:
                owner = bus.call_sync(
                    "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                    "NameHasOwner", GLib.Variant("(s)", ("org.kde.spectacle",)),
                    GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                if owner:
                    subprocess.run(["qdbus6", "org.kde.spectacle", "/MainApplication",
                                    "org.qtproject.Qt.QCoreApplication.quit"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
        if focus_script_loaded:
            try:
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                "org.kde.kwin.Scripting.unloadScript", focus_plugin],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
        try:
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", kwin_plugin],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass
        if desktop_created:
            try:
                if desktop_path.read_text(encoding="utf-8") == PORTAL_DESKTOP_ENTRY:
                    desktop_path.unlink()
            except FileNotFoundError:
                pass
        if desktop_parent_created:
            try:
                desktop_path.parent.rmdir()
            except OSError:
                pass
        if os.environ.get("KEEP_WAYLAND_TEST_TMP") == "1":
            print(f"Synthetic test diagnostics kept at {scratch}", file=sys.stderr, flush=True)
        else:
            shutil.rmtree(scratch, ignore_errors=True)


OBSERVER_PY = r'''import json, pathlib, subprocess, sys, threading, time
from gi.repository import Gio, GLib
path=pathlib.Path(sys.argv[1]); ready=pathlib.Path(sys.argv[2]); portal_pid=int(sys.argv[3]); image=pathlib.Path(sys.argv[4]); status=pathlib.Path(sys.argv[5]); loop=GLib.MainLoop(); captured=False
xml='<node><interface name="org.codexbar.U05.Guard"><method name="Record"><arg name="state" type="s" direction="in"/></method></interface></node>'
node=Gio.DBusNodeInfo.new_for_xml(xml); bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
def method(_c,_s,_p,_i,_m,params,inv):
    global captured
    (raw,)=params.unpack(); state=json.loads(raw); state['received']=time.monotonic()
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(state)); tmp.replace(path)
    if state.get('portal_active') and not captured:
        captured=True
        def capture():
            try:
                result=subprocess.run(['spectacle','--background','--activewindow','--nonotify','--output',str(image)],capture_output=True,text=True,timeout=8)
                status.write_text(json.dumps({'exit_code':result.returncode,'stderr':result.stderr[-500:]}))
            except Exception as error: status.write_text(json.dumps({'exit_code':-1,'error':str(error)}))
        threading.Thread(target=capture,daemon=True).start()
    inv.return_value(GLib.Variant('()',()))
bus.register_object('/org/codexbar/U05/Guard',node.interfaces[0],method)
def acquired(_bus,_name): ready.write_text('ready')
Gio.bus_own_name_on_connection(bus,'org.codexbar.U05.Guard',Gio.BusNameOwnerFlags.NONE,acquired,None)
loop.run()
'''

KWIN_JS = r'''var TARGET_PID=__PID__, PORTAL_PID=__PORTAL_PID__, PLUGIN="__PLUGIN__", service="org.codexbar.U05.Guard", path="/org/codexbar/U05/Guard", iface="org.codexbar.U05.Guard";
function report(){var p=workspace.cursorPos,h=workspace.windowAt(p,1),top=h&&h.length?h[0]:null,a=workspace.activeWindow,w=workspace.stackingOrder,t=null;for(var i=0;i<w.length;i++)if(Number(w[i].pid)===TARGET_PID)t=w[i];var g=t?{x:Number(t.x),y:Number(t.y),width:Number(t.width),height:Number(t.height)}:null;var s={pid:a?Number(a.pid):0,active:!!(a&&Number(a.pid)===TARGET_PID),top_hit:!!(top&&Number(top.pid)===TARGET_PID),target_present:!!t,target_geometry:g?[g.x,g.y,g.width,g.height]:null,cursor:[Number(p.x),Number(p.y)],portal_active:!!(a&&Number(a.pid)===PORTAL_PID)};callDBus(service,path,iface,"Record",JSON.stringify(s));}
report();workspace.cursorPosChanged.connect(report);workspace.windowActivated.connect(report);workspace.windowAdded.connect(report);workspace.windowRemoved.connect(report);'''


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAIL CLOSED: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
