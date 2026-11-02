//! Native preferences panes backed only by the serialized Rust settings actor.

use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    fs,
    path::PathBuf,
    rc::Rc,
    sync::Arc,
    time::Duration,
};

use adw::prelude::*;
use codexbar_backend::{
    login::{LoginActor, LoginRequest, LoginUiEvent},
    settings::{
        HookSettings, PluginInfo, ProviderAction, ProviderSource, SettingsActor, SettingsError,
        SettingsOperation, SettingsRefreshStatus, SettingsRequest, SettingsResponse,
        SettingsResult, SettingsSnapshot,
    },
};
use codexbar_core::preferences::PreferencesStore;
use gio::prelude::*;
use gtk::prelude::*;
use libadwaita as adw;
use serde_json::{json, Value};

enum PreferenceControl {
    Switch {
        widget: gtk::Switch,
        handler: glib::SignalHandlerId,
    },
    Combo {
        widget: adw::ComboRow,
        handler: glib::SignalHandlerId,
        values: Vec<String>,
    },
    Number {
        widget: gtk::SpinButton,
        handler: glib::SignalHandlerId,
        array_index: Option<usize>,
    },
    Text {
        widget: adw::EntryRow,
        handler: glib::SignalHandlerId,
    },
}

#[derive(Clone, Copy)]
enum PendingAction {
    Preference,
    CliPath,
    Timezone,
    Provider,
    ApiKey,
    Hooks,
    LaunchAtLogin,
    Import,
    Export,
    Reset,
    Load,
    CliVersion,
}

pub struct SettingsWindow {
    window: adw::PreferencesWindow,
    actor: SettingsActor,
    login: LoginActor,
    preferences: Arc<PreferencesStore>,
    metadata_version: String,
    controls: RefCell<HashMap<String, Vec<PreferenceControl>>>,
    pending: RefCell<HashMap<u64, PendingAction>>,
    next_request: Cell<u64>,
    status: gtk::Label,
    status_labels: RefCell<Vec<gtk::Label>>,
    providers_group: RefCell<Option<adw::PreferencesGroup>>,
    provider_rows: RefCell<Vec<adw::PreferencesRow>>,
    hooks_group: RefCell<Option<adw::PreferencesGroup>>,
    hook_rows: RefCell<Vec<adw::PreferencesRow>>,
    hook_rules_group: RefCell<Option<adw::PreferencesGroup>>,
    hook_rule_rows: RefCell<Vec<adw::PreferencesRow>>,
    plugins_group: RefCell<Option<adw::PreferencesGroup>>,
    plugin_rows: RefCell<Vec<adw::PreferencesRow>>,
    launch_switch: RefCell<Option<(gtk::Switch, glib::SignalHandlerId)>>,
    timezone_values: RefCell<Vec<String>>,
    cli_version_rows: RefCell<Vec<adw::ActionRow>>,
    login_dialog: RefCell<Option<LoginDialog>>,
    file_chooser: RefCell<Option<gtk::FileChooserNative>>,
}

impl SettingsWindow {
    pub fn new(
        application: &adw::Application,
        actor: SettingsActor,
        login: LoginActor,
        preferences: Arc<PreferencesStore>,
        version: String,
        currency_catalog: &codexbar_core::currency::CurrencyCatalog,
    ) -> Rc<Self> {
        let window = adw::PreferencesWindow::builder()
            .application(application)
            .title("CodexBar Settings")
            .default_width(1000)
            .default_height(740)
            .search_enabled(true)
            .build();
        let status = gtk::Label::new(Some("Loading settings…"));
        status.set_xalign(0.0);
        status.set_wrap(true);
        status.add_css_class("dim-label");
        let view = Rc::new(Self {
            window,
            actor,
            login,
            preferences,
            metadata_version: version,
            controls: RefCell::new(HashMap::new()),
            pending: RefCell::new(HashMap::new()),
            next_request: Cell::new(1),
            status,
            status_labels: RefCell::new(Vec::new()),
            providers_group: RefCell::new(None),
            provider_rows: RefCell::new(Vec::new()),
            hooks_group: RefCell::new(None),
            hook_rows: RefCell::new(Vec::new()),
            hook_rules_group: RefCell::new(None),
            hook_rule_rows: RefCell::new(Vec::new()),
            plugins_group: RefCell::new(None),
            plugin_rows: RefCell::new(Vec::new()),
            launch_switch: RefCell::new(None),
            timezone_values: RefCell::new(Vec::new()),
            cli_version_rows: RefCell::new(Vec::new()),
            login_dialog: RefCell::new(None),
            file_chooser: RefCell::new(None),
        });
        view.build_pages(currency_catalog);
        view.request(
            SettingsOperation::Load {
                timeout: Duration::from_secs(20),
            },
            PendingAction::Load,
        );
        view.request(
            SettingsOperation::CliVersion {
                timeout: Duration::from_secs(8),
            },
            PendingAction::CliVersion,
        );
        view
    }

    pub fn present(&self) {
        self.window.present();
    }

    pub fn hide(&self) {
        self.window.set_visible(false);
    }

    pub fn handle_response(self: &Rc<Self>, response: SettingsResponse) {
        let Some(action) = self.pending.borrow_mut().remove(&response.request_id) else {
            return;
        };
        match response.result {
            Ok(SettingsResult::Snapshot(snapshot)) => {
                self.populate_snapshot(snapshot);
                if matches!(action, PendingAction::Load) {
                    self.set_status("Settings loaded from the shared CodexBar services.");
                }
            }
            Ok(SettingsResult::CliVersion(version)) => {
                for row in self.cli_version_rows.borrow().iter() {
                    row.set_subtitle(&version);
                }
                self.set_status("CodexBar CLI version loaded.");
            }
            Ok(SettingsResult::LaunchAtLogin(state)) => {
                self.set_launch_switch(state.enabled);
                self.set_status(if state.enabled {
                    "Launch at login is enabled."
                } else {
                    "Launch at login is disabled."
                });
            }
            Ok(SettingsResult::Applied { refresh }) => {
                self.sync_preferences();
                let message = match refresh {
                    SettingsRefreshStatus::Queued => "Settings applied; a refresh was queued.",
                    SettingsRefreshStatus::Unavailable => {
                        "Settings were committed, but the refresh channel is closed. Reopen or refresh the app to load them."
                    }
                    SettingsRefreshStatus::NotRequested => match action {
                        PendingAction::Export => "Preferences exported.",
                        _ => "Settings operation completed.",
                    },
                };
                self.set_status(message);
                if matches!(action, PendingAction::Import | PendingAction::Reset) {
                    self.request(
                        SettingsOperation::Load {
                            timeout: Duration::from_secs(20),
                        },
                        PendingAction::Load,
                    );
                }
            }
            Err(error) => {
                if let PendingAction::Preference
                | PendingAction::CliPath
                | PendingAction::Timezone = action
                {
                    self.sync_preferences();
                }
                self.set_status(&safe_settings_error(&error));
                if let Some(dialog) = self.login_dialog.borrow().as_ref() {
                    dialog.status.set_text(&safe_settings_error(&error));
                }
            }
        }
    }

