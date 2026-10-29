"""Parity checks for Rust-backed monthly allowance helpers."""

from __future__ import annotations

import importlib
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

    def test_naive_datetimes_keep_the_python_fallback(self) -> None:
        now = datetime(2026, 7, 1, 12)  # noqa: DTZ001 - deliberately naive fallback
        resets_at = datetime(2026, 7, 11, 12)  # noqa: DTZ001 - deliberately naive fallback
        self.assertAlmostEqual(pace.daily_target(300.0, resets_at, now), 300 / 11)

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
