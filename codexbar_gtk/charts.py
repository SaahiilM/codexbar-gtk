"""Pure geometry helpers for small local charts."""

from __future__ import annotations

import math

from . import rust_bridge


def _rust_number_compatible(value) -> bool:
    return isinstance(value, (int, float)) and not (
        isinstance(value, int) and abs(value) > 2**53
    )


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
    core = rust_bridge.extension()
    if (
        core is not None
        and isinstance(width, int)
        and isinstance(height, int)
        and width <= 2**53
        and height <= 2**53
        and isinstance(points, (list, tuple))
        and all(
            _rust_number_compatible(timestamp) and _rust_number_compatible(value)
            for timestamp, value in points
        )
    ):
        return core.sparkline_coordinates(points, width, height)
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
