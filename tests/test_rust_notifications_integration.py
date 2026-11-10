from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk.controller import AppState, Controller
from codexbar_gtk.data import Pace, RateWindow, provider_usage_from_payload
from codexbar_gtk.prefs import Preferences

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@unittest.skipUnless(EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh")
class RustNotificationIntegrationTests(unittest.TestCase):
    @staticmethod
    def presentation(events):
        fields = ("kind", "id", "title", "body", "used_percent", "provider_id", "account_email", "window_key")
        return [{key: event[key] for key in fields if key in event} for event in events]

    def provider(self, account="fixture@example.invalid"):
        provider = provider_usage_from_payload({"provider": "codex", "usage": {}})
        provider.account_email = account
        provider.windows = [RateWindow(
            key="primary", title="Session", used_percent=100,
            resets_at=NOW + timedelta(hours=24), window_minutes=300,
        )]
        provider.pace = {"primary": Pace(
            stage="behind", delta_percent=4, expected_used_percent=10,
            will_last_to_reset=False, eta_seconds=7200,
        )}
        provider.reset_credits = [{
            "title": "Synthetic credit", "expires_at": NOW + timedelta(hours=22),
        }]
        return provider

    def controllers(self, folder):
        core = importlib.import_module("codexbar_gtk._rust_core")
        path = os.path.join(folder, "settings.json")
        with patch("codexbar_gtk.controller.rust_bridge.extension", return_value=core):
            rust = Controller(Preferences(path), cli=object())
        with patch("codexbar_gtk.controller.rust_bridge.extension", return_value=None):
            python = Controller(Preferences(path), cli=object())
        return rust, python

    def test_typed_events_match_python_reference_and_dedupe(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            state = AppState(providers=[self.provider()])
            events = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(events), self.presentation(python.notification_events(state, NOW)))
            self.assertEqual(events[0]["provider_id"], "codex")
            self.assertEqual(events[0]["window_key"], "primary")
            self.assertEqual(events[0]["account_email"], "fixture@example.invalid")
            self.assertEqual(
                [event["kind"] for event in events],
                ["quota_threshold", "session_exhausted", "predictive_pace", "credit_expiry"],
            )
            self.assertEqual(events[1]["account_email"], "fixture@example.invalid")
            self.assertEqual(events[2]["account_email"], "fixture@example.invalid")
            self.assertTrue(all(event.get("provider_id") == "codex" for event in events))
            self.assertEqual(rust.notification_events(state, NOW), [])
            self.assertEqual(python.notification_events(state, NOW), [])

    def test_policies_run_once_per_successful_snapshot_not_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            state = AppState(providers=[self.provider()], last_updated=NOW.timestamp())
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))
            self.assertEqual(rust.notification_events(state, NOW), [])
            state.last_error = "synthetic failure"
            state.last_updated += 1
            self.assertEqual(rust.notification_events(state, NOW), [])
            self.assertEqual(python.notification_events(state, NOW), [])
            state.last_error = None
            state.last_updated += 1
            state.providers[0].windows[0].used_percent = 10
            self.assertEqual(
                self.presentation(rust.notification_events(state, NOW)),
                self.presentation(python.notification_events(state, NOW)),
            )

    def test_rearm_account_disappearance_and_window_identity_match(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            original = self.provider()
            state = AppState(providers=[original])
            rust.notification_events(state, NOW)
            python.notification_events(state, NOW)

            recovered = self.provider()
            recovered.windows[0].used_percent = 10
            recovered.pace["primary"].will_last_to_reset = True
            state.providers = [recovered]
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))

            state.providers = []
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))

            state.providers = [self.provider(account="second-fixture@example.invalid")]
            events = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(events), self.presentation(python.notification_events(state, NOW)))
            self.assertTrue(any(event["kind"] == "session_exhausted" for event in events))
            exhausted = next(event for event in events if event["kind"] == "session_exhausted")
            self.assertEqual(exhausted["account_email"], "second-fixture@example.invalid")

    def test_unknown_usage_preserves_dedupe_but_known_zero_rearms(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            provider = self.provider()
            provider.windows[0].used_percent = 80
            state = AppState(providers=[provider])
            first_rust = rust.notification_events(state, NOW)
            first_python = python.notification_events(state, NOW)
            self.assertEqual(self.presentation(first_rust), self.presentation(first_python))
            self.assertTrue(any(event["kind"] == "quota_threshold" for event in first_rust))

            provider.windows[0].usage_known = False
            provider.windows[0].used_percent = 0
            unknown_rust = rust.notification_events(state, NOW)
            unknown_python = python.notification_events(state, NOW)
            self.assertEqual(self.presentation(unknown_rust), self.presentation(unknown_python))
            self.assertFalse(any(event["kind"] == "quota_threshold" for event in unknown_rust))

            provider.windows[0].usage_known = True
            provider.windows[0].used_percent = 80
            still_crossed = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(still_crossed), self.presentation(python.notification_events(state, NOW)))
            self.assertFalse(any(event["kind"] == "quota_threshold" for event in still_crossed))

            provider.windows[0].used_percent = 0
            self.assertEqual(
                self.presentation(rust.notification_events(state, NOW)),
                self.presentation(python.notification_events(state, NOW)),
            )
            provider.windows[0].used_percent = 80
            rearmed = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(rearmed), self.presentation(python.notification_events(state, NOW)))
            self.assertTrue(any(event["kind"] == "quota_threshold" for event in rearmed))

    def test_unknown_usage_keeps_exhaustion_identity_until_disappearance(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            state = AppState(providers=[self.provider()])
            first = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(first), self.presentation(python.notification_events(state, NOW)))
            self.assertTrue(any(event["kind"] == "session_exhausted" for event in first))

            unknown = self.provider()
            unknown.windows[0].usage_known = False
            unknown.windows[0].used_percent = 0
            state.providers = [unknown]
            unknown_events = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(unknown_events), self.presentation(python.notification_events(state, NOW)))
            self.assertFalse(any(event["kind"] == "session_exhausted" for event in unknown_events))

            state.providers = [self.provider()]
            still_exhausted = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(still_exhausted), self.presentation(python.notification_events(state, NOW)))
            self.assertFalse(any(event["kind"] == "session_exhausted" for event in still_exhausted))

            state.providers = []
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))
            state.providers = [self.provider()]
            reappeared = rust.notification_events(state, NOW)
            self.assertEqual(self.presentation(reappeared), self.presentation(python.notification_events(state, NOW)))
            self.assertTrue(any(event["kind"] == "session_exhausted" for event in reappeared))

    def test_per_window_disable_still_tracks_quota_rearm_reference_behavior(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            state = AppState(providers=[self.provider()])
            state.providers[0].windows[0].used_percent = 50
            rust.prefs.set("quotaWarningSessionEnabled", True)
            python.prefs.set("quotaWarningSessionEnabled", True)
            self.assertEqual(
                self.presentation(rust.notification_events(state, NOW)),
                self.presentation(python.notification_events(state, NOW)),
            )
            rust.prefs.set("quotaWarningSessionEnabled", False)
            python.prefs.set("quotaWarningSessionEnabled", False)
            state.providers[0].windows[0].used_percent = 10
            self.assertEqual(
                self.presentation(rust.notification_events(state, NOW)),
                self.presentation(python.notification_events(state, NOW)),
            )
            rust.prefs.set("quotaWarningSessionEnabled", True)
            python.prefs.set("quotaWarningSessionEnabled", True)
            state.providers[0].windows[0].used_percent = 30
            rust_events = rust.notification_events(state, NOW)
            python_events = python.notification_events(state, NOW)
            self.assertEqual(self.presentation(rust_events), self.presentation(python_events))
            self.assertTrue(any(event["kind"] == "quota_threshold" for event in rust_events))

    def test_disabled_initial_window_does_not_create_quota_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            state = AppState(providers=[self.provider()])
            state.providers[0].windows[0].used_percent = 80
            rust.prefs.set("quotaWarningSessionEnabled", False)
            python.prefs.set("quotaWarningSessionEnabled", False)
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))
            state.providers[0].windows[0].used_percent = 10
            self.assertEqual(self.presentation(rust.notification_events(state, NOW)), self.presentation(python.notification_events(state, NOW)))
            rust.prefs.set("quotaWarningSessionEnabled", True)
            python.prefs.set("quotaWarningSessionEnabled", True)
            state.providers[0].windows[0].used_percent = 80
            rust_events = rust.notification_events(state, NOW)
            python_events = python.notification_events(state, NOW)
            self.assertEqual(self.presentation(rust_events), self.presentation(python_events))
            self.assertTrue(any(event["kind"] == "quota_threshold" for event in rust_events))

    def test_empty_account_identity_keeps_python_presentation(self):
        with tempfile.TemporaryDirectory() as folder:
            rust, python = self.controllers(folder)
            provider = self.provider(account="")
            state = AppState(providers=[provider])
            rust_events = rust.notification_events(state, NOW)
            python_events = python.notification_events(state, NOW)
            self.assertEqual(self.presentation(rust_events), self.presentation(python_events))
            exhausted = next(event for event in rust_events if event["kind"] == "session_exhausted")
            self.assertEqual(exhausted["body"], "Codex Session is exhausted.")


if __name__ == "__main__":
    unittest.main()
