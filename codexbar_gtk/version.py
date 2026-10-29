"""Version metadata, mirroring the macOS bundle's version pair.

The macOS app shows ``CFBundleShortVersionString`` (``MARKETING_VERSION``) and
``CFBundleVersion`` (``CURRENT_PROJECT_VERSION``) as ``"0.81.0 (123)"``.  The GTK
front-end uses the same scheme: :data:`SHORT_VERSION` is the upstream CodexBar
release this client is feature-compatible with, and :data:`BUILD` increments
with every published build of the Linux front-end.
"""

from __future__ import annotations

SHORT_VERSION = "0.81.0"
BUILD = 18


def display_string() -> str:
    """Return the macOS-style ``"<version> (<build>)"`` string."""
    return f"{SHORT_VERSION} ({BUILD})"
