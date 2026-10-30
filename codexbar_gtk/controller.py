"""Background refresh controller.

Keeps provider usage, spend and status fresh without blocking the UI thread.
Pure Python (no GTK imports) so it can be exercised head-less.
"""

from __future__ import annotations

import math
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from .cli import CLIError, CodexBarCLI
from .format import format_countdown
from .history import HistoryStore, Sample
from .data import (
    AgentSession,
    CostInfo,
    CreditEvent,
    DetailChart,
    DetailRow,
    DetailSection,
    Pace,
    ProviderUsage,
    RateWindow,
    SpendProvider,
    SpendSummary,
    agent_sessions_from_payloads,
    parse_timestamp,
    provider_usage_from_payload,
    spend_from_payloads,
)
from .prefs import Preferences
from .rust_bridge import extension
from . import rust_bridge
from . import currency as currency_service


@dataclass
class AppState:
    backend_sequence: int = 0
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


def _controller_error_text(error: dict | None) -> str | None:
    if not isinstance(error, dict):
        return None
    kind = error.get("kind")
    operation = error.get("operation")
    if not isinstance(kind, str) or not isinstance(operation, str):
        return None
    return f"{kind} ({operation})"


def _provider_from_dto(value: dict) -> ProviderUsage:
    windows = [
        RateWindow(
            key=item["key"],
            title=item["title"],
            used_percent=item["used_percent"],
            resets_at=parse_timestamp(item.get("resets_at")),
            reset_description=item.get("reset_description"),
            window_minutes=item.get("window_minutes"),
            next_regen_percent=item.get("next_regen_percent"),
            is_placeholder=item["is_placeholder"],
            quota_limit=item.get("quota_limit"),
            quota_unit=item.get("quota_unit"),
            usage_known=item["usage_known"],
        )
        for item in value.get("windows", [])
    ]
    pace = {
        key: Pace(
            stage=item["stage"],
            delta_percent=item.get("delta_percent"),
            expected_used_percent=item.get("expected_used_percent"),
            will_last_to_reset=item["will_last_to_reset"],
            eta_seconds=item.get("eta_seconds"),
            run_out_probability=item.get("run_out_probability"),
            summary=item.get("summary"),
        )
        for key, item in value.get("pace", {}).items()
    }
    cost_value = value.get("cost")
    cost = (
        CostInfo(
            used=cost_value["used"],
            limit=cost_value["limit"],
            currency=cost_value["currency"],
            period=cost_value.get("period"),
            balance=cost_value.get("balance"),
            personal_used=cost_value.get("personal_used"),
            resets_at=parse_timestamp(cost_value.get("resets_at")),
        )
        if isinstance(cost_value, dict)
        else None
    )
    details = []
    for section in value.get("details", []):
        rows = [
            DetailRow(
                label=row["label"],
                value=row["value"],
                secondary_value=row.get("secondary_value"),
                used_percent=row.get("used_percent"),
                severity=row["severity"],
            )
            for row in section.get("rows", [])
        ]
        chart_value = section.get("chart")
        chart = (
            DetailChart(
                kind=chart_value["kind"],
                title=chart_value.get("title"),
                unit=chart_value.get("unit"),
                points=[(point[0], point[1]) for point in chart_value.get("points", [])],
            )
            if isinstance(chart_value, dict)
            else None
        )
        details.append(DetailSection(title=section.get("title"), rows=rows, chart=chart))
    reset_credits = [
        {
            **item,
            "granted_at": parse_timestamp(item.get("granted_at")),
            "expires_at": parse_timestamp(item.get("expires_at")),
        }
        for item in value.get("reset_credits", [])
    ]
    return ProviderUsage(
        provider_id=value["provider_id"],
        display_name=value["display_name"],
        source=value.get("source"),
        version=value.get("version"),
        updated_at=parse_timestamp(value.get("updated_at")),
        account_email=value.get("account_email"),
        plan=value.get("plan"),
        login_method=value.get("login_method"),
        windows=windows,
        pace=pace,
        credits_remaining=value.get("credits_remaining"),
        credits_unit=value["credits_unit"],
        credits_available=value["credits_available"],
        cost=cost,
        status_level=value.get("status_level"),
        status_description=value.get("status_description"),
        error=value.get("error"),
        details=details,
        reset_credits_available=value["reset_credits_available"],
        reset_credits=reset_credits,
        credit_events=[CreditEvent(**item) for item in value.get("credit_events", [])],
        accounts=value.get("accounts", []),
        selected_account=value.get("selected_account"),
        accent_color=value["accent_color"],
        raw=value.get("raw", {}),
    )


