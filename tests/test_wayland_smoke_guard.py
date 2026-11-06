import importlib.util
import pathlib
import tempfile
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

    def test_accepts_fresh_stable_target(self):
        self.assertTrue(MODULE.guard_target(self.snapshot(), 4242, 810, 315, now=100.2))

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
                "provider-login",
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
             "provider-api-key", "provider-login"},
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

        driver = MODULE.BridgeDriver("linux-agent-access", runner=fake_runner)
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
            "linux-agent-access", runner=lambda argv, **_k: FakeError())
        with self.assertRaises(RuntimeError) as ctx:
            driver.click(860, 332)
        self.assertIn("not active", str(ctx.exception))

        class FakeBadJson:
            returncode = 0
            stdout = "not json"
            stderr = ""

        driver = MODULE.BridgeDriver(
            "linux-agent-access", runner=lambda argv, **_k: FakeBadJson())
        with self.assertRaises(RuntimeError):
            driver.move(860, 332)

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


if __name__ == "__main__":
    unittest.main()
