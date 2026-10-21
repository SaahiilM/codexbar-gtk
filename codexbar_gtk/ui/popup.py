"""The compact popover — the macOS menu bar experience on Linux.

A small always-on-top panel that lists every enabled provider with its quota
meters, reset countdowns, credits and spend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from gi.repository import Gdk, Gtk

from ..controller import AppState
from .cards import ProviderCard
from .util import iter_children


class PopupContent(Gtk.Box):
    """The contents of the compact panel.

    Kept separate from the window so it can be embedded elsewhere (and rendered
    by the preview tool).
    """

    def __init__(
        self,
        on_refresh: Callable[[], None],
        on_open_dashboard: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("cb-popup")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("cb-popup-header")
        title = Gtk.Label(label="CodexBar")
        title.add_css_class("cb-popup-title")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)

        self.status_label = Gtk.Label(label="")
        self.status_label.add_css_class("cb-provider-subtitle")
        self.status_label.set_valign(Gtk.Align.CENTER)
        header.append(self.status_label)

        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_button.add_css_class("flat")
        refresh_button.set_tooltip_text("Refresh now")
        refresh_button.connect("clicked", lambda _b: on_refresh())
        header.append(refresh_button)

        dashboard_button = Gtk.Button(icon_name="view-fullscreen-symbolic")
        dashboard_button.add_css_class("flat")
        dashboard_button.set_tooltip_text("Open dashboard")
        dashboard_button.connect("clicked", lambda _b: on_open_dashboard())
        header.append(dashboard_button)
        self.append(header)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_max_content_height(560)
        self.scroller.add_css_class("cb-popup-scroll")
        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.scroller.set_child(self.cards_box)
        self.append(self.scroller)

        self.empty_label = Gtk.Label(label="No providers enabled")
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_margin_top(2)
        footer.set_margin_bottom(6)
        footer.set_margin_start(10)
        footer.set_margin_end(10)

        settings_button = Gtk.Button(label="Settings")
        settings_button.add_css_class("flat")
        settings_button.connect("clicked", lambda _b: on_open_settings())
        footer.append(settings_button)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)

        quit_button = Gtk.Button(label="Quit")
        quit_button.add_css_class("flat")
        quit_button.connect("clicked", lambda _b: on_quit())
        footer.append(quit_button)
        self.append(footer)

    # -- content ----------------------------------------------------------

    def update(self, state: AppState, prefs) -> None:
        for child in iter_children(self.cards_box):
            self.cards_box.remove(child)

        providers = [p for p in state.providers if not p.has_error or p.windows]
        errors = [p for p in state.providers if p.has_error and not p.windows]

        self.empty_label.set_visible(not providers and not errors)

        show_used = bool(prefs.get("usageBarsShowUsed", True))
        reset_style = str(prefs.get("resetTimesOption", "countdown"))
        show_pace = bool(prefs.get("paceVisible", True))
        show_identity = not bool(prefs.get("hidePersonalInfo", False))
        thresholds = list(prefs.get("quotaWarningThresholds") or [80, 95])

        for provider in providers:
            self.cards_box.append(
                ProviderCard(
                    provider,
                    show_used=show_used,
                    reset_style=reset_style,
                    show_pace=show_pace,
                    thresholds=thresholds,
                    show_identity=show_identity,
                )
            )

        for provider in errors:
            error_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            error_box.add_css_class("cb-card")
            name = Gtk.Label(label=provider.display_name)
            name.add_css_class("cb-provider-name")
            error_box.append(name)
            message = Gtk.Label(label=provider.error or "Unavailable")
            message.add_css_class("cb-error")
            message.set_ellipsize(3)
            message.set_hexpand(True)
            error_box.append(message)
            self.cards_box.append(error_box)

        if state.refreshing:
            self.status_label.set_text("refreshing…")
        elif state.last_error:
            self.status_label.set_text("error")
            self.status_label.set_tooltip_text(state.last_error)
        else:
            count = len(state.providers)
            self.status_label.set_text(f"{count} provider" if count == 1 else f"{count} providers")

    def tick(self) -> None:
        """Refresh the countdown labels without refetching."""
        now = datetime.now(timezone.utc)
        for child in iter_children(self.cards_box):
            if isinstance(child, ProviderCard):
                child.refresh(now)


class PopupWindow(Gtk.Window):
    """Floating provider panel."""

    def __init__(
        self,
        on_refresh: Callable[[], None],
        on_open_dashboard: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__()
        self.set_title("CodexBar")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(380, 320)
        self.set_hide_on_close(False)

        self.content = PopupContent(
            on_refresh, on_open_dashboard, on_open_settings, on_quit
        )
        self.set_child(self.content)

        self.connect("notify::is-active", self._on_active_changed)
        self.connect("map", self._on_map)

    # -- lifecycle --------------------------------------------------------

    def _on_active_changed(self, *_args) -> None:
        # Dismiss the panel when the user clicks somewhere else.
        if self.get_property("is-active") is False and self.get_visible():
            self.hide()

    def _on_map(self, *_args) -> None:
        self._position()

    def _position(self) -> None:
        """Anchor the panel to the top-right corner of the current monitor.

        GTK4 removed the window positioning API, so this is best effort: it works
        on X11/XWayland when the backend still exposes ``move`` and is a no-op on
        pure Wayland, where the compositor decides.
        """
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = display.get_primary_monitor()
        if monitor is None:
            monitors = display.get_monitors()
            monitor = monitors[0] if monitors else None
        if monitor is None:
            return
        geometry = monitor.get_geometry()
        width, height = self.get_width(), self.get_height()
        if width <= 1:
            width = 380
        if height <= 1:
            height = 320
        x = geometry.x + geometry.width - width - 12
        y = geometry.y + 8
        self.set_default_size(width, height)
        if hasattr(self, "move"):
            try:
                self.move(x, y)
            except Exception:
                pass

    def toggle(self) -> None:
        if self.get_visible():
            self.hide()
        else:
            self.present()
            self._position()

    # -- content ----------------------------------------------------------

    def update(self, state: AppState, prefs) -> None:
        self.content.update(state, prefs)

    def tick(self) -> None:
        self.content.tick()
