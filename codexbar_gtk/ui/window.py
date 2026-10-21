"""Main dashboard window."""

from __future__ import annotations

from datetime import datetime, timezone

from gi.repository import Adw, Gio, Gtk

from ..controller import AppState
from ..format import format_currency, format_percent
from .cards import ProviderCard, StatTile
from .spend import SpendView
from .util import iter_children


class MainWindow(Adw.ApplicationWindow):
    """Usage dashboard plus the Usage & Spend view."""

    def __init__(self, application: Adw.Application, prefs) -> None:
        super().__init__(application=application)
        self.prefs = prefs
        self.set_title("CodexBar")
        self.set_default_size(920, 680)
        self.set_size_request(520, 420)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)

        header = Adw.HeaderBar()
        self.refresh_button = Gtk.Button()
        self.refresh_button.set_tooltip_text("Refresh")
        self.refresh_spinner = Gtk.Spinner()
        self.refresh_spinner.set_visible(False)
        self.refresh_button.set_child(self.refresh_spinner)
        self.refresh_button.connect("clicked", lambda _b: self.request_refresh())
        header.pack_end(self.refresh_button)

        settings_button = Gtk.Button(icon_name="preferences-system-symbolic")
        settings_button.set_tooltip_text("Settings")
        settings_button.connect("clicked", lambda _b: self.show_settings())
        header.pack_end(settings_button)

        self.switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)
        toolbar.add_top_bar(header)

        # ---- usage page ------------------------------------------------
        usage_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        usage_page.set_vexpand(True)
        usage_scroller = Gtk.ScrolledWindow()
        usage_scroller.set_vexpand(True)
        usage_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        usage_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        usage_content.set_vexpand(True)
        usage_content.add_css_class("cb-dash-grid")

        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tiles.set_homogeneous(True)
        self.providers_tile = StatTile("Providers")
        self.highest_tile = StatTile("Highest usage")
        self.credits_tile = StatTile("Credits")
        self.spend_tile = StatTile("Local spend")
        for tile in (self.providers_tile, self.highest_tile, self.credits_tile, self.spend_tile):
            tiles.append(tile)
        usage_content.append(tiles)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_column_spacing(10)
        self.flow.set_row_spacing(10)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(3)
        self.flow.set_margin_top(14)
        usage_content.append(self.flow)

        self.empty_label = Gtk.Label(label="No providers enabled.\nEnable one in Settings → Providers.")
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_justify(Gtk.Justification.CENTER)
        usage_content.append(self.empty_label)

        usage_scroller.set_child(usage_content)
        usage_page.append(usage_scroller)
        self.view_stack.add_titled(usage_page, "usage", "Usage")

        # ---- spend page ------------------------------------------------
        self.spend_view = SpendView()
        spend_scroller = Gtk.ScrolledWindow()
        spend_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        spend_scroller.set_child(self.spend_view)
        self.view_stack.add_titled(spend_scroller, "spend", "Usage & Spend")

        toolbar.set_content(self.view_stack)

        self._refresh_requested = False

    # -- actions ----------------------------------------------------------

    def request_refresh(self) -> None:
        self._refresh_requested = True

    def consume_refresh_request(self) -> bool:
        requested = self._refresh_requested
        self._refresh_requested = False
        return requested

    def show_settings(self) -> None:
        window = self.get_application().settings_window
        if window is not None:
            window.present()

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))

    # -- updates ----------------------------------------------------------

    def update(self, state: AppState) -> None:
        for child in list(iter_children(self.flow)):
            self.flow.remove(child)

        show_used = bool(self.prefs.get("usageBarsShowUsed", True))
        reset_style = str(self.prefs.get("resetTimesOption", "countdown"))
        show_pace = bool(self.prefs.get("paceVisible", True))
        show_identity = not bool(self.prefs.get("hidePersonalInfo", False))
        thresholds = list(self.prefs.get("quotaWarningThresholds") or [80, 95])

        providers = state.providers
        self.empty_label.set_visible(not providers)

        for provider in providers:
            card = ProviderCard(
                provider,
                show_used=show_used,
                reset_style=reset_style,
                show_pace=show_pace,
                thresholds=thresholds,
                show_identity=show_identity,
            )
            child = Gtk.FlowBoxChild()
            child.set_child(card)
            child.set_valign(Gtk.Align.START)
            self.flow.append(child)

        highest = max((p.max_used_percent for p in providers), default=0.0)
        credits = sum(p.credits_remaining or 0.0 for p in providers if p.credits_remaining)
        self.providers_tile.set_value(str(len(providers)))
        self.highest_tile.set_value(format_percent(highest))
        self.credits_tile.set_value(f"{credits:,.0f}" if credits else "—")

        spend = state.spend
        if spend is not None:
            self.spend_tile.set_value(
                format_currency(spend.total_cost, spend.currency),
                spend.history_label or "",
            )
        else:
            self.spend_tile.set_value("—")

        self.spend_view.update(spend)

        if state.refreshing:
            self.refresh_spinner.set_visible(True)
            self.refresh_spinner.start()
        else:
            self.refresh_spinner.stop()
            self.refresh_spinner.set_visible(False)

    def tick(self) -> None:
        now = datetime.now(timezone.utc)
        for child in iter_children(self.flow):
            card = child.get_child()
            if isinstance(card, ProviderCard):
                card.refresh(now)
