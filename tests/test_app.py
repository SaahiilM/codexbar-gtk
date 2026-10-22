"""Test suite for the CodexBar GTK front-end.

Run with:

    python3 -m unittest discover -s tests -v

The tests never touch a real provider account: the CLI is faked and the payloads
are recorded fixtures.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codexbar_gtk import format as fmt
from codexbar_gtk import providers as provider_meta
from codexbar_gtk.cli import CLIError, CodexBarCLI
from codexbar_gtk.controller import (
    AppState,
    Controller,
    automatic_tray_selection,
)
from codexbar_gtk.data import (
    Pace,
    RateWindow,
    agent_sessions_from_payloads,
    provider_usage_from_payload,
    spend_from_payloads,
)
from codexbar_gtk.history import HistoryStore, Sample
from codexbar_gtk.prefs import Preferences

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

CODEX_PAYLOAD = {
    "provider": "codex",
    "source": "oauth",
    "version": "0.160.0",
    "rateWindowLabels": {"primary": "Session", "secondary": "Weekly"},
    "pace": {
        "primary": {
            "stage": "behind",
            "deltaPercent": -48,
            "expectedUsedPercent": 48,
            "willLastToReset": True,
            "summary": "48% in reserve | Expected 48% used",
        }
    },
    "credits": {
        "remaining": 437.553762,
        "creditsAvailable": True,
        "events": [{"id": "e1", "date": "2026-10-20", "service": "codex", "creditsUsed": 12.5}],
    },
    "status": {
        "indicator": "none",
        "description": "All Systems Operational",
        "url": "https://status.openai.com/",
    },
    "usage": {
        "accountEmail": "user@example.com",
        "identity": {"accountEmail": "user@example.com", "loginMethod": "plus"},
        "updatedAt": "2026-10-21T14:56:53Z",
        "primary": {
            "usedPercent": 48,
            "resetsAt": "2026-10-21T20:14:45Z",
            "resetDescription": "4:14 PM",
            "windowMinutes": 300,
        },
        "secondary": {
            "usedPercent": 6,
            "resetsAt": "2026-10-27T13:25:20Z",
            "windowMinutes": 10080,
        },
        "tertiary": None,
        "providerCost": {
            "used": 12.5,
            "limit": 100,
            "currencyCode": "USD",
            "period": "Extra usage",
            "balance": 437.5,
        },
        "details": [
            {
                "title": "Usage breakdown",
                "rows": [{"label": "Code", "value": "3 requests"}],
                "chart": {
                    "kind": "bars",
                    "title": "Daily",
                    "points": [{"label": "10-20", "value": 3}, {"label": "10-21", "value": 8}],
                },
            }
        ],
    },
}

CLAUDE_ERROR_PAYLOAD = {
    "provider": "claude",
    "source": "auto",
    "error": {"message": "Claude OAuth credentials not found.", "kind": "provider", "code": 1},
}


class ProviderTableTests(unittest.TestCase):
    def test_every_provider_resolves(self):
        for provider_id in provider_meta.PROVIDERS:
            self.assertTrue(provider_meta.display_name(provider_id))
            self.assertTrue(provider_meta.accent_color(provider_id).startswith("#"))

    def test_aliases_resolve_to_the_current_ids(self):
        self.assertEqual(provider_meta.canonical_id("azure-openai"), "azureopenai")
        self.assertEqual(provider_meta.display_name("azure-openai"), "Azure Open AI")

    def test_unknown_provider_gets_a_fallback(self):
        self.assertEqual(provider_meta.display_name("nope"), "Nope")
        self.assertTrue(provider_meta.accent_color("nope").startswith("#"))


class UsageParsingTests(unittest.TestCase):
    def setUp(self):
        self.usage = provider_usage_from_payload(CODEX_PAYLOAD)

    def test_windows_are_parsed(self):
        self.assertEqual(len(self.usage.windows), 2)
        self.assertEqual(self.usage.windows[0].title, "Session")
        self.assertEqual(self.usage.windows[0].used_percent, 48)
        self.assertEqual(self.usage.windows[1].title, "Weekly")
        self.assertEqual(self.usage.windows[1].remaining_percent, 94)

    def test_identity_and_credits(self):
        self.assertEqual(self.usage.account_email, "user@example.com")
        self.assertEqual(self.usage.plan, "Plus")
        self.assertAlmostEqual(self.usage.credits_remaining or 0, 437.553762, places=3)
        self.assertEqual(len(self.usage.credit_events), 1)
        self.assertEqual(self.usage.credit_events[0].used, 12.5)

    def test_pace_and_cost(self):
        pace = self.usage.pace_for(self.usage.windows[0])
        self.assertIsNotNone(pace)
        assert pace is not None
        self.assertTrue(pace.in_reserve)
        self.assertFalse(pace.in_deficit)
        cost = self.usage.cost
        self.assertIsNotNone(cost)
        assert cost is not None
        self.assertAlmostEqual(cost.used_percent, 12.5)

    def test_detail_charts_are_parsed(self):
        self.assertEqual(len(self.usage.details), 1)
        chart = self.usage.details[0].chart
        self.assertIsNotNone(chart)
        assert chart is not None
        self.assertEqual(chart.points, [("10-20", 3.0), ("10-21", 8.0)])
        self.assertEqual(chart.peak, 8.0)

    def test_provider_errors_are_surfaced(self):
        usage = provider_usage_from_payload(CLAUDE_ERROR_PAYLOAD)
        self.assertTrue(usage.has_error)
        self.assertIn("OAuth", usage.error or "")

    def test_sessions_are_parsed(self):
        sessions = agent_sessions_from_payloads(
            [
                {
                    "id": "a",
                    "provider": "claude",
                    "state": "active",
                    "projectName": "demo",
                    "cwd": "/tmp/demo",
                    "pid": 42,
                }
            ]
        )
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].is_running)
        self.assertEqual(sessions[0].project_name, "demo")


class SpendParsingTests(unittest.TestCase):
    def test_per_provider_breakdown(self):
        payloads = [
            {
                "provider": "codex",
                "currencyCode": "USD",
                "totals": {"totalCost": 47.2, "totalTokens": 100, "coverage": {"priced": 3}},
                "daily": [{"date": "2026-10-20", "totalCost": 47.2, "totalTokens": 100}],
            },
            {
                "provider": "claude",
                "currencyCode": "USD",
                "totals": {"totalCost": 0, "totalTokens": 900, "coverage": {"unpriced": 4}},
                "daily": [{"date": "2026-10-21", "totalCost": 0, "totalTokens": 900}],
            },
        ]
        summary = spend_from_payloads(payloads)
        self.assertEqual(len(summary.providers), 2)
        self.assertAlmostEqual(summary.total_cost, 47.2)
        self.assertEqual(summary.total_tokens, 1000)
        codex = summary.providers[0]
        self.assertEqual(codex.provider, "codex")
        self.assertTrue(codex.priced)
        claude = summary.providers[1]
        self.assertEqual(claude.provider, "claude")
        self.assertFalse(claude.priced)


class FormatTests(unittest.TestCase):
    def test_percent_helpers(self):
        self.assertEqual(fmt.format_percent(48.4), "48%")
        self.assertEqual(fmt.format_remaining(48.4), "52%")
        self.assertEqual(fmt.format_percent(None), "—")

    def test_currency_keeps_the_currency_case(self):
        # Large amounts round, small ones keep their decimals.
        self.assertEqual(fmt.format_currency(437.5, "Credits"), "438 Credits")
        self.assertEqual(fmt.format_currency(47.21, "Credits"), "47.21 Credits")
        self.assertEqual(fmt.format_currency(47.2, "USD"), "$47.20")
        self.assertEqual(fmt.format_currency(1200, "USD", compact=True), "$1.2k")

    def test_tokens(self):
        self.assertEqual(fmt.format_tokens(1500), "1.5K")
        self.assertEqual(fmt.format_tokens(4_348_597_276), "4.35B")

    def test_pace_text(self):
        class FakePace:
            stage = "behind"
            delta_percent = -48
            in_reserve = True
            in_deficit = False
            stage_label = "In reserve"

        self.assertEqual(fmt.format_pace(FakePace()), "48% in reserve")

    def test_workday_progress(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        resets = now + timedelta(days=2)
        percent = fmt.workday_progress_percent(resets, now, work_days=5)
        self.assertIsNotNone(percent)
        assert percent is not None
        self.assertGreater(percent, 0)
        self.assertLess(percent, 100)

    def test_projection_uses_the_sample_rate(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        samples = [(1000.0, 0.0), (2000.0, 10.0)]
        projected = fmt.project_usage_at_reset(10.0, samples, now + timedelta(hours=1), now)
        self.assertIsNotNone(projected)
        assert projected is not None
        self.assertGreater(projected, 10.0)


class HistoryStoreTests(unittest.TestCase):
    def test_append_and_query(self):
        import time

        now = time.time()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "history.jsonl")
            store = HistoryStore(path)
            store.append(
                [
                    Sample(now - 600, "codex", "primary", 10.0),
                    Sample(now - 300, "codex", "primary", 20.0),
                    Sample(now - 450, "codex", "secondary", 5.0),
                ]
            )
            series = store.series("codex", "primary", hours=24)
            self.assertEqual([value for _, value in series], [10.0, 20.0])
            self.assertEqual(len(store.series("codex", "secondary", hours=24)), 1)

    def test_prune_drops_old_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "history.jsonl")
            store = HistoryStore(path, retention_days=1)
            store.append([Sample(1.0, "codex", "primary", 1.0)])
            store.prune()
            self.assertEqual(store.read_all(), [])

    def test_samples_are_written_as_json_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "history.jsonl")
            store = HistoryStore(path)
            store.append([Sample(1234.5, "codex", "primary", 7.5)])
            with open(path, "r", encoding="utf-8") as handle:
                line = json.loads(handle.readline())
            self.assertEqual(line["p"], "codex")
            self.assertEqual(line["w"], "primary")
            self.assertEqual(line["u"], 7.5)


class PreferencesTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            prefs = Preferences(path)
            self.assertEqual(prefs.get("refreshFrequency"), "adaptive")
            prefs.set("usageBarsShowUsed", False)
            self.assertEqual(Preferences(path).get("usageBarsShowUsed"), False)

    def test_export_uses_the_upstream_document_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(os.path.join(folder, "settings.json"))
            document = prefs.export_document()
            self.assertEqual(document["version"], 1)
            self.assertIn("preferences", document)

    def test_refresh_interval_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(os.path.join(folder, "settings.json"))
            prefs.set("refreshFrequency", "2m")
            self.assertEqual(prefs.refresh_seconds, 120)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.payload = os.path.join(self.directory.name, "usage.json")
        with open(self.payload, "w", encoding="utf-8") as handle:
            json.dump([CODEX_PAYLOAD], handle)
        self.fake = os.path.join(self.directory.name, "codexbar")
        with open(self.fake, "w", encoding="utf-8") as handle:
            handle.write(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "args = sys.argv[1:]\n"
                "if args[0] == '--version':\n"
                "    print('CodexBar 9.9.9')\n"
                "elif args[0] == 'usage':\n"
                "    print(open(os.path.join(os.path.dirname(__file__), 'usage.json')).read())\n"
                "else:\n"
                "    print('[]')\n"
            )
        os.chmod(self.fake, 0o755)

    def tearDown(self):
        self.directory.cleanup()

    def test_usage_is_parsed(self):
        cli = CodexBarCLI(self.fake)
        payloads = cli.usage()
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["provider"], "codex")

    def test_missing_binary_raises(self):
        cli = CodexBarCLI(os.path.join(self.directory.name, "missing"))
        with self.assertRaises(CLIError):
            cli.usage()


class ControllerTests(unittest.TestCase):
    def test_refresh_fills_the_state(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(os.path.join(folder, "settings.json"))
            payload = os.path.join(folder, "usage.json")
            with open(payload, "w", encoding="utf-8") as handle:
                json.dump([CODEX_PAYLOAD], handle)
            controller = Controller(prefs, CodexBarCLI())
            controller.cli.executable = os.path.join(folder, "fake")

            with open(controller.cli.executable, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/usr/bin/env python3\n"
                    "import os, sys\n"
                    "if sys.argv[1] == 'usage':\n"
                    "    print(open(os.path.join(os.path.dirname(__file__), 'usage.json')).read())\n"
                    "else:\n"
                    "    print('[]')\n"
                )
            os.chmod(controller.cli.executable, 0o755)

            state = controller.refresh()
            self.assertEqual(len(state.providers), 1)
            self.assertEqual(state.providers[0].provider_id, "codex")
            self.assertIsNone(state.last_error)


class TraySelectionTests(unittest.TestCase):
    """The tray's automatic lane, mirroring macOS AutomaticQuotaSelection."""

    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def _provider(provider_id, windows, pace=None):
        provider = provider_usage_from_payload({"provider": provider_id, "usage": {}})
        provider.windows = windows
        provider.pace = pace or {}
        return provider

    @staticmethod
    def _window(key, used, minutes=None, resets=None):
        return RateWindow(key=key, title=key.title(), used_percent=used, window_minutes=minutes, resets_at=resets)

    @staticmethod
    def _depleting(eta_seconds):
        return Pace(
            stage="behind",
            delta_percent=4.0,
            expected_used_percent=10.0,
            will_last_to_reset=False,
            eta_seconds=eta_seconds,
            summary="4% in deficit",
        )

    def _hours(self, value):
        return self.NOW + timedelta(hours=value)

    def test_a_quota_at_100_owns_the_tray(self):
        full = self._provider("codex", [self._window("primary", 100)])
        idle = self._provider("claude", [self._window("primary", 40)])
        chosen = automatic_tray_selection([idle, full], now=self.NOW)
        self.assertEqual(chosen[0].provider_id, "codex")

    def test_the_soonest_eta_wins(self):
        fast = self._provider(
            "codex",
            [self._window("primary", 45, minutes=300, resets=self._hours(24))],
            {"primary": self._depleting(2 * 3600)},
        )
        slow = self._provider(
            "claude",
            [self._window("primary", 70, minutes=300, resets=self._hours(24))],
            {"primary": self._depleting(5 * 3600)},
        )
        chosen = automatic_tray_selection([slow, fast], now=self.NOW)
        self.assertEqual(chosen[0].provider_id, "codex")
        self.assertEqual(chosen[1].used_percent, 45)

    def test_a_quota_within_forecast_outranks_a_higher_one(self):
        forecast = self._provider(
            "codex",
            [self._window("primary", 45, minutes=300, resets=self._hours(24))],
            {"primary": self._depleting(3 * 3600)},
        )
        plain = self._provider("claude", [self._window("primary", 90)])
        chosen = automatic_tray_selection([plain, forecast], now=self.NOW)
        self.assertEqual(chosen[0].provider_id, "codex")

    def test_sketchy_forecasts_fall_back_to_usage(self):
        low_expectation = self._provider(
            "codex",
            [self._window("primary", 20, minutes=300, resets=self._hours(24))],
            {
                "primary": Pace(
                    stage="behind",
                    delta_percent=1.0,
                    expected_used_percent=2.0,
                    will_last_to_reset=False,
                    eta_seconds=600.0,
                )
            },
        )
        plain = self._provider("claude", [self._window("primary", 80)])
        chosen = automatic_tray_selection([low_expectation, plain], now=self.NOW)
        self.assertEqual(chosen[0].provider_id, "claude")

    def test_placeholder_windows_are_ignored(self):
        placeholder = self._window("primary", 90)
        placeholder.is_placeholder = True
        healthy = self._provider("codex", [self._window("primary", 10)])
        chosen = automatic_tray_selection(
            [self._provider("claude", [placeholder]), healthy], now=self.NOW
        )
        self.assertEqual(chosen[0].provider_id, "codex")

    def test_without_usable_windows_there_is_no_selection(self):
        self.assertIsNone(automatic_tray_selection([], now=self.NOW))


