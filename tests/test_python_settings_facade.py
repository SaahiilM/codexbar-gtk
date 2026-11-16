"""Python parity coverage for settings facade operations with synthetic data."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk.cli import ProviderStatusEntry
from codexbar_gtk.controller import Controller
from codexbar_gtk.prefs import Preferences


class FixtureCli:
    def config_providers(self):
        return [ProviderStatusEntry("codex", True, "Fixture Codex", True)]

    def hooks(self):
        return {
            "enabled": True,
            "events": [{"event": "session-start", "executable": "fixture-hook", "enabled": True}],
        }

    def plugins(self):
        return [{"id": "fixture-plugin", "name": "Fixture Plugin", "version": "1"}]

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

if __name__ == "__main__":
    unittest.main()
