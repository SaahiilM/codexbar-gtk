"""Reusable widgets: provider cards, quota meters and small stat tiles."""

from __future__ import annotations

from datetime import datetime, timezone

from gi.repository import Graphene, Gtk

from . import cairo_support  # noqa: F401  (enables cairo drawing)

import cairo  # noqa: F401  (registers the cairo foreign-struct converter)

from ..data import ProviderUsage, RateWindow
from .util import iter_children
from ..format import (
    format_absolute,
    format_countdown,
    format_credits,
    format_currency,
    format_percent,
    format_pace,
    format_remaining,
    format_reset,
    format_tokens,
    format_updated,
)

SEVERITY_CLASS = {
    "ok": "",
    "warning": "warning",
    "critical": "critical",
}


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


class MeterBar(Gtk.DrawingArea):
    """A rounded quota meter drawn with Cairo.

    Using a drawing area instead of ``Gtk.ProgressBar`` gives us per-provider
    accent colours, rounded caps and warning markers. When PyGObject cannot
    hand out Cairo contexts the widget falls back to a plain progress bar.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 10)
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

    def _rounded_rect(self, cr, x: float, y: float, width: float, height: float, radius: float) -> None:
        radius = min(radius, height / 2, width / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5707963, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5707963)
        cr.arc(x + radius, y + height - radius, radius, 1.5707963, 3.1415926)
        cr.arc(x + radius, y + radius, radius, 3.1415926, 4.7123890)
        cr.close_path()

    def _draw(self, area, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO:
            return
        if width <= 0 or height <= 0:
            return

        radius = height / 2

        cr.set_source_rgba(0.5, 0.5, 0.5, 0.22)
        self._rounded_rect(cr, 0, 0, width, height, radius)
        cr.fill()

        filled = width * self.fraction
        if filled > 0.5:
            cr.set_source_rgba(*_parse_color(self.color))
            self._rounded_rect(cr, 0, 0, max(filled, height), height, radius)
            cr.fill()

        for marker in self.markers:
            x = width * (marker / 100.0)
            if 0 < x < width - 1:
                cr.set_source_rgba(1, 1, 1, 0.55)
                cr.rectangle(x, 1, 1, height - 2)
                cr.fill()


def _begin_cairo(snapshot, widget: Gtk.Widget):
    """Start a Cairo context for a widget, returning (cr, width, height)."""
    bounds = widget.get_bounds()
    x, y, width, height = bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]
    rect = Graphene.Rect()
    rect.init(x, y, width, height)
    return snapshot.append_cairo(rect), width, height


def _status_color(level: str | None) -> str | None:
    return {
        "minor": "#e0a030",
        "major": "#e05252",
        "critical": "#e05252",
        "maintenance": "#e0a030",
        "unknown": "#9a9a9a",
    }.get((level or "").lower())


def _severity_color(severity: str, accent: str) -> str:
    if severity == "critical":
        return "#e05252"
    if severity == "warning":
        return "#e0a030"
    return accent


def _parse_color(value: str) -> tuple[float, float, float, float]:
    text = value.strip()
    if text.startswith("#") and len(text) == 7:
        try:
            return (
                int(text[1:3], 16) / 255.0,
                int(text[3:5], 16) / 255.0,
                int(text[5:7], 16) / 255.0,
                1.0,
            )
        except ValueError:
            pass
    return (0.39, 0.40, 0.96, 1.0)


class MeterRow(Gtk.Box):
    """One quota window: title, percentage, bar, reset countdown and pace detail."""

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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.window = window
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.thresholds = thresholds or []
        self.accent_color = accent_color
        self.add_css_class("cb-metric")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
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

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.reset_label = Gtk.Label(label="")
        self.reset_label.add_css_class("cb-metric-detail")
        self.reset_label.set_halign(Gtk.Align.START)
        self.reset_label.set_hexpand(True)
        self.reset_label.set_ellipsize(3)
        footer.append(self.reset_label)

        self.detail_label = Gtk.Label(label="")
        self.detail_label.add_css_class("cb-metric-detail")
        self.detail_label.set_halign(Gtk.Align.END)
        footer.append(self.detail_label)
        self.append(footer)

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
        self.reset_label.set_text(reset_text)
        self.reset_label.set_visible(bool(reset_text))

    def set_pace(self, pace_text: str | None, severity: str = "ok") -> None:
        if not pace_text or not self.show_pace:
            self.detail_label.set_text("")
            return
        self.detail_label.set_text(pace_text)
        self.detail_label.remove_css_class("cb-metric-detail-warn")
        self.detail_label.remove_css_class("cb-metric-detail-crit")
        if severity == "critical":
            self.detail_label.add_css_class("cb-metric-detail-crit")
        elif severity == "warning":
            self.detail_label.add_css_class("cb-metric-detail-warn")


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
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.provider = provider
        self.show_used = show_used
        self.reset_style = reset_style
        self.show_pace = show_pace
        self.thresholds = thresholds or []
        self.show_identity = show_identity
        self.compact = compact
        self.add_css_class("cb-card")

        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("cb-card-header")

        self.dot = StatusDot()
        self.dot.set_color(provider.accent_color)
        self.header.append(self.dot)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_hexpand(True)
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
        self.meters_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.meters_box)

        self.extra_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
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
            thresholds = self._thresholds_for(window)
            row = MeterRow(
                window,
                show_used=self.show_used,
                reset_style=self.reset_style,
                show_pace=self.show_pace,
                thresholds=thresholds,
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
        if not subtitle_parts:
            if provider.source:
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

        self.dot.set_tooltip_text(provider.status_description or "")
        status_color = _status_color(provider.status_level)
        self.dot.set_color(status_color or provider.accent_color, filled=status_color is None)

        for row in self.meters:
            row.update(now)
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

        if provider.credits_remaining is not None:
            self.extra_box.append(
                _kv_row("Credits", f"{format_credits(provider.credits_remaining)} remaining")
            )

        cost = provider.cost
        if cost is not None and (cost.used or cost.limit or cost.balance is not None):
            if cost.has_limit:
                text = (
                    f"{format_currency(cost.used, cost.currency)} of "
                    f"{format_currency(cost.limit, cost.currency)} · {cost.period or 'spend'}"
                )
            elif cost.balance is not None:
                text = f"{format_currency(cost.balance, cost.currency)} balance"
            else:
                text = f"{format_currency(cost.used, cost.currency)} spent"
            self.extra_box.append(_kv_row("Spend", text))

        for section in provider.details[:3]:
            for row in section.rows[:4]:
                value = row.value
                if row.secondary_value:
                    value = f"{value} · {row.secondary_value}"
                self.extra_box.append(_kv_row(row.label, value))

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
            used = f"{window.used_percent:.0f}%" if self.show_used else f"{window.remaining_percent:.0f}% left"
            countdown = format_countdown(window.resets_at)
            text = f"{window.title} {used}"
            if countdown:
                text += f" (resets in {countdown})"
            parts.append(text)
        return " — ".join(parts)


def _kv_row(key: str, value: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.add_css_class("cb-kv")
    key_label = Gtk.Label(label=key)
    key_label.add_css_class("cb-kv-key")
    key_label.set_halign(Gtk.Align.START)
    key_label.set_hexpand(True)
    key_label.set_ellipsize(3)
    box.append(key_label)
    value_label = Gtk.Label(label=value)
    value_label.add_css_class("cb-kv-value")
    value_label.set_halign(Gtk.Align.END)
    value_label.set_ellipsize(3)
    box.append(value_label)
    return box


class StatTile(Gtk.Box):
    """A big number with a caption, used on the dashboard."""

    def __init__(self, label: str, value: str = "—", caption: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.add_css_class("cb-tile")
        self.value_label = Gtk.Label(label=value)
        self.value_label.add_css_class("cb-tile-value")
        self.value_label.set_halign(Gtk.Align.START)
        self.append(self.value_label)
        self.label_widget = Gtk.Label(label=label)
        self.label_widget.add_css_class("cb-tile-label")
        self.label_widget.set_halign(Gtk.Align.START)
        self.append(self.label_widget)
        self.caption_widget = Gtk.Label(label=caption)
        self.caption_widget.add_css_class("cb-tile-label")
        self.caption_widget.set_halign(Gtk.Align.START)
        self.caption_widget.set_visible(bool(caption))
        self.append(self.caption_widget)

    def set_value(self, value: str, caption: str | None = None) -> None:
        self.value_label.set_text(value)
        if caption is not None:
            self.caption_widget.set_text(caption)
            self.caption_widget.set_visible(bool(caption))


class MiniBarChart(Gtk.Box):
    """Simple bar chart for daily spend."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("cb-chart")
        self.set_valign(Gtk.Align.END)
        self.set_hexpand(True)

    def set_entries(self, entries: list[tuple[str, float]]) -> None:
        for child in list(iter_children(self)):
            self.remove(child)
        if not entries:
            return
        peak = max((value for _, value in entries), default=0.0) or 1.0
        for label, value in entries:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            column.set_valign(Gtk.Align.END)
            column.set_hexpand(True)
            bar = Gtk.Box()
            bar.add_css_class("cb-chart-bar")
            height = max(4, int(120 * (value / peak)))
            bar.set_size_request(-1, height)
            bar.set_valign(Gtk.Align.END)
            column.append(bar)
            caption = Gtk.Label(label=label)
            caption.add_css_class("cb-tile-label")
            caption.set_halign(Gtk.Align.CENTER)
            column.append(caption)
            self.append(column)
