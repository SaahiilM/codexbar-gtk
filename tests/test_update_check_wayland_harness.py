import importlib.util
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/test-native-update-check-wayland.py"
SPEC = importlib.util.spec_from_file_location("update_check_wayland", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REPO_VERSION = pathlib.Path(__file__).resolve().parents[1] / "VERSION"


class UpdateCheckWaylandHarnessTests(unittest.TestCase):
    def test_synthetic_body_increments_build_by_one(self):
        body = MODULE.synthetic_version_body(REPO_VERSION).decode("ascii")
        version = MODULE.parse_version_file(REPO_VERSION)
        lines = dict(
            line.split("=", 1) for line in body.strip().splitlines() if "=" in line
        )
        self.assertEqual(lines["MARKETING_VERSION"], version["MARKETING_VERSION"])
        self.assertEqual(
            int(lines["CURRENT_PROJECT_VERSION"]),
            int(version["CURRENT_PROJECT_VERSION"]) + 1,
        )

    def test_loopback_url_predicate_matches_native_debug_override(self):
        self.assertTrue(MODULE.is_loopback_update_url("http://127.0.0.1:41991/VERSION"))
        self.assertTrue(MODULE.is_loopback_update_url("http://[::1]:41991/VERSION"))
        self.assertFalse(MODULE.is_loopback_update_url("https://127.0.0.1:41991/VERSION"))
        self.assertFalse(MODULE.is_loopback_update_url("http://example.test:41991/VERSION"))
        self.assertFalse(MODULE.is_loopback_update_url("http://127.0.0.2:41991/VERSION"))
        self.assertFalse(MODULE.is_loopback_update_url(""))

    def test_synthetic_server_is_loopback_only_and_records_requests(self):
        server = MODULE.SyntheticVersionServer(REPO_VERSION)
        try:
            self.assertEqual(server.server.server_address[0], "127.0.0.1")
            self.assertTrue(MODULE.is_loopback_update_url(server.url))
            self.assertTrue(server.url.endswith("/VERSION"))
            server.serve_in_thread()
            import urllib.request

            with urllib.request.urlopen(server.url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                payload = response.read().decode("ascii")
            self.assertIn("CURRENT_PROJECT_VERSION=", payload)
            self.assertEqual(server.requests, ["/VERSION"])
        finally:
            server.stop()

    def test_activation_script_targets_exact_pid_and_records_caption(self):
        script = MODULE.activation_script(4242, "Update available")
        self.assertIn("TARGET_PID=4242", script)
        self.assertIn("Number(windows[i].pid)===TARGET_PID", script)
        self.assertIn('indexOf(FRAGMENT)', script)
        self.assertIn("caption", script)
        self.assertIn('"Record",JSON.stringify(state)', script)
        self.assertNotIn("NotifyPointer", script)
        self.assertNotIn("SendEvent", script)

    def test_kwin_js_reports_caption(self):
        self.assertIn("caption", MODULE.KWIN_JS)
        self.assertNotIn("portal_active:!!(a", MODULE.KWIN_JS)

    def test_constants_match_native_action_surface(self):
        self.assertEqual(MODULE.APP_ID, "com.steipete.CodexBarGTK")
        self.assertEqual(MODULE.UPDATE_DIALOG_CAPTION, "Update available")
        self.assertEqual(MODULE.WIRE_PATH, "/VERSION")
        self.assertEqual(MODULE.UPDATE_URL_ENV, "CODEXBAR_NATIVE_TEST_UPDATE_URL")

    def test_harness_never_uses_public_urls(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("VERSION_URL", source.replace("UPDATE_URL_ENV", ""))
        self.assertIn("127.0.0.1", source)


if __name__ == "__main__":
    unittest.main()
