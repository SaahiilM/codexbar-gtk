from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from codexbar_gtk.data import (
    AgentSession,
    CostInfo,
    DetailChart,
    Pace,
    ProviderUsage,
    RateWindow,
    provider_usage_from_payload,
    _optional_float,
    _optional_int,
    parse_timestamp,
)


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

    def test_pace_payload_normalization_keeps_valid_values_and_python_fallbacks(self):
        parsed = provider_usage_from_payload(
            {
                "provider": "codex",
                "pace": {
                    "primary": {
                        "stage": "behind",
                        "deltaPercent": -12.5,
                        "expectedUsedPercent": 45,
                        "willLastToReset": 1,
                        "etaSeconds": 600,
                        "runOutProbability": 0.2,
                        "summary": "in reserve",
                    }
                },
            }
        ).pace["primary"]
        self.assertEqual(parsed.delta_percent, -12.5)
        self.assertEqual(parsed.expected_used_percent, 45)
        self.assertTrue(parsed.will_last_to_reset)
        self.assertEqual(parsed.eta_seconds, 600)
        self.assertEqual(parsed.run_out_probability, 0.2)
        self.assertEqual(parsed.summary, "in reserve")

        fallback = provider_usage_from_payload(
            {
                "provider": "codex",
                "pace": {"primary": {"stage": "ahead", "etaSeconds": "unknown"}},
            }
        ).pace["primary"]
        self.assertEqual(fallback.eta_seconds, "unknown")

    def test_pace_labels_and_classifications(self):
        cases = (
            ("onTrack", False, False, "On pace"),
            ("slightlyAhead", True, False, "In deficit"),
            ("ahead", True, False, "In deficit"),
            ("farAhead", True, False, "Well in deficit"),
            ("slightlyBehind", False, True, "In reserve"),
            ("behind", False, True, "In reserve"),
            ("farBehind", False, True, "Well in reserve"),
            ("futureStage", False, False, "futureStage"),
        )
        for stage, deficit, reserve, label in cases:
            with self.subTest(stage=stage):
                pace = Pace(stage=stage)
                self.assertEqual(pace.in_deficit, deficit)
                self.assertEqual(pace.in_reserve, reserve)
                self.assertEqual(pace.stage_label, label)

    def test_cost_limit_and_usage_percent(self):
        self.assertFalse(CostInfo(used=10, limit=0).has_limit)
        self.assertFalse(CostInfo(used=10, limit=-1).has_limit)
        self.assertFalse(CostInfo(used=10, limit=math.nan).has_limit)
        self.assertTrue(CostInfo(used=10, limit=math.inf).has_limit)
        self.assertEqual(CostInfo(used=50, limit=100).used_percent, 50)
        self.assertEqual(CostInfo(used=150, limit=100).used_percent, 100)
        self.assertEqual(CostInfo(used=-5, limit=100).used_percent, 0)
        self.assertEqual(CostInfo(used=math.nan, limit=100).used_percent, 100)

    def test_detail_chart_peak_matches_python_contract(self):
        self.assertEqual(DetailChart(points=[("one", 4), ("two", 9)]).peak, 9)
        self.assertEqual(DetailChart(points=[]).peak, 0)
        self.assertEqual(DetailChart(points=[("negative", -2)]).peak, -2)

    def test_provider_usage_derived_properties(self):
        provider = ProviderUsage("fixture", "Fixture", plan="Plus", account_email="fixture@example.invalid")
        provider.windows = [
            RateWindow("primary", "Session", used_percent=25),
            RateWindow("secondary", "Weekly", used_percent=70),
        ]
        self.assertEqual(provider.max_used_percent, 70)
        self.assertIs(provider.primary_window, provider.windows[0])
        self.assertIs(provider.window("secondary"), provider.windows[1])
        self.assertEqual(provider.subtitle, "Plus · fixture@example.invalid")
        self.assertFalse(provider.has_error)
        provider.error = "synthetic error"
        self.assertTrue(provider.has_error)

    def test_agent_session_running_state(self):
        for state in ("running", "ACTIVE", "Live"):
            with self.subTest(state=state):
                self.assertTrue(AgentSession("fixture", state=state).is_running)
        self.assertFalse(AgentSession("fixture", state="finished").is_running)

    def test_standard_window_normalization_preserves_known_zero_and_unknown(self):
        payload = provider_usage_from_payload(
            {
                "provider": "codex",
                "rateWindowLabels": {"primary": "Session"},
                "usage": {
                    "primary": {
                        "usedPercent": 0,
                        "windowMinutes": 300,
                        "resetsAt": "2026-10-29T18:00:00Z",
                    },
                    "secondary": {},
                },
            }
        )
        self.assertEqual(payload.windows[0].used_percent, 0)
        self.assertTrue(payload.windows[0].usage_known)
        self.assertEqual(payload.windows[0].duration_label, "5h window")
        self.assertEqual(payload.windows[1].used_percent, 0)
        self.assertFalse(payload.windows[1].usage_known)

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
