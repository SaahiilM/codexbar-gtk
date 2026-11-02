use std::{
    cell::RefCell,
    path::PathBuf,
    rc::Rc,
    sync::mpsc::{self, Receiver, TryRecvError},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use codexbar_backend::{
    cli::{discover_executable, CliService, SharedCliService},
    controller::{
        ControllerCommand, ControllerSnapshot, RefreshControllerConfig, RefreshControllerHandle,
    },
    currency::CurrencyService,
    login::{LoginActor, LoginUiEvent},
    presentation::{
        sessions_view_model, spend_view_model, tray_summary, SpendViewRequest, TraySummaryRequest,
    },
    settings::{SettingsActor, SettingsResponse},
    updates::{self, UpdateCheck, UpdateCheckRequest, UpdateError, UpdateRelation},
    BackendEvent, BackendEventKind, BackendState, BackendStatus,
};
use codexbar_core::{
    currency::CurrencyCatalog, history::HistoryStore, preferences::PreferencesStore,
};
use codexbar_gtk_native::dashboard::project_dashboard;
use codexbar_gtk_native::dashboard_widget::DashboardView;
use codexbar_gtk_native::panel_widget::PanelView;
use codexbar_gtk_native::usage_pages::{SessionsView, SpendView};
use gio::prelude::*;
use gtk::prelude::*;
use libadwaita as adw;
use libadwaita::prelude::*;
use tokio::sync::{mpsc as tokio_mpsc, oneshot, watch};

use codexbar_gtk_native::{
    icons::{render_meter, render_tray_summary, RequestedSize},
    tray::{NativeTray, TrayPresentation},
    x11_placement::PanelAnchor,
    BuildMetadata, EventInbox, LaunchRoute, Page, APPLICATION_ID,
};

mod settings_window;

const APP_NAME: &str = "CodexBar GTK";
const PROJECT_URL: &str = "https://github.com/SaahiilM/codexbar-gtk";

enum BackendUiOperation {
    CheckUpdates(UpdateCheckRequest),
    Restart,
    LaunchCodexLoginTerminal,
}

enum BackendUiResult {
    Update(Result<UpdateCheck, UpdateError>),
    Restart(codexbar_backend::application::NativeRestartAction),
    TerminalLogin(
        Result<
            codexbar_backend::application::TerminalLoginResult,
            codexbar_backend::application::LoginOperationError,
        >,
    ),
}

struct BackendBridge {
    state: watch::Receiver<BackendState<ControllerSnapshot>>,
    events: tokio_mpsc::Receiver<BackendEvent>,
    refresh: tokio_mpsc::Sender<ControllerCommand>,
    settings: SettingsActor,
    settings_responses: codexbar_backend::settings::SettingsResponseReceiver,
    login: LoginActor,
    login_events: codexbar_backend::login::LoginUiReceiver,
    preferences: std::sync::Arc<PreferencesStore>,
    currencies: std::sync::Arc<CurrencyService>,
    ui_operations: tokio_mpsc::UnboundedSender<BackendUiOperation>,
    ui_results: Receiver<BackendUiResult>,
}

struct BackendWorker {
    ready: Receiver<Result<BackendBridge, ()>>,
    finished: Receiver<()>,
    shutdown: Option<oneshot::Sender<()>>,
    thread: Option<JoinHandle<()>>,
}

impl BackendWorker {
    fn start() -> Result<Self, ()> {
        let (ready_tx, ready) = mpsc::sync_channel(1);
        let (finished_tx, finished) = mpsc::sync_channel(1);
        let (shutdown, shutdown_rx) = oneshot::channel();
        let (ui_operations, mut ui_operation_rx) = tokio_mpsc::unbounded_channel();
        let (ui_result_tx, ui_results) = mpsc::channel();
        let worker = thread::Builder::new()
            .name("codexbar-backend-runtime".to_owned())
            .spawn(move || {
                let result = tokio::runtime::Builder::new_multi_thread()
                    .worker_threads(2)
                    .enable_all()
                    .build();
                match result {
                    Ok(runtime) => runtime.block_on(async move {
                        let mut shutdown_rx = shutdown_rx;
                        let preferences = std::sync::Arc::new(PreferencesStore::new(
                            PreferencesStore::default_path(),
                        ));
                        let history = std::sync::Arc::new(HistoryStore::new(
                            HistoryStore::default_path(),
                            codexbar_core::history::RETENTION_DAYS,
                        ));
                        let currencies =
                            std::sync::Arc::new(CurrencyService::new(currency_cache_path()));
                        let preferred = preferences
                            .get("preferredCurrencyCode")
                            .and_then(|value| value.as_str().map(ToOwned::to_owned))
                            .unwrap_or_else(|| "auto".to_owned());
                        let currency_refresh = currencies.clone();
                        let currency_refresh_task = tokio::spawn(async move {
                            let _ = currency_refresh.ensure_rates(&preferred).await;
                        });
                        let default_executable = default_cli_executable();
                        let cli = service_from_preferences(&preferences, &default_executable);
                        let shared_cli = std::sync::Arc::new(SharedCliService::new(cli));
                        let mut controller = RefreshControllerHandle::start(
                            RefreshControllerConfig::with_shared_cli(
                                shared_cli.clone(),
                                preferences.clone(),
                                history,
                            ),
                        );
                        let refresh = controller.force_refresh_sender();
                        let home = std::env::var_os("HOME")
                            .map(PathBuf::from)
                            .unwrap_or_else(|| PathBuf::from("."));
                        let (settings, settings_responses) =
                            SettingsActor::start_with_currency_service(
                                &tokio::runtime::Handle::current(),
                                shared_cli.clone(),
                                preferences.clone(),
                                home,
                                default_executable,
                                refresh.clone(),
                                currencies.clone(),
                            );
                        let (login, login_events) =
                            LoginActor::start(&tokio::runtime::Handle::current(), shared_cli);
                        let settings_shutdown = settings.clone();
                        let login_shutdown = login.clone();
                        let bridge = BackendBridge {
                            state: controller.state(),
                            events: controller
                                .take_notification_receiver()
                                .expect("controller owns one notification stream"),
                            refresh,
                            settings,
                            settings_responses,
                            login,
                            login_events,
                            preferences,
                            currencies,
                            ui_operations,
                            ui_results,
                        };
                        if ready_tx.send(Ok(bridge)).is_err() {
                            settings_shutdown.shutdown().await;
                            login_shutdown.shutdown().await;
                            currency_refresh_task.abort();
                            let _ = currency_refresh_task.await;
                            let _ = controller.shutdown().await;
                            return;
                        }
                        'service: loop {
                            tokio::select! {
                                _ = &mut shutdown_rx => break 'service,
                                operation = ui_operation_rx.recv() => {
                                    match operation {
                                        Some(BackendUiOperation::CheckUpdates(request)) => {
                                            let result = tokio::select! {
                                                _ = &mut shutdown_rx => break 'service,
                                                result = updates::check(request) => result,
                                            };
                                            let _ = ui_result_tx.send(BackendUiResult::Update(result));
                                        }
                                        Some(BackendUiOperation::Restart) => {
                                            let result = codexbar_backend::application::request_native_restart();
                                            let _ = ui_result_tx.send(BackendUiResult::Restart(result));
                                        }
                                        Some(BackendUiOperation::LaunchCodexLoginTerminal) => {
                                            let package_dir = std::env::current_exe()
                                                .ok()
                                                .and_then(|path| path.parent().map(PathBuf::from))
                                                .unwrap_or_else(|| PathBuf::from("."));
                                            let codex = discover_executable("codex", Some("CODEX_CLI"), &package_dir).ok();
                                            let terminal = ["konsole", "gnome-terminal", "xterm", "kitty", "alacritty"]
                                                .iter()
                                                .find_map(|candidate| codexbar_backend::cli::find_executable_on_path(candidate));
                                            let result = codexbar_backend::application::launch_codex_login_terminal_with(
                                                codex,
                                                terminal,
                                                &mut codexbar_backend::application::SystemApplicationLauncher,
                                            );
                                            let _ = ui_result_tx.send(BackendUiResult::TerminalLogin(result));
                                        }
                                        None => break 'service,
                                    }
                                }
                            }
                        }
                        settings_shutdown.shutdown().await;
                        login_shutdown.shutdown().await;
                        currency_refresh_task.abort();
                        let _ = currency_refresh_task.await;
                        let _ = controller.shutdown().await;
                    }),
                    Err(_) => {
                        let _ = ready_tx.send(Err(()));
                    }
                }
                let _ = finished_tx.send(());
            })
            .map_err(|_| ())?;
        Ok(Self {
            ready,
            finished,
            shutdown: Some(shutdown),
            thread: Some(worker),
        })
    }

    fn request_shutdown(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
    }

    fn is_finished(&self) -> bool {
        matches!(
            self.finished.try_recv(),
            Ok(()) | Err(TryRecvError::Disconnected)
        ) && self.thread.as_ref().is_some_and(JoinHandle::is_finished)
    }

    fn join_finished(&mut self) {
        if self.is_finished() {
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
        }
    }
}

