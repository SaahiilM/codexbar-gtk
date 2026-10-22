"""Pure helpers behind the spend activity heatmap.

Kept free of GTK so the behaviour can be tested head-less, exactly like the
``SpendActivityLevels`` helpers in the macOS app.
"""

from __future__ import annotations

from datetime import date, timedelta

WEEK_COUNT = 53
DAY_COUNT = 7


def activity_levels(values: list[int]) -> list[int]:
    """Bucket values into the five heatmap levels (empty + four shades)."""
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
    total = 0
    running = []
    for value in values:
        total += max(0, value)
        running.append(total)
    return running


def align_start(today: date) -> date:
    """First Sunday of the one-year window ending on ``today``."""
    first = today - timedelta(days=364)
    return first - timedelta(days=(first.weekday() + 1) % DAY_COUNT)
