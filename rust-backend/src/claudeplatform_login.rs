//! One-shot ClaudePlatform cookie login through the external CodexBar CLI.
//! The submitted value exists only in this operation's memory and child stdin.

use std::{ffi::OsString, path::PathBuf, process::Stdio, time::Duration};

use serde_json::Value;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    process::Command,
    sync::{mpsc, watch},
    time,
};

use crate::cli::SharedCliService;

const MAX_INPUT: usize = 16 * 1024;
const MAX_OUTPUT: usize = 64 * 1024;
const ARGS: [&str; 6] = [
    "config",
    "login",
    "--provider",
    "claudeplatform",
    "--stdin",
    "--json",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginStatus {
    Starting,
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginError {
    Input,
    NotFound,
    Spawn,
    Io,
    InvalidResponse,
    Timeout,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginEvent {
    Started,
    Finished(LoginStatus),
    Failed(LoginError),
}

pub enum LoginRequest {
    Submit(String),
    Cancel,
    Shutdown,
}

pub struct LoginActor {
    sender: mpsc::Sender<LoginRequest>,
    task: std::sync::Arc<tokio::sync::Mutex<Option<tokio::task::JoinHandle<()>>>>,
}

impl Clone for LoginActor {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
            task: self.task.clone(),
        }
    }
}

pub struct LoginEvents(mpsc::UnboundedReceiver<LoginEvent>);

impl LoginEvents {
    pub fn try_recv(&mut self) -> Result<LoginEvent, mpsc::error::TryRecvError> {
        self.0.try_recv()
    }
}

impl LoginActor {
    pub fn start(
        runtime: &tokio::runtime::Handle,
        cli: std::sync::Arc<SharedCliService>,
    ) -> (Self, LoginEvents) {
        let (tx, mut rx) = mpsc::channel(4);
        let (event_tx, event_rx) = mpsc::unbounded_channel();
        let task = runtime.spawn(async move {
            while let Some(request) = rx.recv().await {
                let input = match request { LoginRequest::Submit(input) => input, LoginRequest::Cancel => continue, LoginRequest::Shutdown => break };
                let _ = event_tx.send(LoginEvent::Started);
                let (cancel_tx, cancel_rx) = watch::channel(false);
                let operation = run(cli.snapshot().executable().to_path_buf(), input, cancel_rx, Duration::from_secs(60));
                tokio::pin!(operation);
                let mut shutting_down = false;
                let outcome = loop {
                    tokio::select! {
                        result = &mut operation => break result,
                        request = rx.recv() => match request {
                            Some(LoginRequest::Cancel) => { let _ = cancel_tx.send(true); }
                            Some(LoginRequest::Shutdown) | None => { shutting_down = true; let _ = cancel_tx.send(true); }
                            Some(LoginRequest::Submit(_)) => { let _ = event_tx.send(LoginEvent::Failed(LoginError::Input)); }
                        }
                    }
                };
                let event = match outcome {
                    Ok(()) => LoginEvent::Finished(LoginStatus::Succeeded),
                    Err(LoginError::Cancelled) => LoginEvent::Finished(LoginStatus::Cancelled),
                    Err(error) => LoginEvent::Failed(error),
                };
                let _ = event_tx.send(event);
                if shutting_down { break; }
            }
        });
        (
            Self {
                sender: tx,
                task: std::sync::Arc::new(tokio::sync::Mutex::new(Some(task))),
            },
            LoginEvents(event_rx),
        )
    }

    pub fn try_send(
        &self,
        request: LoginRequest,
    ) -> Result<(), mpsc::error::TrySendError<LoginRequest>> {
        self.sender.try_send(request)
    }

    pub async fn shutdown(&self) {
        let _ = self.sender.send(LoginRequest::Shutdown).await;
        if let Some(task) = self.task.lock().await.take() {
            let _ = task.await;
        }
    }
}

async fn read_bounded<R: AsyncRead + Unpin>(mut reader: R, cap: usize) -> (Vec<u8>, bool) {
    let mut kept = Vec::with_capacity(cap.min(4096));
    let mut overflow = false;
    let mut buf = [0u8; 4096];
    loop {
        match reader.read(&mut buf).await {
            Ok(0) | Err(_) => break,
            Ok(n) => {
                let take = cap.saturating_sub(kept.len()).min(n);
                kept.extend_from_slice(&buf[..take]);
                overflow |= take < n;
            }
        }
    }
    (kept, overflow)
}

async fn send_stdin<W: AsyncWrite + Unpin>(mut stdin: W, input: &[u8]) -> std::io::Result<()> {
    stdin.write_all(input).await?;
    stdin.shutdown().await
}

async fn run(
    executable: PathBuf,
    input: String,
    mut cancel: watch::Receiver<bool>,
    timeout: Duration,
) -> Result<(), LoginError> {
    if input.is_empty() || input.len() > MAX_INPUT || input.chars().any(|c| c == '\n' || c == '\r')
    {
        return Err(LoginError::Input);
    }
    let mut command = Command::new(executable);
    // No user value is placed in argv.
    command
        .args(ARGS.map(OsString::from))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.as_std_mut().process_group(0);
    }
    let mut child = command.spawn().map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            LoginError::NotFound
        } else {
            LoginError::Spawn
        }
    })?;
    let group = child.id();
    let stdin = child.stdin.take().ok_or(LoginError::Io)?;
    let stdout = child.stdout.take().ok_or(LoginError::Io)?;
    let stderr = child.stderr.take().ok_or(LoginError::Io)?;
    let out_task = tokio::spawn(read_bounded(stdout, MAX_OUTPUT));
    let err_task = tokio::spawn(read_bounded(stderr, MAX_OUTPUT));
    let mut input_task = tokio::spawn(async move { send_stdin(stdin, input.as_bytes()).await });
    let deadline = time::sleep(timeout);
    tokio::pin!(deadline);
    enum End {
        Exited(std::io::Result<std::process::ExitStatus>),
        Cancelled,
        Timeout,
        InputError,
    }
    let cancel_wait = async {
        loop {
            if *cancel.borrow() {
                return;
            }
            if cancel.changed().await.is_err() {
                return;
            }
        }
    };
    tokio::pin!(cancel_wait);
    let mut input_write_ok = None;
    let end = tokio::select! {
        status = child.wait() => End::Exited(status),
        _ = &mut cancel_wait => End::Cancelled,
        _ = &mut deadline => End::Timeout,
        result = &mut input_task => {
            let succeeded = result.ok().and_then(Result::ok).is_some();
            input_write_ok = Some(succeeded);
            if succeeded { tokio::select! {
                status = child.wait() => End::Exited(status),
                _ = &mut cancel_wait => End::Cancelled,
                _ = &mut deadline => End::Timeout,
            }} else { End::InputError }
        },
    };
    match end {
        End::Exited(status) => {
            if input_write_ok.is_none() {
                input_write_ok = Some(input_task.await.ok().and_then(Result::ok).is_some());
            }
            if input_write_ok != Some(true) {
                kill_group(group);
                let _ = out_task.await;
                let _ = err_task.await;
                return Err(LoginError::Io);
            }
            let status = status.map_err(|_| LoginError::Io)?;
            // The CLI owns the one-shot request. Reap any descendants that may
            // have inherited the output pipes before joining the drainers.
            kill_group(group);
            let (stdout, stdout_overflow) = out_task.await.map_err(|_| LoginError::Io)?;
            let _ = err_task.await.map_err(|_| LoginError::Io)?;
            if !status.success() {
                return Err(LoginError::InvalidResponse);
            }
            if stdout_overflow {
                return Err(LoginError::InvalidResponse);
            }
            let response: Value =
                serde_json::from_slice(&stdout).map_err(|_| LoginError::InvalidResponse)?;
            if response.as_object().is_some_and(|o| {
                o.len() == 1 && o.get("status") == Some(&Value::String("authorized".into()))
            }) {
                Ok(())
            } else {
                Err(LoginError::InvalidResponse)
            }
        }
        End::Cancelled | End::Timeout | End::InputError => {
            kill_group(group);
            let _ = child.kill().await;
            let _ = child.wait().await;
            if input_write_ok.is_none() {
                input_task.abort();
                let _ = input_task.await;
            }
            let _ = out_task.await;
            let _ = err_task.await;
            match end {
                End::Cancelled => Err(LoginError::Cancelled),
                End::Timeout => Err(LoginError::Timeout),
                _ => Err(LoginError::Io),
            }
        }
    }
}

