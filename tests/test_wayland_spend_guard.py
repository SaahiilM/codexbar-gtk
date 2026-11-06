import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/test-native-spend-wayland.py"
SPEC = importlib.util.spec_from_file_location("wayland_spend_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SpendWaylandGuardTests(unittest.TestCase):
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
            {"received": 100.1},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(MODULE.guard_target(self.snapshot(**changes), 4242, 810, 315, now=100.2))

    def test_window_geometry_rejects_coordinates_outside_target(self):
        state = self.snapshot(target_geometry=[100, 200, 900, 700])
        self.assertTrue(MODULE.target_window_contains(state, 810, 315))
        self.assertFalse(MODULE.target_window_contains(state, 1000, 315))
        self.assertFalse(MODULE.target_window_contains(state, 99, 200))
        self.assertFalse(MODULE.target_window_contains(self.snapshot(), 810, 315))

    def test_spend_axes_cover_four_ranges_and_three_modes(self):
        actions = MODULE.WAYLAND_SPEND_ACTIONS
        self.assertEqual(
            {k for k, v in actions.items() if v["kind"] == "range"},
            {"range-7-days", "range-30-days", "range-90-days", "range-all"},
        )
        self.assertEqual(
            {k for k, v in actions.items() if v["kind"] == "mode"},
            {"mode-daily", "mode-weekly", "mode-cumulative"},
        )
        self.assertEqual(
            {v["value"] for v in actions.values() if v["kind"] == "range"},
            {"7 days", "30 days", "90 days", "All"},
        )
        self.assertEqual(
            {v["value"] for v in actions.values() if v["kind"] == "mode"},
            {"Daily", "Weekly", "Cumulative"},
        )
        self.assertEqual(
            set(MODULE.WAYLAND_SPEND_STATES),
            {"loading", "success", "partial", "empty", "retained-error"},
        )

    def test_spend_point_is_derived_inside_spend_window(self):
        point = MODULE.spend_point_from_geometry([0, 0, 1080, 820], 0.5, 0.4)
        self.assertEqual(point, (540, 328))
        self.assertTrue(MODULE.target_window_contains(
            self.snapshot(target_geometry=[364, 149, 1080, 820]), *point))

    def test_spend_point_rejects_bad_geometry_and_fractions(self):
        with self.assertRaises(ValueError):
            MODULE.spend_point_from_geometry(None, 0.5, 0.5)
        with self.assertRaises(ValueError):
            MODULE.spend_point_from_geometry([0, 0, 0, 820], 0.5, 0.5)
        with self.assertRaises(ValueError):
            MODULE.spend_point_from_geometry([0, 0, 1080, 820], 0.0, 0.5)
        with self.assertRaises(ValueError):
            MODULE.spend_point_from_geometry([0, 0, 1080, 820], 0.5, 1.0)
        # Fractional KWin origins still yield integer coordinates.
        fractional = MODULE.spend_point_from_geometry(
            [432, 175.625, 1080, 820], 0.5, 0.4)
        self.assertTrue(all(isinstance(v, int) for v in fractional))

    def test_focus_recovery_targets_only_spend_window(self):
        script = MODULE.activation_script(4242)
        self.assertIn("TARGET_PID=4242", script)
        self.assertIn('indexOf("Usage & Spend")>=0', script)
        self.assertIn("workspace.activeWindow=target", script)
        self.assertIn('"Record",JSON.stringify(state)', script)
        self.assertNotIn("CodexBar Settings", script)
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

    def test_spend_fixture_uses_synthetic_only_markers(self):
        script = MODULE.spend_fixture_script("2026-11-05", "2026-11-04")
        self.assertIn("Synthetic Workspace", script)
        self.assertIn("Synthetic Model", script)
        self.assertNotIn("api_key", script.lower())
        self.assertNotIn("oauth", script.lower())

    def test_retained_error_fixture_sequence_covers_retries_and_settle(self):
        # The failure marker fires before the backend publishes the
        # retained-error view state; the state wait must cover the
        # initial scan plus its per-provider retries (3 cost calls)
        # and a view-state settle before the capture.
        source = pathlib.Path(MODULE.__file__).read_text(encoding="utf-8")
        self.assertIn("wait_cost_calls_at_least(cost_calls_path, 4", source)
        self.assertIn("neighbouring frame", source)

    def test_retained_error_arms_failure_only_after_initial_success(self):
        # Retained-error must start from successful controller state:
        # the initial cost scan completes (cost_done) before the fail
        # marker is armed and the central refresh is dispatched. A
        # pre-seeded fail marker would leave no retained data at all.
        source = pathlib.Path(MODULE.__file__).read_text(encoding="utf-8")
        retained = source[source.index('elif args.state == "retained-error":'):]
        self.assertLess(
            retained.index("wait_cost(cost_done)"),
            retained.index('fail_cost.write_text("")'),
        )
        self.assertLess(
            retained.index('fail_cost.write_text("")'),
            retained.index(
                '["gapplication", "action", "com.steipete.CodexBarGTK", "refresh"]'
            ),
        )
        self.assertNotIn('if args.state in ("retained-error",):', source)
        # The central refresh dispatches until, not just when, the
        # failure-completed controller state is known.
        self.assertIn("wait_cost(cost_failure_done", retained)

    def test_state_capture_requires_active_spend_window(self):
        # A state capture of a foreign/covert window is non-evidence:
        # the capture helper must fail closed unless the synthetic
        # Spend PID is active (same gate as the baseline capture).
        source = pathlib.Path(MODULE.__file__).read_text(encoding="utf-8")
        self.assertIn("def capture_state_screenshot():", source)
        self.assertIn("active_target(spend_state, app.pid)", source)
        self.assertIn("synthetic Spend was not active for state capture", source)


if __name__ == "__main__":
    unittest.main()


class SpendFixtureSubprocessTests(unittest.TestCase):
    """Execute the generated cost fixture for each scripted state."""

    MARKERS = (
        "cost-done", "cost-failure-done", "partial-cost",
        "empty-cost", "fail-cost",
    )

    def make_fixture(self, root):
        fake = root / "codexbar"
        fake.write_text(MODULE.spend_fixture_script("2026-11-06", "2026-11-05"))
        fake.chmod(0o700)
        env = dict(os.environ)
        env.update(
            NATIVE_SPEND_CALLS=str(root / "calls.log"),
            NATIVE_SPEND_COST_CALLS=str(root / "cost-calls.log"),
            NATIVE_SPEND_COST_DONE=str(root / "cost-done"),
            NATIVE_SPEND_COST_FAILURE_DONE=str(root / "cost-failure-done"),
            NATIVE_SPEND_PARTIAL_COST=str(root / "partial-cost"),
            NATIVE_SPEND_EMPTY_COST=str(root / "empty-cost"),
            NATIVE_SPEND_FAIL_COST=str(root / "fail-cost"),
            NATIVE_SPEND_DELAY_COST=str(root / "delay-cost"),
            NATIVE_SPEND_RELEASE_COST=str(root / "release-cost"),
        )
        return fake, env

    def run_cost(self, fake, env, root, *markers):
        for name in ("release-cost", "delay-cost"):
            (root / name).unlink(missing_ok=True)
        for name in ("cost-done", "cost-failure-done",
                     "partial-cost", "empty-cost", "fail-cost"):
            (root / name).unlink(missing_ok=True)
        for marker in markers:
            (root / marker).write_text("")
        return subprocess.run(
            [str(fake), "cost"], capture_output=True, text=True,
            env=env, timeout=10,
        )

    def test_success_payload_is_valid_json_with_known_zero_and_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fake, env = self.make_fixture(root)
            result = self.run_cost(fake, env, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "cost-done").exists())
            payloads = json.loads(result.stdout)
            self.assertEqual(len(payloads), 1)
            entry = payloads[0]
            self.assertEqual(entry["provider"], "codex")
            self.assertNotIn("historyCoverageIsEstablished", entry)
            self.assertEqual(entry["totalCost"], 12.5)
            self.assertEqual(entry["coverage"], {"priced": 3, "unpriced": 1})
            # Yesterday's day is an explicit known zero, not missing.
            yesterday = next(
                d for d in entry["daily"] if d["date"] == "2026-11-05"
            )
            self.assertEqual(yesterday, {"date": "2026-11-05",
                                         "totalCost": 0, "totalTokens": 0})

    def test_partial_payload_sets_coverage_not_established(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fake, env = self.make_fixture(root)
            result = self.run_cost(fake, env, root, "partial-cost")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "cost-done").exists())
            entry = json.loads(result.stdout)[0]
            # The JSON property name must survive shell generation.
            self.assertIs(entry["historyCoverageIsEstablished"], False)
            self.assertEqual(entry["coverage"], {"priced": 3, "unpriced": 1})

    def test_empty_payload_is_valid_json_empty_array(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fake, env = self.make_fixture(root)
            result = self.run_cost(fake, env, root, "empty-cost")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "cost-done").exists())
            self.assertEqual(json.loads(result.stdout), [])

    def test_failure_payload_exits_nonzero_with_failure_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fake, env = self.make_fixture(root)
            result = self.run_cost(fake, env, root, "fail-cost")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")
            self.assertTrue((root / "cost-failure-done").exists())
            self.assertFalse((root / "cost-done").exists())

    def test_success_then_failure_on_same_fixture_rearms_failure_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fake, env = self.make_fixture(root)
            first = self.run_cost(fake, env, root)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue((root / "cost-done").exists())
            second = self.run_cost(fake, env, root, "fail-cost")
            self.assertNotEqual(second.returncode, 0)
            self.assertTrue((root / "cost-failure-done").exists())
            # The failing pass leaves no new success marker.
            self.assertFalse((root / "cost-done").exists())