fn default_cli_executable() -> PathBuf {
    let package_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("."));
    discover_executable("codexbar", Some("CODEXBAR_CLI"), &package_dir)
        .unwrap_or_else(|_| PathBuf::from("codexbar"))
}

fn service_from_preferences(
    preferences: &PreferencesStore,
    default_executable: &std::path::Path,
) -> std::sync::Arc<CliService> {
    let configured_path = preferences
        .get("cliPath")
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .filter(|path| !path.trim().is_empty());
    let executable = configured_path
        .map(PathBuf::from)
        .unwrap_or_else(|| default_executable.to_path_buf());
    let timezone = preferences
        .get("costUsageBucketTimeZone")
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .filter(|timezone| !timezone.is_empty())
        .map(Into::into);
    std::sync::Arc::new(CliService::new(executable, timezone))
}

struct NativeApp {
    application: adw::Application,
    metadata: BuildMetadata,
    worker: Option<BackendWorker>,
    bridge: Option<BackendBridge>,
    window: Option<gtk::ApplicationWindow>,
    dashboard: Option<DashboardView>,
    dashboard_sequence: Option<u64>,
    dashboard_rendered_at: Option<Instant>,
    sessions_view: Option<SessionsView>,
    sessions_sequence: Option<u64>,
    sessions_rendered_at: Option<Instant>,
    spend_view: Option<SpendView>,
    spend_sequence: Option<u64>,
    spend_rendered_at: Option<Instant>,
    spend_range: String,
    settings_window: Option<Rc<settings_window::SettingsWindow>>,
    update_dialog: Option<adw::MessageDialog>,
    panel_window: Option<gtk::ApplicationWindow>,
    panel: Option<PanelView>,
    panel_anchor: Rc<RefCell<Option<PanelAnchor>>>,
    tray: Option<NativeTray>,
    panel_sequence: Option<u64>,
    panel_rendered_at: Option<Instant>,
    state_label: Option<gtk::Label>,
    events_label: Option<gtk::Label>,
    route: LaunchRoute,
    pending_panel: bool,
    backend_start_failed: bool,
    shutting_down: bool,
    worker_stopped: bool,
    restart_after_shutdown: bool,
    hold_guard: Option<gio::ApplicationHoldGuard>,
    event_inbox: EventInbox<BackendEvent>,
}

impl NativeApp {
    fn new(application: adw::Application, metadata: BuildMetadata) -> Self {
        Self {
            application,
            metadata,
            worker: None,
            bridge: None,
            window: None,
            dashboard: None,
            dashboard_sequence: None,
            dashboard_rendered_at: None,
            sessions_view: None,
            sessions_sequence: None,
            sessions_rendered_at: None,
            spend_view: None,
            spend_sequence: None,
            spend_rendered_at: None,
            spend_range: "30 days".to_owned(),
            settings_window: None,
            update_dialog: None,
            panel_window: None,
            panel: None,
            panel_anchor: Rc::new(RefCell::new(None)),
            tray: None,
            panel_sequence: None,
            panel_rendered_at: None,
            state_label: None,
            events_label: None,
            route: LaunchRoute::Default,
            pending_panel: false,
            backend_start_failed: false,
            shutting_down: false,
            worker_stopped: false,
            restart_after_shutdown: false,
            hold_guard: None,
            event_inbox: EventInbox::default(),
        }
    }

    fn start(&mut self) {
        codexbar_gtk_native::icons::install_theme();
        self.hold_guard = Some(self.application.hold());
        match NativeTray::start(&self.application.clone().upcast::<gio::Application>()) {
            Ok(tray) => self.tray = Some(tray),
            Err(error) => eprintln!("{APP_NAME}: tray integration unavailable: {error}"),
        }
        match BackendWorker::start() {
            Ok(worker) => self.worker = Some(worker),
            Err(_) => {
                self.backend_start_failed = true;
                self.set_backend_status("Backend worker could not start.");
            }
        }
    }

    fn dispatch_arguments(&mut self, arguments: &[std::ffi::OsString]) {
        self.dispatch_route(codexbar_gtk_native::route_from_arguments(arguments));
    }