    pub fn handle_login_event(&self, event: LoginUiEvent) {
        let dialog_slot = self.login_dialog.borrow();
        let Some(dialog) = dialog_slot.as_ref() else {
            return;
        };
        match event {
            LoginUiEvent::AuthorizationUrl(url) => dialog.set_url(&url),
            LoginUiEvent::Prompt(prompt) => dialog.show_prompt(prompt),
            LoginUiEvent::Finished(kind) => {
                use codexbar_backend::login::LoginCompletionKind;
                let message = match kind {
                    LoginCompletionKind::Succeeded => "Sign-in completed.",
                    LoginCompletionKind::Failed => "Sign-in did not complete.",
                    LoginCompletionKind::TimedOut => "Sign-in timed out.",
                    LoginCompletionKind::Cancelled => "Sign-in cancelled.",
                };
                dialog.status.set_text(message);
                #[cfg(debug_assertions)]
                if let Some(path) = std::env::var_os("CODEXBAR_NATIVE_SETTINGS_LOGIN_STATUS_REPORT")
                {
                    let _ = fs::write(path, message);
                }
                if matches!(
                    kind,
                    LoginCompletionKind::Succeeded | LoginCompletionKind::Cancelled
                ) {
                    dialog.close_button.set_label("Close");
                }
            }
            LoginUiEvent::Failed(kind) => {
                dialog
                    .status
                    .set_text(&format!("Sign-in unavailable ({kind:?})."));
                dialog.close_button.set_label("Close");
            }
        }
    }

    pub fn handle_terminal_login_result(
        &self,
        result: Result<
            codexbar_backend::application::TerminalLoginResult,
            codexbar_backend::application::LoginOperationError,
        >,
    ) {
        if let Some(dialog) = self.login_dialog.borrow().as_ref() {
            dialog.status.set_text(match result {
                Ok(result) if result.launched => "Codex login started in a terminal.",
                Ok(_) => "No supported terminal was found. Continue with browser sign-in.",
                Err(error)
                    if error.kind
                        == codexbar_backend::application::LoginOperationErrorKind::CliNotFound =>
                {
                    "Codex CLI was not found. Continue with browser sign-in."
                }
                Err(_) => "Could not open a terminal. Continue with browser sign-in.",
            });
        }
    }

    fn request(&self, operation: SettingsOperation, action: PendingAction) {
        let request_id = self.next_request.get();
        self.next_request.set(request_id.wrapping_add(1));
        match self.actor.try_send(SettingsRequest {
            request_id,
            operation,
        }) {
            Ok(()) => {
                self.pending.borrow_mut().insert(request_id, action);
                self.set_status("Applying settings…");
            }
            Err(_) => self.set_status("Settings service is busy or closed."),
        }
    }

    fn set_status(&self, text: &str) {
        self.status.set_text(text);
        for label in self.status_labels.borrow().iter() {
            label.set_text(text);
        }
    }

    fn preference(&self, key: &str) -> Value {
        self.preferences.get(key).unwrap_or(Value::Null)
    }

    fn set_preference(&self, key: &str, value: Value) {
        self.request(
            SettingsOperation::SetPreference {
                key: key.to_owned(),
                value,
            },
            PendingAction::Preference,
        );
    }