def _session_from_dto(value: dict) -> AgentSession:
    return AgentSession(
        id=value["id"],
        provider=value["provider"],
        state=value["state"],
        project_name=value["project_name"],
        cwd=value["cwd"],
        pid=value["pid"],
        started_at=parse_timestamp(value.get("started_at")),
        last_activity_at=parse_timestamp(value.get("last_activity_at")),
        host=value["host"],
    )


def _spend_from_dto(value: dict | None) -> SpendSummary | None:
    if value is None:
        return None
    return SpendSummary(
        total_cost=value["total_cost"],
        cost_known=value["cost_known"],
        cost_partial=value["cost_partial"],
        currency=value["currency"],
        total_tokens=value["total_tokens"],
        total_tokens_known=value["total_tokens_known"],
        total_tokens_partial=value["total_tokens_partial"],
        coverage=value["coverage"],
        provenance=value["provenance"],
        reporting_period=value.get("reporting_period"),
        history_label=value.get("history_label"),
        history_coverage_established=value["history_coverage_established"],
        daily=value["daily"],
        projects=value["projects"],
        models=value["models"],
        session_cost=value["session_cost"],
        session_cost_known=value["session_cost_known"],
        session_cost_partial=value["session_cost_partial"],
        session_tokens=value["session_tokens"],
        session_tokens_known=value["session_tokens_known"],
        session_tokens_partial=value["session_tokens_partial"],
        last30_cost=value["last30_cost"],
        last30_cost_known=value["last30_cost_known"],
        last30_cost_partial=value["last30_cost_partial"],
        last30_tokens=value["last30_tokens"],
        last30_tokens_known=value["last30_tokens_known"],
        last30_tokens_partial=value["last30_tokens_partial"],
        incomplete_requests=value["incomplete_requests"],
        error=value.get("error"),
        providers=[SpendProvider(**item) for item in value["providers"]],
    )


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
        self._refresh_guard = threading.Lock()
        self._queued_refresh = False
        self._notified_windows: dict[tuple[str, str], float] = {}
        self._session_quota_seen: dict[tuple[str, str, str], bool] = {}
        self._last_reset_seen: dict[tuple[str, str], float] = {}
        self._pace_notified: dict[tuple[str, str], tuple[int | None, float]] = {}
        self._credit_expiry_seen: set[tuple] = set()
        self._notification_snapshot_seen: float | None = None
        rust = rust_bridge.extension()
        self._rust_notification_policy = rust.NotificationPolicy() if rust is not None else None
        self._rust_controller = None
        self._rust_sequence = -1
        self._rust_events: list[dict] = []
        self._rust_tray_selection: dict | None = None
        self._presentation_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="codexbar-rust-presentation"
        )
        self._presentation_request_id = 0

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
        rust = rust_bridge.extension()
        if rust is not None:
            if not hasattr(rust, "RefreshController"):
                raise RuntimeError("Rust refresh controller is unavailable; rebuild the Rust extension")
            if self.prefs._rust is None:
                raise RuntimeError("Rust preferences are unavailable for the Rust refresh controller")
            history_store = self.history._rust_store()
            if history_store is None:
                raise RuntimeError("Rust history store is unavailable for the Rust refresh controller")
            shared_currency = currency_service.shared()._rust
            if shared_currency is None:
                raise RuntimeError("Rust currency service is unavailable for the Rust refresh controller")
            self._rust_controller = rust.RefreshController(
                self.cli.executable,
                self.cli.timezone,
                self.prefs._rust,
                history_store,
                shared_currency,
            )
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="codexbar-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._rust_controller is not None:
            self._rust_controller.request_shutdown()
            self._presentation_executor.shutdown(wait=False, cancel_futures=True)
            return
        self._stop.set()

    @property
    def uses_rust_controller(self) -> bool:
        return self._rust_controller is not None

    def poll(self) -> bool:
        """Poll Rust watch state/events without waiting; called on GTK's main loop."""
        if self._rust_controller is None:
            return False
        new_events = json.loads(self._rust_controller.drain_events_json(256))
        if new_events:
            self._rust_events.extend(item["event"] for item in new_events)
        changed = self._rust_controller.state_sequence() != self._rust_sequence
        if changed:
            envelope = json.loads(self._rust_controller.state_json())
            self._rust_sequence = envelope["sequence"]
            self.state.backend_sequence = int(envelope["sequence"])
            snapshot = envelope.get("snapshot")
            status = envelope.get("status")
            self.state.refreshing = status == "refreshing"
            if snapshot is not None:
                self.state.providers = [_provider_from_dto(item) for item in snapshot["providers"]]
                self.state.spend = _spend_from_dto(snapshot.get("spend"))
                self.state.sessions = [_session_from_dto(item) for item in snapshot["sessions"]]
                updated_at = parse_timestamp(snapshot.get("updated_at"))
                self.state.last_updated = updated_at.timestamp() if updated_at else None
                self.state.cli_version = snapshot.get("version", "unknown")
                error = (
                    envelope.get("last_error")
                    if status == "refreshing"
                    else snapshot.get("last_error") or envelope.get("last_error")
                )
                self.state.last_error = _controller_error_text(error)
                self._rust_tray_selection = snapshot.get("tray_selection")
            else:
                self.state.last_error = _controller_error_text(envelope.get("last_error"))
            self._notify()
        elif new_events:
            # Event delivery is lossless and independent of watch coalescing.
            self._notify()
        return True

    def automatic_tray_selection(self, providers: list[ProviderUsage]):
        """Resolve the stored Rust selection; Python mode retains its policy path."""
        if self._rust_controller is None:
            return automatic_tray_selection(providers)
        selection = self._rust_tray_selection
        if selection is None:
            return None
        provider_index = selection.get("provider_index")
        window_index = selection.get("window_index")
        if not isinstance(provider_index, int) or not 0 <= provider_index < len(self.state.providers):
            return None
        provider = self.state.providers[provider_index]
        if provider.has_error or provider.provider_id != selection.get("provider_id") or not any(
            item is provider for item in providers
        ):
            return None
        if not isinstance(window_index, int) or not 0 <= window_index < len(provider.windows):
            return None
        window = provider.windows[window_index]
        if (
            window.key != selection.get("window_key")
            or not window.usage_known
            or window.is_placeholder
            or not math.isfinite(window.used_percent)
            or window.used_percent < 0.0
        ):
            return None
        return provider, window

    def request_rust_presentation(self, callback: Callable[[dict | None, dict | None, str | None], None]) -> bool:
        """Project current spend/tray DTOs off GTK's thread, then return them to its caller."""
        if self._rust_controller is None:
            return False
        with self._lock:
            self._presentation_request_id += 1
            request_id = self._presentation_request_id
        controller = self._rust_controller

        def project() -> tuple[dict | None, dict | None, str | None]:
            try:
                spend = json.loads(controller.spend_view_model_json())
                tray = json.loads(controller.tray_summary_json())
                return spend, tray, None
            except Exception:
                return None, None, "projection_unavailable"

        future = self._presentation_executor.submit(project)

        def complete(result) -> None:
            try:
                spend, tray, error = result.result()
            except Exception:
                spend, tray, error = None, None, "projection_unavailable"
            with self._lock:
                current = request_id == self._presentation_request_id
            if current:
                callback(spend, tray, error)

        future.add_done_callback(complete)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            interval = self.prefs.refresh_seconds
            if interval <= 0:
                # Manual mode: never auto-refresh; refresh only on user action,
                # matching the macOS app. Keep the loop alive to respond to quit.
                interval = 24 * 60 * 60
            # Wake up often enough to notice a changed interval or a quit request.
            deadline = time.monotonic() + interval
            while not self._stop.is_set() and time.monotonic() < deadline:
                time.sleep(0.5)

    # -- refreshing -------------------------------------------------------

    def refresh(self, force: bool = False) -> AppState:
        if self._rust_controller is not None:
            if force:
                self._rust_controller.force_refresh()
            return self.state
        with self._refresh_guard:
            if self._refreshing.is_set():
                if force:
                    self._queued_refresh = True
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
            spend: SpendSummary | None = self.state.spend
            spend_error: str | None = None
            if self.prefs.get("costUsageEnabled", True):
                try:
                    payloads = self._scan_costs()
                    fresh = spend_from_payloads(payloads)
                    # A new CLI may know sources this installed version does
                    # not, or one source may fail. Keep the last usable scan
                    # rather than replace it with a fabricated empty total.
                    if fresh.providers or not fresh.error:
                        spend = fresh
                    spend_error = fresh.error
                except CLIError as exc:
                    spend_error = f"Cost history unavailable: {exc}"
            else:
                spend = None
            try:
                sessions = agent_sessions_from_payloads(self.cli.sessions())
            except CLIError:
                sessions = self.state.sessions
            with self._lock:
                self.state.providers = self._ordered(providers)
                self.state.spend = spend
                self.state.sessions = sessions
                self._collect_accounts()
                self.state.last_updated = time.time()
                self.state.last_error = spend_error
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
            with self._refresh_guard:
                self._refreshing.clear()
                run_queued = self._queued_refresh
                self._queued_refresh = False
            self._notify()

        if run_queued and not self._stop.is_set():
            threading.Thread(
                target=self.refresh,
                kwargs={"force": True},
                name="codexbar-queued-refresh",
                daemon=True,
            ).start()

        return self.state

    def _collect_accounts(self) -> None:
        """Ask the CLI which accounts exist for every enabled provider."""
        for provider in self.state.providers:
            if provider.provider_id in getattr(self, "_accounts_done", set()):
                continue
            try:
                payloads = self.cli.usage(provider.provider_id, all_accounts=True)
            except CLIError:
                continue
            labels: list[str] = []
            for payload in payloads:
                identity = (payload.get("usage") or {}).get("identity") or {}
                label = (
                    identity.get("accountEmail")
                    or payload.get("account")
                    or identity.get("accountOrganization")
                )
                if label and label not in labels:
                    labels.append(str(label))
            if labels:
                provider.accounts = labels
                provider.selected_account = labels[0]
            if not hasattr(self, "_accounts_done"):
                self._accounts_done = set()
            self._accounts_done.add(provider.provider_id)

    def _scan_costs(self) -> list[dict]:
        """Scan the local transcripts of every provider that keeps them.

        The CLI only scans providers that are enabled, so Codex and Claude Code
        are requested explicitly with the same "both" selector the upstream
        desktop app uses.
        """
        try:
            return self.cli.cost(provider="both")
        except CLIError as original_error:
            payloads: list[dict] = []
            succeeded = False
            for provider in ("codex", "claude"):
                try:
                    payloads.extend(self.cli.cost(provider=provider))
                    succeeded = True
                except CLIError as exc:
                    payloads.append({"provider": provider, "error": {"message": str(exc)}})
                    continue
            if not succeeded:
                raise original_error
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
        rust = extension()
        if rust is not None:
            try:
                indices = rust.provider_order_indices(
                    [provider.provider_id for provider in providers],
                    [provider_id for provider_id in order if isinstance(provider_id, str)],
                    [provider_id for provider_id in hidden if isinstance(provider_id, str)],
                )
                return [providers[index] for index in indices]
            except (OverflowError, TypeError, ValueError):
                # Keep Python's broader handling for unusual preference values.
                pass
        visible = [p for p in providers if p.provider_id not in hidden]

        if not order:
            return visible

        index = {pid: i for i, pid in enumerate(order)}

        def sort_key(item: tuple[int, ProviderUsage]) -> tuple[int, int, str]:
            position, provider = item
            return (index.get(provider.provider_id, 10_000), position, provider.provider_id)

        return [p for _, p in sorted(enumerate(visible), key=sort_key)]

    # -- notifications ----------------------------------------------------

    def notification_events(self, state: AppState, now: datetime | None = None) -> list[dict]:
        """Return typed policy outcomes; platform delivery remains a UI concern."""
        if self._rust_controller is not None:
            events = self._rust_events
            self._rust_events = []
            return events
        if state.last_error is not None:
            return []
        if state.last_updated is not None:
            if state.last_updated == self._notification_snapshot_seen:
                return []
            self._notification_snapshot_seen = state.last_updated
        if self._rust_notification_policy is not None:
            now = now or datetime.now(timezone.utc)
            providers = []
            for provider in state.providers:
                windows = [{
                    "key": window.key,
                    "title": window.title,
                    "used_percent": window.used_percent,
                    "resets_at": window.resets_at.isoformat() if window.resets_at else None,
                    "window_minutes": window.window_minutes,
                    "is_placeholder": window.is_placeholder,
                    "usage_known": window.usage_known,
                } for window in provider.windows]
                pace = {key: {
                    "will_last_to_reset": value.will_last_to_reset,
                    "eta_seconds": value.eta_seconds,
                    "run_out_probability": value.run_out_probability,
                } for key, value in provider.pace.items()}
                credits = [{"expires_at": credit["expires_at"].isoformat() if credit.get("expires_at") else None}
                           for credit in provider.reset_credits]
                providers.append({
                    "provider_id": provider.provider_id,
                    "display_name": provider.display_name,
                    "account_email": provider.account_email,
                    "windows": windows,
                    "pace": pace,
                    "reset_credits": credits,
                })
            preferences = {key: self.prefs.get(key, default) for key, default in {
                "quotaWarningNotificationsEnabled": True,
                "quotaWarningSessionEnabled": True,
                "quotaWarningWeeklyEnabled": True,
                "quotaWarningSessionThresholds": [50, 20],
                "quotaWarningWeeklyThresholds": [50, 20],
                "sessionQuotaNotificationsEnabled": True,
                "predictivePaceNotificationsEnabled": True,
                "limitResetNotificationsEnabled": True,
            }.items()}
            encoded = self._rust_notification_policy.observe_json(
                json.dumps(providers), json.dumps(preferences), now.timestamp()
            )
            return json.loads(encoded)

        # Python remains the parity reference until the explicit cutover.
        events = []
        events.extend({
            "kind": "quota_threshold", "provider_id": provider_id,
            "account_email": account_email or None, "window_key": window_key,
            "used_percent": used, "threshold_percent": threshold,
            "title": "Quota warning", "body": message,
        } for provider_id, account_email, window_key, used, threshold, message in self.quota_events(state))
        events.extend({"kind": "session_exhausted", **event}
                      for event in self._session_quota_event_records(state))
        for event in self.predictive_pace_events(state, now=now):
            identity = next(
                ((provider.provider_id, provider.account_email, window.key)
                 for provider in state.providers for window in provider.windows
                 if event.get("id") == f"predictive-pace-{provider.provider_id}-{window.key}"),
                (None, None, None),
            )
            events.append({"kind": "predictive_pace", "provider_id": identity[0],
                           "account_email": identity[1] or None, "window_key": identity[2], **event})
        for event in self.credit_expiry_events(state, now=now):
            provider = next((provider for provider in state.providers
                             if event.get("id") == f"reset-credit-expiry-{provider.provider_id}"), None)
            events.append({"kind": "credit_expiry", "provider_id": provider.provider_id if provider else None, **event})
        return events

    def quota_events(self, state: AppState) -> list[tuple[str, str | None, str, float, float, str]]:
        """Return newly crossed quota warning thresholds.

        Each entry is ``(provider_id, account_email, window_key, used_percent,
        threshold_percent, message)``. Account identity is carried in the typed
        outcome; threshold deduplication keeps the Python provider/window key.
        """
        events: list[tuple[str, str | None, str, float, float, str]] = []
        if not self.prefs.get("quotaWarningNotificationsEnabled", True):
            return events

        session_thresholds = list(self.prefs.get("quotaWarningSessionThresholds") or [50, 20])
        weekly_thresholds = list(self.prefs.get("quotaWarningWeeklyThresholds") or [50, 20])

        for provider in state.providers:
            for window in provider.windows:
                if not window.usage_known or window.is_placeholder or not math.isfinite(window.used_percent):
                    continue
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
                                provider.account_email,
                                window.key,
                                used,
                                threshold,
                                f"{provider.display_name} {window.title} at {used:.0f}% "
                                f"(threshold {threshold:.0f}%)",
                            )
                        )
                        break
                else:
                    if previous is not None and used < previous:
                        self._notified_windows[marker] = used

        return events

    def _session_quota_event_records(self, state: AppState) -> list[dict]:
        """Return identity-preserving exhaustion outcomes for notification delivery."""
        events: list[dict] = []
        enabled = bool(self.prefs.get("sessionQuotaNotificationsEnabled", True))
        seen: set[tuple[str, str, str]] = set()
        for provider in state.providers:
            for window in provider.windows:
                if window.key != "primary":
                    continue
                key = (provider.provider_id, provider.account_email or "", window.key)
                seen.add(key)
                if not window.usage_known or window.is_placeholder or not math.isfinite(window.used_percent):
                    continue
                exhausted = window.used_percent >= 100.0
                was_exhausted = self._session_quota_seen.get(key, False)
                self._session_quota_seen[key] = exhausted
                if enabled and exhausted and not was_exhausted:
                    account = f" ({provider.account_email})" if provider.account_email else ""
                    events.append({
                        "provider_id": provider.provider_id,
                        "account_email": provider.account_email or None,
                        "window_key": window.key,
                        "title": "Session quota exhausted",
                        "body": f"{provider.display_name}{account} {window.title} is exhausted.",
                    })
        # Drop disappeared accounts/providers so a later appearance can notify again.
        for key in self._session_quota_seen.keys() - seen:
            self._session_quota_seen.pop(key, None)
        return events

    def session_quota_events(self, state: AppState) -> list[tuple[str, str]]:
        """Return the legacy title/body pairs for Python parity callers."""
        return [(event["title"], event["body"])
                for event in self._session_quota_event_records(state)]

    # -- pace and reset-credit events ------------------------------------

    def predictive_pace_events(self, state: AppState, now: datetime | None = None) -> list[dict[str, str]]:
        """Warn when pace says a quota may not last until its reset.

        Mirrors the macOS ``PredictivePaceWarnings`` logic: only Codex and
        Claude, only once per reset cycle, only when the pace forecast says
        the quota depletes before the window resets.
        """
        events: list[dict[str, str]] = []
        if not self.prefs.get("predictivePaceNotificationsEnabled", True):
            return events

        now = now or datetime.now(timezone.utc)
        for provider in state.providers:
            if provider.provider_id not in ("codex", "claude"):
                continue
            for window in provider.windows:
                if window.resets_at is None:
                    continue
                key = (
                    provider.provider_id,
                    provider.account_email or "",
                    window.key,
                )
                pace = provider.pace.get(window.key)
                if pace is None or pace.will_last_to_reset:
                    self._pace_notified.pop(key, None)
                    continue

                eta = pace.eta_seconds
                try:
                    eta = float(eta) if eta is not None else None
                except (TypeError, ValueError):
                    eta = None
                probability = _pace_probability(pace)
                if (
                    eta is None
                    or not math.isfinite(eta)
                    or eta <= 0.0
                    or probability < 0.5
                ):
                    continue

                cycle = (window.window_minutes, window.resets_at.timestamp())
                previous = self._pace_notified.get(key)
                if previous is not None and _same_cycle(previous, cycle):
                    # Already warned during this reset cycle.
                    continue

                self._pace_notified[key] = cycle
                countdown = format_countdown(now + timedelta(seconds=eta), now) or "—"
                title = f"{provider.display_name} {window.title} pace warning"
                body = "At the current pace, this quota may run out in {duration}, before it resets.".format(
                    duration=countdown
                )
                if provider.account_email:
                    body = f"Account {provider.account_email}. {body}"
                events.append(
                    {
                        "id": f"predictive-pace-{provider.provider_id}-{window.key}",
                        "title": title,
                        "body": body,
                    }
                )

        return events

    def credit_expiry_events(self, state: AppState, now: datetime | None = None) -> list[dict[str, str]]:
        """Alert when rate-limit reset credits are about to expire.

        Mirrors the macOS ``CodexResetCreditExpiryNotifier``: a 3-day window
        and a fingerprint per inventory so each change alerts only once.
        """
        events: list[dict[str, str]] = []
        if not self.prefs.get("limitResetNotificationsEnabled", True):
            return events

        now = now or datetime.now(timezone.utc)
        window = timedelta(days=3)
        for provider in state.providers:
            if not provider.reset_credits:
                continue
            expiring = sorted(
                credit["expires_at"]
                for credit in provider.reset_credits
                if credit.get("expires_at") is not None
                and 0 < (credit["expires_at"] - now).total_seconds() <= window.total_seconds()
            )
            if not expiring:
                continue

            fingerprint = (provider.provider_id, tuple(expiring))
            if fingerprint in self._credit_expiry_seen:
                continue
            self._credit_expiry_seen.add(fingerprint)

            first = format_countdown(expiring[0], now) or "soon"
            if len(expiring) == 1:
                body = f"{provider.display_name} rate limit reset expires in {first}."
            else:
                body = (
                    f"{len(expiring)} {provider.display_name} rate limit resets expire within 3 days — "
                    f"the first one in {first}."
                )
            events.append(
                {
                    "id": f"reset-credit-expiry-{provider.provider_id}",
                    "title": "Reset credit expiring",
                    "body": body,
                }
            )

        return events