    fn dispatch_route(&mut self, route: LaunchRoute) {
        if self.shutting_down {
            return;
        }
        if route != LaunchRoute::Settings {
            if let Some(settings) = self.settings_window.as_ref() {
                settings.hide();
            }
        }
        if route != LaunchRoute::Panel {
            self.hide_panel();
        }
        self.route = route;
        self.pending_panel = route == LaunchRoute::Panel;
        if route == LaunchRoute::About {
            self.show_about();
            return;
        }
        if self.pending_panel {
            if self.backend_has_completed_initial_refresh() {
                self.pending_panel = false;
                self.show_route(route);
            }
            return;
        }
        self.show_route(route);
    }

    fn show_route(&mut self, route: LaunchRoute) {
        if route == LaunchRoute::Settings {
            self.show_settings();
            return;
        }
        if matches!(route, LaunchRoute::Default | LaunchRoute::Page(Page::Usage)) {
            self.show_dashboard(route);
            return;
        }
        if route == LaunchRoute::Page(Page::Sessions) {
            self.show_sessions();
            return;
        }
        if route == LaunchRoute::Page(Page::Spend) {
            self.show_spend();
            return;
        }
        if route == LaunchRoute::Panel {
            self.show_panel();
            return;
        }
        let window = self.ensure_main_window();
        let (title, body, width, height) = match route {
            LaunchRoute::Panel => unreachable!("panel route has a separate native window"),
            LaunchRoute::Settings => unreachable!("Settings uses the native PreferencesWindow"),
            LaunchRoute::Page(page) => (
                format!("{APP_NAME} — {} — Native UI bootstrap", page.label()),
                page_description(page),
                860,
                560,
            ),
            LaunchRoute::Default => (
                format!("{APP_NAME} — Dashboard"),
                "Dashboard is not available.",
                980,
                720,
            ),
            LaunchRoute::About => unreachable!("about route is shown separately"),
        };
        window.set_title(Some(&title));
        window.set_default_size(width, height);

        let content = gtk::Box::new(gtk::Orientation::Vertical, 16);
        content.set_margin_top(24);
        content.set_margin_bottom(24);
        content.set_margin_start(28);
        content.set_margin_end(28);

        let heading = gtk::Label::new(Some(&title));
        heading.add_css_class("title-1");
        heading.set_xalign(0.0);
        heading.set_wrap(true);
        content.append(&heading);

        let explanation = gtk::Label::new(Some(body));
        explanation.set_xalign(0.0);
        explanation.set_wrap(true);
        content.append(&explanation);

        let build = gtk::Label::new(Some(&format!("Version {}", self.metadata.display())));
        build.set_xalign(0.0);
        build.add_css_class("dim-label");
        content.append(&build);

        let initial_status = if self.backend_start_failed {
            "Backend worker could not start.".to_owned()
        } else {
            self.bridge
                .as_ref()
                .map(|bridge| status_label(&bridge.state.borrow()))
                .unwrap_or_else(|| "Backend starting…".to_owned())
        };
        let status = gtk::Label::new(Some(&initial_status));
        status.set_xalign(0.0);
        status.set_wrap(true);
        content.append(&status);

        let progress = self.event_inbox.progress();
        let events = gtk::Label::new(Some(&format!(
            "Backend events received: {} · queued: {}",
            progress.received,
            self.event_inbox.len()
        )));
        events.set_xalign(0.0);
        events.add_css_class("dim-label");
        content.append(&events);

        let controls = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let refresh_button = gtk::Button::with_label("Refresh");
        controls.append(&refresh_button);
        let about_button = gtk::Button::with_label("About");
        controls.append(&about_button);
        let quit_button = gtk::Button::with_label("Quit");
        controls.append(&quit_button);
        content.append(&controls);

        window.set_child(Some(&content));
        self.state_label = Some(status);
        self.events_label = Some(events);
        self.install_window_actions(&refresh_button, &about_button, &quit_button);
        window.present();
    }

    fn show_dashboard(&mut self, route: LaunchRoute) {
        self.hide_panel();
        let window = self.ensure_main_window();
        let title = match route {
            LaunchRoute::Page(Page::Usage) => format!("{APP_NAME} — Usage"),
            _ => format!("{APP_NAME} — Dashboard"),
        };
        window.set_title(Some(&title));
        window.set_default_size(980, 720);
        if self.dashboard.is_none() {
            self.dashboard = Some(DashboardView::new());
        }
        if self.backend_start_failed {
            self.dashboard
                .as_ref()
                .expect("dashboard was created")
                .show_backend_start_error();
        } else if let Some(bridge) = &self.bridge {
            let state = bridge.state.borrow().clone();
            self.render_dashboard_state(&state);
        }
        let dashboard_widget = self
            .dashboard
            .as_ref()
            .expect("dashboard was created")
            .widget();
        window.set_child(Some(&dashboard_widget));
        window.present();
    }

    fn render_dashboard_state(&mut self, state: &BackendState<ControllerSnapshot>) {
        let Some(bridge) = &self.bridge else {
            return;
        };
        let preferences = bridge.preferences.values();
        // `catalog()` is an in-memory cache clone. Rate refresh remains on the
        // Tokio worker and can never block GTK's main context.
        let currencies: CurrencyCatalog = bridge.currencies.catalog();
        let model = project_dashboard(state, &preferences, &currencies, chrono::Utc::now());
        if let Some(dashboard) = &self.dashboard {
            dashboard.render(&model);
        }
        self.dashboard_sequence = Some(state.sequence);
        self.dashboard_rendered_at = Some(Instant::now());
    }

    fn show_sessions(&mut self) {
        self.hide_panel();
        let window = self.ensure_main_window();
        window.set_title(Some(&format!("{APP_NAME} — Sessions")));
        window.set_default_size(920, 700);
        if self.sessions_view.is_none() {
            self.sessions_view = Some(SessionsView::new(&self.application));
        }
        if self.backend_start_failed {
            self.sessions_view
                .as_ref()
                .expect("Sessions page was created")
                .show_backend_start_error();
        } else if let Some(bridge) = &self.bridge {
            let state = bridge.state.borrow().clone();
            self.render_sessions_state(&state);
        }
        let widget = self
            .sessions_view
            .as_ref()
            .expect("Sessions page was created")
            .widget();
        window.set_child(Some(&widget));
        window.present();
    }

    fn render_sessions_state(&mut self, state: &BackendState<ControllerSnapshot>) {
        if let Some(view) = &self.sessions_view {
            view.render(&sessions_view_model(state));
        }
        self.sessions_sequence = Some(state.sequence);
        self.sessions_rendered_at = Some(Instant::now());
    }