    fn build_pages(self: &Rc<Self>, currency_catalog: &codexbar_core::currency::CurrencyCatalog) {
        let general = self.page(
            "General",
            &["system-run-symbolic", "dialog-information-symbolic"],
        );
        let navigation = self.group("Navigation", None);
        let dashboard = adw::ActionRow::builder()
            .title("Return to dashboard")
            .subtitle("Usage quotas, active sessions and spending")
            .build();
        let open = gtk::Button::with_label("Open dashboard");
        open.set_valign(gtk::Align::Center);
        open.set_action_name(Some("app.dashboard"));
        dashboard.add_suffix(&open);
        dashboard.set_activatable_widget(Some(&open));
        navigation.add(&dashboard);
        general.add(&navigation);

        let refresh = self.group("Refreshing", None);
        self.combo_setting(
            &refresh,
            "refreshFrequency",
            "Refresh interval",
            &[
                ("Manual", "manual"),
                ("Every minute", "1m"),
                ("Every 2 minutes", "2m"),
                ("Every 5 minutes", "5m"),
                ("Every 15 minutes", "15m"),
                ("Every 30 minutes", "30m"),
                ("Adaptive", "adaptive"),
            ],
            None,
        );
        self.switch_setting(
            &refresh,
            "refreshAllProvidersOnMenuOpen",
            "Refresh when the panel opens",
            "Fetch fresh provider data each time the compact panel is shown.",
            None,
        );
        general.add(&refresh);

        let startup = self.group("Startup", None);
        let launch = adw::ActionRow::builder()
            .title("Start at login")
            .subtitle("Launch CodexBar when you sign in")
            .build();
        let launch_switch = gtk::Switch::new();
        launch_switch.set_valign(gtk::Align::Center);
        let weak = Rc::downgrade(self);
        let launch_handler = launch_switch.connect_active_notify(move |switch| {
            if let Some(view) = weak.upgrade() {
                let executable = std::env::current_exe()
                    .ok()
                    .map(|path| path.to_string_lossy().into_owned())
                    .unwrap_or_else(|| "codexbar-gtk-native".to_owned());
                view.request(
                    SettingsOperation::SetLaunchAtLogin {
                        enabled: switch.is_active(),
                        app_exec: executable,
                    },
                    PendingAction::LaunchAtLogin,
                );
            }
        });
        launch.add_suffix(&launch_switch);
        launch.set_activatable_widget(Some(&launch_switch));
        startup.add(&launch);
        *self.launch_switch.borrow_mut() = Some((launch_switch, launch_handler));
        self.switch_setting(
            &startup,
            "showPopupOnStart",
            "Show the panel on start",
            "Open the compact provider panel when the app launches.",
            None,
        );
        general.add(&startup);

        let currencies = self.group("General", None);
        let mut currency_options = vec![("Automatic (as reported)".to_owned(), "auto".to_owned())];
        for code in currency_catalog.codes() {
            currency_options.push((currency_catalog.label(&code), code));
        }
        let currency_refs: Vec<(&str, &str)> = currency_options
            .iter()
            .map(|(label, value)| (label.as_str(), value.as_str()))
            .collect();
        self.combo_setting(
            &currencies,
            "preferredCurrencyCode",
            "Preferred currency",
            &currency_refs,
            None,
        );
        general.add(&currencies);
        self.add_status(&general);
        self.window.add(&general);

        let providers = self.page(
            "Providers",
            &["network-server-symbolic", "dialog-information-symbolic"],
        );
        let provider_group = self.group("Providers", Some("Enable the providers you use. Credentials are sent to the CodexBar CLI and are never saved by Settings."));
        let loading_providers = self.loading_row("Loading providers…");
        provider_group.add(&loading_providers);
        self.provider_rows
            .borrow_mut()
            .push(loading_providers.upcast());
        *self.providers_group.borrow_mut() = Some(provider_group.clone());
        providers.add(&provider_group);
        self.add_status(&providers);
        self.window.add(&providers);

        let menu = self.page(
            "Menu Bar",
            &["view-list-symbolic", "dialog-information-symbolic"],
        );
        let icon = self.group("Tray icon", None);
        self.combo_setting(
            &icon,
            "menuBarIconStyle",
            "Icon style",
            &[
                ("Usage meter", "meter"),
                ("Icon and percentage", "iconPercent"),
            ],
            None,
        );
        self.combo_setting(
            &icon,
            "unifiedIconSource",
            "Icon shows",
            &[
                ("Quota running out soonest", "automatic"),
                ("Highest usage", "highest"),
                ("First enabled provider", "first"),
            ],
            Some("For providers without a quota, choose First enabled provider."),
        );
        self.combo_setting(
            &icon,
            "switcherRowsOption",
            "Provider rows",
            &[("Usage bar", "progress"), ("Quota details", "details")],
            None,
        );
        self.switch_setting(
            &icon,
            "showTray",
            "Show the tray icon",
            "Display the compact CodexBar panel from the system tray.",
            None,
        );
        menu.add(&icon);
        self.add_status(&menu);
        self.window.add(&menu);

        let display = self.page(
            "Display",
            &["user-desktop-symbolic", "dialog-information-symbolic"],
        );
        let usage = self.group("Usage", None);
        self.switch_setting(
            &usage,
            "usageBarsShowUsed",
            "Show used instead of remaining",
            "Meters fill as quota is consumed.",
            None,
        );
        self.combo_setting(
            &usage,
            "resetTimesOption",
            "Reset time format",
            &[
                ("Countdown", "countdown"),
                ("Absolute time", "absolute"),
                ("Both", "both"),
            ],
            None,
        );
        self.switch_setting(
            &usage,
            "paceVisible",
            "Show pace indicators",
            "Compare current usage with expected pace.",
            None,
        );
        self.switch_setting(
            &usage,
            "hidePersonalInfo",
            "Hide account details",
            "Do not show email addresses or plan names.",
            None,
        );
        display.add(&usage);
        let weekly = self.group(
            "Weekly window",
            Some("Show progress through the working days in the weekly quota."),
        );
        self.number_setting(
            &weekly,
            "weeklyProgressWorkDays",
            "Working days per week",
            1.0,
            7.0,
            None,
        );
        self.combo_setting(
            &weekly,
            "workdayTickAppearance",
            "Workday ticks",
            &[
                ("Hidden", "hidden"),
                ("Subtle", "subtle"),
                ("High contrast", "highContrast"),
            ],
            None,
        );
        self.switch_setting(
            &weekly,
            "quotaBurndownEnabled",
            "Project usage at reset",
            "Extrapolate usage from the recorded history.",
            None,
        );
        display.add(&weekly);
        let warnings = self.group(
            "Quota warnings",
            Some("Set warning and critical levels for usage meters."),
        );
        self.number_setting(
            &warnings,
            "quotaWarningThresholds",
            "Warning threshold (%)",
            5.0,
            99.0,
            Some(0),
        );
        self.number_setting(
            &warnings,
            "quotaWarningThresholds",
            "Critical threshold (%)",
            5.0,
            99.0,
            Some(1),
        );
        display.add(&warnings);
        self.add_status(&display);
        self.window.add(&display);

        let notifications = self.page("Notifications", &["dialog-information-symbolic"]);
        let notification_group = self.group("Quota notifications", None);
        self.switch_setting(
            &notification_group,
            "sessionQuotaNotificationsEnabled",
            "Session quota notifications",
            "Notify when a session window is exhausted.",
            None,
        );
        self.switch_setting(
            &notification_group,
            "quotaWarningNotificationsEnabled",
            "Quota warning notifications",
            "Notify when a provider crosses a warning level.",
            None,
        );
        self.switch_setting(
            &notification_group,
            "limitResetNotificationsEnabled",
            "Limit reset notifications",
            "Notify when a window resets or a reset credit is near expiry.",
            None,
        );
        self.switch_setting(
            &notification_group,
            "predictivePaceNotificationsEnabled",
            "Pace warnings",
            "Warn when current pace may run out before reset.",
            None,
        );
        let (test_notification, send_test) = self.action_row(
            "Send a test notification",
            "Check that desktop notifications are working.",
            "Send",
        );
        let weak = Rc::downgrade(self);
        send_test.connect_clicked(move |_| {
            if let Some(view) = weak.upgrade() {
                view.send_test_notification();
            }
        });
        notification_group.add(&test_notification);
        notifications.add(&notification_group);
        self.add_status(&notifications);
        self.window.add(&notifications);

        let spend = self.page(
            "Usage & Spend",
            &[
                "document-open-recent-symbolic",
                "dialog-information-symbolic",
            ],
        );
        let local_cost = self.group("Local cost scanning", None);
        self.switch_setting(
            &local_cost,
            "costUsageEnabled",
            "Enable local cost scans",
            "Read local Codex and Claude transcripts to estimate spend.",
            None,
        );
        spend.add(&local_cost);
        let daily = self.group("Daily buckets", Some("Daily usage follows a fixed time zone. Changing it can move usage to another date."));
        self.timezone_setting(&daily);
        spend.add(&daily);
        self.add_status(&spend);
        self.window.add(&spend);

        let hooks = self.page(
            "Hooks",
            &[
                "application-x-executable-symbolic",
                "system-run-symbolic",
                "dialog-information-symbolic",
            ],
        );
        let hooks_group = self.group(
            "Hooks",
            Some("Run configured commands when provider or quota events occur."),
        );
        let loading_hooks = self.loading_row("Loading hooks…");
        hooks_group.add(&loading_hooks);
        self.hook_rows.borrow_mut().push(loading_hooks.upcast());
        *self.hooks_group.borrow_mut() = Some(hooks_group.clone());
        hooks.add(&hooks_group);
        let rules = self.group(
            "Rules",
            Some("Rules are configured in the shared CodexBar CLI settings."),
        );
        let loading_rules = self.loading_row("Loading rules…");
        rules.add(&loading_rules);
        self.hook_rule_rows
            .borrow_mut()
            .push(loading_rules.upcast());
        *self.hook_rules_group.borrow_mut() = Some(rules.clone());
        hooks.add(&rules);
        self.add_status(&hooks);
        self.window.add(&hooks);

        let plugins = self.page(
            "Plugins",
            &["view-grid-symbolic", "dialog-information-symbolic"],
        );
        let plugins_group = self.group(
            "Plugins",
            Some("JavaScript plugins can add extra providers to CodexBar."),
        );
        let loading_plugins = self.loading_row("Loading plugins…");
        plugins_group.add(&loading_plugins);
        self.plugin_rows.borrow_mut().push(loading_plugins.upcast());
        *self.plugins_group.borrow_mut() = Some(plugins_group.clone());
        plugins.add(&plugins_group);
        self.add_status(&plugins);
        self.window.add(&plugins);

        let advanced = self.page(
            "Advanced",
            &["system-run-symbolic", "dialog-information-symbolic"],
        );
        let cli_group = self.group(
            "CodexBar CLI",
            Some("The desktop app uses this executable for provider data and account actions."),
        );
        let cli_path = adw::EntryRow::builder()
            .title("CLI path")
            .show_apply_button(true)
            .build();
        cli_path.set_text(self.preference("cliPath").as_str().unwrap_or_default());
        let weak = Rc::downgrade(self);
        let cli_handler = cli_path.connect_apply(move |row| {
            if let Some(view) = weak.upgrade() {
                view.request(
                    SettingsOperation::ReconfigureCli {
                        cli_path: Some(row.text().trim().to_owned()),
                        timezone: None,
                    },
                    PendingAction::CliPath,
                );
            }
        });
        self.controls
            .borrow_mut()
            .entry("cliPath".to_owned())
            .or_default()
            .push(PreferenceControl::Text {
                widget: cli_path.clone(),
                handler: cli_handler,
            });
        cli_group.add(&cli_path);
        let cli_version = adw::ActionRow::builder()
            .title("CLI version")
            .subtitle("Loading…")
            .build();
        self.cli_version_rows.borrow_mut().push(cli_version.clone());
        cli_group.add(&cli_version);
        advanced.add(&cli_group);
        let data = self.group("Preferences", None);
        let export = self.action_row(
            "Export preferences",
            "Save portable settings as JSON",
            "Export…",
        );
        let weak = Rc::downgrade(self);
        export.1.connect_clicked(move |_| {
            if let Some(view) = weak.upgrade() {
                view.choose_preferences_file(true);
            }
        });
        data.add(&export.0);
        let import = self.action_row(
            "Import preferences",
            "Merge known settings from a JSON file",
            "Import…",
        );
        let weak = Rc::downgrade(self);
        import.1.connect_clicked(move |_| {
            if let Some(view) = weak.upgrade() {
                view.choose_preferences_file(false);
            }
        });
        data.add(&import.0);
        let reset = self.action_row(
            "Reset all preferences",
            "Restore the default preferences without changing the autostart file",
            "Reset…",
        );
        let weak = Rc::downgrade(self);
        reset.1.connect_clicked(move |_| {
            if let Some(view) = weak.upgrade() {
                view.confirm_reset();
            }
        });
        data.add(&reset.0);
        advanced.add(&data);
        self.add_status(&advanced);
        self.window.add(&advanced);

        let acknowledgements = self.page(
            "Acknowledgements",
            &["text-x-generic-symbolic", "dialog-information-symbolic"],
        );
        let dependencies = self.group("Third-party software", None);
        for (name, description, license) in [
            ("GTK4", "GIMP Toolkit", "LGPL-2.1-or-later"),
            (
                "libadwaita",
                "GNOME application widgets",
                "LGPL-2.1-or-later",
            ),
            ("GLib", "Core application library", "LGPL-2.1-or-later"),
            ("Tokio", "Asynchronous runtime", "MIT"),
            ("Serde", "Serialization framework", "MIT OR Apache-2.0"),
            (
                "portable-pty",
                "Portable pseudo terminals",
                "MIT OR Apache-2.0",
            ),
        ] {
            let row = adw::ActionRow::builder()
                .title(name)
                .subtitle(description)
                .build();
            let license_label = gtk::Label::new(Some(license));
            license_label.add_css_class("caption");
            license_label.set_xalign(1.0);
            row.add_suffix(&license_label);
            dependencies.add(&row);
        }
        acknowledgements.add(&dependencies);
        let source = adw::ActionRow::builder()
            .title("Source code")
            .subtitle("github.com/SaahiilM/codexbar-gtk")
            .build();
        let source_button = gtk::Button::with_label("Open");
        source_button.set_valign(gtk::Align::Center);
        source_button.connect_clicked(|_| {
            gio::AppInfo::launch_default_for_uri_async(
                "https://github.com/SaahiilM/codexbar-gtk",
                None::<&gio::AppLaunchContext>,
                None::<&gio::Cancellable>,
                |_| {},
            );
        });
        source.add_suffix(&source_button);
        let project = self.group("Project", None);
        project.add(&source);
        acknowledgements.add(&project);
        self.add_status(&acknowledgements);
        self.window.add(&acknowledgements);

        let about = self.page("About", &["dialog-information-symbolic"]);
        let app_group = self.group("CodexBar GTK", None);
        for (title, subtitle) in [
            ("Version", self.metadata_version.as_str()),
            ("Toolkit", "GTK4 / libadwaita"),
        ] {
            app_group.add(
                &adw::ActionRow::builder()
                    .title(title)
                    .subtitle(subtitle)
                    .build(),
            );
        }
        let about_cli = adw::ActionRow::builder()
            .title("CodexBar CLI")
            .subtitle("Loading…")
            .build();
        self.cli_version_rows.borrow_mut().push(about_cli.clone());
        app_group.add(&about_cli);
        about.add(&app_group);
        let project = self.group("Project", None);
        let project_row = adw::ActionRow::builder()
            .title("CodexBar GTK")
            .subtitle("Open the project source code")
            .build();
        let project_button = gtk::Button::with_label("Open");
        project_button.set_valign(gtk::Align::Center);
        project_button.connect_clicked(|_| {
            gio::AppInfo::launch_default_for_uri_async(
                "https://github.com/SaahiilM/codexbar-gtk",
                None::<&gio::AppLaunchContext>,
                None::<&gio::Cancellable>,
                |_| {},
            );
        });
        project_row.add_suffix(&project_button);
        project.add(&project_row);
        about.add(&project);
        self.add_status(&about);
        self.window.add(&about);
    }

