"""Formatting helpers shared by the popover, the dashboard and the tray tooltip."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import rust_bridge
from .currency import CURRENCIES

RESET_STYLES = ("countdown", "absolute", "both")


def _rust_datetime(value: datetime | None) -> str | None:
    """Serialize UTC datetimes accepted by the current Rust formatting API."""
    if value is None or not isinstance(value, datetime):
        return None
    try:
        if value.utcoffset() != timedelta(0):
            return None
    except (OverflowError, ValueError):
        return None
    return value.isoformat()


def _rust_datetime_compatible(value: datetime | None) -> bool:
    return value is None or _rust_datetime(value) is not None


def _rust_number_compatible(value: float | None) -> bool:
    if value is None:
        return True
    if type(value) not in (int, float):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number)


def compact_window_label(title: str | None, window_minutes: int | None) -> str | None:
    """Short label identifying a quota window, mirroring macOS ``windowPrefix``.

    Session windows render as ``5h``/``90m`` from the window length, weekly and
    other named windows as an uppercased initial (``W``), like the automatic
    menu-bar tokens use (#4743).
    """
    core = rust_bridge.extension()
    compatible = (
        (
            window_minutes is None
            or isinstance(window_minutes, int)
            and not isinstance(window_minutes, bool)
            and -(2**63) <= window_minutes < 2**63
        )
        and (title is None or isinstance(title, str))
    )
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "compact window label")
        return core.compact_window_label(title, window_minutes)
    text = (title or "").strip()
    if not text:
        return None
    lower = text.lower()
    if "session" in lower:
        minutes = window_minutes
        if minutes and minutes > 0:
            if minutes % 60 == 0:
                return f"{minutes // 60}h"
            return f"{minutes}m"
        return "S"
    return text[:1].upper()


def format_percent(value: float | None, decimals: int = 0) -> str:
    core = rust_bridge.extension()
    compatible = _rust_number_compatible(value) and type(decimals) is int and decimals >= 0
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "percent formatting")
        return core.format_percent(value, decimals)
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


def format_remaining(used_percent: float | None, decimals: int = 0) -> str:
    core = rust_bridge.extension()
    compatible = _rust_number_compatible(used_percent) and type(decimals) is int and decimals >= 0
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "remaining-percent formatting")
        return core.format_remaining(used_percent, decimals)
    if used_percent is None:
        return "—"
    remaining = max(0.0, 100.0 - used_percent)
    return f"{remaining:.{decimals}f}%"


def format_countdown(
    target: datetime | None, now: datetime | None = None
) -> str | None:
    """Human readable ``4h 12m`` style countdown to ``target``."""
    core = rust_bridge.extension()
    if core is not None:
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = _rust_datetime_compatible(target) and rust_now is not None
        rust_bridge.reject_unsupported(
            core if not compatible else None,
            "countdown formatting",
            "datetime values must be UTC-aware",
        )
        return core.format_countdown(_rust_datetime(target), rust_now)
    if target is None:
        return None
    now = now or datetime.now(timezone.utc)
    delta = target - now
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "now"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days >= 1:
        return f"{days}d {hours}h"
    if hours >= 1:
        return f"{hours}h {minutes}m"
    if minutes >= 1:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_absolute(target: datetime | None, now: datetime | None = None) -> str | None:
    core = rust_bridge.extension()
    if core is not None:
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = _rust_datetime_compatible(target) and rust_now is not None
        rust_bridge.reject_unsupported(
            core if not compatible else None,
            "absolute-time formatting",
            "datetime values must be UTC-aware",
        )
        return core.format_absolute(_rust_datetime(target), rust_now)
    if target is None:
        return None
    now = now or datetime.now(timezone.utc)
    if target.date() == now.date():
        return target.strftime("%H:%M")
    if (now - target).days <= 7:
        return target.strftime("%a %H:%M")
    return target.strftime("%b %d %H:%M")


def format_reset(
    target: datetime | None,
    style: str = "countdown",
    now: datetime | None = None,
) -> str | None:
    core = rust_bridge.extension()
    if core is not None:
        now = now or datetime.now(timezone.utc)
        compatible = (
            isinstance(style, str)
            and _rust_datetime_compatible(target)
            and _rust_datetime_compatible(now)
        )
        rust_bridge.reject_unsupported(
            core if not compatible else None,
            "reset formatting",
            "style must be text and datetime values must be UTC-aware",
        )
        return core.format_reset(_rust_datetime(target), style, _rust_datetime(now))
    countdown = format_countdown(target, now)
    absolute = format_absolute(target, now)
    if style == "absolute":
        return absolute
    if style == "both":
        if countdown and absolute:
            return f"resets in {countdown} · {absolute}"
        return countdown or absolute
    if not countdown:
        return None
    if countdown == "now":
        return "resetting now"
    return f"resets in {countdown}"


def format_currency(
    value: float | None, currency: str = "USD", compact: bool = False
) -> str:
    core = rust_bridge.extension()
    compatible = (
        _rust_number_compatible(value)
        and isinstance(currency, str)
        and type(compact) is bool
    )
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "currency formatting")
        return core.format_currency(value, currency, compact)
    if value is None:
        return "—"
    symbol = {code: glyph for code, glyph, _rate in CURRENCIES}.get(
        currency.upper(), ""
    )
    prefix = symbol if symbol else ""
    suffix = "" if symbol else f" {currency}"
    if compact and abs(value) >= 1000:
        return f"{prefix}{value / 1000:,.1f}k{suffix}"
    if abs(value) >= 100 or value == int(value):
        return f"{prefix}{value:,.0f}{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def format_credits(value: float | None) -> str:
    core = rust_bridge.extension()
    compatible = _rust_number_compatible(value)
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "credit formatting")
        return core.format_credits(value)
    if value is None:
        return "—"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def format_tokens(value: int | None) -> str:
    core = rust_bridge.extension()
    compatible = (
        value is None
        or type(value) is int and -(2**127) <= value < 2**127
    )
    if core is not None:
        if type(value) is int and not compatible:
            raise OverflowError(
                "Rust token formatting supports signed 128-bit integer values"
            )
        rust_bridge.reject_unsupported(core if not compatible else None, "token formatting")
        return core.format_tokens(value)
    if not value:
        return "0"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_updated(target: datetime | None, now: datetime | None = None) -> str | None:
    core = rust_bridge.extension()
    if core is not None:
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = _rust_datetime_compatible(target) and rust_now is not None
        rust_bridge.reject_unsupported(
            core if not compatible else None,
            "updated-time formatting",
            "datetime values must be UTC-aware",
        )
        return core.format_updated(_rust_datetime(target), rust_now)
    if target is None:
        return None
    now = now or datetime.now(timezone.utc)
    delta = now - target
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def format_reset_credits(
    expirations: list[datetime | None],
    style: str = "countdown",
    now: datetime | None = None,
) -> tuple[str, str, list[str]] | None:
    """Present the expiring reset-credit inventory like the macOS app.

    Returns ``(count_text, compact_text, help_items)`` where ``compact_text``
    lists the first four expirations ("4h 39m · 7d 2h …", or times with the
    absolute style) and ``help_items`` one line per credit. ``None`` when
    there is nothing to show.
    """
    core = rust_bridge.extension()
    if core is not None:
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = (
            isinstance(style, str)
            and all(_rust_datetime_compatible(item) for item in expirations)
            and rust_now is not None
        )
        rust_bridge.reject_unsupported(
            core if not compatible else None,
            "credit-expiry formatting",
            "style must be text and datetime values must be UTC-aware",
        )
        return core.format_reset_credits(
            [_rust_datetime(item) for item in expirations], style, rust_now
        )
    if not expirations:
        return None
    now = now or datetime.now(timezone.utc)
    count_text = (
        "1 available" if len(expirations) == 1 else f"{len(expirations)} available"
    )

    def expiry_item(expires_at: datetime | None) -> tuple[str, str]:
        if expires_at is None:
            return ("No expiry", "No expiry")
        countdown = format_countdown(expires_at, now)
        if style == "countdown" and countdown:
            compact = countdown
        else:
            compact = format_absolute(expires_at, now) or "No expiry"
        return (f"Expires {compact}", compact)

    items = [expiry_item(expires_at) for expires_at in expirations]
    visible = [compact for _, compact in items[:4]]
    hidden = len(items) - len(visible)
    if hidden > 0:
        visible.append(f"+{hidden}")
    return (count_text, " · ".join(visible), [line for line, _ in items])


def format_pace(pace) -> str:
    """Compact pace text, matching the macOS app's wording."""
    core = rust_bridge.extension()
    delta = pace.delta_percent
    if core is not None:
        compatible = (
            _rust_number_compatible(delta)
            and isinstance(pace.stage, str)
            and isinstance(pace.in_deficit, bool)
            and isinstance(pace.in_reserve, bool)
            and isinstance(pace.stage_label, str)
        )
        rust_bridge.reject_unsupported(core if not compatible else None, "pace formatting")
        return core.format_pace(
            pace.stage,
            delta,
            pace.in_deficit,
            pace.in_reserve,
            pace.stage_label,
        )
    value = int(round(abs(float(delta)))) if delta is not None else 0
    if pace.stage == "onTrack" or value == 0:
        return "On pace"
    if pace.in_deficit:
        return f"{value}% in deficit"
    if pace.in_reserve:
        return f"{value}% in reserve"
    return pace.stage_label


def format_window_span(minutes: int | None) -> str | None:
    core = rust_bridge.extension()
    compatible = minutes is None or type(minutes) is int and -(2**63) <= minutes < 2**63
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "window-span formatting")
        return core.format_window_span(minutes)
    if not minutes:
        return None
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days}d" if days > 1 else "24h"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def next_refresh_delta(interval_seconds: int) -> timedelta:
    core = rust_bridge.extension()
    compatible = type(interval_seconds) is int and -(2**63) <= interval_seconds < 2**63
    if core is not None:
        rust_bridge.reject_unsupported(core if not compatible else None, "refresh-interval formatting")
        return timedelta(seconds=core.next_refresh_seconds(interval_seconds))
    return timedelta(seconds=max(5, interval_seconds))


