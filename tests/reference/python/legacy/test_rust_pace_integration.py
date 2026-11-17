"""Parity checks for Rust-backed monthly allowance helpers."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk import pace
from codexbar_gtk.data import CostInfo, RateWindow

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(
    EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh"
)
class RustPaceIntegrationTests(unittest.TestCase):
    def test_monthly_window_and_daily_target_helpers_match_rust(self) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        for minutes in (
            None,
            -1,
            5 * 60,
            27 * 1440,
            28 * 1440,
            29 * 1440,
            30 * 1440,
            31 * 1440,
        ):
            self.assertEqual(
                pace.is_monthly_window(minutes), core.pace_is_monthly_window(minutes)
            )

        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        for remaining, reset in (
            (300.0, datetime(2026, 7, 11, 12, tzinfo=timezone.utc)),
            (300.0, datetime(2026, 7, 11, 0, tzinfo=timezone.utc)),
            (300.0, datetime(2026, 6, 30, 12, tzinfo=timezone.utc)),
            (None, datetime(2026, 7, 11, 12, tzinfo=timezone.utc)),
            (-1.0, datetime(2026, 7, 11, 12, tzinfo=timezone.utc)),
            (float("nan"), datetime(2026, 7, 11, 12, tzinfo=timezone.utc)),
            (300.0, None),
        ):
            rust_result = core.pace_daily_target(
                remaining,
                reset.isoformat() if reset is not None else None,
                now.isoformat(),
            )
            python_result = pace.daily_target(remaining, reset, now)
            if rust_result is None:
                self.assertIsNone(python_result)
            else:
                self.assertAlmostEqual(python_result, rust_result)

    def test_naive_and_second_offset_datetimes_match_python(self) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        now = datetime(2026, 7, 1, 12)  # noqa: DTZ001 - deliberate local-time input
        resets_at = datetime(2026, 7, 11, 12)  # noqa: DTZ001 - deliberate local-time input
        with patch("codexbar_gtk.pace.rust_bridge.extension", return_value=None):
            python_naive = pace.daily_target(300.0, resets_at, now)
        with patch("codexbar_gtk.pace.rust_bridge.extension", return_value=core):
            rust_naive = pace.daily_target(300.0, resets_at, now)
        self.assertEqual(rust_naive, python_naive)

        offset_reset = datetime.fromisoformat("2026-07-11T12:00:00+02:00:30")
        now_utc = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        with patch("codexbar_gtk.pace.rust_bridge.extension", return_value=None):
            python_offset = pace.daily_target(300.0, offset_reset, now_utc)
        with patch("codexbar_gtk.pace.rust_bridge.extension", return_value=core):
            rust_offset = pace.daily_target(300.0, offset_reset, now_utc)
        self.assertEqual(rust_offset, python_offset)

    def test_window_and_monthly_cost_targets_match_rust(self) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        resets_at = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
        window = RateWindow(
            key="monthly",
            title="Monthly",
            used_percent=25.0,
            resets_at=resets_at,
            window_minutes=30 * 1440,
            quota_limit=200.0,
            quota_unit="credits",
        )
        rust_window_target = core.pace_window_daily_target(
            {
                "is_placeholder": window.is_placeholder,
                "usage_known": window.usage_known,
                "window_minutes": window.window_minutes,
                "used_percent": window.used_percent,
                "quota_limit": window.quota_limit,
                "quota_unit": window.quota_unit,
                "resets_at": resets_at.isoformat(),
            },
            now.isoformat(),
        )
        self.assertAlmostEqual(
            pace.window_daily_target(window, now), rust_window_target
        )
        self.assertEqual(
            pace.format_window_target(window, now=now),
            "≈ 13.64 credits / day to last until reset",
        )

        cost = CostInfo(
            used=20.0,
            limit=80.0,
            currency="USD",
            period="Monthly",
            resets_at=resets_at,
        )
        rust_cost_target = core.pace_monthly_cost_daily_target(
            cost.used,
            cost.limit,
            cost.currency,
            cost.period,
            resets_at.isoformat(),
            now.isoformat(),
        )
        self.assertAlmostEqual(
            pace.daily_target(60.0, resets_at, now), rust_cost_target
        )
        with patch("codexbar_gtk.pace.currency.convert", return_value=5.02):
            self.assertEqual(
                pace.format_monthly_cost_target(cost, "EUR", now),
                "≈ €5.02 / day to last until reset",
            )

    def test_dst_local_midnight_reset_matches_python_and_rust(self) -> None:
        script = """
import json
import sys
from datetime import datetime, timezone
from unittest.mock import patch
from codexbar_gtk import pace
from codexbar_gtk import _rust_core
cases = json.loads(sys.argv[1])
values = []
for case in cases['cases']:
    now = datetime.fromisoformat(case['now'])
    reset = datetime.fromisoformat(case['reset'])
    with patch('codexbar_gtk.pace.rust_bridge.extension', return_value=None):
        python_value = pace.daily_target(case['remaining'], reset, now)
    with patch('codexbar_gtk.pace.rust_bridge.extension', return_value=_rust_core):
        rust_value = pace.daily_target(case['remaining'], reset, now)
    values.append([python_value, rust_value])
print(json.dumps(values))
"""
        fixture = json.loads(
            (ROOT / "tests/fixtures/b15/dst_pace_cases.json").read_text()
        )
        env = os.environ.copy()
        env["TZ"] = fixture["timezone"]
        env["CODEXBAR_RUST_CORE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", script, json.dumps(fixture)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        values = json.loads(completed.stdout)
        expected = fixture["cases"]
        self.assertEqual(
            values,
            [[case["expected"], case["expected"]] for case in expected],
        )

    def test_daily_target_formatting_matches_rust_and_keeps_currency_conversion(
        self,
    ) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        for target, unit in (
            (42.0, None),
            (12.5, "credits"),
            (9.0, "requests"),
            (1234.5, "USD"),
            (10.0, "widgets"),
            (None, "%"),
        ):
            self.assertEqual(
                pace.format_daily_target(target, unit),
                core.pace_format_daily_target(target, unit, "auto", None),
            )

        with patch("codexbar_gtk.pace.currency.convert", return_value=9.2):
            self.assertEqual(
                pace.format_daily_target(10.0, "USD", "EUR"),
                core.pace_format_daily_target(10.0, "USD", "EUR", 9.2),
            )