    fn page(&self, title: &str, icon_candidates: &[&str]) -> adw::PreferencesPage {
        let selected_icon = gtk::gdk::Display::default().and_then(|display| {
            let theme = gtk::IconTheme::for_display(&display);
            icon_candidates
                .iter()
                .copied()
                .find(|icon| theme.has_icon(icon))
        });
        if std::env::var_os("CODEXBAR_NATIVE_SETTINGS_ICON_REPORT").is_some() {
            eprintln!(
                "native-settings-icon: {title}: {}",
                selected_icon.unwrap_or("<none>")
            );
        }
        let builder = adw::PreferencesPage::builder().title(title);
        if let Some(icon) = selected_icon {
            builder.icon_name(icon).build()
        } else {
            builder.build()
        }
    }

    fn group(&self, title: &str, description: Option<&str>) -> adw::PreferencesGroup {
        let builder = adw::PreferencesGroup::builder().title(title);
        builder.description(description.unwrap_or_default()).build()
    }

    fn add_status(&self, page: &adw::PreferencesPage) {
        let group = self.group("Status", None);
        let row = adw::ActionRow::new();
        let label = if self.status_labels.borrow().is_empty() {
            self.status.clone()
        } else {
            gtk::Label::new(Some(&self.status.label()))
        };
        label.set_xalign(0.0);
        label.set_wrap(true);
        label.add_css_class("dim-label");
        row.add_suffix(&label);
        self.status_labels.borrow_mut().push(label);
        group.add(&row);
        page.add(&group);
    }

