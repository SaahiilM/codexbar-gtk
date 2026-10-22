"""Monthly allowance daily targets.

Mirrors ``UsagePace.dailyTarget`` and ``UsagePaceText.dailyTarget`` in the macOS
app: divide what is left of a monthly allowance by the remaining local calendar
days (today included) and show it in the allowance's own unit.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import currency
from .currency import CURRENCIES
from .format import format_currency

MONTHLY_DAYS = range(28, 32)


def is_monthly_window(window_minutes: int | None) -> bool:
    """Whether a window is a monthly allowance (28-31 days)."""
    if window_minutes is None or window_minutes <= 0:
        return False
    rounded_days = math.floor(window_minutes / 1440 + 0.5)
    return rounded_days in MONTHLY_DAYS


def daily_target(
    remaining: float | None,
    resets_at: datetime | None,
    now: datetime | None = None,
) -> float | None:
    """Remaining allowance divided by the remaining local calendar days.

    Today counts even when it is almost over; a midnight reset starts the next
    allowance, so that day is not counted for this one. Unknown or expired
    resets have no target.
    """
    if remaining is None or not math.isfinite(remaining) or remaining < 0:
        return None
    if resets_at is None:
        return None
    try:
        reset_timestamp = resets_at.timestamp()
    except (OverflowError, OSError, ValueError):
        return None
    if not math.isfinite(reset_timestamp):
        return None

    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone()
    local_reset = resets_at.astimezone()
    if local_reset <= local_now:
        return None

    reset_day = local_reset.replace(hour=0, minute=0, second=0, microsecond=0)
    days = (reset_day.date() - local_now.date()).days
    day_count = max(1, days + (1 if local_reset > reset_day else 0))
    return remaining / day_count


def window_daily_target(window, now: datetime | None = None) -> float | None:
    """Daily target for a monthly quota window, in the window's own unit."""
    if (
        window.is_placeholder
        or not window.usage_known
        or not is_monthly_window(window.window_minutes)
    ):
        return None
    if not math.isfinite(window.used_percent) or window.used_percent < 0:
        return None
    limit = window.quota_limit if window.quota_limit and window.quota_limit > 0 else 100.0
    remaining = limit * window.remaining_percent / 100.0
    return daily_target(remaining, window.resets_at, now)


def format_window_target(
    window, preferred_currency: str = "auto", now: datetime | None = None
) -> str | None:
    """The menu-card line for a monthly quota window."""
    if window.quota_limit is not None and not window.quota_unit:
        return None
    unit = "%" if window.quota_limit is None else window.quota_unit
    return format_daily_target(
        window_daily_target(window, now),
        unit,
        preferred_currency,
    )


def format_monthly_cost_target(
    cost, preferred_currency: str = "auto", now: datetime | None = None
) -> str | None:
    """Format a provider's monthly spending cap as a daily target."""
    if cost is None:
        return None
    period = cost.period.strip().lower() if isinstance(cost.period, str) else ""
    if period not in {
        "monthly",
        "month",
        "this month",
        "monthly cap",
        "monthly credit limit",
    }:
        return None
    used, limit = cost.used, cost.limit
    if (
        not math.isfinite(used)
        or used < 0
        or not math.isfinite(limit)
        or limit <= 0
    ):
        return None
    target = daily_target(max(0.0, limit - used), cost.resets_at, now)
    return format_daily_target(target, cost.currency, preferred_currency)


def _number(value: float) -> str:
    """Up to two decimals, without trailing zeroes, with thousands separators."""
    text = f"{value:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


_ISO_CURRENCIES = {code for code, _glyph, _rate in CURRENCIES}


def format_daily_target(
    target: float | None,
    unit: str | None,
    preferred_currency: str = "auto",
) -> str | None:
    """Format a daily target the way the macOS menu card does."""
    if target is None or not math.isfinite(target):
        return None

    normalized = (unit or "%").strip()
    lowered = normalized.lower()
    if lowered in ("%", "percent"):
        amount = f"{_number(target)}%"
    elif lowered == "credits":
        amount = f"{_number(target)} credits"
    elif lowered == "requests":
        amount = f"{_number(target)} requests"
    else:
        code = normalized.upper()
        if code not in _ISO_CURRENCIES:
            return None
        preferred = (preferred_currency or "auto").upper()
        value = target
        output = code
        if preferred not in ("", "AUTO") and preferred != code:
            converted = currency.convert(target, code, preferred)
            if converted is not None:
                value, output = converted, preferred
        amount = format_currency(value, output)
    return f"≈ {amount} / day to last until reset"
