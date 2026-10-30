"""Usage & Spend dashboard page."""

from __future__ import annotations

import math
from datetime import date, timedelta

import cairo
from gi.repository import Gtk

from .. import currency
from ..activity import (
    DAY_COUNT,
    WEEK_COUNT,
    activity_levels,
    align_start,
    cumulative_totals,
    daily_series,
    weekly_totals,
)
from ..data import SpendSummary
from ..format import format_currency, format_tokens
from . import cairo_support  # noqa: F401  (enables cairo drawing)
from .cards import MiniBarChart, StatTile
from .util import iter_children

# Cairo RGBA for the five activity levels (empty + four shades of the accent).
_HEAT_COLORS = (
    (0.55, 0.55, 0.55, 0.12),
    (0.063, 0.64, 0.50, 0.25),
    (0.063, 0.64, 0.50, 0.45),
    (0.063, 0.64, 0.50, 0.70),
    (0.063, 0.64, 0.50, 0.95),
)


class SpendHeatmap(Gtk.Box):
    """Token activity over the last year: daily, weekly or cumulative."""

    MODES = (("Daily", "daily"), ("Weekly", "weekly"), ("Cumulative", "cumulative"))

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._values: dict[date, int] = {}
        self._today = date.today()
        self._start = self._align_start(self._today)
        self._mode = "daily"
        self._hover_index: int | None = None

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        title = Gtk.Label(label="Token activity")
        title.add_css_class("cb-heat-title")
        title.set_halign(Gtk.Align.START)
        titles.append(title)
        self.summary = Gtk.Label(label="")
        self.summary.add_css_class("cb-caption")
        self.summary.set_halign(Gtk.Align.START)
        titles.append(self.summary)
        head.append(titles)

        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        modes.add_css_class("linked")
        group: Gtk.ToggleButton | None = None
        for label, mode in self.MODES:
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("flat")
            if group is None:
                button.set_active(True)
                group = button
            else:
                button.set_group(group)
            button.connect("toggled", self._on_mode_toggled, mode)
            modes.append(button)
        modes.set_halign(Gtk.Align.START)
        head.append(modes)
        self.append(head)

        self.area = Gtk.DrawingArea()
        self.area.set_content_height(104)
        self.area.set_hexpand(True)
        self.area.set_draw_func(self._draw)
        self.area.set_has_tooltip(True)
        self.area.connect("query-tooltip", self._on_query_tooltip)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.area.add_controller(motion)
        self.append(self.area)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        legend.set_halign(Gtk.Align.END)
        less = Gtk.Label(label="Less")
        less.add_css_class("cb-caption")
        legend.append(less)
        for level in range(5):
            swatch = Gtk.Box()
            swatch.add_css_class("cb-heat-swatch")
            swatch.add_css_class(f"cb-heat-{level}")
            legend.append(swatch)
        more = Gtk.Label(label="More")
        more.add_css_class("cb-caption")
        legend.append(more)
        self.append(legend)

        self.caption = Gtk.Label(
            label="",
            xalign=0.0,
        )
        self.caption.add_css_class("cb-caption")
        self.caption.set_halign(Gtk.Align.START)
        self.append(self.caption)

    # -- data -------------------------------------------------------------

    @staticmethod
    def _align_start(today: date) -> date:
        return align_start(today)

    def set_entries(self, daily: list[dict]) -> None:
        """Accept the raw ``cost --json`` daily entries."""
        values: dict[date, int] = {}
        for entry in daily:
            raw = str(entry.get("date") or "")
            try:
                day = date.fromisoformat(raw[:10])
            except ValueError:
                continue
            tokens = int(entry.get("totalTokens") or 0)
            values[day] = values.get(day, 0) + tokens
        self._values = values
        self._today = date.today()
        self._start = self._align_start(self._today)

        visible = [
            values.get(self._start + timedelta(days=index), 0)
            for index in range(WEEK_COUNT * DAY_COUNT)
            if self._start + timedelta(days=index) <= self._today
        ]
        total = sum(visible)
        self.summary.set_text(f"{format_tokens(total)} in the last year" if total else "No activity in the last year")
        self._update_caption()
        self.area.queue_draw()

    def _on_mode_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        if not button.get_active():
            return
        self._mode = mode
        self._update_caption()
        self.area.queue_draw()

    def _update_caption(self) -> None:
        if self._mode == "weekly":
            self.caption.set_text("Each column = 1 week")
        elif self._mode == "cumulative":
            self.caption.set_text("Running total")
        else:
            self.caption.set_text("Each cell = 1 day")

    # -- drawing ----------------------------------------------------------

    def _layout(self, width: float, height: float) -> tuple[float, float, float, float]:
        header = 18.0
        pitch = min(width / WEEK_COUNT, (height - header) / DAY_COUNT)
        pitch = max(pitch, 1.0)
        grid_w = pitch * WEEK_COUNT
        grid_h = pitch * DAY_COUNT
        x0 = (width - grid_w) / 2
        y0 = height - grid_h
        return pitch, x0, y0, header

    def _series(self) -> tuple[list[int], list[int]]:
        daily = []
        for index in range(WEEK_COUNT * DAY_COUNT):
            day = self._start + timedelta(days=index)
            if day < self._today - timedelta(days=364) or day > self._today:
                daily.append(-1)
            else:
                daily.append(self._values.get(day, 0))

        if self._mode == "weekly":
            return daily, activity_levels(weekly_totals(self._start, self._values, self._today))
        if self._mode == "cumulative":
            weekly = weekly_totals(self._start, self._values, self._today)
            return daily, activity_levels(cumulative_totals(weekly))
        visible = [value for value in daily if value >= 0]
        return daily, activity_levels(visible)

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if not cairo_support.HAS_CAIRO or width <= 0 or height <= 0:
            return
        pitch, x0, y0, header = self._layout(float(width), float(height))
        cell = max(pitch - 3.0, 2.0)
        radius = min(cell * 0.22, 2.5)
        daily, levels = self._series()

        # Month labels above the grid.
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.0)
        last_month = None
        last_x = -100.0
        for week in range(WEEK_COUNT):
            day = self._start + timedelta(days=week * DAY_COUNT)
            month = day.strftime("%b")
            x = x0 + week * pitch
            if month != last_month and x - last_x >= 28:
                cr.set_source_rgba(0.6, 0.6, 0.6, 0.8)
                cr.move_to(x, 12)
                cr.show_text(month)
                last_month = month
                last_x = x

        if self._mode == "daily":
            visible_index = 0
            visible_levels = levels
            for index, value in enumerate(daily):
                if value < 0:
                    continue
                level = visible_levels[visible_index] if visible_index < len(visible_levels) else 0
                visible_index += 1
                self._draw_cell(cr, x0, y0, pitch, cell, radius, index, level)
        else:
            # One tall column per week.
            for week in range(WEEK_COUNT):
                level = levels[week] if week < len(levels) else 0
                column_day = self._start + timedelta(days=week * DAY_COUNT)
                if column_day > self._today:
                    continue
                x = x0 + week * pitch + (pitch - cell) / 2
                y = y0 + (pitch - cell) / 2
                cr.set_source_rgba(*_HEAT_COLORS[level])
                _rounded_rect(cr, x, y, cell, pitch * DAY_COUNT - (pitch - cell), radius)
                cr.fill()

        if self._hover_index is not None:
            index = self._hover_index
            column = index // DAY_COUNT
            row = index % DAY_COUNT
            x = x0 + column * pitch + (pitch - cell) / 2
            y = y0 + row * pitch + (pitch - cell) / 2
            cr.set_source_rgba(0.85, 0.85, 0.85, 0.9)
            cr.set_line_width(1.5)
            _rounded_rect(cr, x, y, cell, cell, radius)
            cr.stroke()

    def _draw_cell(self, cr, x0, y0, pitch, cell, radius, index: int, level: int) -> None:
        column = index // DAY_COUNT
        row = index % DAY_COUNT
        x = x0 + column * pitch + (pitch - cell) / 2
        y = y0 + row * pitch + (pitch - cell) / 2
        cr.set_source_rgba(*_HEAT_COLORS[level])
        _rounded_rect(cr, x, y, cell, cell, radius)
        cr.fill()

    # -- interaction ------------------------------------------------------

    def _on_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        width = self.area.get_width()
        height = self.area.get_height()
        pitch, x0, y0, _header = self._layout(float(width), float(height))
        column = int((x - x0) // pitch)
        row = int((y - y0) // pitch)
        index = None
        if 0 <= column < WEEK_COUNT and 0 <= row < DAY_COUNT:
            day = self._start + timedelta(days=column * DAY_COUNT + row)
            if self._today - timedelta(days=364) <= day <= self._today:
                index = column * DAY_COUNT + row
        if index != self._hover_index:
            self._hover_index = index
            self.area.queue_draw()

    def _on_leave(self, controller: Gtk.EventControllerMotion) -> None:
        if self._hover_index is not None:
            self._hover_index = None
            self.area.queue_draw()

    def _on_query_tooltip(self, widget, x: int, y: int, keyboard: bool, tooltip: Gtk.Tooltip) -> bool:
        width = self.area.get_width()
        height = self.area.get_height()
        pitch, x0, y0, _header = self._layout(float(width), float(height))
        column = int((x - x0) // pitch)
        row = int((y - y0) // pitch)
        if not (0 <= column < WEEK_COUNT and 0 <= row < DAY_COUNT):
            return False
        day = self._start + timedelta(days=column * DAY_COUNT + row)
        if not (self._today - timedelta(days=364) <= day <= self._today):
            return False
        if self._mode == "daily":
            tokens = self._values.get(day, 0)
            tooltip.set_text(f"{day.strftime('%a %-d %b %Y')} · {format_tokens(tokens)} tokens")
        else:
            week_start = self._start + timedelta(days=column * DAY_COUNT)
            if self._mode == "weekly":
                tokens = sum(
                    self._values.get(week_start + timedelta(days=offset), 0)
                    for offset in range(DAY_COUNT)
                )
                label = "week of"
            else:
                tokens = sum(
                    sum(
                        self._values.get(self._start + timedelta(days=index * DAY_COUNT + offset), 0)
                        for offset in range(DAY_COUNT)
                    )
                    for index in range(column + 1)
                )
                label = "through"
            tooltip.set_text(f"{label} {week_start.strftime('%-d %b %Y')} · {format_tokens(tokens)} tokens")
        return True


def _rounded_rect(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = max(0.0, min(radius, width / 2, height / 2))
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


class SpendView(Gtk.Box):
    """Local spend summary: totals, activity heatmap, daily chart, projects and models."""

    def __init__(self, prefs=None, refresh=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.prefs = prefs
        self._refresh = refresh
        self.add_css_class("cb-dash-grid")
        self.set_size_request(720, -1)

        tiles = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.total_tile = StatTile("Total spend")
        self.session_tile = StatTile("This session")
        self.tokens_tile = StatTile("Tokens")
        self.coverage_tile = StatTile("Coverage")
        for index, tile in enumerate((self.total_tile, self.session_tile, self.tokens_tile, self.coverage_tile)):
            tiles.attach(tile, index % 2, index // 2, 1, 1)

        range_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        range_box.set_margin_top(4)
        range_label = Gtk.Label(label="Cost history")
        range_label.add_css_class("cb-caption")
        range_label.set_xalign(0)
        range_box.append(range_label)
        self.time_range = Gtk.ComboBoxText()
        self._range_days = {
            "7 days": 7,
            "30 days": 30,
            "90 days": 90,
            "All": None,
        }
        for label in self._range_days:
            self.time_range.append_text(label)
        self.time_range.connect("changed", self._on_time_range_changed)
        range_box.append(self.time_range)
        self._select_time_range(str(self.prefs.get("spendTimeRange") or "30 days"))
        self.append(range_box)
        self.append(tiles)

        self.notice_label = Gtk.Label(label="", xalign=0.0)
        self.notice_label.add_css_class("cb-caption")
        self.notice_label.set_wrap(True)
        self.notice_label.set_visible(False)
        self.append(self.notice_label)

        self.heatmap = SpendHeatmap()
        self.append(self.heatmap)

        chart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label="Daily spend")
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        chart_box.append(label)
        self.chart = MiniBarChart()
        chart_box.append(self.chart)
        self.append(chart_box)

        self.providers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(self.providers_box)

        self.projects_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(self.projects_box)

        self.models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(self.models_box)

        self.empty_label = Gtk.Label(label="No local cost data yet")
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

    def _select_time_range(self, label: str) -> None:
        """Select the combo entry for ``label`` (e.g. ``"30 days"``)."""
        model = self.time_range.get_model()
        iterator = model.get_iter_first()
        index = 0
        while iterator is not None:
            if model.get_value(iterator, 0) == label:
                self.time_range.set_active(index)
                return
            iterator = model.iter_next(iterator)
            index += 1

    def _time_range_days(self) -> int | None:
        """Days of history to show, or ``None`` for all available days."""
        label = self.time_range.get_active_text() or "30 days"
        return self._range_days.get(label, 30)

    def _on_time_range_changed(self, combo) -> None:
        label = combo.get_active_text() or "30 days"
        if self.prefs is not None:
            self.prefs.set("spendTimeRange", label)
        if self._refresh is not None:
            self._refresh()

    # -- currency ---------------------------------------------------------

    def _target_currency(self, source: str) -> tuple[str, str]:
        preferred = str(self.prefs.get("preferredCurrencyCode") or "auto") if self.prefs else "auto"
        preferred = preferred.strip().upper()
        source = (source or "USD").strip()
        if preferred in ("", "AUTO") or preferred == source.upper() or not currency.requires_live_rates(preferred):
            return source.upper(), source.upper()
        return preferred, source.upper()

    def _convert_value(self, amount: float, source: str) -> float:
        target, source = self._target_currency(source)
        if target != source:
            converted = currency.convert(amount, source, target)
            if converted is not None:
                return converted
        return amount

    def _money(self, amount: float, source: str) -> str:
        target, source = self._target_currency(source)
        return format_currency(self._convert_value(amount, source), target)

    def _display_currency(self, source: str) -> str:
        target, source = self._target_currency(source)
        if target != source and currency.convert(1.0, source, target) is None:
            return source
        return target

    # -- updates ----------------------------------------------------------

    def update(self, spend: SpendSummary | None, error: str | None = None) -> None:
        if spend is None:
            self.total_tile.set_value("—")
            self.session_tile.set_value("—")
            self.tokens_tile.set_value("—")
            self.coverage_tile.set_value("—")
            self.chart.set_entries([])
            self.heatmap.set_entries([])
            self.empty_label.set_visible(True)
            self.notice_label.set_text(error or "")
            self.notice_label.set_visible(bool(error))
            return

        source = spend.currency or "USD"
        currency_code = self._display_currency(source)
        partial = spend.cost_partial or bool(error)
        self.total_tile.set_value(
            ("≥ " if partial else "") + self._money(spend.total_cost, source)
            if spend.cost_known else "—",
            "Known subtotal · some costs unavailable" if partial and spend.cost_known
            else spend.history_label or spend.reporting_period or "",
        )
        self.session_tile.set_value(
            self._money(spend.session_cost, source) if spend.session_cost_known else "—",
            f"{format_tokens(spend.session_tokens)} tokens",
        )
        self.tokens_tile.set_value(
            format_tokens(spend.total_tokens),
            (("≥ " if spend.last30_cost_partial else "")
             + self._money(spend.last30_cost, source)
             + " last 30 days") if spend.last30_cost_known else "cost unavailable",
        )
        priced = int(spend.coverage.get("priced", 0) or 0)
        unpriced = int(spend.coverage.get("unpriced", 0) or 0)
        if priced or unpriced:
            self.coverage_tile.set_value(
                f"{priced}/{priced + unpriced}",
                "priced entries",
            )
        else:
            self.coverage_tile.set_value(
                "—",
                (spend.provenance or "unknown").replace("_", " "),
            )

        self.heatmap.set_entries(spend.daily)

        entries = [
            (
                day.isoformat()[5:],
                self._convert_value(value, source) if value is not None else None,
            )
            for day, value in daily_series(
                spend.daily,
                days=self._time_range_days(),
                history_coverage_established=spend.history_coverage_established,
            )
        ]
        self.chart.set_entries(entries, currency_code)

        self._rebuild_providers(spend, currency_code)

        self._rebuild_list(
            self.projects_box,
            "Projects",
            [
                (
                    str(project.get("name") or project.get("path") or "—"),
                    self._money(float(project["totalCost"]), source)
                    if project.get("totalCost") is not None
                    else "unpriced",
                    format_tokens(int(project.get("totalTokens") or 0)),
                )
                for project in spend.projects[:12]
            ],
        )

        models: dict[str, dict[str, float | bool]] = {}
        for model in spend.models:
            name = str(model.get("modelName") or model.get("name") or "—")
            raw_cost = model.get("cost")
            fallback_cost = model.get("totalCost")
            if raw_cost is None or raw_cost == 0:
                if fallback_cost not in (None, 0):
                    raw_cost = fallback_cost
                elif raw_cost is None:
                    raw_cost = fallback_cost
            bucket = models.setdefault(
                name,
                {"cost": 0.0, "tokens": 0.0, "cost_known": False, "cost_partial": False},
            )
            if raw_cost is None:
                bucket["cost_partial"] = True
            else:
                cost = float(raw_cost)
                if math.isfinite(cost):
                    bucket["cost"] = float(bucket["cost"]) + cost
                    bucket["cost_known"] = True
                else:
                    bucket["cost_partial"] = True
            bucket["tokens"] = float(bucket["tokens"]) + float(model.get("totalTokens") or 0.0)
        self._rebuild_list(
            self.models_box,
            "Models",
            [
                (
                    name,
                    (
                        ("≥ " if values["cost_partial"] else "")
                        + self._money(float(values["cost"]), source)
                        if values["cost_known"]
                        else "unpriced"
                    ),
                    format_tokens(int(values["tokens"])),
                )
                for name, values in sorted(models.items(), key=lambda kv: float(kv[1]["cost"]), reverse=True)[:12]
            ],
        )

        self.empty_label.set_visible(not spend.daily and not spend.projects)
        notice = error or spend.error
        self.notice_label.set_text(notice or "")
        self.notice_label.set_visible(bool(notice))

    def update_projection(self, model: dict) -> None:
        """Render the Rust-owned spend DTO without reapplying data policy."""
        self._select_time_range(model.get("selected_range", "30 days"))
        currency_code = model.get("display_currency") or model.get("source_currency") or "USD"

        def amount_text(amount: dict) -> str:
            if not amount.get("known") or amount.get("display_amount") is None:
                return "—"
            prefix = "≥ " if amount.get("partial") else ""
            return prefix + format_currency(amount["display_amount"], currency_code)

        def count_text(count: dict) -> str:
            value = count.get("value")
            if not count.get("known") or value is None:
                return "—"
            prefix = "≥ " if count.get("partial") else ""
            return prefix + format_tokens(int(value))

        total = model.get("total") or {}
        session = model.get("session") or {}
        last30 = model.get("last30") or {}
        self.total_tile.set_value(
            amount_text(total),
            "Known subtotal · some costs unavailable"
            if total.get("known") and total.get("partial")
            else model.get("history_label") or model.get("reporting_period") or "",
        )
        self.session_tile.set_value(
            amount_text(session),
            f"{count_text(model.get('session_tokens') or {})} tokens",
        )
        last30_label = (
            amount_text(last30) + " last 30 days"
            if last30.get("known")
            else "cost unavailable"
        )
        if (last30_tokens := model.get("last30_tokens") or {}).get("known"):
            last30_label += " · " + count_text(last30_tokens) + " tokens"
        self.tokens_tile.set_value(count_text(model.get("tokens") or {}), last30_label)

        coverage = model.get("coverage") or {}
        priced = int(coverage.get("priced") or 0)
        unpriced = int(coverage.get("unpriced") or 0)
        if coverage.get("has_counts"):
            self.coverage_tile.set_value(f"{priced}/{priced + unpriced}", "priced entries")
        else:
            provenance = coverage.get("provenance") or model.get("provenance") or "—"
            self.coverage_tile.set_value("—", str(provenance).replace("_", " "))

        self.heatmap.set_entries(model.get("heatmap_daily") or [])
        chart_entries = [
            (str(point.get("date") or "")[5:10], point.get("display_amount"))
            for point in model.get("daily_chart") or []
        ]
        self.chart.set_entries(chart_entries, currency_code)

        self._render_projection_rows(
            self.providers_box,
            "By provider",
            model.get("providers") or [],
            "provider",
            currency_code,
        )
        self._render_projection_rows(
            self.projects_box,
            "Projects",
            model.get("projects") or [],
            "name",
            currency_code,
        )
        self._render_projection_rows(
            self.models_box,
            "Models",
            model.get("models") or [],
            "name",
            currency_code,
        )
        has_summary = bool(model.get("spend_present"))
        loading = not has_summary and model.get("backend_status") in ("idle", "refreshing")
        self.empty_label.set_text("Loading local cost data…" if loading else "No local cost data yet")
        self.empty_label.set_visible(bool(model.get("empty")) or (not has_summary and not loading))
        notice = {
            "refresh_failed": "Refresh failed; showing the last available data.",
            "cost_sources_unavailable": "Some cost sources are unavailable.",
        }.get(model.get("notice"), "")
        self.notice_label.set_text(notice)
        self.notice_label.set_visible(bool(notice))

    def _render_projection_rows(
        self,
        box: Gtk.Box,
        title: str,
        entries: list[dict],
        name_key: str,
        currency_code: str,
    ) -> None:
        for child in list(iter_children(box)):
            box.remove(child)
        if not entries:
            return
        label = Gtk.Label(label=title)
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        box.append(label)
        for entry in entries:
            count = entry.get("tokens") or {}
            tokens = "—"
            if count.get("known") and count.get("value") is not None:
                prefix = "≥ " if count.get("partial") else ""
                tokens = prefix + format_tokens(int(count["value"]))
            cost = "unpriced"
            if entry.get("cost_known") and entry.get("display_cost") is not None:
                prefix = "≥ " if entry.get("cost_partial") else ""
                cost = prefix + format_currency(entry["display_cost"], currency_code)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.add_css_class("cb-kv")
            name = Gtk.Label(label=str(entry.get(name_key) or "—"))
            name.add_css_class("cb-kv-key")
            name.set_hexpand(True)
            name.set_halign(Gtk.Align.START)
            name.set_ellipsize(3)
            row.append(name)
            token_label = Gtk.Label(label=tokens)
            token_label.add_css_class("cb-kv-key")
            token_label.set_halign(Gtk.Align.END)
            row.append(token_label)
            cost_label = Gtk.Label(label=cost)
            cost_label.add_css_class("cb-kv-value")
            cost_label.set_halign(Gtk.Align.END)
            row.append(cost_label)
            box.append(row)

    def _rebuild_providers(self, spend: SpendSummary, currency_code: str) -> None:
        """One row per provider that has local usage data."""
        for child in list(iter_children(self.providers_box)):
            self.providers_box.remove(child)
        if not spend.providers:
            return

        label = Gtk.Label(label="By provider")
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        self.providers_box.append(label)

        source = spend.currency or "USD"
        for entry in spend.providers:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.add_css_class("cb-kv")

            name = Gtk.Label(label=entry.display_name)
            name.add_css_class("cb-kv-key")
            name.set_halign(Gtk.Align.START)
            name.set_hexpand(True)
            row.append(name)

            tokens = Gtk.Label(label=format_tokens(entry.tokens))
            tokens.add_css_class("cb-kv-key")
            tokens.set_halign(Gtk.Align.END)
            row.append(tokens)

            if entry.cost_known:
                partial = any(day.get("totalCost") is None for day in entry.daily)
                cost_text = ("≥ " if partial else "") + self._money(entry.cost, source)
            else:
                cost_text = "unpriced"
            cost = Gtk.Label(label=cost_text)
            cost.add_css_class("cb-kv-value")
            cost.set_halign(Gtk.Align.END)
            row.append(cost)
            self.providers_box.append(row)

    def _rebuild_list(self, box: Gtk.Box, title: str, rows: list[tuple[str, str, str]]) -> None:
        for child in list(iter_children(box)):
            box.remove(child)
        if not rows:
            return
        label = Gtk.Label(label=title)
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        box.append(label)
        for name, cost, tokens in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.add_css_class("cb-kv")
            name_label = Gtk.Label(label=name)
            name_label.add_css_class("cb-kv-key")
            name_label.set_hexpand(True)
            name_label.set_halign(Gtk.Align.START)
            name_label.set_ellipsize(3)
            row.append(name_label)
            tokens_label = Gtk.Label(label=tokens)
            tokens_label.add_css_class("cb-kv-key")
            row.append(tokens_label)
            cost_label = Gtk.Label(label=cost)
            cost_label.add_css_class("cb-kv-value")
            row.append(cost_label)
            box.append(row)
