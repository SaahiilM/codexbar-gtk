"""A small local history of quota usage.

The CLI does not expose historical quota snapshots, so the app records them
itself. Every refresh appends one sample per provider window; the file is kept
as JSON lines and pruned to a configurable number of days.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass

from . import rust_bridge

DEFAULT_PATH = os.path.expanduser("~/.config/codexbar-gtk/history.jsonl")
RETENTION_DAYS = 30


@dataclass
class Sample:
    timestamp: float
    provider: str
    window: str
    used_percent: float


class HistoryStore:
    """Append-only sample log with a simple query API."""

    def __init__(
        self, path: str = DEFAULT_PATH, retention_days: int = RETENTION_DAYS
    ) -> None:
        self.path = path
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._cache: list[Sample] | None = None
        self._rust = None
        self._rust_key = None
        self._python_only = False

    def _rust_store(self):
        core = rust_bridge.extension()
        if core is None:
            return None
        path = os.fspath(self.path)
        if not isinstance(path, str):
            raise TypeError("Rust history paths must be text paths")
        if not isinstance(self.retention_days, int) or not -(2**63) <= self.retention_days < 2**63:
            raise OverflowError("Rust history retention must fit in signed 64-bit range")
        if self._python_only:
            raise RuntimeError("Rust history store cannot switch to Python mode")
        key = (path, self.retention_days)
        with self._lock:
            if self._rust_key != key:
                self._rust = core.HistoryStore(path, self.retention_days)
                self._rust_key = key
                self._cache = None
            return self._rust

    # -- writing ----------------------------------------------------------

    def append(self, samples: list[Sample]) -> None:
        if not samples:
            return
        core = self._rust_store()
        if core is not None:
            try:
                compatible = all(
                    isinstance(sample.provider, str)
                    and isinstance(sample.window, str)
                    and all(
                        isinstance(value, (int, float)) and math.isfinite(value)
                        for value in (sample.timestamp, sample.used_percent)
                    )
                    for sample in samples
                )
            except OverflowError as exc:
                raise OverflowError(
                    "Rust history samples must fit finite floating-point range"
                ) from exc
            if not compatible:
                raise TypeError("Rust history samples require finite text and numeric fields")
            core.append(
                [
                    (
                        float(round(s.timestamp, 2)),
                        s.provider,
                        s.window,
                        float(round(s.used_percent, 2)),
                    )
                    for s in samples
                ]
            )
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self._lock, open(self.path, "a", encoding="utf-8") as handle:
                for sample in samples:
                    handle.write(
                        json.dumps(
                            {
                                "t": round(sample.timestamp, 2),
                                "p": sample.provider,
                                "w": sample.window,
                                "u": round(sample.used_percent, 2),
                            }
                        )
                        + "\n"
                    )
        except OSError:
            return
        self._cache = None

    def prune(self) -> None:
        """Drop samples older than the retention window."""
        core = self._rust_store()
        if core is not None:
            core.prune(time.time())
            return
        cutoff = time.time() - self.retention_days * 86400
        kept = [s for s in self.read_all() if s.timestamp >= cutoff]
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self._lock, open(self.path, "w", encoding="utf-8") as handle:
                for sample in kept:
                    handle.write(
                        json.dumps(
                            {
                                "t": round(sample.timestamp, 2),
                                "p": sample.provider,
                                "w": sample.window,
                                "u": round(sample.used_percent, 2),
                            }
                        )
                        + "\n"
                    )
        except OSError:
            return
        self._cache = None

    # -- reading ----------------------------------------------------------

    def read_all(self) -> list[Sample]:
        core = self._rust_store()
        if core is not None:
            return [Sample(*row) for row in core.read_all()]
        with self._lock:
            if self._cache is not None:
                return list(self._cache)
        samples: list[Sample] = []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    try:
                        sample = Sample(
                            timestamp=float(raw.get("t", 0)),
                            provider=raw.get("p", ""),
                            window=raw.get("w", ""),
                            used_percent=float(raw.get("u", 0)),
                        )
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if (
                        isinstance(sample.provider, str)
                        and isinstance(sample.window, str)
                        and math.isfinite(sample.timestamp)
                        and math.isfinite(sample.used_percent)
                    ):
                        samples.append(sample)
        except OSError:
            samples = []
        with self._lock:
            self._cache = samples
        return list(samples)

    def series(
        self, provider: str, window: str, hours: float = 24.0
    ) -> list[tuple[float, float]]:
        """Return ``[(timestamp, used_percent)]`` for one provider window."""
        core = self._rust_store()
        if core is not None:
            if (
                not isinstance(provider, str)
                or not isinstance(window, str)
                or not isinstance(hours, (int, float))
            ):
                raise TypeError("Rust history queries require text keys and numeric hours")
            return core.series(provider, window, float(hours), time.time())
        cutoff = time.time() - hours * 3600
        points = [
            (s.timestamp, s.used_percent)
            for s in self.read_all()
            if s.provider == provider and s.window == window and s.timestamp >= cutoff
        ]
        points.sort(key=lambda item: item[0])
        return points
