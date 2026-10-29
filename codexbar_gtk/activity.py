"""Pure helpers behind the spend activity heatmap.

Kept free of GTK so the behaviour can be tested head-less, exactly like the
``SpendActivityLevels`` helpers in the macOS app.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

from . import rust_bridge

WEEK_COUNT = 53
DAY_COUNT = 7


def activity_levels(values: list[int]) -> list[int]:
    """Bucket values into the five heatmap levels (empty + four shades)."""
    core = rust_bridge.extension()
    if core is not None:
        return core.activity_levels(values)
    peak = max(values, default=0)
    levels: list[int] = []
    for value in values:
        if value <= 0 or peak <= 0:
            levels.append(0)
            continue
        ratio = value / float(peak)
        if ratio > 0.75:
            levels.append(4)
        elif ratio > 0.5:
            levels.append(3)
        elif ratio > 0.25:
            levels.append(2)
        else:
            levels.append(1)
    return levels


def weekly_totals(start: date, values: dict[date, int], today: date) -> list[int]:
    """Sum each Sunday-aligned week, mirroring SpendActivitySeries.weeklyActivity."""
    core = rust_bridge.extension()
    if core is not None:
        return core.weekly_totals(
            start.isoformat(),
            [(day.isoformat(), value) for day, value in values.items()],
            today.isoformat(),
        )
    totals = []
    for week in range(WEEK_COUNT):
        total = 0
        for day in range(DAY_COUNT):
            current = start + timedelta(days=week * DAY_COUNT + day)
            if current > today:
                continue
            total += max(0, values.get(current, 0))
        totals.append(total)
    return totals


def cumulative_totals(values: list[int]) -> list[int]:
    """Running total per week, mirroring SpendActivityAggregateSeries.cumulative."""
    core = rust_bridge.extension()
    if core is not None:
        return core.cumulative_totals(values)
    total = 0
    running = []
    for value in values:
        total += max(0, value)
        running.append(total)
    return running


def daily_series(
    entries: list[dict],
    days: int = 30,
    history_coverage_established: bool = True,
) -> list[tuple[date, float | None]]:
    """Daily cost series with missing interior calendar days kept as zero.

    Providers that omit known zero-usage days used to compress the spend chart;
    filling those gaps keeps the x-axis proportional. Explicitly unpriced or
    incomplete days remain unknown, as do gaps before history coverage is
    established. Days outside the reported range stay absent.
    """
    core = rust_bridge.extension()
    if core is not None:
        try:
            entries_json = json.dumps(entries, allow_nan=False)
        except (TypeError, ValueError):
            # Preserve Python's broader input behavior for non-JSON values and
            # non-finite floats; CLI JSON payloads take the Rust path.
            pass
        else:
            return [
                (date.fromisoformat(day), value)
                for day, value in core.daily_series(
                    entries_json, days, history_coverage_established
                )
            ]

    totals: dict[date, float] = {}
    unknown: set[date] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("date") or "")
        try:
            day = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        raw_cost = entry.get("totalCost")
        if raw_cost is None:
            unknown.add(day)
            continue
        try:
            cost = float(raw_cost)
        except (OverflowError, TypeError, ValueError):
            unknown.add(day)
            continue
        if not math.isfinite(cost) or cost < 0:
            unknown.add(day)
            continue
        totals[day] = totals.get(day, 0.0) + cost
    if not totals and not unknown:
        return []

    observed_days = totals.keys() | unknown
    last = max(observed_days)
    if days is None:
        first = min(observed_days)
    else:
        first = max(min(observed_days), last - timedelta(days=max(1, days) - 1))
    return [
        (
            day,
            None
            if day in unknown or (day not in totals and not history_coverage_established)
            else totals.get(day, 0.0),
        )
        for day in (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    ]


def align_start(today: date) -> date:
    """First Sunday of the one-year window ending on ``today``."""
    core = rust_bridge.extension()
    if core is not None:
        return date.fromisoformat(core.align_start(today.isoformat()))
    first = today - timedelta(days=364)
    return first - timedelta(days=(first.weekday() + 1) % DAY_COUNT)