    fn show_spend(&mut self) {
        self.hide_panel();
        let window = self.ensure_main_window();
        window.set_title(Some(&format!("{APP_NAME} — Usage & Spend")));
        window.set_default_size(1080, 820);
        if self.spend_view.is_none() {
            self.spend_view = Some(SpendView::new(&self.application, &self.spend_range));
        }
        if self.backend_start_failed {
            self.spend_view
                .as_ref()
                .expect("Spend page was created")
                .show_backend_start_error();
        } else if let Some(bridge) = &self.bridge {
            let state = bridge.state.borrow().clone();
            self.render_spend_state(&state);
        }
        let widget = self
            .spend_view
            .as_ref()
            .expect("Spend page was created")
            .widget();
        window.set_child(Some(&widget));
        window.present();
    }

    fn render_spend_state(&mut self, state: &BackendState<ControllerSnapshot>) {
        let Some(bridge) = &self.bridge else {
            return;
        };
        let preferred_currency = bridge
            .preferences
            .get("preferredCurrencyCode")
            .and_then(|value| value.as_str().map(ToOwned::to_owned))
            .unwrap_or_else(|| "auto".to_owned());
        let currencies = bridge.currencies.clone();
        let model = spend_view_model(
            state,
            &SpendViewRequest {
                selected_range: self.spend_range.clone(),
                preferred_currency,
            },
            &currencies,
        );
        if let Some(view) = &self.spend_view {
            view.render(&model);
        }
        self.spend_sequence = Some(state.sequence);
        self.spend_rendered_at = Some(Instant::now());
    }

    fn request_spend_range(&mut self, value: &str) {
        self.spend_range = match value {
            "7 days" | "7d" => "7 days".to_owned(),
            "90 days" | "90d" => "90 days".to_owned(),
            "All" => "All".to_owned(),
            _ => "30 days".to_owned(),
        };
        if self.route == LaunchRoute::Page(Page::Spend) {
            if let Some(state) = self
                .bridge
                .as_ref()
                .map(|bridge| bridge.state.borrow().clone())
            {
                self.render_spend_state(&state);
            }
        }
    }

    fn ensure_panel_window(&mut self) -> gtk::ApplicationWindow {
        if let Some(window) = &self.panel_window {
            return window.clone();
        }
        let window = gtk::ApplicationWindow::builder()
            .application(&self.application)
            .title(format!("{APP_NAME} — Panel"))
            .default_width(420)
            .default_height(420)
            .decorated(false)
            .resizable(false)
            .build();
        let panel = PanelView::new();
        window.set_child(Some(&panel.widget()));

        let close_window = window.clone();
        let keys = gtk::EventControllerKey::new();
        keys.connect_key_pressed(move |_, key, _, _| {
            if key == gtk::gdk::Key::Escape {
                close_window.hide();
                glib::Propagation::Stop
            } else {
                glib::Propagation::Proceed
            }
        });
        window.add_controller(keys);
        window.connect_close_request(|window| {
            window.hide();
            glib::Propagation::Stop
        });

        let placement_window = window.clone();
        let anchor_state = self.panel_anchor.clone();
        window.connect_map(move |_| {
            let placement_window = placement_window.clone();
            let anchor_state = anchor_state.clone();
            glib::timeout_add_local_once(Duration::from_millis(150), move || {
                let anchor = anchor_state.borrow().clone();
                let _ = codexbar_gtk_native::x11_placement::place_panel(
                    &placement_window,
                    anchor.as_ref(),
                );
            });
        });
        self.panel = Some(panel);
        self.panel_window = Some(window.clone());
        window
    }

    fn show_panel(&mut self) {
        let window = self.ensure_panel_window();
        if self.backend_start_failed {
            if let Some(panel) = &self.panel {
                panel.show_backend_start_error();
            }
        } else if let Some(bridge) = &self.bridge {
            let state = bridge.state.borrow().clone();
            self.render_panel_state(&state);
        }
        window.present();
    }

    fn hide_panel(&self) {
        if let Some(window) = &self.panel_window {
            window.hide();
        }
    }

    fn panel_is_open_or_pending(&self) -> bool {
        self.pending_panel
            || self
                .panel_window
                .as_ref()
                .is_some_and(|window| window.is_visible())
    }

    fn open_panel(&mut self, anchor: Option<PanelAnchor>) {
        if self.panel_is_open_or_pending() {
            return;
        }
        *self.panel_anchor.borrow_mut() = anchor;
        if self.backend_has_completed_initial_refresh() || self.backend_start_failed {
            self.pending_panel = false;
            self.show_route(LaunchRoute::Panel);
        } else {
            self.pending_panel = true;
        }
    }

    fn toggle_panel(&mut self, anchor: Option<PanelAnchor>) -> bool {
        if self.pending_panel {
            self.pending_panel = false;
            return false;
        }
        if self
            .panel_window
            .as_ref()
            .is_some_and(|window| window.is_visible())
        {
            self.hide_panel();
            self.pending_panel = false;
            return false;
        }
        *self.panel_anchor.borrow_mut() = anchor;
        if self.backend_has_completed_initial_refresh() || self.backend_start_failed {
            self.pending_panel = false;
            self.show_route(LaunchRoute::Panel);
        } else {
            self.pending_panel = true;
        }
        true
    }

    fn render_panel_state(&mut self, state: &BackendState<ControllerSnapshot>) {
        let Some(bridge) = &self.bridge else {
            return;
        };
        let preferences = bridge.preferences.values();
        let currencies: CurrencyCatalog = bridge.currencies.catalog();
        let model = project_dashboard(state, &preferences, &currencies, chrono::Utc::now());
        if let Some(panel) = &self.panel {
            panel.render(&model);
        }
        self.panel_sequence = Some(state.sequence);
        self.panel_rendered_at = Some(Instant::now());
    }

    fn install_window_actions(
        &self,
        refresh_button: &gtk::Button,
        about_button: &gtk::Button,
        quit_button: &gtk::Button,
    ) {
        // The actions are attached at application creation; buttons dispatch
        // Gio actions so secondary instances use the same path as the UI.
        refresh_button.set_action_name(Some("app.refresh"));
        about_button.set_action_name(Some("app.about"));
        quit_button.set_action_name(Some("app.quit"));
    }

    fn ensure_main_window(&mut self) -> gtk::ApplicationWindow {
        if let Some(window) = &self.window {
            return window.clone();
        }
        let window = gtk::ApplicationWindow::builder()
            .application(&self.application)
            .title(format!("{APP_NAME} — Native UI bootstrap"))
            .default_width(860)
            .default_height(560)
            .build();
        let application = self.application.clone();
        window.connect_close_request(move |_| {
            application.activate_action("quit", None);
            glib::Propagation::Stop
        });
        self.window = Some(window.clone());
        window
    }

