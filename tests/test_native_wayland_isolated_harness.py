import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/test-native-wayland-isolated.py"
SPEC = importlib.util.spec_from_file_location("native_wayland_isolated", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeWaylandIsolatedHarnessTests(unittest.TestCase):
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
                "XDG_RUNTIME_DIR": "/run/user/1000", "GDK_BACKEND": "x11",
                "GSK_RENDERER": "gl", "GTK_USE_PORTAL": "1",
            }, root / "home", root / "runtime", "wayland-private",
               root / "fake-codexbar", "unix:path=/private/session-bus")
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
