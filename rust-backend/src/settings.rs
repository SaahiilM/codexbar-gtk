//! Typed settings operations composed from the shared B07 CLI and B05
//! preferences services. This module contains no frontend types or strings
//! derived from command output, paths, or credentials.

use crate::cli::{
    executable_override_is_valid, CliError, CliErrorKind, CliResult, CliService,
    ProviderStatusEntry, SharedCliService,
};
use crate::controller::ControllerCommand;
use codexbar_core::preferences::PreferencesStore;
use serde::Serialize;
use serde_json::{json, Map, Value};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};

static NEXT_AUTOSTART_TEMP: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SettingsSection<T> {
    pub value: Option<T>,
    pub error: Option<SettingsError>,
}

impl<T> SettingsSection<T> {
    fn success(value: T) -> Self {
        Self {
            value: Some(value),
            error: None,
        }
    }

    fn failure(error: SettingsError) -> Self {
        Self {
            value: None,
            error: Some(error),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SettingsSnapshot {
    pub providers: SettingsSection<Vec<ProviderStatusEntry>>,
    pub hooks: SettingsSection<HookSettings>,
    pub plugins: SettingsSection<Vec<PluginInfo>>,
    pub launch_at_login: SettingsSection<LaunchAtLoginState>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct HookSettings {
    pub enabled: bool,
    pub events: Vec<HookRule>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct HookRule {
    pub event: Option<String>,
    pub executable: Option<String>,
    pub enabled: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct PluginInfo {
    pub id: Option<String>,
    pub name: Option<String>,
    pub version: Option<String>,
    pub provider: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct LaunchAtLoginState {
    pub enabled: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct CliReconfigureResult {
    pub applied: bool,
    pub refresh_queued: bool,
}

struct CliReconfigureRequest {
    cli_path: Option<String>,
    timezone: Option<String>,
    reply: oneshot::Sender<Result<CliReconfigureResult, SettingsError>>,
}

/// Serializes reconfiguration commands without holding a lock while validating
/// the executable or persisting preferences. The actor is owned by the facade
/// runtime; callers can await it from a worker thread.
#[derive(Clone)]
pub struct CliReconfigureActor {
    sender: mpsc::Sender<CliReconfigureRequest>,
}

impl CliReconfigureActor {
    pub fn start(
        runtime: &tokio::runtime::Handle,
        cli: Arc<SharedCliService>,
        preferences: Arc<PreferencesStore>,
        default_executable: PathBuf,
        refresh: mpsc::Sender<ControllerCommand>,
    ) -> Self {
        let (sender, mut receiver) = mpsc::channel::<CliReconfigureRequest>(16);
        runtime.spawn(async move {
            while let Some(request) = receiver.recv().await {
                let result = apply_cli_reconfiguration(
                    &cli,
                    &preferences,
                    &default_executable,
                    &refresh,
                    request.cli_path.as_deref(),
                    request.timezone.as_deref(),
                )
                .await;
                let _ = request.reply.send(result);
            }
        });
        Self { sender }
    }

    pub async fn reconfigure(
        &self,
        cli_path: Option<String>,
        timezone: Option<String>,
    ) -> Result<CliReconfigureResult, SettingsError> {
        let (reply, result) = oneshot::channel();
        self.sender
            .send(CliReconfigureRequest {
                cli_path,
                timezone,
                reply,
            })
            .await
            .map_err(|_| {
                SettingsError::new(
                    SettingsErrorCategory::CliProcess,
                    "settings_cli_reconfigure",
                )
            })?;
        result.await.unwrap_or_else(|_| {
            Err(SettingsError::new(
                SettingsErrorCategory::CliProcess,
                "settings_cli_reconfigure",
            ))
        })
    }
}

async fn apply_cli_reconfiguration(
    cli: &SharedCliService,
    preferences: &PreferencesStore,
    default_executable: &Path,
    refresh: &mpsc::Sender<ControllerCommand>,
    cli_path: Option<&str>,
    timezone: Option<&str>,
) -> Result<CliReconfigureResult, SettingsError> {
    if cli_path.is_none() && timezone.is_none() {
        return Err(SettingsError::invalid_input("settings_cli_reconfigure"));
    }
    let current_preferences = preferences.values();
    let existing_path = current_preferences
        .get("cliPath")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let configured_path = cli_path.map(str::trim).unwrap_or(existing_path).trim();
    let executable = if configured_path.is_empty() {
        default_executable.to_path_buf()
    } else {
        PathBuf::from(configured_path)
    };
    let valid_executable = if configured_path.is_empty() {
        executable_override_is_valid(&executable.to_string_lossy())
    } else {
        executable_override_is_valid(configured_path)
    };
    if !valid_executable {
        return Err(SettingsError::invalid_input("settings_cli_reconfigure"));
    }
    let existing_timezone = current_preferences
        .get("costUsageBucketTimeZone")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let timezone_preference = timezone.unwrap_or(existing_timezone);
    let timezone_override =
        (!timezone_preference.is_empty()).then(|| std::ffi::OsString::from(timezone_preference));
    let replacement = Arc::new(CliService::new(executable, timezone_override));

    let mut updates = Map::new();
    updates.insert("cliPath".to_owned(), json!(configured_path));
    updates.insert(
        "costUsageBucketTimeZone".to_owned(),
        json!(timezone_preference),
    );
    preferences
        .update_transactional(updates)
        .map_err(|error| SettingsError::preferences(error, "settings_cli_reconfigure"))?;

    cli.replace(replacement);
    let refresh_queued = refresh.send(ControllerCommand::ForceRefresh).await.is_ok();
    Ok(CliReconfigureResult {
        applied: true,
        refresh_queued,
    })
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderAction {
    Enable,
    Disable,
    SetSource { source: ProviderSource },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderSource {
    Auto,
    Web,
    Cli,
    Oauth,
    Api,
}

impl ProviderSource {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Web => "web",
            Self::Cli => "cli",
            Self::Oauth => "oauth",
            Self::Api => "api",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SettingsErrorCategory {
    CliNotFound,
    CliTimeout,
    CliCancelled,
    CliProcess,
    CliProtocol,
    CommandRejected,
    InvalidInput,
    PreferencesIo,
    PreferencesDocument,
    AutostartIo,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SettingsError {
    pub category: SettingsErrorCategory,
    pub operation: &'static str,
}

impl SettingsError {
    const fn new(category: SettingsErrorCategory, operation: &'static str) -> Self {
        Self {
            category,
            operation,
        }
    }

    pub const fn invalid_input(operation: &'static str) -> Self {
        Self::new(SettingsErrorCategory::InvalidInput, operation)
    }

    fn cli(error: CliError, operation: &'static str) -> Self {
        let category = match error.kind {
            CliErrorKind::NotFound => SettingsErrorCategory::CliNotFound,
            CliErrorKind::Timeout => SettingsErrorCategory::CliTimeout,
            CliErrorKind::Cancelled => SettingsErrorCategory::CliCancelled,
            CliErrorKind::Spawn | CliErrorKind::Io => SettingsErrorCategory::CliProcess,
            CliErrorKind::InvalidJson => SettingsErrorCategory::CliProtocol,
            CliErrorKind::CommandRejected => SettingsErrorCategory::CommandRejected,
        };
        Self::new(category, operation)
    }

    fn preferences(error: io::Error, operation: &'static str) -> Self {
        let category = if error.kind() == io::ErrorKind::InvalidData {
            SettingsErrorCategory::PreferencesDocument
        } else {
            SettingsErrorCategory::PreferencesIo
        };
        Self::new(category, operation)
    }
}

impl std::fmt::Display for SettingsError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let category = match self.category {
            SettingsErrorCategory::CliNotFound => "cli_not_found",
            SettingsErrorCategory::CliTimeout => "cli_timeout",
            SettingsErrorCategory::CliCancelled => "cli_cancelled",
            SettingsErrorCategory::CliProcess => "cli_process",
            SettingsErrorCategory::CliProtocol => "cli_protocol",
            SettingsErrorCategory::CommandRejected => "command_rejected",
            SettingsErrorCategory::InvalidInput => "invalid_input",
            SettingsErrorCategory::PreferencesIo => "preferences_io",
            SettingsErrorCategory::PreferencesDocument => "preferences_document",
            SettingsErrorCategory::AutostartIo => "autostart_io",
        };
        write!(formatter, "{category} ({})", self.operation)
    }
}

impl std::error::Error for SettingsError {}

/// Load every settings section independently. One command or filesystem
/// failure never erases usable data from another section.
pub async fn settings_snapshot(
    cli: &CliService,
    home: &Path,
    timeout: Duration,
) -> SettingsSnapshot {
    let (providers, hooks, plugins) = tokio::join!(
        cli.config_providers_checked(timeout, None),
        cli.hooks_checked(timeout, None),
        cli.plugins_checked(timeout, None),
    );
    SettingsSnapshot {
        providers: providers
            .map(SettingsSection::success)
            .map_err(|error| SettingsError::cli(error, "settings_providers"))
            .unwrap_or_else(SettingsSection::failure),
        hooks: hooks
            .map(parse_hooks)
            .map(SettingsSection::success)
            .map_err(|error| SettingsError::cli(error, "settings_hooks"))
            .unwrap_or_else(SettingsSection::failure),
        plugins: plugins
            .map(|values| values.into_iter().map(parse_plugin).collect())
            .map(SettingsSection::success)
            .map_err(|error| SettingsError::cli(error, "settings_plugins"))
            .unwrap_or_else(SettingsSection::failure),
        launch_at_login: match launch_at_login_state_at(home) {
            Ok(state) => SettingsSection::success(state),
            Err(_) => SettingsSection::failure(SettingsError::new(
                SettingsErrorCategory::AutostartIo,
                "settings_launch_at_login_state",
            )),
        },
    }
}

pub async fn provider_action(
    cli: &CliService,
    action: ProviderAction,
    provider_id: &str,
    timeout: Duration,
) -> Result<(), SettingsError> {
    if provider_id.trim().is_empty() || provider_id.chars().any(char::is_control) {
        return Err(SettingsError::new(
            SettingsErrorCategory::InvalidInput,
            "settings_provider_action",
        ));
    }
    let (action_name, source) = match action {
        ProviderAction::Enable => ("enable", None),
        ProviderAction::Disable => ("disable", None),
        ProviderAction::SetSource { source } => ("set-source", Some(source.as_str())),
    };
    let result = cli
        .provider_action(action_name, provider_id, source, timeout, None)
        .await
        .map_err(|error| SettingsError::cli(error, "settings_provider_action"))?;
    check_action_result(result, "settings_provider_action")
}

pub async fn set_api_key(
    cli: &CliService,
    provider_id: &str,
    secret: &str,
    timeout: Duration,
) -> Result<(), SettingsError> {
    if provider_id.trim().is_empty()
        || provider_id.chars().any(char::is_control)
        || secret.trim().is_empty()
    {
        return Err(SettingsError::new(
            SettingsErrorCategory::InvalidInput,
            "settings_set_api_key",
        ));
    }
    let result = cli
        .set_api_key(provider_id, secret, timeout, None)
        .await
        .map_err(|error| SettingsError::cli(error, "settings_set_api_key"))?;
    check_action_result(result, "settings_set_api_key")
}

pub async fn set_hooks_enabled(
    cli: &CliService,
    enabled: bool,
    timeout: Duration,
) -> Result<(), SettingsError> {
    let result = cli
        .set_hooks_enabled(enabled, timeout, None)
        .await
        .map_err(|error| SettingsError::cli(error, "settings_set_hooks_enabled"))?;
    check_action_result(result, "settings_set_hooks_enabled")
}

fn check_action_result(result: CliResult, operation: &'static str) -> Result<(), SettingsError> {
    if result.returncode == 0 {
        Ok(())
    } else {
        // Do not propagate stdout/stderr; either can contain credentials or
        // provider-specific command details.
        Err(SettingsError::new(
            SettingsErrorCategory::CommandRejected,
            operation,
        ))
    }
}

pub fn preferences_export_to(
    preferences: &PreferencesStore,
    path: &Path,
) -> Result<(), SettingsError> {
    preferences
        .export_to_path(path)
        .map_err(|error| SettingsError::preferences(error, "settings_preferences_export"))
}

pub fn preferences_import_from(
    preferences: &PreferencesStore,
    path: &Path,
) -> Result<(), SettingsError> {
    preferences
        .import_from_path(path)
        .map_err(|error| SettingsError::preferences(error, "settings_preferences_import"))
}

pub fn preferences_reset(preferences: &PreferencesStore) -> Result<(), SettingsError> {
    preferences
        .reset()
        .map_err(|error| SettingsError::preferences(error, "settings_preferences_reset"))
}

pub fn launch_at_login_state(home: &Path) -> Result<LaunchAtLoginState, SettingsError> {
    launch_at_login_state_at(home).map_err(|_| {
        SettingsError::new(
            SettingsErrorCategory::AutostartIo,
            "settings_launch_at_login_state",
        )
    })
}

pub fn set_launch_at_login(
    preferences: &PreferencesStore,
    home: &Path,
    enabled: bool,
    app_exec: &str,
) -> Result<LaunchAtLoginState, SettingsError> {
    if enabled && (app_exec.trim().is_empty() || app_exec.chars().any(char::is_control)) {
        return Err(SettingsError::new(
            SettingsErrorCategory::InvalidInput,
            "settings_launch_at_login_set",
        ));
    }
    set_launch_at_login_at(home, enabled, app_exec).map_err(|_| {
        SettingsError::new(
            SettingsErrorCategory::AutostartIo,
            "settings_launch_at_login_set",
        )
    })?;
    preferences
        .set("launchAtLogin", Value::Bool(enabled), true)
        .map_err(|error| SettingsError::preferences(error, "settings_launch_at_login_set"))?;
    Ok(LaunchAtLoginState { enabled })
}

fn parse_hooks(value: Value) -> HookSettings {
    let enabled = value
        .get("enabled")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let events = value
        .get("events")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
        .map(|event| HookRule {
            event: event
                .get("event")
                .and_then(Value::as_str)
                .map(str::to_owned),
            executable: event
                .get("executable")
                .and_then(Value::as_str)
                .map(str::to_owned),
            enabled: event.get("enabled").and_then(Value::as_bool),
        })
        .collect();
    HookSettings { enabled, events }
}

fn parse_plugin(value: Value) -> PluginInfo {
    let field = |key: &str| value.get(key).and_then(Value::as_str).map(str::to_owned);
    PluginInfo {
        id: field("id"),
        name: field("name"),
        version: field("version"),
        provider: field("provider"),
    }
}

fn autostart_file(home: &Path) -> PathBuf {
    home.join(".config/autostart/codexbar-gtk.desktop")
}

fn launch_at_login_state_at(home: &Path) -> io::Result<LaunchAtLoginState> {
    Ok(LaunchAtLoginState {
        enabled: autostart_file(home).try_exists()?,
    })
}

fn set_launch_at_login_at(home: &Path, enabled: bool, app_exec: &str) -> io::Result<()> {
    let path = autostart_file(home);
    if enabled {
        if app_exec.trim().is_empty() || app_exec.chars().any(char::is_control) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid executable",
            ));
        }
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid autostart path"))?;
        fs::create_dir_all(parent)?;
        let quoted_exec = format!(
            "\"{}\"",
            app_exec.replace('\\', "\\\\").replace('"', "\\\"")
        );
        let document = format!(
            "[Desktop Entry]\nType=Application\nName=CodexBar\nExec={quoted_exec}\nX-GNOME-Autostart-enabled=true\nTerminal=false\n"
        );
        write_private_atomic(&path, document.as_bytes())
    } else {
        match fs::remove_file(path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error),
        }
    }
}

fn write_private_atomic(path: &Path, contents: &[u8]) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid destination"))?;
    fs::create_dir_all(parent)?;
    let temporary = loop {
        let suffix = NEXT_AUTOSTART_TEMP.fetch_add(1, Ordering::Relaxed);
        let name = format!("codexbar-gtk.desktop.tmp-{}-{suffix}", std::process::id());
        let candidate = parent.join(name);
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&candidate) {
            Ok(mut file) => {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o600))?;
                }
                let result = file.write_all(contents).and_then(|_| file.sync_all());
                drop(file);
                if let Err(error) = result {
                    let _ = fs::remove_file(&candidate);
                    return Err(error);
                }
                break candidate;
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    };
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(temporary);
        return Err(error);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);
    static PROCESS_TEST_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    struct Fixture {
        dir: PathBuf,
        executable: PathBuf,
    }

    impl Fixture {
        fn new(script: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "codexbar-settings-test-{}-{}",
                std::process::id(),
                NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&dir).unwrap();
            let executable = dir.join("fake-cli");
            fs::write(&executable, format!("#!/bin/sh\n{script}\n")).unwrap();
            fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
            Self { dir, executable }
        }

        fn home(&self) -> PathBuf {
            self.dir.join("home")
        }

        fn cli(&self) -> CliService {
            CliService::new(&self.executable, None)
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }

    #[tokio::test]
    async fn checked_settings_reads_reject_valid_looking_json_on_nonzero_exit() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new(
            r#"case "$1/$2" in
  config/providers) printf 'codex: enabled (Codex)\n'; printf 'synthetic detail\n' >&2; exit 7;;
  hooks/list) printf '{"enabled":true,"events":[]}'; exit 8;;
  plugins/list) printf '[{"id":"fixture-plugin"}]'; exit 9;;
esac
exit 0"#,
        );
        let preferences = PreferencesStore::new(fixture.home().join("settings.json"));
        let snapshot =
            settings_snapshot(&fixture.cli(), &fixture.home(), Duration::from_secs(2)).await;

        for (category, operation) in [
            (snapshot.providers.error.as_ref(), "settings_providers"),
            (snapshot.hooks.error.as_ref(), "settings_hooks"),
            (snapshot.plugins.error.as_ref(), "settings_plugins"),
        ] {
            let error = category.expect("nonzero command is a section failure");
            assert_eq!(error.category, SettingsErrorCategory::CommandRejected);
            assert_eq!(error.operation, operation);
        }
        assert!(snapshot.providers.value.is_none());
        assert!(snapshot.hooks.value.is_none());
        assert!(snapshot.plugins.value.is_none());
        let serialized = serde_json::to_string(&snapshot).unwrap();
        assert!(!serialized.contains("synthetic detail"));
        assert!(!serialized.contains("codex: enabled"));
        assert_eq!(preferences.get("launchAtLogin"), Some(Value::Bool(false)));
    }

    #[tokio::test]
    async fn timeout_and_partial_read_failure_keep_successful_settings_sections() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new(
            r#"case "$1/$2" in
  config/providers) printf 'codex: enabled (Codex)\n'; exit 0;;
  hooks/list) sleep 2; printf '{"enabled":false,"events":[]}'; exit 0;;
  plugins/list) printf '[{"id":"fixture-plugin","version":"1"}]'; exit 0;;
