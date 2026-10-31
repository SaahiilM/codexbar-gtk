//! Native UI bootstrap contracts that can be tested without creating widgets.

use std::{collections::VecDeque, ffi::OsString};

pub mod dashboard;
pub mod dashboard_widget;

pub const APPLICATION_ID: &str = "com.steipete.CodexBarGTK";
const VERSION_FILE: &str = include_str!("../../VERSION");

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Page {
    Usage,
    Sessions,
    Spend,
}

impl Page {
    fn parse(value: &str) -> Self {
        match value {
            "sessions" => Self::Sessions,
            "spend" => Self::Spend,
            // Python's Gtk.Stack leaves the default Usage page selected when
            // given an unknown page name. Keep that safe fallback.
            _ => Self::Usage,
        }
    }

    pub const fn label(self) -> &'static str {
        match self {
            Self::Usage => "Usage",
            Self::Sessions => "Sessions",
            Self::Spend => "Usage & Spend",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LaunchRoute {
    Default,
    Panel,
    Settings,
    About,
    Page(Page),
}

/// Parse argv received by `G_APPLICATION_HANDLES_COMMAND_LINE`.
///
/// The first entry is the executable name. The option precedence and missing
/// `--page` argument behavior match `CodexBarApp.do_activate` in the Python
/// application. Gio forwards this same argv to the primary instance, so one
/// parser covers both initial and secondary launches.
pub fn route_from_arguments(arguments: &[OsString]) -> LaunchRoute {
    let args: Vec<String> = arguments
        .iter()
        .skip(1)
        .filter(|arg| arg.as_os_str() != "--")
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect();

    if args.iter().any(|arg| arg == "--settings") {
        return LaunchRoute::Settings;
    }
    if args.iter().any(|arg| arg == "--about") {
        return LaunchRoute::About;
    }
    if args.iter().any(|arg| arg == "--panel") {
        return LaunchRoute::Panel;
    }
    if let Some(index) = args.iter().position(|arg| arg == "--page") {
        let page = args.get(index + 1).map(String::as_str).unwrap_or("usage");
        return LaunchRoute::Page(Page::parse(page));
    }
    LaunchRoute::Default
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BuildMetadata {
    pub marketing_version: String,
    pub build: u64,
}

impl BuildMetadata {
    pub fn current() -> Result<Self, &'static str> {
        Self::parse(VERSION_FILE)
    }

    pub fn parse(contents: &str) -> Result<Self, &'static str> {
        let marketing_version = contents
            .lines()
            .find_map(|line| line.strip_prefix("MARKETING_VERSION="))
            .ok_or("missing marketing version")?;
        let build = contents
            .lines()
            .find_map(|line| line.strip_prefix("CURRENT_PROJECT_VERSION="))
            .ok_or("missing project build")?
            .parse::<u64>()
            .map_err(|_| "invalid project build")?;
        if marketing_version.is_empty()
            || !marketing_version.split('.').all(|component| {
                !component.is_empty() && component.bytes().all(|b| b.is_ascii_digit())
            })
        {
            return Err("invalid marketing version");
        }
        Ok(Self {
            marketing_version: marketing_version.to_owned(),
            build,
        })
    }

    pub fn display(&self) -> String {
        format!("{} ({})", self.marketing_version, self.build)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct EventProgress {
    pub received: u64,
    pub last_sequence: Option<u64>,
    pub sequence_gaps: u64,
}

/// Events drained from the backend's bounded lossless channel stay owned by
/// the GTK application until a native delivery consumer is added in U07.
/// Keeping payloads here avoids turning a successful GLib dispatch into a
/// silent notification drop during the bootstrap phase.
pub struct EventInbox<T> {
    events: VecDeque<T>,
    progress: EventProgress,
}

impl<T> Default for EventInbox<T> {
    fn default() -> Self {
        Self {
            events: VecDeque::new(),
            progress: EventProgress::default(),
        }
    }
}

impl<T> EventInbox<T> {
    pub fn push(&mut self, sequence: u64, event: T) {
        self.progress.observe(sequence);
        self.events.push_back(event);
    }

    pub const fn progress(&self) -> EventProgress {
        self.progress
    }

    pub fn len(&self) -> usize {
        self.events.len()
    }

    pub fn is_empty(&self) -> bool {
        self.events.is_empty()
    }

    pub fn pop_front(&mut self) -> Option<T> {
        self.events.pop_front()
    }
}

impl EventProgress {
    /// Record each bounded backend event observed by the GLib dispatch tick.
    pub fn observe(&mut self, sequence: u64) {
        if let Some(previous) = self.last_sequence {
            if sequence != previous.saturating_add(1) {
                self.sequence_gaps = self.sequence_gaps.saturating_add(1);
            }
        } else if sequence != 0 {
            self.sequence_gaps = self.sequence_gaps.saturating_add(1);
        }
        self.received = self.received.saturating_add(1);
        self.last_sequence = Some(sequence);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codexbar_backend::{event_channel, BackendEventKind};
    use codexbar_core::notifications::NotificationEvent;

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn routes_flags_with_legacy_precedence() {
        assert_eq!(
            route_from_arguments(&args(&[
                "codexbar-gtk-native",
                "--page",
                "spend",
                "--panel",
                "--about",
                "--settings",
            ])),
            LaunchRoute::Settings
        );
        assert_eq!(
            route_from_arguments(&args(&["app", "--about", "--panel"])),
            LaunchRoute::About
        );
        assert_eq!(
            route_from_arguments(&args(&["app", "--panel", "--page", "sessions"])),
            LaunchRoute::Panel
        );
    }

    #[test]
    fn page_arguments_match_python_default_and_invalid_behavior() {
        assert_eq!(
            route_from_arguments(&args(&["app", "--page", "sessions"])),
            LaunchRoute::Page(Page::Sessions)
        );
        assert_eq!(
            route_from_arguments(&args(&["app", "--page", "spend"])),
            LaunchRoute::Page(Page::Spend)
        );
        assert_eq!(
            route_from_arguments(&args(&["app", "--page"])),
            LaunchRoute::Page(Page::Usage)
        );
        assert_eq!(
            route_from_arguments(&args(&["app", "--page", "not-a-page"])),
            LaunchRoute::Page(Page::Usage)
        );
    }

    #[test]
    fn separator_is_ignored_like_the_python_command_line_adapter() {
        assert_eq!(
            route_from_arguments(&args(&["app", "--", "--about"])),
            LaunchRoute::About
        );
    }

    #[test]
    fn version_metadata_tracks_the_root_version_file() {
        let metadata = BuildMetadata::current().unwrap();
        let expected = include_str!("../../VERSION");
        let python_version = include_str!("../../codexbar_gtk/version.py");
        let readme = include_str!("../../README.md");
        assert!(expected.contains(&format!("MARKETING_VERSION={}", metadata.marketing_version)));
        assert!(expected.contains(&format!("CURRENT_PROJECT_VERSION={}", metadata.build)));
        assert!(readme.contains(&format!("\"{}\"", metadata.display())));
        assert!(python_version.contains(&format!(
            "SHORT_VERSION = \"{}\"",
            metadata.marketing_version
        )));
        assert!(python_version.contains(&format!("BUILD = {}", metadata.build)));
        assert_eq!(
            metadata.display(),
            format!("{} ({})", metadata.marketing_version, metadata.build)
        );
        assert_eq!(metadata.marketing_version, env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn metadata_rejects_missing_or_malformed_fields() {
        assert!(BuildMetadata::parse("MARKETING_VERSION=1.0\n").is_err());
        assert!(BuildMetadata::parse("MARKETING_VERSION=x\nCURRENT_PROJECT_VERSION=no\n").is_err());
    }

    #[test]
    fn event_progress_detects_gaps_without_losing_received_events() {
        let mut progress = EventProgress::default();
        for sequence in 0..3 {
            progress.observe(sequence);
        }
        assert_eq!(
            progress,
            EventProgress {
                received: 3,
                last_sequence: Some(2),
                sequence_gaps: 0,
            }
        );
        progress.observe(4);
        assert_eq!(progress.received, 4);
        assert_eq!(progress.sequence_gaps, 1);
        let mut late = EventProgress::default();
        late.observe(2);
        assert_eq!(late.sequence_gaps, 1);
    }

    #[test]
    fn event_inbox_retains_every_dispatched_payload_in_sequence_order() {
        let mut inbox = EventInbox::default();
        for sequence in 0..512_u64 {
            inbox.push(sequence, format!("event-{sequence}"));
        }

        assert_eq!(inbox.len(), 512);
        assert_eq!(inbox.progress().received, 512);
        assert_eq!(inbox.progress().sequence_gaps, 0);
        for sequence in 0..512_u64 {
            let expected = format!("event-{sequence}");
            assert_eq!(inbox.pop_front().as_deref(), Some(expected.as_str()));
        }
        assert!(inbox.is_empty());
    }

    #[test]
    fn bounded_backend_events_reach_the_gtk_inbox_without_loss() {
        const EVENT_COUNT: u64 = 512;
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .unwrap();
        let mut inbox = runtime.block_on(async {
            let (publisher, mut receiver) = event_channel();
            let producer = tokio::spawn(async move {
                for index in 0..EVENT_COUNT {
                    publisher
                        .publish_notification(NotificationEvent::CreditExpiry {
                            id: format!("fixture-{index}"),
                            provider_id: "synthetic".to_owned(),
                            title: "Synthetic notification".to_owned(),
                            body: "Fixture only".to_owned(),
                        })
                        .await
                        .unwrap();
                }
            });

            let mut inbox = EventInbox::default();
            while inbox.progress().received < EVENT_COUNT {
                let event = receiver.recv().await.unwrap();
                inbox.push(event.sequence, event);
            }
            producer.await.unwrap();
            inbox
        });

        assert_eq!(inbox.progress().received, EVENT_COUNT);
        assert_eq!(inbox.progress().sequence_gaps, 0);
        for sequence in 0..EVENT_COUNT {
            let event = inbox.pop_front().unwrap();
            assert_eq!(event.sequence, sequence);
            match event.kind {
                BackendEventKind::Notification(NotificationEvent::CreditExpiry { id, .. }) => {
                    assert_eq!(id, format!("fixture-{sequence}"));
                }
                other => panic!("unexpected synthetic event: {other:?}"),
            }
        }
        assert!(inbox.is_empty());
    }
}
