"""Pick symbolic icon names that exist in the running icon theme.

libadwaita apps normally assume the Adwaita icon theme is installed.  On KDE
(and on minimal desktops) Breeze or another theme is used instead and several
Adwaita names are missing; GTK then draws the red ``image-missing`` glyph.
:func:`themed_icon` walks a list of acceptable names and returns the first one
the current theme actually provides.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

_CACHE: dict[tuple[str, ...], str] = {}

# Section icons, used by the view switcher, stat tiles and preferences pages.
USAGE = ("view-grid-symbolic", "view-list-symbolic", "utilities-system-monitor-symbolic")
SESSIONS = ("utilities-terminal-symbolic", "view-list-symbolic", "text-x-generic-symbolic")
SPEND = ("document-open-recent-symbolic", "wallet-open-symbolic", "emblem-money-symbolic")
PROVIDERS = ("network-server-symbolic", "network-workgroup-symbolic", "view-list-symbolic")
HIGHEST = ("speedometer-symbolic", "view-statistics-symbolic", "utilities-system-monitor-symbolic")
CREDITS = ("wallet-open-symbolic", "emblem-money-symbolic", "document-open-recent-symbolic")
DISPLAY = ("video-display-symbolic", "applications-graphics-symbolic", "preferences-desktop-symbolic")
NOTIFICATIONS = (
    "preferences-system-notifications-symbolic",
    "preferences-desktop-notification-symbolic",
    "preferences-system-symbolic",
)
HOOKS = ("application-x-executable-symbolic", "utilities-terminal-symbolic")
PLUGINS = ("application-x-addon-symbolic", "application-x-executable-symbolic")
ADVANCED = ("applications-graphics-symbolic", "preferences-system-symbolic")
ABOUT = ("help-about-symbolic", "preferences-system-symbolic", "applications-graphics-symbolic")
REFRESH = ("view-refresh-symbolic", "view-refresh")
MENU_BAR = ("view-continuous-symbolic", "view-grid-symbolic")


def themed_icon(*candidates: str, fallback: str = "image-missing-symbolic") -> str:
    """Return the first candidate available in the current icon theme."""
    if not candidates:
        return fallback
    key = candidates
    if key in _CACHE:
        return _CACHE[key]

    theme = None
    try:
        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
    except Exception:
        theme = None

    chosen = fallback
    for name in candidates:
        if theme is None or theme.has_icon(name):
            chosen = name
            break
    _CACHE[key] = chosen
    return chosen
