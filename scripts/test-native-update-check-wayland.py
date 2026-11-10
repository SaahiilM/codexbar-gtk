#!/usr/bin/env python3
"""Wayland evidence harness for the native update-check action (build 85).

Drives the real Gio action ``check-updates`` of the native GTK binary
against a loopback-only synthetic VERSION server, asserts the request
arrived, and verifies the visible "Update available" state — on Wayland,
with synthetic fixtures only. Never contacts a public URL.

Flow (no portal, no pointer/keyboard input needed):
  1. Fail-closed preflight: Wayland session, debug binary (the
     CODEXBAR_NATIVE_TEST_UPDATE_URL loopback override only exists under
     ``#[cfg(debug_assertions)]`` in rust-gtk/src/main.rs), D-Bus app id
     unowned, required tools present, cgroup not the wired systemd scope
     (this flow needs no portal consent, so the legacy
     app-codexbar-gtk-synthetic-wayland-test.scope does not apply).
  2. Start a 127.0.0.1-only synthetic server serving VERSION content whose
     CURRENT_PROJECT_VERSION is the repo build + 1, so the result is
     "Update available".
  3. Launch the native binary with isolated HOME/config/cache, a fake
     CLI and CODEXBAR_NATIVE_TEST_UPDATE_URL pointing at the server.
  4. Fire ``gapplication action com.steipete.CodexBarGTK check-updates``.
  5. Assert the loopback server recorded the GET /VERSION request.
  6. Assert KWin reports the synthetic app window with caption
     "Update available" and capture it via Spectacle (kept outside the
     scratch dir so evidence survives cleanup).
  7. Quit over Gio ``quit`` action; assert the app name is unowned.

Fully automated. Only the native binary build and the live desktop
session are external prerequisites; no human consent is required.
"""
import argparse
import http.server
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

APP_ID = "com.steipete.CodexBarGTK"
UPDATE_URL_ENV = "CODEXBAR_NATIVE_TEST_UPDATE_URL"
UPDATE_DIALOG_CAPTION = "Update available"
APP_WINDOW_CAPTION = "CodexBar"
WIRE_PATH = "/VERSION"
SANDBOXED_SCOPE = "app-codexbar-gtk-synthetic-wayland-test.scope"
UNSAFE_SCOPES = (
    SANDBOXED_SCOPE,
    "app-t3code-agents-",
)


def parse_version_file(path):
    values = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep:
            values[key] = value
    return values


def synthetic_version_body(version_path):
    version = parse_version_file(version_path)
    marketing = version.get("MARKETING_VERSION", "0.0.0")
    build = int(version["CURRENT_PROJECT_VERSION"]) + 1
    return f"MARKETING_VERSION={marketing}\nCURRENT_PROJECT_VERSION={build}\n".encode("ascii")


def is_loopback_update_url(url):
    """Mirror rust-gtk's is_loopback_update_url (debug-only override)."""
    return url.startswith("http://127.0.0.1:") or url.startswith("http://[::1]:")


class SyntheticVersionServer:
    """Threading loopback-only VERSION server for the harness."""

    def __init__(self, version_path):
        self.body = synthetic_version_body(version_path)
        self.requests = []
        handler_body = self.body
        handler_requests = self.requests

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != WIRE_PATH:
                    self.send_error(404)
                    return
                handler_requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(handler_body)))
                self.end_headers()
                self.wfile.write(handler_body)

            def log_message(self, fmt, *args):
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.url = f"http://127.0.0.1:{self.port}{WIRE_PATH}"

    def serve_in_thread(self):
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def name_has_owner(name):
    result = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
         "--object-path", "/org/freedesktop/DBus",
         "--method", "org.freedesktop.DBus.NameHasOwner", name],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"NameHasOwner failed for {name}: {result.stderr.strip()}")
    return result.stdout.strip() == "(true,)"


def activation_script(expected_pid, caption_fragment):
    """KWin helper: reactivate the synthetic app window, then record state.

    Window lookup is by PID only (caption match optional): the app may
    host the settings window plus the update dialog at different times,
    so the report always attaches the exact-PID window's geometry plus
    its caption; the caller decides whether the caption matches the
    expected update-dialog fragment.
    """
    expected_pid = int(expected_pid)
    fragment = json.dumps(caption_fragment)
    return f'''var TARGET_PID={expected_pid}, FRAGMENT={fragment};
var target=null;
var windows=workspace.stackingOrder;
for(var i=0;i<windows.length;i++){{
  if(Number(windows[i].pid)===TARGET_PID && String(windows[i].caption).indexOf(FRAGMENT)>=0){{
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
var caption=targetState?String(targetState.caption):"";
var state={{pid:a?Number(a.pid):0,active:!!(a&&Number(a.pid)===TARGET_PID),top_hit:!!(top&&Number(top.pid)===TARGET_PID),target_present:!!targetState,caption:caption,target_geometry:geometry?[geometry.x,geometry.y,geometry.width,geometry.height]:null,cursor:[Number(p.x),Number(p.y)],portal_active:false}};
callDBus("org.codexbar.U05.Guard","/org/codexbar/U05/Guard","org.codexbar.U05.Guard","Record",JSON.stringify(state));
'''


