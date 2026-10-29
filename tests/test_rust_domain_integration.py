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
    agent_sessions_from_payloads,
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

if __name__ == "__main__":
    unittest.main()
