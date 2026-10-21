"""Reusable widgets: provider cards, quota meters and stat tiles.

The look is built on libadwaita's own style classes (``.card``, ``.title``,
``.heading``, ``.caption``, ``.numeric``) so the app feels native on GNOME and
still looks right on KDE Plasma.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gi.repository import Gtk

from ..data import ProviderUsage, RateWindow
from ..format import (
    format_credits,
    format_currency,
    format_countdown,
    format_pace,
    format_percent,
    format_remaining,
    format_reset,
    format_updated,
)
from . import cairo_support  # noqa: F401  (enables cairo drawing)
from .util import iter_children

import cairo  # noqa: F401  (registers the cairo foreign-struct converter)


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


class ProviderAvatar(Gtk.DrawingArea):
    """A rounded badge with the provider's initial, in its brand colour."""

    def __init__(self, name: str, color: str, size: int = 34) -> None:
        super().__init__()
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.name = name
        self.color = color
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO:
            return
        radius = min(width, height) * 0.28
        r, g, b, _a = _parse_color(self.color)
        cr.set_source_rgba(r, g, b, 0.22)
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 6.2831853)
        cr.fill()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.set_line_width(1.4)
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 6.2831853)
        cr.stroke()

        initial = (self.name or "?")[0].upper()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.select_font_face("Sans", 0, 1)  # normal slant, bold weight
        cr.set_font_size(min(width, height) * 0.46)
        extents = cr.text_extents(initial)
        x = width / 2 - (extents[2] / 2 + extents[0])
        y = height / 2 + (extents[3] / 2 + extents[1])
        cr.move_to(x, y)
        cr.show_text(initial)


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
        if cairo_support.HAS_CAIRO:
            self.set_draw_func(self._draw)
        else:
            self._fallback = Gtk.ProgressBar()
            self._fallback.set_show_text(False)
            self._fallback.set_valign(Gtk.Align.CENTER)
            self._fallback.set_hexpand(True)
            self.add_css_class("cb-meter")
            self._fallback.set_parent(self)

    def set_meter(self, fraction: float, color: str, markers: list[float] | None = None) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.color = color
        self.markers = markers or []
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
        values = [value for _, value in self.points]
        low = min(values)
        high = max(values)
        span = max(high - low, 5.0)
        count = len(self.points)
        step = width / max(count - 1, 1)

        r, g, b, _a = _parse_color(self.color)

        # Filled area under the line.
        cr.set_source_rgba(r, g, b, 0.16)
        cr.move_to(0, height)
        for index, (_, value) in enumerate(self.points):
            x = index * step
            y = height - ((value - low) / span) * (height - 4) - 2
            cr.line_to(x, y)
        cr.line_to(width, height)
        cr.close_path()
        cr.fill()

        # The line itself.
        cr.set_source_rgba(r, g, b, 0.85)
        cr.set_line_width(1.6)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for index, (_, value) in enumerate(self.points):
            x = index * step
            y = height - ((value - low) / span) * (height - 4) - 2
            if index == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        # Current value marker.
        last_x = (count - 1) * step
        last_y = height - ((values[-1] - low) / span) * (height - 4) - 2
        cr.set_source_rgba(r, g, b, 1.0)
        cr.arc(last_x, last_y, 2.4, 0, 6.2831853)
        cr.fill()


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
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window = window
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.thresholds = thresholds or []
        self.accent_color = accent_color

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
        )

        reset_text = format_reset(window.resets_at, self.reset_style, now)
        if reset_text is None:
            reset_text = window.reset_description or ""
        self.reset_chip.set_text(reset_text)
        self.reset_chip.set_visible(bool(reset_text))

    def set_trend(self, points: list[tuple[float, float]], color: str) -> None:
        self.sparkline.set_points(points, color)
        self.trend_label.set_visible(len(points) >= 3)

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
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.provider = provider
        self.history = history
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.thresholds = thresholds or []
        self.show_identity = show_identity
        self.compact = compact
        self.add_css_class("cb-card")

        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("cb-card-header")

        self.avatar = ProviderAvatar(provider.display_name, provider.accent_color)
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
        self.append(self.header)

        self.meters: list[MeterRow] = []
        self.meters_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.meters_box.set_margin_top(14)
        self.append(self.meters_box)

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
            )
            self.meters.append(row)
            self.meters_box.append(row)

    def _thresholds_for(self, window: RateWindow) -> list[float]:
        return self.thresholds

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
        if updated:
            subtitle_parts.append(f"updated {updated}")
        self.subtitle_label.set_text(" · ".join(subtitle_parts))

        badge = ""
        if provider.status_level:
            badge = str(provider.status_level).replace("_", " ").title()
        elif provider.reset_credits_available:
            badge = f"{provider.reset_credits_available} resets"
        self.badge_label.set_text(badge)
        self.badge_label.set_visible(bool(badge))

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

        self._rebuild_extra(now)

        if provider.error:
            self.error_label.set_text(provider.error)
            self.error_label.set_visible(True)
        else:
            self.error_label.set_visible(False)

    def _rebuild_extra(self, now: datetime) -> None:
        for child in list(iter_children(self.extra_box)):
            self.extra_box.remove(child)

        provider = self.provider
        rows: list[tuple[str, str, str]] = []

        if provider.credits_remaining is not None:
            rows.append(("Credits", f"{format_credits(provider.credits_remaining)} remaining", ""))

        cost = provider.cost
        if cost is not None and (cost.used or cost.limit or cost.balance is not None):
            if cost.has_limit:
                text = (
                    f"{format_currency(cost.used, cost.currency)} of "
                    f"{format_currency(cost.limit, cost.currency)}"
                )
            elif cost.balance is not None:
                text = f"{format_currency(cost.balance, cost.currency)} balance"
            else:
                text = f"{format_currency(cost.used, cost.currency)} spent"
            rows.append(("Spend", text, cost.period or ""))

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
            if hint:
                hint_label = Gtk.Label(label=hint)
                hint_label.add_css_class("cb-kv-key")
                row.append(hint_label)
            grid.append(row)
        self.extra_box.append(grid)

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


class MiniBarChart(Gtk.Box):
    """Bar chart for daily spend, with a value label on top of each bar."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("cb-chart")
        self.set_valign(Gtk.Align.END)
        self.set_hexpand(True)

    def set_entries(self, entries: list[tuple[str, float]], currency: str = "USD") -> None:
        for child in list(iter_children(self)):
            self.remove(child)
        if not entries:
            return
        peak = max((value for _, value in entries), default=0.0) or 1.0
        for label, value in entries:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            column.set_valign(Gtk.Align.END)
            column.set_hexpand(True)

            value_label = Gtk.Label(label=format_currency(value, currency, compact=True))
            value_label.add_css_class("cb-chart-value")
            value_label.set_halign(Gtk.Align.CENTER)
            column.append(value_label)

            bar = Gtk.Box()
            bar.add_css_class("cb-chart-bar")
            height = max(4, int(120 * (value / peak)))
            bar.set_size_request(-1, height)
            bar.set_valign(Gtk.Align.END)
            column.append(bar)

            caption = Gtk.Label(label=label)
            caption.add_css_class("cb-chart-label")
            caption.set_halign(Gtk.Align.CENTER)
            column.append(caption)
            self.append(column)
