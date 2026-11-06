#!/usr/bin/env python3
"""Guarded Wayland Spend-page evidence harness (build 84 slice).

Target surface: Usage & Spend (--page spend), NOT Settings. The Spend page is a
separate window (title "CodexBar GTK — Usage & Spend") in the same transient
app scope as the Settings runner in scripts/test-native-settings-wayland.py;
window geometry, focus recovery, and control coordinates are therefore
Spend-specific, while the portal/guard/cleanup patterns are reused (copied,
not imported, so this runner is independent of the Settings runner owned by
sibling work).

Interactions exercised with one fresh named KDE RemoteDesktop grant
(types=3, persist_mode=0, no ScreenCast/clipboard):
  --action range-7-days | range-30-days | range-90-days | range-all
  --action mode-daily | mode-weekly | mode-cumulative
  --action tooltip   (hover a heatmap cell; no click)
  --action refresh   (pointer click on the Refresh button; no keyboard event)

States exercised without portal input (--state, fixture sequence only):
  loading | success | partial | empty | retained-error

Each run: synthetic CLI fixture (isolated HOME, no real accounts/keys),
Spectacle active-window baseline capture before portal consent, guarded
portal motion/click (or hover), post-action Spectacle capture, and a checked
hold-fixture state assertion where applicable. Fails closed (no input sent)
unless fresh KWin evidence shows the exact synthetic Spend PID active,
topmost, and at the target cursor point. The app's Ctrl+R accelerator is NOT
used; refresh goes through the pointer path only.

Live run (serially owned Wayland slot, intended KDE session):
  systemd-run --user --scope --unit=app-codexbar-gtk-synthetic-wayland-test.scope \
    python3 scripts/test-native-spend-wayland.py \
      --binary "$PWD/rust-gtk/target/debug/codexbar-gtk-native" --action range-30-days
  systemd-run --user --scope --unit=app-codexbar-gtk-synthetic-wayland-test.scope \
    python3 scripts/test-native-spend-wayland.py \
      --binary "$PWD/rust-gtk/target/debug/codexbar-gtk-native" --state success
  # Optional measured overrides (must be supplied as a pair, inside the window):
  #   --point-x 780 --point-y 340
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
SPEND_TITLE = "CodexBar GTK"
SPEND_TITLE_SUFFIX = "Usage & Spend"

# Xvfb-measured control centers from scripts/smoke-native-usage-pages.sh in
# the fixed 1080x820 Spend window (range y=334, mode y=430). On Wayland the
# window size is compositor-chosen; fractions are relative to the live
# geometry so the same action adapts. The operator verifies the before/after
# Spectacle captures visually; --point-x/--point-y override a single action
# when a live measurement disagrees.
WAYLAND_SPEND_ACTIONS = {
    "range-7-days": {"kind": "range", "value": "7 days",
                     "x_fraction": 745 / 1080, "y_fraction": 334 / 820},
    "range-30-days": {"kind": "range", "value": "30 days",
                      "x_fraction": 820 / 1080, "y_fraction": 334 / 820},
    "range-90-days": {"kind": "range", "value": "90 days",
                      "x_fraction": 900 / 1080, "y_fraction": 334 / 820},
    "range-all": {"kind": "range", "value": "All",
                  "x_fraction": 1000 / 1080, "y_fraction": 334 / 820},
    "mode-daily": {"kind": "mode", "value": "Daily",
                   "x_fraction": 85 / 1080, "y_fraction": 430 / 820},
    "mode-weekly": {"kind": "mode", "value": "Weekly",
                    "x_fraction": 160 / 1080, "y_fraction": 430 / 820},
    "mode-cumulative": {"kind": "mode", "value": "Cumulative",
                        "x_fraction": 251 / 1080, "y_fraction": 430 / 820},
}

WAYLAND_SPEND_STATES = ("loading", "success", "partial", "empty",
                        "retained-error")

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


def spend_point_from_geometry(geometry, x_fraction, y_fraction):
    """Map an Xvfb-measured fraction onto the live Spend window geometry."""
    if not isinstance(geometry, list) or len(geometry) != 4:
        raise ValueError("Spend window geometry is unavailable")
    gx, gy, width, height = geometry
    if width <= 0 or height <= 0:
        raise ValueError("Spend window geometry is invalid")
    if not (0.0 < x_fraction < 1.0 and 0.0 < y_fraction < 1.0):
        raise ValueError("Spend control fraction is invalid")
    return round(gx + width * x_fraction), round(gy + height * y_fraction)


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


def activation_script(expected_pid):
    """Reactivate only the synthetic Spend window after consent confirmation."""
    expected_pid = int(expected_pid)
    return f'''var TARGET_PID={expected_pid};
var target=null;
var windows=workspace.stackingOrder;
for(var i=0;i<windows.length;i++){{
  if(Number(windows[i].pid)===TARGET_PID && String(windows[i].caption).indexOf("Usage & Spend")>=0){{
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
callDBus("org.codexbar.SpendGuard","/org/codexbar/SpendGuard","org.codexbar.SpendGuard","Record",JSON.stringify(state));
'''


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
        token = "spend_" + uuid.uuid4().hex
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
            "session_handle_token": GLib.Variant("s", "spend_" + uuid.uuid4().hex),
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

    def hover_settle(self, seconds=0.6):
        """Hold the pointer still so the heatmap tooltip can appear."""
        time.sleep(seconds)

    def close(self):
        if self.session:
            try:
                self.bus.call_sync(PORTAL, self.session, SESSION_IFACE, "Close", None,
                                   None, Gio.DBusCallFlags.NONE, 5000, None)
            except Exception:
                pass


def guarded_move(portal, app_pid, latest, x, y):
    """Move to (x, y) and wait until the compositor state passes guard."""
    state = latest()
    dx, dy = x - state["cursor"][0], y - state["cursor"][1]
    if abs(dx) > 1600 or abs(dy) > 1200:
        raise RuntimeError("requested pointer delta exceeds safety bound; no input sent")
    portal.move(dx, dy)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if guard_target(latest(), app_pid, x, y):
            break
        time.sleep(.01)
    else:
        raise RuntimeError("target/focus hit-test unstable after motion; no input sent")
    if not guard_target(latest(), app_pid, x, y):
        raise RuntimeError("final target/focus guard failed; no input sent")


def guarded_click(portal, app_pid, latest, x, y):
    guarded_move(portal, app_pid, latest, x, y)
    if not guard_target(latest(), app_pid, x, y):
        raise RuntimeError("final target/focus guard failed; no click sent")
    portal.click()


def count_cost_calls(count_path):
    try:
        return len(count_path.read_text().splitlines())
    except FileNotFoundError:
        return 0


def spend_fixture_script(today, yesterday):
    """Synthetic cost provider with file-controlled empty/fail/delay states."""
    return f'''#!/bin/sh
set -eu
case "${{1-}}" in
  --version) echo 'CodexBar synthetic fixture 0.82.0'; echo call >> "$NATIVE_SPEND_CALLS";;
  usage) echo '[]'; echo call >> "$NATIVE_SPEND_CALLS";;
  cost)
    echo call >> "$NATIVE_SPEND_CALLS"
    echo call >> "$NATIVE_SPEND_COST_CALLS"
    if [ -e "$NATIVE_SPEND_FAIL_COST" ]; then : > "$NATIVE_SPEND_COST_FAILURE_DONE"; exit 1; fi
    while [ -e "$NATIVE_SPEND_DELAY_COST" ] && [ ! -e "$NATIVE_SPEND_RELEASE_COST" ]; do sleep 0.03; done
    if [ -e "$NATIVE_SPEND_EMPTY_COST" ]; then printf '%s\n' '[]'; : > "$NATIVE_SPEND_COST_DONE"; exit 0; fi
    partial=""
    if [ -e "$NATIVE_SPEND_PARTIAL_COST" ]; then partial=",\"historyCoverageIsEstablished\":false"; fi
    printf '[{{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{{"priced":3,"unpriced":1}}%s,"provenance":"synthetic_history","daily":[{{"date":"{today}","totalCost":3.25,"totalTokens":800}},{{"date":"{yesterday}","totalCost":0,"totalTokens":0}}],"projects":[{{"name":"Synthetic Workspace","totalCost":12.5,"totalTokens":1200}}],"models":[{{"name":"Synthetic Model","cost":12.5,"totalTokens":1200}}]}}]\n' "$partial"
    : > "$NATIVE_SPEND_COST_DONE"
    ;;
  sessions) printf '%s\n' '[]';;
  *) printf '%s\n' '[]';;
esac
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--action", choices=tuple(WAYLAND_SPEND_ACTIONS) + ("tooltip", "refresh"),
                        help="allowlisted Spend pointer action to exercise")
    parser.add_argument("--state", choices=WAYLAND_SPEND_STATES,
                        help="fixture state to capture without portal input")
    parser.add_argument("--inspect-only", action="store_true",
                        help="capture the synthetic Spend baseline and exit without requesting portal access")
    parser.add_argument("--point-x", type=int, help="override the geometry-derived KWin X coordinate")
    parser.add_argument("--point-y", type=int, help="override the geometry-derived KWin Y coordinate")
    args = parser.parse_args()
    if args.action and args.state:
        parser.error("--action and --state are mutually exclusive")
    if not args.action and not args.state:
        parser.error("supply one of --action or --state")
    if (args.point_x is None) != (args.point_y is None):
        parser.error("--point-x and --point-y must be supplied together")
    if args.point_x is not None and not args.action:
        parser.error("--point-x/--point-y apply to --action runs only")
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

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="codexbar-wayland-spend-"))
    scratch.chmod(0o700)
    app = observer = portal = None
    bus = None
    capture_status = None
    kwin_plugin = "codexbar_spend_guard_" + uuid.uuid4().hex[:12]
    focus_plugin = "codexbar_spend_focus_" + uuid.uuid4().hex[:12]
    focus_script_loaded = False
    desktop_path = pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share")) / "applications" / f"{APP_ID}.desktop"
    desktop_created = False
    desktop_parent_created = not desktop_path.parent.exists()
    try:
        home = scratch / "home"
        (home / ".config" / "codexbar-gtk").mkdir(parents=True, mode=0o700)
        # Seed one known preference; Spend axes here deliberately assert no
        # preference key changes (ranges/modes are view state, not settings).
        preferences = home / ".config" / "codexbar-gtk" / "settings.json"
        # Purposely empty: Defaults would trigger a refresh schedule where
        # retained-error's empty-cost fixture could never fire cost-done.
        # The empty map keeps the "no preference changed" baseline assertion
        # trivially true.
        preferences.write_text(json.dumps({}) + "\n")

        import datetime as _dt
        _today = _dt.date.today().isoformat()
        _yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        fake = scratch / "codexbar"
        fake.write_text(spend_fixture_script(_today, _yesterday))
        fake.chmod(0o700)
        calls_path = scratch / "calls.log"
        cost_calls_path = scratch / "cost-calls.log"
        cost_done = scratch / "cost-done"
        cost_failure_done = scratch / "cost-failure-done"
        delay_cost = scratch / "delay-cost"
        release_cost = scratch / "release-cost"
        partial_cost = scratch / "partial-cost"
        fail_cost = scratch / "fail-cost"
        empty_cost = scratch / "empty-cost"
        if args.state in ("loading",):
            delay_cost.write_text("")
        if args.state in ("empty",):
            empty_cost.write_text("")
        if args.state in ("partial",):
            partial_cost.write_text("")
        if args.state in ("retained-error",):
            fail_cost.write_text("")

        create_portal_desktop_entry(desktop_path)
        desktop_created = True
        env = os.environ.copy()
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
                   CODEXBAR_CLI=str(fake), GTK_A11Y="none", GTK_USE_PORTAL="0",
                   GDK_BACKEND="wayland", GSK_RENDERER="cairo",
                   NATIVE_SPEND_CALLS=str(calls_path),
                   NATIVE_SPEND_COST_CALLS=str(cost_calls_path),
                   NATIVE_SPEND_PARTIAL_COST=str(partial_cost),
                   NATIVE_SPEND_COST_DONE=str(cost_done),
                   NATIVE_SPEND_COST_FAILURE_DONE=str(cost_failure_done),
                   NATIVE_SPEND_DELAY_COST=str(delay_cost),
                   NATIVE_SPEND_RELEASE_COST=str(release_cost),
                   NATIVE_SPEND_FAIL_COST=str(fail_cost),
                   NATIVE_SPEND_EMPTY_COST=str(empty_cost),
                   )
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
        app = subprocess.Popen([str(args.binary), "--page", "spend"], env=env, stdout=app_log,
                               stderr=subprocess.STDOUT, start_new_session=True)
        state_path = scratch / "kwin-state.json"
        observer_ready = scratch / "observer-ready"
        consent_capture = scratch / "portal-consent.png"
        spend_capture = scratch / "spend-before.png"
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

        # Wait for the Spend window and, for success/partial, fixture data.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and app.poll() is None:
            if state_path.exists() and json.loads(state_path.read_text()).get("target_present"):
                break
            time.sleep(.05)
        if not state_path.exists() or not json.loads(state_path.read_text()).get("target_present"):
            raise RuntimeError("KWin observer did not see the synthetic Spend window")

        def latest():
            return json.loads(state_path.read_text())

        def wait_cost(*paths, timeout=20):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if all(p.exists() for p in paths):
                    return
                time.sleep(.05)
            raise RuntimeError(f"timed out waiting for fixture markers: {[str(p) for p in paths]}")

        def wait_cost_calls_at_least(path, count, timeout=20):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if count_cost_calls(path) >= count:
                    return
                time.sleep(.05)
            raise RuntimeError(f"timed out waiting for {count} fixture calls in {path}")

        def capture_state_screenshot():
            """Spectacle active-window capture with fail-closed active-target gate."""
            # Fail closed unless the synthetic Spend PID is active — a state
            # capture of a foreign window would be non-evidence.
            focus_deadline = time.monotonic() + 5
            spend_state = json.loads(state_path.read_text())
            while time.monotonic() < focus_deadline and not active_target(spend_state, app.pid):
                if app.poll() is not None:
                    break
                time.sleep(.02)
                if state_path.exists():
                    spend_state = json.loads(state_path.read_text())
            if not active_target(spend_state, app.pid):
                raise RuntimeError("synthetic Spend was not active for state capture; no capture claimed")
            focus_js_path = scratch / "kwin-focus-state.js"
            focus_js_path.write_text(activation_script(app.pid))
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.loadScript", str(focus_js_path), focus_plugin],
                           check=True, capture_output=True, text=True)
            loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                     "org.kde.kwin.Scripting.isScriptLoaded", focus_plugin],
                                    check=True, capture_output=True, text=True).stdout.strip()
            if loaded != "true":
                raise RuntimeError("KWin did not load the synthetic Spend focus helper; no capture claimed")
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], check=True, capture_output=True)
            time.sleep(0.5)
            state_capture = scratch / f"spend-state-{args.state}.png"
            result = subprocess.run(
                ["spectacle", "--background", "--activewindow", "--nonotify",
                 "--output", str(state_capture)],
                capture_output=True, text=True, timeout=8)
            if result.returncode != 0 or not state_capture.is_file():
                raise RuntimeError(f"Spend state capture failed for {args.state}")
            kept = pathlib.Path(f"/tmp/codexbar-spend-{args.state}-wayland.png")
            try:
                kept.write_bytes(state_capture.read_bytes())
            except OSError:
                kept = state_capture
            print(f"PASS: synthetic Spend state {args.state} captured at {kept}", flush=True)
            return 0

        # State runs: fixture-only sequences, captured without any portal.
        if args.state:
            if args.state == "loading":
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not delay_cost.exists():
                    pass  # already seeded; loading = delayed cost call below
                # Cost call is blocked on the fixture; the loading label shows.
                wait_cost(cost_calls_path)
                # Give the view a beat to render the loading state.
                time.sleep(0.6)
            elif args.state == "empty":
                wait_cost(cost_done)
                time.sleep(0.6)
            elif args.state == "retained-error":
                # The fixture signals failure before exiting (see
                # spend_fixture_script), but the backend publishes the
                # retained-error view state only after the initial cost
                # scan and its per-provider retries complete — the
                # window is still "refreshing" between the first marker
                # and publication. Wait for the 3rd cost call (1 + 2
                # retries), then settle so the capture records no stale /
                # neighbouring frame. Wait for the 3rd cost call (1 + 2
                # retries), then settle before capturing, otherwise the
                # capture races the view-state update and may record the
                # earlier (e.g. partial) frame.
                wait_cost(cost_failure_done, timeout=40)
                wait_cost_calls_at_least(cost_calls_path, 3, timeout=20)
                time.sleep(1.2)
            elif args.state == "partial":
                # Fixture succeeds with historyCoverageIsEstablished=false,
                # yielding the "partial" label in the view ("· partial" on
                # the Total spend card). wait_cost(cost_done) waits for the
                # cost marker; the capture then shows partial data.
                wait_cost(cost_done)
                time.sleep(0.6)
            else:  # success
                wait_cost(cost_done)
                time.sleep(0.6)
            return capture_state_screenshot()

        # Action / inspect runs need settled data before portal consent.
        if args.action == "refresh":
            wait_cost(cost_done)
            time.sleep(0.5)
        elif args.action in ("tooltip",) or str(args.action).startswith("range-") or str(args.action).startswith("mode-"):
            wait_cost(cost_done)
            time.sleep(0.5)

        # Baseline capture: require exact active PID for Spend.
        baseline_deadline = time.monotonic() + 5
        spend_state = json.loads(state_path.read_text())
        while time.monotonic() < baseline_deadline and not active_target(spend_state, app.pid):
            time.sleep(.02)
            if state_path.exists():
                spend_state = json.loads(state_path.read_text())
        if not active_target(spend_state, app.pid):
            raise RuntimeError("synthetic Spend was not active for baseline capture; no portal request sent")
        baseline_capture = subprocess.run(
            ["spectacle", "--background", "--activewindow", "--nonotify", "--output", str(spend_capture)],
            capture_output=True, text=True, timeout=8,
        )
        if baseline_capture.returncode != 0 or not spend_capture.is_file():
            raise RuntimeError("synthetic Spend baseline capture failed; no portal request sent")
        print(f"Synthetic Spend baseline captured at {spend_capture}; verify the Spend controls before approving.", flush=True)
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

        # Reactivate only the Spend window (title "Usage & Spend"), never Settings.
        focus_js_path = scratch / "kwin-focus-target.js"
        focus_js_path.write_text(activation_script(app.pid))
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.loadScript", str(focus_js_path), focus_plugin],
                       check=True, capture_output=True, text=True)
        loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                 "org.kde.kwin.Scripting.isScriptLoaded", focus_plugin],
                                check=True, capture_output=True, text=True).stdout.strip()
        if loaded != "true":
            raise RuntimeError("KWin did not load the synthetic Spend focus helper; no input sent")
        focus_script_loaded = True
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.start"], check=True, capture_output=True)

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
            raise RuntimeError("Spend did not regain stable focus after portal consent; no input sent")

        action = WAYLAND_SPEND_ACTIONS.get(args.action, {})
        if args.action == "tooltip":
            x_fraction, y_fraction = 0.35, 0.58
            target_x, target_y = spend_point_from_geometry(
                baseline.get("target_geometry"), x_fraction, y_fraction)
        elif args.action == "refresh":
            # Refresh button sits in the status row near the Spend title.
            x_fraction, y_fraction = 0.88, 0.09
            target_x, target_y = spend_point_from_geometry(
                baseline.get("target_geometry"), x_fraction, y_fraction)
        else:
            target_x, target_y = spend_point_from_geometry(
                baseline.get("target_geometry"),
                action["x_fraction"], action["y_fraction"])
        if args.point_x is not None:
            target_x, target_y = args.point_x, args.point_y
        if not target_window_contains(baseline, target_x, target_y):
            raise RuntimeError("action coordinates are outside the synthetic Spend window; no input sent")
        print(f"Guarded Spend action '{args.action}' point: ({target_x},{target_y})", flush=True)
        baseline_preferences = json.loads(preferences.read_text())
        baseline_cost_calls = count_cost_calls(cost_calls_path)

        if args.action == "tooltip":
            # Hover only: no button press. A heatmap cell tooltip requires
            # ~0.5s dwell; capture during the dwell window.
            guarded_move(portal, app.pid, latest, target_x, target_y)
            portal.hover_settle(0.8)
            if not guard_target(latest(), app.pid, target_x, target_y):
                raise RuntimeError("tooltip hover target unstable; no capture claimed")
            after_capture = scratch / "spend-after.png"
            result = subprocess.run(
                ["spectacle", "--background", "--activewindow", "--nonotify",
                 "--output", str(after_capture)],
                capture_output=True, text=True, timeout=8)
            if result.returncode != 0 or not after_capture.is_file():
                raise RuntimeError("Spend tooltip capture failed")
            kept = pathlib.Path("/tmp/codexbar-spend-tooltip-wayland.png")
            try:
                kept.write_bytes(after_capture.read_bytes())
            except OSError:
                kept = after_capture
            print(f"PASS: synthetic Spend tooltip hover captured at {kept}", flush=True)
            return 0

        # Pointer click: range/mode/refresh.
        guarded_click(portal, app.pid, latest, target_x, target_y)

        # Refresh is asserted by a new cost-fixture call within 10s.
        if args.action == "refresh":
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if count_cost_calls(cost_calls_path) > baseline_cost_calls:
                    break
                time.sleep(.05)
            else:
                raise RuntimeError("refresh click did not re-invoke the cost fixture")
            time.sleep(0.6)
        else:
            # Range/mode are view-state only; allow a beat to re-render, then
            # verify no settings preference key changed.
            time.sleep(0.6)

        after_capture = scratch / "spend-after.png"
        focus_js_path.write_text(activation_script(app.pid))
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.loadScript", str(focus_js_path), focus_plugin],
                       check=True, capture_output=True, text=True)
        loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                 "org.kde.kwin.Scripting.isScriptLoaded", focus_plugin],
                                check=True, capture_output=True, text=True).stdout.strip()
        if loaded != "true":
            raise RuntimeError("KWin did not load the synthetic Spend focus helper; no capture claimed")
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.start"], check=True, capture_output=True)
        time.sleep(0.5)
        result = subprocess.run(
            ["spectacle", "--background", "--activewindow", "--nonotify",
             "--output", str(after_capture)],
            capture_output=True, text=True, timeout=8)
        if result.returncode != 0 or not after_capture.is_file():
            raise RuntimeError("Spend post-action capture failed")
        kept = pathlib.Path(f"/tmp/codexbar-spend-{args.action}-wayland.png")
        try:
            kept.write_bytes(after_capture.read_bytes())
        except OSError:
            kept = after_capture

        # Range/mode actions must not persist any preference change.
        after_preferences = json.loads(preferences.read_text())
        if after_preferences != baseline_preferences:
            changed = sorted(k for k in set(baseline_preferences) | set(after_preferences)
                             if baseline_preferences.get(k) != after_preferences.get(k))
            raise RuntimeError(f"Spend {args.action} unexpectedly changed preferences: {changed}")
        print(f"PASS: synthetic Spend action {args.action} captured at {kept}", flush=True)
        return 0
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
xml='<node><interface name="org.codexbar.SpendGuard"><method name="Record"><arg name="state" type="s" direction="in"/></method></interface></node>'
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
bus.register_object('/org/codexbar/SpendGuard',node.interfaces[0],method)
def acquired(_bus,_name): ready.write_text('ready')
Gio.bus_own_name_on_connection(bus,'org.codexbar.SpendGuard',Gio.BusNameOwnerFlags.NONE,acquired,None)
loop.run()
'''

KWIN_JS = r'''var TARGET_PID=__PID__, PORTAL_PID=__PORTAL_PID__, PLUGIN="__PLUGIN__", service="org.codexbar.SpendGuard", path="/org/codexbar/SpendGuard", iface="org.codexbar.SpendGuard";
function report(){var p=workspace.cursorPos,h=workspace.windowAt(p,1),top=h&&h.length?h[0]:null,a=workspace.activeWindow,w=workspace.stackingOrder,t=null;for(var i=0;i<w.length;i++)if(Number(w[i].pid)===TARGET_PID)t=w[i];var g=t?{x:Number(t.x),y:Number(t.y),width:Number(t.width),height:Number(t.height)}:null;var s={pid:a?Number(a.pid):0,active:!!(a&&Number(a.pid)===TARGET_PID),top_hit:!!(top&&Number(top.pid)===TARGET_PID),target_present:!!t,target_geometry:g?[g.x,g.y,g.width,g.height]:null,cursor:[Number(p.x),Number(p.y)],portal_active:!!(a&&Number(a.pid)===PORTAL_PID)};callDBus(service,path,iface,"Record",JSON.stringify(s));}
report();workspace.cursorPosChanged.connect(report);workspace.windowActivated.connect(report);workspace.windowAdded.connect(report);workspace.windowRemoved.connect(report);'''


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAIL CLOSED: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