    fn loading_row(&self, title: &str) -> adw::ActionRow {
        adw::ActionRow::builder().title(title).build()
    }

    fn switch_setting(
        self: &Rc<Self>,
        group: &adw::PreferencesGroup,
        key: &str,
        title: &str,
        subtitle: &str,
        _callback: Option<fn(bool)>,
    ) {
        let row = adw::ActionRow::builder()
            .title(title)
            .subtitle(subtitle)
            .build();
        let switch = gtk::Switch::new();
        switch.set_valign(gtk::Align::Center);
        switch.set_active(self.preference(key).as_bool().unwrap_or(false));
        let preference_key = key.to_owned();
        let weak = Rc::downgrade(self);
        let handler = switch.connect_active_notify(move |switch| {
            if let Some(view) = weak.upgrade() {
                view.set_preference(&preference_key, json!(switch.is_active()));
            }
        });
        self.controls
            .borrow_mut()
            .entry(key.to_owned())
            .or_default()
            .push(PreferenceControl::Switch {
                widget: switch.clone(),
                handler,
            });
        row.add_suffix(&switch);
        row.set_activatable_widget(Some(&switch));
        group.add(&row);
    }

    fn combo_setting(
        self: &Rc<Self>,
        group: &adw::PreferencesGroup,
        key: &str,
        title: &str,
        options: &[(&str, &str)],
        subtitle: Option<&str>,
    ) {
        let row = adw::ComboRow::builder()
            .title(title)
            .subtitle(subtitle.unwrap_or_default())
            .build();
        let model = gtk::StringList::new(&[]);
        for (label, _) in options {
            model.append(label);
        }
        row.set_model(Some(&model));
        let values: Vec<String> = options
            .iter()
            .map(|(_, value)| (*value).to_owned())
            .collect();
        let current = self.preference(key).as_str().unwrap_or_default().to_owned();
        let selected = values
            .iter()
            .position(|value| value == &current)
            .unwrap_or(0);
        row.set_selected(selected as u32);
        let preference_key = key.to_owned();
        let values_for_handler = values.clone();
        let weak = Rc::downgrade(self);
        let handler = row.connect_selected_notify(move |row| {
            if let Some(view) = weak.upgrade() {
                if let Some(value) = values_for_handler.get(row.selected() as usize) {
                    view.set_preference(&preference_key, json!(value));
                }
            }
        });
        self.controls
            .borrow_mut()
            .entry(key.to_owned())
            .or_default()
            .push(PreferenceControl::Combo {
                widget: row.clone(),
                handler,
                values,
            });
        group.add(&row);
    }

    fn number_setting(
        self: &Rc<Self>,
        group: &adw::PreferencesGroup,
        key: &str,
        title: &str,
        minimum: f64,
        maximum: f64,
        array_index: Option<usize>,
    ) {
        let value = self.preference(key);
        let current = value
            .as_array()
            .and_then(|values| values.get(array_index.unwrap_or(0)))
            .and_then(Value::as_f64)
            .or_else(|| value.as_i64().map(|number| number as f64))
            .unwrap_or(5.0);
        let row = adw::ActionRow::builder().title(title).build();
        let adjustment = gtk::Adjustment::new(current, minimum, maximum, 1.0, 5.0, 0.0);
        let spin = gtk::SpinButton::new(Some(&adjustment), 1.0, 0);
        spin.set_valign(gtk::Align::Center);
        let preference_key = key.to_owned();
        let weak = Rc::downgrade(self);
        let handler = spin.connect_value_changed(move |spin| {
            if let Some(view) = weak.upgrade() {
                if let Some(index) = array_index {
                    view.request(
                        SettingsOperation::SetPreferenceArrayElement {
                            key: preference_key.clone(),
                            index,
                            value: json!(spin.value_as_int()),
                        },
                        PendingAction::Preference,
                    );
                } else {
                    view.set_preference(&preference_key, json!(spin.value_as_int()));
                }
            }
        });
        self.controls
            .borrow_mut()
            .entry(key.to_owned())
            .or_default()
            .push(PreferenceControl::Number {
                widget: spin.clone(),
                handler,
                array_index,
            });
        row.add_suffix(&spin);
        row.set_activatable_widget(Some(&spin));
        group.add(&row);
    }

    fn timezone_setting(self: &Rc<Self>, group: &adw::PreferencesGroup) {
        let current = self
            .preference("costUsageBucketTimeZone")
            .as_str()
            .unwrap_or_default()
            .to_owned();
        let mut options = vec![("System local time".to_owned(), String::new())];
        options.extend(
            available_timezones()
                .into_iter()
                .map(|zone| (zone.clone(), zone)),
        );
        if !current.is_empty() && !options.iter().any(|(_, value)| value == &current) {
            options.push((format!("{current} (saved)"), current.clone()));
        }
        let row = adw::ComboRow::builder()
            .title("Statistics time zone")
            .subtitle("Daily spend buckets use this time zone.")
            .build();
        let model = gtk::StringList::new(&[]);
        let values: Vec<String> = options.iter().map(|(_, value)| value.clone()).collect();
        for (label, _) in &options {
            model.append(label);
        }
        row.set_model(Some(&model));
        row.set_selected(
            values
                .iter()
                .position(|value| value == &current)
                .unwrap_or(0) as u32,
        );
        self.timezone_values.replace(values.clone());
        let weak = Rc::downgrade(self);
        let handler = row.connect_selected_notify(move |row| {
            if let Some(view) = weak.upgrade() {
                let timezone = view
                    .timezone_values
                    .borrow()
                    .get(row.selected() as usize)
                    .cloned()
                    .unwrap_or_default();
                view.request(
                    SettingsOperation::ReconfigureCli {
                        cli_path: None,
                        timezone: Some(timezone),
                    },
                    PendingAction::Timezone,
                );
            }
        });
        self.controls
            .borrow_mut()
            .entry("costUsageBucketTimeZone".to_owned())
            .or_default()
            .push(PreferenceControl::Combo {
                widget: row.clone(),
                handler,
                values,
            });
        group.add(&row);
    }

