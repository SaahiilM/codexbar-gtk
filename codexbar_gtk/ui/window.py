"""Main dashboard window."""

from __future__ import annotations

from datetime import datetime, timezone

from gi.repository import Adw, Gtk

from .. import currency
from ..controller import AppState
from ..format import format_countdown, format_currency, format_percent, format_updated
from . import icon_names
from .cards import ProviderCard, StatTile
from .sessions import SessionsView
from .spend import SpendView
from .util import iter_children


class MainWindow(Adw.ApplicationWindow):
    """Usage dashboard, agent sessions and the Usage & Spend view."""

    def __init__(self, application: Adw.Application, prefs, history=None) -> None:
        super().__init__(application=application)
        self.prefs = prefs
        self.history = history
        self.set_title("CodexBar")
        self.set_default_size(980, 720)
        self.set_size_request(560, 460)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="CodexBar")
        header.pack_start(title)

        self.refresh_button = Gtk.Button()
        self.refresh_button.set_tooltip_text("Refresh")
        self.refresh_icon = Gtk.Image.new_from_icon_name(
            icon_names.themed_icon(*icon_names.REFRESH)
        )
        self.refresh_spinner = Gtk.Spinner()
        self.refresh_spinner.set_visible(False)
        self.refresh_button.set_child(self.refresh_icon)
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
        usage_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        usage_page.set_vexpand(True)
        usage_scroller = Gtk.ScrolledWindow()
        usage_scroller.set_vexpand(True)
        usage_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        usage_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        usage_content.set_vexpand(True)
        usage_content.set_size_request(720, -1)
        usage_content.add_css_class("cb-dash-grid")

        self.overview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.overview.add_css_class("cb-overview")
        self.overview_title = Gtk.Label(label="CodexBar")
        self.overview_title.add_css_class("cb-overview-title")
        self.overview_title.set_halign(Gtk.Align.START)
        self.overview.append(self.overview_title)
        self.overview_sub = Gtk.Label(label="Waiting for provider data…")
        self.overview_sub.add_css_class("cb-overview-sub")
        self.overview_sub.set_halign(Gtk.Align.START)
        self.overview.append(self.overview_sub)
        usage_content.append(self.overview)

        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        tiles.set_homogeneous(True)
        self.providers_tile = StatTile(
            "Providers", icon=icon_names.themed_icon(*icon_names.PROVIDERS)
        )
        self.highest_tile = StatTile(
            "Highest usage", icon=icon_names.themed_icon(*icon_names.HIGHEST)
        )
        self.credits_tile = StatTile(
            "Credits", icon=icon_names.themed_icon(*icon_names.CREDITS)
        )
        self.spend_tile = StatTile(
            "Local spend", icon=icon_names.themed_icon(*icon_names.SPEND)
        )
        for tile in (self.providers_tile, self.highest_tile, self.credits_tile, self.spend_tile):
            tiles.append(tile)
        usage_content.append(tiles)

        # A vertical list of full width cards reads better than a grid and
        # matches the popover layout of the macOS app.
        self.flow = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.flow.set_hexpand(True)
        self.flow.set_margin_top(24)
        usage_content.append(self.flow)

        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.empty_box.set_margin_top(40)
        self.empty_label = Gtk.Label(
            label="No providers are enabled yet.\n"
            "Turn one on in Settings → Providers to start tracking your quota."
        )
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_justify(Gtk.Justification.CENTER)
        self.empty_box.append(self.empty_label)
        empty_button = Gtk.Button(label="Open Settings")
        empty_button.add_css_class("suggested-action")
        empty_button.set_halign(Gtk.Align.CENTER)
        empty_button.connect("clicked", lambda _b: self.show_settings())
        self.empty_box.append(empty_button)
        usage_content.append(self.empty_box)

        usage_scroller.set_child(self._centered(usage_content))
        usage_page.append(usage_scroller)
        self.view_stack.add_titled_with_icon(
            usage_page, "usage", "Usage", icon_names.themed_icon(*icon_names.USAGE)
        )

        # ---- sessions page ----------------------------------------------
        self.sessions_view = SessionsView()
        sessions_scroller = Gtk.ScrolledWindow()
        sessions_scroller.set_vexpand(True)
        sessions_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sessions_scroller.set_child(self._centered(self.sessions_view))
        self.view_stack.add_titled_with_icon(
            sessions_scroller, "sessions", "Sessions", icon_names.themed_icon(*icon_names.SESSIONS)
        )

        # ---- spend page ------------------------------------------------
        self.spend_view = SpendView(prefs)
        spend_scroller = Gtk.ScrolledWindow()
        spend_scroller.set_vexpand(True)
        spend_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        spend_scroller.set_child(self._centered(self.spend_view))
        self.view_stack.add_titled_with_icon(
            spend_scroller, "spend", "Usage & Spend", icon_names.themed_icon(*icon_names.SPEND)
        )

        toolbar.set_content(self.view_stack)

        self._refresh_requested = False

    def _centered(self, child: Gtk.Widget) -> Gtk.Widget:
        """Keep the content column readable instead of stretching it wide."""
        clamp = Adw.Clamp()
        clamp.set_maximum_size(720)
        clamp.set_tightening_threshold(560)
        clamp.set_child(child)
        return clamp

    # -- actions ----------------------------------------------------------

    def show_page(self, name: str) -> None:
        """Switch to one of the pages: usage, sessions or spend."""
        try:
            self.view_stack.set_visible_child_name(name)
        except Exception:
            pass

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
        work_days = int(self.prefs.get("weeklyProgressWorkDays") or 5)
        tick_appearance = str(self.prefs.get("workdayTickAppearance") or "subtle")
        burndown = bool(self.prefs.get("quotaBurndownEnabled", True))

        providers = state.providers
        self.empty_box.set_visible(not providers)

        for provider in providers:
            card = ProviderCard(
                provider,
                show_used=show_used,
                reset_style=reset_style,
                show_pace=show_pace,
                thresholds=thresholds,
                show_identity=show_identity,
                history=self.history,
                work_days=work_days,
                tick_appearance=tick_appearance,
                burndown=burndown,
                preferred_currency=str(
                    self.prefs.get("preferredCurrencyCode") or "auto"
                ),
            )
            card.set_hexpand(True)
            self.flow.append(card)

        self._update_overview(state)

        highest = max((p.max_used_percent for p in providers), default=0.0)
        credits = sum(p.credits_remaining or 0.0 for p in providers if p.credits_remaining)
        self.providers_tile.set_value(str(len(providers)))
        self.highest_tile.set_value(format_percent(highest) if providers else "—")
        self.credits_tile.set_value(f"{credits:,.0f}" if credits else "—")

        spend = state.spend
        if spend is not None:
            amount, code = self._converted(spend.total_cost, spend.currency)
            self.spend_tile.set_value(
                format_currency(amount, code),
                spend.history_label or "",
            )
        else:
            self.spend_tile.set_value("—")

        self.spend_view.update(spend)
        self.sessions_view.update(state.sessions)

        if state.refreshing:
            self.refresh_icon.set_visible(False)
            self.refresh_spinner.set_visible(True)
            self.refresh_spinner.start()
        else:
            self.refresh_spinner.stop()
            self.refresh_spinner.set_visible(False)
            self.refresh_icon.set_visible(True)

    def _converted(self, amount: float, source: str | None) -> tuple[float, str]:
        """Apply the preferred display currency, falling back to the source unit."""
        source = (source or "USD").upper()
        preferred = str(self.prefs.get("preferredCurrencyCode") or "auto").strip().upper()
        if preferred in ("", "AUTO") or preferred == source or not currency.requires_live_rates(preferred):
            return amount, source
        converted = currency.convert(amount, source, preferred)
        return (converted, preferred) if converted is not None else (amount, source)

    def _update_overview(self, state: AppState) -> None:
        """A one line summary of how the quota situation looks right now."""
        now = datetime.now(timezone.utc)
        providers = [p for p in state.providers if not p.has_error]

        if not providers:
            self.overview_title.set_text("Nothing to track yet")
            self.overview_sub.set_text("Enable a provider in Settings → Providers")
            return

        highest = max(providers, key=lambda p: p.max_used_percent)
        resets = []
        for provider in providers:
            for window in provider.windows:
                if window.resets_at:
                    resets.append((window.resets_at, provider.display_name, window.title))
        resets.sort(key=lambda item: item[0])

        thresholds = list(self.prefs.get("quotaWarningThresholds") or [80, 95])
        critical = max(thresholds) if thresholds else 95
        if highest.max_used_percent >= critical:
            headline = f"{highest.display_name} is running low"
        elif highest.max_used_percent >= (min(thresholds) if thresholds else 50):
            headline = f"{highest.display_name} is picking up usage"
        else:
            headline = "Everything is within limits"

        details = []
        if resets:
            when, provider_name, title = resets[0]
            countdown = format_countdown(when, now)
            if countdown:
                details.append(f"next reset: {title.lower()} in {countdown}")
        if state.last_updated:
            stamp = datetime.fromtimestamp(state.last_updated, tz=timezone.utc)
            updated = format_updated(stamp, now)
            if updated:
                details.append(f"updated {updated}")
        self.overview_title.set_text(headline)
        self.overview_sub.set_text(" · ".join(details))

    def tick(self) -> None:
        now = datetime.now(timezone.utc)
        for child in iter_children(self.flow):
            if isinstance(child, ProviderCard):
                child.refresh(now)
