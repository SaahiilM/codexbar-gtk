//! Asynchronous, argv-safe access to the external CodexBar CLI.
//!
//! This service owns non-interactive commands only. Interactive login and
//! other terminal sessions belong to the PTY service. Errors crossing this
//! boundary contain a stable category and static operation ID, never process
//! output, paths, URLs, or credentials.

use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    process::Stdio,
    sync::{Arc, RwLock},
    time::{Duration, Instant},
};

use serde_json::Value;
use tokio::{io::AsyncReadExt, process::Command, task::JoinHandle, time};

use crate::Cancellation;

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
pub enum CliErrorKind {
    NotFound,
    Timeout,
    Cancelled,
    Spawn,
    Io,
    InvalidJson,
    /// A checked typed operation received a nonzero command exit status.
    CommandRejected,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
pub struct CliError {
    pub kind: CliErrorKind,
    pub operation: &'static str,
}

impl CliError {
    const fn new(kind: CliErrorKind, operation: &'static str) -> Self {
        Self { kind, operation }
    }

    pub const fn backend_error(self) -> crate::BackendError {
        let kind = match self.kind {
            CliErrorKind::NotFound | CliErrorKind::Spawn | CliErrorKind::Io => {
                crate::BackendErrorKind::Process
            }
            CliErrorKind::Timeout => crate::BackendErrorKind::Timeout,
            CliErrorKind::Cancelled => crate::BackendErrorKind::Cancelled,
            CliErrorKind::InvalidJson => crate::BackendErrorKind::Protocol,
            CliErrorKind::CommandRejected => crate::BackendErrorKind::Process,
        };
        crate::BackendError::new(kind, self.operation)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
pub struct CliResult {
    pub returncode: i32,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
pub struct ProviderStatusEntry {
    pub provider_id: String,
    pub enabled: bool,
    pub display_name: String,
    pub is_default: bool,
}

/// Resolve an executable from an explicit override, app-local locations, or
/// PATH. `package_dir` is the Python package directory during transition and
/// may be any known app directory in a native frontend.
pub fn discover_executable(
    name: &str,
    override_env: Option<&str>,
    package_dir: &Path,
) -> Result<PathBuf, CliError> {
    if let Some(value) = override_env.and_then(std::env::var_os) {
        if !value.is_empty() {
            return Ok(absolute_lexical(&PathBuf::from(value)));
        }
    }

    for candidate in [
        package_dir.join("..").join("bin").join(name),
        package_dir.join("..").join("..").join("bin").join(name),
    ] {
        let candidate = absolute_lexical(&candidate);
        if is_executable_file(&candidate) {
            return Ok(candidate);
        }
    }

    if let Some(path) = std::env::var_os("PATH") {
        for folder in std::env::split_paths(&path) {
            let candidate = absolute_lexical(&folder.join(name));
            if is_executable_file(&candidate) {
                return Ok(candidate);
            }
        }
    }

    if let Some(home) = std::env::var_os("HOME") {
        let candidate = PathBuf::from(home)
            .join(".local/lib/codexbar-cli")
            .join(name);
        if candidate.is_file() {
            return Ok(candidate);
        }
    }

    Err(CliError::new(CliErrorKind::NotFound, "cli_discovery"))
}

fn absolute_lexical(path: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn is_executable_file(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .map(|metadata| metadata.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        true
    }
}

/// Resolve a command from PATH only. Use this for optional platform tools such
/// as terminal emulators; unlike `discover_executable`, it does not search
/// app-local CLI bundles or user CLI install directories.
pub fn find_executable_on_path(name: &str) -> Option<PathBuf> {
    find_executable_in_path(name, std::env::var_os("PATH").as_deref())
}

fn find_executable_in_path(name: &str, path: Option<&std::ffi::OsStr>) -> Option<PathBuf> {
    std::env::split_paths(path?)
        .map(|folder| folder.join(name))
        .find(|candidate| is_executable_file(candidate))
        .map(|candidate| absolute_lexical(&candidate))
}

/// Whether an explicit CLI setting resolves to an executable. A bare command
/// name is accepted when it is present on PATH; the configured spelling is
/// retained so subprocess argv behavior remains compatible with Python.
pub fn executable_override_is_valid(value: &str) -> bool {
    let path = Path::new(value);
    if path.components().count() > 1 || path.is_absolute() {
        return is_executable_file(path);
    }
    std::env::var_os("PATH")
        .into_iter()
        .flat_map(|paths| std::env::split_paths(&paths).collect::<Vec<_>>())
        .any(|folder| is_executable_file(&folder.join(path)))
}

/// Configuration is immutable while a call is running. A caller constructs a
/// new service when the configured executable or timezone changes.
#[derive(Clone, Debug)]
pub struct CliService {
    executable: PathBuf,
    timezone: Option<OsString>,
}

impl CliService {
    pub fn new(executable: impl Into<PathBuf>, timezone: Option<OsString>) -> Self {
        Self {
            executable: executable.into(),
            timezone,
        }
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }

    pub async fn run(
        &self,
        args: &[OsString],
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<CliResult, CliError> {
        self.run_operation(args, timeout, cancellation, "cli_command")
            .await
    }

    async fn run_operation(
        &self,
        args: &[OsString],
        timeout: Duration,
        cancellation: Option<Cancellation>,
        operation: &'static str,
    ) -> Result<CliResult, CliError> {
        let mut command = Command::new(&self.executable);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.as_std_mut().process_group(0);
        }
        if let Some(timezone) = &self.timezone {
            command.env("TZ", timezone);
        }

        let mut child = command.spawn().map_err(|error| {
            CliError::new(
                if error.kind() == std::io::ErrorKind::NotFound {
                    CliErrorKind::NotFound
                } else {
                    CliErrorKind::Spawn
                },
                operation,
            )
        })?;
        let process_group_id = child.id();
        let stdout = child.stdout.take().expect("stdout was piped");
        let stderr = child.stderr.take().expect("stderr was piped");
        let mut stdout_task = tokio::spawn(read_all(stdout));
        let mut stderr_task = tokio::spawn(read_all(stderr));
        let started = Instant::now();

        enum WaitResult {
            Exited(std::io::Result<std::process::ExitStatus>),
            TimedOut,
            Cancelled,
        }
        let wait_result = if let Some(cancel) = cancellation {
            tokio::select! {
                status = child.wait() => WaitResult::Exited(status),
                _ = time::sleep(timeout) => WaitResult::TimedOut,
                _ = cancel.cancelled() => WaitResult::Cancelled,
            }
        } else {
            tokio::select! {
                status = child.wait() => WaitResult::Exited(status),
                _ = time::sleep(timeout) => WaitResult::TimedOut,
            }
        };

        match wait_result {
            WaitResult::Exited(status) => {
                let status = status.map_err(|_| CliError::new(CliErrorKind::Io, operation))?;
                let drained = time::timeout(timeout.saturating_sub(started.elapsed()), async {
                    let stdout = join_output(&mut stdout_task, operation).await?;
                    let stderr = join_output(&mut stderr_task, operation).await?;
                    Ok::<_, CliError>((stdout, stderr))
                })
                .await;
                let (stdout, stderr) = match drained {
                    Ok(result) => result?,
                    Err(_) => {
                        kill_process_group(process_group_id);
                        let _ = join_output(&mut stdout_task, operation).await;
                        let _ = join_output(&mut stderr_task, operation).await;
                        return Err(CliError::new(CliErrorKind::Timeout, operation));
                    }
                };
                Ok(CliResult {
                    returncode: status.code().unwrap_or(-1),
                    stdout: String::from_utf8_lossy(&stdout).into_owned(),
                    stderr: String::from_utf8_lossy(&stderr).into_owned(),
                })
            }
            WaitResult::TimedOut => {
                // `kill` waits for the child in Tokio. Keep an explicit wait
                // after the kill attempt so every terminal path is joined.
                kill_process_group(process_group_id);
                let _ = child.kill().await;
                let _ = child.wait().await;
                let _ = join_output(&mut stdout_task, operation).await;
                let _ = join_output(&mut stderr_task, operation).await;
                Err(CliError::new(CliErrorKind::Timeout, operation))
            }
            WaitResult::Cancelled => {
                kill_process_group(process_group_id);
                let _ = child.kill().await;
                let _ = child.wait().await;
                let _ = join_output(&mut stdout_task, operation).await;
                let _ = join_output(&mut stderr_task, operation).await;
                Err(CliError::new(CliErrorKind::Cancelled, operation))
            }
        }
    }

    pub async fn run_json(
        &self,
        args: &[OsString],
        timeout: Duration,
        cancellation: Option<Cancellation>,
        operation: &'static str,
    ) -> Result<Value, CliError> {
        let result = self
            .run_operation(args, timeout, cancellation, operation)
            .await?;
        if result.stdout.trim().is_empty() {
            return Err(CliError::new(CliErrorKind::InvalidJson, operation));
        }
        serde_json::from_str(result.stdout.trim())
            .map_err(|_| CliError::new(CliErrorKind::InvalidJson, operation))
    }

    pub async fn version(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<String, CliError> {
        let args = [OsString::from("--version")];
        match self
            .run_operation(
                &args,
                timeout.min(Duration::from_secs(20)),
                cancellation,
                "cli_version",
            )
            .await
        {
            Ok(result) => Ok(if result.stdout.trim().is_empty() {
                "unknown".to_owned()
            } else {
                result.stdout.trim().to_owned()
            }),
            Err(error) => Err(error),
        }
    }

    pub async fn usage(
        &self,
        provider: Option<&str>,
        account_index: Option<u32>,
        all_accounts: bool,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<Value>, CliError> {
        let mut args = vec!["usage".into(), "--format".into(), "json".into()];
        if let Some(provider) = provider.filter(|provider| !provider.is_empty()) {
            args.extend(["--provider".into(), provider.into()]);
        }
        if all_accounts {
            args.push("--all-accounts".into());
        }
        if let Some(index) = account_index {
            args.extend(["--account-index".into(), index.to_string().into()]);
        }
        as_array(
            self.run_json(&args, timeout, cancellation, "cli_usage")
                .await?,
        )
    }

    pub async fn dashboard(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Value, CliError> {
        let args = [OsString::from("dashboard")];
        Ok(
            match self
                .run_json(&args, timeout, cancellation, "cli_dashboard")
                .await?
            {
                Value::Object(object) => Value::Object(object),
                _ => Value::Object(Default::default()),
            },
        )
    }

    pub async fn cost(
        &self,
        provider: Option<&str>,
        days: Option<u32>,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<Value>, CliError> {
        let mut args = vec!["cost".into(), "--format".into(), "json".into()];
        if let Some(provider) = provider.filter(|provider| !provider.is_empty()) {
            args.extend(["--provider".into(), provider.into()]);
        }
        if let Some(days) = days.filter(|days| *days > 0) {
            args.extend(["--days".into(), days.to_string().into()]);
        }
        as_array(
            self.run_json(&args, timeout, cancellation, "cli_cost")
                .await?,
        )
    }

    pub async fn sessions(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<Value>, CliError> {
        let args = ["sessions".into(), "--json-v2".into()];
        let mut output = self
            .run_json(&args, timeout, cancellation, "cli_sessions")
            .await?;
        if let Value::Object(mut object) = output {
            output = object.remove("sessions").unwrap_or(Value::Array(vec![]));
        }
        Ok(output.as_array().cloned().unwrap_or_default())
    }

    pub async fn config_providers(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<ProviderStatusEntry>, CliError> {
        let args = ["config".into(), "providers".into()];
        let result = self
            .run_operation(&args, timeout, cancellation, "cli_config_providers")
            .await?;
        Ok(parse_config_providers(&result.stdout))
    }

    /// Checked settings read that rejects nonzero command status before
    /// interpreting stdout. The generic `run` and `run_json` methods retain
    /// their historical return-code behavior for parity callers.
    pub async fn config_providers_checked(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<ProviderStatusEntry>, CliError> {
        let args = ["config".into(), "providers".into()];
        let result = self
            .run_operation(&args, timeout, cancellation, "cli_config_providers")
            .await?;
        checked_result(result, "cli_config_providers")
            .map(|result| parse_config_providers(&result.stdout))
    }

    pub async fn set_api_key(
        &self,
        provider: &str,
        key: &str,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<CliResult, CliError> {
        self.run_operation(
            &[
                "config",
                "set-api-key",
                "--provider",
                provider,
                "--api-key",
                key,
            ]
            .map(OsString::from),
            timeout,
            cancellation,
            "cli_set_api_key",
        )
        .await
    }

    pub async fn provider_action(
        &self,
        action: &str,
        provider: &str,
        source: Option<&str>,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<CliResult, CliError> {
        let args = if let Some(source) = source {
            vec!["config", action, "--provider", provider, "--source", source]
        } else {
            vec!["config", action, "--provider", provider]
        };
        let args = args.into_iter().map(OsString::from).collect::<Vec<_>>();
        self.run_operation(&args, timeout, cancellation, "cli_config_provider")
            .await
    }

    pub async fn hooks(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Value, CliError> {
        let args = [
            "hooks".into(),
            "list".into(),
            "--format".into(),
            "json".into(),
        ];
        match self
            .run_json(&args, timeout, cancellation, "cli_hooks")
            .await
        {
            Ok(Value::Object(object)) => Ok(Value::Object(object)),
            Ok(_) => Ok(serde_json::json!({"enabled": false, "events": []})),
            Err(error) => Err(error),
        }
    }

    /// Checked settings read that rejects a nonzero exit even if stdout looks
    /// like valid JSON. No process output is included in the error.
    pub async fn hooks_checked(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Value, CliError> {
        let args = [
            "hooks".into(),
            "list".into(),
            "--format".into(),
            "json".into(),
        ];
        let result = self
            .run_operation(&args, timeout, cancellation, "cli_hooks")
            .await?;
        let result = checked_result(result, "cli_hooks")?;
        parse_checked_json(&result.stdout, "cli_hooks").map(|value| match value {
            Value::Object(object) => Value::Object(object),
            _ => serde_json::json!({"enabled": false, "events": []}),
        })
    }

    pub async fn set_hooks_enabled(
        &self,
        enabled: bool,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<CliResult, CliError> {
        let args = [
            "hooks".into(),
            if enabled { "enable" } else { "disable" }.into(),
        ];
        self.run_operation(&args, timeout, cancellation, "cli_hooks_toggle")
            .await
    }

    pub async fn plugins(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<Value>, CliError> {
        let args = ["plugins".into(), "list".into()];
        self.run_json(&args, timeout, cancellation, "cli_plugins")
            .await
            .map(as_array_or_object)
    }

    /// Checked plugin listing used by settings. A nonzero process exit is a
    /// stable command-rejected error, even when stdout contains valid JSON.
    pub async fn plugins_checked(
        &self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> Result<Vec<Value>, CliError> {
        let args = ["plugins".into(), "list".into()];
        let result = self
            .run_operation(&args, timeout, cancellation, "cli_plugins")
            .await?;
        let result = checked_result(result, "cli_plugins")?;
        parse_checked_json(&result.stdout, "cli_plugins").map(as_array_or_object)
    }
}

/// Mutable configuration boundary around immutable CLI service instances.
/// Refresh and settings share one slot; each operation takes a short snapshot
/// and then performs all process I/O without holding the slot lock.
pub struct SharedCliService {
    current: RwLock<Arc<CliService>>,
}

impl SharedCliService {
    pub fn new(initial: Arc<CliService>) -> Self {
        Self {
            current: RwLock::new(initial),
        }
    }

    pub fn snapshot(&self) -> Arc<CliService> {
        self.current
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    pub fn replace(&self, replacement: Arc<CliService>) {
        *self
            .current
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = replacement;
    }
}

fn checked_result(result: CliResult, operation: &'static str) -> Result<CliResult, CliError> {
    if result.returncode == 0 {
        Ok(result)
    } else {
        Err(CliError::new(CliErrorKind::CommandRejected, operation))
    }
}

fn parse_checked_json(stdout: &str, operation: &'static str) -> Result<Value, CliError> {
    if stdout.trim().is_empty() {
        return Err(CliError::new(CliErrorKind::InvalidJson, operation));
    }
    serde_json::from_str(stdout.trim())
        .map_err(|_| CliError::new(CliErrorKind::InvalidJson, operation))
}

fn kill_process_group(process_group_id: Option<u32>) {
    #[cfg(unix)]
    if let Some(pid) = process_group_id {
        // Commands start in a fresh process group so pipes held open by a
        // helper child cannot outlive the timeout or cancellation request.
        unsafe {
            libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
    #[cfg(not(unix))]
    let _ = process_group_id;
}

async fn read_all<R: tokio::io::AsyncRead + Unpin>(mut reader: R) -> std::io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader.read_to_end(&mut bytes).await?;
    Ok(bytes)
}

async fn join_output(
    task: &mut JoinHandle<std::io::Result<Vec<u8>>>,
    operation: &'static str,
) -> Result<Vec<u8>, CliError> {
    task.await
        .map_err(|_| CliError::new(CliErrorKind::Io, operation))?
        .map_err(|_| CliError::new(CliErrorKind::Io, operation))
}

fn as_array(value: Value) -> Result<Vec<Value>, CliError> {
    Ok(match value {
        Value::Array(values) => values,
        Value::Object(_) => vec![value],
        Value::Null => vec![],
        _ => vec![],
    })
}

fn as_array_or_object(value: Value) -> Vec<Value> {
    match value {
        Value::Array(values) => values,
        Value::Object(_) => vec![value],
        _ => vec![],
    }
}

fn parse_config_providers(output: &str) -> Vec<ProviderStatusEntry> {
    output
        .lines()
        .filter_map(|line| {
            let (provider, rest) = line.trim().split_once(':')?;
            let rest = rest.trim();
            let enabled = rest.starts_with("enabled");
            let is_default = enabled && rest.contains("default");
            let display_name = rest
                .rfind('(')
                .and_then(|start| rest.rfind(')').map(|end| (start, end)))
                .filter(|(start, end)| start < end)
                .map(|(start, end)| rest[start + 1..end].trim().to_owned())
                .unwrap_or_default();
            Some(ProviderStatusEntry {
                provider_id: provider.trim().to_owned(),
                enabled,
                display_name,
                is_default,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        sync::atomic::{AtomicU64, Ordering},
    };
    use tokio::sync::watch;

    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    static PROCESS_TEST_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    struct Fixture {
        dir: PathBuf,
        executable: PathBuf,
    }

    impl Fixture {
        fn new(script: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "codexbar-cli-test-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&dir).unwrap();
            let executable = dir.join("fake-cli");
            let script = script.replace("{DIR}", dir.to_string_lossy().as_ref());
            fs::write(&executable, format!("#!/bin/sh\n{script}\n")).unwrap();
            fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
            Self { dir, executable }
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }

    async fn wait_for_fixture_pid(path: &Path) -> i32 {
        for _ in 0..300 {
            if let Ok(contents) = fs::read_to_string(path) {
                if let Ok(pid) = contents.trim().parse() {
                    return pid;
                }
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("fixture process did not write a complete child PID");
    }

    #[tokio::test]
    async fn command_uses_argv_boundaries_and_returns_both_streams_and_status() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new("printf '%s\\n' \"$1\"; printf 'warning\\n' >&2; exit 7");
        let service = CliService::new(&fixture.executable, None);
        let result = service
            .run(&[OsString::from("two words")], Duration::from_secs(2), None)
            .await
            .unwrap();
        assert_eq!(result.returncode, 7);
        assert_eq!(result.stdout, "two words\n");
        assert_eq!(result.stderr, "warning\n");
    }

    #[tokio::test]
    async fn timeout_kills_and_reaps_child_with_sanitized_error() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new("echo $$ > {DIR}/child.pid; sleep 10");
        let service = CliService::new(&fixture.executable, None);
        let error = service
            .run(&[], Duration::from_millis(600), None)
            .await
            .unwrap_err();
        assert_eq!(error, CliError::new(CliErrorKind::Timeout, "cli_command"));
        let pid = wait_for_fixture_pid(&fixture.dir.join("child.pid")).await;
        assert!(!Path::new(&format!("/proc/{pid}")).exists());
    }

    #[tokio::test]
    async fn cancellation_kills_and_reaps_child() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new("echo $$ > {DIR}/child.pid; sleep 10");
        let service = CliService::new(&fixture.executable, None);
        let (sender, receiver) = watch::channel(false);
        let cancellation = Cancellation { receiver };
        let task = tokio::spawn(async move {
            service
                .run(&[], Duration::from_secs(10), Some(cancellation))
                .await
        });
        let pid = wait_for_fixture_pid(&fixture.dir.join("child.pid")).await;
        sender.send_replace(true);
        let error = task.await.unwrap().unwrap_err();
        assert_eq!(error.kind, CliErrorKind::Cancelled);
        assert!(!Path::new(&format!("/proc/{pid}")).exists());
    }

    #[tokio::test]
    async fn output_pipe_drain_is_bounded_when_a_descendant_outlives_leader() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new("sleep 10 & exit 0");
        let service = CliService::new(&fixture.executable, None);
        let started = std::time::Instant::now();
        let error = service
            .run(&[], Duration::from_millis(150), None)
            .await
            .unwrap_err();
        assert_eq!(error.kind, CliErrorKind::Timeout);
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[tokio::test]
    async fn command_methods_preserve_envelopes_and_invalid_json_is_safe() {
        let _guard = PROCESS_TEST_LOCK.lock().await;
        let fixture = Fixture::new(
            "case $1 in usage) printf '{\"provider\":\"claude\"}';; *) printf 'not json';; esac",
        );
        let service = CliService::new(&fixture.executable, None);
        let usage = service
            .usage(None, None, true, Duration::from_secs(2), None)
            .await
            .unwrap();
        assert_eq!(usage[0]["provider"], "claude");
        let error = service
            .sessions(Duration::from_secs(2), None)
            .await
            .unwrap_err();
        assert_eq!(error.kind, CliErrorKind::InvalidJson);
        assert_eq!(error.operation, "cli_sessions");
    }

    #[test]
    fn config_provider_output_becomes_typed_entries() {
        let entries = parse_config_providers(
            "codex: enabled (OpenAI Codex)\nclaude: disabled (Claude)\ninvalid\n",
        );
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].provider_id, "codex");
        assert!(entries[0].enabled);
        assert_eq!(entries[0].display_name, "OpenAI Codex");
        assert_eq!(entries[1].display_name, "Claude");
    }

    #[test]
    fn cli_error_maps_to_the_backend_safe_error_contract() {
        let cli_error = CliError::new(CliErrorKind::InvalidJson, "cli_usage");
        assert_eq!(
            cli_error.backend_error(),
            crate::BackendError::new(crate::BackendErrorKind::Protocol, "cli_usage")
        );
    }

    #[test]
    fn discovery_returns_an_absolute_app_local_path_for_pty_callers() {
        let fixture = Fixture::new("");
        let package_dir = fixture.dir.join("app").join("codexbar_gtk");
        let bundle_bin = fixture.dir.join("app").join("bin");
        fs::create_dir_all(&package_dir).unwrap();
        fs::create_dir_all(&bundle_bin).unwrap();
        let claude = bundle_bin.join("claude");
        fs::write(&claude, "#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(&claude, fs::Permissions::from_mode(0o700)).unwrap();
        let path = discover_executable("claude", None, &package_dir).unwrap();
        assert_eq!(path, claude);
        assert!(path.is_absolute());
    }

    #[test]
    fn path_only_discovery_returns_only_executable_matches() {
        let fixture = Fixture::new("");
        let first = fixture.dir.join("one");
        let second = fixture.dir.join("two");
        fs::create_dir_all(&first).unwrap();
        fs::create_dir_all(&second).unwrap();
        let not_executable = first.join("terminal");
        fs::write(&not_executable, "fixture").unwrap();
        let executable = second.join("terminal");
        fs::write(&executable, "#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
        let path = std::env::join_paths([first, second]).unwrap();
        assert_eq!(
            find_executable_in_path("terminal", Some(path.as_os_str())),
            Some(executable)
        );
    }
}