KWIN_JS = r'''var TARGET_PID=__PID__, PLUGIN="__PLUGIN__", service="org.codexbar.U05.Guard", path="/org/codexbar/U05/Guard", iface="org.codexbar.U05.Guard";
function report(){var p=workspace.cursorPos,h=workspace.windowAt(p,1),top=h&&h.length?h[0]:null,a=workspace.activeWindow,w=workspace.stackingOrder,t=null;for(var i=0;i<w.length;i++)if(Number(w[i].pid)===TARGET_PID)t=w[i];var g=t?{x:Number(t.x),y:Number(t.y),width:Number(t.width),height:Number(t.height)}:null;var c=t?String(t.caption):"";var s={pid:a?Number(a.pid):0,active:!!(a&&Number(a.pid)===TARGET_PID),top_hit:!!(top&&Number(top.pid)===TARGET_PID),target_present:!!t,caption:c,target_geometry:g?[g.x,g.y,g.width,g.height]:null,cursor:[Number(p.x),Number(p.y)],portal_active:false};callDBus(service,path,iface,"Record",JSON.stringify(s));}
report();workspace.cursorPosChanged.connect(report);workspace.windowActivated.connect(report);workspace.windowAdded.connect(report);workspace.windowRemoved.connect(report);'''

OBSERVER_PY = r'''import json, pathlib, sys, time
from gi.repository import Gio, GLib
path=pathlib.Path(sys.argv[1]); ready=pathlib.Path(sys.argv[2]); loop=GLib.MainLoop()
xml='<node><interface name="org.codexbar.U05.Guard"><method name="Record"><arg name="state" type="s" direction="in"/></method></interface></node>'
node=Gio.DBusNodeInfo.new_for_xml(xml); bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
def method(_c,_s,_p,_i,_m,params,inv):
    (raw,)=params.unpack(); state=json.loads(raw); state['received']=time.monotonic()
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(state)); tmp.replace(path)
    inv.return_value(GLib.Variant('()',()))
bus.register_object('/org/codexbar/U05/Guard',node.interfaces[0],method)
def acquired(_bus,_name): ready.write_text('ready')
Gio.bus_own_name_on_connection(bus,'org.codexbar.U05.Guard',Gio.BusNameOwnerFlags.NONE,acquired,None)
loop.run()
'''