esac
exit 0"#,
        );
        let snapshot =
            settings_snapshot(&fixture.cli(), &fixture.home(), Duration::from_millis(120)).await;

        assert_eq!(snapshot.providers.value.as_ref().unwrap().len(), 1);
        assert_eq!(
            snapshot.plugins.value.as_ref().unwrap()[0].id.as_deref(),
            Some("fixture-plugin")
        );
        assert!(snapshot.hooks.value.is_none());
        let error = snapshot.hooks.error.as_ref().unwrap();
        assert_eq!(error.category, SettingsErrorCategory::CliTimeout);
        assert_eq!(error.operation, "settings_hooks");
        assert_eq!(
            snapshot.launch_at_login.value,
            Some(LaunchAtLoginState { enabled: false })
        );
    }

    #[tokio::test]
    async fn hooks_plugins_and_provider_actions_return_owned_typed_values() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new(
            r#"case "$1/$2" in
  config/providers) printf 'codex: enabled (Codex)\n'; exit 0;;
  hooks/list) printf '{"enabled":true,"events":[{"event":"session-start","executable":"fixture-hook","enabled":false},{"event":"future-rule"}]}'; exit 0;;
  plugins/list) printf '[{"id":"fixture-plugin","version":"1","provider":"example"}]'; exit 0;;
  config/set-source) printf 'changed\n'; exit 0;;
