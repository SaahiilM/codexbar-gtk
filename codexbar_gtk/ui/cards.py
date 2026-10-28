"""Reusable widgets: provider cards, quota meters and stat tiles.

The look is built on libadwaita's own style classes (``.card``, ``.title``,
``.heading``, ``.caption``, ``.numeric``) so the app feels native on GNOME and
still looks right on KDE Plasma.
"""

from __future__ import annotations

from datetime import datetime, timezone

import cairo  # registers the cairo foreign-struct converter
from gi.repository import GdkPixbuf, GLib, Gtk

from .. import currency
from ..charts import sparkline_coordinates
from ..data import ProviderUsage, RateWindow
from ..format import (
    format_countdown,
    format_credits,
    format_currency,
    format_pace,
    format_percent,
    format_remaining,
    format_reset,
    format_reset_credits,
    format_updated,
    project_usage_at_reset,
    workday_progress_percent,
)
from ..pace import format_monthly_cost_target, format_window_target
from ..provider_icons import provider_icon_path
from . import cairo_support  # enables cairo drawing
from .util import iter_children


def _severity_color(severity: str, accent: str) -> str:
    if severity == "critical":
        return "#e05252"
    if severity == "warning":
        return "#e0a030"
    return accent


def _status_color(level: str | None) -> str | None:
    return {
        "minor": "#e0a030",
        "major": "#e05252",
        "critical": "#e05252",
        "maintenance": "#e0a030",
        "unknown": "#9a9a9a",
    }.get((level or "").lower())


def _parse_color(value: str) -> tuple[float, float, float, float]:
    text = value.strip().lstrip("#")
    if len(text) == 6:
        try:
            return (
                int(text[0:2], 16) / 255.0,
                int(text[2:4], 16) / 255.0,
                int(text[4:6], 16) / 255.0,
                1.0,
            )
        except ValueError:
            pass
    return (0.39, 0.40, 0.96, 1.0)


def severity_for(used_percent: float, thresholds: list[float] | None) -> str:
    """Map a used percentage onto ok / warning / critical."""
    thresholds = thresholds or [80, 95]
    ordered = sorted(thresholds, reverse=True)
    for index, threshold in enumerate(ordered):
        if used_percent >= threshold:
            return "critical" if index == 0 else "warning"
    return "ok"


