"""Preferences window.

Mirrors the macOS app's settings panes: General, Providers, Display,
Notifications, Usage & Spend and Advanced.
"""

from __future__ import annotations

import os
import sys

from gi.repository import Adw, Gio, GLib, Gtk

from .. import providers as provider_meta

AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "codexbar-gtk.desktop")

REFRESH_LABELS = [
    ("Manual", "manual"),
    ("Every minute", "1m"),
    ("Every 2 minutes", "2m"),
    ("Every 5 minutes", "5m"),
    ("Every 15 minutes", "15m"),
    ("Every 30 minutes", "30m"),
    ("Adaptive", "adaptive"),
]

RESET_LABELS = [
    ("Countdown", "countdown"),
    ("Absolute time", "absolute"),
    ("Both", "both"),
]

SOURCE_LABELS = [
    ("Automatic", "auto"),
    ("Web", "web"),
    ("CLI", "cli"),
    ("OAuth", "oauth"),
    ("API", "api"),
]


def _combo_row(title: str, options: list[tuple[str, str]], current: str, on_change) -> Adw.ComboRow:
    row = Adw.ComboRow(title=title)
    model = Gtk.StringList()
    for label, _value in options:
        model.append(label)
    row.set_model(model)
    for index, (_label, value) in enumerate(options):
        if value == current:
            row.set_selected(index)
            break
    row.connect("notify::selected", lambda r, _p: on_change(options[r.get_selected()][1]))
    return row


def _switch_row(title: str, subtitle: str, active: bool, on_change) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    switch.set_active(active)
    switch.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    row.add_suffix(switch)
    row.set_activatable_widget(switch)
    return row


