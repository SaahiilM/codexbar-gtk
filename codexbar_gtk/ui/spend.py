"""Usage & Spend dashboard page."""

from __future__ import annotations

from gi.repository import Gtk

from ..data import SpendSummary
from ..format import format_currency, format_tokens
from .cards import MiniBarChart, StatTile
from .util import iter_children


class SpendView(Gtk.Box):
    """Local spend summary: totals, daily chart, projects and models."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("cb-dash-grid")
        self.set_size_request(720, -1)

        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tiles.set_homogeneous(True)
        self.total_tile = StatTile("Total spend")
        self.session_tile = StatTile("This session")
        self.tokens_tile = StatTile("Tokens")
        self.coverage_tile = StatTile("Coverage")
        for tile in (self.total_tile, self.session_tile, self.tokens_tile, self.coverage_tile):
            tiles.append(tile)
        self.append(tiles)

        chart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        chart_box.set_margin_top(16)
        label = Gtk.Label(label="Daily spend")
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        chart_box.append(label)
        self.chart = MiniBarChart()
        chart_box.append(self.chart)
        self.append(chart_box)

        self.providers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.providers_box.set_margin_top(16)
        self.append(self.providers_box)

        self.projects_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.projects_box.set_margin_top(16)
        self.append(self.projects_box)

        self.models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.models_box.set_margin_top(16)
        self.append(self.models_box)

        self.empty_label = Gtk.Label(label="No local cost data yet")
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

    def update(self, spend: SpendSummary | None) -> None:
        if spend is None:
            self.total_tile.set_value("—")
            self.session_tile.set_value("—")
            self.tokens_tile.set_value("—")
            self.coverage_tile.set_value("—")
            self.chart.set_entries([])
            self.empty_label.set_visible(True)
            return

        currency = spend.currency or "USD"
        self.total_tile.set_value(
            format_currency(spend.total_cost, currency),
            spend.history_label or spend.reporting_period or "",
        )
        self.session_tile.set_value(
            format_currency(spend.session_cost, currency),
            f"{format_tokens(spend.session_tokens)} tokens",
        )
        self.tokens_tile.set_value(
            format_tokens(spend.total_tokens),
            f"{format_currency(spend.last30_cost, currency)} last 30 days",
        )
        coverage_text = "unknown"
        if spend.coverage:
            parts = [f"{count} {key}" for key, count in spend.coverage.items() if count]
            coverage_text = ", ".join(parts) if parts else "unknown"
        self.coverage_tile.set_value(
            coverage_text,
            (spend.provenance or "").replace("_", " "),
        )

        entries = []
        for day in spend.daily[-30:]:
            date = str(day.get("date", ""))
            entries.append((date[5:] if len(date) >= 10 else date, float(day.get("totalCost") or 0.0)))
        self.chart.set_entries(entries)

        self._rebuild_providers(spend)

        self._rebuild_list(
            self.projects_box,
            "Projects",
            [
                (
                    str(project.get("name") or project.get("path") or "—"),
                    format_currency(float(project.get("totalCost") or 0.0), currency),
                    format_tokens(int(project.get("totalTokens") or 0)),
                )
                for project in spend.projects[:12]
            ],
        )

        models: dict[str, list[float]] = {}
        for model in spend.models:
            name = str(model.get("modelName") or model.get("name") or "—")
            cost = float(model.get("cost") or model.get("totalCost") or 0.0)
            tokens = float(model.get("totalTokens") or 0.0)
            bucket = models.setdefault(name, [0.0, 0.0])
            bucket[0] += cost
            bucket[1] += tokens
        self._rebuild_list(
            self.models_box,
            "Models",
            [
                (name, format_currency(values[0], currency), format_tokens(int(values[1])))
                for name, values in sorted(models.items(), key=lambda kv: kv[1][0], reverse=True)[:12]
            ],
        )

        self.empty_label.set_visible(not spend.daily and not spend.projects)

    def _rebuild_providers(self, spend: SpendSummary) -> None:
        """One row per provider that has local usage data."""
        for child in list(iter_children(self.providers_box)):
            self.providers_box.remove(child)
        if not spend.providers:
            return

        label = Gtk.Label(label="By provider")
        label.add_css_class("cb-section-label")
        label.set_halign(Gtk.Align.START)
        self.providers_box.append(label)

        currency = spend.currency or "USD"
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

            if entry.priced:
                cost_text = format_currency(entry.cost, currency)
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
