"""A small local history of quota usage.

The CLI does not expose historical quota snapshots, so the app records them
itself. Every refresh appends one sample per provider window; the file is kept
as JSON lines and pruned to a configurable number of days.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

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

    def __init__(self, path: str = DEFAULT_PATH, retention_days: int = RETENTION_DAYS) -> None:
        self.path = path
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._cache: list[Sample] | None = None

    # -- writing ----------------------------------------------------------

    def append(self, samples: list[Sample]) -> None:
        if not samples:
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
                    samples.append(
                        Sample(
                            timestamp=float(raw.get("t", 0)),
                            provider=str(raw.get("p", "")),
                            window=str(raw.get("w", "")),
                            used_percent=float(raw.get("u", 0)),
                        )
                    )
        except OSError:
            samples = []
        with self._lock:
            self._cache = samples
        return list(samples)

    def series(
        self, provider: str, window: str, hours: float = 24.0
    ) -> list[tuple[float, float]]:
        """Return ``[(timestamp, used_percent)]`` for one provider window."""
        cutoff = time.time() - hours * 3600
        points = [
            (s.timestamp, s.used_percent)
            for s in self.read_all()
            if s.provider == provider and s.window == window and s.timestamp >= cutoff
        ]
        points.sort(key=lambda item: item[0])
        return points