class SettingsWindow(Adw.PreferencesWindow):
    """The preferences window of the Linux app."""

    def __init__(self, application: Adw.Application, prefs, controller) -> None:
        super().__init__(application=application)
        self.prefs = prefs
        self.controller = controller
        self.set_title("CodexBar Settings")
        self.set_default_size(760, 640)
        self.set_modal(False)
        self.search_enabled = True

        self.add(self._general_page())
        self.add(self._providers_page())
        self.add(self._menu_bar_page())
        self.add(self._display_page())
        self.add(self._notifications_page())
        self.add(self._spend_page())
        self.add(self._hooks_page())
        self.add(self._plugins_page())
        self.add(self._advanced_page())

    # -- pages ------------------------------------------------------------

    def _general_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")

        refresh_group = Adw.PreferencesGroup(title="Refreshing")
        refresh_group.add(
            _combo_row(
                "Refresh interval",
                REFRESH_LABELS,
                str(self.prefs.get("refreshFrequency")),
                self._set_refresh,
            )
        )
        refresh_group.add(
            _switch_row(
                "Refresh when the popover opens",
                "Fetch fresh data every time the panel is shown",
                bool(self.prefs.get("refreshAllProvidersOnMenuOpen")),
                lambda value: self.prefs.set("refreshAllProvidersOnMenuOpen", value),
            )
        )
        refresh_group.add(
            _switch_row(
                "Provider status checks",
                "Poll provider status pages for incident badges",
                bool(self.prefs.get("statusChecksEnabled")),
                lambda value: self.prefs.set("statusChecksEnabled", value),
            )
        )
        page.add(refresh_group)

        startup = Adw.PreferencesGroup(title="Startup")
        startup.add(
            _switch_row(
                "Start at login",
                "Launch CodexBar when you sign in",
                bool(self.prefs.get("launchAtLogin")),
                self._set_launch_at_login,
            )
        )
        startup.add(
            _switch_row(
                "Show the popover on start",
                "Open the compact panel when the app launches",
                bool(self.prefs.get("showPopupOnStart")),
                lambda value: self.prefs.set("showPopupOnStart", value),
            )
        )
        page.add(startup)

        general = Adw.PreferencesGroup(title="General")
        currency_row = _combo_row(
            "Preferred currency",
            [("Automatic", "auto"), ("USD", "USD"), ("EUR", "EUR"), ("GBP", "GBP"), ("INR", "INR"), ("JPY", "JPY")],
            str(self.prefs.get("preferredCurrencyCode")),
            lambda value: self.prefs.set("preferredCurrencyCode", value),
        )
        general.add(currency_row)
        page.add(general)
        return page

    def _providers_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Providers", icon_name="network-server-symbolic")

        group = Adw.PreferencesGroup(
            title="Providers",
            description="Enable the providers you use. Credentials are managed by the codexbar CLI.",
        )

        entries = []
        try:
            entries = self.controller.cli.config_providers()
        except Exception:
            entries = []

        for entry in entries:
            name = entry.display_name or provider_meta.display_name(entry.provider_id)
            # Adwaita rows interpret their title as markup.
            name = GLib.markup_escape_text(name)
            row = Adw.ExpanderRow(title=name, subtitle=entry.provider_id)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.set_active(entry.enabled)
            switch.connect("notify::active", lambda s, _p, pid=entry.provider_id: self._toggle_provider(pid, s.get_active()))
            row.add_suffix(switch)

            source_row = _combo_row(
                "Source",
                SOURCE_LABELS,
                "auto",
                lambda value, pid=entry.provider_id: self._set_provider_source(pid, value),
            )
            row.add_row(source_row)

            if entry.provider_id in ("claude", "codex"):
                sign_in_row = Adw.ActionRow(
                    title="Sign in with the provider CLI",
                    subtitle=(
                        "Run claude auth login --claudeai in a terminal"
                        if entry.provider_id == "claude"
                        else "Run codex login in a terminal"
                    ),
                )
                sign_in_row.set_activatable(True)
                sign_in_row.connect(
                    "activated", lambda _r, pid=entry.provider_id: self._sign_in(pid)
                )
                row.add_row(sign_in_row)

            api_row = Adw.PasswordEntryRow(title="API key")
            api_row.set_show_apply_button(True)
            api_row.connect("apply", lambda r, pid=entry.provider_id: self._set_api_key(pid, r.get_text()))
            row.add_row(api_row)

            group.add(row)

        page.add(group)
        return page

    def _menu_bar_page(self) -> Adw.PreferencesPage:
        """Tray appearance — the equivalent of the macOS "Menu Bar" pane."""
        page = Adw.PreferencesPage(title="Menu Bar", icon_name="view-continuous-symbolic")

        icon_group = Adw.PreferencesGroup(title="Tray icon")
        icon_group.add(
            _combo_row(
                "Icon style",
                [("Usage meter", "meter"), ("Icon and percentage", "iconPercent")],
                str(self.prefs.get("menuBarIconStyle")),
                lambda value: self.prefs.set("menuBarIconStyle", value),
            )
        )
        icon_group.add(
            _combo_row(
                "Icon shows",
                [
                    ("Provider with the highest usage", "highest"),
                    ("First enabled provider", "first"),
                ],
                str(self.prefs.get("unifiedIconSource")),
                lambda value: self.prefs.set("unifiedIconSource", value),
            )
        )
        icon_group.add(
            _combo_row(
                "Provider rows in the menu",
                [("Usage bar", "progress"), ("Quota details", "details")],
                str(self.prefs.get("switcherRowsOption")),
                lambda value: self.prefs.set("switcherRowsOption", value),
            )
        )
        icon_group.add(
            _switch_row(
                "Show the tray icon",
                "Display the usage meter in the system tray",
                bool(self.prefs.get("showTray")),
                lambda value: self.prefs.set("showTray", value),
            )
        )
        page.add(icon_group)
        return page

    def _display_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Display", icon_name="video-display-symbolic")

        usage = Adw.PreferencesGroup(title="Usage")
        usage.add(
            _switch_row(
                "Show used instead of remaining",
                "Meters fill up as the quota is consumed",
                bool(self.prefs.get("usageBarsShowUsed")),
                lambda value: self.prefs.set("usageBarsShowUsed", value),
            )
        )
        usage.add(
            _combo_row(
                "Reset time format",
                RESET_LABELS,
                str(self.prefs.get("resetTimesOption")),
                lambda value: self.prefs.set("resetTimesOption", value),
            )
        )
        usage.add(
            _switch_row(
                "Show pace indicators",
                "Compare the current burn against the expected pace",
                bool(self.prefs.get("paceVisible")),
                lambda value: self.prefs.set("paceVisible", value),
            )
        )
        usage.add(
            _switch_row(
                "Hide account details",
                "Do not show e-mail addresses or plan names",
                bool(self.prefs.get("hidePersonalInfo")),
                lambda value: self.prefs.set("hidePersonalInfo", value),
            )
        )
        page.add(usage)

        weekly = Adw.PreferencesGroup(
            title="Weekly window",
            description="Show how far through the working days the weekly quota is.",
        )
        weekly.add(
            _spin_row(
                "Working days per week",
                1,
                7,
                int(self.prefs.get("weeklyProgressWorkDays") or 5),
                lambda value: self.prefs.set("weeklyProgressWorkDays", value),
            )
        )
        weekly.add(
            _combo_row(
                "Workday tick",
                [("Hidden", "hidden"), ("Subtle", "subtle"), ("High contrast", "highContrast")],
                str(self.prefs.get("workdayTickAppearance")),
                lambda value: self.prefs.set("workdayTickAppearance", value),
            )
        )
        weekly.add(
            _switch_row(
                "Project the usage at reset",
                "Extrapolate the burndown from the recorded history",
                bool(self.prefs.get("quotaBurndownEnabled", True)),
                lambda value: self.prefs.set("quotaBurndownEnabled", value),
            )
        )
        page.add(weekly)

        warnings = Adw.PreferencesGroup(
            title="Quota warnings",
            description="Percentages at which a provider is flagged as a warning or critical.",
        )
        warnings.add(
            _spin_row(
                "Warning threshold",
                5,
                99,
                list(self.prefs.get("quotaWarningThresholds") or [80, 95])[0],
                lambda value: self._set_threshold("quotaWarningThresholds", 0, value),
            )
        )
        warnings.add(
            _spin_row(
                "Critical threshold",
                5,
                99,
                (list(self.prefs.get("quotaWarningThresholds") or [80, 95]) + [95])[1],
                lambda value: self._set_threshold("quotaWarningThresholds", 1, value),
            )
        )
        page.add(warnings)

        tray = Adw.PreferencesGroup(title="Tray")
        tray.add(
            _switch_row(
                "Show the tray icon",
                "Display the usage meter in the system tray",
                bool(self.prefs.get("showTray")),
                lambda value: self.prefs.set("showTray", value),
            )
        )
        page.add(tray)
        return page

    def _notifications_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Notifications", icon_name="preferences-system-notifications-symbolic")

        group = Adw.PreferencesGroup(title="Quota notifications")
        group.add(
            _switch_row(
                "Session quota notifications",
                "Notify when a session window is exhausted",
                bool(self.prefs.get("sessionQuotaNotificationsEnabled")),
                lambda value: self.prefs.set("sessionQuotaNotificationsEnabled", value),
            )
        )
        group.add(
            _switch_row(
                "Quota warning notifications",
                "Notify when a provider crosses a warning threshold",
                bool(self.prefs.get("quotaWarningNotificationsEnabled")),
                lambda value: self.prefs.set("quotaWarningNotificationsEnabled", value),
            )
        )
        group.add(
            _switch_row(
                "Limit reset notifications",
                "Notify when a window resets",
                bool(self.prefs.get("limitResetNotificationsEnabled")),
                lambda value: self.prefs.set("limitResetNotificationsEnabled", value),
            )
        )

        test_row = Adw.ActionRow(title="Send a test notification")
        test_row.set_subtitle("Check that desktop notifications work")
        test_row.set_activatable(True)
        test_row.connect("activated", lambda _r: self._test_notification())
        group.add(test_row)
        page.add(group)
        return page

    def _spend_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Usage & Spend", icon_name="document-open-recent-symbolic")

        group = Adw.PreferencesGroup(title="Local cost scanning")
        group.add(
            _switch_row(
                "Enable local cost scans",
                "Read Codex and Claude transcripts to estimate spend",
                bool(self.prefs.get("costUsageEnabled")),
                lambda value: self.prefs.set("costUsageEnabled", value),
            )
        )
        group.add(
            _switch_row(
                "Show comparison periods",
                "Compare the current period against the previous one",
                bool(self.prefs.get("costComparisonPeriodsEnabled")),
                lambda value: self.prefs.set("costComparisonPeriodsEnabled", value),
            )
        )
        page.add(group)
        return page

    def _hooks_page(self) -> Adw.PreferencesPage:
        """Hook rules — external commands run on quota events."""
        page = Adw.PreferencesPage(title="Hooks", icon_name="application-x-executable-symbolic")

        group = Adw.PreferencesGroup(
            title="Hooks",
            description=(
                "Run your own commands when a quota event happens. "
                "Rules live in the shared CodexBar config."
            ),
        )
        try:
            hooks = self.controller.cli.hooks()
        except Exception:
            hooks = {}
        enabled = bool(hooks.get("enabled"))
        group.add(
            _switch_row(
                "Enable hooks",
                "Fire the configured rules on quota and provider events",
                enabled,
                self._toggle_hooks,
            )
        )
        page.add(group)

        rules = hooks.get("events") or []
        rule_group = Adw.PreferencesGroup(title="Rules")
        if not rules:
            empty = Adw.ActionRow(title="No rules configured")
            empty.set_subtitle(
                "Add a rule to the shared CodexBar config to run a command on an event"
            )
            rule_group.add(empty)
        else:
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                row = Adw.ActionRow(
                    title=str(rule.get("event") or "event"),
                    subtitle=str(rule.get("executable") or ""),
                )
                state = Gtk.Label(label="on" if rule.get("enabled") else "off")
                state.add_css_class("cb-kv-key")
                state.set_valign(Gtk.Align.CENTER)
                row.add_suffix(state)
                rule_group.add(row)
        page.add(rule_group)
        return page

    def _plugins_page(self) -> Adw.PreferencesPage:
        """User supplied provider plugins."""
        page = Adw.PreferencesPage(title="Plugins", icon_name="application-x-addon-symbolic")

        group = Adw.PreferencesGroup(
            title="Plugins",
            description="JavaScript plugins that add extra providers.",
        )
        try:
            plugins = self.controller.cli.plugins()
        except Exception:
            plugins = []
        if not plugins:
            empty = Adw.ActionRow(title="No plugins installed")
            empty.set_subtitle("Install plugins into the CodexBar plugin directory")
            group.add(empty)
        else:
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    continue
                row = Adw.ActionRow(
                    title=str(plugin.get("id") or plugin.get("name") or "plugin"),
                    subtitle=str(plugin.get("version") or plugin.get("provider") or ""),
                )
                group.add(row)
        page.add(group)
        return page

    def _sign_in(self, provider_id: str) -> None:
        """Sign in to a provider.

        Claude Code uses a browser flow, so the CLI runs in a pseudo terminal
        inside a dialog — the same approach the macOS app takes.
        """
        if provider_id == "claude":
            from .login_dialog import LoginDialog

            app = self.get_application()
            dialog = LoginDialog(app, provider_id)
            dialog.start()
            dialog.present()
            return

        self._open_terminal_login(provider_id)

    def _open_terminal_login(self, provider_id: str) -> None:
        """Open a terminal with the provider's login command."""
        command = "claude auth login --claudeai" if provider_id == "claude" else "codex login"
        terminal = None
        for candidate in ("konsole", "gnome-terminal", "xterm", "kitty", "alacritty"):
            from shutil import which

            found = which(candidate)
            if found:
                terminal = found
                break
        if terminal is None:
            self._notify(f"Run this in a terminal: {command}")
            return
        import subprocess

        try:
            subprocess.Popen([terminal, "-e", command], start_new_session=True)
            self._notify(f"Started {command} in a terminal")
        except OSError as exc:
            self._notify(f"Could not open a terminal: {exc}")

    def _toggle_hooks(self, value: bool) -> None:
        try:
            self.controller.cli.set_hooks_enabled(value)
            self._notify(f"Hooks {'enabled' if value else 'disabled'}")
        except Exception as exc:
            self._notify(f"Could not change hooks: {exc}")

    def _advanced_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Advanced", icon_name="applications-graphics-symbolic")

        cli_group = Adw.PreferencesGroup(
            title="CodexBar CLI",
            description="The desktop app drives the codexbar command line tool.",
        )
        cli_row = Adw.EntryRow(title="CLI path")
        cli_row.set_text(str(self.prefs.get("cliPath") or ""))
        cli_row.connect("apply", lambda row: self.prefs.set("cliPath", row.get_text().strip()))
        cli_group.add(cli_row)

        version_row = Adw.ActionRow(title="CLI version")
        version_row.set_subtitle(self.controller.cli.version())
        cli_group.add(version_row)
        page.add(cli_group)

        data_group = Adw.PreferencesGroup(title="Preferences")
        export_row = Adw.ActionRow(title="Export preferences", subtitle="Save as JSON")
        export_row.set_activatable(True)
        export_row.connect("activated", lambda _r: self._export_preferences())
        data_group.add(export_row)

        import_row = Adw.ActionRow(title="Import preferences", subtitle="Load from JSON")
        import_row.set_activatable(True)
        import_row.connect("activated", lambda _r: self._import_preferences())
        data_group.add(import_row)

        reset_row = Adw.ActionRow(title="Reset all preferences")
        reset_row.set_activatable(True)
        reset_row.connect("activated", lambda _r: self._reset_preferences())
        data_group.add(reset_row)
        page.add(data_group)
        return page

    # -- handlers ---------------------------------------------------------

    def _set_refresh(self, value: str) -> None:
        self.prefs.set("refreshFrequency", value)

    def _set_threshold(self, key: str, index: int, value: int) -> None:
        thresholds = list(self.prefs.get(key) or [80, 95])
        while len(thresholds) <= index:
            thresholds.append(95)
        thresholds[index] = value
        self.prefs.set(key, thresholds)

    def _set_launch_at_login(self, value: bool) -> None:
        self.prefs.set("launchAtLogin", value)
        try:
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            if value:
                executable = os.path.abspath(sys.argv[0]) if sys.argv else "codexbar-gtk"
                with open(AUTOSTART_FILE, "w", encoding="utf-8") as handle:
                    handle.write(
                        "[Desktop Entry]\n"
                        "Type=Application\n"
                        "Name=CodexBar\n"
                        f"Exec={executable}\n"
                        "X-GNOME-Autostart-enabled=true\n"
                        "Terminal=false\n"
                    )
            elif os.path.exists(AUTOSTART_FILE):
                os.remove(AUTOSTART_FILE)
        except OSError:
            pass

    def _toggle_provider(self, provider_id: str, enabled: bool) -> None:
        try:
            if enabled:
                self.controller.cli.enable_provider(provider_id)
            else:
                self.controller.cli.disable_provider(provider_id)
        except Exception as exc:
            self._notify(f"Could not update {provider_id}: {exc}")

    def _set_provider_source(self, provider_id: str, source: str) -> None:
        try:
            self.controller.cli.set_source(provider_id, source)
            self._notify(f"{provider_id} source set to {source}")
        except Exception as exc:
            self._notify(f"Could not set source: {exc}")

    def _set_api_key(self, provider_id: str, key: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        try:
            self.controller.cli.set_api_key(provider_id, key)
            self._notify(f"API key saved for {provider_id}")
        except Exception as exc:
            self._notify(f"Could not save API key: {exc}")

    def _export_preferences(self) -> None:
        import json

        path = os.path.join(
            os.path.expanduser("~"), ".config", "codexbar-gtk", "preferences-export.json"
        )
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.prefs.export_document(), handle, indent=2)
            self._notify(f"Exported to {path}")
        except OSError as exc:
            self._notify(f"Export failed: {exc}")

    def _import_preferences(self) -> None:
        import json

        path = os.path.join(
            os.path.expanduser("~"), ".config", "codexbar-gtk", "preferences-export.json"
        )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                self.prefs.import_document(json.load(handle))
            self._notify("Preferences imported")
        except (OSError, json.JSONDecodeError) as exc:
            self._notify(f"Import failed: {exc}")

    def _reset_preferences(self) -> None:
        self.prefs.reset()
        self._notify("Preferences reset")

    def _notify(self, message: str) -> None:
        window = self.get_application().main_window
        if window is not None:
            window.toast(message)

    def _test_notification(self) -> None:
        app = self.get_application()
        app._notify("CodexBar", "This is a test notification from CodexBar.")


def _spin_row(title: str, lower: int, upper: int, value: int, on_change) -> Adw.ActionRow:
    """A numeric preference row (Adw.SpinRow when available, else a spin button)."""
    if hasattr(Adw, "SpinRow"):
        row = Adw.SpinRow(title=title)
        row.set_range(lower, upper)
        row.set_value(value)
        row.connect("notify::value", lambda r, _p: on_change(int(r.get_value())))
        return row

    row = Adw.ActionRow(title=title)
    adjustment = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=1)
    spin = Gtk.SpinButton(adjustment=adjustment, valign=Gtk.Align.CENTER)
    spin.connect("value-changed", lambda s: on_change(int(s.get_value())))
    row.add_suffix(spin)
    row.set_activatable_widget(spin)
    return row
