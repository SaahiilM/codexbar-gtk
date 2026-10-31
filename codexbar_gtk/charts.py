"""Pure geometry helpers for small local charts."""

from __future__ import annotations

import math

from . import rust_bridge


def sparkline_coordinates(
    points: list[tuple[float, float]], width: int, height: int
) -> list[tuple[float, float]]:
    """Map timestamp/percentage samples to a stable 0–100% chart axis.

    A fixed quota axis avoids exaggerating tiny usage changes into full-height
    spikes. X positions use elapsed time rather than sample index so a burst of
    refreshes does not visually occupy the same duration as several quiet hours.
    """
    core = rust_bridge.extension()
    if core is not None:
        # Python accepts Fraction and integers well beyond f64's exact range.
        # Normalize valid timestamps before conversion so wide epochs and
        # Fraction spans retain their relative positions in Rust's f64 API.
        # Match the Python filter first: an invalid point cannot choose origin.
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
            rust_points = [
                (index / (len(valid) - 1), float(value))
                for index, (_timestamp, value) in enumerate(valid)
            ]
        else:
            rust_points = [
                (float((timestamp - first) / duration), float(value))
                for timestamp, value in valid
            ]
        try:
            rust_width, rust_height = float(width), float(height)
        except OverflowError as exc:
            raise OverflowError(
                "Rust chart dimensions must fit in finite floating-point range"
            ) from exc
        return core.sparkline_coordinates(rust_points, rust_width, rust_height)
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
