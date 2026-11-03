import importlib.util
import pathlib
import tempfile
import unittest


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

    def test_general_switch_actions_are_allowlisted_and_geometry_derived(self):
        actions = MODULE.WAYLAND_SWITCH_ACTIONS
        self.assertEqual(
            set(actions),
            {"refresh-when-panel-opens", "show-panel-on-start", "start-at-login"},
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


if __name__ == "__main__":
    unittest.main()
