"""Application entry point: wires the controller, tray, popover and windows."""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import APP_ID, currency, display_string
from ..cli import CodexBarCLI
from ..controller import Controller, automatic_tray_selection
from ..format import compact_window_label
from ..prefs import Preferences
from ..startup import wait_for_display
from ..updates import PROJECT_URL, check_latest_version, version_key
from ..version import BUILD, SHORT_VERSION
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
        cli = CodexBarCLI(
            str(self.prefs.get("cliPath") or "") or None,
            timezone=str(self.prefs.get("costUsageBucketTimeZone") or "") or None,
        )
        self.controller = Controller(self.prefs, cli)
        # Mirrors the macOS bundle's marketing version and build pair.
        self.set_version(display_string())

        self.main_window: MainWindow | None = None
        self.settings_window: SettingsWindow | None = None
        self.popup: PopupWindow | None = None
        self.tray = TrayIcon(
            on_activate=self._on_tray_activate,
            on_context_menu=self._show_tray_context_menu,
        )
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
        currency.shared().ensure_rates(
            str(self.prefs.get("preferredCurrencyCode") or "auto")
        )

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
        if "--about" in self.extra_args:
            self._open_about()
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
            self.main_window = MainWindow(
                self,
                self.prefs,
                self.controller.history,
                on_open_settings=self._open_settings,
            )
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
                on_check_updates=self._check_for_updates,
                on_restart=self._restart,
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
        if self.popup is not None:
            self.popup.hide()
        window = self._ensure_main_window()
        # GTK4's present() already raises the window; raise_() was removed.
        window.present()

    def _open_settings(self) -> None:
        window = self._ensure_settings_window()
        window.present()

    def _open_about(self) -> None:
        window = self._ensure_settings_window()
        window.show_about()

    def _toggle_popup(self) -> None:
        popup = self._ensure_popup()
        popup.toggle()
        if popup.get_visible() and self.prefs.get("refreshAllProvidersOnMenuOpen", True):
            self._refresh_now()

    def _on_tray_activate(self) -> None:
        self._toggle_popup()

    def _show_tray_context_menu(self) -> None:
        """Show the action panel for SNI hosts that delegate ContextMenu to apps."""
        popup = self._ensure_popup()
        if not popup.get_visible():
            popup.toggle()
        if self.prefs.get("refreshAllProvidersOnMenuOpen", True):
            self._refresh_now()

    def _quit(self) -> None:
        self.controller.stop()
        self.quit()

    def _restart(self) -> None:
        """Restart through the installed user unit, or re-exec in dev runs."""
        if os.environ.get("INVOCATION_ID"):
            try:
                subprocess.Popen(
                    ["systemctl", "--user", "restart", "codexbar-gtk"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
            except OSError:
                pass
        self.controller.stop()
        os.execv(sys.executable, [sys.executable, "-m", "codexbar_gtk", *sys.argv[1:]])

    def _check_for_updates(self) -> None:
        """Compare this build with the public VERSION marker without blocking GTK."""
        parent = self.get_active_window() or self.main_window or self.settings_window
        dialog = Adw.MessageDialog.new(parent, "Checking for updates…", "Contacting GitHub…")
        dialog.add_response("open", "Open project")
        dialog.add_response("close", "Close")
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("close")
        dialog.connect("response", self._on_update_check_response)
        dialog.present()

        def check() -> None:
            try:
                latest = check_latest_version()
                result: tuple[str, tuple[str, int] | str] = ("ok", latest)
            except Exception as error:
                result = ("error", str(error))
            GLib.idle_add(self._finish_update_check, dialog, result)

        threading.Thread(target=check, name="codexbar-update-check", daemon=True).start()

    def _finish_update_check(self, dialog, result: tuple[str, tuple[str, int] | str]) -> bool:
        status, value = result
        if status != "ok" or not isinstance(value, tuple):
            error = value if isinstance(value, str) else "unexpected update-check response"
            dialog.set_heading("Couldn’t check for updates")
            dialog.set_body(
                f"The update check failed: {error}\n\n"
                "You can still open the project page and check manually."
            )
        else:
            latest_version, latest_build = value
            current_key = version_key(SHORT_VERSION, BUILD)
            latest_key = version_key(latest_version, latest_build)
            current_display = display_string()
            latest_display = f"{latest_version} ({latest_build})"
            if latest_key > current_key:
                dialog.set_heading(f"Update available: {latest_display}")
                dialog.set_body(
                    f"You have {current_display}. This client is distributed as source; "
                    "pull the latest changes in your checkout, run "
                    "./scripts/install.sh --no-autostart, then restart the app."
                )
            elif latest_key < current_key:
                dialog.set_heading("This build is newer than the public version")
                dialog.set_body(f"Installed: {current_display}\nPublic main: {latest_display}")
            else:
                dialog.set_heading("You’re up to date")
                dialog.set_body(f"CodexBar GTK {current_display} is the latest public build.")
        return False

    @staticmethod
    def _on_update_check_response(dialog, response: str) -> None:
        if response == "open":
            Gtk.show_uri(dialog, PROJECT_URL, Gdk.CURRENT_TIME)
        dialog.close()

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
            self.tray.update(
                "codexbar-gtk",
                "CodexBar GTK",
                "Provider data unavailable\nUse Refresh to check again.",
            )
            self.tray.set_menu(
                [
                    ("Show usage panel", self._toggle_popup),
                    ("Refresh", self._refresh_now),
                    ("Open Dashboard", self._open_dashboard),
                    (None, None),
                    ("Check for updates…", self._check_for_updates),
                    ("Restart CodexBar", self._restart),
                    ("Settings…", self._open_settings),
                    (None, None),
                    ("Quit CodexBar", self._quit),
                ]
            )
            self.tray.register()
            return

        source = str(self.prefs.get("unifiedIconSource") or "highest")
        tray_window = None
        if source == "automatic":
            automatic = automatic_tray_selection(providers)
            if automatic is not None:
                highest, tray_window = automatic
            else:
                highest = max(providers, key=lambda p: p.max_used_percent)
        elif source == "first":
            highest = providers[0]
        else:
            highest = max(providers, key=lambda p: p.max_used_percent)
        used_percent = tray_window.used_percent if tray_window is not None else highest.max_used_percent
        tray_title = highest.display_name
        if tray_window is not None:
            # Auto tokens identify the selected window once several exist (#4743):
            # "Codex 5h 84%" instead of a bare "Codex" that could mean any lane.
            same_title = [
                w for w in highest.windows if w.title == tray_window.title and not w.is_placeholder
            ]
            if len(same_title) == 1:
                if label := compact_window_label(tray_window.title, tray_window.window_minutes):
                    tray_title = f"{highest.display_name} {label}"
        level = min(9, int(used_percent / 10.0))
        accent = highest.accent_color
        levels = icons.write_icons(accent)
        icon_name = levels.get(level) or "codexbar-gtk"

        style = str(self.prefs.get("menuBarIconStyle") or "meter")
        if style == "iconPercent":
            pixmap = icons.render_percent_pixmap(
                used_percent,
                accent,
                (highest.display_name or "?")[0],
            )
            icon_name = ""
        else:
            pixmap = icons.render_meter_pixmap(level, accent)
        tooltip_rows = [f"Provider: {highest.display_name}"]
        for provider in providers[:4]:
            if provider.windows:
                values = " · ".join(
                    f"{window.title}: {window.used_percent:.0f}%"
                    if window.usage_known
                    else f"{window.title}: unavailable"
                    for window in provider.windows
                )
                tooltip_rows.append(
                    values if provider is highest else f"{provider.display_name}: {values}"
                )
            elif provider is highest:
                tooltip_rows.append("Usage unavailable")
            else:
                tooltip_rows.append(f"{provider.display_name}: unavailable")
        if len(providers) > 4:
            tooltip_rows.append(f"+ {len(providers) - 4} more providers")
        body = "\n".join(tooltip_rows)
        tray_title = f"CodexBar GTK · {tray_title}"
        # Hosts read the properties once, when the item appears, so the
        # tooltip has to be complete before the item is published.
        self.tray.update(icon_name, tray_title, body, pixmap)

        rows_option = str(self.prefs.get("switcherRowsOption") or "progress")
        entries: list = []
        for provider in providers:
            if rows_option == "progress":
                used = max((w.used_percent for w in provider.windows), default=0.0)
                windows_at_used = [w for w in provider.windows if w.used_percent == used]
                used_window = next(
                    (w for w in windows_at_used if not w.is_placeholder),
                    windows_at_used[0] if windows_at_used else None,
                )
                filled = int(round(used / 10))
                bar = "▇" * filled + "░" * (10 - filled)
                summary = f"{bar} {used:.0f}%"
                if used_window is not None:
                    # A bare bar does not reveal whether it tracks the session or
                    # the weekly lane, so name the window once several exist.
                    same_title = [
                        w for w in provider.windows if w.title == used_window.title and not w.is_placeholder
                    ]
                    if len(same_title) == 1:
                        if label := compact_window_label(
                            used_window.title, used_window.window_minutes
                        ):
                            summary = f"{bar} {label} {used:.0f}%"
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
            (None, None),
            ("Check for updates…", self._check_for_updates),
            ("Restart CodexBar", self._restart),
            ("Settings…", self._open_settings),
            (f"About CodexBar GTK {display_string()}", self._open_about),
            (None, None),
            ("Quit CodexBar", self._quit),
        ]
        self.tray.set_menu(entries)
        # The icon is in place now, so the item can be published to the host.
        self.tray.register()

    def _check_notifications(self, state) -> None:
        for provider_id, window_key, used, message in self.controller.quota_events(state):
            self._notify("Quota warning", message)
        for event in self.controller.predictive_pace_events(state):
            self._notify(event["title"], event["body"], id=event["id"])
        for event in self.controller.credit_expiry_events(state):
            self._notify(event["title"], event["body"], id=event["id"])

    def _notify(self, title: str, message: str, id: str | None = None) -> None:
        notification = Gio.Notification.new(title)
        notification.set_body(message)
        notification.set_priority(Gio.NotificationPriority.NORMAL)
        key = id or f"{abs(hash(message)) % 100000}"
        self.send_notification(f"codexbar-{key}", notification)

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


DISPLAY_WAIT_SECONDS = 30.0


def ensure_display(timeout: float = DISPLAY_WAIT_SECONDS) -> bool:
    """Wait for the graphical session, then report whether GTK can start.

    The systemd unit deliberately starts before plasmashell so the tray item is
    registered in time. At login the Wayland/X11 display can still be a moment
    away, so retry instead of raising ``Gtk couldn't be initialized``.
    """
    def display_is_ready() -> bool:
        # In GTK4, init_check() may succeed even when Gdk has no display
        # connection, so check the actual default display as well.
        return Gtk.init_check() and Gdk.Display.get_default() is not None

    return wait_for_display(display_is_ready, timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if not ensure_display():
        print(
            "codexbar-gtk: no graphical display found; start it inside a desktop session",
            file=sys.stderr,
        )
        return 1
    app = CodexBarApp()
    return app.run(argv)