class StatusDot(Gtk.DrawingArea):
    """A small coloured circle showing the provider brand or incident state."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(10, 10)
        self.set_valign(Gtk.Align.CENTER)
        self.color = "#6366F1"
        self.filled = True
        self.set_draw_func(self._draw)

    def set_color(self, color: str, filled: bool = True) -> None:
        self.color = color
        self.filled = filled
        self.queue_draw()

    def _draw(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO:
            return
        radius = min(width, height) / 2
        if not self.filled:
            cr.set_source_rgba(*_parse_color(self.color))
            cr.set_line_width(1.5)
            cr.arc(width / 2, height / 2, max(radius - 1, 0.5), 0, 6.2831853)
            cr.stroke()
            return
        cr.set_source_rgba(*_parse_color(self.color))
        cr.arc(width / 2, height / 2, radius, 0, 6.2831853)
        cr.fill()


class ProviderAvatar(Gtk.Overlay):
    """A brand-tinted badge with upstream provider artwork or an initial fallback."""

    def __init__(
        self,
        name: str,
        color: str,
        provider_id: str | None = None,
        size: int = 34,
    ) -> None:
        super().__init__()
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.name = name
        self.color = color
        canvas = Gtk.DrawingArea()
        canvas.set_content_width(size)
        canvas.set_content_height(size)
        canvas.set_draw_func(self._draw_background)
        self.set_child(canvas)

        initial = Gtk.Label(label=(name or "?")[0].upper())
        initial.add_css_class("cb-provider-avatar-letter")
        initial.set_halign(Gtk.Align.CENTER)
        initial.set_valign(Gtk.Align.CENTER)
        self.add_overlay(initial)

        logo_path = provider_icon_path(provider_id or "")
        if logo_path is not None:
            try:
                icon_size = max(20, size - 4)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                    str(logo_path), icon_size, icon_size
                )
                if logo_path.name.startswith("ProviderIcon-"):
                    pixbuf = self._tint_logo(pixbuf, color)
                logo = Gtk.Image.new_from_pixbuf(pixbuf)
                logo.set_size_request(icon_size, icon_size)
                logo.set_halign(Gtk.Align.CENTER)
                logo.set_valign(Gtk.Align.CENTER)
                self.add_overlay(logo)
                initial.set_visible(False)
            except (GLib.Error, TypeError, ValueError):
                # Missing or unsupported artwork must not hide the usable fallback.
                pass

    @staticmethod
    def _tint_logo(pixbuf: GdkPixbuf.Pixbuf, color: str) -> GdkPixbuf.Pixbuf:
        """Render an upstream monochrome logo as a single-color alpha mask."""
        if not pixbuf.get_has_alpha():
            pixbuf = pixbuf.add_alpha(False, 0, 0, 0)

        red, green, blue, _alpha = _parse_color(color)
        red, green, blue = (round(channel * 255) for channel in (red, green, blue))
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        rowstride = pixbuf.get_rowstride()
        channels = pixbuf.get_n_channels()
        source = pixbuf.get_pixels()
        tinted = bytearray(source)
        for y in range(height):
            row = y * rowstride
            for x in range(width):
                offset = row + x * channels
                tinted[offset] = red
                tinted[offset + 1] = green
                tinted[offset + 2] = blue

        return GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(tinted)),
            pixbuf.get_colorspace(),
            True,
            pixbuf.get_bits_per_sample(),
            width,
            height,
            rowstride,
        )

    def _draw_background(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO:
            return
        r, g, b, _a = _parse_color(self.color)
        cr.set_source_rgba(r, g, b, 0.22)
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 6.2831853)
        cr.fill()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.set_line_width(1.4)
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 6.2831853)
        cr.stroke()


class MeterBar(Gtk.DrawingArea):
    """A rounded quota meter drawn with Cairo.

    Using a drawing area instead of ``Gtk.ProgressBar`` gives us per-provider
    accent colours, rounded caps and warning markers. When PyGObject cannot
    hand out Cairo contexts the widget falls back to a plain progress bar.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 12)
        self.set_valign(Gtk.Align.CENTER)
        self.fraction = 0.0
        self.color = "#6366F1"
        self.markers: list[float] = []
        self.ticks: list[float] = []
        self.tick_color = (1, 1, 1, 0.35)
        if cairo_support.HAS_CAIRO:
            self.set_draw_func(self._draw)
        else:
            self._fallback = Gtk.ProgressBar()
            self._fallback.set_show_text(False)
            self._fallback.set_valign(Gtk.Align.CENTER)
            self._fallback.set_hexpand(True)
            self.add_css_class("cb-meter")
            self._fallback.set_parent(self)

    def set_meter(
        self,
        fraction: float,
        color: str,
        markers: list[float] | None = None,
        ticks: list[float] | None = None,
        tick_appearance: str = "subtle",
    ) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.color = color
        self.markers = markers or []
        self.ticks = ticks or []
        if tick_appearance == "hidden":
            self.ticks = []
        elif tick_appearance == "highContrast":
            self.tick_color = (1, 1, 1, 0.85)
        else:
            self.tick_color = (1, 1, 1, 0.35)
        if not cairo_support.HAS_CAIRO:
            self._fallback.set_fraction(self.fraction)
        self.queue_draw()

    def _draw(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO or width <= 0 or height <= 0:
            return

        radius = height / 2

        cr.set_source_rgba(1, 1, 1, 0.12)
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.fill()

        filled = width * self.fraction
        if filled > 0.5:
            cr.set_source_rgba(*_parse_color(self.color))
            _rounded_rect(cr, 0, 0, max(filled, height), height, radius)
            cr.fill()

        for marker in self.markers:
            x = width * (marker / 100.0)
            if 0 < x < width - 1:
                cr.set_source_rgba(1, 1, 1, 0.45)
                cr.rectangle(x, 1, 1, height - 2)
                cr.fill()

        for tick in self.ticks:
            x = width * (tick / 100.0)
            if 0 < x < width - 1:
                cr.set_source_rgba(*self.tick_color)
                cr.rectangle(x, 0, 1, height)
                cr.fill()


def _rounded_rect(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, height / 2, width / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -1.5707963, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5707963)
    cr.arc(x + radius, y + height - radius, radius, 1.5707963, 3.1415926)
    cr.arc(x + radius, y + radius, radius, 3.1415926, 4.7123890)
    cr.close_path()


class Sparkline(Gtk.DrawingArea):
    """A small trend line for the recorded usage of a quota window."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 26)
        self.set_valign(Gtk.Align.CENTER)
        self.points: list[tuple[float, float]] = []
        self.color = "#6366F1"
        self.set_draw_func(self._draw)

    def set_points(self, points: list[tuple[float, float]], color: str) -> None:
        self.points = points
        self.color = color
        self.set_visible(len(points) >= 3)
        self.queue_draw()

    def _draw(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO or len(self.points) < 2 or width <= 0:
            return
        coords = sparkline_coordinates(self.points, width, height)
        if len(coords) < 2:
            return

        r, g, b, _a = _parse_color(self.color)

        # Filled area under the line.
        cr.set_source_rgba(r, g, b, 0.16)
        cr.move_to(coords[0][0], height)
        for x, y in coords:
            cr.line_to(x, y)
        cr.line_to(coords[-1][0], height)
        cr.close_path()
        cr.fill()

        # The line itself.
        cr.set_source_rgba(r, g, b, 0.85)
        cr.set_line_width(1.6)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*coords[0])
        for point in coords[1:]:
            cr.line_to(*point)
        cr.stroke()

        # Current value marker.
        last_x, last_y = coords[-1]
        cr.set_source_rgba(r, g, b, 1.0)
        cr.arc(last_x, last_y, 2.4, 0, 6.2831853)
        cr.fill()


class DetailChartView(Gtk.Box):
    """Bar or line chart for a provider detail section (usage breakdown etc.)."""

    def __init__(self, title: str | None = None, unit: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("cb-chart-block")
        if title:
            heading = Gtk.Label(label=title)
            heading.add_css_class("cb-section-label")
            heading.set_halign(Gtk.Align.START)
            self.append(heading)
        self.bars = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.bars.set_valign(Gtk.Align.END)
        self.bars.set_hexpand(True)
        self.append(self.bars)
        self.unit = unit

    def set_points(self, points: list[tuple[str, float]], color: str = "#10A37F") -> None:
        for child in list(iter_children(self.bars)):
            self.bars.remove(child)
        if not points:
            self.set_visible(False)
            return
        self.set_visible(True)
        peak = max((value for _, value in points), default=0.0) or 1.0
        for label, value in points[-24:]:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            column.set_valign(Gtk.Align.END)
            column.set_hexpand(True)

            bar = Gtk.Box()
            bar.add_css_class("cb-chart-bar")
            bar.set_size_request(-1, max(4, int(90 * (value / peak))))
            bar.set_valign(Gtk.Align.END)
            column.append(bar)

            caption = Gtk.Label(label=label)
            caption.add_css_class("cb-chart-label")
            caption.set_halign(Gtk.Align.CENTER)
            caption.set_ellipsize(3)
            column.append(caption)
            self.bars.append(column)


class Chip(Gtk.Box):
    """A small rounded label, e.g. a reset countdown or a pace note."""

    def __init__(self, text: str = "", icon: str | None = None, style: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("cb-chip")
        if style:
            self.add_css_class(style)
        self.icon = Gtk.Image()
        self.icon.set_from_icon_name(icon) if icon else None
        self.icon.set_visible(bool(icon))
        self.append(self.icon)
        self.label = Gtk.Label(label=text)
        self.label.add_css_class("cb-chip-label")
        self.append(self.label)

    def set_text(self, text: str) -> None:
        self.label.set_text(text)


class MeterRow(Gtk.Box):
    """One quota window: title, percentage, bar, reset countdown and pace."""

    def __init__(
        self,
        window: RateWindow,
        *,
        show_used: bool = True,
        reset_style: str = "countdown",
        show_pace: bool = True,
        thresholds: list[float] | None = None,
        accent_color: str = "#6366F1",
        workday_ticks: list[float] | None = None,
        tick_appearance: str = "subtle",
        compact: bool = False,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5 if compact else 6)
        self.window = window
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.compact = compact
        self.thresholds = thresholds or []
        self.accent_color = accent_color
        self.workday_ticks = workday_ticks or []
        self.tick_appearance = tick_appearance

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.title_label = Gtk.Label(label=window.title)
        self.title_label.add_css_class("cb-metric-title")
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_hexpand(True)
        self.title_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        header.append(self.title_label)

        self.percent_label = Gtk.Label(label="")
        self.percent_label.add_css_class("cb-metric-percent")
        header.append(self.percent_label)
        self.append(header)

        self.progress = MeterBar()
        self.append(self.progress)

        trend_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.sparkline = Sparkline()
        self.sparkline.set_visible(False)
        self.sparkline.set_hexpand(True)
        trend_row.append(self.sparkline)
        self.trend_label = Gtk.Label(label="last 24h")
        self.trend_label.add_css_class("cb-trend-label")
        self.trend_label.set_valign(Gtk.Align.CENTER)
        trend_row.append(self.trend_label)
        trend_row.set_visible(not compact)
        self.append(trend_row)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.reset_chip = Chip(icon="view-refresh-symbolic")
        meta.append(self.reset_chip)

        self.pace_chip = Chip()
        self.pace_chip.set_visible(False)
        meta.append(self.pace_chip)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        meta.append(spacer)
        self.append(meta)

        # Monthly allowances also answer "how much can I use per day".
        self.target_label = Gtk.Label(label="")
        self.target_label.add_css_class("cb-daily-target")
        self.target_label.set_xalign(0)
        self.target_label.set_visible(False)
        self.append(self.target_label)

    def update(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        window = self.window
        used = window.used_percent

        if self.show_used:
            self.percent_label.set_text(format_percent(used))
        else:
            self.percent_label.set_text(format_remaining(used))

        severity = severity_for(used, self.thresholds)
        self.progress.set_meter(
            min(1.0, max(0.0, used / 100.0)),
            _severity_color(severity, self.accent_color),
            self.thresholds,
            self.workday_ticks,
        )

        reset_text = format_reset(window.resets_at, self.reset_style, now)
        if reset_text is None:
            reset_text = window.reset_description or ""
        self.reset_chip.set_text(reset_text)
        self.reset_chip.set_visible(bool(reset_text))

    def set_trend(self, points: list[tuple[float, float]], color: str) -> None:
        self.sparkline.set_points(points, color)
        self.trend_label.set_visible(len(points) >= 3)

    def set_target(self, target_text: str | None) -> None:
        self.target_label.set_text(target_text or "")
        self.target_label.set_visible(bool(target_text))

    def set_pace(self, pace_text: str | None, severity: str = "ok") -> None:
        if not pace_text or not self.show_pace:
            self.pace_chip.set_visible(False)
            return
        self.pace_chip.set_text(pace_text)
        self.pace_chip.remove_css_class("cb-chip-warn")
        self.pace_chip.remove_css_class("cb-chip-crit")
        if severity == "critical":
            self.pace_chip.add_css_class("cb-chip-crit")
        elif severity == "warning":
            self.pace_chip.add_css_class("cb-chip-warn")
        self.pace_chip.set_visible(True)


class ProviderCard(Gtk.Box):
    """The macOS-style provider card: header, quota meters, credits and cost."""

    def __init__(
        self,
        provider: ProviderUsage,
        *,
        show_used: bool = True,
        reset_style: str = "countdown",
        show_pace: bool = True,
        thresholds: list[float] | None = None,
        show_identity: bool = True,
        compact: bool = False,
        history=None,
        work_days: int = 5,
        tick_appearance: str = "subtle",
        burndown: bool = True,
        preferred_currency: str = "auto",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.provider = provider
        self.preferred_currency = (preferred_currency or "auto").upper()
        self.history = history
        self.work_days = work_days
        self.tick_appearance = tick_appearance
        self.burndown = burndown
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.thresholds = thresholds or []
        self.show_identity = show_identity
        self.compact = compact
        self.add_css_class("cb-card")
        if compact:
            self.add_css_class("cb-card-compact")

        self.header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8 if compact else 12
        )
        self.add_css_class("cb-card-header")

        self.avatar = ProviderAvatar(
            provider.display_name,
            provider.accent_color,
            # Keep the full dashboard's established avatar treatment unchanged;
            # provider artwork is part of the compact tray card refinement.
            provider_id=provider.provider_id if compact else None,
            size=30 if compact else 34,
        )
        self.header.append(self.avatar)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_box.set_hexpand(True)
        title_box.set_valign(Gtk.Align.CENTER)
        self.name_label = Gtk.Label(label=provider.display_name)
        self.name_label.add_css_class("cb-provider-name")
        self.name_label.set_halign(Gtk.Align.START)
        self.name_label.set_ellipsize(3)
        title_box.append(self.name_label)

        self.subtitle_label = Gtk.Label(label="")
        self.subtitle_label.add_css_class("cb-provider-subtitle")
        self.subtitle_label.set_halign(Gtk.Align.START)
        self.subtitle_label.set_ellipsize(3)
        title_box.append(self.subtitle_label)
        self.header.append(title_box)

        self.badge_label = Gtk.Label(label="")
        self.badge_label.add_css_class("cb-plan-badge")
        self.badge_label.set_valign(Gtk.Align.CENTER)
        self.header.append(self.badge_label)

        self.account_label = Gtk.Label(label="")
        self.account_label.add_css_class("cb-plan-badge")
        self.account_label.set_valign(Gtk.Align.CENTER)
        self.account_label.set_visible(False)
        self.header.append(self.account_label)
        self.append(self.header)

        self.meters: list[MeterRow] = []
        self.meters_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=11 if compact else 14
        )
        self.meters_box.set_margin_top(10 if compact else 14)
        self.append(self.meters_box)

        # The projection chip lives in its own row so the details rebuild
        # below cannot wipe it.
        self.burndown_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.burndown_chip = Chip(icon="utilities-system-monitor-symbolic")
        self.burndown_chip.set_visible(False)
        self.burndown_box.append(self.burndown_chip)
        self.append(self.burndown_box)

        self.charts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(self.charts_box)

        self.extra_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.extra_box)

        self.error_label = Gtk.Label(label="")
        self.error_label.add_css_class("cb-error")
        self.error_label.set_wrap(True)
        self.error_label.set_xalign(0)
        self.error_label.set_visible(False)
        self.append(self.error_label)

        self._build_meters()
        self.refresh()

    # -- construction -----------------------------------------------------

    def _build_meters(self) -> None:
        for child in list(iter_children(self.meters_box)):
            self.meters_box.remove(child)
        self.meters = []
        for window in self.provider.windows:
            row = MeterRow(
                window,
                show_used=self.show_used,
                reset_style=self.reset_style,
                show_pace=self.show_pace,
                thresholds=self._thresholds_for(window),
                accent_color=self.provider.accent_color,
                workday_ticks=self._workday_ticks_for(window),
                tick_appearance=self.tick_appearance,
                compact=self.compact,
            )
            self.meters.append(row)
            self.meters_box.append(row)

    def _thresholds_for(self, window: RateWindow) -> list[float]:
        return self.thresholds

    def _workday_ticks_for(self, window: RateWindow) -> list[float]:
        """Weekly windows show a tick for the working-day progress."""
        if window.key != "secondary" or self.work_days <= 0:
            return []
        percent = workday_progress_percent(window.resets_at, work_days=self.work_days)
        if percent is None:
            return []
        return [percent]

    # -- updates ----------------------------------------------------------

    def refresh(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        provider = self.provider

        subtitle_parts = []
        if self.show_identity:
            if provider.plan:
                subtitle_parts.append(provider.plan)
            if provider.account_email:
                subtitle_parts.append(provider.account_email)
        if not subtitle_parts and provider.source:
            subtitle_parts.append(provider.source)
        updated = format_updated(provider.updated_at, now)
        if updated and not self.compact:
            subtitle_parts.append(f"updated {updated}")
        self.subtitle_label.set_text(" · ".join(subtitle_parts))
        tooltip_parts = list(subtitle_parts)
        if updated and self.compact:
            tooltip_parts.append(f"updated {updated}")
        self.subtitle_label.set_tooltip_text(" · ".join(tooltip_parts) or None)

        badge = ""
        badge_help = ""
        if provider.status_level:
            badge = str(provider.status_level).replace("_", " ").title()
        elif provider.reset_credits:
            presentation = format_reset_credits(
                [credit["expires_at"] for credit in provider.reset_credits],
                style=str(self.reset_style or "countdown"),
                now=now,
            )
            if presentation is not None:
                count_text, compact, help_items = presentation
                badge = f"{count_text} · {compact}" if compact else count_text
                header = provider.reset_credits[0].get("title") or "Rate limit resets"
                badge_help = "\n".join([header, ""] + [
                    f"{index + 1}. {item}" for index, item in enumerate(help_items)
                ])
        elif provider.reset_credits_available:
            badge = f"{provider.reset_credits_available} resets"
        self.badge_label.set_text(badge)
        self.badge_label.set_tooltip_text(badge_help or None)
        if self.compact and provider.reset_credits:
            self.badge_label.set_text(f"{len(provider.reset_credits)} resets")
        self.badge_label.set_visible(bool(badge))

        accounts = provider.accounts
        if len(accounts) > 1:
            self.account_label.set_text(f"{len(accounts)} accounts")
            self.account_label.set_tooltip_text("\n".join(accounts))
            self.account_label.set_visible(not self.compact)
        else:
            self.account_label.set_visible(False)

        for row in self.meters:
            row.update(now)
            if self.history is not None:
                row.set_trend(
                    self.history.series(provider.provider_id, row.window.key, hours=24.0),
                    provider.accent_color,
                )
            pace = provider.pace_for(row.window)
            if pace is not None:
                severity = "ok"
                if pace.in_deficit:
                    severity = "warning"
                if pace.stage == "farAhead":
                    severity = "critical"
                row.set_pace(format_pace(pace), severity)
            else:
                row.set_pace(None)
            row.set_target(
                format_window_target(row.window, self.preferred_currency, now)
                if self.show_pace and not self.compact
                else None
            )

        self._rebuild_charts()
        self._update_burndown(now)
        self._rebuild_extra(now)

        if provider.error:
            self.error_label.set_text(provider.error)
            self.error_label.set_visible(True)
        else:
            self.error_label.set_visible(False)

    def _rebuild_charts(self) -> None:
        """Render the charts the CLI attached to the provider details."""
        for child in list(iter_children(self.charts_box)):
            self.charts_box.remove(child)

        if self.compact:
            return

        for section in self.provider.details:
            if section.chart is None or not section.chart.points:
                continue
            view = DetailChartView(section.chart.title, section.chart.unit)
            view.set_points(section.chart.points, self.provider.accent_color)
            self.charts_box.append(view)

        if self.provider.credit_events:
            view = DetailChartView("Credits used")
            view.set_points(
                [(event.date[5:] if len(event.date) >= 10 else event.date, event.used)
                 for event in self.provider.credit_events[-24:]],
                self.provider.accent_color,
            )
            self.charts_box.append(view)

    def _update_burndown(self, now: datetime) -> None:
        """Project the usage at reset time from the recorded history."""
        if self.compact or not self.burndown or self.history is None:
            self.burndown_chip.set_visible(False)
            return
        window = self.provider.windows[0] if self.provider.windows else None
        if window is None or window.resets_at is None:
            self.burndown_chip.set_visible(False)
            return
        samples = self.history.series(self.provider.provider_id, window.key, hours=24.0)
        projected = project_usage_at_reset(window.used_percent, samples, window.resets_at, now)
        if projected is None:
            self.burndown_chip.set_visible(False)
            return
        if projected >= 95:
            text = f"projected {projected:.0f}% at reset — will run out"
        else:
            text = f"projected {projected:.0f}% at reset"
        self.burndown_chip.set_text(text)
        self.burndown_chip.set_visible(True)

    def _money(self, amount: float, code: str) -> str:
        """Format a provider cost in the preferred display currency."""
        source = (code or "USD").upper()
        if (
            self.preferred_currency in ("", "AUTO")
            or self.preferred_currency == source
            or not currency.requires_live_rates(self.preferred_currency)
        ):
            return format_currency(amount, code)
        converted = currency.convert(amount, source, self.preferred_currency)
        if converted is None:
            return format_currency(amount, code)
        return format_currency(converted, self.preferred_currency)

    def _rebuild_extra(self, now: datetime) -> None:
        for child in list(iter_children(self.extra_box)):
            self.extra_box.remove(child)

        provider = self.provider
        rows: list[tuple[str, str, str]] = []

        if provider.credits_remaining is not None:
            rows.append(("Credits", f"{format_credits(provider.credits_remaining)} remaining", ""))

        cost = provider.cost
        cost_target = None
        if cost is not None and (cost.used or cost.limit or cost.balance is not None):
            if cost.has_limit:
                text = (
                    f"{self._money(cost.used, cost.currency)} of "
                    f"{self._money(cost.limit, cost.currency)}"
                )
                rows.append(("Spend", text, cost.period or ""))
                if cost.balance is not None and provider.credits_remaining is None:
                    rows.append(("Balance", self._money(cost.balance, cost.currency), ""))
            elif cost.balance is not None:
                text = f"{self._money(cost.balance, cost.currency)} balance"
                rows.append(("Spend", text, cost.period or ""))
            else:
                text = f"{self._money(cost.used, cost.currency)} spent"
                rows.append(("Spend", text, cost.period or ""))

            cost_target = format_monthly_cost_target(
                cost, self.preferred_currency, now
            )

        if not self.compact:
            for section in provider.details[:3]:
                for row in section.rows[:4]:
                    value = row.value
                    if row.secondary_value:
                        value = f"{value} · {row.secondary_value}"
                    rows.append((row.label, value, ""))

        if not rows:
            return

        divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        divider.set_margin_top(12)
        divider.set_margin_bottom(10)
        self.extra_box.append(divider)

        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for label, value, hint in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            key = Gtk.Label(label=label)
            key.add_css_class("cb-kv-key")
            key.set_halign(Gtk.Align.START)
            key.set_hexpand(True)
            row.append(key)
            value_label = Gtk.Label(label=value)
            value_label.add_css_class("cb-kv-value")
            value_label.set_halign(Gtk.Align.END)
            value_label.set_ellipsize(3)
            row.append(value_label)
            if hint and not self.compact:
                hint_label = Gtk.Label(label=hint)
                hint_label.add_css_class("cb-kv-key")
                row.append(hint_label)
            grid.append(row)
        self.extra_box.append(grid)

        if cost_target and not self.compact:
            target_label = Gtk.Label(label=cost_target)
            target_label.add_css_class("cb-daily-target")
            target_label.set_xalign(0)
            target_label.set_wrap(True)
            self.extra_box.append(target_label)

    # -- helpers ----------------------------------------------------------

    def summary_text(self) -> str:
        """One line summary used for the tray tooltip."""
        provider = self.provider
        if provider.error:
            return f"{provider.display_name}: {provider.error}"
        parts = [provider.display_name]
        if provider.plan:
            parts.append(provider.plan)
        for row in self.meters:
            window = row.window
            used = (
                f"{window.used_percent:.0f}%"
                if self.show_used
                else f"{window.remaining_percent:.0f}% left"
            )
            countdown = format_countdown(window.resets_at)
            text = f"{window.title} {used}"
            if countdown:
                text += f" (resets in {countdown})"
            parts.append(text)
        return " — ".join(parts)


class StatTile(Gtk.Box):
    """A big number with a caption, used on the dashboard."""

    def __init__(self, label: str, value: str = "—", caption: str = "", icon: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.add_css_class("cb-tile")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if icon:
            icon_widget = Gtk.Image.new_from_icon_name(icon)
            icon_widget.add_css_class("cb-tile-icon")
            icon_widget.set_valign(Gtk.Align.CENTER)
            top.append(icon_widget)
        self.label_widget = Gtk.Label(label=label)
        self.label_widget.add_css_class("cb-tile-label")
        self.label_widget.set_halign(Gtk.Align.START)
        self.label_widget.set_hexpand(True)
        self.label_widget.set_valign(Gtk.Align.CENTER)
        top.append(self.label_widget)
        self.append(top)

        self.value_label = Gtk.Label(label=value)
        self.value_label.add_css_class("cb-tile-value")
        self.value_label.set_halign(Gtk.Align.START)
        self.append(self.value_label)

        self.caption_widget = Gtk.Label(label=caption)
        self.caption_widget.add_css_class("cb-tile-caption")
        self.caption_widget.set_halign(Gtk.Align.START)
        self.caption_widget.set_visible(bool(caption))
        self.append(self.caption_widget)

    def set_value(self, value: str, caption: str | None = None) -> None:
        self.value_label.set_text(value)
        if caption is not None:
            self.caption_widget.set_text(caption)
            self.caption_widget.set_visible(bool(caption))


class MiniBarChart(Gtk.DrawingArea):
    """Compact bar chart for daily spend.

    Drawing with Cairo keeps thirty day columns from forcing the page wider
    than its 720 px content column; value labels appear only where they fit and
    date labels are thinned out instead of colliding.
    """

    HEIGHT = 168
    TOP = 22
    BOTTOM = 20

    def __init__(self) -> None:
        super().__init__()
        self.add_css_class("cb-chart")
        self.set_content_height(self.HEIGHT)
        self.set_hexpand(True)
        self.set_has_tooltip(True)
        self.entries: list[tuple[str, float | None]] = []
        self.currency = "USD"
        self._hover_index: int | None = None
        self.set_draw_func(self._draw)
        self.connect("query-tooltip", self._on_query_tooltip)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_entries(
        self, entries: list[tuple[str, float | None]], currency: str = "USD"
    ) -> None:
        self.entries = list(entries or [])
        self.currency = currency or "USD"
        self._hover_index = None
        self.queue_draw()

    # -- geometry ---------------------------------------------------------

    def _pitch(self, width: float) -> float:
        return width / len(self.entries) if self.entries else 0.0

    def _index_at(self, x: float, width: float) -> int | None:
        pitch = self._pitch(width)
        if pitch <= 0 or not self.entries:
            return None
        return max(0, min(len(self.entries) - 1, int(x // pitch)))

    # -- drawing ----------------------------------------------------------

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO or not self.entries or width <= 0:
            return
        pitch = width / len(self.entries)
        bar_width = max(2.0, min(24.0, pitch * 0.58))
        plot_bottom = height - self.BOTTOM
        plot_height = max(1.0, plot_bottom - self.TOP)
        peak = max(
            (value for _label, value in self.entries if value is not None),
            default=0.0,
        ) or 1.0

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.0)

        # Show dates sparsely so they never collide.
        every = max(1, round(44.0 / pitch)) if pitch > 0 else 1

        for index, (label, value) in enumerate(self.entries):
            centre = pitch * index + pitch / 2
            if value is None:
                cr.save()
                cr.set_source_rgba(0.62, 0.62, 0.62, 0.35)
                cr.set_line_width(1.0)
                cr.set_dash([2.0, 2.0])
                cr.move_to(centre, self.TOP)
                cr.line_to(centre, plot_bottom)
                cr.stroke()
                cr.restore()
                if index % every == 0 or index == len(self.entries) - 1:
                    _draw_centred_text(
                        cr, label, centre, height - 4, 9.0, (0.55, 0.55, 0.55)
                    )
                continue
            bar_height = plot_height * (max(0.0, value) / peak)
            bar_height = max(2.0, bar_height)
            x = centre - bar_width / 2
            y = plot_bottom - bar_height

            if value <= 0:
                cr.set_source_rgba(0.55, 0.55, 0.55, 0.18)
            elif self._hover_index == index:
                cr.set_source_rgba(0.13, 0.76, 0.60, 1.0)
            else:
                cr.set_source_rgba(0.063, 0.64, 0.50, 0.92)
            _rounded_rect(cr, x, y, bar_width, bar_height, min(5.0, bar_width / 3))
            cr.fill()

            # Value above the bar when the columns have room.
            if value > 0 and pitch >= 34:
                text = format_currency(value, self.currency, compact=True)
                _draw_centred_text(cr, text, centre, y - 6, 10.0, (0.67, 0.67, 0.67))

            if index % every == 0 or index == len(self.entries) - 1:
                _draw_centred_text(
                    cr, label, centre, height - 4, 9.0, (0.55, 0.55, 0.55)
                )

    # -- interaction ------------------------------------------------------

    def _on_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        index = self._index_at(x, self.get_width())
        if index != self._hover_index:
            self._hover_index = index
            self.queue_draw()

    def _on_leave(self, controller: Gtk.EventControllerMotion) -> None:
        if self._hover_index is not None:
            self._hover_index = None
            self.queue_draw()

    def _on_query_tooltip(self, widget, x: int, y: int, keyboard: bool, tooltip: Gtk.Tooltip) -> bool:
        index = self._index_at(x, self.get_width())
        if index is None:
            return False
        label, value = self.entries[index]
        if value is None:
            tooltip.set_text(f"{label} · cost unavailable")
        else:
            tooltip.set_text(f"{label} · {format_currency(value, self.currency)}")
        return True


def _draw_centred_text(cr, text: str, x: float, baseline: float, size: float, color) -> None:
    cr.set_font_size(size)
    extents = cr.text_extents(text)
    cr.set_source_rgba(*color)
    cr.move_to(x - extents.width / 2 - extents.x_bearing, baseline)
    cr.show_text(text)
