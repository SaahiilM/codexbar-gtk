use std::{
    cell::RefCell,
    path::PathBuf,
    rc::Rc,
    sync::mpsc::{self, Receiver, TryRecvError},
    thread::{self, JoinHandle},
    time::Duration,
};

use codexbar_backend::{
    cli::{discover_executable, CliService, SharedCliService},
    controller::{
        ControllerCommand, ControllerSnapshot, RefreshControllerConfig, RefreshControllerHandle,
    },
    BackendEvent, BackendState, BackendStatus,
};
use codexbar_core::{history::HistoryStore, preferences::PreferencesStore};
use gio::prelude::*;
use gtk::prelude::*;
use libadwaita as adw;
use tokio::sync::{mpsc as tokio_mpsc, oneshot, watch};

use codexbar_gtk_native::{BuildMetadata, EventInbox, LaunchRoute, Page, APPLICATION_ID};

const APP_NAME: &str = "CodexBar GTK";

struct BackendBridge {
    state: watch::Receiver<BackendState<ControllerSnapshot>>,
    events: tokio_mpsc::Receiver<BackendEvent>,
    refresh: tokio_mpsc::Sender<ControllerCommand>,
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
        let worker = thread::Builder::new()
            .name("codexbar-backend-runtime".to_owned())
            .spawn(move || {
                let result = tokio::runtime::Builder::new_multi_thread()
                    .worker_threads(2)
                    .enable_all()
                    .build();
                match result {
                    Ok(runtime) => runtime.block_on(async move {
                        let preferences = std::sync::Arc::new(PreferencesStore::new(
                            PreferencesStore::default_path(),
                        ));
                        let history = std::sync::Arc::new(HistoryStore::new(
                            HistoryStore::default_path(),
                            codexbar_core::history::RETENTION_DAYS,
                        ));
                        let cli = service_from_preferences(&preferences);
                        let shared_cli = std::sync::Arc::new(SharedCliService::new(cli));
                        let mut controller = RefreshControllerHandle::start(
                            RefreshControllerConfig::with_shared_cli(
                                shared_cli,
                                preferences,
                                history,
                            ),
                        );
                        let bridge = BackendBridge {
                            state: controller.state(),
                            events: controller
                                .take_notification_receiver()
                                .expect("controller owns one notification stream"),
                            refresh: controller.force_refresh_sender(),
                        };
                        if ready_tx.send(Ok(bridge)).is_err() {
                            let _ = controller.shutdown().await;
                            return;
                        }
                        let _ = shutdown_rx.await;
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

fn service_from_preferences(preferences: &PreferencesStore) -> std::sync::Arc<CliService> {
    let configured_path = preferences
        .get("cliPath")
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .filter(|path| !path.trim().is_empty());
    let executable = configured_path
        .map(PathBuf::from)
        .or_else(|| {
            let package_dir = std::env::current_exe()
                .ok()
                .and_then(|path| path.parent().map(PathBuf::from))
                .unwrap_or_else(|| PathBuf::from("."));
            discover_executable("codexbar", Some("CODEXBAR_CLI"), &package_dir).ok()
        })
        .unwrap_or_else(|| PathBuf::from("codexbar"));
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
    state_label: Option<gtk::Label>,
    events_label: Option<gtk::Label>,
    route: LaunchRoute,
    pending_panel: bool,
    backend_start_failed: bool,
    shutting_down: bool,
    worker_stopped: bool,
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
            state_label: None,
            events_label: None,
            route: LaunchRoute::Default,
            pending_panel: false,
            backend_start_failed: false,
            shutting_down: false,
            worker_stopped: false,
            hold_guard: None,
            event_inbox: EventInbox::default(),
        }
    }

    fn start(&mut self) {
        self.hold_guard = Some(self.application.hold());
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
        self.route = route;
        self.pending_panel = route == LaunchRoute::Panel;
        if route == LaunchRoute::About {
            self.show_about();
            return;
        }
        if self.pending_panel {
            if self.backend_has_completed_initial_refresh() {
                self.show_route(route);
            }
            return;
        }
        self.show_route(route);
    }

    fn show_route(&mut self, route: LaunchRoute) {
        let window = self.ensure_main_window();
        let (title, body, width, height) = match route {
            LaunchRoute::Panel => (
                format!("{APP_NAME} — Panel — Native UI bootstrap"),
                "The native compact panel is a placeholder. Full panel behavior is scheduled for U03.",
                420,
                220,
            ),
            LaunchRoute::Settings => (
                format!("{APP_NAME} — Settings — Native UI bootstrap"),
                "Settings controls are placeholders. The native settings panes are scheduled for U05.",
                620,
                420,
            ),
            LaunchRoute::Page(page) => (
                format!("{APP_NAME} — {} — Native UI bootstrap", page.label()),
                page_description(page),
                860,
                560,
            ),
            LaunchRoute::Default => (
                format!("{APP_NAME} — Dashboard — Native UI bootstrap"),
                "The native dashboard is a placeholder. Provider cards and dashboard parity are scheduled for U02.",
                860,
                560,
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
            .application_name(APP_NAME)
            .version(self.metadata.display())
            .developer_name("CodexBar GTK contributors")
            .comments("Native UI migration bootstrap. Screens are implemented in later U tasks.")
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

        let mut latest_state = None;
        if let Some(bridge) = &mut self.bridge {
            latest_state = Some(bridge.state.borrow_and_update().clone());
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
        if let Some(state) = latest_state {
            self.set_backend_status(&status_label(&state));
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

    fn request_about(&self) {
        self.show_about();
    }

    fn begin_shutdown(&mut self) {
        if self.shutting_down {
            return;
        }
        self.shutting_down = true;
        if let Some(worker) = &mut self.worker {
            worker.request_shutdown();
        } else {
            self.worker_stopped = true;
            self.hold_guard.take();
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
            self.application.quit();
        }
    }
}

fn page_description(page: Page) -> &'static str {
    match page {
        Page::Usage => {
            "The native Usage page is a placeholder. Dashboard parity is scheduled for U02."
        }
        Page::Sessions => {
            "The native Sessions page is a placeholder. Session history is scheduled for U04."
        }
        Page::Spend => {
            "The native Usage & Spend page is a placeholder. Spend parity is scheduled for U04."
        }
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

fn main() {
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

    let about = gio::SimpleAction::new("about", None);
    let about_state = state.clone();
    about.connect_activate(move |_, _| {
        about_state.borrow_mut().request_about();
    });
    application.add_action(&about);

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
