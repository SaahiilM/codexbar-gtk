import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROW_HELPER_SPEC = importlib.util.spec_from_file_location(
    "native_atspi_rows", pathlib.Path(__file__).resolve().parents[1] /
    "scripts/native_atspi_rows.py")
ROW_HELPER = importlib.util.module_from_spec(ROW_HELPER_SPEC)
ROW_HELPER_SPEC.loader.exec_module(ROW_HELPER)


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/test-native-wayland-isolated.py"
SPEC = importlib.util.spec_from_file_location("native_wayland_isolated", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeWaylandIsolatedHarnessTests(unittest.TestCase):
    def test_failed_atspi_probe_and_capture_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "AT-SPI missing probe failed"):
            MODULE.atspi_probe(sys.executable, "missing", 1, "")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            screenshooter = root / "screenshooter"
            screenshooter.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            screenshooter.chmod(0o700)
            with self.assertRaisesRegex(RuntimeError, "private Weston screenshot failed"):
                MODULE.capture_screen(screenshooter, {}, root / "capture", root / "out.png")

    def test_runner_failure_exits_nonzero_and_retains_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            artifact_dir = root / "artifacts"
            argv = [str(SCRIPT), "--inside-private-bus", "--binary",
                    str(root / "missing-native-binary"), "--artifact-dir", str(artifact_dir)]
            with mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main(), 1)
            failure = json.loads((artifact_dir / "failure-evidence.json").read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertIn("not executable", failure["message"])

    @unittest.skipUnless(pathlib.Path("/proc").is_dir(), "requires Linux procfs")
    def test_outer_timeout_kills_owned_child_and_grandchild_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            child_pid = root / "child.pid"
            grandchild_pid = root / "grandchild.pid"
            child_code = (
                "import os,signal,subprocess,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "g=subprocess.Popen([sys.executable,'-c',"
                "'import os,signal,sys,time; open(sys.argv[1],\\\"w\\\").write(str(os.getpid())); "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)',sys.argv[2]]); "
                "open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(60)"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                MODULE.run_owned_process_group(
                    [sys.executable, "-c", child_code, str(child_pid), str(grandchild_pid)],
                    env=dict(os.environ), timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertTrue(child_pid.exists())
            self.assertTrue(grandchild_pid.exists())
            for pid_file in (child_pid, grandchild_pid):
                pid = int(pid_file.read_text(encoding="utf-8"))
                proc_stat = pathlib.Path(f"/proc/{pid}/stat")
                if proc_stat.exists():
                    # A zombie is dead; it cannot continue running the fixture.
                    self.assertEqual(proc_stat.read_text(encoding="utf-8").split()[2], "Z")

    def test_client_environment_drops_host_display_and_bus_handles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            env = MODULE.sanitized_environment({
                "DISPLAY": ":42", "WAYLAND_DISPLAY": "wayland-0",
                "WAYLAND_SOCKET": "13", "XAUTHORITY": "/host/auth",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/host/bus",
                "DBUS_STARTER_ADDRESS": "unix:path=/host/starter-bus",
                "DBUS_STARTER_BUS_TYPE": "session",
                "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/host/system-bus",
                "AT_SPI_BUS_ADDRESS": "unix:path=/host/a11y",
                "XDG_DESKTOP_PORTAL_DIR": "/run/host/portal",
                "PORTAL_BUS_ADDRESS": "unix:path=/host/portal-bus",
                "GIO_LAUNCHED_DESKTOP_FILE_PID": "12345",
                "SESSION_MANAGER": "local/host:@/tmp/session",
                "XDG_RUNTIME_DIR": "/run/user/1000", "GDK_BACKEND": "x11",
                "GSK_RENDERER": "gl", "GTK_USE_PORTAL": "1",
            }, root / "home", root / "runtime", "wayland-private",
               root / "fake-codexbar", "unix:path=/private/session-bus", root / "diagnostics")
            for key in ("DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY", "DBUS_SYSTEM_BUS_ADDRESS",
                        "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE", "AT_SPI_BUS_ADDRESS"):
                self.assertNotIn(key, env)
            self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-private")
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/private/session-bus")
            self.assertEqual(env["XDG_RUNTIME_DIR"], str(root / "runtime"))
            self.assertEqual(env["GDK_BACKEND"], "wayland")
            self.assertEqual(env["GSK_RENDERER"], "cairo")
            self.assertEqual(env["GTK_A11Y"], "atspi")
            self.assertEqual(env["GTK_USE_PORTAL"], "0")

    def test_private_bus_wrapper_does_not_inherit_host_session_handles(self):
        env = MODULE.private_bus_environment({
            "DISPLAY": ":42", "WAYLAND_DISPLAY": "wayland-0",
            "WAYLAND_SOCKET": "13", "XAUTHORITY": "/host/auth",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/host/bus",
            "DBUS_STARTER_ADDRESS": "unix:path=/host/starter-bus",
            "DBUS_STARTER_BUS_TYPE": "session",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/host/system-bus",
            "AT_SPI_BUS_ADDRESS": "unix:path=/host/a11y",
            "XDG_RUNTIME_DIR": "/run/user/1000", "PATH": "/usr/bin",
        })
        for key in MODULE.HOST_SESSION_KEYS:
            self.assertNotIn(key, env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_synthetic_cli_produces_valid_fixture_payloads_without_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cli = root / "fake-codexbar"
            cli.write_text(MODULE.fake_cli_text(), encoding="utf-8")
            cli.chmod(0o700)
            log = root / "calls.log"
            env = dict(os.environ, NATIVE_CLI_LOG=str(log))
            usage = subprocess.run([str(cli), "usage"], env=env, capture_output=True,
                                   text=True, check=True)
            cost = subprocess.run([str(cli), "cost"], env=env, capture_output=True,
                                  text=True, check=True)
            self.assertEqual(json.loads(usage.stdout)[0]["provider"], "codex")
            self.assertEqual(json.loads(cost.stdout)[0]["totalCost"], 12.5)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ["usage", "cost"])
            self.assertNotIn("api_key", MODULE.fake_cli_text().lower())
            self.assertNotIn("oauth", MODULE.fake_cli_text().lower())
            self.assertNotIn("--url", MODULE.fake_cli_text().lower())

    def test_sessions_fixture_modes_produce_success_empty_delay_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cli = root / "fake-codexbar"
            cli.write_text(MODULE.fake_cli_text(), encoding="utf-8")
            cli.chmod(0o700)
            mode_file = root / "sessions-mode"
            calls = root / "calls.log"
            env = dict(os.environ, NATIVE_CLI_LOG=str(calls),
                       NATIVE_SESSIONS_MODE_FILE=str(mode_file))
            expected = {
                "success": (0, '"id":"fixture-session"'),
                "empty": (0, "[]"),
                "error": (7, "synthetic session scan failure"),
            }
            for mode, (return_code, marker) in expected.items():
                with self.subTest(mode=mode):
                    mode_file.write_text(mode + "\n", encoding="utf-8")
                    result = subprocess.run([str(cli), "sessions", "--json-v2"], env=env,
                                            capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, return_code)
                    self.assertIn(marker, result.stdout + result.stderr)
            mode_file.write_text("loading\n", encoding="utf-8")
            result = subprocess.run([str(cli), "sessions", "--json-v2"], env=env,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"id":"fixture-session"', result.stdout)
            call_lines = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual([line for line in call_lines if line == "sessions --json-v2"],
                             ["sessions --json-v2"] * 4)
            self.assertEqual([line for line in call_lines if line.endswith("-done")], [
                "sessions-fixture-success-done", "sessions-fixture-empty-done",
                "sessions-fixture-error-done", "sessions-fixture-loading-done"])

    def test_sessions_state_captures_follow_visible_assertions_and_daily_return_precedes_route(self):
        source = SCRIPT.read_text(encoding="utf-8")
        sessions = source.split('gaction("page", "\'sessions\'")', 1)[1]
        self.assertIn('if mode in ("success", "empty", "error"):', sessions)
        self.assertIn('f"capture-sessions-{mode}"', sessions)
        self.assertIn('artifact_dir / f"sessions-{mode}.png"', sessions)
        self.assertLess(sessions.index("visible = wait_visible_text"),
                        sessions.index('if mode in ("success", "empty", "error")'))
        self.assertLess(sessions.index('f"sessions-fixture-{mode}-done"'),
                        sessions.index('if mode in ("success", "empty", "error")'))
        before_sessions_route = source.split('gaction("page", "\'sessions\'")', 1)[0]
        self.assertIn("heatmap Daily final return pressed state", before_sessions_route)
        self.assertIn("final_return", before_sessions_route)

    def test_hooks_fixture_tracks_exact_enable_disable_cli_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cli = root / "fake-codexbar"
            cli.write_text(MODULE.fake_cli_text(), encoding="utf-8")
            cli.chmod(0o700)
            state = root / "hooks-enabled"
            state.write_text("true\n", encoding="utf-8")
            calls = root / "calls.log"
            env = dict(os.environ, NATIVE_CLI_LOG=str(calls),
                       NATIVE_HOOKS_STATE_FILE=str(state))
            before = subprocess.run([str(cli), "hooks", "list", "--format", "json"],
                                    env=env, capture_output=True, text=True, check=True)
            disabled = subprocess.run([str(cli), "hooks", "disable"], env=env,
                                      capture_output=True, text=True, check=True)
            after = subprocess.run([str(cli), "hooks", "list", "--format", "json"],
                                   env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(before.stdout), {"enabled": True, "events": []})
            self.assertEqual(json.loads(after.stdout), {"enabled": False, "events": []})
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), [
                "hooks list --format json", "hooks disable", "hooks list --format json"])
            self.assertEqual(disabled.returncode, 0)

    def test_visible_actionable_control_identity_ignores_same_name_label_nodes(self):
        row = {"name": "Refresh when the panel opens", "role": "check box", "pid": 123,
               "identity": "123:app[0]/tab[1]:check box:Refresh when the panel opens",
               "path": "app[0]/window:CodexBar Settings/panel:General/panel[0]",
               "showing": True, "visible": True, "action_count": 1}
        label = {"name": row["name"], "role": "label", "pid": 123,
                 "identity": "123:app[0]/label:Refresh when the panel opens",
                 "path": "app[0]/window:CodexBar Settings/panel:General/panel[0]",
                 "showing": True, "visible": True, "action_count": 0}
        item = {"name": row["name"], "role": "list item", "pid": 123,
                "identity": "123:app[0]/item:Refresh when the panel opens",
                "path": "app[0]/window:CodexBar Settings/panel:General/panel[0]",
                "showing": True, "visible": True, "action_count": 0}
        stale = dict(row, identity=row["identity"] + "/stale",
                     path="app[0]/window:CodexBar Settings/panel:Notifications/panel[0]")
        with mock.patch.object(MODULE, "atspi_probe",
                               return_value={"matches": [label, row, item, stale]}):
            found = MODULE.wait_visible_control(
                sys.executable, 123, row["name"], ("check box", "switch"),
                "General", timeout=0.1)
            self.assertEqual(found["identity"], row["identity"])

        duplicate = dict(row, identity=row["identity"] + "/duplicate")
        with mock.patch.object(MODULE, "atspi_probe",
                               return_value={"matches": [row, duplicate]}):
            with self.assertRaisesRegex(RuntimeError, "ambiguous visible actionable AT-SPI control"):
                MODULE.wait_visible_control(
                    sys.executable, 123, row["name"], ("check box", "switch"),
                    "General", timeout=0.1)

    def test_accessible_activation_can_be_bound_to_observed_identity(self):
        identity = "123:app[0]/tab[1]:check box:fixture"
        with mock.patch.object(MODULE, "atspi_probe", return_value={"ok": True}) as probe:
            self.assertEqual(MODULE.activate_accessible(sys.executable, 123, "fixture", identity),
                             {"ok": True})
            probe.assert_called_once_with(sys.executable, "activate", 123, "fixture", identity)

    def test_visible_action_requires_one_enabled_same_process_actionable_node(self):
        row = {"name": "Export…", "role": "button", "pid": 123,
               "identity": "123:app[0]/button:Export", "showing": True,
               "visible": True, "states": ["sensitive"], "action_count": 1,
               "path": "app[0]/panel[0]:Advanced/button[0]"}
        with mock.patch.object(MODULE, "atspi_probe", return_value={"matches": [row]}):
            self.assertEqual(MODULE.wait_visible_action(
                sys.executable, 123, "Export…", ("button",), timeout=0.1,
                context="Advanced"), row)
        for invalid in (dict(row, pid=456), dict(row, visible=False),
                        dict(row, states=[]), dict(row, action_count=0)):
            with self.subTest(invalid=invalid), mock.patch.object(
                    MODULE, "atspi_probe", return_value={"matches": [invalid]}):
                with self.assertRaisesRegex(RuntimeError, "timed out waiting for visible action"):
                    MODULE.wait_visible_action(
                        sys.executable, 123, "Export…", ("button",), timeout=0.05,
                        context="Advanced")
        duplicate = dict(row, identity=row["identity"] + "/duplicate")
        with mock.patch.object(MODULE, "atspi_probe", return_value={"matches": [row, duplicate]}):
            with self.assertRaisesRegex(RuntimeError, "ambiguous visible action"):
                MODULE.wait_visible_action(
                    sys.executable, 123, "Export…", ("button",), timeout=0.1,
                    context="Advanced")

    def test_advanced_scenario_is_opt_in_and_chooser_selection_is_exact(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('choices=("matrix", "advanced"), default="matrix"', source)
        self.assertIn('if args.scenario == "advanced":\n                run_advanced_preferences(', source)
        helper = (SCRIPT.parent / "select-native-file-chooser.py").read_text(encoding="utf-8")
        self.assertIn("row_has_exact_filename(child, basename, app_pid)", helper)
        self.assertIn('child.get_process_id() == app_pid', helper)
        self.assertIn('selection.select_child(index)', helper)
        self.assertIn('read_text(location_entry) == path', helper)
        self.assertIn("exact_selected_row_records", helper)
        self.assertNotIn('basename in (child.get_name() or "")', helper)
        self.assertNotIn('xdotool', helper)
        selector = helper.split("def select_file_row", 1)[1].split("def save_default", 1)[0]
        self.assertNotIn("Ctrl+L", selector)

    def test_selected_chooser_row_requires_exact_visible_same_pid_cell_and_unique_identity(self):
        def row(identity="row-1", row_pid=123, cell_name="synthetic.json",
                cell_pid=123, row_states=("selected", "showing", "sensitive"),
                cell_states=("showing", "sensitive")):
            return {"identity": identity, "role": "table row", "pid": row_pid,
                    "states": row_states, "descendants": [{
                        "role": "label", "name": cell_name, "text": None,
                        "pid": cell_pid, "states": cell_states}]}

        exact = row()
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            [exact], "synthetic.json", 123), [exact])
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            [row(cell_name="prefix-synthetic.json")], "synthetic.json", 123), [])
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            [row(cell_pid=456)], "synthetic.json", 123), [])
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            [row(row_pid=456)], "synthetic.json", 123), [])
        duplicate_controls = [exact, row(identity="row-2")]
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            duplicate_controls, "synthetic.json", 123), duplicate_controls)
        duplicate_identity = [exact, row(identity="row-1")]
        self.assertEqual(ROW_HELPER.exact_selected_row_records(
            duplicate_identity, "synthetic.json", 123), [])

    def test_visible_text_requires_exact_pid_and_unique_identity(self):
        row = {"name": "1 running of 1 known sessions", "pid": 123,
               "identity": "123:app[0]/label[1]:label:session status",
               "showing": True, "visible": True}
        with mock.patch.object(MODULE, "atspi_probe", return_value={"matches": [row]}):
            self.assertEqual(MODULE.wait_visible_text(
                sys.executable, 123, "running of", timeout=0.1), row)

        duplicate = dict(row, identity=row["identity"] + "/duplicate")
        with mock.patch.object(MODULE, "atspi_probe", return_value={"matches": [row, duplicate]}):
            with self.assertRaisesRegex(RuntimeError, "ambiguous visible AT-SPI text"):
                MODULE.wait_visible_text(sys.executable, 123, "running of", timeout=0.1)

        wrong_pid = dict(row, pid=456)
        with mock.patch.object(MODULE, "atspi_probe", return_value={"matches": [wrong_pid]}):
            with self.assertRaisesRegex(RuntimeError, "timed out waiting for visible AT-SPI text"):
                MODULE.wait_visible_text(sys.executable, 123, "running of", timeout=0.1)

    def test_heatmap_state_requires_one_unique_pressed_mode(self):
        rows = {
            "Daily": [{"name": "Daily", "role": "toggle button", "pid": 123,
                       "identity": "123:daily", "states": ["pressed"]}],
            "Weekly": [{"name": "Weekly", "role": "toggle button", "pid": 123,
                        "identity": "123:weekly", "states": []}],
            "Cumulative": [{"name": "Cumulative", "role": "toggle button", "pid": 123,
                            "identity": "123:cumulative", "states": []}],
        }
        with mock.patch.object(MODULE, "atspi_probe",
                               side_effect=lambda _python, _mode, _pid, name: {"matches": rows[name]}):
            self.assertEqual(MODULE.selected_heatmap_mode(sys.executable, 123)["name"], "Daily")
            rows["Weekly"][0]["states"] = ["pressed"]
            with self.assertRaisesRegex(RuntimeError, "exactly one pressed heatmap mode"):
                MODULE.selected_heatmap_mode(sys.executable, 123)

    def test_atspi_and_action_evidence_never_claims_physical_input(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("actions.do_action(0)", MODULE.AT_SPI_PROBE)
        self.assertIn('"kind": "GAction"', source)
        self.assertIn("AT-SPI and GAction evidence is not physical pointer/keyboard input.", source)
        self.assertNotIn("NotifyPointer", source)
        self.assertNotIn("NotifyKeyboard", source)
        self.assertNotIn("wtype", source)

    def test_private_capture_requires_weston_debug_screenshooter_and_nonempty_png(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"--debug"', source)
        self.assertIn('"--backend=headless"', source)
        self.assertIn('"--renderer=pixman"', source)
        self.assertIn('"--shell=desktop-shell.so"', source)
        self.assertIn('evidence["private_runtime_permissions"]', source)
        self.assertIn('evidence["private_wayland_socket_permissions"]', source)
        self.assertIn('evidence["cleanup"]["private_dbus_socket_removed"]', source)
        self.assertIn("client={desktop_client}", source)
        self.assertIn("weston-screenshooter", source)
        self.assertIn("candidates[0].stat().st_size < 1000", source)

    def test_preferences_seed_is_one_synthetic_preference_and_actions_are_allowlisted(self):
        self.assertEqual(MODULE.SETTING_KEY, "refreshAllProvidersOnMenuOpen")
        self.assertEqual(MODULE.SETTING_LABEL, "Refresh when the panel opens")
        self.assertEqual(MODULE.SPEND_LABEL, "7 days")
        self.assertEqual(MODULE.APP_ID, "com.steipete.CodexBarGTK")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"pressed" in row["states"]', source)
        self.assertIn('evidence["persisted_settings_json"]', source)


if __name__ == "__main__":
    unittest.main()
