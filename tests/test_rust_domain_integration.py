from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from codexbar_gtk.data import RateWindow, _optional_float, _optional_int, parse_timestamp


class DomainPrimitiveIntegrationTests(unittest.TestCase):
    def test_timestamp_inputs_normalize_like_the_python_reference(self):
        cases = {
            "2026-10-21T14:56:53Z": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
            "2026-10-21T16:56:53+02:00": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
            "2026-10-21 14:56:53.125": datetime(
                2026, 10, 21, 14, 56, 53, 125000, tzinfo=timezone.utc
            ),
            "2026-10-21": datetime(2026, 10, 21, tzinfo=timezone.utc),
            # Python accepts this basic form; it exercises the compatibility fallback.
            "20261021T145653": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_timestamp(value), expected)
        for value in (None, False, "", "  ", "not a timestamp"):
            with self.subTest(value=value):
                self.assertIsNone(parse_timestamp(value))

    def test_optional_number_contract_preserves_python_fallbacks(self):
        self.assertEqual(_optional_float(12), 12.0)
        self.assertEqual(_optional_float(12.5), 12.5)
        self.assertIsNone(_optional_float(True))
        self.assertIsNone(_optional_float("12"))
        self.assertIsNone(_optional_float(float("inf")))
        self.assertIsNone(_optional_float(10**1000))
        self.assertEqual(_optional_int(12.0), 12)
        self.assertIsNone(_optional_int(12.5))
        self.assertIsNone(_optional_int(True))
        # Python's float-then-int behavior is intentionally kept for values
        # outside the Rust i64 duration range.
        self.assertEqual(_optional_int(2**70), 2**70)
        self.assertIsNone(_optional_int(math.inf))

    def test_rate_window_derived_properties(self):
        window = RateWindow("primary", "Session", used_percent=48, window_minutes=300)
        self.assertEqual(window.remaining_percent, 52)
        self.assertEqual(window.duration_label, "5h window")
        self.assertEqual(
            RateWindow("weekly", "Weekly", window_minutes=10080).duration_label,
            "7d window",
        )
        self.assertIsNone(RateWindow("unknown", "Unknown", window_minutes=0).duration_label)
        self.assertEqual(RateWindow("bad", "Bad", used_percent=math.nan).remaining_percent, 0)

if __name__ == "__main__":
    unittest.main()