def _pace_probability(pace) -> float:
    """The CLI omits ``runOutProbability`` (schema parity only); macOS defaults it to 1."""
    probability = getattr(pace, "run_out_probability", None)
    try:
        return float(probability) if probability is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


def _same_cycle(previous: tuple[int | None, float], current: tuple[int | None, float]) -> bool:
    """Whether two reset windows belong to the same cycle.

    Mirrors macOS ``belongsToSameCycle``: the same window length and reset
    times within half a window (at least five minutes) of each other count as
    one cycle, so small provider reset-time corrections do not re-alert.
    """
    previous_minutes, previous_reset = previous
    current_minutes, current_reset = current
    if previous_minutes != current_minutes:
        return False
    tolerance = max((previous_minutes or 0) * 30.0, 300.0)
    return abs(current_reset - previous_reset) < tolerance


def automatic_tray_selection(
    providers: list[ProviderUsage], now: datetime | None = None
) -> tuple[ProviderUsage, RateWindow] | None:
    """Pick the quota the tray should represent, like the macOS Auto lane.

    Error providers, placeholders and unknown usage are excluded; known zero
    remains eligible. The ranking mirrors ``AutomaticQuotaSelection``: a fully
    depleted window outranks everything, then a window forecast to deplete
    before its reset outranks one that lasts, then the smallest ETA, then the
    highest usage.
    """
    now = now or datetime.now(timezone.utc)
    rust = extension()
    if rust is not None:
        candidates: list[tuple[ProviderUsage, RateWindow]] = []
        used_percent: list[float] = []
        placeholders: list[bool] = []
        candidate_eligible: list[bool] = []
        window_minutes: list[int | None] = []
        seconds_until_reset: list[float | None] = []
        expected_used_percent: list[float | None] = []
        eta_seconds: list[float | None] = []
        for provider in providers:
            provider_eligible = not provider.has_error
            for window in provider.windows:
                pace = provider.pace.get(window.key)
                candidates.append((provider, window))
                used_percent.append(float(window.used_percent))
                placeholders.append(bool(window.is_placeholder))
                candidate_eligible.append(provider_eligible and window.usage_known)
                window_minutes.append(window.window_minutes)
                seconds_until_reset.append(
                    (window.resets_at - now).total_seconds()
                    if window.resets_at is not None
                    else None
                )
                expected_used_percent.append(
                    pace.expected_used_percent if pace is not None else None
                )
                eta_seconds.append(pace.eta_seconds if pace is not None else None)
        try:
            index = rust.automatic_quota_candidate(
                used_percent,
                placeholders,
                candidate_eligible,
                window_minutes,
                seconds_until_reset,
                expected_used_percent,
                eta_seconds,
            )
            return candidates[index] if index is not None else None
        except (OverflowError, TypeError, ValueError):
            # Keep Python's wider numeric/date support for out-of-contract data.
            pass
    candidates: list[tuple[ProviderUsage, RateWindow, float | None]] = []
    for provider in providers:
        if provider.has_error:
            continue
        for window in provider.windows:
            # Older Python selection treated the model's default 0.0 as usage
            # when a provider omitted the field. Keep known zero eligible, but
            # do not select unknown usage as though it were a measured zero.
            if window.is_placeholder or not window.usage_known:
                continue
            if not math.isfinite(window.used_percent) or window.used_percent < 0:
                continue
            candidates.append((provider, window, _window_eta(provider, window, now)))

    best: tuple[ProviderUsage, RateWindow, float | None] | None = None
    for candidate in candidates:
        if best is None or _quota_outranks(best, candidate):
            best = candidate
    if best is None:
        return None
    return (best[0], best[1])


