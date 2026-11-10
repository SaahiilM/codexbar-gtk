from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from codexbar_gtk.data import (
    AgentSession,
    CostInfo,
    DetailChart,
    Pace,
    ProviderUsage,
    RateWindow,
    SpendProvider,
    SpendSummary,
    agent_sessions_from_payloads,
    provider_usage_from_payload,
    spend_from_payloads,
    _optional_float,
    _optional_int,
    parse_timestamp,
)
from codexbar_gtk.rust_bridge import extension

ROOT = Path(__file__).resolve().parents[1]


class DomainPrimitiveIntegrationTests(unittest.TestCase):
    def test_timestamp_inputs_normalize_like_the_python_reference(self):
        cases = {
            "2026-10-21T14:56:53Z": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
            "2026-10-21T16:56:53+02:00": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
            "2026-10-21 14:56:53.125": datetime(
                2026, 10, 21, 14, 56, 53, 125000, tzinfo=timezone.utc
            ),
            "2026-10-21": datetime(2026, 10, 21, tzinfo=timezone.utc),
            # Basic ISO date/time is parsed directly by the Rust contract.
            "20261021T145653": datetime(2026, 10, 21, 14, 56, 53, tzinfo=timezone.utc),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_timestamp(value), expected)
        for value in (None, False, "", "  ", "not a timestamp"):
            with self.subTest(value=value):
                self.assertIsNone(parse_timestamp(value))

    def test_optional_number_contract_characterizes_large_integers(self):
        limits = json.loads(
            (ROOT / "tests/fixtures/b15/numeric_boundaries.json").read_text()
        )
        self.assertEqual(_optional_float(12), 12.0)
        self.assertEqual(_optional_float(12.5), 12.5)
        self.assertIsNone(_optional_float(True))
        self.assertIsNone(_optional_float("12"))
        self.assertIsNone(_optional_float(float("inf")))
        self.assertIsNone(_optional_float(10**1000))
        self.assertEqual(_optional_int(12.0), 12)
        self.assertIsNone(_optional_int(12.5))
        self.assertIsNone(_optional_int(True))
        self.assertIsNone(_optional_int(math.inf))

        import importlib

        try:
            core = importlib.import_module("codexbar_gtk._rust_core")
        except ImportError:
            core = None
        rounded = limits["optional_int_rounding_result"]
        with patch("codexbar_gtk.data.extension", return_value=None):
            self.assertEqual(
                _optional_int(limits["optional_int_rounding_input"]), rounded
            )
            self.assertEqual(
                _optional_int(limits["wide_optional_int"]),
                limits["wide_optional_int"],
            )
            self.assertEqual(
                _optional_int(limits["optional_int_max_i64_input"]),
                int(float(limits["optional_int_max_i64_input"])),
            )
            self.assertIsNone(_optional_int(10**1000))
        if core is not None:
            with patch("codexbar_gtk.data.extension", return_value=core):
                self.assertEqual(
                    _optional_int(limits["optional_int_rounding_input"]), rounded
                )
                with self.assertRaisesRegex(OverflowError, "signed 64-bit"):
                    _optional_int(limits["wide_optional_int"])
                with self.assertRaisesRegex(OverflowError, "signed 64-bit"):
                    _optional_int(limits["optional_int_max_i64_input"])
                self.assertIsNone(_optional_int(10**1000))

        wide_window = RateWindow("wide", "Wide", window_minutes=2**70)
        with patch("codexbar_gtk.data.extension", return_value=None):
            self.assertEqual(wide_window.duration_label, f"{2**70}m window")
        if core is not None:
            with patch("codexbar_gtk.data.extension", return_value=core):
                with self.assertRaises(OverflowError):
                    _ = wide_window.duration_label

    def test_timestamp_shapes_match_python_reference(self):
        from unittest.mock import patch

        import importlib

        try:
            core = importlib.import_module("codexbar_gtk._rust_core")
        except ImportError:
            self.skipTest("build the extension with scripts/build-rust-core.sh")
        values = (
            "2026-10-21T16:56:53+02:00:30",
            "2026-10-21T16:56:53,125+02:00:30.5",
            "2026-10-21T16:56:53.123456789012+02:00:30.123456789",
            "20261021T145653",
            "2026-W43-3",
            "2026W433",
            "2026-W43",
            "2026W43",
            "2026-10-21x14:56",
            "2026-10-21T12",
            "2026-10-21T12:30.5",
            "2026-10-21T1230,5",
            "2026-10-21T12:30:45+01:30.5",
            "2026-10-21T12:30:45+01.5",
            "2026-10-21T12:30:45-00:00:00.999999",
            "2026-10-21🐢12:30:45Z",
        )
        for value in values:
            with self.subTest(value=value):
                expected = datetime.fromisoformat(value)
                if expected.tzinfo is None:
                    expected = expected.replace(tzinfo=timezone.utc)
                expected = expected.astimezone(timezone.utc)
                with patch("codexbar_gtk.data.extension", return_value=None):
                    python_value = parse_timestamp(value)
                with patch("codexbar_gtk.data.extension", return_value=core):
                    rust_value = parse_timestamp(value)
                self.assertEqual(rust_value, expected)
                self.assertEqual(rust_value, python_value)

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

    def test_cost_payload_normalization_preserves_fields_and_fallbacks(self):
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {
                    "providerCost": {
                        "used": 12.5,
                        "limit": 100.0,
                        "currencyCode": "USD",
                        "period": "Extra usage",
                        "balance": 87.5,
                        "personalUsed": 2.0,
                        "resetsAt": "2026-10-30T20:00:00Z",
                    }
                },
            }
        )
        cost = usage.cost
        assert cost is not None
        self.assertEqual(cost.used, 12.5)
        self.assertEqual(cost.limit, 100.0)
        self.assertEqual(cost.currency, "USD")
        self.assertEqual(cost.period, "Extra usage")
        self.assertEqual(cost.balance, 87.5)
        self.assertEqual(cost.personal_used, 2.0)
        self.assertEqual(
            cost.resets_at,
            datetime(2026, 10, 30, 20, 0, 0, tzinfo=timezone.utc),
        )

        # Missing fields fall back to defaults
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {"providerCost": {}},
            }
        )
        cost = usage.cost
        assert cost is not None
        self.assertEqual(cost.used, 0.0)
        self.assertEqual(cost.limit, 0.0)
        self.assertEqual(cost.currency, "USD")
        self.assertFalse(cost.has_limit)

    def test_detail_section_normalization_preserves_rows_and_chart(self):
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {
                    "details": [
                        {
                            "title": "Usage breakdown",
                            "rows": [
                                {
                                    "label": "Code",
                                    "value": "3 requests",
                                    "secondaryValue": "Python",
                                    "progress": {"usedPercent": 45},
                                    "severity": "normal",
                                },
                                {
                                    "label": "Tests",
                                    "value": "12 passed",
                                    "progress": {},
                                    "severity": "warning",
                                },
                            ],
                            "chart": {
                                "kind": "bars",
                                "title": "Daily",
                                "unit": "requests",
                                "points": [
                                    {"label": "10-20", "value": 3},
                                    {"label": "10-21", "value": 8},
                                    {"label": "bad", "value": "not a number"},
                                ][:120],
                            },
                        }
                    ]
                },
            }
        )
        sections = usage.details
        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertEqual(section.title, "Usage breakdown")
        self.assertEqual(len(section.rows), 2)
        row = section.rows[0]
        self.assertEqual(row.label, "Code")
        self.assertEqual(row.value, "3 requests")
        self.assertEqual(row.secondary_value, "Python")
        self.assertEqual(row.used_percent, 45.0)
        self.assertEqual(row.severity, "normal")
        row = section.rows[1]
        self.assertEqual(row.label, "Tests")
        self.assertEqual(row.value, "12 passed")
        self.assertIsNone(row.secondary_value)
        self.assertIsNone(row.used_percent)
        self.assertEqual(row.severity, "warning")
        chart = section.chart
        assert chart is not None
        self.assertEqual(chart.kind, "bars")
        self.assertEqual(chart.title, "Daily")
        self.assertEqual(chart.unit, "requests")
        self.assertEqual(len(chart.points), 3)
        self.assertEqual(chart.points[0], ("10-20", 3.0))
        self.assertEqual(chart.points[1], ("10-21", 8.0))
        self.assertEqual(chart.points[2], ("bad", 0.0))
        self.assertEqual(chart.peak, 8.0)

        # Missing fields fall back to defaults
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {"details": [{}]},
            }
        )
        sections = usage.details
        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertIsNone(section.title)
        self.assertEqual(len(section.rows), 0)
        self.assertIsNone(section.chart)

    def test_context_normalization_preserves_credits_status_error_plan(self):
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {
                    "credits": {
                        "remaining": 437.55,
                        "creditsAvailable": True,
                        "events": [
                            {"id": "e1", "date": "2026-10-20", "service": "codex", "creditsUsed": 12.5},
                            {"id": "e2", "date": "2026-10-21", "service": "codex", "creditsUsed": 5.0},
                        ],
                    },
                    "codexResetCredits": {"availableCount": 3},
                    "status": {"indicator": "warning", "description": "Degraded performance"},
                    "error": {"message": "API rate limit exceeded"},
                },
                "plan": "Pro Plus",
            }
        )
        self.assertEqual(usage.credits_remaining, 437.55)
        self.assertTrue(usage.credits_available)
        self.assertEqual(len(usage.credit_events), 2)
        self.assertEqual(usage.credit_events[0].id, "e1")
        self.assertEqual(usage.credit_events[0].date, "2026-10-20")
        self.assertEqual(usage.credit_events[0].service, "codex")
        self.assertEqual(usage.credit_events[0].used, 12.5)
        self.assertEqual(usage.credit_events[1].used, 5.0)
        self.assertEqual(usage.reset_credits_available, 3)
        self.assertEqual(usage.status_level, "warning")
        self.assertEqual(usage.status_description, "Degraded performance")
        self.assertEqual(usage.error, "API rate limit exceeded")
        self.assertEqual(usage.plan, "Pro Plus")

        # Missing fields fall back to defaults
        usage = provider_usage_from_payload({"provider": "codex"})
        self.assertIsNone(usage.credits_remaining)
        self.assertFalse(usage.credits_available)
        self.assertEqual(len(usage.credit_events), 0)
        self.assertEqual(usage.reset_credits_available, 0)
        self.assertIsNone(usage.status_level)
        self.assertIsNone(usage.status_description)
        self.assertIsNone(usage.error)
        self.assertIsNone(usage.plan)

        # Plan from identity
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {
                    "identity": {
                        "plan": "Team Plan",
                        "loginMethod": "apiKey",
                    },
                },
            }
        )
        self.assertEqual(usage.plan, "Team Plan")

        # Plan derived from loginMethod when not oauth/apiKey/cookie
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {"identity": {"loginMethod": "sso"}},
            }
        )
        self.assertEqual(usage.plan, "Sso")

        # No plan from oauth login method
        usage = provider_usage_from_payload(
            {
                "provider": "codex",
                "usage": {"identity": {"loginMethod": "oauth"}},
            }
        )
        self.assertIsNone(usage.plan)

    def test_agent_session_normalization(self):
        sessions = agent_sessions_from_payloads(
            [
                {
                    "id": "s1",
                    "provider": "claude",
                    "state": "running",
                    "projectName": "My Project",
                    "cwd": "/home/user/project",
                    "pid": 1234,
                    "startedAt": "2026-10-30T10:00:00Z",
                    "lastActivityAt": "2026-10-30T10:30:00Z",
                    "host": "my-machine",
                },
                {
                    "id": "s2",
                    "provider": "codex",
                    "state": "stopped",
                    "projectName": "Other Project",
                    "cwd": "/home/user/other",
                    "pid": 5678,
                    "startedAt": "2026-10-30T09:00:00Z",
                    "lastActivityAt": "2026-10-30T09:30:00Z",
                    "host": "other-machine",
                },
            ]
        )
        self.assertEqual(len(sessions), 2)
        # Running session should come first
        self.assertEqual(sessions[0].id, "s1")
        self.assertTrue(sessions[0].is_running)
        self.assertEqual(sessions[0].provider, "claude")
        self.assertEqual(sessions[0].project_name, "My Project")
        self.assertEqual(sessions[0].pid, 1234)
        self.assertEqual(
            sessions[0].started_at,
            datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            sessions[0].last_activity_at,
            datetime(2026, 10, 30, 10, 30, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(sessions[0].host, "my-machine")

        self.assertEqual(sessions[1].id, "s2")
        self.assertFalse(sessions[1].is_running)
        self.assertEqual(sessions[1].provider, "codex")
        self.assertEqual(sessions[1].project_name, "Other Project")
        self.assertEqual(sessions[1].pid, 5678)
        self.assertEqual(sessions[1].host, "other-machine")

        # Empty payloads
        sessions = agent_sessions_from_payloads([])
        self.assertEqual(len(sessions), 0)

        sessions = agent_sessions_from_payloads(["not a dict"])
        self.assertEqual(len(sessions), 0)

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

    def test_extra_rate_window_usage_known_and_metadata(self):
        payload = provider_usage_from_payload(
            {
                "provider": "claude",
                "usage": {
                    "extraRateWindows": [
                        {
                            "id": "monthly",
                            "title": "Monthly allowance",
                            "usageKnown": False,
                            "window": {
                                "usedPercent": 0,
                                "windowMinutes": 43200,
                                "quotaLimit": 500,
                                "quotaUnit": "requests",
                                "nextRegenPercent": 1.5,
                            },
                        },
                        {
                            "id": "weekly-extra",
                            "window": {
                                "usedPercent": 25,
                                "windowMinutes": 10080,
                                "quotaLimit": 200,
                                "quotaUnit": "requests",
                            },
                        },
                        {
                            "window": {
                                "usedPercent": 10,
                                "windowMinutes": 43200,
                                "quotaLimit": 300,
                                "quotaUnit": "tokens",
                            },
                        },
                    ]
                },
            }
        )
        self.assertEqual(len(payload.windows), 3)
        monthly = payload.windows[0]
        self.assertEqual(monthly.key, "monthly")
        self.assertEqual(monthly.title, "Monthly allowance")
        self.assertEqual(monthly.used_percent, 0)
        self.assertFalse(monthly.usage_known)
        self.assertEqual(monthly.quota_limit, 500)
        self.assertEqual(monthly.quota_unit, "requests")
        self.assertEqual(monthly.next_regen_percent, 1.5)

        weekly_extra = payload.windows[1]
        self.assertEqual(weekly_extra.key, "weekly-extra")
        self.assertEqual(weekly_extra.title, "weekly-extra")
        self.assertEqual(weekly_extra.used_percent, 25)
        self.assertTrue(weekly_extra.usage_known)
        self.assertEqual(weekly_extra.quota_limit, 200)

        fallback_key = payload.windows[2]
        self.assertEqual(fallback_key.key, "extra")
        self.assertEqual(fallback_key.title, "Extra")
        self.assertEqual(fallback_key.used_percent, 10)
        self.assertTrue(fallback_key.usage_known)

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

class SpendAggregationTests(unittest.TestCase):
    def test_large_counts_keep_python_range_and_rust_reports_i64_limit(self):
        import importlib
        limits = json.loads(
            (ROOT / "tests/fixtures/b15/numeric_boundaries.json").read_text()
        )

        payloads = [
            {"provider": f"provider-{index}", "totalTokens": value}
            for index, value in enumerate(limits["counter_aggregate_inputs"])
        ]
        with patch("codexbar_gtk.data.extension", return_value=None):
            python_summary = spend_from_payloads(payloads)
        self.assertEqual(
            python_summary.total_tokens, limits["counter_aggregate_python_result"]
        )

        try:
            core = importlib.import_module("codexbar_gtk._rust_core")
        except ImportError:
            self.skipTest("build the extension with scripts/build-rust-core.sh")
        with patch("codexbar_gtk.data.extension", return_value=core):
            with self.assertRaisesRegex(OverflowError, "spend counters must fit in signed 64-bit"):
                spend_from_payloads(payloads)
            with self.assertRaisesRegex(OverflowError, "spend counters must fit in signed 64-bit"):
                spend_from_payloads(
                    [{"provider": "wide", "totalTokens": limits["wide_optional_int"]}]
                )

    def test_spend_aggregation_matches_python_reference(self):
        payloads = [
            {
                "provider": "claude",
                "currencyCode": "USD",
                "totalCost": 12.5,
                "totalTokens": 1000,
                "sessionCostUSD": 2.5,
                "sessionTokens": 100,
                "last30DaysCostUSD": 50.0,
                "last30DaysTokens": "5000",
                "sessionTokens": 100.8,
                "incompleteRequestCount": True,
                "coverage": {"unpriced": 1.9, "unmetered": 1.9},
                "provenance": "scan",
                "totals": {"provenance": "totals"},
                "daily": [
                    {
                        "date": "2026-10-20",
                        "totalCost": 5.0,
                        "modelBreakdowns": [{"model": "m1", "cost": 3.0}],
                    }
                ],
                "projects": [{"name": "proj-a", "totalCost": 7.5}],
                "models": [{"model": "m2", "totalCost": 2.0}],
            },
            {"provider": "known-zero", "totalCost": 0.0, "totalTokens": 0},
            {"provider": "unknown-cost", "totalTokens": 42},
            {"provider": "empty-provider"},
            {"provider": "no-error", "error": None},
            {"provider": "also-no-error", "error": {}},
        ]
        with patch("codexbar_gtk.data.extension", return_value=None):
            python_summary = spend_from_payloads(payloads)

        self.assertEqual(spend_from_payloads(payloads), python_summary)

    def test_spend_aggregation_preserves_totals_and_coverage(self):
        summary = spend_from_payloads(
            [
                {
                    "provider": "claude",
                    "currencyCode": "USD",
                    "totalCost": 12.50,
                    "totalTokens": 1000,
                    "sessionCostUSD": 2.50,
                    "sessionTokens": 100,
                    "last30DaysCostUSD": 50.00,
                    "last30DaysTokens": 5000,
                    "incompleteRequestCount": 0,
                    "coverage": {"unpriced": 0, "unmetered": 0},
                    "provenance": "scan",
                    "daily": [{"date": "2026-10-20", "totalCost": 5.0}],
                    "projects": [{"name": "proj-a", "totalCost": 7.5}],
                    "models": [{"cost": 3.0}],
                },
                {
                    "provider": "codex",
                    "totalCost": 7.25,
                    "totalTokens": 500,
                    "sessionCostUSD": 1.0,
                    "sessionTokens": 50,
                    "last30DaysCostUSD": 30.00,
                    "last30DaysTokens": 2500,
                    "incompleteRequestCount": 2,
                    "coverage": {"unpriced": 1},
                    "provenance": "scan",
                },
            ]
        )

        self.assertEqual(summary.total_cost, 19.75)
        self.assertTrue(summary.cost_known)
        self.assertEqual(summary.total_tokens, 1500)
        self.assertEqual(summary.session_cost, 3.50)
        self.assertTrue(summary.session_cost_known)
        self.assertEqual(summary.session_tokens, 150)
        self.assertEqual(summary.last30_cost, 80.00)
        self.assertTrue(summary.last30_cost_known)
        self.assertFalse(summary.last30_cost_partial)
        self.assertEqual(summary.last30_tokens, 7500)
        self.assertEqual(summary.incomplete_requests, 2)
        self.assertTrue(summary.cost_partial)
        self.assertEqual(len(summary.providers), 2)
        self.assertEqual(summary.providers[0].provider, "claude")
        self.assertEqual(summary.providers[0].cost, 12.50)
        self.assertEqual(summary.providers[1].provider, "codex")
        self.assertEqual(summary.providers[1].cost, 7.25)
        self.assertEqual(summary.coverage.get("unpriced"), 1)
        self.assertEqual(summary.provenance, "scan")

    def test_spend_aggregation_skips_error_payload(self):
        summary = spend_from_payloads(
            [
                {"provider": "claude", "error": {"message": "rate limited"}},
                {"provider": "codex", "totalCost": 5.0, "totalTokens": 100},
            ]
        )

        self.assertEqual(summary.error, "rate limited")
        self.assertTrue(summary.cost_partial)
        self.assertEqual(len(summary.providers), 1)
        self.assertEqual(summary.providers[0].provider, "codex")
        self.assertEqual(summary.providers[0].cost, 5.0)

    def test_spend_aggregation_unknown_vs_known_zero(self):
        summary = spend_from_payloads(
            [
                {"provider": "known-zero", "totalCost": 0.0, "totalTokens": 0},
                {"provider": "unknown-cost", "totalTokens": 42},
                {"provider": "empty-provider"},
            ]
        )

        # known-zero is kept (cost_known=true); unknown-cost kept; empty-provider filtered out
        self.assertEqual(len(summary.providers), 2)
        # Sorted by (cost, tokens) desc: unknown-cost before known-zero
        self.assertEqual(summary.providers[0].provider, "unknown-cost")
        self.assertFalse(summary.providers[0].cost_known)
        self.assertEqual(summary.providers[0].tokens, 42)
        self.assertEqual(summary.providers[1].provider, "known-zero")
        self.assertTrue(summary.providers[1].cost_known)
        self.assertEqual(summary.total_cost, 0.0)
        self.assertTrue(summary.cost_known)

    def test_spend_aggregation_totals_not_double_counted(self):
        summary = spend_from_payloads(
            [
                {
                    "provider": "cli",
                    "totalCost": 10.0,
                    "totalTokens": 100,
                    "totals": {"totalCost": 999.0, "totalTokens": 999},
                }
            ]
        )

        self.assertEqual(summary.total_cost, 10.0)
        self.assertEqual(summary.total_tokens, 100)
        self.assertTrue(summary.cost_known)

    def test_spend_aggregation_empty_and_non_dict(self):
        summary = spend_from_payloads([])
        self.assertEqual(summary.total_cost, 0.0)
        self.assertFalse(summary.cost_known)
        self.assertEqual(len(summary.providers), 0)
        self.assertIsNone(summary.error)

        summary = spend_from_payloads(["not a dict", 42, None])
        self.assertEqual(len(summary.providers), 0)
        self.assertIsNone(summary.error)

    def test_spend_aggregation_daily_projects_models_sorted(self):
        summary = spend_from_payloads(
            [
                {
                    "provider": "cli",
                    "daily": [
                        {"date": "2026-10-22", "totalCost": 2.0},
                        {"date": "2026-10-20", "totalCost": 1.0},
                        {"date": "2026-10-21", "totalCost": 3.0},
                    ],
                    "projects": [
                        {"name": "b", "totalCost": 1.0},
                        {"name": "a", "totalCost": "5.0"},
                    ],
                    "models": [
                        {"cost": 2.0},
                        {"totalCost": 10.0},
                        {"cost": 0.0, "totalCost": "8.0"},
                    ],
                }
            ]
        )

        self.assertEqual(len(summary.daily), 3)
        self.assertEqual(summary.daily[0].get("date"), "2026-10-20")
        self.assertEqual(summary.daily[2].get("date"), "2026-10-22")

        self.assertEqual(len(summary.projects), 2)
        self.assertEqual(summary.projects[0].get("name"), "a")
        self.assertEqual(summary.projects[1].get("name"), "b")

        self.assertEqual(len(summary.models), 3)
        self.assertEqual(summary.models[0].get("totalCost"), 10.0)
        self.assertEqual(summary.models[1].get("totalCost"), "8.0")
        self.assertEqual(summary.models[2].get("cost"), 2.0)

    def test_spend_aggregation_history_coverage_and_provenance(self):
        summary = spend_from_payloads(
            [
                {
                    "provider": "cli",
                    "historyCoverageIsEstablished": False,
                    "provenance": "",
                    "totals": {"provenance": "from-totals"},
                }
            ]
        )

        self.assertFalse(summary.history_coverage_established)
        self.assertEqual(summary.provenance, "from-totals")
        self.assertTrue(summary.cost_partial)

if __name__ == "__main__":
    unittest.main()
