"""Parity checks for provider ordering and tray selection in Rust opt-in mode."""

from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk.controller import Controller, automatic_tray_selection
from codexbar_gtk.data import Pace, RateWindow, provider_usage_from_payload

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


class _Preferences:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@unittest.skipUnless(EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh")
class RustOrderingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = importlib.import_module("codexbar_gtk._rust_core")
        self.now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def provider(provider_id, windows, pace=None):
        provider = provider_usage_from_payload({"provider": provider_id, "usage": {}})
        provider.windows = windows
        provider.pace = pace or {}
        return provider

    def window(
        self, key, used, *, placeholder=False, known=True, minutes=None, reset_hours=None
    ):
        return RateWindow(
            key=key,
            title=key.title(),
            used_percent=used,
            window_minutes=minutes,
            resets_at=self.now + timedelta(hours=reset_hours) if reset_hours else None,
            is_placeholder=placeholder,
            usage_known=known,
        )

    def test_saved_order_hidden_ids_and_unspecified_order_match_python(self):
        providers = [
            self.provider("claude", [self.window("primary", 20)]),
            self.provider("codex", [self.window("primary", 30)]),
            self.provider("gemini", [self.window("primary", 40)]),
            self.provider("openai", [self.window("primary", 50)]),
        ]
        prefs = _Preferences({"providerOrder": ["openai", "codex"], "hiddenProviders": ["gemini"]})
        controller = Controller(prefs)
        results = []
        for core in (None, self.core):
            with patch("codexbar_gtk.controller.extension", return_value=core):
                results.append([item.provider_id for item in controller._ordered(providers)])
        self.assertEqual(results, [["openai", "codex", "claude"]] * 2)

    def test_tray_selection_preserves_depletion_eta_and_placeholder_policy(self):
        fast = self.provider(
            "codex",
            [self.window("primary", 45, minutes=300, reset_hours=24)],
            {"primary": Pace(expected_used_percent=10, eta_seconds=2 * 3600)},
        )
        slow = self.provider(
            "claude",
            [self.window("primary", 70, minutes=300, reset_hours=24)],
            {"primary": Pace(expected_used_percent=10, eta_seconds=5 * 3600)},
        )
        full = self.provider("gemini", [self.window("primary", 100)])
        placeholder = self.provider(
            "placeholder", [self.window("primary", 100, placeholder=True)]
        )
        providers = [slow, fast, placeholder]
        tied = [
            self.provider("first", [self.window("primary", 55)]),
            self.provider("second", [self.window("primary", 55)]),
        ]
        results = []
        for core in (None, self.core):
            with patch("codexbar_gtk.controller.extension", return_value=core):
                choice = automatic_tray_selection(providers, now=self.now)
                depleted = automatic_tray_selection([fast, full], now=self.now)
                first_tie = automatic_tray_selection(tied, now=self.now)
                results.append(
                    (
                        (choice[0].provider_id, choice[1].key) if choice else None,
                        (depleted[0].provider_id, depleted[1].key) if depleted else None,
                        (first_tie[0].provider_id, first_tie[1].key) if first_tie else None,
                        automatic_tray_selection([placeholder], now=self.now),
                    )
                )
        self.assertEqual(
            results[0][:3],
            (("codex", "primary"), ("gemini", "primary"), ("first", "primary")),
        )
        self.assertEqual(results[1][:3], results[0][:3])
        self.assertIsNone(results[0][3])
        self.assertIsNone(results[1][3])

    def test_unknown_error_and_known_zero_eligibility_match_python_and_rust(self):
        errored = self.provider("errored", [self.window("primary", 100)])
        errored.error = "fixture error"
        unknown = self.provider("unknown", [self.window("unknown", 100, known=False)])
        known_zero = self.provider("known-zero", [self.window("known-zero", 0)])
        providers = [errored, unknown, known_zero]

        choices = []
        for core in (None, self.core):
            with patch("codexbar_gtk.controller.extension", return_value=core):
                selected = automatic_tray_selection(providers, now=self.now)
                no_eligible = automatic_tray_selection([unknown], now=self.now)
                choices.append(
                    (
                        (selected[0].provider_id, selected[1].key) if selected else None,
                        no_eligible,
                    )
                )

        self.assertEqual(choices[0], (("known-zero", "known-zero"), None))
        self.assertEqual(choices[1], choices[0])


if __name__ == "__main__":
    unittest.main()
