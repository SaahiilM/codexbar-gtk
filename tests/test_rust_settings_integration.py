"""Fixture-only PyO3 coverage for the shared Rust settings facade."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk import rust_bridge


@unittest.skipUnless(rust_bridge.extension() is not None, "Rust extension is opt-in")
class RustSettingsIntegrationTests(unittest.TestCase):
    def _controller(self, root: Path, *, provider_status: int = 0):
        core = rust_bridge.extension()
        script = f"""#!/bin/sh
case "$1/$2" in
  config/providers) printf 'codex: enabled (Fixture Codex)\\n'; exit {provider_status};;
  hooks/list) printf '{{"enabled":true,"events":[{{"event":"session-start","executable":"fixture-hook","enabled":true}}]}}'; exit 0;;
  plugins/list) printf '[{{"id":"fixture-plugin","name":"Fixture Plugin","version":"1"}}]'; exit 0;;
  config/set-source) exit 0;;
  config/set-api-key) printf 'fixture command detail\\n' >&2; exit 6;;
  hooks/disable) exit 0;;
esac
case "$1" in
  usage|cost|sessions) printf '[]\\n'; exit 0;;
  --version) printf 'fixture-cli 1.0\\n'; exit 0;;
esac
exit 0
"""
        executable = root / "codexbar-fixture"
        executable.write_text(script, encoding="utf-8")
        executable.chmod(0o700)
        preferences = core.PreferencesStore(str(root / ".config/codexbar-gtk/settings.json"))
        history = core.HistoryStore(str(root / ".local/share/codexbar/history.jsonl"), 365)
        currencies = core.CurrencyConverter(str(root / ".cache/codexbar/rates.json"))
        return core.RefreshController(str(executable), None, preferences, history, currencies), preferences

    def test_snapshot_actions_preference_files_and_launch_at_login(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codexbar-settings-rust-") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HOME": str(root)}):
                controller, preferences = self._controller(root)
                try:
                    snapshot = json.loads(controller.settings_snapshot_json())
                    self.assertEqual(snapshot["providers"]["value"][0]["provider_id"], "codex")
                    self.assertTrue(snapshot["hooks"]["value"]["enabled"])
                    self.assertEqual(snapshot["plugins"]["value"][0]["id"], "fixture-plugin")
                    self.assertEqual(snapshot["launch_at_login"]["value"], {"enabled": False})

                    controller.settings_provider_action("set-source", "codex", "web")
                    controller.settings_set_hooks_enabled(False)
                    with self.assertRaisesRegex(RuntimeError, "command_rejected \\(settings_set_api_key\\)") as caught:
                        controller.settings_set_api_key("codex", "fixture-only-key")
                    self.assertNotIn("fixture-only", str(caught.exception))

                    preferences.set_json("showTray", "false", True)
                    export = root / "chosen-export.json"
                    controller.preferences_export_to(str(export))
                    document = json.loads(export.read_text(encoding="utf-8"))
                    self.assertEqual(document["version"], 1)
                    self.assertFalse(document["preferences"]["showTray"])
                    preferences.set_json("showTray", "true", True)
                    controller.preferences_import_from(str(export))
                    self.assertEqual(preferences.get_json("showTray"), "false")
                    controller.preferences_reset()
                    self.assertEqual(preferences.get_json("showTray"), "true")

                    self.assertEqual(controller.launch_at_login_state(), {"enabled": False})
                    self.assertEqual(
                        controller.set_launch_at_login(True, "/tmp/fixture CodexBar"),
                        {"enabled": True},
                    )
                    self.assertEqual(preferences.get_json("launchAtLogin"), "true")
                    self.assertEqual(controller.launch_at_login_state(), {"enabled": True})
                    desktop = root / ".config/autostart/codexbar-gtk.desktop"
                    self.assertIn('Exec="/tmp/fixture CodexBar"', desktop.read_text(encoding="utf-8"))

                    invalid = root / "invalid.json"
                    invalid.write_text("{", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "preferences_document \\(settings_preferences_import\\)") as invalid_error:
                        controller.preferences_import_from(str(invalid))
                    self.assertNotIn(str(invalid), str(invalid_error.exception))
                finally:
                    controller.request_shutdown()

    def test_nonzero_valid_provider_output_is_a_section_error_with_partial_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codexbar-settings-partial-") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HOME": str(root)}):
                controller, _preferences = self._controller(root, provider_status=7)
                try:
                    snapshot = json.loads(controller.settings_snapshot_json())
                    self.assertIsNone(snapshot["providers"]["value"])
                    self.assertEqual(
                        snapshot["providers"]["error"],
                        {"category": "command_rejected", "operation": "settings_providers"},
                    )
                    self.assertTrue(snapshot["hooks"]["value"]["enabled"])
                    self.assertEqual(snapshot["plugins"]["value"][0]["id"], "fixture-plugin")
                finally:
                    controller.request_shutdown()

    def test_reconfigure_commits_and_queues_refresh_with_new_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codexbar-settings-reconfigure-rust-") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HOME": str(root)}):
                controller, preferences = self._controller(root)
                replacement = root / "codexbar-replacement"
                replacement.write_text(
                    '''#!/bin/sh
case "$1/$2" in
  config/providers) printf 'fixture-new: enabled (Fixture New)\\n'; exit 0;;
  hooks/list) printf '{"enabled":false,"events":[]}'; exit 0;;
  plugins/list) printf '[]'; exit 0;;
esac
case "$1" in
  usage|cost|sessions) printf '[]\\n'; exit 0;;
  --version) printf 'fixture-cli 2.0 %s\\n' "${TZ-unset}"; exit 0;;
esac
exit 0
''',
                    encoding="utf-8",
                )
                replacement.chmod(0o700)
                try:
                    before_path = preferences.get_json("cliPath")
                    before_timezone = preferences.get_json("costUsageBucketTimeZone")
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "invalid_input \\(settings_cli_reconfigure\\)",
                    ):
                        controller.settings_reconfigure_cli(
                            str(root / "missing-cli"), "Pacific/Chatham"
                        )
                    self.assertEqual(preferences.get_json("cliPath"), before_path)
                    self.assertEqual(
                        preferences.get_json("costUsageBucketTimeZone"), before_timezone
                    )

                    outcome = controller.settings_reconfigure_cli(
                        f"  {replacement}  ", None
                    )
                    self.assertEqual(
                        outcome, {"applied": True, "refresh_queued": True}
                    )
                    self.assertEqual(
                        preferences.get_json("cliPath"), json.dumps(str(replacement))
                    )

                    system_timezone = os.environ.get("TZ", "unset")
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        envelope = json.loads(controller.state_json())
                        snapshot = envelope.get("snapshot")
                        if snapshot and snapshot.get("version") == f"fixture-cli 2.0 {system_timezone}":
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("path-only refresh did not use the replacement executable")

                    outcome = controller.settings_reconfigure_cli(
                        None, "Pacific/Chatham"
                    )
                    self.assertEqual(
                        outcome, {"applied": True, "refresh_queued": True}
                    )
                    self.assertEqual(
                        preferences.get_json("cliPath"), json.dumps(str(replacement))
                    )
                    self.assertEqual(
                        preferences.get_json("costUsageBucketTimeZone"),
                        json.dumps("Pacific/Chatham"),
                    )
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        envelope = json.loads(controller.state_json())
                        snapshot = envelope.get("snapshot")
                        if snapshot and snapshot.get("version") == "fixture-cli 2.0 Pacific/Chatham":
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("timezone-only refresh did not preserve the replacement executable")

                    settings = json.loads(controller.settings_snapshot_json())
                    self.assertEqual(
                        settings["providers"]["value"][0]["provider_id"],
                        "fixture-new",
                    )
                finally:
                    controller.request_shutdown()


if __name__ == "__main__":
    unittest.main()