    fn show_about(&self) {
        let about = adw::AboutWindow::builder()
            .application(&self.application)
            .application_name(APP_NAME)
            .version(self.metadata.display())
            .developer_name("CodexBar GTK contributors")
            .comments("Native GTK4/libadwaita desktop app for CodexBar provider usage.")
            .website("https://github.com/SaahiilM/codexbar-gtk")
            .build();
        about.set_title(Some("About CodexBar GTK"));
        if let Some(window) = &self.window {
            about.set_transient_for(Some(window));
        }
        let application = self.application.clone();
        let main_window = self.window.clone();
        about.connect_close_request(move |_| {
            if main_window
                .as_ref()
                .is_none_or(|window| !window.is_visible())
            {
                application.activate_action("quit", None);
            }
            glib::Propagation::Proceed
        });
        about.present();
    }

    fn poll_backend(&mut self) {
        if self.bridge.is_none() {
            if let Some(worker) = &self.worker {
                match worker.ready.try_recv() {
                    Ok(Ok(bridge)) => self.bridge = Some(bridge),
                    Ok(Err(())) | Err(TryRecvError::Disconnected) => {
                        self.backend_start_failed = true;
                        self.set_backend_status("Backend worker could not start.");
                    }
                    Err(TryRecvError::Empty) => {}
                }
            }
        }

        let tray_preferences = self
            .bridge
            .as_ref()
            .map(|bridge| bridge.preferences.clone());
        let mut latest_state = None;
        let mut settings_responses = Vec::<SettingsResponse>::new();
        let mut login_events = Vec::<LoginUiEvent>::new();
        let mut ui_results = Vec::<BackendUiResult>::new();
        if let Some(bridge) = &mut self.bridge {
            latest_state = Some(bridge.state.borrow_and_update().clone());
            while let Ok(response) = bridge.settings_responses.try_recv() {
                settings_responses.push(response);
            }
            while let Ok(event) = bridge.login_events.try_recv() {
                login_events.push(event);
            }
            while let Ok(result) = bridge.ui_results.try_recv() {
                ui_results.push(result);
            }
            loop {
                match bridge.events.try_recv() {
                    Ok(event) => {
                        self.event_inbox.push(event.sequence, event);
                    }
                    Err(tokio_mpsc::error::TryRecvError::Empty) => break,
                    Err(tokio_mpsc::error::TryRecvError::Disconnected) => break,
                }
            }
        }
        self.deliver_notifications();
        for result in ui_results {
            self.handle_backend_ui_result(result);
        }
        if self.route == LaunchRoute::Settings && self.settings_window.is_none() {
            self.show_settings();
        }
        if let Some(settings) = self.settings_window.as_ref() {
            for response in settings_responses {
                settings.handle_response(response);
            }
            for event in login_events {
                settings.handle_login_event(event);
            }
        }
        if let (Some(state), Some(preferences)) = (latest_state, tray_preferences) {
            self.set_backend_status(&status_label(&state));
            self.update_tray(&tray_presentation(&state, &preferences));
            if let Some(label) = &self.events_label {
                let progress = self.event_inbox.progress();
                let suffix = progress
                    .last_sequence
                    .map(|sequence| format!(" (last sequence {sequence})"))
                    .unwrap_or_default();
                let gap = if progress.sequence_gaps == 0 {
                    String::new()
                } else {
                    format!(" · {} sequence gap(s)", progress.sequence_gaps)
                };
                label.set_text(&format!(
                    "Backend events received: {} · queued: {}{suffix}{gap}",
                    progress.received,
                    self.event_inbox.len()
                ));
            }
            let should_render = self.dashboard.is_some()
                && (self.dashboard_sequence != Some(state.sequence)
                    || self
                        .dashboard_rendered_at
                        .is_none_or(|last| last.elapsed() >= Duration::from_secs(5)));
            if should_render {
                self.render_dashboard_state(&state);
            }
            let should_render_sessions = self.route == LaunchRoute::Page(Page::Sessions)
                && self.sessions_view.is_some()
                && (self.sessions_sequence != Some(state.sequence)
                    || self
                        .sessions_rendered_at
                        .is_none_or(|last| last.elapsed() >= Duration::from_secs(5)));
            if should_render_sessions {
                self.render_sessions_state(&state);
            }
            let should_render_spend = self.route == LaunchRoute::Page(Page::Spend)
                && self.spend_view.is_some()
                && (self.spend_sequence != Some(state.sequence)
                    || self
                        .spend_rendered_at
                        .is_none_or(|last| last.elapsed() >= Duration::from_secs(5)));
            if should_render_spend {
                self.render_spend_state(&state);
            }
            let panel_visible = self
                .panel_window
                .as_ref()
                .is_some_and(|window| window.is_visible());
            let should_render_panel = panel_visible
                && (self.panel_sequence != Some(state.sequence)
                    || self
                        .panel_rendered_at
                        .is_none_or(|last| last.elapsed() >= Duration::from_secs(5)));
            if should_render_panel {
                self.render_panel_state(&state);
            }
            if self.pending_panel && state.status != BackendStatus::Idle {
                let refresh_complete = matches!(
                    state.status,
                    BackendStatus::Ready | BackendStatus::Failed | BackendStatus::Stopped
                );
                if refresh_complete {
                    self.pending_panel = false;
                    self.show_route(LaunchRoute::Panel);
                }
            }
        }

        if self.pending_panel && self.backend_start_failed {
            self.pending_panel = false;
            self.show_route(LaunchRoute::Panel);
        }

        if self.backend_start_failed {
            self.update_tray(&TrayPresentation {
                icon_name: "codexbar-gtk".to_owned(),
                title: APP_NAME.to_owned(),
                body: "Provider data unavailable\nUse Refresh to check again.".to_owned(),
                pixmap: Some(render_meter(
                    None,
                    "#10A37F",
                    RequestedSize {
                        width: 32,
                        height: 32,
                    },
                )),
                switcher_rows: Vec::new(),
            });
            if let Some(dashboard) = &self.dashboard {
                dashboard.show_backend_start_error();
            }
            if let Some(panel) = &self.panel {
                panel.show_backend_start_error();
            }
            if let Some(view) = &self.sessions_view {
                view.show_backend_start_error();
            }
            if let Some(view) = &self.spend_view {
                view.show_backend_start_error();
            }
        }

        if self.shutting_down {
            self.finish_shutdown_if_ready();
        }
    }

