"""Typed view over the codexbar CLI JSON payloads.

The CLI already normalises ~100 providers into a stable envelope, so the GUI only
needs a small amount of shaping: flatten the primary/secondary/tertiary windows,
pair them with their labels and pace info, and keep the raw payload around for
provider specific detail sections.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import providers as provider_meta
from .rust_bridge import extension

WINDOW_KEYS = ("primary", "secondary", "tertiary")


def parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    rust = extension()
    if rust is not None:
        parsed = rust.parse_timestamp(text)
        if parsed is not None:
            try:
                return datetime.fromisoformat(parsed).astimezone(timezone.utc)
            except ValueError:
                pass
    # Keep Python's wider fromisoformat grammar as a compatibility fallback.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: Any) -> float | None:
    """A finite JSON number, ignoring booleans and non-numeric strings."""
    rust = extension()
    if rust is not None:
        result = rust.optional_float(value)
        if result is not None:
            return result
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    """An integral JSON number, rejecting booleans and malformed durations."""
    rust = extension()
    if rust is not None:
        result = rust.optional_int(value)
        if result is not None:
            return result
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() else None


@dataclass
class RateWindow:
    """One quota window (session, weekly, ...)."""

    key: str
    title: str
    used_percent: float = 0.0
    resets_at: datetime | None = None
    reset_description: str | None = None
    window_minutes: int | None = None
    next_regen_percent: float | None = None
    is_placeholder: bool = False
    quota_limit: float | None = None
    quota_unit: str | None = None
    usage_known: bool = True

    @property
    def remaining_percent(self) -> float:
        rust = extension()
        if rust is not None:
            return rust.rate_window_remaining_percent(self.used_percent)
        return max(0.0, 100.0 - self.used_percent)

    @property
    def duration_label(self) -> str | None:
        minutes = self.window_minutes
        rust = extension()
        if rust is not None:
            try:
                return rust.rate_window_duration_label(minutes)
            except (OverflowError, TypeError, ValueError):
                # Preserve Python support for values outside Rust's i64 contract.
                pass
        if not minutes:
            return None
        if minutes % 1440 == 0:
            days = minutes // 1440
            return f"{days}d window" if days > 1 else "24h window"
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours}h window"
        return f"{minutes}m window"


@dataclass
class Pace:
    """Pace forecast for a window (are we ahead of or behind the expected burn?)."""

    stage: str = "onTrack"
    delta_percent: float | None = None
    expected_used_percent: float | None = None
    will_last_to_reset: bool = True
    eta_seconds: float | None = None
    run_out_probability: float | None = None
    summary: str | None = None

    @property
    def in_deficit(self) -> bool:
        """Burning faster than the expected pace."""
        return self.stage in {"slightlyAhead", "ahead", "farAhead"}

    @property
    def in_reserve(self) -> bool:
        """Burning slower than the expected pace."""
        return self.stage in {"slightlyBehind", "behind", "farBehind"}

    @property
    def stage_label(self) -> str:
        return {
            "onTrack": "On pace",
            "slightlyAhead": "In deficit",
            "ahead": "In deficit",
            "farAhead": "Well in deficit",
            "slightlyBehind": "In reserve",
            "behind": "In reserve",
            "farBehind": "Well in reserve",
        }.get(self.stage, self.stage)


@dataclass
class CostInfo:
    used: float = 0.0
    limit: float = 0.0
    currency: str = "USD"
    period: str | None = None
    balance: float | None = None
    personal_used: float | None = None
    resets_at: datetime | None = None

    @property
    def has_limit(self) -> bool:
        return self.limit and self.limit > 0

    @property
    def used_percent(self) -> float:
        if not self.has_limit:
            return 0.0
        return max(0.0, min(100.0, (self.used / self.limit) * 100.0))


@dataclass
class DetailChart:
    """A chart attached to a provider detail section."""

    kind: str = "bars"
    title: str | None = None
    unit: str | None = None
    points: list[tuple[str, float]] = field(default_factory=list)

    @property
    def peak(self) -> float:
        return max((value for _, value in self.points), default=0.0)


@dataclass
class CreditEvent:
    id: str = ""
    date: str = ""
    service: str = ""
    used: float = 0.0


@dataclass
class DetailRow:
    label: str
    value: str
    secondary_value: str | None = None
    used_percent: float | None = None
    severity: str = "normal"


@dataclass
class DetailSection:
    title: str | None
    rows: list[DetailRow] = field(default_factory=list)
    chart: DetailChart | None = None


@dataclass
class ProviderUsage:
    """Everything the GUI shows for a single provider."""

    provider_id: str
    display_name: str
    source: str | None = None
    version: str | None = None
    updated_at: datetime | None = None
    account_email: str | None = None
    plan: str | None = None
    login_method: str | None = None
    windows: list[RateWindow] = field(default_factory=list)
    pace: dict[str, Pace] = field(default_factory=dict)
    credits_remaining: float | None = None
    credits_unit: str = "credits"
    credits_available: bool = False
    cost: CostInfo | None = None
    status_level: str | None = None
    status_description: str | None = None
    error: str | None = None
    details: list[DetailSection] = field(default_factory=list)
    reset_credits_available: int = 0
    reset_credits: list[dict[str, Any]] = field(default_factory=list)
    credit_events: list[CreditEvent] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)
    selected_account: str | None = None
    accent_color: str = "#6366F1"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_error(self) -> bool:
        return bool(self.error)

    @property
    def primary_window(self) -> RateWindow | None:
        return self.windows[0] if self.windows else None

    @property
    def max_used_percent(self) -> float:
        return max((w.used_percent for w in self.windows), default=0.0)

    def window(self, key: str) -> RateWindow | None:
        for win in self.windows:
            if win.key == key:
                return win
        return None

    def pace_for(self, win: RateWindow) -> Pace | None:
        return self.pace.get(win.key)

    @property
    def subtitle(self) -> str:
        parts = []
        if self.plan:
            parts.append(self.plan)
        if self.account_email:
            parts.append(self.account_email)
        return " · ".join(parts)


def _window_from(payload: dict[str, Any], key: str, title: str) -> RateWindow | None:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return None
    used = raw.get("usedPercent")
    used_percent = _optional_float(used)
    return RateWindow(
        key=key,
        title=title or key.title(),
        used_percent=used_percent if used_percent is not None else 0.0,
        resets_at=parse_timestamp(raw.get("resetsAt")),
        reset_description=raw.get("resetDescription"),
        window_minutes=_optional_int(raw.get("windowMinutes")),
        next_regen_percent=_optional_float(raw.get("nextRegenPercent")),
        is_placeholder=bool(raw.get("isSyntheticPlaceholder")),
        quota_limit=_optional_float(raw.get("quotaLimit")),
        quota_unit=(
            raw.get("quotaUnit") if isinstance(raw.get("quotaUnit"), str) else None
        ),
        usage_known=used_percent is not None,
    )


def _pace_from(payload: Any) -> Pace | None:
    if not isinstance(payload, dict):
        return None
    stage = payload.get("stage")
    if not stage:
        return None
    return Pace(
        stage=stage,
        delta_percent=payload.get("deltaPercent"),
        expected_used_percent=payload.get("expectedUsedPercent"),
        will_last_to_reset=bool(payload.get("willLastToReset", True)),
        eta_seconds=payload.get("etaSeconds"),
        run_out_probability=payload.get("runOutProbability"),
        summary=payload.get("summary"),
    )


def _details_from(payload: Any) -> list[DetailSection]:
    sections: list[DetailSection] = []
    if not isinstance(payload, list):
        return sections
    for raw_section in payload[:8]:
        if not isinstance(raw_section, dict):
            continue
        rows: list[DetailRow] = []
        for raw_row in (raw_section.get("rows") or [])[:24]:
            if not isinstance(raw_row, dict):
                continue
            progress = raw_row.get("progress") or {}
            used_percent = progress.get("usedPercent") if isinstance(progress, dict) else None
            rows.append(
                DetailRow(
                    label=str(raw_row.get("label", "")),
                    value=str(raw_row.get("value", "")),
                    secondary_value=raw_row.get("secondaryValue"),
                    used_percent=float(used_percent) if isinstance(used_percent, (int, float)) else None,
                    severity=str(raw_row.get("severity", "normal")),
                )
            )
        chart = None
        raw_chart = raw_section.get("chart")
        if isinstance(raw_chart, dict):
            points = []
            for point in raw_chart.get("points") or []:
                if not isinstance(point, dict):
                    continue
                value = point.get("value")
                points.append(
                    (
                        str(point.get("label", "")),
                        float(value) if isinstance(value, (int, float)) else 0.0,
                    )
                )
            chart = DetailChart(
                kind=str(raw_chart.get("kind", "bars")),
                title=raw_chart.get("title"),
                unit=raw_chart.get("unit"),
                points=points[:120],
            )

        sections.append(
            DetailSection(
                title=raw_section.get("title"),
                rows=rows,
                chart=chart,
            )
        )
    return sections


def _reset_credits_from(payload: Any) -> list[dict[str, Any]]:
    """The available rate-limit reset credits, with their expirations.

    Mirrors the macOS ``LimitResetCreditsPresentation`` source data: only
    credits that are still available are listed, each with an optional
    ``expires_at``.
    """
    credits: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return credits
    for raw in payload.get("credits") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("status") or "available") != "available":
            continue
        credits.append(
            {
                "title": raw.get("title"),
                "granted_at": parse_timestamp(raw.get("grantedAt") or raw.get("granted_at")),
                "expires_at": parse_timestamp(raw.get("expiresAt") or raw.get("expires_at")),
                "description": raw.get("description"),
            }
        )
    return credits


def provider_usage_from_payload(payload: dict[str, Any]) -> ProviderUsage:
    """Convert one CLI ``ProviderPayload`` into a :class:`ProviderUsage`."""
    provider_id = str(payload.get("provider") or "unknown")
    usage = payload.get("usage") or {}
    labels = payload.get("rateWindowLabels") or {}

    windows: list[RateWindow] = []
    for key in WINDOW_KEYS:
        window = _window_from(usage, key, labels.get(key))
        if window is not None:
            windows.append(window)

    extra = usage.get("extraRateWindows")
    if isinstance(extra, list):
        for item in extra[:6]:
            if not isinstance(item, dict):
                continue
            inner = item.get("window") or {}
            if not isinstance(inner, dict):
                continue
            used = inner.get("usedPercent")
            used_percent = _optional_float(used)
            windows.append(
                RateWindow(
                    key=str(item.get("id") or "extra"),
                    title=str(item.get("title") or item.get("id") or "Extra"),
                    used_percent=used_percent if used_percent is not None else 0.0,
                    resets_at=parse_timestamp(inner.get("resetsAt")),
                    reset_description=inner.get("resetDescription"),
                    window_minutes=_optional_int(inner.get("windowMinutes")),
                    next_regen_percent=_optional_float(inner.get("nextRegenPercent")),
                    is_placeholder=bool(inner.get("isSyntheticPlaceholder")),
                    quota_limit=_optional_float(inner.get("quotaLimit")),
                    quota_unit=(
                        inner.get("quotaUnit")
                        if isinstance(inner.get("quotaUnit"), str)
                        else None
                    ),
                    usage_known=(
                        item.get("usageKnown", used_percent is not None) is not False
                        and used_percent is not None
                    ),
                )
            )

    pace: dict[str, Pace] = {}
    raw_pace = payload.get("pace") or {}
    if isinstance(raw_pace, dict):
        for key in WINDOW_KEYS:
            parsed = _pace_from(raw_pace.get(key))
            if parsed is not None:
                pace[key] = parsed

    credits = payload.get("credits") or {}
    credits_remaining = credits.get("remaining")
    if not isinstance(credits_remaining, (int, float)):
        credits_remaining = None

    cost: CostInfo | None = None
    raw_cost = usage.get("providerCost")
    if isinstance(raw_cost, dict):
        cost = CostInfo(
            used=float(raw_cost.get("used") or 0.0),
            limit=float(raw_cost.get("limit") or 0.0),
            currency=str(raw_cost.get("currencyCode") or "USD"),
            period=raw_cost.get("period"),
            balance=raw_cost.get("balance"),
            personal_used=raw_cost.get("personalUsed"),
            resets_at=parse_timestamp(raw_cost.get("resetsAt")),
        )

    identity = usage.get("identity") or {}
    account_email = identity.get("accountEmail") or usage.get("accountEmail")
    status = payload.get("status") or {}
    error = payload.get("error") or {}
    error_message = error.get("message") if isinstance(error, dict) else None

    credit_events: list[CreditEvent] = []
    for event in credits.get("events") or []:
        if not isinstance(event, dict):
            continue
        used = event.get("creditsUsed")
        credit_events.append(
            CreditEvent(
                id=str(event.get("id", "")),
                date=str(event.get("date", "")),
                service=str(event.get("service", "")),
                used=float(used) if isinstance(used, (int, float)) else 0.0,
            )
        )

    reset_credits = usage.get("codexResetCredits") or {}
    reset_credits_available = reset_credits.get("availableCount") or 0

    return ProviderUsage(
        reset_credits=_reset_credits_from(reset_credits),
        provider_id=provider_id,
        display_name=provider_meta.display_name(provider_id),
        source=payload.get("source"),
        version=payload.get("version"),
        updated_at=parse_timestamp(usage.get("updatedAt")),
        account_email=account_email,
        plan=_plan_from(payload, identity),
        login_method=identity.get("loginMethod") or usage.get("loginMethod"),
        windows=windows,
        pace=pace,
        credits_remaining=float(credits_remaining) if credits_remaining is not None else None,
        credits_available=bool(credits.get("creditsAvailable")),
        cost=cost,
        status_level=(status.get("indicator") if isinstance(status, dict) else None),
        status_description=(status.get("description") if isinstance(status, dict) else None),
        error=error_message,
        details=_details_from(usage.get("details")),
        reset_credits_available=int(reset_credits_available or 0),
        credit_events=credit_events,
        accent_color=provider_meta.accent_color(provider_id),
        raw=payload,
    )


def _plan_from(payload: dict[str, Any], identity: dict[str, Any]) -> str | None:
    for key in ("plan", "subscriptionPlan"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    value = identity.get("plan")
    if isinstance(value, str) and value:
        return value
    login = identity.get("loginMethod")
    if isinstance(login, str) and login and login not in {"oauth", "apiKey", "cookie"}:
        return login.title()
    return None


@dataclass
class AgentSession:
    """A running or recent coding-agent session."""

    id: str
    provider: str = ""
    state: str = ""
    project_name: str = ""
    cwd: str = ""
    pid: int = 0
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    host: str = ""

    @property
    def is_running(self) -> bool:
        return self.state.lower() in {"running", "active", "live"}


def agent_sessions_from_payloads(payloads: list[Any]) -> list[AgentSession]:
    sessions: list[AgentSession] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        sessions.append(
            AgentSession(
                id=str(payload.get("id", "")),
                provider=str(payload.get("provider", "")),
                state=str(payload.get("state", "")),
                project_name=str(payload.get("projectName") or ""),
                cwd=str(payload.get("cwd") or ""),
                pid=int(payload.get("pid") or 0),
                started_at=parse_timestamp(payload.get("startedAt")),
                last_activity_at=parse_timestamp(payload.get("lastActivityAt")),
                host=str(payload.get("host") or ""),
            )
        )
    sessions.sort(key=lambda s: (not s.is_running, s.last_activity_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=False)
    return sessions


@dataclass
class SpendProvider:
    """Spend and token usage for one provider."""

    provider: str
    cost: float = 0.0
    tokens: int = 0
    session_tokens: int = 0
    daily: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    priced: bool = True
    provenance: str = ""
    cost_known: bool = False

    @property
    def display_name(self) -> str:
        return provider_meta.display_name(self.provider)


@dataclass
class SpendSummary:
    """Aggregated local spend from ``codexbar cost``."""

    total_cost: float = 0.0
    cost_known: bool = False
    cost_partial: bool = False
    currency: str = "USD"
    total_tokens: int = 0
    coverage: dict[str, int] = field(default_factory=dict)
    provenance: str = "unknown"
    reporting_period: str | None = None
    history_label: str | None = None
    history_coverage_established: bool = True
    daily: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    session_cost: float = 0.0
    session_cost_known: bool = False
    session_tokens: int = 0
    last30_cost: float = 0.0
    last30_cost_known: bool = False
    last30_cost_partial: bool = False
    last30_tokens: int = 0
    incomplete_requests: int = 0
    error: str | None = None
    providers: list[SpendProvider] = field(default_factory=list)


def spend_from_payloads(payloads: list[dict[str, Any]]) -> SpendSummary:
    summary = SpendSummary()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        entry = SpendProvider(provider=str(payload.get("provider") or "unknown"))
        if payload.get("error"):
            summary.error = str(payload["error"].get("message") if isinstance(payload["error"], dict) else payload["error"])
            continue
        entry.provenance = str(payload.get("provenance") or "")
        summary.currency = payload.get("currencyCode") or summary.currency
        summary.provenance = payload.get("provenance") or summary.provenance
        totals = payload.get("totals")
        totals = totals if isinstance(totals, dict) else {}
        coverage = payload.get("coverage")
        if not isinstance(coverage, dict):
            coverage = totals.get("coverage")
        if isinstance(coverage, dict):
            for key, value in coverage.items():
                summary.coverage[key] = summary.coverage.get(key, 0) + int(value or 0)
        summary.reporting_period = payload.get("reportingPeriod") or summary.reporting_period
        summary.history_label = payload.get("historyLabel") or summary.history_label
        if payload.get("historyCoverageIsEstablished") is False:
            summary.history_coverage_established = False
        # The CLI repeats totals at the top level on some versions. Choose one
        # representation per provider; never sum two views of the same data.
        raw_cost = payload.get("totalCost")
        if raw_cost is None:
            raw_cost = totals.get("totalCost")
        cost = _optional_float(raw_cost)
        if cost is not None:
            summary.total_cost += cost
            summary.cost_known = True
            entry.cost = cost
            entry.cost_known = True
        raw_tokens = payload.get("totalTokens")
        if raw_tokens is None:
            raw_tokens = totals.get("totalTokens")
        tokens = _optional_int(raw_tokens)
        if tokens is not None:
            summary.total_tokens += tokens
            entry.tokens = tokens
        session_cost = _optional_float(payload.get("sessionCostUSD"))
        if session_cost is not None:
            summary.session_cost += session_cost
            summary.session_cost_known = True
        summary.session_tokens += int(payload.get("sessionTokens") or 0)
        entry.session_tokens += int(payload.get("sessionTokens") or 0)
        last30_cost = _optional_float(payload.get("last30DaysCostUSD"))
        if last30_cost is not None:
            summary.last30_cost += last30_cost
            summary.last30_cost_known = True
        else:
            summary.last30_cost_partial = True
        summary.last30_tokens += int(payload.get("last30DaysTokens") or 0)
        summary.incomplete_requests += int(payload.get("incompleteRequestCount") or 0)

        summary.provenance = totals.get("provenance") or summary.provenance
        entry.priced = entry.cost_known
        summary.cost_partial |= (
            not entry.cost_known
            or not summary.history_coverage_established
            or bool((coverage or {}).get("unpriced"))
            or bool((coverage or {}).get("unmetered"))
            or bool(payload.get("incompleteRequestCount") or totals.get("incompleteRequestCount"))
        )
        if payload.get("incompleteRequestCount") is None:
            summary.incomplete_requests += int(totals.get("incompleteRequestCount") or 0)

        for day in payload.get("daily") or []:
            if isinstance(day, dict):
                summary.daily.append(day)
                entry.daily.append(day)
                for model in day.get("modelBreakdowns") or []:
                    if isinstance(model, dict):
                        summary.models.append(model)
        for project in payload.get("projects") or []:
            if isinstance(project, dict):
                summary.projects.append(project)
                entry.projects.append(project)
        for model in payload.get("models") or []:
            if isinstance(model, dict):
                summary.models.append(model)

        summary.providers.append(entry)

    summary.cost_partial |= bool(summary.error)
    summary.providers = [p for p in summary.providers if p.tokens or p.cost_known]
    summary.providers.sort(key=lambda p: (p.cost, p.tokens), reverse=True)
    summary.daily.sort(key=lambda e: e.get("date", ""))
    summary.projects.sort(key=lambda e: float(e.get("totalCost") or 0.0), reverse=True)
    summary.models.sort(key=lambda e: float(e.get("cost") or e.get("totalCost") or 0.0), reverse=True)
    return summary