esac
exit 0"#,
        );
        let snapshot =
            settings_snapshot(&fixture.cli(), &fixture.home(), Duration::from_secs(2)).await;
        assert!(snapshot.providers.error.is_none());
        assert_eq!(
            snapshot.providers.value.as_ref().unwrap()[0].provider_id,
            "codex"
        );
        let hooks = snapshot.hooks.value.unwrap();
        assert!(hooks.enabled);
        assert_eq!(hooks.events[0].event.as_deref(), Some("session-start"));
        assert_eq!(hooks.events[0].enabled, Some(false));
        assert_eq!(hooks.events[1].executable, None);
        let plugins = snapshot.plugins.value.unwrap();
        assert_eq!(plugins[0].id.as_deref(), Some("fixture-plugin"));
        assert_eq!(plugins[0].provider.as_deref(), Some("example"));
        provider_action(
            &fixture.cli(),
            ProviderAction::SetSource {
                source: ProviderSource::Web,
            },
            "codex",
            Duration::from_secs(2),
        )
        .await
        .unwrap();
        assert!(provider_action(
            &fixture.cli(),
            ProviderAction::SetSource {
                source: ProviderSource::Web,
            },
            "\n",
            Duration::from_secs(2),
        )
        .await
        .unwrap_err()
        .to_string()
        .starts_with("invalid_input (settings_provider_action)"));
    }

    #[tokio::test]
    async fn rejected_mutation_does_not_return_command_output_or_secret() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new(
            r#"printf 'fixture-only-api-key-output\n'; printf 'fixture-only-error\n' >&2; exit 6"#,
        );
        let error = set_api_key(
            &fixture.cli(),
            "codex",
            "fixture-only-key",
            Duration::from_secs(2),
        )
        .await
        .unwrap_err();
        assert_eq!(error.category, SettingsErrorCategory::CommandRejected);
        assert!(!error.to_string().contains("fixture-only"));
        let serialized = serde_json::to_string(&error).unwrap();
        assert!(!serialized.contains("fixture-only"));
    }

    #[tokio::test]
    async fn cli_reconfigure_rejects_invalid_path_without_persisting_or_swapping() {
        let fixture = Fixture::new("printf 'old'");
        let preferences = Arc::new(PreferencesStore::new(fixture.home().join("settings.json")));
        preferences.set("cliPath", json!("before"), false).unwrap();
        preferences
            .set("costUsageBucketTimeZone", json!("Before/Zone"), false)
            .unwrap();
        let original = Arc::new(CliService::new(&fixture.executable, None));
        let shared = Arc::new(SharedCliService::new(original.clone()));
        let (refresh, mut refresh_rx) = mpsc::channel(4);
        let actor = CliReconfigureActor::start(
            &tokio::runtime::Handle::current(),
            shared.clone(),
            preferences.clone(),
            fixture.executable.clone(),
            refresh,
        );

        let error = actor
            .reconfigure(
                Some("/path/that/does/not/exist".into()),
                Some("After/Zone".into()),
            )
            .await
            .unwrap_err();
        assert_eq!(error.category, SettingsErrorCategory::InvalidInput);
        assert_eq!(error.operation, "settings_cli_reconfigure");
        assert!(Arc::ptr_eq(&shared.snapshot(), &original));
        assert_eq!(preferences.get("cliPath"), Some(json!("before")));
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Before/Zone"))
        );
        assert!(matches!(
            refresh_rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
    }

    #[tokio::test]
    async fn cli_reconfigure_persistence_failure_keeps_slot_and_preferences_unchanged() {
        let fixture = Fixture::new("printf 'old'");
        let blocker = fixture.home().join("settings-parent-file");
        fs::create_dir_all(fixture.home()).unwrap();
        fs::write(&blocker, "not a directory").unwrap();
        let preferences = Arc::new(PreferencesStore::new(blocker.join("settings.json")));
        preferences.set("cliPath", json!("before"), false).unwrap();
        let original = Arc::new(CliService::new(&fixture.executable, None));
        let shared = Arc::new(SharedCliService::new(original.clone()));
        let (refresh, mut refresh_rx) = mpsc::channel(4);
        let actor = CliReconfigureActor::start(
            &tokio::runtime::Handle::current(),
            shared.clone(),
            preferences.clone(),
            fixture.executable.clone(),
            refresh,
        );

        let error = actor
            .reconfigure(
                Some(fixture.executable.to_string_lossy().into_owned()),
                Some("After/Zone".into()),
            )
            .await
            .unwrap_err();
        assert_eq!(error.category, SettingsErrorCategory::PreferencesIo);
        assert_eq!(error.operation, "settings_cli_reconfigure");
        assert!(Arc::ptr_eq(&shared.snapshot(), &original));
        assert_eq!(preferences.get("cliPath"), Some(json!("before")));
        assert_eq!(preferences.get("costUsageBucketTimeZone"), Some(json!("")));
        assert!(matches!(
            refresh_rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
    }

    #[tokio::test]
    async fn cli_reconfigure_keeps_inflight_old_config_and_uses_new_argv_timezone_after_commit() {
        let old_fixture = Fixture::new("");
        let new_fixture = Fixture::new(r#"printf 'new|%s|%s' "$*" "${TZ-unset}""#);
        let started = old_fixture.dir.join("started");
        let release = old_fixture.dir.join("release");
        fs::write(
            &old_fixture.executable,
            format!(
                "#!/bin/sh\nprintf started > '{}'\nwhile [ ! -f '{}' ]; do sleep 0.01; done\nprintf 'old|%s|%s' \"$*\" \"${{TZ-unset}}\"\n",
                started.display(),
                release.display(),
            ),
        )
        .unwrap();
        let preferences = Arc::new(PreferencesStore::new(
            old_fixture
                .home()
                .join(".config/codexbar-gtk/settings.json"),
        ));
        let old = Arc::new(CliService::new(
            &old_fixture.executable,
            Some("Old/Zone".into()),
        ));
        let shared = Arc::new(SharedCliService::new(old));
        let (refresh, mut refresh_rx) = mpsc::channel(4);
        let actor = CliReconfigureActor::start(
            &tokio::runtime::Handle::current(),
            shared.clone(),
            preferences.clone(),
            new_fixture.executable.clone(),
            refresh,
        );

        let in_flight_service = shared.snapshot();
        let in_flight = tokio::spawn(async move {
            in_flight_service
                .run(&["probe".into()], Duration::from_secs(3), None)
                .await
                .unwrap()
        });
        tokio::time::timeout(Duration::from_secs(2), async {
            while !started.exists() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("old CLI call should start before reconfiguration");

        let outcome = actor
            .reconfigure(
                Some(format!("  {}  ", new_fixture.executable.display())),
                Some("Pacific/Chatham".into()),
            )
            .await
            .unwrap();
        assert_eq!(
            outcome,
            CliReconfigureResult {
                applied: true,
                refresh_queued: true,
            }
        );
        assert!(matches!(
            refresh_rx.recv().await,
            Some(ControllerCommand::ForceRefresh)
        ));
        assert_eq!(
            preferences.get("cliPath"),
            Some(json!(new_fixture.executable.to_string_lossy().as_ref()))
        );
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Pacific/Chatham"))
        );

        let later = shared
            .snapshot()
            .run(&["next-pass".into()], Duration::from_secs(2), None)
            .await
            .unwrap();
        assert_eq!(later.stdout, "new|next-pass|Pacific/Chatham");
        fs::write(&release, "release").unwrap();
        let earlier = in_flight.await.unwrap();
        assert_eq!(earlier.stdout, "old|probe|Old/Zone");
    }

    #[tokio::test]
    async fn cli_reconfigure_actor_serializes_concurrent_commits_and_reports_closed_refresh() {
        let first = Fixture::new(r#"printf 'first|%s' "${TZ-unset}""#);
        let second = Fixture::new(r#"printf 'second|%s' "${TZ-unset}""#);
        let preferences = Arc::new(PreferencesStore::new(first.home().join("settings.json")));
        preferences
            .set(
                "cliPath",
                json!(second.executable.to_string_lossy().as_ref()),
                false,
            )
            .unwrap();
        preferences
            .set("costUsageBucketTimeZone", json!("Initial/Zone"), false)
            .unwrap();
        let shared = Arc::new(SharedCliService::new(Arc::new(CliService::new(
            &second.executable,
            Some("Initial/Zone".into()),
        ))));
        let (refresh, mut refresh_rx) = mpsc::channel(8);
        let actor = CliReconfigureActor::start(
            &tokio::runtime::Handle::current(),
            shared.clone(),
            preferences.clone(),
            first.executable.clone(),
            refresh,
        );

        actor.reconfigure(Some(String::new()), None).await.unwrap();
        assert_eq!(preferences.get("cliPath"), Some(json!("")));
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Initial/Zone"))
        );
        let path_only = shared
            .snapshot()
            .run(&["probe".into()], Duration::from_secs(2), None)
            .await
            .unwrap();
        assert_eq!(path_only.stdout, "first|Initial/Zone");

        actor.reconfigure(None, Some(String::new())).await.unwrap();
        let system_timezone = std::env::var("TZ").unwrap_or_else(|_| "unset".to_owned());
        assert_eq!(preferences.get("cliPath"), Some(json!("")));
        assert_eq!(preferences.get("costUsageBucketTimeZone"), Some(json!("")));
        let timezone_only = shared
            .snapshot()
            .run(&["probe".into()], Duration::from_secs(2), None)
            .await
            .unwrap();
        assert_eq!(timezone_only.stdout, format!("first|{system_timezone}"));

        let (left, right) = tokio::join!(
            actor.reconfigure(Some(second.executable.to_string_lossy().into_owned()), None),
            actor.reconfigure(None, Some("Second/Zone".into())),
        );
        assert!(left.unwrap().applied);
        assert!(right.unwrap().applied);
        let final_cli_path = preferences.get("cliPath").unwrap();
        let final_timezone = preferences.get("costUsageBucketTimeZone").unwrap();
        let final_result = shared
            .snapshot()
            .run(&["probe".into()], Duration::from_secs(2), None)
            .await
            .unwrap();
        let final_cli_path = final_cli_path.as_str().unwrap();
        let final_timezone = final_timezone.as_str().unwrap();
        assert_eq!(final_cli_path, second.executable.to_string_lossy());
        assert_eq!(final_timezone, "Second/Zone");
        assert_eq!(final_result.stdout, "second|Second/Zone");

        let queued_before_noop = refresh_rx.len();
        let no_op = actor.reconfigure(None, None).await.unwrap_err();
        assert_eq!(no_op.category, SettingsErrorCategory::InvalidInput);
        assert_eq!(
            refresh_rx.len(),
            queued_before_noop,
            "an empty patch queues no refresh"
        );
        assert_eq!(preferences.get("cliPath"), Some(json!(final_cli_path)));
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!(final_timezone))
        );
        while refresh_rx.try_recv().is_ok() {}

        drop(refresh_rx);
        let result = actor
            .reconfigure(Some(String::new()), None)
            .await
            .expect("refresh channel closure occurs after commit");
        assert_eq!(
            result,
            CliReconfigureResult {
                applied: true,
                refresh_queued: false,
            }
        );
        assert_eq!(preferences.get("cliPath"), Some(json!("")));
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Second/Zone"))
        );
        assert_eq!(
            shared.snapshot().executable(),
            first.executable.as_path(),
            "clearing the override returns to the discovered default executable"
        );
    }

    #[tokio::test]
    async fn coalesced_controller_refresh_uses_final_partial_patch_pair() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let old = Fixture::new("");
        let replacement = Fixture::new("");
        let started = old.dir.join("initial-usage-started");
        let release = old.dir.join("release-initial-usage");
        fs::write(
            &old.executable,
            format!(
                "#!/bin/sh\nif [ \"$1\" = usage ]; then printf started > '{}'; while [ ! -f '{}' ]; do sleep 0.01; done; fi\nprintf '[]\\n'\n",
                started.display(),
                release.display(),
            ),
        )
        .unwrap();
        let log = replacement.dir.join("replacement-calls.log");
        fs::write(
            &replacement.executable,
            format!(
                "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"${{TZ-unset}}\" >> '{}'\ncase \"$1\" in usage|sessions) printf '[]\\n';; --version) printf 'replacement %s\\n' \"${{TZ-unset}}\";; esac\n",
                log.display(),
            ),
        )
        .unwrap();

        let preferences = Arc::new(PreferencesStore::new(old.home().join("settings.json")));
        preferences
            .set("refreshFrequency", json!("manual"), false)
            .unwrap();
        preferences
            .set("costUsageEnabled", json!(false), false)
            .unwrap();
        preferences
            .set(
                "cliPath",
                json!(old.executable.to_string_lossy().as_ref()),
                false,
            )
            .unwrap();
        preferences
            .set("costUsageBucketTimeZone", json!("Initial/Zone"), false)
            .unwrap();

        let cli = Arc::new(SharedCliService::new(Arc::new(CliService::new(
            &old.executable,
            Some("Initial/Zone".into()),
        ))));
        let history = Arc::new(codexbar_core::history::HistoryStore::new(
            old.dir.join("history.jsonl"),
            30,
        ));
        let handle = crate::controller::RefreshControllerHandle::start(
            crate::controller::RefreshControllerConfig::with_shared_cli(
                cli.clone(),
                preferences.clone(),
                history,
            ),
        );
        let actor = CliReconfigureActor::start(
            &tokio::runtime::Handle::current(),
            cli,
            preferences.clone(),
            old.executable.clone(),
            handle.force_refresh_sender(),
        );

        tokio::time::timeout(Duration::from_secs(3), async {
            while !started.exists() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("initial B10 usage command should be in flight");

        let path_only = actor
            .reconfigure(
                Some(replacement.executable.to_string_lossy().into_owned()),
                None,
            )
            .await
            .unwrap();
        assert!(path_only.refresh_queued);
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Initial/Zone")),
            "path-only patch must preserve the timezone"
        );
        let timezone_only = actor
            .reconfigure(None, Some("Final/Zone".into()))
            .await
            .unwrap();
        assert!(timezone_only.refresh_queued);
        assert_eq!(
            preferences.get("cliPath"),
            Some(json!(replacement.executable.to_string_lossy().as_ref())),
            "timezone-only patch must preserve the CLI path"
        );

        fs::write(&release, "release").unwrap();
        let mut state = handle.state();
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                if state
                    .borrow()
                    .snapshot
                    .as_ref()
                    .is_some_and(|snapshot| snapshot.revision >= 2)
                {
                    break;
                }
                state.changed().await.unwrap();
            }
        })
        .await
        .expect("the queued follow-up refresh should publish");
        let snapshot = state.borrow().snapshot.as_ref().unwrap().clone();
        assert_eq!(
            snapshot.revision, 2,
            "two forces coalesce into one follow-up"
        );
        assert_eq!(snapshot.version, "replacement Final/Zone");

        let calls = fs::read_to_string(&log).unwrap();
        for command in ["usage", "sessions", "--version"] {
            assert!(
                calls
                    .lines()
                    .any(|line| line == format!("{command}|Final/Zone")),
                "queued B10 pass should call {command} with the final timezone: {calls}"
            );
        }
        assert_eq!(
            preferences.get("cliPath"),
            Some(json!(replacement.executable.to_string_lossy().as_ref()))
        );
        assert_eq!(
            preferences.get("costUsageBucketTimeZone"),
            Some(json!("Final/Zone"))
        );
        handle.shutdown().await.unwrap();
    }

    #[test]
    fn launch_at_login_updates_desktop_entry_and_shared_preferences() {
        let fixture = Fixture::new("");
        let home = fixture.home();
        let preferences = PreferencesStore::new(home.join(".config/codexbar-gtk/settings.json"));
        assert_eq!(
            launch_at_login_state(&home).unwrap(),
            LaunchAtLoginState { enabled: false }
        );

        let executable = "/tmp/Codex Bar/desktop app\"test";
        assert_eq!(
            set_launch_at_login(&preferences, &home, true, executable).unwrap(),
            LaunchAtLoginState { enabled: true }
        );
        assert_eq!(preferences.get("launchAtLogin"), Some(Value::Bool(true)));
        let path = autostart_file(&home);
        let contents = fs::read_to_string(&path).unwrap();
        assert!(contents.contains("Exec=\"/tmp/Codex Bar/desktop app\\\"test\""));
        assert_eq!(
            launch_at_login_state(&home).unwrap(),
            LaunchAtLoginState { enabled: true }
        );
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );

        assert_eq!(
            set_launch_at_login(&preferences, &home, false, executable).unwrap(),
            LaunchAtLoginState { enabled: false }
        );
        assert_eq!(preferences.get("launchAtLogin"), Some(Value::Bool(false)));
        assert!(!path.exists());
    }

    #[test]
    fn launch_at_login_failures_are_fallible_and_sanitized() {
        let fixture = Fixture::new("");
        let home = fixture.home();
        let preferences = PreferencesStore::new(home.join("settings.json"));
        let invalid = set_launch_at_login(&preferences, &home, true, "bad\nexec").unwrap_err();
        assert_eq!(invalid.category, SettingsErrorCategory::InvalidInput);
        assert_eq!(invalid.operation, "settings_launch_at_login_set");

        let blocker = home.join(".config");
        fs::create_dir_all(&home).unwrap();
        fs::write(&blocker, "file").unwrap();
        let error = launch_at_login_state(&home).unwrap_err();
        assert_eq!(error.category, SettingsErrorCategory::AutostartIo);
        assert_eq!(error.operation, "settings_launch_at_login_state");
        assert!(!error
            .to_string()
            .contains(blocker.to_string_lossy().as_ref()));
    }
}
