"""Fixture-only PyO3 coverage for Rust spend and tray projections."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from codexbar_gtk import rust_bridge


@unittest.skipUnless(rust_bridge.extension() is not None, "Rust extension is opt-in")
class RustPresentationIntegrationTests(unittest.TestCase):
    def test_facade_projects_snapshot_and_reads_shared_preferences(self) -> None:
        core = rust_bridge.extension()
        self.assertIsNotNone(core)
        usage = json.dumps(
            [
                {
                    "provider": "codex",
                    "rateWindowLabels": {"primary": "5h", "secondary": "Weekly"},
                    "usage": {
                        "primary": {
                            "usedPercent": 42,
                            "windowMinutes": 300,
                            "resetsAt": "2026-10-30T17:00:00Z",
                        },
                        "secondary": {"windowMinutes": 10080},
                    },
                }
            ]
        )
        costs = json.dumps(
            [
                {
                    "provider": "codex",
                    "currencyCode": "USD",
                    "totalCost": 12.0,
                    "totalTokens": 900,
                    "sessionCostUSD": 1.5,
                    "sessionTokens": 15,
                    "last30DaysCostUSD": 4.0,
                    "last30DaysTokens": 300,
                    "coverage": {"priced": 3, "unpriced": 1},
                    "provenance": "fixture_history",
                    "daily": [{"date": "2026-10-30", "totalCost": 12.0}],
                    "projects": [
                        {"name": "synthetic-project", "totalCost": 1.0, "totalTokens": 20},
                        {"name": "unknown-cost-project", "totalTokens": 7},
                        {"name": "known-zero-project", "totalCost": 0, "totalTokens": 0},
                    ],
                    "models": [
                        {"modelName": "synthetic-model", "cost": 2.0, "totalTokens": 10},
                        {"name": "unknown-cost-model", "totalTokens": 5},
                        {"name": "known-zero-model", "cost": 0, "totalTokens": 0},
                        {"name": "fallback-zero-model", "cost": 0, "totalCost": 3, "totalTokens": 8},
                    ],
                }
            ]
        )
        executable_text = f"""#!/bin/sh
case "$1" in
  usage) printf '%s\\n' '{usage}';;
  cost) printf '%s\\n' '{costs}';;
  sessions) printf '%s\\n' '[]';;
  --version) printf '%s\\n' 'fixture-1.0';;
  *) exit 2;;
esac
"""

        with tempfile.TemporaryDirectory(prefix="codexbar-b13-presentation-") as directory:
            root = Path(directory)
            executable = root / "codexbar-fixture"
            executable.write_text(executable_text, encoding="utf-8")
            executable.chmod(0o700)
            preferences = core.PreferencesStore(str(root / "settings.json"))
            preferences.set_json("spendTimeRange", '"7d"', True)
            preferences.set_json("preferredCurrencyCode", '"EUR"', True)
            preferences.set_json("unifiedIconSource", '"automatic"', True)
            preferences.set_json("menuBarIconStyle", '"iconPercent"', True)
            preferences.set_json("switcherRowsOption", '"all"', True)
            history = core.HistoryStore(str(root / "history.jsonl"), 365)
            currencies = core.CurrencyConverter(str(root / "rates.json"))
            controller = core.RefreshController(
                str(executable), None, preferences, history, currencies
            )
            try:
                deadline = time.monotonic() + 8
                snapshot = None
                while time.monotonic() < deadline:
                    envelope = json.loads(controller.state_json())
                    if envelope.get("snapshot") is not None:
                        snapshot = envelope["snapshot"]
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(snapshot, "fixture controller did not publish a snapshot")

                spend = json.loads(controller.spend_view_model_json())
                self.assertEqual(spend["selected_range"], "7 days")
                self.assertEqual(spend["source_currency"], "USD")
                self.assertEqual(spend["display_currency"], "EUR")
                self.assertEqual(spend["total"]["source_amount"], 12.0)
                self.assertAlmostEqual(spend["total"]["display_amount"], 12.0 * 0.92)
                self.assertTrue(spend["tokens"]["known"])
                self.assertEqual(spend["tokens"]["value"], 900)
                unknown_project = next(
                    row for row in spend["projects"] if row["name"] == "unknown-cost-project"
                )
                self.assertIsNone(unknown_project["source_cost"])
                self.assertIsNone(unknown_project["display_cost"])
                self.assertFalse(unknown_project["cost_known"])
                unknown_model = next(
                    row for row in spend["models"] if row["name"] == "unknown-cost-model"
                )
                self.assertIsNone(unknown_model["source_cost"])
                self.assertIsNone(unknown_model["display_cost"])
                self.assertFalse(unknown_model["cost_known"])
                known_zero_project = next(
                    row for row in spend["projects"] if row["name"] == "known-zero-project"
                )
                self.assertEqual(known_zero_project["source_cost"], 0.0)
                self.assertEqual(known_zero_project["display_cost"], 0.0)
                self.assertTrue(known_zero_project["cost_known"])
                known_zero_model = next(
                    row for row in spend["models"] if row["name"] == "known-zero-model"
                )
                self.assertEqual(known_zero_model["source_cost"], 0.0)
                self.assertEqual(known_zero_model["display_cost"], 0.0)
                self.assertTrue(known_zero_model["cost_known"])
                fallback_zero_model = next(
                    row for row in spend["models"] if row["name"] == "fallback-zero-model"
                )
                self.assertEqual(fallback_zero_model["source_cost"], 3.0)
                self.assertAlmostEqual(fallback_zero_model["display_cost"], 3.0 * 0.92)
                self.assertTrue(fallback_zero_model["cost_known"])

                tray = json.loads(controller.tray_summary_json())
                self.assertEqual(tray["unified_icon_source"], "automatic")
                self.assertEqual(tray["menu_bar_icon_style"], "iconPercent")
                self.assertEqual(tray["switcher_rows_option"], "all")
                self.assertEqual(tray["selected_provider_id"], "codex")
                self.assertEqual(tray["selected_window_key"], "primary")
                self.assertEqual(tray["used_percent"], 42.0)
                self.assertTrue(tray["available"])
            finally:
                controller.request_shutdown()


if __name__ == "__main__":
    unittest.main()
