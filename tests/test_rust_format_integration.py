"""Parity checks for Rust-backed display formatting helpers."""

from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codexbar_gtk import format as fmt

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(
    EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh"
)
class RustFormatIntegrationTests(unittest.TestCase):
    def test_python_format_adapters_match_rust(self) -> None:
        core = importlib.import_module("codexbar_gtk._rust_core")
        now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        target = now + timedelta(hours=4, minutes=12)
        now_iso, target_iso = now.isoformat(), target.isoformat()

        self.assertEqual(fmt.compact_window_label(" Session ", 300), "5h")
        self.assertEqual(fmt.compact_window_label("weekly", None), "W")
        self.assertEqual(fmt.format_percent(23.45, 1), core.format_percent(23.45, 1))
        self.assertEqual(
            fmt.format_remaining(23.45, 1), core.format_remaining(23.45, 1)
        )
        self.assertEqual(
            fmt.format_countdown(target, now),
            core.format_countdown(target_iso, now_iso),
        )
        self.assertEqual(
            fmt.format_absolute(target, now), core.format_absolute(target_iso, now_iso)
        )
        for style in ("countdown", "absolute", "both", "unknown"):
            self.assertEqual(
                fmt.format_reset(target, style, now),
                core.format_reset(target_iso, style, now_iso),
            )

        for value, currency, compact in (
            (47.21, "USD", False),
            (1234.5, "EUR", True),
            (12.5, "Credits", False),
            (None, "USD", False),
        ):
            self.assertEqual(
                fmt.format_currency(value, currency, compact),
                core.format_currency(value, currency, compact),
            )
        for value in (None, -12.5, 12.345, 1234.5):
            self.assertEqual(fmt.format_credits(value), core.format_credits(value))
        for value in (None, 0, 1500, 4_348_597_276):
            self.assertEqual(fmt.format_tokens(value), core.format_tokens(value))

        self.assertEqual(
            fmt.format_updated(now - timedelta(minutes=5), now),
            core.format_updated((now - timedelta(minutes=5)).isoformat(), now_iso),
        )
        expirations = [target, now + timedelta(days=7), None]
        self.assertEqual(
            fmt.format_reset_credits(expirations, "countdown", now),
            core.format_reset_credits(
                [target_iso, (now + timedelta(days=7)).isoformat(), None],
                "countdown",
                now_iso,
            ),
        )

        class Pace:
            stage = "behind"
            delta_percent = -48
            in_deficit = False
            in_reserve = True
            stage_label = "In reserve"

        self.assertEqual(
            fmt.format_pace(Pace()),
            core.format_pace("behind", -48.0, False, True, "In reserve"),
        )
        self.assertEqual(
            fmt.format_window_span(10_080), core.format_window_span(10_080)
        )
        self.assertEqual(
            fmt.next_refresh_delta(1).total_seconds(),
            core.next_refresh_seconds(1),
        )
        self.assertEqual(
            fmt.workday_progress_percent(target, now, 5),
            core.workday_progress_percent(target_iso, now_iso, 5),
        )
        samples = [(1000.0, 0.0), (2000.0, 10.0)]
        self.assertEqual(
            fmt.project_usage_at_reset(10.0, samples, target, now),
            core.project_usage_at_reset(10.0, samples, target_iso, now_iso),
        )

    def test_python_fallback_preserves_unsupported_numeric_edges(self) -> None:
        with self.assertRaises(OverflowError):
            fmt.format_percent(10**1000)
        self.assertEqual(fmt.format_tokens(True), "True")
        self.assertEqual(fmt.format_credits(float("nan")), "nan")
        with self.assertRaises(ValueError):
            fmt.format_currency(float("nan"))

    def test_non_utc_datetimes_keep_the_python_timezone_behavior(self) -> None:
        local_zone = timezone(timedelta(hours=9))
        now = datetime(2026, 10, 22, 12, tzinfo=local_zone)
        target = now + timedelta(hours=4)
        self.assertEqual(fmt.format_absolute(target, now), "16:00")
