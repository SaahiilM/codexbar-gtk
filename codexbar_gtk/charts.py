"""Pure geometry helpers for small local charts."""

from __future__ import annotations

import math


def sparkline_coordinates(
    points: list[tuple[float, float]], width: int, height: int
) -> list[tuple[float, float]]:
    """Map timestamp/percentage samples to a stable 0–100% chart axis.

    A fixed quota axis avoids exaggerating tiny usage changes into full-height
    spikes. X positions use elapsed time rather than sample index so a burst of
    refreshes does not visually occupy the same duration as several quiet hours.
    """
    if width <= 1 or height <= 4:
        return []
    valid = [
        (timestamp, max(0.0, min(100.0, value)))
        for timestamp, value in points
        if math.isfinite(timestamp) and math.isfinite(value)
    ]
    if len(valid) < 2:
        return []

    first = valid[0][0]
    duration = valid[-1][0] - first
    if duration <= 0:
        duration = float(len(valid) - 1)
        times = [float(index) for index in range(len(valid))]
    else:
        times = [timestamp - first for timestamp, _ in valid]

    drawable_height = height - 4
    return [
        (
            (elapsed / duration) * (width - 1),
            height - 2 - (value / 100.0) * drawable_height,
        )
        for elapsed, (_, value) in zip(times, valid)
    ]