    fn populate_snapshot(self: &Rc<Self>, snapshot: SettingsSnapshot) {
        self.populate_providers(
            snapshot.providers.value.as_deref(),
            snapshot.providers.error.as_ref(),
        );
        if let Some(hooks) = snapshot.hooks.value.as_ref() {
            self.populate_hooks(hooks);
        } else if let Some(error) = snapshot.hooks.error.as_ref() {
            replace_group_rows(
                self.hooks_group.borrow().as_ref(),
                &self.hook_rows,
                vec![self.loading_row(&safe_settings_error(error)).upcast()],
            );
        }
        if let Some(plugins) = snapshot.plugins.value.as_ref() {
            self.populate_plugins(plugins);
        } else if let Some(error) = snapshot.plugins.error.as_ref() {
            replace_group_rows(
                self.plugins_group.borrow().as_ref(),
                &self.plugin_rows,
                vec![self.loading_row(&safe_settings_error(error)).upcast()],
            );
        }
        if let Some(launch) = snapshot.launch_at_login.value {
            self.set_launch_switch(launch.enabled);
        } else if let Some(error) = snapshot.launch_at_login.error.as_ref() {
            self.set_status(&safe_settings_error(error));
        }
    }

    fn populate_providers(
        self: &Rc<Self>,
        entries: Option<&[codexbar_backend::cli::ProviderStatusEntry]>,
        error: Option<&SettingsError>,
    ) {
        let Some(group) = self.providers_group.borrow().clone() else {
            return;
        };
        let mut rows: Vec<adw::PreferencesRow> = Vec::new();
        if let Some(error) = error {
            rows.push(
                self.loading_row(&format!(
                    "Could not load providers · {}",
                    safe_settings_error(error)
                ))
                .upcast(),
            );
        } else if let Some(entries) = entries {
            if entries.is_empty() {
                rows.push(self.loading_row("No providers found").upcast());
            }
            for provider in entries {
                let row = adw::ExpanderRow::builder()
                    .title(&provider.display_name)
                    .subtitle(&provider.provider_id)
                    .build();
                let enabled = gtk::Switch::new();
                enabled.set_valign(gtk::Align::Center);
                enabled.set_active(provider.enabled);
                let provider_id = provider.provider_id.clone();
                let weak = Rc::downgrade(self);
                enabled.connect_active_notify(move |switch| {
                    if let Some(view) = weak.upgrade() {
                        view.request(
                            SettingsOperation::ProviderAction {
                                action: if switch.is_active() {
                                    ProviderAction::Enable
                                } else {
                                    ProviderAction::Disable
                                },
                                provider_id: provider_id.clone(),
                            },
                            PendingAction::Provider,
                        );
                    }
                });
                let enabled_row = adw::ActionRow::builder().title("Provider enabled").build();
                enabled_row.add_suffix(&enabled);
                enabled_row.set_activatable_widget(Some(&enabled));
                row.add_row(&enabled_row);
                let source = combo_control(
                    "Source",
                    &[
                        ("Automatic", "auto"),
                        ("Web", "web"),
                        ("CLI", "cli"),
                        ("OAuth", "oauth"),
                        ("API", "api"),
                    ],
                    "auto",
                );
                let provider_id = provider.provider_id.clone();
                let weak = Rc::downgrade(self);
                source.connect_selected_notify(move |source| {
                    if let Some(view) = weak.upgrade() {
                        let selected = source.selected() as usize;
                        let source = match selected {
                            1 => ProviderSource::Web,
                            2 => ProviderSource::Cli,
                            3 => ProviderSource::Oauth,
                            4 => ProviderSource::Api,
                            _ => ProviderSource::Auto,
                        };
                        view.request(
                            SettingsOperation::ProviderAction {
                                action: ProviderAction::SetSource { source },
                                provider_id: provider_id.clone(),
                            },
                            PendingAction::Provider,
                        );
                    }
                });
                row.add_row(&source);
                if provider.provider_id == "claude" || provider.provider_id == "codex" {
                    let sign_in = adw::ActionRow::builder()
                        .title("Sign in with provider CLI")
                        .subtitle(
                            "Open the native sign-in dialog; authentication events stay in memory.",
                        )
                        .build();
                    let sign_in_button = gtk::Button::with_label("Sign in…");
                    sign_in_button.set_valign(gtk::Align::Center);
                    let provider_id = provider.provider_id.clone();
                    let weak = Rc::downgrade(self);
                    sign_in_button.connect_clicked(move |_| {
                        if let Some(view) = weak.upgrade() {
                            view.show_login(&provider_id);
                        }
                    });
                    sign_in.add_suffix(&sign_in_button);
                    row.add_row(&sign_in);
                }
                let api_key = adw::PasswordEntryRow::builder().title("API key").build();
                api_key.set_show_apply_button(true);
                let provider_id = provider.provider_id.clone();
                let weak = Rc::downgrade(self);
                api_key.connect_apply(move |entry| {
                    let secret = entry.text().trim().to_owned();
                    entry.set_text("");
                    if secret.is_empty() {
                        return;
                    }
                    if let Some(view) = weak.upgrade() {
                        view.request(
                            SettingsOperation::SetApiKey {
                                provider_id: provider_id.clone(),
                                secret,
                            },
                            PendingAction::ApiKey,
                        );
                    }
                });
                row.add_row(&api_key);
                rows.push(row.upcast::<adw::PreferencesRow>());
            }
        }
        replace_group_rows(Some(&group), &self.provider_rows, rows);
    }

    fn populate_hooks(self: &Rc<Self>, hooks: &HookSettings) {
        let Some(group) = self.hooks_group.borrow().clone() else {
            return;
        };
        let row = adw::ActionRow::builder()
            .title("Enable hooks")
            .subtitle("Fire configured rules on quota and provider events.")
            .build();
        let switch = gtk::Switch::new();
        switch.set_valign(gtk::Align::Center);
        switch.set_active(hooks.enabled);
        let weak = Rc::downgrade(self);
        switch.connect_active_notify(move |switch| {
            if let Some(view) = weak.upgrade() {
                view.request(
                    SettingsOperation::SetHooksEnabled {
                        enabled: switch.is_active(),
                    },
                    PendingAction::Hooks,
                );
            }
        });
        row.add_suffix(&switch);
        row.set_activatable_widget(Some(&switch));
        replace_group_rows(Some(&group), &self.hook_rows, vec![row.upcast()]);
        let rules: Vec<adw::PreferencesRow> = if hooks.events.is_empty() {
            vec![self.loading_row("No rules configured").upcast()]
        } else {
            hooks
                .events
                .iter()
                .map(|rule| {
                    let row = adw::ActionRow::builder()
                        .title(rule.event.as_deref().unwrap_or("event"))
                        .subtitle(rule.executable.as_deref().unwrap_or(""))
                        .build();
                    let label = gtk::Label::new(Some(if rule.enabled.unwrap_or(false) {
                        "On"
                    } else {
                        "Off"
                    }));
                    label.add_css_class("caption");
                    row.add_suffix(&label);
                    row.upcast::<adw::PreferencesRow>()
                })
                .collect()
        };
        replace_group_rows(
            self.hook_rules_group.borrow().as_ref(),
            &self.hook_rule_rows,
            rules,
        );
    }

