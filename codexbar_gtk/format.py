"""Formatting helpers shared by the popover, the dashboard and the tray tooltip."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

RESET_STYLES = ("countdown", "absolute", "both")


def format_percent(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


def format_remaining(used_percent: float | None, decimals: int = 0) -> str:
    if used_percent is None:
        return "—"
    remaining = max(0.0, 100.0 - used_percent)
    return f"{remaining:.{decimals}f}%"


def format_countdown(target: datetime | None, now: datetime | None = None) -> str | None:
    """Human readable ``4h 12m`` style countdown to ``target``."""
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


def format_currency(value: float | None, currency: str = "USD", compact: bool = False) -> str:
    if value is None:
        return "—"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹"}.get(currency.upper(), "")
    prefix = symbol if symbol else ""
    suffix = "" if symbol else f" {currency}"
    if compact and abs(value) >= 1000:
        return f"{prefix}{value / 1000:,.1f}k{suffix}"
    if abs(value) >= 100 or value == int(value):
        return f"{prefix}{value:,.0f}{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def format_credits(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def format_tokens(value: int | None) -> str:
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
    if not expirations:
        return None
    now = now or datetime.now(timezone.utc)
    count_text = "1 available" if len(expirations) == 1 else f"{len(expirations)} available"

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
    delta = pace.delta_percent
    value = int(round(abs(float(delta)))) if delta is not None else 0
    if pace.stage == "onTrack" or value == 0:
        return "On pace"
    if pace.in_deficit:
        return f"{value}% in deficit"
    if pace.in_reserve:
        return f"{value}% in reserve"
    return pace.stage_label


def format_window_span(minutes: int | None) -> str | None:
    if not minutes:
        return None
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days}d" if days > 1 else "24h"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def next_refresh_delta(interval_seconds: int) -> timedelta:
    return timedelta(seconds=max(5, interval_seconds))


def workday_progress_percent(
    resets_at: datetime | None, now: datetime | None = None, work_days: int = 5
) -> float | None:
    """How far through the working days a weekly window is, in percent.

    Mirrors the macOS app's weekly progress tick: with five work days only the
    Monday to Friday stretch counts towards the expected burn.
    """
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
