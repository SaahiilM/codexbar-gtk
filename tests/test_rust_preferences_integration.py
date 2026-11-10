from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk.prefs import DEFAULTS, Preferences

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh")
class RustPreferencesIntegrationTests(unittest.TestCase):
    def make_preferences(self, path: str) -> Preferences:
        core = importlib.import_module("codexbar_gtk._rust_core")
        with patch("codexbar_gtk.prefs.rust_bridge.extension", return_value=core):
            return Preferences(path)

    def test_defaults_match_python_and_settings_round_trip(self):
        core = importlib.import_module("codexbar_gtk._rust_core")
        self.assertEqual(json.loads(core.preferences_defaults_json()), DEFAULTS)

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            prefs = self.make_preferences(path)
            self.assertEqual(prefs.as_dict(), DEFAULTS)
            prefs.set("usageBarsShowUsed", False)
            prefs.set("futurePreference", {"enabled": True})
            self.assertFalse(prefs.get("usageBarsShowUsed"))
            self.assertEqual(prefs.get("missing", "fallback"), "fallback")
            self.assertEqual(Preferences(path).get("usageBarsShowUsed"), False)
            self.assertNotIn("futurePreference", Preferences(path).as_dict())

    def test_portable_import_filters_unknown_keys_and_refresh_values(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = self.make_preferences(os.path.join(folder, "settings.json"))
            prefs.import_document(
                {
                    "version": 1,
                    "preferences": {
                        "refreshFrequency": "15m",
                        "unknownPreference": "ignored",
                    },
                }
            )
            self.assertEqual(prefs.refresh_seconds, 900)
            self.assertFalse(prefs.refresh_is_manual)
            self.assertNotIn("unknownPreference", prefs.as_dict())
            document = prefs.export_document()
            self.assertEqual(document["version"], 1)
            self.assertEqual(document["preferences"]["refreshFrequency"], "15m")
            prefs.import_document({"preferences": {"refreshFrequency": "manual"}})
            self.assertEqual(prefs.refresh_seconds, 0)
            self.assertTrue(prefs.refresh_is_manual)

    def test_unsupported_python_value_falls_back_without_losing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = self.make_preferences(os.path.join(folder, "settings.json"))
            prefs.set("usageBarsShowUsed", False, persist=False)
            value = object()
            prefs.set("pythonOnly", value, persist=False)
            self.assertIsNone(prefs._rust)
            self.assertIs(prefs.get("pythonOnly"), value)
            self.assertFalse(prefs.get("usageBarsShowUsed"))

    def test_storage_errors_are_reported_to_the_python_caller(self):
        with tempfile.TemporaryDirectory() as folder:
            blocker = os.path.join(folder, "not-a-directory")
            with open(blocker, "w", encoding="utf-8") as handle:
                handle.write("file")
            prefs = self.make_preferences(os.path.join(blocker, "settings.json"))
            with self.assertRaises(OSError):
                prefs.save()