#[cfg(unix)]
fn kill_group(group: Option<u32>) {
    if let Some(group) = group {
        unsafe {
            libc::kill(-(group as i32), libc::SIGKILL);
        }
    }
}
#[cfg(not(unix))]
fn kill_group(_: Option<u32>) {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        sync::atomic::{AtomicUsize, Ordering},
    };

    static NEXT: AtomicUsize = AtomicUsize::new(0);

    struct Fixture(PathBuf);
    impl Fixture {
        fn script(body: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "codexbar-claudeplatform-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&dir).unwrap();
            let path = dir.join("fake-codexbar");
            let body = body.replace("@DIR@", &dir.display().to_string());
            fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
            let mut mode = fs::metadata(&path).unwrap().permissions();
            mode.set_mode(0o700);
            fs::set_permissions(&path, mode).unwrap();
            Self(dir)
        }
        fn executable(&self) -> PathBuf {
            self.0.join("fake-codexbar")
        }
        fn path(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn watch_cancel() -> (watch::Sender<bool>, watch::Receiver<bool>) {
        watch::channel(false)
    }

    #[tokio::test]
    async fn exact_argv_stdin_eof_and_sanitized_success() {
        let fixture = Fixture::script("printf '%s\\n' \"$@\" > '@DIR@/argv'; cat > '@DIR@/stdin'; printf '{\"status\":\"authorized\"}'");
        let (_tx, rx) = watch_cancel();
        let cookie = "sessionKey=synthetic-candidate";
        assert_eq!(
            run(
                fixture.executable(),
                cookie.to_owned(),
                rx,
                Duration::from_secs(3)
            )
            .await,
            Ok(())
        );
        assert_eq!(
            fs::read_to_string(fixture.path("argv"))
                .unwrap()
                .lines()
                .collect::<Vec<_>>(),
            [
                "config",
                "login",
                "--provider",
                "claudeplatform",
                "--stdin",
                "--json"
            ]
        );
        assert_eq!(fs::read_to_string(fixture.path("stdin")).unwrap(), cookie);
    }

    #[tokio::test]
    async fn nonzero_malformed_and_trailing_json_fail_closed() {
        for script in [
            "cat >/dev/null; printf '{\\\"status\\\":\\\"authorized\\\"}'; exit 9",
            "cat >/dev/null; printf 'not-json'",
            "cat >/dev/null; printf '{\\\"status\\\":\\\"authorized\\\"} extra'",
        ] {
            let fixture = Fixture::script(script);
            let (_tx, rx) = watch_cancel();
            assert_eq!(
                run(
                    fixture.executable(),
                    "sessionKey=synthetic".into(),
                    rx,
                    Duration::from_secs(3)
                )
                .await,
                Err(LoginError::InvalidResponse)
            );
        }
    }

    #[tokio::test]
    async fn rejects_multiline_and_oversized_input_before_spawn() {
        let (_tx, rx) = watch_cancel();
        assert_eq!(
            run(
                PathBuf::from("/definitely/missing"),
                "line1\nline2".into(),
                rx,
                Duration::from_secs(1)
            )
            .await,
            Err(LoginError::Input)
        );
        let (_tx, rx) = watch_cancel();
        assert_eq!(
            run(
                PathBuf::from("/definitely/missing"),
                "x".repeat(MAX_INPUT + 1),
                rx,
                Duration::from_secs(1)
            )
            .await,
            Err(LoginError::Input)
        );
    }

    #[tokio::test]
    async fn timeout_cancels_and_reaps_child_group() {
        let fixture = Fixture::script("sleep 30 & echo $! > '@DIR@/child'; wait");
        let (_tx, rx) = watch_cancel();
        assert_eq!(
            run(
                fixture.executable(),
                "synthetic".into(),
                rx,
                Duration::from_millis(100)
            )
            .await,
            Err(LoginError::Timeout)
        );
        let pid: i32 = fs::read_to_string(fixture.path("child"))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        for _ in 0..50 {
            let proc = fs::read_to_string(format!("/proc/{pid}/stat")).ok();
            if proc
                .as_deref()
                .is_none_or(|s| s.split_whitespace().nth(2) == Some("Z"))
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        let proc = fs::read_to_string(format!("/proc/{pid}/stat")).ok();
        assert!(proc
            .as_deref()
            .is_none_or(|s| s.split_whitespace().nth(2) == Some("Z")));
    }

    #[tokio::test]
    async fn explicit_cancel_kills_and_joins_the_process_group() {
        let fixture = Fixture::script("sleep 30 & echo $! > '@DIR@/child'; wait");
        let (cancel_tx, cancel_rx) = watch_cancel();
        let task = tokio::spawn(run(
            fixture.executable(),
            "synthetic".into(),
            cancel_rx,
            Duration::from_secs(10),
        ));
        tokio::time::timeout(Duration::from_secs(2), async {
            while !fixture.path("child").exists() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        cancel_tx.send(true).unwrap();
        assert_eq!(task.await.unwrap(), Err(LoginError::Cancelled));
    }

    #[tokio::test]
    async fn oversized_stdout_is_drained_bounded_and_rejected() {
        let fixture = Fixture::script("cat >/dev/null; head -c 65537 /dev/zero | tr '\\000' x");
        let (_tx, rx) = watch_cancel();
        assert_eq!(
            run(
                fixture.executable(),
                "synthetic".into(),
                rx,
                Duration::from_secs(3)
            )
            .await,
            Err(LoginError::InvalidResponse)
        );
    }

    #[tokio::test]
    async fn actor_shutdown_cancels_joins_and_emits_only_sanitized_status() {
        let fixture = Fixture::script("sleep 30 & echo $! > '@DIR@/child'; wait");
        let cli = std::sync::Arc::new(SharedCliService::new(std::sync::Arc::new(
            crate::cli::CliService::new(fixture.executable(), None),
        )));
        let (actor, mut events) = LoginActor::start(&tokio::runtime::Handle::current(), cli);
        actor
            .try_send(LoginRequest::Submit(
                "sessionKey=synthetic-candidate".to_owned(),
            ))
            .unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            while !fixture.path("child").exists() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        actor.shutdown().await;
        let collected: Vec<_> = std::iter::from_fn(|| events.try_recv().ok()).collect();
        assert!(collected.contains(&LoginEvent::Finished(LoginStatus::Cancelled)));
        assert!(!format!("{collected:?}").contains("synthetic-candidate"));
    }

    #[tokio::test]
    async fn stdin_write_failure_is_sanitized() {
        let (mut writer, reader) = tokio::io::duplex(16);
        drop(reader);
        assert!(send_stdin(&mut writer, b"synthetic-cookie").await.is_err());
    }
}
