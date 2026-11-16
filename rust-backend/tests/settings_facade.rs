//! Public settings-service coverage for the legacy Python facade contracts.
//! Fixtures are local shell executables and isolated temporary homes; this
//! integration target does not load Python, PyO3, GTK, or the app package.

#![cfg(unix)]

use codexbar_backend::{
    cli::CliService,
    settings::{
        launch_at_login_state, preferences_export_to, preferences_import_from, preferences_reset,
        provider_action, set_api_key, set_hooks_enabled, set_launch_at_login, settings_snapshot,
        LaunchAtLoginState, ProviderAction, ProviderSource,
    },
};
use codexbar_core::preferences::PreferencesStore;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
    executable: PathBuf,
}

impl Fixture {
    fn new(script: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "codexbar-settings-facade-{}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let staged = root.join("fake-codexbar.tmp");
        let executable = root.join("fake-codexbar");
        fs::write(&staged, format!("#!/bin/sh\n{script}\n")).unwrap();
        fs::set_permissions(&staged, fs::Permissions::from_mode(0o700)).unwrap();
        fs::rename(staged, &executable).unwrap();
        Self { root, executable }
    }

    fn home(&self) -> PathBuf {
        self.root.join("home")
    }

    fn cli(&self) -> CliService {
        CliService::new(&self.executable, None)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn settings_snapshot_actions_and_launch_at_login_work_through_public_services() {
    let fixture = Fixture::new(
        r#"case "$1/$2" in
  config/providers) printf 'codex: enabled (Fixture Codex) [default]\n';;
  hooks/list) printf '{"enabled":true,"events":[{"event":"session-start","executable":"fixture-hook","enabled":true}]}';;
  plugins/list) printf '[{"id":"fixture-plugin","name":"Fixture Plugin","version":"1"}]';;
  config/enable) [ "$3/$4" = "--provider/codex" ] || exit 31;;
  config/set-source) [ "$3/$4/$5/$6" = "--provider/codex/--source/web" ] || exit 32;;
  config/set-api-key) [ "$3/$4/$5/$6" = "--provider/codex/--api-key/synthetic-fixture-key" ] || exit 33;;
  hooks/disable) [ -z "$3" ] || exit 34;;
esac
exit 0"#,
    );
    let cli = fixture.cli();
    let home = fixture.home();
    let preferences = PreferencesStore::new(home.join(".config/codexbar-gtk/settings.json"));

    let snapshot = settings_snapshot(&cli, &home, Duration::from_secs(2)).await;
    let providers = snapshot.providers.value.expect("providers load");
    assert_eq!(providers.len(), 1);
    assert_eq!(providers[0].provider_id, "codex");
    assert_eq!(providers[0].display_name, "Fixture Codex");
    assert!(snapshot.hooks.value.as_ref().unwrap().enabled);
    assert_eq!(
        snapshot.hooks.value.as_ref().unwrap().events[0]
            .event
            .as_deref(),
        Some("session-start")
    );
    assert_eq!(
        snapshot.plugins.value.as_ref().unwrap()[0].id.as_deref(),
        Some("fixture-plugin")
    );
    assert_eq!(
        snapshot.launch_at_login.value,
        Some(LaunchAtLoginState { enabled: false })
    );

    provider_action(
        &cli,
        ProviderAction::Enable,
        "codex",
        Duration::from_secs(2),
    )
    .await
    .unwrap();
    provider_action(
        &cli,
        ProviderAction::SetSource {
            source: ProviderSource::Web,
        },
        "codex",
        Duration::from_secs(2),
    )
    .await
    .unwrap();
    set_api_key(
        &cli,
        "codex",
        "synthetic-fixture-key",
        Duration::from_secs(2),
    )
    .await
    .unwrap();
    set_hooks_enabled(&cli, false, Duration::from_secs(2))
        .await
        .unwrap();

    let state = set_launch_at_login(&preferences, &home, true, "/tmp/fixture-codexbar").unwrap();
    assert_eq!(state, LaunchAtLoginState { enabled: true });
    assert_eq!(preferences.get("launchAtLogin"), Some(Value::Bool(true)));
    assert_eq!(launch_at_login_state(&home).unwrap(), state);
    assert!(home
        .join(".config/autostart/codexbar-gtk.desktop")
        .is_file());
}

#[test]
fn settings_export_import_and_reset_preserve_portable_preferences_shape() {
    let fixture = Fixture::new("exit 0");
    let home = fixture.home();
    let preferences = PreferencesStore::new(home.join(".config/codexbar-gtk/settings.json"));
    let export = fixture.root.join("selected-export.json");

    preferences.set("showTray", json!(false), true).unwrap();
    preferences_export_to(&preferences, &export).unwrap();
    let document: Value = serde_json::from_slice(&fs::read(&export).unwrap()).unwrap();
    assert_eq!(document["version"], json!(1));
    assert_eq!(
        document
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        ["preferences", "version"]
    );
    assert_eq!(document["preferences"]["showTray"], json!(false));

    preferences.set("showTray", json!(true), true).unwrap();
    preferences_import_from(&preferences, &export).unwrap();
    assert_eq!(preferences.get("showTray"), Some(Value::Bool(false)));

    preferences_reset(&preferences).unwrap();
    assert_eq!(preferences.get("showTray"), Some(Value::Bool(true)));
    assert_eq!(
        preferences.values(),
        codexbar_core::preferences::default_values()
    );
}
