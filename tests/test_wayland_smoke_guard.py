import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/test-native-settings-wayland.py"
SPEC = importlib.util.spec_from_file_location("wayland_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WaylandGuardTests(unittest.TestCase):
    def snapshot(self, **overrides):
        state = {
            "received": 100.0,
            "pid": 4242,
            "active": True,
            "top_hit": True,
            "cursor": [810, 315],
        }
        state.update(overrides)
        return state

    def geometry_fixture(self):
        kwin = {
            "pid": 4242, "active": True, "target_present": True,
            "active_window_pid": 4242, "active_window_title": "CodexBar Settings",
            "target_window_pid": 4242, "target_window_title": "CodexBar Settings",
            "target_window_count": 1, "target_geometry": [364, 149, 1000, 740],
        }
        raw = {
            "application": "codexbar-gtk-synthetic-wayland-test", "pid": 4242,
            "requested_label": "Notifications", "expected_roles": ["page tab"],
            "application_bus_name": "org.example.synthetic",
            "desktop_scale_factors": [1],
            "top_level_windows": [{
                "name": "CodexBar Settings", "role": "frame", "visible": True,
                "showing": True, "screen": [364, 149, 1000, 740],
                "window": [0, 0, 1000, 740], "bus_name": "org.example.synthetic",
                "object_path": "/org/example/window",
            }],
            "controls": [{
                "name": "Notifications", "role": "page tab", "visible": True,
                "showing": True, "screen": [500, 300, 80, 40],
                "window": [136, 151, 80, 40], "bus_name": "org.example.synthetic",
                "object_path": "/org/example/tab",
            }],
        }
        return raw, kwin

    def test_coordinate_geometry_accepts_verified_global_frame(self):
        raw, kwin = self.geometry_fixture()
        result = MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                                    "codexbar-gtk-synthetic-wayland-test")
        self.assertEqual(result["coordinate_space"], "screen")
        self.assertEqual(result["control_bounds"], [500, 300, 80, 40])
        self.assertEqual(result["calculated_point"], [540, 320])

    def test_coordinate_geometry_accepts_verified_window_local_translation(self):
        raw, kwin = self.geometry_fixture()
        raw["top_level_windows"][0]["screen"] = [0, 0, 1000, 740]
        raw["controls"][0]["screen"] = [0, 0, 80, 40]
        result = MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                                    "codexbar-gtk-synthetic-wayland-test")
        self.assertEqual(result["coordinate_space"], "window-local-translated")
        self.assertEqual(result["control_bounds"], [500, 300, 80, 40])
        self.assertEqual(result["calculated_point"], [540, 320])

    def test_coordinate_geometry_fails_closed_for_unverified_or_unsafe_evidence(self):
        raw0, kwin0 = self.geometry_fixture()
        mutations = (
            (lambda raw, kwin: kwin.update(target_window_pid=99), "wrong PID"),
            (lambda raw, kwin: kwin.update(target_window_count=2), "multiple KWin windows"),
            (lambda raw, kwin: raw["top_level_windows"][0].update(showing=False), "hidden frame"),
            (lambda raw, kwin: kwin.update(active_window_title="Other window"), "wrong focused window"),
            (lambda raw, kwin: raw.update(application="other-app"), "wrong app name"),
            (lambda raw, kwin: raw.update(expected_roles=["button"]), "wrong role"),
            (lambda raw, kwin: raw["controls"][0].update(visible=False), "hidden control"),
            (lambda raw, kwin: (raw["top_level_windows"][0].update(window=[0, 0, 999, 740]),
                                raw["top_level_windows"][0].update(screen=[0, 0, 1000, 740])), "frame size"),
            (lambda raw, kwin: raw.update(desktop_scale_factors=[2]), "unsupported scale"),
            (lambda raw, kwin: (raw["top_level_windows"][0].update(screen=[0, 0, 1000, 740]),
                                raw["controls"][0].update(window=[990, 720, 20, 20])), "outside"),
            (lambda raw, kwin: raw["top_level_windows"][0].update(screen=[-1, -1, -1, -1], window=[-1, -1, -1, -1]), "sentinel"),
            (lambda raw, kwin: raw["controls"].append({**raw["controls"][0], "object_path": "/org/example/tab2"}), "ambiguous"),
            (lambda raw, kwin: raw["top_level_windows"].append({**raw["top_level_windows"][0], "object_path": "/org/example/window2"}), "multiple frames"),
            (lambda raw, kwin: raw["top_level_windows"][0].update(screen=[10, 10, 1000, 740]), "unverified translation"),
        )
        for mutate, label in mutations:
            with self.subTest(case=label):
                raw, kwin = json.loads(json.dumps(raw0)), json.loads(json.dumps(kwin0))
                mutate(raw, kwin)
                with self.assertRaises(MODULE.GeometryResolutionError):
                    MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                                        "codexbar-gtk-synthetic-wayland-test")

    def test_atspi_identity_collapses_only_same_bus_and_path(self):
        raw, kwin = self.geometry_fixture()
        raw["controls"].append(dict(raw["controls"][0]))
        result = MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                                    "codexbar-gtk-synthetic-wayland-test")
        self.assertEqual(result["calculated_point"], [540, 320])
        raw["controls"].append({**raw["controls"][0], "bus_name": "org.example.other"})
        with self.assertRaises(MODULE.GeometryResolutionError):
            MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                               "codexbar-gtk-synthetic-wayland-test")

    def test_distinct_overlapping_checkboxes_remain_ambiguous(self):
        raw, kwin = self.geometry_fixture()
        raw["expected_roles"] = ["check box"]
        raw["requested_label"] = "Notifications"
        raw["controls"] = [{**raw["controls"][0], "role": "check box"},
                            {**raw["controls"][0], "role": "check box",
                             "object_path": "/org/example/checkbox2"}]
        with self.assertRaises(MODULE.GeometryResolutionError):
            MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                               "codexbar-gtk-synthetic-wayland-test")

    def test_atspi_identity_rejects_missing_invalid_or_wrong_application(self):
        raw0, kwin0 = self.geometry_fixture()
        for field, value in (("object_path", None), ("object_path", "relative/path"),
                             ("bus_name", "org.example.other")):
            raw, kwin = json.loads(json.dumps(raw0)), json.loads(json.dumps(kwin0))
            raw["controls"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(MODULE.GeometryResolutionError):
                MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                                   "codexbar-gtk-synthetic-wayland-test")

    def test_atspi_same_identity_with_contradictory_record_is_rejected(self):
        raw, kwin = self.geometry_fixture()
        raw["controls"].append({**raw["controls"][0], "window": [137, 151, 80, 40]})
        with self.assertRaises(MODULE.GeometryResolutionError):
            MODULE.resolve_coordinate_geometry(raw, kwin, 4242,
                                               "codexbar-gtk-synthetic-wayland-test")

    def test_generated_probe_terminates_cycle_and_collapses_repeated_remote_reference(self):
        raw, kwin = self.geometry_fixture()

        class App:
            bus_name = "org.example.synthetic"
            path = "/org/example/app"
            def __init__(self): self.children = []
            def get_name(self): return "codexbar-gtk-synthetic-wayland-test"
            def get_process_id(self): return 4242
            def get_role_name(self): return "application"
            def get_state_set(self): return State()
            def get_component_iface(self): return None
            def get_child_count(self): return len(self.children)
            def get_child_at_index(self, index): return self.children[index]

        class State:
            def contains(self, _state): return True

        class Component:
            def __init__(self, values): self.values = values
            def get_extents(self, coord):
                return types.SimpleNamespace(x=self.values[coord][0], y=self.values[coord][1],
                                             width=self.values[coord][2], height=self.values[coord][3])

        class Node:
            def __init__(self, name, role, path, values=None):
                self.app, self.path = app, path
                self.name, self.role, self.children = name, role, []
                self.component = Component(values or {})
            def get_name(self): return self.name
            def get_role_name(self): return self.role
            def get_state_set(self): return State()
            def get_component_iface(self): return self.component
            def get_child_count(self): return len(self.children)
            def get_child_at_index(self, index): return self.children[index]

        app = App()
        screen, window = "SCREEN", "WINDOW"
        frame = Node("CodexBar Settings", "frame", "/org/example/window",
                     {screen: [364, 149, 1000, 740], window: [0, 0, 1000, 740]})
        target = Node("Notifications", "page tab", "/org/example/tab",
                      {screen: [500, 300, 80, 40], window: [136, 151, 80, 40]})
        frame.children = [target, target]
        target.children = [frame]
        app.children = [frame]
        desktop = types.SimpleNamespace(get_child_count=lambda: 1,
                                       get_child_at_index=lambda _index: app)
        atspi = types.SimpleNamespace(init=lambda: None, get_desktop=lambda _index: desktop,
            CoordType=types.SimpleNamespace(SCREEN=screen, WINDOW=window),
            StateType=types.SimpleNamespace(VISIBLE=1, SHOWING=2))
        monitor_model = types.SimpleNamespace(get_n_items=lambda: 1,
            get_item=lambda _index: types.SimpleNamespace(get_scale_factor=lambda: 1))
        gdk = types.SimpleNamespace(Display=types.SimpleNamespace(get_default=lambda:
            types.SimpleNamespace(get_monitors=lambda: monitor_model)))
        gtk = types.SimpleNamespace(init=lambda: None)

        def fake_runner(command, **_kwargs):
            repository = types.ModuleType("gi.repository")
            repository.Atspi, repository.Gdk, repository.Gtk = atspi, gdk, gtk
            gi = types.ModuleType("gi")
            gi.require_version = lambda *_args: None
            gi.repository = repository
            with unittest.mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
                old_argv, capture = sys.argv, __import__("io").StringIO()
                try:
                    sys.argv = ["-c", *command[3:]]
                    with unittest.mock.patch("sys.stdout", capture):
                        exec(compile(command[2], "<generated-atspi-probe>", "exec"), {})
                finally:
                    sys.argv = old_argv
            return subprocess.CompletedProcess(command, 0, capture.getvalue(), "")

        result = MODULE.resolve_atspi_geometry(
            "codexbar-gtk-synthetic-wayland-test", 4242, "Notifications", kwin,
            runner=fake_runner, expected_roles=("page tab",))
        self.assertEqual(result["calculated_point"], [540, 320])

        foreign_bus_alias = Node("Notifications", "page tab", "/org/example/tab",
                                 {screen: [500, 300, 80, 40], window: [136, 151, 80, 40]})
        foreign_bus_alias.app = types.SimpleNamespace(bus_name="org.example.other")
        frame.children.append(foreign_bus_alias)
        with self.assertRaises(MODULE.GeometryResolutionError):
            MODULE.resolve_atspi_geometry(
                "codexbar-gtk-synthetic-wayland-test", 4242, "Notifications", kwin,
                runner=fake_runner, expected_roles=("page tab",))

    def test_accepts_fresh_stable_target(self):
        self.assertTrue(MODULE.guard_target(self.snapshot(), 4242, 810, 315, now=100.2))

    def test_batch_parser_is_ordered_unique_bounded_and_allowlisted(self):
        actions = ["session-quota-notifications", "quota-warning-notifications",
                   "limit-reset-notifications", "predictive-pace-notifications",
                   "show-tray-icon", "disable-global-hooks"]
        self.assertEqual(MODULE.parse_action_batch(",".join(actions),
                                                  MODULE.WAYLAND_SWITCH_ACTIONS), actions)
        for value in ("", ",".join(actions + ["show-panel-on-start", "start-at-login", "hide-personal-info"]),
                      "show-tray-icon,show-tray-icon", "show-tray-icon,not-allowlisted", "show-tray-icon,,hide-personal-info"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.parse_action_batch(value, MODULE.WAYLAND_SWITCH_ACTIONS)

    def test_batch_cli_rejects_unsupported_routes_before_environment_or_input(self):
        action = "session-quota-notifications"
        cases = (
            (["--actions", action, "--portal"], "cannot be combined"),
            (["--actions", action, "--bridge", "--inspect-only"], "cannot be combined"),
            (["--actions", action, "--bridge", "--move-only"], "cannot be combined"),
            (["--actions", action], "requires explicit --bridge"),
            (["--actions", "unknown", "--portal"], "unknown action"),
            (["--actions", f"{action},{action}", "--portal"], "must be unique"),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--binary", "/does/not/exist", *extra],
                    capture_output=True, text=True, timeout=8,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("--binary must name", result.stderr)

    def test_synthetic_generated_cli_hooks_and_provider_readout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cli = root / "codexbar"
            hooks_state = root / "hooks-enabled"
            provider_state = root / "provider-enabled"
            calls = root / "calls.log"
            cli.write_text(MODULE.synthetic_cli_source(True, True))
            cli.chmod(0o700)
            env = dict(os.environ, HOME=str(root / "home"), FIXTURE_HOOKS_ENABLED=str(hooks_state),
                       FIXTURE_PROVIDER_ENABLED=str(provider_state), FIXTURE_CLI_CALLS=str(calls))
            (root / "home").mkdir()

            for state in ("true", "false"):
                hooks_state.write_text(state)
                result = subprocess.run([str(cli), "hooks", "list"], env=env,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"enabled": state == "true", "events": []})
                self.assertFalse(result.stderr)

            for command, expected in (("disable", "false"), ("enable", "true")):
                result = subprocess.run([str(cli), "hooks", command], env=env,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"ok": True})
                self.assertEqual(hooks_state.read_text(), expected)
            self.assertEqual(calls.read_text().splitlines(), ["hooks disable", "hooks enable"])

            provider_state.write_text("true")
            result = subprocess.run([str(cli), "config", "providers"], env=env,
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "codex: enabled (Codex)", "claude: disabled (Claude)",
            ])
            self.assertEqual(calls.read_text().splitlines(), [
                "hooks disable", "hooks enable", "config providers",
            ])

    def test_batch_preference_comparison_requires_full_native_default_map(self):
        action = "session-quota-notifications"
        expected = MODULE.batch_expected_preferences([action])
        self.assertEqual(expected["sessionQuotaNotificationsEnabled"], False)
        expected["sessionQuotaNotificationsEnabled"] = True
        self.assertTrue(MODULE.preferences_equal(expected, dict(expected)))
        invalid_maps = (
            {**expected, "unknownAddedKey": False},
            {**expected, "showTray": False},
            {key: value for key, value in expected.items() if key != "debugMenuEnabled"},
        )
        for observed in invalid_maps:
            with self.subTest(observed=observed):
                self.assertFalse(MODULE.preferences_equal(expected, observed))

    def test_batch_phase_plan_groups_only_adjacent_actions_on_same_page(self):
        actions = ["session-quota-notifications", "quota-warning-notifications",
                   "show-tray-icon", "disable-global-hooks", "predictive-pace-notifications"]
        self.assertEqual(MODULE.batch_page_phases(actions), [
            {"page": "Notifications", "actions": actions[:2]},
            {"page": "Menu Bar", "actions": actions[2:3]},
            {"page": "Hooks", "actions": actions[3:4]},
            {"page": "Notifications", "actions": actions[4:]},
        ])

    def test_six_control_batch_counts_page_tabs_as_separate_input(self):
        actions = ["session-quota-notifications", "quota-warning-notifications",
                   "limit-reset-notifications", "predictive-pace-notifications",
                   "show-tray-icon", "disable-global-hooks"]
        phases = MODULE.batch_page_phases(actions)
        navigation_clicks = len(phases)
        self.assertEqual(navigation_clicks, 3)
        self.assertEqual(len(actions) + navigation_clicks, 9)

    def test_batch_hooks_maps_to_existing_global_cli_switch(self):
        hooks = MODULE.WAYLAND_SWITCH_ACTIONS["disable-global-hooks"]
        self.assertEqual(hooks["page"], "Hooks")
        self.assertEqual(hooks["label"], "Enable hooks")
        self.assertEqual(hooks["kind"], "hooks_switch")
        self.assertIsNone(hooks["preference"])

    def test_batch_control_probe_is_read_only_and_exact_pid_name_and_label(self):
        raw, kwin = self.geometry_fixture()
        raw["application"] = "synthetic-app"
        raw["controls"][0].update(name="Pace warnings", screen=[850, 300, 28, 28],
                                  window=[486, 151, 28, 28], role="switch")
        raw.update(requested_label="Pace warnings", expected_roles=["switch"])
        result = unittest.mock.Mock(returncode=0, stdout=json.dumps(raw))
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return result

        geometry = MODULE.resolve_atspi_geometry("synthetic-app", 4242, "Pace warnings", kwin,
                                                 runner=runner, expected_roles=("switch",))
        self.assertEqual(geometry["control_bounds"], [850, 300, 28, 28])
        argv, kwargs = calls[0]
        self.assertEqual(argv[-5:], ["4242", "synthetic-app", "Pace warnings", '["switch"]', "CodexBar Settings"])
        self.assertEqual(kwargs["timeout"], 8)
        self.assertIn("int(app.get_process_id())!=want_pid", argv[2])
        self.assertIn("app.get_name()!=want_name", argv[2])
        self.assertIn("Atspi.CoordType.SCREEN", argv[2])
        self.assertIn("Atspi.CoordType.WINDOW", argv[2])
        self.assertIn("Gtk.init()", argv[2])
        self.assertIn("get_scale_factor()", argv[2])
        self.assertIn("if name==want_label", argv[2])
        self.assertNotIn("role in roles", argv[2])
        self.assertEqual(json.loads(argv[-2]), ["switch"])
        self.assertNotIn("do_action", argv[2].lower())

    def test_measured_checkbox_is_uniquely_selected_from_three_same_label_nodes(self):
        kwin = self.geometry_fixture()[1]
        raw = {
            "application": "synthetic-app", "pid": 4242,
            "application_bus_name": "org.example.synthetic",
            "requested_label": "Refresh when the panel opens",
            "expected_roles": list(MODULE.AT_SPI_TOGGLE_ROLES),
            "desktop_scale_factors": [1],
            "top_level_windows": [{
                "name": "CodexBar Settings", "role": "frame", "visible": True,
                "showing": True, "screen": [0, 0, 1000, 740],
                "window": [0, 0, 1000, 740],
                "bus_name": "org.example.synthetic", "object_path": "/org/example/window",
            }],
            # This mirrors the measured GTK export: one checkbox, its list row,
            # and the text label all have the same accessible name.
            "controls": [
                {"name": "Refresh when the panel opens", "role": "check box",
                 "visible": True, "showing": True,
                 "labelled_by": "Refresh when the panel opens",
                 "screen": [0, 0, 46, 26], "window": [731, 306, 46, 26],
                 "bus_name": "org.example.synthetic", "object_path": "/org/example/checkbox"},
                {"name": "Refresh when the panel opens", "role": "list item",
                 "visible": True, "showing": True,
                 "labelled_by": "Refresh when the panel opens",
                 "described_by": "Refreshes provider data when the panel opens",
                 "screen": [0, 0, 576, 58], "window": [214, 289, 576, 58],
                 "bus_name": "org.example.synthetic", "object_path": "/org/example/list_row"},
                {"name": "Refresh when the panel opens", "role": "label",
                 "visible": True, "showing": True,
                 "screen": [0, 0, 496, 21], "window": [226, 295, 496, 21],
                 "bus_name": "org.example.synthetic", "object_path": "/org/example/label"},
            ],
        }
        result = unittest.mock.Mock(returncode=0, stdout=json.dumps(raw))
        calls = []
        resolved = MODULE.resolve_atspi_geometry(
            "synthetic-app", 4242, "Refresh when the panel opens", kwin,
            runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or result),
            expected_roles=MODULE.AT_SPI_TOGGLE_ROLES,
        )
        self.assertEqual(json.loads(calls[0][0][-2]), ["check box", "switch"])
        self.assertEqual(len(raw["controls"]), 3)
        self.assertEqual(resolved["control_bounds"], [1095, 455, 46, 26])
        self.assertEqual(resolved["calculated_point"], [1118, 468])

        rejected = []
        wrong_label = json.loads(json.dumps(raw))
        wrong_label["controls"][0]["name"] = "A different preference"
        rejected.append((wrong_label, kwin))
        hidden_checkbox = json.loads(json.dumps(raw))
        hidden_checkbox["controls"][0]["showing"] = False
        rejected.append((hidden_checkbox, kwin))
        duplicate_checkbox = json.loads(json.dumps(raw))
        duplicate_checkbox["controls"].append({**raw["controls"][0], "object_path": "/org/example/checkbox2"})
        rejected.append((duplicate_checkbox, kwin))
        wrong_pid = json.loads(json.dumps(raw))
        wrong_pid["pid"] = 77
        rejected.append((wrong_pid, kwin))
        for forbidden_role in ("list item", "label", "toggle button"):
            forbidden = json.loads(json.dumps(raw))
            forbidden["expected_roles"] = [forbidden_role]
            rejected.append((forbidden, kwin))
        for evidence, compositor in rejected:
            with self.subTest(evidence=evidence):
                with self.assertRaises(MODULE.GeometryResolutionError):
                    MODULE.resolve_coordinate_geometry(
                        evidence, compositor, 4242, "synthetic-app")

    def test_batch_control_probe_rejects_missing_ambiguous_invalid_and_failed(self):
        _, kwin = self.geometry_fixture()
        for result in (
            unittest.mock.Mock(returncode=0, stdout='{"bounds":[]}'),
            unittest.mock.Mock(returncode=0, stdout='{"bounds":[[1,2,20,20],[4,5,30,30]]}'),
            unittest.mock.Mock(returncode=0, stdout='{"bounds":[[1,2,0,20]]}'),
            unittest.mock.Mock(returncode=0, stdout='not-json'),
            unittest.mock.Mock(returncode=1, stdout='{}'),
        ):
            with self.subTest(stdout=result.stdout), self.assertRaises(MODULE.GeometryResolutionError):
                MODULE.resolve_atspi_geometry("synthetic-app", 4242, "exact control", kwin,
                                              runner=lambda *_a, _result=result, **_k: _result)

    def test_batch_evidence_contains_only_allowlisted_metadata(self):
        state = self.snapshot(sample_seq=14, received=100.05, cursor=[864, 314],
                              pre_click_age_seconds=0.2,
                              target_geometry=[364, 149, 1000, 740],
                              coordinate_space="screen", calculated_point=[864, 314],
                              raw_geometry={"synthetic": True})
        with unittest.mock.patch.object(MODULE.time, "monotonic", return_value=100.25):
            evidence = MODULE.safe_action_evidence(
                "predictive-pace-notifications", state, 4242, "Pace warnings",
                [850, 300, 28, 28], False, True,
            )
        self.assertEqual(evidence["target_pid"], 4242)
        self.assertEqual(evidence["input_method"], "guarded_pointer_click")
        self.assertEqual(evidence["control_bounds"], [850, 300, 28, 28])
        self.assertEqual(evidence["sample_seq"], 14)
        self.assertEqual(evidence["sample_age_seconds"], 0.2)
        self.assertEqual(evidence["sample_received_monotonic"], 100.05)
        self.assertEqual(set(evidence), {
            "action", "target_pid", "control", "control_bounds", "target_geometry",
            "coordinate_space", "calculated_point", "raw_geometry",
            "input_method", "sample_seq", "sample_age_seconds", "sample_received_monotonic",
            "input_requested_monotonic", "input_outcome", "input_return_metadata",
            "action_state_before", "action_state_after",
        })
        self.assertFalse(any("password" in key.lower() or "secret" in key.lower()
                             for key in evidence))
        self.assertNotIn("actual account", json.dumps(evidence))
        for changes in ({"pid": 19}, {"active": False}, {"top_hit": False},
                        {"cursor": [0, 0]}, {"pre_click_age_seconds": 0.8},
                        {"sample_seq": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                MODULE.safe_action_evidence(
                    "predictive-pace-notifications", {**state, **changes}, 4242,
                    "Pace warnings", [850, 300, 28, 28], False, True,
                )

    def test_batch_preclick_guard_checks_unrounded_age(self):
        for age in (0.1496, 0.3504):
            state = self.snapshot(sample_seq=1, received=100.0,
                                  pre_click_age_seconds=age,
                                  target_geometry=[364, 149, 1000, 740], cursor=[864, 314])
            with self.subTest(age=age), self.assertRaises(ValueError):
                MODULE.safe_action_evidence("predictive-pace-notifications", state, 4242,
                                            "Pace warnings", [850, 300, 28, 28], False, True)

    def test_read_only_baseline_requires_exact_active_target_but_not_pointer_hit(self):
        state = self.snapshot(top_hit=False, cursor=[1727, 2])
        self.assertTrue(MODULE.active_target(state, 4242))
        self.assertFalse(MODULE.active_target(state, 7))
        self.assertFalse(MODULE.active_target({**state, "active": False}, 4242))

    def test_rejects_stale_foreign_or_non_topmost_target(self):
        for changes in (
            {"received": 99.0},
            {"pid": 7},
            {"active": False},
            {"top_hit": False},
            {"cursor": [0, 0]},
            {"received": 100.1},  # too soon after the last cursor/focus event
        ):
            with self.subTest(changes=changes):
                self.assertFalse(MODULE.guard_target(self.snapshot(**changes), 4242, 810, 315, now=100.2))

    def test_compositor_sampler_refreshes_stationary_target_with_ordered_reports(self):
        sample = {
            "sample_seq": 1, "pid": 4242, "active": True, "top_hit": True,
            "target_present": True, "target_geometry": [364, 149, 1000, 740],
            "cursor": [810, 315], "portal_active": False,
        }
        state = dict(sample, received=100.25)
        self.assertTrue(MODULE.valid_kwin_observer_sample(":1.20", ":1.20", sample, 0))
        self.assertTrue(MODULE.guard_target(state, 4242, 810, 315, now=100.45))

        # Same cursor, active PID and hit result; the timer's next compositor
        # query has a new sequence and receive time, so the age gate can pass.
        next_sample = dict(sample, sample_seq=2)
        self.assertTrue(MODULE.valid_kwin_observer_sample(":1.20", ":1.20", next_sample, 1))
        refreshed = dict(next_sample, received=100.50)
        self.assertEqual(refreshed["cursor"], state["cursor"])
        self.assertTrue(MODULE.guard_target(refreshed, 4242, 810, 315, now=100.70))

    def test_observer_rejects_wrong_sender_malformed_and_replayed_samples(self):
        sample = {
            "sample_seq": 8, "pid": 4242, "active": True, "top_hit": True,
            "target_present": True, "target_geometry": [364, 149, 1000, 740],
            "cursor": [810, 315], "portal_active": False,
        }
        self.assertFalse(MODULE.valid_kwin_observer_sample(":1.21", ":1.20", sample, 7))
        self.assertFalse(MODULE.valid_kwin_observer_sample(":1.20", ":1.20", sample, 8))
        self.assertFalse(MODULE.valid_kwin_observer_sample(
            ":1.20", ":1.20", dict(sample, sample_seq=True), 7))
        self.assertFalse(MODULE.valid_kwin_observer_sample(
            ":1.20", ":1.20", dict(sample, cursor=[810, "315"]), 7))

    def test_kwin_sampler_is_bounded_timer_and_single_flight(self):
        script = MODULE.KWIN_JS
        self.assertIn("new QTimer(this)", script)
        self.assertIn("SAMPLE_INTERVAL_MS=250", script)
        self.assertIn("sampler.start(SAMPLE_INTERVAL_MS)", script)
        self.assertIn("MAX_SAMPLES=2400", script)
        self.assertIn("active_window_pid", script)
        self.assertIn("active_window_title", script)
        self.assertIn('String(a.caption)', script)
        self.assertIn("MAX_LIFETIME_MS=600000", script)
        self.assertIn("if(sampleInFlight||now-lastSampleAt<SAMPLE_INTERVAL_MS)return", script)
        self.assertIn("sample_seq:sequence", script)
        self.assertIn("workspace.windowAt(p,1)", script)
        self.assertIn("workspace.activeWindow", script)
        self.assertIn("workspace.stackingOrder", script)
        self.assertIn("__VALIDATOR__", MODULE.OBSERVER_PY)
        self.assertIn("valid_kwin_observer_sample(sender,expected_sender,state,last_sequence)",
                      MODULE.OBSERVER_PY)

    def test_delayed_bridge_return_uses_new_compositor_sample_before_click(self):
        calls = []
        state = self.snapshot(target_geometry=[364, 149, 1000, 740], received=100.0,
                              sample_seq=1)

        class SlowBridge:
            def move(self, x, y):
                calls.append(("move", x, y))
                # Simulate two 250 ms compositor timer samples while the
                # bridge's screenshot-backed call is still returning.
                state.update(received=100.72, sample_seq=3, cursor=[x, y], top_hit=True)

            def click(self, x, y):
                calls.append(("click", x, y))

        # More than the 350 ms age limit elapsed in move(); only the timer
        # report received at 100.72 can make the exact-target guard pass.
        with unittest.mock.patch.object(
                MODULE.time, "monotonic", side_effect=[100.80, 100.80, 100.91, 100.93, 100.94]):
            clicked = MODULE.guarded_click_bridge(SlowBridge(), 4242, lambda: dict(state), 810, 315)
        self.assertEqual(calls, [("move", 810, 315), ("click", 810, 315)])
        self.assertEqual(state["sample_seq"], 3)
        self.assertEqual(clicked["input_requested_monotonic"], 100.94)
        self.assertEqual(clicked["input_outcome"], "returned")
        self.assertEqual(clicked["input_return_metadata"], {})

    def test_no_heartbeat_after_delayed_move_never_clicks(self):
        calls = []
        state = self.snapshot(target_geometry=[364, 149, 1000, 740], received=100.0,
                              sample_seq=1)

        class StalledBridge:
            def move(self, x, y):
                calls.append(("move", x, y))

            def click(self, x, y):
                calls.append(("click", x, y))

        with unittest.mock.patch.object(
                MODULE.time, "monotonic", side_effect=[100.80, 100.80, 100.80, 103.0]), \
                unittest.mock.patch.object(MODULE.time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no click sent"):
                MODULE.guarded_click_bridge(StalledBridge(), 4242, lambda: dict(state), 810, 315)
        self.assertEqual(calls, [("move", 810, 315)])

    def test_focus_change_after_motion_never_clicks(self):
        calls = []
        state = self.snapshot(target_geometry=[364, 149, 1000, 740], received=100.2)

        class FocusChangingBridge:
            def move(self, x, y):
                calls.append(("move", x, y))
                state.update(pid=17, active=False, top_hit=False, cursor=[x, y], received=100.2)

            def click(self, x, y):
                calls.append(("click", x, y))

        with unittest.mock.patch.object(
                MODULE.time, "monotonic", side_effect=[100.4, 100.4, 100.4, 103.0]), \
                unittest.mock.patch.object(MODULE.time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no click sent"):
                MODULE.guarded_click_bridge(FocusChangingBridge(), 4242, lambda: dict(state), 810, 315)
        self.assertEqual(calls, [("move", 810, 315)])

    def test_window_geometry_rejects_coordinates_outside_target(self):
        state = self.snapshot(target_geometry=[100, 200, 900, 700])
        self.assertTrue(MODULE.target_window_contains(state, 810, 315))
        self.assertFalse(MODULE.target_window_contains(state, 1000, 315))
        self.assertFalse(MODULE.target_window_contains(state, 99, 200))
        self.assertFalse(MODULE.target_window_contains(self.snapshot(), 810, 315))

    def test_default_switch_point_is_derived_inside_settings_window(self):
        point = MODULE.switch_point_from_geometry([364, 149, 1000, 740])
        self.assertEqual(point, (864, 445))
        self.assertTrue(MODULE.target_window_contains(
            self.snapshot(target_geometry=[364, 149, 1000, 740]), *point
        ))
        with self.assertRaises(ValueError):
            MODULE.switch_point_from_geometry(None)

    def test_notification_actions_are_allowlisted_and_geometry_derived(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        self.assertEqual(
            set(actions),
            {
                "refresh-when-panel-opens", "show-panel-on-start", "start-at-login",
                "hide-personal-info",
                "session-quota-notifications", "quota-warning-notifications",
                "limit-reset-notifications", "predictive-pace-notifications",
                "test-notification", "show-tray-icon",
                "disable-codex-provider", "provider-source", "provider-api-key",
                "provider-login", "disable-global-hooks",
            },
        )
        self.assertEqual(
            actions["session-quota-notifications"]["preference"],
            "sessionQuotaNotificationsEnabled",
        )
        self.assertEqual(
            actions["quota-warning-notifications"]["preference"],
            "quotaWarningNotificationsEnabled",
        )
        self.assertEqual(
            actions["limit-reset-notifications"]["preference"],
            "limitResetNotificationsEnabled",
        )
        self.assertEqual(
            actions["predictive-pace-notifications"]["preference"],
            "predictivePaceNotificationsEnabled",
        )
        for name in (
            "session-quota-notifications", "quota-warning-notifications",
            "limit-reset-notifications", "predictive-pace-notifications",
            "test-notification",
        ):
            self.assertEqual(actions[name]["page"], "Notifications")
            self.assertIn("/tmp/codexbar-notifications-page-check.png",
                          actions[name].get("page_check", ""))
            point = MODULE.switch_point_from_geometry(
                [364, 149, 1000, 740], y_offset=actions[name]["y_offset"]
            )
            self.assertTrue(MODULE.target_window_contains(
                self.snapshot(target_geometry=[364, 149, 1000, 740]), *point))

    def test_test_notification_button_requires_delivery_not_preference(self):
        action = MODULE.WAYLAND_SWITCH_ACTIONS["test-notification"]
        self.assertIsNone(action["preference"])
        self.assertEqual(action.get("kind"), "button")
        self.assertTrue(action.get("requires_notification_delivery"))

    def test_notification_delivery_log_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = pathlib.Path(temporary) / "notifications-monitor.log"
            self.assertFalse(MODULE.notification_delivered(log))
            log.write_text("Method call: Notify('CodexBar', 'CodexBar GTK test notification')\n")
            self.assertTrue(MODULE.notification_delivered(log))
            log.write_text("D-Bus connection established\n")
            self.assertFalse(MODULE.notification_delivered(log))
            self.assertFalse(MODULE.notification_delivered(pathlib.Path(temporary) / "missing.log"))

    def test_general_switch_actions_are_allowlisted_and_geometry_derived(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        self.assertEqual(
            set(actions),
            {"refresh-when-panel-opens", "show-panel-on-start", "start-at-login", "hide-personal-info",
             "session-quota-notifications", "quota-warning-notifications",
             "limit-reset-notifications", "predictive-pace-notifications", "test-notification",
             "show-tray-icon", "disable-codex-provider", "provider-source",
             "provider-api-key", "provider-login", "disable-global-hooks"},
        )
        self.assertEqual(
            actions["show-panel-on-start"]["preference"],
            "showPopupOnStart",
        )
        point = MODULE.switch_point_from_geometry(
            [364, 149, 1000, 740], y_offset=actions["show-panel-on-start"]["y_offset"]
        )
        self.assertEqual(point, (864, 637))
        self.assertTrue(
            MODULE.target_window_contains(
                self.snapshot(target_geometry=[364, 149, 1000, 740]), *point
            )
        )
        with self.assertRaises(ValueError):
            MODULE.switch_point_from_geometry([364, 149, 1000, 740], y_offset=740)
        fractional_point = MODULE.switch_point_from_geometry(
            [432, 175.625, 1000, 740], y_offset=488
        )
        self.assertEqual(fractional_point, (932, 664))
        self.assertTrue(all(isinstance(value, int) for value in fractional_point))

    def test_menu_bar_switch_maps_to_show_tray_preference(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        self.assertEqual(actions["show-tray-icon"]["preference"], "showTray")
        self.assertEqual(actions["show-tray-icon"]["page"], "Menu Bar")
        self.assertEqual(actions["show-tray-icon"]["label"], "Show the tray icon")
        point = MODULE.switch_point_from_geometry(
            [364, 149, 1000, 740],
            y_offset=actions["show-tray-icon"]["y_offset"],
            x_fraction=actions["show-tray-icon"]["switch_x_fraction"],
        )
        self.assertTrue(
            MODULE.target_window_contains(
                self.snapshot(target_geometry=[364, 149, 1000, 740]), *point
            )
        )
        # The three Menu Bar combos (menuBarIconStyle, unifiedIconSource,
        # switcherRowsOption) are intentionally NOT allowlisted: dropdown
        # selection has no safe synthetic path here and stays manual.
        self.assertNotIn("icon-style", actions)
        self.assertNotIn("icon-shows", actions)
        self.assertNotIn("provider-rows", actions)

    def test_provider_switch_maps_to_cli_disable_and_state_file(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        action = actions["disable-codex-provider"]
        # No preference key: the CLI owns provider state, like autostart.
        self.assertIsNone(action["preference"])
        self.assertEqual(action.get("kind"), "provider_switch")
        self.assertEqual(action["cli_action"], "disable")
        self.assertEqual(action["provider_id"], "codex")
        self.assertEqual(action["page"], "Providers")
        self.assertIn("/tmp/codexbar-providers-page-check.png",
                      action.get("page_check", ""))
        point = MODULE.switch_point_from_geometry(
            [364, 149, 1000, 740],
            y_offset=action["y_offset"],
            x_fraction=action["switch_x_fraction"],
        )
        self.assertEqual(point, (1174, 383))
        self.assertTrue(
            MODULE.target_window_contains(
                self.snapshot(target_geometry=[364, 149, 1000, 740]), *point
            )
        )
        self.assertEqual(
            MODULE.provider_cli_call("disable", "codex"),
            "config disable --provider codex",
        )
        self.assertEqual(
            MODULE.provider_cli_call("set-source", "codex", "api"),
            "config set-source --provider codex --source api",
        )

    def test_provider_state_check_requires_call_and_flipped_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = pathlib.Path(temporary) / "calls.log"
            enabled = pathlib.Path(temporary) / "enabled"
            self.assertFalse(MODULE.check_provider_state(calls, enabled, "disable", "codex"))
            enabled.write_text("true\n")
            self.assertFalse(MODULE.check_provider_state(calls, enabled, "disable", "codex"))
            calls.write_text("config disable --provider codex\n")
            self.assertFalse(MODULE.check_provider_state(calls, enabled, "disable", "codex"))
            enabled.write_text("false\n")
            self.assertTrue(MODULE.check_provider_state(calls, enabled, "disable", "codex"))
            enabled.write_text("true\n")
            self.assertFalse(MODULE.check_provider_state(calls, enabled, "disable", "codex"))

    def test_provider_source_api_key_and_login_are_manual_only(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        for name, cli_action in (
            ("provider-source", "set-source"),
            ("provider-api-key", "set-api-key"),
            ("provider-login", "login"),
        ):
            with self.subTest(action=name):
                action = actions[name]
                self.assertEqual(action.get("kind"), "manual")
                self.assertIsNone(action["preference"])
                self.assertEqual(action["cli_action"], cli_action)
                self.assertEqual(action["provider_id"], "codex")
                self.assertEqual(action["page"], "Providers")

    def test_action_result_reports_only_the_selected_preference_change(self):
        before = {"showPopupOnStart": False, "launchAtLogin": False}
        after = {"showPopupOnStart": False, "launchAtLogin": True}
        self.assertEqual(MODULE.changed_preferences(before, after), ["launchAtLogin"])
        self.assertEqual(
            MODULE.changed_preferences(
                before, {"showPopupOnStart": True, "launchAtLogin": False}
            ),
            ["showPopupOnStart"],
        )

    def test_display_tab_point_hits_measured_pill(self):
        """E184: the old (0.34, 0.94) estimate landed 1 px above the pill."""
        geometry = [364, 149, 1000, 740]
        point = MODULE.page_tab_point_from_geometry(geometry, "Display")
        # Display pill spans window px x 283..367, y 697..736; absolute
        # rect x 647..731, y 846..885; centre (689, 866); old estimate
        # (704, 845) is 1 px above the pill top edge 846.
        self.assertEqual(point, (689, 865))
        self.assertTrue(647 <= point[0] <= 731)
        self.assertTrue(846 <= point[1] <= 885)
        state = self.snapshot(target_geometry=geometry)
        self.assertTrue(MODULE.target_window_contains(state, *point))
        old_point = (704, 845)
        self.assertFalse(846 <= old_point[1] <= 885)
        with self.assertRaises(ValueError):
            MODULE.page_tab_point_from_geometry(geometry, "Nope")
        with self.assertRaises(ValueError):
            MODULE.page_tab_point_from_geometry(None, "Display")

    def test_page_verification_fails_closed_without_evidence(self):
        self.assertFalse(
            MODULE.page_verified_from_capture(
                "/tmp/does-not-exist-wayland-evidence.png", [364, 149, 1000, 740]
            )
        )


    def test_focus_recovery_targets_only_the_synthetic_settings_window(self):
        script = MODULE.activation_script(4242)
        self.assertIn("TARGET_PID=4242", script)
        self.assertIn('Number(windows[i].pid)===TARGET_PID', script)
        self.assertIn('String(windows[i].caption).indexOf("CodexBar Settings")>=0', script)
        self.assertIn("workspace.activeWindow=target", script)
        self.assertIn('"Record",JSON.stringify(state)', script)
        self.assertNotIn("NotifyPointer", script)

    def test_move_only_reactivates_lost_focus_then_samples_before_one_move(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            preferences = root / "settings.json"
            preferences.write_text('{"showPopupOnStart":false}\n')
            original_preferences = preferences.read_bytes()
            telemetry = MODULE.BoundedTelemetry(root / "telemetry.json")
            events = []
            state = self.snapshot(active=False, target_geometry=[364, 149, 1000, 740])

            class MoveOnly:
                def move(self, x, y):
                    events.append(("move", x, y))

                def __getattr__(self, name):
                    raise AssertionError(f"move-only diagnostic attempted forbidden {name}")

            class CommandResult:
                returncode = 0
                stdout = "true\n"

            def fake_runner(argv, **_kwargs):
                events.append(("activate", argv[4] if len(argv) > 4 else "start"))
                if argv[-1:] == ["org.kde.kwin.Scripting.start"]:
                    state.update(active=True, pid=4242,
                                 received=MODULE.time.monotonic() - .2)
                return CommandResult()

            def latest():
                events.append(("sample", state["active"], state["pid"]))
                return dict(state)

            # Baseline focus was lost; activation must restore the exact PID
            # before a fresh sample is accepted and before the one move.
            self.assertFalse(MODULE.active_target(state, 4242))
            baseline = MODULE.activate_and_wait_for_target(
                4242, root / "focus.js", "focus-plugin", latest,
                runner=fake_runner,
            )
            self.assertTrue(MODULE.fresh_active_target(baseline, 4242))
            MODULE.move_only_diagnostic(
                MoveOnly(), 4242, latest, preferences, telemetry,
                timeout_seconds=0,
            )
            move_index = next(i for i, event in enumerate(events) if event[0] == "move")
            start_index = max(i for i, event in enumerate(events[:move_index])
                              if event[0] == "activate")
            fresh_sample_index = max(i for i, event in enumerate(events[:move_index])
                                     if event[0] == "sample" and event[1:]
                                     == (True, 4242))
            self.assertLess(start_index, fresh_sample_index)
            self.assertLess(fresh_sample_index, move_index)
            self.assertEqual([event[0] for event in events].count("move"), 1)
            self.assertEqual(preferences.read_bytes(), original_preferences)

    def test_move_only_rejects_stale_or_wrong_pid_immediately_before_move(self):
        for changes in (
            {"received": MODULE.time.monotonic() - .5},
            {"pid": 7, "active": False},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                preferences = root / "settings.json"
                preferences.write_text('{"showPopupOnStart":false}\n')
                telemetry = MODULE.BoundedTelemetry(root / "telemetry.json")
                state = self.snapshot(
                    **{**changes, "target_geometry": [364, 149, 1000, 740]}
                )

                class MoveOnly:
                    moves = 0

                    def move(self, _x, _y):
                        self.moves += 1

                bridge = MoveOnly()
                with self.assertRaisesRegex(RuntimeError, "fresh active"):
                    MODULE.move_only_diagnostic(
                        bridge, 4242, lambda: dict(state), preferences,
                        telemetry, timeout_seconds=0,
                    )
                self.assertEqual(bridge.moves, 0)
                self.assertEqual(preferences.read_text(), '{"showPopupOnStart":false}\n')

    def test_portal_desktop_entry_never_replaces_existing_user_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            existing = root / "existing.desktop"
            existing.write_text("user-owned entry\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                MODULE.create_portal_desktop_entry(existing)
            self.assertEqual(existing.read_text(encoding="utf-8"), "user-owned entry\n")

            created = root / "new.desktop"
            self.assertTrue(MODULE.create_portal_desktop_entry(created))
            self.assertIn("CodexBar GTK synthetic Wayland test", created.read_text(encoding="utf-8"))

    def test_portal_input_calls_use_remote_desktop_endpoint_on_same_bus(self):
        class FakeBus:
            def __init__(self):
                self.calls = []

            def get_unique_name(self):
                return ":1.42"

            def call_sync(self, *args):
                self.calls.append(args)
                return None

        bus = FakeBus()
        driver = MODULE.PortalDriver(bus)
        driver.session = "/org/freedesktop/portal/desktop/session/test"
        driver.move(12, -4)
        driver.click()
        self.assertEqual(len(bus.calls), 3)
        for call in bus.calls:
            self.assertEqual(call[0], MODULE.PORTAL)
            self.assertEqual(call[1], MODULE.PORTAL_PATH)
            self.assertEqual(call[2], MODULE.REMOTE)
            self.assertEqual(call[4].unpack()[0], driver.session)
        self.assertEqual(bus.calls[0][4].get_type_string(), "(oa{sv}dd)")
        self.assertEqual(bus.calls[1][4].get_type_string(), "(oa{sv}iu)")
        self.assertEqual(bus.calls[2][4].get_type_string(), "(oa{sv}iu)")


    def test_bridge_driver_sends_absolute_actions(self):
        calls = []

        class FakeDone:
            returncode = 0
            stdout = '{"sent": true}'
            stderr = ""

        def fake_runner(argv, **_kwargs):
            calls.append(argv)
            return FakeDone()

        driver = MODULE.BridgeDriver("linux-agent-access", "com.steipete.CodexBarGTK", runner=fake_runner)
        driver.move(860, 332)
        driver.click(860, 332)
        self.assertEqual(len(calls), 2)
        for argv, kind in ((calls[0], "move"), (calls[1], "click")):
            self.assertEqual(argv[0], "linux-agent-access")
            self.assertEqual(argv[1], "action")
            self.assertEqual(argv[3], "com.steipete.CodexBarGTK")
            payload = MODULE.json.loads(argv[5])
            self.assertEqual(payload["kind"], kind)
            self.assertEqual((payload["x"], payload["y"]), (860, 332))
        self.assertEqual(MODULE.json.loads(calls[1][5])["button"], "left")
        driver.close()

    def test_bridge_driver_fails_closed_on_bridge_error(self):
        class FakeError:
            returncode = 1
            stdout = ""
            stderr = "Named target application is not active"

        driver = MODULE.BridgeDriver(
            "linux-agent-access", "com.steipete.CodexBarGTK", runner=lambda argv, **_k: FakeError())
        with self.assertRaises(RuntimeError) as ctx:
            driver.click(860, 332)
        self.assertIn("bounded synthetic telemetry", str(ctx.exception))

        class FakeBadJson:
            returncode = 0
            stdout = "not json"
            stderr = ""

        driver = MODULE.BridgeDriver(
            "linux-agent-access", "com.steipete.CodexBarGTK", runner=lambda argv, **_k: FakeBadJson())
        with self.assertRaises(RuntimeError):
            driver.move(860, 332)

    def test_fixture_env_bridge_requires_a11y_and_portal_disables_it(self):
        base = {"GTK_A11Y": "none", "HOME": "/x"}
        bridge_env = MODULE.fixture_env(True, runner_env=base)
        self.assertNotIn("GTK_A11Y", bridge_env)
        portal_env = MODULE.fixture_env(False, runner_env=base)
        self.assertEqual(portal_env["GTK_A11Y"], "none")

    def test_resolve_atspi_application_fails_closed_on_mismatch(self):
        class NoMatch:
            returncode = 1
            stdout = ""
            stderr = "synthetic PID not found in AT-SPI desktop"

        with self.assertRaises(RuntimeError):
            MODULE.resolve_atspi_application(4242, runner=lambda *a, **k: NoMatch())

        class Empty:
            returncode = 0
            stdout = "  \n"
            stderr = ""

        with self.assertRaises(RuntimeError):
            MODULE.resolve_atspi_application(4242, runner=lambda *a, **k: Empty())

        class Found:
            returncode = 0
            stdout = '{"found": "com.steipete.CodexBarGTK", "children": []}'
            stderr = ""

        self.assertEqual(
            MODULE.resolve_atspi_application(4242, runner=lambda *a, **k: Found()),
            "com.steipete.CodexBarGTK",
        )

        class FailedWithName:
            returncode = 1
            stdout = '{"found": "com.steipete.CodexBarGTK", "children": []}'
            stderr = "identity probe failed"

        with self.assertRaises(RuntimeError):
            MODULE.resolve_atspi_application(4242, runner=lambda *a, **k: FailedWithName())

    def test_bridge_driver_requires_verified_application_identity(self):
        with self.assertRaises(ValueError):
            MODULE.BridgeDriver("linux-agent-access", "")
        with self.assertRaises(ValueError):
            MODULE.BridgeDriver("linux-agent-access", None)

    def test_bridge_telemetry_is_bounded_sanitized_and_does_not_invent_sent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "telemetry.json"
            telemetry = MODULE.BoundedTelemetry(path)

            class FakeDone:
                returncode = 0
                stdout = '{"action_count":1,"window_title":"private","content":"secret"}'
                stderr = ""

            driver = MODULE.BridgeDriver(
                "linux-agent-access", "synthetic-app", runner=lambda *a, **k: FakeDone(),
                telemetry=telemetry,
            )
            driver.move(689, 865)
            records = MODULE.json.loads(path.read_text())
            self.assertEqual([record["event"] for record in records],
                             ["bridge_request", "bridge_result"])
            request, result = records
            self.assertEqual(request["coordinates"], [689, 865])
            self.assertLessEqual(request["monotonic_start"], request["timestamp_monotonic"])
            self.assertEqual(result["bridge_return_code"], 0)
            self.assertEqual(result["return_metadata"], {"action_count": 1})
            self.assertNotIn("sent", result["return_metadata"])
            self.assertNotIn("private", path.read_text())
            self.assertNotIn("secret", path.read_text())
            for index in range(100):
                telemetry.add("bounded", index=index)
            self.assertEqual(len(telemetry.entries), telemetry.MAX_ENTRIES)

    def test_move_only_diagnostic_calls_only_one_move_and_preserves_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            preferences = root / "settings.json"
            original = b'{"hidePersonalInfo":false}\n'
            preferences.write_bytes(original)
            state = self.snapshot(
                received=MODULE.time.monotonic() - .2,
                target_geometry=[364, 149, 1000, 740],
            )
            calls = []

            class MoveOnlyBridge:
                def move(self, x, y):
                    calls.append(("move", x, y))
                    state["cursor"] = [x, y]

                def click(self, *_args):
                    calls.append(("click",))
                    raise AssertionError("move-only diagnostic must not click")

            telemetry = MODULE.BoundedTelemetry(root / "telemetry.json")
            result = MODULE.move_only_diagnostic(
                MoveOnlyBridge(), 4242, lambda: state, preferences, telemetry,
                timeout_seconds=0.025,
            )
            self.assertEqual(result, 0)
            self.assertEqual(calls, [("move", 689, 865)])
            self.assertEqual(preferences.read_bytes(), original)
            records = MODULE.json.loads((root / "telemetry.json").read_text())
            self.assertEqual(records[0]["requested"], [689, 865])
            self.assertEqual(records[-1]["event"], "diagnostic_end")
            self.assertTrue(records[-1]["json_unchanged"])

    def test_move_only_fails_before_input_without_target_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            prefs = root / "settings.json"
            prefs.write_text("{}")
            calls = []

            class Bridge:
                def move(self, *_args):
                    calls.append("move")
                def click(self, *_args):
                    calls.append("click")

            state = self.snapshot(
                received=MODULE.time.monotonic() - .2,
                target_geometry=[364, 149, 1000, 740], active=False,
            )
            with self.assertRaisesRegex(RuntimeError, "fresh active"):
                MODULE.move_only_diagnostic(
                    Bridge(), 4242, lambda: state, prefs,
                    MODULE.BoundedTelemetry(root / "telemetry.json"), 0,
                )
            self.assertEqual(calls, [])

    def test_bridge_command_resolution_fails_closed(self):
        self.assertEqual(
            MODULE.resolve_bridge_command(None, exists_fn=lambda c: "/usr/bin/" + c),
            "/usr/bin/linux-agent-access",
        )
        self.assertEqual(
            MODULE.resolve_bridge_command(
                "/opt/bridge", exists_fn=lambda c: None, is_file=lambda p: True),
            "/opt/bridge",
        )
        with self.assertRaises(RuntimeError):
            MODULE.resolve_bridge_command(None, exists_fn=lambda c: None)
        with self.assertRaises(RuntimeError):
            MODULE.resolve_bridge_command("/missing/bridge", exists_fn=lambda c: None)

    def test_guarded_bridge_click_requires_same_kwin_evidence(self):
        calls = []

        class FakeBridge:
            def move(self, x, y):
                calls.append(("move", x, y))
                state["cursor"] = [x, y]
                state["received"] = 100.2

            def click(self, x, y):
                calls.append(("click", x, y))

        state = self.snapshot()

        # Fresh, exact-target evidence: the bridge click goes through.
        # guard_target pins `now` via time.monotonic, so the dead `state`
        # snapshot is only ever exact evidence for the containment/pid checks.
        fresh = self.snapshot(target_geometry=[364, 149, 1000, 740])

        class FreshBridge:
            def move(self, x, y):
                calls.append(("move", x, y))

            def click(self, x, y):
                calls.append(("click", x, y))

        with unittest.mock.patch.object(
                MODULE, "guard_target", return_value=True):
            MODULE.guarded_click_bridge(FreshBridge(), 4242, lambda: fresh, 810, 315)
        self.assertIn(("move", 810, 315), calls)
        self.assertIn(("click", 810, 315), calls)
        _ = state

        calls.clear()
        state = self.snapshot()


    def test_bridge_can_move_from_outside_before_strict_click_guard(self):
        calls = []
        state = self.snapshot(
            target_geometry=[364, 149, 1000, 740],
            cursor=[1727, 84], top_hit=False, received=100.2,
        )

        class Bridge:
            def move(self, x, y):
                calls.append(("move", x, y))
                state.update(cursor=[x, y], top_hit=True)

            def click(self, x, y):
                calls.append(("click", x, y))

        with unittest.mock.patch.object(MODULE.time, "monotonic", return_value=100.4):
            MODULE.guarded_click_bridge(Bridge(), 4242, lambda: state, 810, 315)
        self.assertEqual(calls, [("move", 810, 315), ("click", 810, 315)])

    def test_bridge_never_clicks_if_top_hit_does_not_follow_motion(self):
        calls = []
        state = self.snapshot(
            target_geometry=[364, 149, 1000, 740],
            cursor=[1727, 84], top_hit=False, received=100.2,
        )

        class Bridge:
            def move(self, x, y):
                calls.append(("move", x, y))
                state.update(cursor=[x, y])

            def click(self, x, y):
                calls.append(("click", x, y))

        with unittest.mock.patch.object(
                MODULE.time, "monotonic", side_effect=[100.4, 100.4, 100.4, 103]):
            with self.assertRaisesRegex(RuntimeError, "no click sent"):
                MODULE.guarded_click_bridge(Bridge(), 4242, lambda: state, 810, 315)
        self.assertEqual(calls, [("move", 810, 315)])

if __name__ == "__main__":
    unittest.main()
