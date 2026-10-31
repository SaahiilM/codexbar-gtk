"""Preferences window.

Mirrors the macOS app's settings panes: General, Providers, Display,
Notifications, Usage & Spend and Advanced.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import display_string
from .. import providers as provider_meta
from ..login import terminal_command_argv
from . import icon_names

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


def _combo_row(
    title: str,
    options: list[tuple[str, str]],
    current: str,
    on_change,
    subtitle: str | None = None,
    handler_sink: list[int] | None = None,
) -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, subtitle=subtitle or "")
    model = Gtk.StringList()
    for label, _value in options:
        model.append(label)
    row.set_model(model)
    for index, (_label, value) in enumerate(options):
        if value == current:
            row.set_selected(index)
            break
    handler = row.connect(
        "notify::selected", lambda r, _p: on_change(options[r.get_selected()][1])
    )
    if handler_sink is not None:
        handler_sink.append(handler)
    return row


def _switch_row(title: str, subtitle: str, active: bool, on_change) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    switch.set_active(active)
    switch.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    row.add_suffix(switch)
    row.set_activatable_widget(switch)
    return row


def _replace_rows(
    group: Adw.PreferencesGroup,
    old_rows: list[Gtk.Widget],
    rows: list[Gtk.Widget],
) -> None:
    for row in old_rows:
        group.remove(row)
    old_rows.clear()
    for row in rows:
        group.add(row)
        old_rows.append(row)


class SettingsWindow(Adw.PreferencesWindow):
    """The preferences window of the Linux app."""

    def __init__(
        self,
        application: Adw.Application,
        prefs,
        controller,
        on_show_tray_changed: Callable[[bool], None] | None = None,
        on_open_dashboard: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(application=application)
        self.prefs = prefs
        self.controller = controller
        self._on_show_tray_changed = on_show_tray_changed
        self._on_open_dashboard = on_open_dashboard
        self._cli_load_generation = 0
        self._version_rows: list[Adw.ActionRow] = []
        self._launch_at_login_switch: Gtk.Switch | None = None
        self._launch_at_login_handler: int | None = None
        self._cli_path_entry: Adw.EntryRow | None = None
        self._timezone_row: Adw.ComboRow | None = None
        self._timezone_handler: int | None = None
        self._accepted_cli_path = ""
        self._accepted_timezone = ""
        self.set_title("CodexBar Settings")
        self.set_default_size(1000, 720)
        self.set_modal(False)
        self.search_enabled = True

        self.general_page = self._general_page()
        self.providers_page = self._providers_page()
        self.advanced_page = self._advanced_page()
        self.add(self.general_page)
        self.add(self.providers_page)
        self.add(self._menu_bar_page())
        self.add(self._display_page())
        self.add(self._notifications_page())
        self.add(self._spend_page())
        self.add(self._hooks_page())
        self.add(self._plugins_page())
        self.add(self.advanced_page)
        self.acknowledgements_page = self._acknowledgements_page()
        self.add(self.acknowledgements_page)
        self.about_page = self._about_page()
        self.add(self.about_page)
        self._reload_cli_settings()

    # -- pages ------------------------------------------------------------

    def _general_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")

        if self._on_open_dashboard is not None:
            navigation = Adw.PreferencesGroup(title="Navigation")
            row = Adw.ActionRow(
                title="Return to dashboard",
                subtitle="Usage quotas, active sessions and spending",
            )
            button = Gtk.Button(label="Open")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda _button: self._on_open_dashboard())
            row.add_suffix(button)
            row.set_activatable_widget(button)
            navigation.add(row)
            page.add(navigation)

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
        page.add(refresh_group)

        startup = Adw.PreferencesGroup(title="Startup")
        launch_row = Adw.ActionRow(
            title="Start at login",
            subtitle="Launch CodexBar when you sign in",
        )
        launch_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        launch_switch.set_active(False)
        self._launch_at_login_switch = launch_switch
        self._launch_at_login_handler = launch_switch.connect(
            "notify::active", lambda switch, _param: self._set_launch_at_login(switch.get_active())
        )
        launch_row.add_suffix(launch_switch)
        launch_row.set_activatable_widget(launch_switch)
        startup.add(launch_row)
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
        currency_options = [("Automatic (as reported)", "auto")]
        currency_options += [
            (f"{code} ({symbol})", code)
            for code, symbol, _rate in self.controller.catalog_async()
        ]
        currency_row = _combo_row(
            "Preferred currency",
            currency_options,
            str(self.prefs.get("preferredCurrencyCode")),
            self._set_currency,
        )
        self._currency_row = currency_row
        general.add(currency_row)
        page.add(general)
        return page

    def _providers_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Providers", icon_name=icon_names.themed_icon(*icon_names.PROVIDERS))

        group = Adw.PreferencesGroup(
            title="Providers",
            description="Enable the providers you use. Credentials are managed by the codexbar CLI.",
        )

        self._providers_group = group
        self._providers_loading = Adw.ActionRow(title="Loading providers…")
        group.add(self._providers_loading)
        self._provider_rows = [self._providers_loading]
        page.add(group)
        return page

    def _populate_providers(self, entries, error: str | None = None) -> None:
        def field(entry, name, default=None):
            return entry.get(name, default) if isinstance(entry, dict) else getattr(entry, name, default)

        rows: list[Gtk.Widget] = []
        if error:
            row = Adw.ActionRow(title="Could not load providers")
            row.set_subtitle(error)
            rows.append(row)
        elif not entries:
            rows.append(Adw.ActionRow(title="No providers found"))
        for entry in ([] if error else entries):
            provider_id = str(field(entry, "provider_id", ""))
            name = field(entry, "display_name") or provider_meta.display_name(provider_id)
            # Adwaita rows interpret their title as markup.
            name = GLib.markup_escape_text(name)
            row = Adw.ExpanderRow(title=name, subtitle=provider_id)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.set_active(field(entry, "enabled", False))
            switch.connect(
                "notify::active",
                lambda s, _p, pid=provider_id: self._toggle_provider(
                    pid, s.get_active()
                ),
            )
            row.add_suffix(switch)

            source_row = _combo_row(
                "Source",
                SOURCE_LABELS,
                "auto",
                lambda value, pid=provider_id: self._set_provider_source(
                    pid, value
                ),
            )
            row.add_row(source_row)

            if provider_id in ("claude", "codex"):
                sign_in_row = Adw.ActionRow(
                    title="Sign in with the provider CLI",
                    subtitle=(
                        "Run claude auth login --claudeai in a terminal"
                        if provider_id == "claude"
                        else "Run codex login in a terminal"
                    ),
                )
                sign_in_row.set_activatable(True)
                sign_in_row.connect(
                    "activated", lambda _r, pid=provider_id: self._sign_in(pid)
                )
                row.add_row(sign_in_row)

            api_row = Adw.PasswordEntryRow(title="API key")
            api_row.set_show_apply_button(True)
            api_row.connect(
                "apply",
                lambda r, pid=provider_id: self._set_api_key(pid, r.get_text()),
            )
            row.add_row(api_row)

            rows.append(row)
        _replace_rows(self._providers_group, self._provider_rows, rows)

    def _menu_bar_page(self) -> Adw.PreferencesPage:
        """Tray appearance — the equivalent of the macOS "Menu Bar" pane."""
        page = Adw.PreferencesPage(title="Menu Bar", icon_name=icon_names.themed_icon(*icon_names.MENU_BAR))

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
                    ("The quota running out soonest", "automatic"),
                    ("Provider with the highest usage", "highest"),
                    ("First enabled provider", "first"),
                ],
                str(self.prefs.get("unifiedIconSource")),
                lambda value: self.prefs.set("unifiedIconSource", value),
                subtitle=(
                    "Highest usage compares quota percentages. For a provider "
                    "without a quota, choose First enabled provider."
                ),
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
                self._set_show_tray,
            )
        )
        page.add(icon_group)
        return page

    def _display_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Display", icon_name=icon_names.themed_icon(*icon_names.DISPLAY))

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

        return page

    def _notifications_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Notifications", icon_name=icon_names.themed_icon(*icon_names.NOTIFICATIONS))

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
                "Notify when a window resets and when a reset credit is about to expire",
                bool(self.prefs.get("limitResetNotificationsEnabled")),
                lambda value: self.prefs.set("limitResetNotificationsEnabled", value),
            )
        )
        group.add(
            _switch_row(
                "Pace warnings",
                "Warn for Codex and Claude when the current pace may run out before the reset",
                bool(self.prefs.get("predictivePaceNotificationsEnabled")),
                lambda value: self.prefs.set("predictivePaceNotificationsEnabled", value),
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
        page = Adw.PreferencesPage(title="Usage & Spend", icon_name=icon_names.themed_icon(*icon_names.SPEND))

        group = Adw.PreferencesGroup(title="Local cost scanning")
        group.add(
            _switch_row(
                "Enable local cost scans",
                "Read Codex and Claude transcripts to estimate spend",
                bool(self.prefs.get("costUsageEnabled")),
                lambda value: self.prefs.set("costUsageEnabled", value),
            )
        )
        page.add(group)

        zone_group = Adw.PreferencesGroup(
            title="Daily buckets",
            description=(
                "Daily usage uses a fixed time zone. Changing it may move usage "
                "to a different day."
            ),
        )
        timezone_handlers: list[int] = []
        self._accepted_timezone = str(self.prefs.get("costUsageBucketTimeZone") or "")
        self._timezone_row = _combo_row(
            "Statistics time zone",
            self._time_zone_options(),
            self._accepted_timezone,
            self._set_time_zone,
            handler_sink=timezone_handlers,
        )
        self._timezone_handler = timezone_handlers[0]
        zone_group.add(self._timezone_row)
        page.add(zone_group)
        return page

    def _hooks_page(self) -> Adw.PreferencesPage:
        """Hook rules — external commands run on quota events."""
        page = Adw.PreferencesPage(title="Hooks", icon_name=icon_names.themed_icon(*icon_names.HOOKS))

        group = Adw.PreferencesGroup(
            title="Hooks",
            description=(
                "Run your own commands when a quota event happens. "
                "Rules live in the shared CodexBar config."
            ),
        )
        self._hooks_group = group
        hooks_loading = Adw.ActionRow(title="Loading hooks…")
        group.add(hooks_loading)
        self._hooks_rows = [hooks_loading]
        page.add(group)

        self._hooks_rules_group = Adw.PreferencesGroup(title="Rules")
        rules_loading = Adw.ActionRow(title="Loading rules…")
        self._hooks_rules_group.add(rules_loading)
        self._hooks_rule_rows = [rules_loading]
        page.add(self._hooks_rules_group)
        return page

    def _populate_hooks(self, hooks: dict) -> None:
        enabled = bool(hooks.get("enabled"))
        hook_row = _switch_row(
            "Enable hooks",
            "Fire the configured rules on quota and provider events",
            enabled,
            self._toggle_hooks,
        )
        rule_rows: list[Gtk.Widget] = []

        rules = hooks.get("events") or []
        if not rules:
            empty = Adw.ActionRow(title="No rules configured")
            empty.set_subtitle(
                "Add a rule to the shared CodexBar config to run a command on an event"
            )
            rule_rows.append(empty)
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
                rule_rows.append(row)
        _replace_rows(self._hooks_group, self._hooks_rows, [hook_row])
        _replace_rows(self._hooks_rules_group, self._hooks_rule_rows, rule_rows)

    def _plugins_page(self) -> Adw.PreferencesPage:
        """User supplied provider plugins."""
        page = Adw.PreferencesPage(title="Plugins", icon_name=icon_names.themed_icon(*icon_names.PLUGINS))

        group = Adw.PreferencesGroup(
            title="Plugins",
            description="JavaScript plugins that add extra providers.",
        )
        self._plugins_group = group
        plugins_loading = Adw.ActionRow(title="Loading plugins…")
        group.add(plugins_loading)
        self._plugin_rows = [plugins_loading]
        page.add(group)
        return page

    def _populate_plugins(self, plugins: list[dict]) -> None:
        rows: list[Gtk.Widget] = []
        if not plugins:
            empty = Adw.ActionRow(title="No plugins installed")
            empty.set_subtitle("Install plugins into the CodexBar plugin directory")
            rows.append(empty)
        else:
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    continue
                row = Adw.ActionRow(
                    title=str(plugin.get("id") or plugin.get("name") or "plugin"),
                    subtitle=str(plugin.get("version") or plugin.get("provider") or ""),
                )
                rows.append(row)
        _replace_rows(self._plugins_group, self._plugin_rows, rows)

    def _reload_cli_settings(self) -> None:
        """Load Rust-owned settings DTOs away from the GTK thread."""
        self._cli_load_generation += 1
        generation = self._cli_load_generation

        def load() -> None:
            try:
                snapshot = self.controller.settings_snapshot()
            except Exception:
                snapshot = {"load_error": "settings_unavailable"}
            try:
                version = (
                    self.controller.state.cli_version
                    if self.controller.uses_rust_controller
                    else self.controller.cli.version()
                )
            except Exception:
                version = "unknown"
            GLib.idle_add(self._apply_cli_settings, generation, snapshot, version)

        threading.Thread(target=load, name="codexbar-settings-load", daemon=True).start()

    @staticmethod
    def _settings_error_text(error: dict | None) -> str | None:
        if not isinstance(error, dict):
            return None
        category = error.get("category")
        operation = error.get("operation")
        if not isinstance(category, str) or not isinstance(operation, str):
            return "settings_unavailable"
        return f"{category} ({operation})"

    def _apply_cli_settings(self, generation: int, snapshot: dict, version: str) -> bool:
        if generation != self._cli_load_generation:
            return False
        if "load_error" in snapshot:
            self._populate_providers([], snapshot["load_error"])
            self._populate_hooks({})
            self._populate_plugins([])
        else:
            providers = snapshot.get("providers") or {}
            hooks = snapshot.get("hooks") or {}
            plugins = snapshot.get("plugins") or {}
            launch = snapshot.get("launch_at_login") or {}
            self._populate_providers(
                providers.get("value") or [],
                self._settings_error_text(providers.get("error")),
            )
            self._populate_hooks(hooks.get("value") or {})
            self._populate_plugins(plugins.get("value") or [])
            launch_value = launch.get("value")
            if (
                self._launch_at_login_switch is not None
                and isinstance(launch_value, dict)
                and isinstance(launch_value.get("enabled"), bool)
            ):
                handler = self._launch_at_login_handler
                if handler is not None:
                    self._launch_at_login_switch.handler_block(handler)
                self._launch_at_login_switch.set_active(launch_value["enabled"])
                if handler is not None:
                    self._launch_at_login_switch.handler_unblock(handler)
        for row in self._version_rows:
            row.set_subtitle(version or "unknown")
        return False

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
        if self.controller.uses_rust_controller and provider_id == "codex":
            def launch() -> None:
                try:
                    outcome = self.controller.launch_codex_login_terminal()
                    message = (
                        "Started Codex login in a terminal"
                        if outcome.get("launched")
                        else "Run this in a terminal: codex login"
                    )
                except Exception:
                    message = "Could not start Codex login"
                GLib.idle_add(self._finish_codex_terminal_login, message)

            threading.Thread(
                target=launch,
                name="codexbar-codex-terminal-login",
                daemon=True,
            ).start()
            return

        command = (
            ["claude", "auth", "login", "--claudeai"]
            if provider_id == "claude"
            else ["codex", "login"]
        )
        terminal = None
        for candidate in ("konsole", "gnome-terminal", "xterm", "kitty", "alacritty"):
            from shutil import which

            found = which(candidate)
            if found:
                terminal = found
                break
        if terminal is None:
            self._notify(f"Run this in a terminal: {' '.join(command)}")
            return
        import subprocess

        try:
            subprocess.Popen(
                terminal_command_argv(terminal, command), start_new_session=True
            )
            self._notify(f"Started {' '.join(command)} in a terminal")
        except OSError as exc:
            self._notify(f"Could not open a terminal: {exc}")

    def _finish_codex_terminal_login(self, message: str) -> bool:
        self._notify(message)
        return False

    def _toggle_hooks(self, value: bool) -> None:
        self._run_settings_action(
            lambda: self.controller.settings_set_hooks_enabled(value),
            f"Hooks {'enabled' if value else 'disabled'}",
            "Could not change hooks",
            on_success=self._reload_cli_settings,
        )

    def _advanced_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Advanced", icon_name=icon_names.themed_icon(*icon_names.ADVANCED))

        cli_group = Adw.PreferencesGroup(
            title="CodexBar CLI",
            description="The desktop app drives the codexbar command line tool.",
        )
        cli_row = Adw.EntryRow(title="CLI path")
        self._accepted_cli_path = str(self.prefs.get("cliPath") or "")
        cli_row.set_text(self._accepted_cli_path)
        self._cli_path_entry = cli_row
        cli_row.connect("apply", lambda row: self._set_cli_path(row.get_text().strip()))
        cli_group.add(cli_row)

        version_row = Adw.ActionRow(title="CLI version")
        version_row.set_subtitle("Loading…")
        self._version_rows.append(version_row)
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

    def _acknowledgements_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="Acknowledgements", icon_name=icon_names.themed_icon(*icon_names.ABOUT)
        )

        group = Adw.PreferencesGroup(title="Third-party software")

        dependencies = [
            ("GTK4", "GIMP Tool Kit", "LGPL 2.1+"),
            ("libadwaita", "Adwaita library", "LGPL 2.1+"),
            ("PyGObject", "GObject introspection bindings for Python", "LGPL 2.1+"),
            ("Python", "Programming language", "Python Software Foundation License"),
            ("Cairo", "2D vector graphics library", "MPL 1.1 / LGPL 2.1+"),
            ("GLib", "Core application library", "LGPL 2.1+"),
            ("dbus-python", "D-Bus bindings for Python", "MIT"),
        ]
        for name, description, licence in dependencies:
            row = Adw.ActionRow(title=name, subtitle=description)
            licence_label = Gtk.Label(label=licence)
            licence_label.add_css_class("caption")
            licence_label.set_xalign(1)
            licence_label.set_hexpand(True)
            row.add_suffix(licence_label)
            group.add(row)

        page.add(group)

        notes = Adw.ActionRow(
            title="Source code",
            subtitle="github.com/SaahiilM/codexbar-gtk",
        )
        notes.set_activatable(True)
        notes.connect(
            "activated",
            lambda _r: Gtk.show_uri(
                self, "https://github.com/SaahiilM/codexbar-gtk", Gdk.CURRENT_TIME
            ),
        )
        group.add(notes)
        return page

    def _about_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="About", icon_name=icon_names.themed_icon(*icon_names.ABOUT)
        )

        app_group = Adw.PreferencesGroup(title="CodexBar GTK")
        version_row = Adw.ActionRow(title="Version")
        version_row.set_subtitle(display_string())
        app_group.add(version_row)

        toolkit_row = Adw.ActionRow(title="Toolkit")
        toolkit_row.set_subtitle("GTK4 / libadwaita")
        app_group.add(toolkit_row)

        cli_row = Adw.ActionRow(title="CodexBar CLI")
        cli_row.set_subtitle("Loading…")
        self._version_rows.append(cli_row)
        app_group.add(cli_row)
        page.add(app_group)

        link_group = Adw.PreferencesGroup(title="Project")
        project_row = Adw.ActionRow(
            title="Source code",
            subtitle="github.com/SaahiilM/codexbar-gtk",
        )
        project_row.set_activatable(True)
        project_row.connect(
            "activated",
            lambda _r: Gtk.show_uri(
                self, "https://github.com/SaahiilM/codexbar-gtk", Gdk.CURRENT_TIME
            ),
        )
        link_group.add(project_row)
        page.add(link_group)
        return page

    def show_about(self) -> None:
        """Present the window with the About page selected."""
        self.present()
        try:
            self.set_visible_page(self.about_page)
        except Exception:
            pass

    # -- handlers ---------------------------------------------------------

    def _set_refresh(self, value: str) -> None:
        self.prefs.set("refreshFrequency", value)

    def _set_currency(self, value: str) -> None:
        self.prefs.set("preferredCurrencyCode", value)
        self.controller.ensure_rates(value)
        self._request_refresh()

    @staticmethod
    def _time_zone_options() -> list[tuple[str, str]]:
        options = [("System local time", "")]
        try:
            from zoneinfo import available_timezones

            zones = sorted(available_timezones())
        except Exception:
            zones = ["UTC"]
        options.extend((zone, zone) for zone in zones)
        return options

    def _set_time_zone(self, value: str) -> None:
        self._reconfigure_cli_settings(timezone=value)

    def _set_cli_path(self, value: str) -> None:
        self._reconfigure_cli_settings(cli_path=value.strip(), reload_settings=True)

    def _reconfigure_cli_settings(
        self,
        *,
        cli_path: str | None = None,
        timezone: str | None = None,
        reload_settings: bool = False,
    ) -> None:
        """Apply CLI configuration through the facade away from GTK."""
        def run() -> None:
            try:
                result = self.controller.settings_reconfigure_cli(
                    cli_path, timezone
                )
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            GLib.idle_add(
                self._finish_cli_reconfigure,
                result,
                error,
                reload_settings,
                cli_path,
                timezone,
            )

        threading.Thread(target=run, name="codexbar-settings-reconfigure", daemon=True).start()

    def _finish_cli_reconfigure(
        self,
        result: dict | None,
        error: str | None,
        reload_settings: bool,
        cli_path: str | None,
        timezone: str | None,
    ) -> bool:
        if error is not None or not isinstance(result, dict) or not result.get("applied"):
            self._notify(f"Could not apply CLI settings: {error or 'settings_cli_reconfigure'}")
            self._restore_cli_config_controls()
            self._reload_cli_settings()
            return False
        if cli_path is not None:
            self._accepted_cli_path = cli_path.strip()
        if timezone is not None:
            self._accepted_timezone = timezone
        self._sync_cli_config_controls()
        if result.get("refresh_queued"):
            self._notify("CLI settings applied")
        else:
            self._notify("CLI settings applied; refresh unavailable")
        if reload_settings:
            self._reload_cli_settings()
        return False

    def _restore_cli_config_controls(self) -> None:
        self._sync_cli_config_controls()

    def _sync_cli_config_controls(self) -> None:
        if self._cli_path_entry is not None:
            self._cli_path_entry.set_text(self._accepted_cli_path)
        if self._timezone_row is not None:
            for index, (_label, value) in enumerate(self._time_zone_options()):
                if value == self._accepted_timezone:
                    if self._timezone_handler is not None:
                        self._timezone_row.handler_block(self._timezone_handler)
                    self._timezone_row.set_selected(index)
                    if self._timezone_handler is not None:
                        self._timezone_row.handler_unblock(self._timezone_handler)
                    break

    def _set_show_tray(self, value: bool) -> None:
        self.prefs.set("showTray", value)
        if self._on_show_tray_changed is not None:
            self._on_show_tray_changed(value)

    def _request_refresh(self) -> None:
        app = self.get_application()
        if app is not None and hasattr(app, "_refresh_now"):
            app._refresh_now()

    def _set_threshold(self, key: str, index: int, value: int) -> None:
        thresholds = list(self.prefs.get(key) or [80, 95])
        while len(thresholds) <= index:
            thresholds.append(95)
        thresholds[index] = value
        self.prefs.set(key, thresholds)

    def _set_launch_at_login(self, value: bool) -> None:
        executable = os.path.abspath(sys.argv[0]) if sys.argv else "codexbar-gtk"
        self._run_settings_action(
            lambda: self.controller.set_launch_at_login(value, executable),
            f"Launch at login {'enabled' if value else 'disabled'}",
            "Could not change launch at login",
        )

    def _toggle_provider(self, provider_id: str, enabled: bool) -> None:
        self._run_settings_action(
            lambda: self.controller.settings_provider_action(
                "enable" if enabled else "disable", provider_id
            ),
            f"{provider_id} {'enabled' if enabled else 'disabled'}",
            f"Could not update {provider_id}",
            on_success=self._request_refresh,
        )

    def _set_provider_source(self, provider_id: str, source: str) -> None:
        self._run_settings_action(
            lambda: self.controller.settings_provider_action(
                "set-source", provider_id, source
            ),
            f"{provider_id} source set to {source}",
            "Could not set source",
            on_success=self._request_refresh,
        )

    def _set_api_key(self, provider_id: str, key: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        self._run_settings_action(
            lambda: self.controller.settings_set_api_key(provider_id, key),
            f"API key saved for {provider_id}",
            "Could not save API key",
            on_success=self._request_refresh,
        )

    def _run_settings_action(
        self,
        action: Callable[[], object],
        success_message: str,
        failure_message: str,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        """Run a CLI mutation away from the UI thread and report its result."""
        def run() -> None:
            try:
                action()
                error = None
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(
                self._finish_cli_action,
                success_message,
                failure_message,
                error,
                on_success,
            )

        threading.Thread(target=run, name="codexbar-settings-operation", daemon=True).start()

    def _finish_cli_action(
        self,
        success_message: str,
        failure_message: str,
        error: str | None,
        on_success: Callable[[], None] | None,
    ) -> bool:
        if error is None:
            self._notify(success_message)
            if on_success is not None:
                on_success()
        else:
            self._notify(f"{failure_message}: {error}")
            self._reload_cli_settings()
        return False

    def _choose_preferences_file(self, *, exporting: bool) -> None:
        action = Gtk.FileChooserAction.SAVE if exporting else Gtk.FileChooserAction.OPEN
        title = "Export preferences" if exporting else "Import preferences"
        accept = "Save" if exporting else "Open"
        chooser = Gtk.FileChooserNative.new(title, self, action, accept, "Cancel")
        if exporting:
            chooser.set_current_name("preferences-export.json")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON documents")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)

        def response(dialog, response_id) -> None:
            if response_id == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_file()
                path = selected.get_path() if selected is not None else None
                if path:
                    if exporting:
                        self._run_settings_action(
                            lambda: self.controller.preferences_export_to(path),
                            f"Exported preferences to {os.path.basename(path)}",
                            "Preferences export failed",
                        )
                    else:
                        self._run_settings_action(
                            lambda: self.controller.preferences_import_from(path),
                            "Preferences imported",
                            "Preferences import failed",
                            on_success=self._request_refresh,
                        )
            dialog.destroy()

        chooser.connect("response", response)
        chooser.show()

    def _export_preferences(self) -> None:
        self._choose_preferences_file(exporting=True)

    def _import_preferences(self) -> None:
        self._choose_preferences_file(exporting=False)

    def _reset_preferences(self) -> None:
        self._run_settings_action(
            self.controller.preferences_reset,
            "Preferences reset",
            "Preferences reset failed",
            on_success=self._request_refresh,
        )

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