    fn backend_has_completed_initial_refresh(&self) -> bool {
        self.bridge.as_ref().is_some_and(|bridge| {
            matches!(
                bridge.state.borrow().status,
                BackendStatus::Ready | BackendStatus::Failed | BackendStatus::Stopped
            )
        })
    }

    fn deliver_notifications(&mut self) {
        while let Some(event) = self.event_inbox.pop_front() {
            if self.shutting_down {
                continue;
            }
            let BackendEventKind::Notification(policy_event) = event.kind;
            let content = codexbar_gtk_native::notifications::notification_content(&policy_event);
            let notification = gio::Notification::new(&content.title);
            notification.set_body(Some(&content.body));
            notification.set_priority(gio::NotificationPriority::Normal);
            self.application
                .send_notification(Some(&content.id), &notification);
        }
    }

    fn set_backend_status(&self, message: &str) {
        if let Some(label) = &self.state_label {
            label.set_text(message);
        }
    }

    fn request_refresh(&self) {
        if let Some(bridge) = &self.bridge {
            let _ = bridge.refresh.try_send(ControllerCommand::ForceRefresh);
        }
    }

    fn request_restart(&self) {
        let Some(bridge) = self.bridge.as_ref() else {
            self.set_backend_status("Restart is unavailable while the backend starts.");
            return;
        };
        let _ = bridge.ui_operations.send(BackendUiOperation::Restart);
    }

    fn request_codex_terminal_login(&self) {
        let Some(bridge) = self.bridge.as_ref() else {
            self.set_backend_status("Terminal login is unavailable while the backend starts.");
            return;
        };
        if bridge
            .ui_operations
            .send(BackendUiOperation::LaunchCodexLoginTerminal)
            .is_err()
        {
            self.set_backend_status("Terminal login service is closed.");
        }
    }

    fn request_update_check(&mut self) {
        if self
            .update_dialog
            .as_ref()
            .is_some_and(|dialog| dialog.is_visible())
        {
            return;
        }
        let Some(bridge) = self.bridge.as_ref() else {
            self.set_backend_status("Update check is unavailable while the backend starts.");
            return;
        };
        let current = updates::Version::new(
            self.metadata.marketing_version.clone(),
            self.metadata.build.to_string(),
        )
        .expect("bundled version metadata is validated at startup");
        let request =
            UpdateCheckRequest::new(current, update_check_version_url(), updates::MAX_TIMEOUT);
        if bridge
            .ui_operations
            .send(BackendUiOperation::CheckUpdates(request))
            .is_err()
        {
            self.show_update_result(Err(UpdateError::Network));
            return;
        }

        let dialog = adw::MessageDialog::new(
            self.window.as_ref(),
            Some("Checking for updates…"),
            Some("Reading the public version marker."),
        );
        dialog.add_response("close", "Close");
        dialog.set_default_response(Some("close"));
        dialog.present();
        self.update_dialog = Some(dialog);
    }

    fn handle_backend_ui_result(&mut self, result: BackendUiResult) {
        match result {
            BackendUiResult::Update(result) => self.show_update_result(result),
            BackendUiResult::Restart(action) => {
                self.restart_after_shutdown = action
                    == codexbar_backend::application::NativeRestartAction::ExecCurrentProcess;
                self.begin_shutdown();
            }
            BackendUiResult::TerminalLogin(result) => {
                if let Some(settings) = &self.settings_window {
                    settings.handle_terminal_login_result(result);
                }
            }
        }
    }

    fn show_update_result(&mut self, result: Result<UpdateCheck, UpdateError>) {
        if let Some(progress) = self.update_dialog.take() {
            progress.close();
        }
        let (heading, body) = match result {
            Err(error) => (
                "Couldn’t check for updates".to_owned(),
                format!(
                    "The update check failed: {error}. You can still open the project page and check manually."
                ),
            ),
            Ok(check) => {
                let current = display_update_version(&check.current);
                let latest = display_update_version(&check.latest);
                match check.relation {
                    UpdateRelation::Available => (
                        format!("Update available: {latest}"),
                        format!(
                            "You have {current}. This client is distributed as source; pull the latest changes in your checkout, run ./scripts/install.sh --no-autostart, then restart the app."
                        ),
                    ),
                    UpdateRelation::Current => (
                        "You’re up to date".to_owned(),
                        format!("CodexBar GTK {current} is the latest public build."),
                    ),
                    UpdateRelation::Ahead => (
                        "This build is newer than the public version".to_owned(),
                        format!("Installed: {current}\nPublic main: {latest}"),
                    ),
                }
            }
        };
        let dialog = adw::MessageDialog::new(self.window.as_ref(), Some(&heading), Some(&body));
        dialog.add_response("open", "Open project");
        dialog.add_response("close", "Close");
        dialog.set_response_appearance("open", adw::ResponseAppearance::Suggested);
        dialog.set_default_response(Some("close"));
        dialog.connect_response(None, |dialog, response| {
            if response == "open" {
                gio::AppInfo::launch_default_for_uri_async(
                    PROJECT_URL,
                    None::<&gio::AppLaunchContext>,
                    None::<&gio::Cancellable>,
                    |_| {},
                );
            }
            dialog.close();
        });
        dialog.present();
        self.update_dialog = Some(dialog);
    }

    fn update_tray(&self, presentation: &TrayPresentation) {
        if let Some(tray) = &self.tray {
            tray.update(presentation.clone());
        }
    }

    fn request_about(&mut self) {
        self.dispatch_route(LaunchRoute::About);
    }

    fn request_settings(&mut self) {
        self.dispatch_route(LaunchRoute::Settings);
    }

    fn show_settings(&mut self) {
        let Some(bridge) = self.bridge.as_ref() else {
            return;
        };
        if let Some(window) = self.settings_window.as_ref() {
            window.present();
            return;
        }
        let settings_actor = bridge.settings.clone();
        let login_actor = bridge.login.clone();
        let preferences = bridge.preferences.clone();
        let currencies = bridge.currencies.catalog();
        let window = settings_window::SettingsWindow::new(
            &self.application,
            settings_actor,
            login_actor,
            preferences,
            self.metadata.display(),
            &currencies,
        );
        window.present();
        self.settings_window = Some(window);
    }

    fn request_dashboard(&mut self) {
        self.dispatch_route(LaunchRoute::Default);
    }

    fn request_panel_toggle(&mut self) {
        let _ = self.toggle_panel(None);
    }