def workday_progress_percent(
    resets_at: datetime | None, now: datetime | None = None, work_days: int = 5
) -> float | None:
    """How far through the working days a weekly window is, in percent.

    Mirrors the macOS app's weekly progress tick: with five work days only the
    Monday to Friday stretch counts towards the expected burn.
    """
    core = rust_bridge.extension()
    if core is not None:
        if type(work_days) is int and work_days <= 0:
            return None
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = (
            _rust_datetime_compatible(resets_at)
            and rust_now is not None
            and type(work_days) is int
            and 0 <= work_days <= 4_294_967_295
        )
        rust_bridge.reject_unsupported(core if not compatible else None, "workday-progress calculation")
        return core.workday_progress_percent(_rust_datetime(resets_at), rust_now, work_days)
    if resets_at is None or work_days <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    week_start = resets_at - timedelta(days=7)
    if now >= resets_at:
        return 100.0

    total_work = 0.0
    elapsed_work = 0.0
    cursor = week_start
    while cursor < resets_at:
        is_workday = cursor.weekday() < work_days
        if is_workday:
            total_work += 1
            if cursor <= now:
                elapsed_work += 1
        cursor += timedelta(days=1)

    if total_work <= 0:
        return None
    return max(0.0, min(100.0, (elapsed_work / total_work) * 100.0))


