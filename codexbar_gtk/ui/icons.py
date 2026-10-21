"""Tray icon assets.

The tray icon is a small usage meter. Because the system tray renders a themed
icon by name, we generate one SVG per usage level and swap the icon name as the
quota moves.
"""

from __future__ import annotations

import os
import shutil
import subprocess

ICON_DIR = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
ICON_PREFIX = "codexbar-gtk"

_LEVELS = 10

_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <defs>
    <clipPath id="cb-rounded">
      <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5"/>
    </clipPath>
  </defs>
  <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5" fill="#ffffff" fill-opacity="0.16"/>
  <g clip-path="url(#cb-rounded)">
    <rect x="2.5" y="6.5" width="{w:.2f}" height="11" fill="{color}"/>
  </g>
  <rect x="2.5" y="6.5" width="19" height="11" rx="4.5" ry="4.5" fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.4"/>
</svg>
"""


def _level_color(level: int, accent: str) -> str:
    if level >= 9:
        return "#e05a5a"
    if level >= 7:
        return "#e0a030"
    return accent


def _ensure_theme_index() -> None:
    """Make sure the user hicolor theme is a valid icon theme.

    Without an ``index.theme`` file, icon loaders (KDE's in particular) ignore
    the directory entirely, so the tray icon would never be found.
    """
    theme_dir = os.path.expanduser("~/.local/share/icons/hicolor")
    index = os.path.join(theme_dir, "index.theme")
    if os.path.exists(index):
        return
    for candidate in (
        "/usr/share/icons/hicolor/index.theme",
        "/usr/share/pixmaps/hicolor/index.theme",
    ):
        if not os.path.exists(candidate):
            continue
        try:
            os.makedirs(theme_dir, exist_ok=True)
            with open(candidate, "r", encoding="utf-8") as source:
                content = source.read()
            with open(index, "w", encoding="utf-8") as target:
                target.write(content)
            return
        except OSError:
            continue
    try:
        os.makedirs(theme_dir, exist_ok=True)
        with open(index, "w", encoding="utf-8") as target:
            target.write(
                "[Icon Theme]\nName=Hicolor\nComment=Fallback icon theme\n"
                "Directories=scalable/apps,symbolic/apps\n"
                "\n[scalable/apps]\nSize=48\nMinSize=8\nMaxSize=512\n"
                "Context=Applications\nType=Scalable\n\n"
                "[symbolic/apps]\nSize=16\nMinSize=8\nMaxSize=512\n"
                "Context=Applications\nType=Scalable\n"
            )
    except OSError:
        pass


def _refresh_icon_cache() -> None:
    """Rebuild the hicolor cache so the tray host picks up new icons."""
    theme_dir = os.path.expanduser("~/.local/share/icons/hicolor")
    if not os.path.isdir(theme_dir):
        return
    for binary in ("gtk4-update-icon-cache", "gtk-update-icon-cache"):
        path = shutil.which(binary)
        if not path:
            continue
        try:
            subprocess.run(
                [path, "-f", "-t", theme_dir],
                check=False,
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return


def write_icons(accent: str = "#10A37F") -> dict[int, str]:
    """Write the per-level SVG icons and return ``{level: icon_name}``."""
    _ensure_theme_index()
    os.makedirs(ICON_DIR, exist_ok=True)
    mapping: dict[int, str] = {}
    changed = False
    for level in range(_LEVELS):
        fraction = level / float(_LEVELS - 1)
        width = max(1.6, 19.0 * fraction)
        color = _level_color(level, accent)
        name = f"{ICON_PREFIX}-{level}"
        path = os.path.join(ICON_DIR, f"{name}.svg")
        content = _TEMPLATE.format(w=width, color=color)
        try:
            existing = None
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    existing = handle.read()
            if existing != content:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                changed = True
        except OSError:
            continue
        mapping[level] = name
    if changed:
        _refresh_icon_cache()
    return mapping


def app_icon_name() -> str:
    return ICON_PREFIX


def render_meter_pixmap(level: int, accent: str = "#10A37F", size: int = 32):
    """Render the meter icon to raw ARGB32 pixels.

    Some system tray hosts do not resolve themed icons reliably, so the
    StatusNotifierItem also carries the pixels directly.

    Returns ``(width, height, bytes)`` in the network byte order the spec
    requires (ARGB32).
    """
    try:
        import cairo
    except Exception:
        return None

    try:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    except Exception:
        return None

    cr = cairo.Context(surface)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)

    margin = size * 0.11
    bar_height = size * 0.44
    width = size - 2 * margin
    radius = bar_height / 2
    top = (size - bar_height) / 2

    def rounded_rect(x: float, y: float, w: float, h: float) -> None:
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -1.5707963, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, 1.5707963)
        cr.arc(x + radius, y + h - radius, radius, 1.5707963, 3.1415926)
        cr.arc(x + radius, y + radius, radius, 3.1415926, 4.7123890)
        cr.close_path()

    cr.set_source_rgba(1, 1, 1, 0.16)
    rounded_rect(margin, top, width, bar_height)
    cr.fill()

    fraction = max(0.0, min(1.0, level / float(_LEVELS - 1)))
    filled = max(bar_height * 0.35, width * fraction)
    r, g, b = _hex_to_rgb(_level_color(level, accent))
    cr.set_source_rgba(r, g, b, 1.0)
    rounded_rect(margin, top, min(filled, width), bar_height)
    cr.fill()

    cr.set_source_rgba(1, 1, 1, 0.85)
    cr.set_line_width(max(1.0, size * 0.055))
    rounded_rect(margin, top, width, bar_height)
    cr.stroke()

    surface.flush()
    stride = surface.get_stride()
    raw = bytes(surface.get_data())
    out = bytearray()
    for y in range(size):
        row = raw[y * stride : y * stride + size * 4]
        for x in range(size):
            b, g, r, a = row[x * 4 : x * 4 + 4]
            out += bytes((a, r, g, b))
    return size, size, bytes(out)


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    text = value.strip().lstrip("#")
    if len(text) == 6:
        try:
            return (
                int(text[0:2], 16) / 255.0,
                int(text[2:4], 16) / 255.0,
                int(text[4:6], 16) / 255.0,
            )
        except ValueError:
            pass
    return (0.39, 0.40, 0.96)


def ensure_app_icon(accent: str = "#10A37F") -> str:
    """Write the application icon used by the launcher entry."""
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, f"{ICON_PREFIX}.svg")
    content = _TEMPLATE.format(w=13.0, color=accent)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError:
        pass
    return ICON_PREFIX