def wait_for_file(path, description, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pathlib.Path(path).exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {description}")


def wait_for_update_dialog(state_path, app_pid, timeout=15):
    """Poll the observer state until the exact-PID window shows the dialog."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state.get("pid") == app_pid and UPDATE_DIALOG_CAPTION in (state.get("caption") or ""):
                return state
        time.sleep(0.05)
    raise RuntimeError(
        f"timed out waiting for KWin to report {UPDATE_DIALOG_CAPTION!r} "
        f"caption on synthetic app PID {app_pid}"
    )


def capture_active_window(output):
    result = subprocess.run(
        ["spectacle", "--background", "--activewindow", "--nonotify",
         "--output", str(output)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or not pathlib.Path(output).is_file():
        raise RuntimeError(f"Spectacle capture failed: {result.stderr.strip()[-500:]}")
    return pathlib.Path(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--version-file", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1] / "VERSION")
    parser.add_argument("--inspect-only", action="store_true",
                        help="launch and capture the synthetic app, then quit without firing the action")
    args = parser.parse_args()

    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("XDG_RUNTIME_DIR"):
        parser.error("run inside the intended Wayland session")
    if os.environ.get("XDG_SESSION_TYPE") not in (None, "wayland"):
        parser.error("XDG_SESSION_TYPE is not Wayland")
    if not args.binary.is_file() or not os.access(args.binary, os.X_OK):
        parser.error("--binary must name an executable native GTK build")
    for tool in ("gapplication", "gdbus", "qdbus6", "spectacle"):
        if shutil.which(tool) is None:
            parser.error(f"required tool missing: {tool}")
    cgroup = pathlib.Path("/proc/self/cgroup").read_text()
    for scope in UNSAFE_SCOPES:
        if scope in cgroup:
            parser.error(f"refusing to run inside {scope!r}; this harness does not need the portal scope")
    if not args.version_file.is_file():
        parser.error("--version-file must name the repo VERSION file")

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="codexbar-wayland-update-check-"))
    scratch.chmod(0o700)
    app = observer = None
    server = None
    focus_plugin = "codexbar_update_focus_" + str(int(time.time() * 1000))[-12:]
    kwin_plugin = "codexbar_update_guard_" + str(int(time.time() * 1000))[-12:]
    focus_script_loaded = False
    try:
        if name_has_owner(APP_ID):
            raise RuntimeError("native application ID already owned; refusing to target an existing app")
        server = SyntheticVersionServer(args.version_file)
        if not is_loopback_update_url(server.url):
            raise RuntimeError("synthetic update URL is not loopback; refusing")
        server.serve_in_thread()

        home = scratch / "home"
        (home / ".config" / "codexbar-gtk").mkdir(parents=True, mode=0o700)
        fake = scratch / "codexbar"
        fake.write_text("#!/bin/sh\ncase \"${1-}\" in --version) echo 'CodexBar synthetic fixture 0.82.0';; *) echo '[]';; esac\n")
        fake.chmod(0o700)

        env = os.environ.copy()
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
                   CODEXBAR_CLI=str(fake), GTK_A11Y="none", GTK_USE_PORTAL="0",
                   GDK_BACKEND="wayland", GSK_RENDERER="cairo",
                   **{UPDATE_URL_ENV: server.url})
        env.pop("CODEXBAR_RUST_CORE", None)

        app_log = (scratch / "app.log").open("wb")
        app = subprocess.Popen([str(args.binary), "--settings"], env=env,
                               stdout=app_log, stderr=subprocess.STDOUT,
                               start_new_session=True)

        state_path = scratch / "kwin-state.json"
        observer_ready = scratch / "observer-ready"
        observer_py = scratch / "observer.py"
        observer_py.write_text(OBSERVER_PY)
        observer = subprocess.Popen([sys.executable, str(observer_py), str(state_path),
                                     str(observer_ready)],
                                    env=os.environ.copy(), stdout=subprocess.DEVNULL,
                                    stderr=(scratch / "observer.log").open("wb"),
                                    start_new_session=True)
        wait_for_file(observer_ready, "KWin guard D-Bus observer", timeout=5)
        js_path = scratch / "kwin-observer.js"
        js_path.write_text(KWIN_JS.replace("__PID__", str(app.pid)).replace("__PLUGIN__", kwin_plugin))
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

        baseline_state = json.loads(state_path.read_text())
        if baseline_state.get("pid") != app.pid or not baseline_state.get("active"):
            # Reactivate the exact synthetic window for the baseline capture.
            focus_js_path = scratch / "kwin-focus-target.js"
            focus_js_path.write_text(activation_script(app.pid, APP_WINDOW_CAPTION))
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.loadScript", str(focus_js_path), focus_plugin],
                           check=True, capture_output=True, text=True)
            loaded = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                     "org.kde.kwin.Scripting.isScriptLoaded", focus_plugin],
                                    check=True, capture_output=True, text=True).stdout.strip()
            if loaded != "true":
                raise RuntimeError("KWin did not load the synthetic focus helper")
            focus_script_loaded = True
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], check=True, capture_output=True)
            time.sleep(0.5)

        settings_capture = scratch / "settings-before.png"
        capture_active_window(settings_capture)
        print(f"Synthetic Settings baseline captured at {settings_capture}", flush=True)
        if args.inspect_only:
            print("Inspection-only mode; no action fired, no request made.", flush=True)
            return 0

        print("Firing Gio update-check action on the synthetic app...", flush=True)
        fired = subprocess.run(
            ["gapplication", "action", APP_ID, "check-updates"],
            capture_output=True, text=True, timeout=10,
        )
        if fired.returncode != 0:
            raise RuntimeError(
                f"check-updates action failed: {(fired.stderr or fired.stdout).strip()[-500:]}"
            )

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and WIRE_PATH not in server.requests:
            time.sleep(0.05)
        if WIRE_PATH not in server.requests:
            raise RuntimeError("loopback synthetic version server recorded no GET /VERSION request")
        print(f"PASS: loopback server recorded {len(server.requests)} GET {WIRE_PATH} request(s)", flush=True)

        state = wait_for_update_dialog(state_path, app.pid)
        print(f"PASS: KWin reports caption {state.get('caption')!r} on synthetic PID {app.pid}", flush=True)

        result_capture = scratch / "update-result.png"
        capture_active_window(result_capture)
        kept = pathlib.Path("/tmp/codexbar-wayland-update-result.png")
        try:
            kept.write_bytes(result_capture.read_bytes())
            print(f"Update result capture kept at {kept}", flush=True)
        except OSError:
            print(f"Update result capture at {result_capture}", flush=True)

        subprocess.run(["gapplication", "action", APP_ID, "quit"],
                       capture_output=True, text=True, timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and app.poll() is None:
            time.sleep(0.05)
        if app.poll() is None:
            raise RuntimeError("synthetic app did not quit after the Gio quit action")
        if name_has_owner(APP_ID):
            raise RuntimeError("native application ID still owned after quit")
        print("PASS: update-check action reached loopback server; visible Update available state verified", flush=True)
        return 0
    finally:
        if server:
            server.stop()
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
        if os.environ.get("KEEP_WAYLAND_TEST_TMP") == "1":
            print(f"Synthetic test diagnostics kept at {scratch}", file=sys.stderr, flush=True)
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAIL CLOSED: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
