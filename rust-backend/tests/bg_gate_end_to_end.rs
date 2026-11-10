//! BG acceptance flow: the public headless backend drives its CLI/controller,
//! loopback HTTP currency refresh, and fake PTY login lifecycle in one process.
//! This integration test intentionally imports no Python, GTK, or PyO3 crate.

#![cfg(unix)]

use std::{
    fs,
    io::{Read, Write},
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::Duration,
};

use codexbar_backend::{
    cli::CliService,
    controller::{ControllerSnapshot, RefreshControllerConfig, RefreshControllerHandle},
    currency::{CurrencyService, RateSource},
    login::{LoginCompletionKind, LoginEvent, LoginPrompt, LoginSession, LoginStatus},
    updates::{self, UpdateRelation, Version},
    BackendEventKind, BackendStatus,
};
use codexbar_core::{history::HistoryStore, preferences::PreferencesStore};
use serde_json::json;
use tokio::{sync::watch, time::timeout};

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct FixtureDir(PathBuf);

impl FixtureDir {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "codexbar-bg-e2e-{}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).expect("create isolated fixture directory");
        Self(path)
    }

    fn path(&self) -> &std::path::Path {
        &self.0
    }
}

impl Drop for FixtureDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn write_fake_cli(dir: &FixtureDir) -> PathBuf {
    let path = dir.path().join("codexbar-fixture");
    fs::write(
        &path,
        r##"#!/bin/sh
set -eu
case "${1-}" in
  --version)
    printf '%s\n' 'fixture-cli 1.2'
    ;;
  usage)
    printf '%s\n' '[{"provider":"codex","usage":{"primary":{"usedPercent":100,"windowMinutes":300},"identity":{"accountEmail":"synthetic@example.invalid"}}}]'
    ;;
  cost)
    printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totals":{"totalCost":4.25,"totalTokens":100,"priced":true}}]'
    ;;
  sessions)
    printf '%s\n' '{"sessions":[{"id":"synthetic-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":17,"host":"fixture"}]}'
    ;;
  *)
    exit 64
    ;;
esac
"##,
    )
    .expect("write synthetic CLI fixture");
    let mut permissions = fs::metadata(&path).expect("stat fake CLI").permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(&path, permissions).expect("make fake CLI executable");
    path
}

fn write_fake_login(dir: &FixtureDir) -> PathBuf {
    let path = dir.path().join("fake-pty-login");
    fs::write(
        &path,
        r##"#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
printf '%s\n' "$$" > "$base/pty-pid"
printf '%s\n' 'Paste code here'
read -r synthetic_input
"##,
    )
    .expect("write fake PTY login fixture");
    let mut permissions = fs::metadata(&path)
        .expect("stat fake PTY login")
        .permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(&path, permissions).expect("make fake PTY login executable");
    path
}

