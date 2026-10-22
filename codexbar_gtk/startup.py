"""Small headless helpers for desktop-session startup."""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_for_display(
    check_display: Callable[[], bool],
    timeout: float = 30.0,
    interval: float = 0.25,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll until the graphical display is ready or the timeout expires.

    The status-tray service is intentionally ordered before the panel host, so
    at login the display server can be available slightly later than systemd.
    """
    deadline = monotonic() + max(0.0, timeout)
    while True:
        try:
            if check_display():
                return True
        except RuntimeError:
            # Display backends may transiently fail while the session starts.
            pass
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(max(0.0, interval), remaining))
