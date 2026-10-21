"""Background refresh controller.

Keeps provider usage, spend and status fresh without blocking the UI thread.
Pure Python (no GTK imports) so it can be exercised head-less.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .cli import CLIError, CodexBarCLI
from .history import HistoryStore, Sample
from .data import (
    AgentSession,
    ProviderUsage,
    SpendSummary,
    agent_sessions_from_payloads,
    provider_usage_from_payload,
    spend_from_payloads,
)
from .prefs import Preferences


@dataclass
class AppState:
    providers: list[ProviderUsage] = field(default_factory=list)
    spend: SpendSummary | None = None
    sessions: list[AgentSession] = field(default_factory=list)
    last_updated: float | None = None
    last_error: str | None = None
    refreshing: bool = False
    cli_version: str = ""

    def provider(self, provider_id: str) -> ProviderUsage | None:
        for item in self.providers:
            if item.provider_id == provider_id:
                return item
        return None


Listener = Callable[[AppState], None]


class Controller:
    """Polls the codexbar CLI on a background thread and publishes state."""

    def __init__(self, prefs: Preferences, cli: CodexBarCLI | None = None) -> None:
        self.prefs = prefs
        self.cli = cli or CodexBarCLI(path_from_prefs(prefs))
        self.history = HistoryStore()
        self.state = AppState()
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._refreshing = threading.Event()
        self._notified_windows: dict[tuple[str, str], float] = {}
        self._last_reset_seen: dict[tuple[str, str], float] = {}

    # -- listeners --------------------------------------------------------

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
            state = self.state
        for listener in listeners:
            try:
                listener(state)
            except Exception:  # pragma: no cover - a broken listener must not kill the loop
                pass

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="codexbar-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            interval = self.prefs.refresh_seconds
            if interval <= 0:
                interval = 60  # manual mode: keep the tray alive but poll rarely
            # Wake up often enough to notice a changed interval or a quit request.
            deadline = time.monotonic() + interval
            while not self._stop.is_set() and time.monotonic() < deadline:
                time.sleep(0.5)

    # -- refreshing -------------------------------------------------------

    def refresh(self, force: bool = False) -> AppState:
        if self._refreshing.is_set():
            return self.state
        self._refreshing.set()
        with self._lock:
            self.state.refreshing = True
        self._notify()

        try:
            providers = [
                provider_usage_from_payload(payload)
                for payload in self.cli.usage()
            ]
            spend: SpendSummary | None = None
            if self.prefs.get("costUsageEnabled", True):
                try:
                    spend = spend_from_payloads(self._scan_costs())
                except CLIError:
                    spend = None
            try:
                sessions = agent_sessions_from_payloads(self.cli.sessions())
            except CLIError:
                sessions = []
            with self._lock:
                self.state.providers = self._ordered(providers)
                self.state.spend = spend
                self.state.sessions = sessions
                self.state.last_updated = time.time()
                self.state.last_error = None
                self._record_history()
                self.state.cli_version = self.cli.version()
        except CLIError as exc:
            with self._lock:
                self.state.last_error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                self.state.last_error = f"Unexpected error: {exc}"
        finally:
            with self._lock:
                self.state.refreshing = False
            self._refreshing.clear()
            self._notify()

        return self.state

    def _scan_costs(self) -> list[dict]:
        """Scan local transcripts for every provider that keeps them.

        The CLI only scans providers that are enabled, so the ones the user
        works with daily (Codex, Claude Code, OpenCode) are requested
        explicitly.
        """
        providers = ["codex", "claude", "opencode"]
        payloads: list[dict] = []
        for provider in providers:
            try:
                payloads.extend(self.cli.cost(provider=provider))
            except CLIError:
                continue
        return payloads

    def _record_history(self) -> None:
        """Store one sample per provider window so the app can show trends."""
        now = time.time()
        samples: list[Sample] = []
        for provider in self.state.providers:
            for window in provider.windows:
                samples.append(
                    Sample(
                        timestamp=now,
                        provider=provider.provider_id,
                        window=window.key,
                        used_percent=window.used_percent,
                    )
                )
        if samples:
            self.history.append(samples)
            if len(self.history.read_all()) > 20000:
                self.history.prune()

    def _ordered(self, providers: list[ProviderUsage]) -> list[ProviderUsage]:
        order = list(self.prefs.get("providerOrder") or [])
        hidden = set(self.prefs.get("hiddenProviders") or [])
        visible = [p for p in providers if p.provider_id not in hidden]

        if not order:
            return visible

        index = {pid: i for i, pid in enumerate(order)}

        def sort_key(item: tuple[int, ProviderUsage]) -> tuple[int, int, str]:
            position, provider = item
            return (index.get(provider.provider_id, 10_000), position, provider.provider_id)

        return [p for _, p in sorted(enumerate(visible), key=sort_key)]

    # -- notifications ----------------------------------------------------

    def quota_events(self, state: AppState) -> list[tuple[str, str, float, str]]:
        """Return newly crossed quota warning thresholds.

        Each entry is ``(provider_id, window_key, used_percent, message)``.
        """
        events: list[tuple[str, str, float, str]] = []
        if not self.prefs.get("quotaWarningNotificationsEnabled", True):
            return events

        session_thresholds = list(self.prefs.get("quotaWarningSessionThresholds") or [50, 20])
        weekly_thresholds = list(self.prefs.get("quotaWarningWeeklyThresholds") or [50, 20])

        for provider in state.providers:
            for window in provider.windows:
                if window.key == "primary":
                    thresholds = session_thresholds if self.prefs.get("quotaWarningSessionEnabled", True) else []
                elif window.key == "secondary":
                    thresholds = weekly_thresholds if self.prefs.get("quotaWarningWeeklyEnabled", True) else []
                else:
                    thresholds = []

                marker = (provider.provider_id, window.key)
                previous = self._notified_windows.get(marker)
                used = window.used_percent
                for threshold in sorted(thresholds, reverse=True):
                    if used >= threshold and (previous is None or previous < threshold):
                        self._notified_windows[marker] = used
                        events.append(
                            (
                                provider.provider_id,
                                window.key,
                                used,
                                f"{provider.display_name} {window.title} at {used:.0f}% "
                                f"(threshold {threshold:.0f}%)",
                            )
                        )
                        break
                else:
                    if previous is not None and used < previous:
                        self._notified_windows[marker] = used

        return events


def path_from_prefs(prefs: Preferences) -> str | None:
    value = str(prefs.get("cliPath") or "").strip()
    return value or None