def _window_eta(provider: ProviderUsage, window: RateWindow, now: datetime) -> float | None:
    """Seconds until the window depletes, when the forecast is trustworthy."""
    pace = provider.pace.get(window.key)
    if pace is None or window.window_minutes is None or window.resets_at is None:
        return None
    expected = pace.expected_used_percent
    if expected is None or expected < 3.0:
        return None
    eta = pace.eta_seconds
    if eta is None or not math.isfinite(float(eta)) or eta <= 0:
        return None
    until_reset = (window.resets_at - now).total_seconds()
    if eta >= until_reset:
        return None
    return float(eta)


def _quota_outranks(
    best: tuple[ProviderUsage, RateWindow, float | None],
    candidate: tuple[ProviderUsage, RateWindow, float | None],
) -> bool:
    """Whether ``candidate`` should replace ``best``, mirroring macOS ``precedes``."""
    _, best_window, best_eta = best
    _, candidate_window, candidate_eta = candidate
    best_full = best_window.used_percent >= 100
    candidate_full = candidate_window.used_percent >= 100
    if best_full != candidate_full:
        return candidate_full
    if (best_eta is None) != (candidate_eta is None):
        return candidate_eta is not None
    if best_eta is not None and candidate_eta is not None and best_eta != candidate_eta:
        return candidate_eta < best_eta
    return candidate_window.used_percent > best_window.used_percent


def path_from_prefs(prefs: Preferences) -> str | None:
    value = str(prefs.get("cliPath") or "").strip()
    return value or None