    fn populate_plugins(&self, plugins: &[PluginInfo]) {
        let rows: Vec<adw::PreferencesRow> = if plugins.is_empty() {
            vec![self
                .loading_row("No plugins installed. Add plugins to the CodexBar plugins directory.")
                .upcast()]
        } else {
            plugins
                .iter()
                .map(|plugin| {
                    adw::ActionRow::builder()
                        .title(
                            plugin
                                .name
                                .as_deref()
                                .or(plugin.id.as_deref())
                                .unwrap_or("Plugin"),
                        )
                        .subtitle(
                            plugin
                                .version
                                .as_deref()
                                .or(plugin.provider.as_deref())
                                .unwrap_or(""),
                        )
                        .build()
                        .upcast::<adw::PreferencesRow>()
                })
                .collect()
        };
        replace_group_rows(
            self.plugins_group.borrow().as_ref(),
            &self.plugin_rows,
            rows,
        );
    }

    fn set_launch_switch(&self, active: bool) {
        if let Some((switch, handler)) = self.launch_switch.borrow().as_ref() {
            switch.block_signal(handler);
            switch.set_active(active);
            switch.unblock_signal(handler);
        }
    }

    fn sync_preferences(&self) {
        let controls = self.controls.borrow();
        for (key, key_controls) in controls.iter() {
            let value = self.preferences.get(key).unwrap_or(Value::Null);
            for control in key_controls {
                match control {
                    PreferenceControl::Switch { widget, handler } => {
                        widget.block_signal(handler);
                        widget.set_active(value.as_bool().unwrap_or(false));
                        widget.unblock_signal(handler);
                    }
                    PreferenceControl::Combo {
                        widget,
                        handler,
                        values,
                    } => {
                        if let Some(selected) = values
                            .iter()
                            .position(|candidate| Some(candidate.as_str()) == value.as_str())
                        {
                            widget.block_signal(handler);
                            widget.set_selected(selected as u32);
                            widget.unblock_signal(handler);
                        }
                    }
                    PreferenceControl::Number {
                        widget,
                        handler,
                        array_index,
                    } => {
                        let number = value
                            .as_i64()
                            .map(|number| number as f64)
                            .or_else(|| {
                                value
                                    .as_array()
                                    .and_then(|values| values.get(array_index.unwrap_or(0)))
                                    .and_then(Value::as_f64)
                            })
                            .unwrap_or(5.0);
                        widget.block_signal(handler);
                        widget.set_value(number);
                        widget.unblock_signal(handler);
                    }
                    PreferenceControl::Text { widget, handler } => {
                        widget.block_signal(handler);
                        widget.set_text(value.as_str().unwrap_or_default());
                        widget.unblock_signal(handler);
                    }
                }
            }
        }
    }

    fn choose_preferences_file(self: &Rc<Self>, exporting: bool) {
        let action = if exporting {
            gtk::FileChooserAction::Save
        } else {
            gtk::FileChooserAction::Open
        };
        let title = if exporting {
            "Export preferences"
        } else {
            "Import preferences"
        };
        let accept = if exporting { "Save" } else { "Import" };
        let chooser = gtk::FileChooserNative::new(
            Some(title),
            Some(&self.window),
            action,
            Some(accept),
            Some("Cancel"),
        );
        if exporting {
            chooser.set_current_name("preferences-export.json");
        }
        let filter = gtk::FileFilter::new();
        filter.set_name(Some("JSON documents"));
        filter.add_pattern("*.json");
        chooser.add_filter(&filter);
        // GtkNativeDialog is not a toplevel widget and GTK does not retain it
        // after show(); keep the Rust object alive until its response arrives.
        self.file_chooser.replace(Some(chooser.clone()));
        let weak = Rc::downgrade(self);
        chooser.connect_response(move |chooser, response| {
            if response == gtk::ResponseType::Accept {
                if let Some(path) = chooser.file().and_then(|file| file.path()) {
                    if let Some(view) = weak.upgrade() {
                        let operation = if exporting {
                            SettingsOperation::ExportPreferences { path }
                        } else {
                            SettingsOperation::ImportPreferences { path }
                        };
                        view.request(
                            operation,
                            if exporting {
                                PendingAction::Export
                            } else {
                                PendingAction::Import
                            },
                        );
                    }
                }
            }
            chooser.destroy();
            if let Some(view) = weak.upgrade() {
                view.file_chooser.borrow_mut().take();
            }
        });
        chooser.show();
    }

    fn confirm_reset(self: &Rc<Self>) {
        let dialog = adw::MessageDialog::new(
            Some(&self.window),
            Some("Reset all preferences?"),
            Some("All saved preferences will return to their defaults. The existing autostart entry will not be changed."),
        );
        dialog.add_response("cancel", "Cancel");
        dialog.add_response("reset", "Reset");
        dialog.set_response_appearance("reset", adw::ResponseAppearance::Destructive);
        dialog.set_default_response(Some("cancel"));
        let weak = Rc::downgrade(self);
        dialog.connect_response(None, move |_, response| {
            if response == "reset" {
                if let Some(view) = weak.upgrade() {
                    view.request(SettingsOperation::ResetPreferences, PendingAction::Reset);
                }
            }
        });
        dialog.present();
    }

    fn send_test_notification(&self) {
        let notification = gio::Notification::new("CodexBar GTK test notification");
        notification.set_body(Some("Desktop notifications are working."));
        if let Some(application) = self.window.application() {
            application.send_notification(Some("settings-test"), &notification);
            self.set_status("Test notification sent.");
        } else {
            self.set_status("Could not send a test notification.");
        }
    }

    fn action_row(
        &self,
        title: &str,
        subtitle: &str,
        button_label: &str,
    ) -> (adw::ActionRow, gtk::Button) {
        let row = adw::ActionRow::builder()
            .title(title)
            .subtitle(subtitle)
            .build();
        let button = gtk::Button::with_label(button_label);
        button.set_valign(gtk::Align::Center);
        row.add_suffix(&button);
        (row, button)
    }

    fn show_login(self: &Rc<Self>, provider_id: &str) {
        if let Some(dialog) = self.login_dialog.borrow().as_ref() {
            dialog.window.present();
            return;
        }
        let dialog = LoginDialog::new(&self.window, &self.login, provider_id);
        let weak = Rc::downgrade(self);
        let login_actor = self.login.clone();
        dialog.window.connect_close_request(move |_| {
            if let Some(view) = weak.upgrade() {
                view.login_dialog.borrow_mut().take();
            }
            let _ = login_actor.try_send(LoginRequest::Cancel);
            glib::Propagation::Proceed
        });
        dialog.window.present();
        self.login_dialog.replace(Some(dialog));
        if self
            .login
            .try_send(LoginRequest::Start {
                provider_id: provider_id.to_owned(),
            })
            .is_err()
        {
            if let Some(dialog) = self.login_dialog.borrow().as_ref() {
                dialog.status.set_text("Sign-in service is busy or closed.");
            }
        }
    }
}

