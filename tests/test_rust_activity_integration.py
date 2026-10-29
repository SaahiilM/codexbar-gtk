"""Parity checks for the optional Rust-backed spend activity helpers."""

from __future__ import annotations

import importlib
import json
import os
import unittest
from datetime import date
from pathlib import Path

from codexbar_gtk import activity, rust_bridge

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh")
class RustActivityIntegrationTests(unittest.TestCase):
    def test_adapter_matches_rust_activity_functions(self) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        values = [0, 1, 25, 50, 75, 100, -4]
        self.assertEqual(activity.activity_levels(values), core.activity_levels(values))

        start = date(2026, 10, 18)
        today = date(2026, 10, 27)
        dated_values = {
            start: 3,
            date(2026, 10, 19): -2,
            date(2026, 10, 20): 5,
            date(2026, 10, 25): 4,
            date(2026, 10, 28): 99,
        }
        rust_weekly = core.weekly_totals(
            start.isoformat(),
            [(day.isoformat(), value) for day, value in dated_values.items()],
            today.isoformat(),
        )
        self.assertEqual(activity.weekly_totals(start, dated_values, today), rust_weekly)

        cumulative_values = [3, -2, 5, 4]
        self.assertEqual(
            activity.cumulative_totals(cumulative_values),
            core.cumulative_totals(cumulative_values),
        )

        entries = [
            {"date": "2026-10-20", "totalCost": 2.5},
            {"date": "2026-10-20T12:00:00Z", "totalCost": "1.5"},
            {"date": "2026-10-22", "totalTokens": 900},
            {"date": "2026-10-23", "totalCost": -1},
            {"date": "2026-10-24", "totalCost": " 0.75 "},
            {"date": "bad-date", "totalCost": 8},
        ]
        rust_series = [
            (date.fromisoformat(day), value)
            for day, value in core.daily_series(json.dumps(entries), 30, True)
        ]
        self.assertEqual(activity.daily_series(entries), rust_series)
        self.assertEqual(
            activity.daily_series(entries, history_coverage_established=False),
            [
                (date.fromisoformat(day), value)
                for day, value in core.daily_series(json.dumps(entries), 30, False)
            ],
        )

        non_json_entries = [{"date": "2026-10-25", "totalCost": float("nan")}]
        self.assertEqual(
            activity.daily_series(non_json_entries),
            [(date(2026, 10, 25), None)],
        )

        today = date(2026, 10, 27)
        self.assertEqual(
            activity.align_start(today).isoformat(),
            core.align_start(today.isoformat()),
        )

    def test_backend_selection_matches_opt_in_setting(self) -> None:
        enabled = os.environ.get("CODEXBAR_RUST_CORE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.assertEqual(rust_bridge.backend_name(), "rust" if enabled else "python")
