"""Application entry point: wires the controller, tray, popover and windows."""

from __future__ import annotations

import os
import sys

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_ID, __version__
from ..cli import CodexBarCLI
from ..controller import Controller
from ..prefs import Preferences
from . import icons
from .popup import PopupWindow
from .settings import SettingsWindow
from .style import apply_theme
from .tray import TrayIcon
from .window import MainWindow

TICK_SECONDS = 20


class CodexBarApp(Adw.Application):
    """The GTK4/libadwaita front-end for CodexBar."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.prefs = Preferences()
        cli = CodexBarCLI(str(self.prefs.get("cliPath") or "") or None)
        self.controller = Controller(self.prefs, cli)

        self.main_window: MainWindow | None = None
        self.settings_window: SettingsWindow | None = None
        self.popup: PopupWindow | None = None
        self.tray = TrayIcon(on_activate=self._on_tray_activate)
        self._icon_levels: dict[int, str] = {}
        self._pending_refresh = False
        self.extra_args: list[str] = []
        self._show_panel_when_ready = False

    # -- lifecycle --------------------------------------------------------

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        apply_theme()
        self._install_actions()
        # This is a tray application: keep running even without a window.
        self.hold()

        self.controller.subscribe(self._on_state)
        self.controller.start()

        if self.prefs.get("showTray", True):
            self.tray.start()
            # The controller may have produced data before the tray existed.
            self._apply_state(self.controller.state)

        GLib.timeout_add_seconds(TICK_SECONDS, self._tick)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handle our own flags.

        ``Gio.Application`` forwards the command line to the primary instance,
        so ``codexbar-gtk --settings`` also works while the app is already
        running in the tray.
        """
        argv = list(command_line.get_arguments())
        self.extra_args = [arg for arg in argv[1:] if arg != "--"]
        self.activate()
        return 0

    def do_activate(self) -> None:
        if "--settings" in self.extra_args:
            self._open_settings()
            return
        if "--panel" in self.extra_args:
            # Wait for the first refresh so the panel is shown with content.
            self._show_panel_when_ready = True
            return
        if "--page" in self.extra_args:
            index = self.extra_args.index("--page")
            page = self.extra_args[index + 1] if index + 1 < len(self.extra_args) else "usage"
            window = self._ensure_main_window()
            window.show_page(page)
            window.present()
            return
        window = self._ensure_main_window()
        window.present()

    def do_shutdown(self) -> None:
        self.controller.stop()
        self.release()
        Adw.Application.do_shutdown(self)

    # -- windows ----------------------------------------------------------

    def _ensure_main_window(self) -> MainWindow:
        if self.main_window is None:
            self.main_window = MainWindow(self, self.prefs, self.controller.history)
            self.main_window.connect("close-request", self._on_main_closed)
        return self.main_window

    def _ensure_settings_window(self) -> SettingsWindow:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self, self.prefs, self.controller)
        return self.settings_window

    def _on_main_closed(self, *_args) -> bool:
        if self.main_window is not None:
            self.main_window.hide()
        return True  # keep the app alive in the tray

    def _ensure_popup(self) -> PopupWindow:
        if self.popup is None:
            self.popup = PopupWindow(
                on_refresh=self._refresh_now,
                on_open_dashboard=self._open_dashboard,
                on_open_settings=self._open_settings,
                on_quit=self._quit,
                history=self.controller.history,
            )
        return self.popup

    # -- actions ----------------------------------------------------------

    def _install_actions(self) -> None:
        actions = [
            ("refresh", self._refresh_now),
            ("dashboard", self._open_dashboard),
            ("settings", self._open_settings),
            ("popup", self._toggle_popup),
            ("quit", self._quit),
        ]
        for name, handler in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, fn=handler: fn())
            self.add_action(action)

        self.set_accels_for_action("app.refresh", ["<Primary>r"])
        self.set_accels_for_action("app.quit", ["<Primary>q"])
        self.set_accels_for_action("app.popup", ["<Primary>space"])

    def _refresh_now(self) -> None:
        if self._pending_refresh:
            return
        self._pending_refresh = True
        GLib.idle_add(self._do_refresh)

    def _do_refresh(self) -> bool:
        self._pending_refresh = False
        GLib.idle_add(lambda: (self.controller.refresh(), False)[1])
        return False

    def _open_dashboard(self) -> None:
        window = self._ensure_main_window()
        window.present()
        window.raise_()

    def _open_settings(self) -> None:
        window = self._ensure_settings_window()
        window.present()

    def _toggle_popup(self) -> None:
        popup = self._ensure_popup()
        popup.toggle()
        if popup.get_visible() and self.prefs.get("refreshAllProvidersOnMenuOpen", True):
            self._refresh_now()

    def _on_tray_activate(self) -> None:
        self._toggle_popup()

    def _quit(self) -> None:
        self.controller.stop()
        self.quit()

    # -- state ------------------------------------------------------------

    def _on_state(self, state) -> None:
        GLib.idle_add(lambda: (self._apply_state(state), False)[1])

    def _apply_state(self, state) -> None:
        if self._show_panel_when_ready and state.providers:
            self._show_panel_when_ready = False
            self._toggle_popup()
        if self.popup is not None:
            self.popup.update(state, self.prefs)
        if self.main_window is not None:
            self.main_window.update(state)
        self._update_tray(state)
        self._check_notifications(state)

    def _update_tray(self, state) -> None:
        if not self.tray.available:
            return
        providers = [p for p in state.providers if not p.has_error]
        if not providers:
            self.tray.update("codexbar-gtk", "CodexBar", "No provider data")
            self.tray.set_menu(
                [
                    (None, None),
                    ("Show usage panel", self._toggle_popup),
                    ("Refresh", self._refresh_now),
                    ("Open Dashboard", self._open_dashboard),
                    ("Settings…", self._open_settings),
                    (None, None),
                    ("Quit CodexBar", self._quit),
                ]
            )
            self.tray.register()
            return

        source = str(self.prefs.get("unifiedIconSource") or "highest")
        if source == "first":
            chosen = providers[0]
        else:
            chosen = max(providers, key=lambda p: p.max_used_percent)
        highest = chosen
        level = min(9, int(highest.max_used_percent / 10.0))
        accent = highest.accent_color
        levels = icons.write_icons(accent)
        icon_name = levels.get(level) or "codexbar-gtk"

        style = str(self.prefs.get("menuBarIconStyle") or "meter")
        if style == "iconPercent":
            pixmap = icons.render_percent_pixmap(
                highest.max_used_percent,
                accent,
                (highest.display_name or "?")[0],
            )
            icon_name = ""
        else:
            pixmap = icons.render_meter_pixmap(level, accent)
        body = "\n".join(
            f"{p.display_name}: " + ", ".join(
                f"{w.title} {w.used_percent:.0f}%" for w in p.windows
            )
            for p in providers[:4]
        )
        # Hosts read the properties once, when the item appears, so the
        # tooltip has to be complete before the item is published.
        self.tray.update(icon_name, highest.display_name, body, pixmap)

        rows_option = str(self.prefs.get("switcherRowsOption") or "progress")
        entries: list = []
        for provider in providers:
            if rows_option == "progress":
                used = max((w.used_percent for w in provider.windows), default=0.0)
                filled = int(round(used / 10))
                bar = "▇" * filled + "░" * (10 - filled)
                summary = f"{bar} {used:.0f}%"
            else:
                summary = " · ".join(
                    f"{w.title} {w.used_percent:.0f}%" for w in provider.windows
                )
            entries.append((f"{provider.display_name} — {summary}", self._open_dashboard))
        entries += [
            (None, None),
            ("Show usage panel", self._toggle_popup),
            ("Refresh", self._refresh_now),
            ("Open Dashboard", self._open_dashboard),
            ("Settings…", self._open_settings),
            (None, None),
            ("Quit CodexBar", self._quit),
        ]
        self.tray.set_menu(entries)
        # The icon is in place now, so the item can be published to the host.
        self.tray.register()

    def _check_notifications(self, state) -> None:
        for provider_id, window_key, used, message in self.controller.quota_events(state):
            self._notify("Quota warning", message)

    def _notify(self, title: str, message: str) -> None:
        notification = Gio.Notification.new(title)
        notification.set_body(message)
        notification.set_priority(Gio.NOTIFICATION_PRIORITY_NORMAL)
        self.send_notification(f"codexbar-{abs(hash(message)) % 100000}", notification)

    # -- ticker -----------------------------------------------------------

    def _tick(self) -> bool:
        now = GLib.get_monotonic_time()
        if self.popup is not None and self.popup.get_visible():
            self.popup.tick()
        if self.main_window is not None and self.main_window.get_visible():
            self.main_window.tick()
        if self.main_window is not None and self.main_window.consume_refresh_request():
            self._refresh_now()
        return True


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    app = CodexBarApp()
    return app.run(argv)