struct LoginDialog {
    window: gtk::Window,
    status: gtk::Label,
    url: gtk::Entry,
    code: gtk::Entry,
    open_button: gtk::Button,
    continue_button: gtk::Button,
    close_button: gtk::Button,
}

impl LoginDialog {
    fn new(parent: &adw::PreferencesWindow, actor: &LoginActor, provider_id: &str) -> Self {
        let window = gtk::Window::builder()
            .title(format!("Sign in to {}", provider_id.to_uppercase()))
            .default_width(520)
            .default_height(360)
            .transient_for(parent)
            .modal(true)
            .build();
        let box_ = gtk::Box::new(gtk::Orientation::Vertical, 12);
        box_.set_margin_top(20);
        box_.set_margin_bottom(20);
        box_.set_margin_start(20);
        box_.set_margin_end(20);
        let status = gtk::Label::new(Some("Starting the sign-in flow…"));
        status.set_wrap(true);
        status.set_xalign(0.0);
        box_.append(&status);
        let url = gtk::Entry::new();
        url.set_placeholder_text(Some("Waiting for an authorization link…"));
        url.set_editable(false);
        box_.append(&url);
        let actions = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let open_button = gtk::Button::with_label("Open in browser");
        open_button.set_sensitive(false);
        let url_for_open = url.clone();
        let status_for_open = status.clone();
        open_button.connect_clicked(move |_| {
            let link = url_for_open.text();
            if link.starts_with("https://") && !link.chars().any(char::is_whitespace) {
                let status = status_for_open.clone();
                gio::AppInfo::launch_default_for_uri_async(
                    link.as_str(),
                    None::<&gio::AppLaunchContext>,
                    None::<&gio::Cancellable>,
                    move |result| {
                        if result.is_err() {
                            status.set_text("Could not open the authorization link.");
                        }
                    },
                );
            }
        });
        actions.append(&open_button);
        if provider_id == "codex" {
            let terminal_button = gtk::Button::with_label("Use terminal");
            let status_for_terminal = status.clone();
            let app_for_terminal = window.application();
            terminal_button.connect_clicked(move |_| {
                status_for_terminal.set_text("Opening Codex login in a terminal…");
                if let Some(application) = &app_for_terminal {
                    application.activate_action("login-terminal", None);
                }
            });
            actions.append(&terminal_button);
        }
        let copy = gtk::Button::with_label("Copy link");
        let url_for_copy = url.clone();
        let window_for_copy = window.clone();
        copy.connect_clicked(move |_| {
            if let Some(display) = gtk::gdk::Display::default() {
                display.clipboard().set_text(&url_for_copy.text());
            }
            let _ = &window_for_copy;
        });
        actions.append(&copy);
        box_.append(&actions);
        let code = gtk::Entry::new();
        code.set_placeholder_text(Some("Code from the browser"));
        code.set_visibility(false);
        code.set_visible(false);
        box_.append(&code);
        let submit = gtk::Button::with_label("Continue");
        submit.add_css_class("suggested-action");
        submit.set_halign(gtk::Align::End);
        submit.set_visible(false);
        let actor_submit = actor.clone();
        let code_submit = code.clone();
        let status_submit = status.clone();
        submit.connect_clicked(move |_| {
            let code = code_submit.text().to_string();
            code_submit.set_text("");
            if code.is_empty() {
                return;
            }
            if actor_submit
                .try_send(LoginRequest::SubmitCode { code })
                .is_ok()
            {
                status_submit.set_text("Finishing sign-in…");
            } else {
                status_submit.set_text("Sign-in service is busy or closed.");
            }
        });
        box_.append(&submit);
        let close_button = gtk::Button::with_label("Cancel");
        close_button.set_halign(gtk::Align::End);
        let window_cancel = window.clone();
        close_button.connect_clicked(move |_| window_cancel.close());
        box_.append(&close_button);
        window.set_child(Some(&box_));
        Self {
            window,
            status,
            url,
            code,
            open_button,
            continue_button: submit,
            close_button,
        }
    }

    fn set_url(&self, url: &str) {
        self.url.set_text(url);
        self.open_button.set_sensitive(url.starts_with("https://"));
        self.status
            .set_text("Open the link in your browser, then enter the code it provides.");
    }

    fn show_prompt(&self, prompt: codexbar_backend::login::LoginPrompt) {
        match prompt {
            codexbar_backend::login::LoginPrompt::OpenBrowser => {
                self.status
                    .set_text("Open the authorization link in your browser.");
            }
            codexbar_backend::login::LoginPrompt::PasteCode => {
                self.code.set_visible(true);
                self.continue_button.set_visible(true);
                self.status.set_text("Paste the browser code and continue.");
            }
        }
    }
}

fn combo_control(title: &str, options: &[(&str, &str)], current: &str) -> adw::ComboRow {
    let row = adw::ComboRow::builder().title(title).build();
    let model = gtk::StringList::new(&[]);
    for (label, _) in options {
        model.append(label);
    }
    row.set_model(Some(&model));
    let selected = options
        .iter()
        .position(|(_, value)| *value == current)
        .unwrap_or(0);
    row.set_selected(selected as u32);
    row
}

fn replace_group_rows(
    group: Option<&adw::PreferencesGroup>,
    previous_rows: &RefCell<Vec<adw::PreferencesRow>>,
    rows: Vec<adw::PreferencesRow>,
) {
    let Some(group) = group else {
        return;
    };
    let mut previous_rows = previous_rows.borrow_mut();
    for row in previous_rows.drain(..) {
        group.remove(&row);
    }
    for row in rows {
        group.add(&row);
        previous_rows.push(row);
    }
}

fn safe_settings_error(error: &SettingsError) -> String {
    format!(
        "{} ({})",
        format!("{:?}", error.category).to_lowercase(),
        error.operation
    )
}

fn available_timezones() -> Vec<String> {
    fn descend(path: &PathBuf, base: &PathBuf, zones: &mut Vec<String>) {
        let Ok(entries) = fs::read_dir(path) else {
            return;
        };
        for entry in entries.flatten() {
            let item = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.')
                || matches!(
                    name.as_str(),
                    "posix" | "right" | "SystemV" | "localtime" | "posixrules"
                )
            {
                continue;
            }
            if item.is_dir() {
                descend(&item, base, zones);
            } else if item.is_file() {
                if let Ok(zone) = item.strip_prefix(base) {
                    let zone = zone
                        .to_string_lossy()
                        .replace(std::path::MAIN_SEPARATOR, "/");
                    if zone.contains('/') || zone == "UTC" || zone == "GMT" {
                        zones.push(zone);
                    }
                }
            }
        }
    }
    let root = PathBuf::from("/usr/share/zoneinfo");
    let mut zones = Vec::new();
    descend(&root, &root, &mut zones);
    zones.sort();
    zones.dedup();
    if zones.is_empty() {
        zones.push("UTC".to_owned());
    }
    zones
}
