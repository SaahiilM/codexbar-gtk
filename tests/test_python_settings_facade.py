"""Python parity coverage for settings facade operations with synthetic data."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk.cli import CLIResult, ProviderStatusEntry
from codexbar_gtk.controller import Controller
from codexbar_gtk.prefs import Preferences


class FixtureCli:
    def __init__(self) -> None:
        self.actions: list[tuple] = []

    def config_providers(self):
        return [ProviderStatusEntry("codex", True, "Fixture Codex", True)]

    def hooks(self):
        return {
            "enabled": True,
            "events": [{"event": "session-start", "executable": "fixture-hook", "enabled": True}],
        }

    def plugins(self):
        return [{"id": "fixture-plugin", "name": "Fixture Plugin", "version": "1"}]

    def enable_provider(self, provider):
        self.actions.append(("enable", provider))
        return CLIResult(0, "", "")

    def disable_provider(self, provider):
        self.actions.append(("disable", provider))
        return CLIResult(0, "", "")

    def set_source(self, provider, source):
        self.actions.append(("set-source", provider, source))
        return CLIResult(0, "", "")

    def set_api_key(self, provider, secret):
        self.actions.append(("set-api-key", provider, secret))
        return CLIResult(0, "", "")

    def set_hooks_enabled(self, enabled):
        self.actions.append(("hooks", enabled))
        return CLIResult(0, "", "")


class PythonSettingsFacadeTests(unittest.TestCase):
    def test_python_cli_reconfigure_preserves_permissive_path_and_timezone_behavior(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codexbar-settings-reconfigure-python-") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HOME": str(root)}), patch(
                "codexbar_gtk.controller.rust_bridge.extension", return_value=None
            ), patch("codexbar_gtk.prefs.rust_bridge.extension", return_value=None), patch(
                "codexbar_gtk.controller.default_cli_path", return_value="fixture-default-cli"
            ):
                prefs = Preferences(str(root / "settings.json"))
                cli = FixtureCli()
                controller = Controller(prefs, cli=cli)
                with patch.object(controller, "refresh") as refresh:
                    outcome = controller.settings_reconfigure_cli(
                        "  /missing/fixture-cli  ", "Not/A/Validated-Timezone"
                    )
                    self.assertEqual(
                        outcome, {"applied": True, "refresh_queued": True}
                    )
                    self.assertEqual(cli.executable, "/missing/fixture-cli")
                    self.assertEqual(cli.timezone, "Not/A/Validated-Timezone")
                    self.assertEqual(prefs.get("cliPath"), "/missing/fixture-cli")
                    self.assertEqual(
                        prefs.get("costUsageBucketTimeZone"),
                        "Not/A/Validated-Timezone",
                    )
                    refresh.assert_called_once_with(force=True)

                    controller.settings_reconfigure_cli("/another/fixture-cli", None)
                    self.assertEqual(cli.executable, "/another/fixture-cli")
                    self.assertEqual(cli.timezone, "Not/A/Validated-Timezone")
                    self.assertEqual(
                        prefs.get("costUsageBucketTimeZone"),
                        "Not/A/Validated-Timezone",
                    )

                    controller.settings_reconfigure_cli(None, "")
                    self.assertEqual(cli.executable, "/another/fixture-cli")
                    self.assertIsNone(cli.timezone)
                    self.assertEqual(prefs.get("cliPath"), "/another/fixture-cli")

                    controller.settings_reconfigure_cli("", None)
                    self.assertEqual(cli.executable, "fixture-default-cli")
                    self.assertIsNone(cli.timezone)
                    self.assertEqual(prefs.get("cliPath"), "")
                    self.assertEqual(prefs.get("costUsageBucketTimeZone"), "")
                    self.assertEqual(refresh.call_count, 4)

    def test_python_parity_sections_actions_preferences_and_launch_at_login(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codexbar-settings-python-") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HOME": str(root)}), patch(
                "codexbar_gtk.controller.rust_bridge.extension", return_value=None
            ), patch("codexbar_gtk.prefs.rust_bridge.extension", return_value=None):
                prefs = Preferences(str(root / ".config/codexbar-gtk/settings.json"))
                cli = FixtureCli()
                controller = Controller(prefs, cli=cli)

                snapshot = controller.settings_snapshot()
                self.assertEqual(snapshot["providers"]["value"][0]["provider_id"], "codex")
                self.assertTrue(snapshot["hooks"]["value"]["enabled"])
                self.assertEqual(snapshot["plugins"]["value"][0]["id"], "fixture-plugin")
                self.assertEqual(snapshot["launch_at_login"]["value"], {"enabled": False})

                controller.settings_provider_action("enable", "codex")
                controller.settings_provider_action("set-source", "codex", "web")
                controller.settings_set_api_key("codex", "fixture-key")
                controller.settings_set_hooks_enabled(False)
                self.assertEqual(
                    cli.actions,
                    [
                        ("enable", "codex"),
                        ("set-source", "codex", "web"),
                        ("set-api-key", "codex", "fixture-key"),
                        ("hooks", False),
                    ],
                )

                export = root / "selected-export.json"
                prefs.set("showTray", False)
                controller.preferences_export_to(str(export))
                document = json.loads(export.read_text(encoding="utf-8"))
                self.assertEqual(document["version"], 1)
                self.assertFalse(document["preferences"]["showTray"])
                prefs.set("showTray", True)
                controller.preferences_import_from(str(export))
                self.assertFalse(prefs.get("showTray"))
                controller.preferences_reset()
                self.assertTrue(prefs.get("showTray"))

                state = controller.set_launch_at_login(True, "/tmp/fixture-codexbar")
                self.assertEqual(state, {"enabled": True})
                self.assertTrue(prefs.get("launchAtLogin"))
                self.assertEqual(controller.launch_at_login_state(), {"enabled": True})
                self.assertTrue(
                    (root / ".config/autostart/codexbar-gtk.desktop").is_file()
                )


if __name__ == "__main__":
    unittest.main()