async fn wait_for_snapshot(
    state: &mut watch::Receiver<codexbar_backend::BackendState<ControllerSnapshot>>,
) -> ControllerSnapshot {
    timeout(Duration::from_secs(5), async {
        loop {
            if let Some(snapshot) = state.borrow().snapshot.clone() {
                return (*snapshot).clone();
            }
            state
                .changed()
                .await
                .expect("controller state remains open");
        }
    })
    .await
    .expect("controller publishes an initial snapshot")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn headless_backend_cli_http_pty_events_cancellation_and_join() {
    let fixture = FixtureDir::new();
    let fake_cli = write_fake_cli(&fixture);

    let preferences =
        std::sync::Arc::new(PreferencesStore::new(fixture.path().join("settings.json")));
    preferences
        .set("refreshFrequency", json!("manual"), false)
        .expect("select deterministic manual refresh");
    let config = RefreshControllerConfig::new(
        CliService::new(&fake_cli, None),
        preferences,
        std::sync::Arc::new(HistoryStore::new(fixture.path().join("history.jsonl"), 30)),
    );
    let mut controller = RefreshControllerHandle::start(config);
    let mut state = controller.state();
    let snapshot = wait_for_snapshot(&mut state).await;
    assert_eq!(snapshot.version, "fixture-cli 1.2");
    assert_eq!(snapshot.providers.len(), 1);
    assert_eq!(snapshot.providers[0].provider_id, "codex");
    assert!(snapshot.providers[0].windows[0].usage_known);
    assert!(snapshot.spend.is_some());
    assert_eq!(snapshot.sessions.len(), 1);
    assert_eq!(snapshot.history.len(), 1);
    assert_eq!(
        snapshot
            .tray_selection
            .as_ref()
            .map(|selection| selection.provider_id.as_str()),
        Some("codex")
    );

    let mut notifications = controller
        .take_notification_receiver()
        .expect("controller exposes its bounded event stream");
    let mut event_sequences = Vec::new();
    while event_sequences.len() < 2 {
        let event = timeout(Duration::from_secs(2), notifications.recv())
            .await
            .expect("threshold notifications are delivered")
            .expect("event receiver remains open");
        assert!(matches!(event.kind, BackendEventKind::Notification(_)));
        event_sequences.push(event.sequence);
    }
    assert_eq!(event_sequences, [0, 1]);

    // Exercise the actual reqwest client against a local fixture only.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind loopback fixture");
    let address = listener.local_addr().expect("loopback address");
    let http_server = thread::spawn(move || {
        for (expected_path, body) in [
            ("/rates", r#"{"rates":{"USD":1,"EUR":1.25}}"#),
            (
                "/VERSION",
                "MARKETING_VERSION=0.82.0\nCURRENT_PROJECT_VERSION=53\n",
            ),
        ] {
            let (mut stream, _) = listener.accept().expect("accept loopback request");
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .expect("bound request read");
            let mut request = [0u8; 2048];
            let size = stream.read(&mut request).expect("read fixture request");
            let request = String::from_utf8_lossy(&request[..size]);
            assert!(request.starts_with(&format!("GET {expected_path} HTTP/1.1")));
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .expect("write synthetic HTTP response");
        }
    });
    let currency = CurrencyService::with_endpoint(
        fixture.path().join("rates.json"),
        format!("http://{address}/rates"),
    );
    assert!(currency.ensure_rates_at("EUR", 1_900_000_000.0).await);
    assert_eq!(currency.status().source, RateSource::Live);
    assert_eq!(currency.convert(100.0, "USD", "EUR"), Some(125.0));

    let current = Version::new("0.82.0", "52").expect("valid current marker");
    let latest = updates::fetch(&format!("http://{address}/VERSION"), Duration::from_secs(2))
        .await
        .expect("read-only update service uses loopback fixture");
    assert_eq!(latest.marketing, "0.82.0");
    assert_eq!(latest.build, "53");
    assert_eq!(
        updates::relation(&current, &latest),
        Ok(UpdateRelation::Available)
    );
    http_server.join().expect("loopback HTTP fixture exits");

    // A fake PTY emits a synthetic prompt, then cancellation must reap/join it.
    let fake_login = write_fake_login(&fixture);
    let mut login = LoginSession::start(fake_login, vec![], Duration::from_secs(5))
        .await
        .expect("start fixture-only PTY child");
    let lifecycle = login.state();
    let mut login_events = login.take_events().expect("PTY event stream is available");
    let prompt_seen = timeout(Duration::from_secs(3), async {
        while let Some(event) = login_events.recv().await {
            if event == LoginEvent::Prompt(LoginPrompt::PasteCode) {
                return true;
            }
        }
        false
    })
    .await
    .expect("fake PTY prompt arrives");
    assert!(prompt_seen);
    let login_pid = fs::read_to_string(fixture.path().join("pty-pid"))
        .expect("fake PTY wrote its process id")
        .trim()
        .parse::<libc::pid_t>()
        .expect("fixture process id is numeric");
    login.cancel().await;
    let completion = timeout(Duration::from_secs(3), login.wait())
        .await
        .expect("cancelled PTY is reaped and joined")
        .expect("PTY worker returns a typed completion");
    assert_eq!(completion.kind, LoginCompletionKind::Cancelled);
    assert_eq!(lifecycle.borrow().status, LoginStatus::Cancelled);
    assert_eq!(
        unsafe { libc::kill(login_pid, 0) },
        -1,
        "PTY child was reaped"
    );

    // The service's own shutdown requests cancellation and joins its worker.
    controller
        .shutdown()
        .await
        .expect("controller task joins cleanly");
    assert_eq!(state.borrow().status, BackendStatus::Stopped);
}