    fn request_panel_toggle_at(&mut self, x: i32, y: i32) {
        let anchor = codexbar_gtk_native::x11_placement::activation_anchor(x, y);
        let opened = self.toggle_panel(anchor);
        if opened && self.refresh_all_providers_on_menu_open() {
            self.request_refresh();
        }
    }

    fn request_panel_open_at(&mut self, x: i32, y: i32) {
        let anchor = codexbar_gtk_native::x11_placement::activation_anchor(x, y);
        self.open_panel(anchor);
        if self.refresh_all_providers_on_menu_open() {
            self.request_refresh();
        }
    }

    fn refresh_all_providers_on_menu_open(&self) -> bool {
        self.bridge
            .as_ref()
            .and_then(|bridge| bridge.preferences.get("refreshAllProvidersOnMenuOpen"))
            .and_then(|value| value.as_bool())
            .unwrap_or(true)
    }

    fn request_page(&mut self, name: &str) {
        self.dispatch_route(codexbar_gtk_native::route_from_page_action(name));
    }

    fn begin_shutdown(&mut self) {
        if self.shutting_down {
            return;
        }
        self.shutting_down = true;
        if let Some(tray) = &mut self.tray {
            tray.stop();
        }
        self.settings_window.take();
        self.panel_window.take();
        self.window.take();
        if let Some(worker) = &mut self.worker {
            worker.request_shutdown();
        } else {
            self.worker_stopped = true;
            self.hold_guard.take();
            if self.restart_after_shutdown && relaunch_current_process().is_err() {
                eprintln!("{APP_NAME}: could not replace the process during restart");
                std::process::exit(1);
            }
            self.application.quit();
        }
    }

    fn finish_shutdown_if_ready(&mut self) {
        if let Some(bridge) = &mut self.bridge {
            while let Ok(event) = bridge.events.try_recv() {
                self.event_inbox.push(event.sequence, event);
            }
        }
        let finished = self.worker.as_ref().is_none_or(BackendWorker::is_finished);
        if finished {
            if let Some(worker) = &mut self.worker {
                worker.join_finished();
            }
            self.worker_stopped = true;
            self.hold_guard.take();
            if self.restart_after_shutdown && relaunch_current_process().is_err() {
                eprintln!("{APP_NAME}: could not replace the process during restart");
                std::process::exit(1);
            }
            self.application.quit();
        }
    }
}

fn page_description(page: Page) -> &'static str {
    match page {
        Page::Usage => {
            "The native Usage dashboard with provider history charts and quota burndown."
        }
        Page::Sessions => "The native Sessions page with scan status and retained recent activity.",
        Page::Spend => "The native Usage & Spend page with cost history and token activity.",
    }
}

fn relaunch_current_process() -> std::io::Result<()> {
    let executable = std::env::current_exe()?;
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        Err(std::process::Command::new(executable)
            .args(arguments)
            .exec())
    }
    #[cfg(not(unix))]
    {
        std::process::Command::new(executable)
            .args(arguments)
            .spawn()
            .map(drop)
    }
}

fn currency_cache_path() -> PathBuf {
    if let Some(cache_home) = std::env::var_os("XDG_CACHE_HOME") {
        PathBuf::from(cache_home).join("codexbar-gtk/currency-rates.json")
    } else {
        std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".cache/codexbar-gtk/currency-rates.json")
    }
}

fn status_label(state: &BackendState<ControllerSnapshot>) -> String {
    match state.status {
        BackendStatus::Idle => "Backend is starting…".to_owned(),
        BackendStatus::Refreshing => format!("Refreshing · revision {}", state.sequence),
        BackendStatus::Ready => format!("Backend ready · revision {}", state.sequence),
        BackendStatus::Failed => format!("Backend refresh failed · revision {}", state.sequence),
        BackendStatus::Stopped => format!("Backend stopped · revision {}", state.sequence),
    }
}

fn display_update_version(version: &updates::Version) -> String {
    format!("{} ({})", version.marketing, version.build)
}

fn update_check_version_url() -> String {
    #[cfg(debug_assertions)]
    if let Ok(url) = std::env::var("CODEXBAR_NATIVE_TEST_UPDATE_URL") {
        if is_loopback_update_url(&url) {
            return url;
        }
    }
    updates::VERSION_URL.to_owned()
}

#[cfg(debug_assertions)]
fn is_loopback_update_url(url: &str) -> bool {
    url.starts_with("http://127.0.0.1:") || url.starts_with("http://[::1]:")
}

fn tray_preference(preferences: &PreferencesStore, key: &str, default: &str) -> String {
    preferences
        .get(key)
        .and_then(|value| value.as_str().map(str::to_owned))
        .unwrap_or_else(|| default.to_owned())
}

fn tray_presentation(
    state: &BackendState<ControllerSnapshot>,
    preferences: &PreferencesStore,
) -> TrayPresentation {
    if state.snapshot.is_none() {
        let body = match state.status {
            BackendStatus::Idle => "Loading provider usage…".to_owned(),
            BackendStatus::Refreshing => "Refreshing provider usage…".to_owned(),
            BackendStatus::Ready | BackendStatus::Failed => {
                "Provider data unavailable\nUse Refresh to check again.".to_owned()
            }
            BackendStatus::Stopped => "Provider refresh stopped.".to_owned(),
        };
        return TrayPresentation {
            icon_name: String::new(),
            title: APP_NAME.to_owned(),
            body,
            pixmap: Some(render_meter(
                None,
                "#10A37F",
                RequestedSize {
                    width: 32,
                    height: 32,
                },
            )),
            switcher_rows: Vec::new(),
        };
    }

    let summary = tray_summary(
        state,
        &TraySummaryRequest {
            unified_icon_source: tray_preference(preferences, "unifiedIconSource", "highest"),
            menu_bar_icon_style: tray_preference(preferences, "menuBarIconStyle", "meter"),
            switcher_rows_option: tray_preference(preferences, "switcherRowsOption", "progress"),
        },
    );
    let body = if summary.tooltip_rows.is_empty() {
        "Provider data unavailable\nUse Refresh to check again.".to_owned()
    } else {
        summary.tooltip_rows.join("\n")
    };
    let pixmap = render_tray_summary(
        &summary,
        RequestedSize {
            width: 32,
            height: 32,
        },
    )
    .or_else(|| {
        Some(render_meter(
            summary.meter_level,
            summary.accent_color.as_deref().unwrap_or("#10A37F"),
            RequestedSize {
                width: 32,
                height: 32,
            },
        ))
    });
    TrayPresentation {
        icon_name: String::new(),
        title: summary.title,
        body,
        pixmap,
        switcher_rows: summary
            .switcher_rows
            .into_iter()
            .map(|row| row.text)
            .collect(),
    }
}