def project_usage_at_reset(
    used_percent: float,
    samples: list[tuple[float, float]],
    resets_at: datetime | None,
    now: datetime | None = None,
) -> float | None:
    """Project the quota usage when the window resets, from recorded samples."""
    core = rust_bridge.extension()
    compatible = (
        _rust_datetime_compatible(resets_at)
        and _rust_number_compatible(used_percent)
        and all(
            isinstance(t, (int, float))
            and _rust_number_compatible(t)
            and _rust_number_compatible(value)
            for t, value in samples
        )
    )
    if core is not None:
        now = now or datetime.now(timezone.utc)
        rust_now = _rust_datetime(now)
        compatible = compatible and rust_now is not None
        rust_bridge.reject_unsupported(core if not compatible else None, "reset-projection calculation")
        return core.project_usage_at_reset(
            used_percent,
            [(t, value) for t, value in samples],
            _rust_datetime(resets_at),
            rust_now,
        )
    if resets_at is None or len(samples) < 2:
        return None
    now = now or datetime.now(timezone.utc)
    (first_t, first_v), (last_t, last_v) = samples[0], samples[-1]
    span = last_t - first_t
    if span <= 0:
        return None
    per_second = (last_v - first_v) / span
    hours_left = max(0.0, (resets_at - now).total_seconds() / 3600.0)
    projected = used_percent + per_second * hours_left * 3600.0
    return max(0.0, min(200.0, projected))