class PaceWarningTests(unittest.TestCase):
    """Predictive pace notifications, mirroring macOS PredictivePaceWarnings."""

    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def _controller(self, folder):
        prefs = Preferences(os.path.join(folder, "settings.json"))
        return Controller(prefs, CodexBarCLI())

    @staticmethod
    def _provider(provider_id, will_last, eta=7200.0, resets_at=None):
        provider = provider_usage_from_payload({"provider": provider_id, "usage": {}})
        provider.windows = [RateWindow(key="primary", title="Session", used_percent=20, resets_at=resets_at)]
        provider.pace = {
            "primary": Pace(
                stage="behind",
                delta_percent=4.0,
                expected_used_percent=10.0,
                will_last_to_reset=will_last,
                eta_seconds=eta,
            )
        }
        return provider

    @staticmethod
    def _state(providers):
        state = AppState()
        state.providers = providers
        return state

    def _window_at(self, hours=24):
        return self.NOW + timedelta(hours=hours)

    def test_a_depleting_quota_warns_once_per_cycle(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            provider = self._provider("codex", will_last=False, resets_at=self._window_at())
            state = self._state([provider])

            events = controller.predictive_pace_events(state, now=self.NOW)
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["title"].startswith("Codex Session"))
            self.assertIn("may run out in 2h 0m", events[0]["body"])
            self.assertEqual(controller.predictive_pace_events(state, now=self.NOW), [])

    def test_a_recovered_pace_can_warn_again(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            state = self._state([self._provider("codex", will_last=False, resets_at=self._window_at())])
            controller.predictive_pace_events(state, now=self.NOW)
            state.providers[0].pace["primary"].will_last_to_reset = True
            controller.predictive_pace_events(state, now=self.NOW)
            state.providers[0].pace["primary"].will_last_to_reset = False
            events = controller.predictive_pace_events(state, now=self.NOW)
            self.assertEqual(len(events), 1)

    def test_a_new_reset_cycle_warns_again(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            state = self._state([self._provider("codex", will_last=False, resets_at=self._window_at())])
            controller.predictive_pace_events(state, now=self.NOW)
            state.providers[0].windows[0].resets_at = self._window_at(hours=24 + 400)
            events = controller.predictive_pace_events(state, now=self.NOW)
            self.assertEqual(len(events), 1)

    def test_only_supported_providers_warn(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            state = self._state([self._provider("grok", will_last=False)])
            self.assertEqual(controller.predictive_pace_events(state, now=self.NOW), [])

    def test_the_filter_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            controller.prefs.set("predictivePaceNotificationsEnabled", False)
            state = self._state([self._provider("codex", will_last=False)])
            self.assertEqual(controller.predictive_pace_events(state, now=self.NOW), [])

    def test_without_eta_there_is_no_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            provider = provider_usage_from_payload({"provider": "codex", "usage": {}})
            provider.windows = [RateWindow(key="primary", title="Session", used_percent=20)]
            provider.pace = {
                "primary": Pace(stage="behind", delta_percent=4.0, expected_used_percent=10.0,
                                will_last_to_reset=False, eta_seconds=None)
            }
            state = self._state([provider])
            self.assertEqual(controller.predictive_pace_events(state, now=self.NOW), [])


class CreditExpiryTests(unittest.TestCase):
    """Expiring reset-credit alerts, mirroring the macOS 3-day notifier."""

    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def _controller(self, folder):
        prefs = Preferences(os.path.join(folder, "settings.json"))
        return Controller(prefs, CodexBarCLI())

    @staticmethod
    def _provider(provider_id, credits):
        provider = provider_usage_from_payload({"provider": provider_id, "usage": {}})
        provider.reset_credits = credits
        return provider

    def _state(self, credits):
        state = AppState()
        state.providers = [self._provider("codex", credits)]
        return state

    @staticmethod
    def _credit(hours):
        return {"title": "Full reset", "expires_at": datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc) + timedelta(hours=hours)}

    def test_expiring_credits_alert_once(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            state = self._state([self._credit(48), self._credit(240)])
            events = controller.credit_expiry_events(state, now=self.NOW)
            self.assertEqual(len(events), 1)
            self.assertIn("expires in 2d 0h", events[0]["body"])
            self.assertEqual(controller.credit_expiry_events(state, now=self.NOW), [])

    def test_credits_further_out_do_not_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            state = self._state([self._credit(24 * 5)])
            self.assertEqual(controller.credit_expiry_events(state, now=self.NOW), [])

    def test_the_toggle_gates_the_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = self._controller(folder)
            controller.prefs.set("limitResetNotificationsEnabled", False)
            state = self._state([self._credit(48)])
            self.assertEqual(controller.credit_expiry_events(state, now=self.NOW), [])


class ResetCreditPresentationTests(unittest.TestCase):
    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def _hours(self, value):
        return self.NOW + timedelta(hours=value)

    def test_countdown_style(self):
        presentation = fmt.format_reset_credits(
            [self._hours(4.5), self._hours(7 * 24), None], style="countdown", now=self.NOW
        )
        self.assertEqual(presentation[0], "3 available")
        self.assertEqual(presentation[1], "4h 30m · 7d 0h · No expiry")
        self.assertEqual(presentation[2], ["Expires 4h 30m", "Expires 7d 0h", "No expiry"])

    def test_more_than_four_roll_up(self):
        expirations = [self._hours(index + 1) for index in range(6)]
        presentation = fmt.format_reset_credits(expirations, style="countdown", now=self.NOW)
        self.assertEqual(presentation[0], "6 available")
        self.assertTrue(presentation[1].endswith("+2"))
        self.assertEqual(len(presentation[1].split(" · ")), 5)

    def test_absolute_style_uses_times(self):
        presentation = fmt.format_reset_credits([self._hours(4.5)], style="absolute", now=self.NOW)
        self.assertEqual(presentation[2], ["Expires 16:30"])

    def test_empty_inventory_shows_nothing(self):
        self.assertIsNone(fmt.format_reset_credits([], style="countdown", now=self.NOW))

    def test_payload_parsing_keeps_available_credits(self):
        payload = dict(CODEX_PAYLOAD)
        usage = dict(payload["usage"])
        usage["codexResetCredits"] = {
            "availableCount": 2,
            "credits": [
                {"status": "available", "title": "Full reset", "expires_at": "2026-10-26T12:00:00Z"},
                {"status": "used", "title": "Full reset", "expires_at": "2026-10-24T12:00:00Z"},
                {"status": "available", "title": "Full reset", "expires_at": None},
            ],
        }
        payload["usage"] = usage
        provider = provider_usage_from_payload(payload)
        self.assertEqual(provider.reset_credits_available, 2)
        self.assertEqual(len(provider.reset_credits), 2)
        self.assertEqual(provider.reset_credits[0]["title"], "Full reset")
        self.assertIsNotNone(provider.reset_credits[0]["expires_at"])
        self.assertIsNone(provider.reset_credits[1]["expires_at"])


if __name__ == "__main__":
    unittest.main()