fn main() {
    if !codexbar_gtk_native::lifecycle::wait_for_display(Duration::from_secs(30)) {
        eprintln!("{APP_NAME}: no graphical display became available within 30 seconds");
        std::process::exit(1);
    }
    let metadata = BuildMetadata::current().unwrap_or_else(|error| {
        eprintln!("{APP_NAME}: invalid bundled version metadata ({error})");
        std::process::exit(2);
    });
    let application = adw::Application::builder()
        .application_id(APPLICATION_ID)
        .flags(gio::ApplicationFlags::HANDLES_COMMAND_LINE)
        .build();
    let state = Rc::new(RefCell::new(NativeApp::new(application.clone(), metadata)));
    let startup_state = state.clone();
    application.connect_startup(move |_| {
        startup_state.borrow_mut().start();
    });

    let command_line_state = state.clone();
    application.connect_command_line(move |_, command_line| {
        let arguments = command_line.arguments();
        command_line_state
            .borrow_mut()
            .dispatch_arguments(&arguments);
        command_line.set_exit_status(0);
        0
    });

    let quit = gio::SimpleAction::new("quit", None);
    let quit_state = state.clone();
    quit.connect_activate(move |_, _| {
        quit_state.borrow_mut().begin_shutdown();
    });
    application.add_action(&quit);

    let refresh = gio::SimpleAction::new("refresh", None);
    let refresh_state = state.clone();
    refresh.connect_activate(move |_, _| {
        refresh_state.borrow_mut().request_refresh();
    });
    application.add_action(&refresh);

    let dashboard = gio::SimpleAction::new("dashboard", None);
    let dashboard_state = state.clone();
    dashboard.connect_activate(move |_, _| {
        dashboard_state.borrow_mut().request_dashboard();
    });
    application.add_action(&dashboard);

    let panel = gio::SimpleAction::new("panel", None);
    let panel_state = state.clone();
    panel.connect_activate(move |_, _| {
        panel_state.borrow_mut().request_panel_toggle();
    });
    application.add_action(&panel);

    let panel_at = gio::SimpleAction::new(
        "panel-at",
        Some(glib::VariantTy::new("(ii)").expect("panel activation uses an integer point")),
    );
    let panel_at_state = state.clone();
    panel_at.connect_activate(move |_, parameter| {
        if let Some((x, y)) = parameter.and_then(|value| value.get::<(i32, i32)>()) {
            panel_at_state.borrow_mut().request_panel_toggle_at(x, y);
        }
    });
    application.add_action(&panel_at);

    let panel_open_at = gio::SimpleAction::new(
        "panel-open-at",
        Some(glib::VariantTy::new("(ii)").expect("panel activation uses an integer point")),
    );
    let panel_open_at_state = state.clone();
    panel_open_at.connect_activate(move |_, parameter| {
        if let Some((x, y)) = parameter.and_then(|value| value.get::<(i32, i32)>()) {
            panel_open_at_state.borrow_mut().request_panel_open_at(x, y);
        }
    });
    application.add_action(&panel_open_at);

    let check_updates = gio::SimpleAction::new("check-updates", None);
    let update_state = state.clone();
    check_updates.connect_activate(move |_, _| {
        update_state.borrow_mut().request_update_check();
    });
    application.add_action(&check_updates);

    let restart = gio::SimpleAction::new("restart", None);
    let restart_state = state.clone();
    restart.connect_activate(move |_, _| {
        restart_state.borrow().request_restart();
    });
    application.add_action(&restart);

    let terminal_login = gio::SimpleAction::new("login-terminal", None);
    let terminal_login_state = state.clone();
    terminal_login.connect_activate(move |_, _| {
        terminal_login_state.borrow().request_codex_terminal_login();
    });
    application.add_action(&terminal_login);

    let page = gio::SimpleAction::new("page", Some(glib::VariantTy::STRING));
    let page_state = state.clone();
    page.connect_activate(move |_, parameter| {
        if let Some(name) = parameter.and_then(|parameter| parameter.str()) {
            page_state.borrow_mut().request_page(name);
        }
    });
    application.add_action(&page);

    let spend_range = gio::SimpleAction::new("spend-range", Some(glib::VariantTy::STRING));
    let spend_range_state = state.clone();
    spend_range.connect_activate(move |_, parameter| {
        if let Some(value) = parameter.and_then(|parameter| parameter.str()) {
            spend_range_state.borrow_mut().request_spend_range(value);
        }
    });
    application.add_action(&spend_range);

    let settings = gio::SimpleAction::new("settings", None);
    let settings_state = state.clone();
    settings.connect_activate(move |_, _| {
        settings_state.borrow_mut().request_settings();
    });
    application.add_action(&settings);

    let about = gio::SimpleAction::new("about", None);
    let about_state = state.clone();
    about.connect_activate(move |_, _| {
        about_state.borrow_mut().request_about();
    });
    application.add_action(&about);

    // Keep keyboard navigation on the same Gio actions used by buttons,
    // command-line routes and the StatusNotifierItem menu.
    application.set_accels_for_action("app.refresh", &["<Primary>r"]);
    application.set_accels_for_action("app.page('usage')", &["<Primary>1"]);
    application.set_accels_for_action("app.page('sessions')", &["<Primary>2"]);
    application.set_accels_for_action("app.page('spend')", &["<Primary>3"]);
    application.set_accels_for_action("app.quit", &["<Primary>q"]);

    let weak = Rc::downgrade(&state);
    glib::timeout_add_local(Duration::from_millis(40), move || {
        if let Some(state) = weak.upgrade() {
            state.borrow_mut().poll_backend();
            if state.borrow().worker_stopped {
                return glib::ControlFlow::Break;
            }
            glib::ControlFlow::Continue
        } else {
            glib::ControlFlow::Break
        }
    });

    let _exit_status = application.run();
    state.borrow_mut().begin_shutdown();
    let context = glib::MainContext::default();
    while !state.borrow().worker_stopped {
        context.iteration(true);
    }
}

#[cfg(all(test, debug_assertions))]
mod update_url_tests {
    use super::is_loopback_update_url;

    #[test]
    fn update_test_url_override_accepts_only_loopback_http_hosts() {
        assert!(is_loopback_update_url("http://127.0.0.1:41991/VERSION"));
        assert!(is_loopback_update_url("http://[::1]:41991/VERSION"));
        assert!(!is_loopback_update_url("https://127.0.0.1:41991/VERSION"));
        assert!(!is_loopback_update_url("http://example.test:41991/VERSION"));
        assert!(!is_loopback_update_url("http://127.0.0.2:41991/VERSION"));
    }
}
