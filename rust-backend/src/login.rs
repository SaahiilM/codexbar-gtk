//! Interactive provider authentication over a pseudo terminal.
//!
//! Login output and authorization URLs are ephemeral events. They are never
//! included in the lifecycle snapshot or in the sanitized errors below.

use std::{
    collections::VecDeque,
    ffi::OsString,
    io::{Read, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc as std_mpsc, Arc, Condvar, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use crate::{cli::CliService, Cancellation};
use portable_pty::{native_pty_system, Child, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde_json::{Map, Value};
use tokio::sync::{mpsc, watch};

const EVENT_CAPACITY: usize = 32;
const MAX_AUTH_INPUT_BYTES: usize = 16 * 1024;
const PTY_ROWS: u16 = 24;
const PTY_COLUMNS: u16 = 100;
const READ_CHUNK: usize = 4096;

pub const CLAUDE_LOGIN_ARGS: [&str; 3] = ["auth", "login", "--claudeai"];
const SUCCESS_MARKERS: [&str; 3] = [
    "Successfully logged in",
    "Login successful",
    "Logged in successfully",
];
const CODE_PROMPT: &str = "Paste code here";
const BROWSER_PROMPT: &str = "press ENTER to open in browser";

/// Safe lifecycle state published with latest-value semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginStatus {
    Starting,
    WaitingForAuthorization,
    WaitingForCode,
    Finishing,
    Succeeded,
    Failed,
    TimedOut,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LoginSnapshot {
    pub status: LoginStatus,
    pub needs_code: bool,
}

/// Ephemeral login output. Do not log, persist, or put these values in a
/// `LoginSnapshot`, backend error, or tracing span.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LoginEvent {
    AuthorizationUrl(String),
    Prompt(LoginPrompt),
    Output(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginPrompt {
    OpenBrowser,
    PasteCode,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginErrorKind {
    PtyUnavailable,
    Spawn,
    Io,
    Input,
    Child,
}

/// Safe error type. It intentionally has no source string or process output.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LoginError {
    pub kind: LoginErrorKind,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginCompletionKind {
    Succeeded,
    Failed,
    TimedOut,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LoginCompletion {
    pub kind: LoginCompletionKind,
    pub exit_code: Option<u32>,
}

/// A running PTY login. The event stream is bounded and separate from the
/// coalescing lifecycle watch. The caller must consume events while the login
/// is running; ordinary output events may be dropped if the stream is full,
/// while URL and prompt events are retained in a small bounded pending queue.
pub struct LoginSession {
    state: watch::Receiver<LoginSnapshot>,
    events: Option<mpsc::Receiver<LoginEvent>>,
    input: Arc<(Mutex<VecDeque<String>>, Condvar)>,
    cancelled: Arc<AtomicBool>,
    task: Option<tokio::task::JoinHandle<Result<LoginCompletion, LoginError>>>,
}

impl LoginSession {
    /// Start an interactive process in a native PTY. The executable is
    /// expected to come from `codexbar_backend::cli::discover_executable`;
    /// the PTY path does not use B07's non-PTY subprocess runner.
    pub async fn start(
        executable: PathBuf,
        args: Vec<OsString>,
        timeout: Duration,
    ) -> Result<Self, LoginError> {
        let system = native_pty_system();
        let pair = system
            .openpty(PtySize {
                rows: PTY_ROWS,
                cols: PTY_COLUMNS,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|_| LoginError {
                kind: LoginErrorKind::PtyUnavailable,
            })?;

        let master = pair.master;
        let reader = master.try_clone_reader().map_err(|_| LoginError {
            kind: LoginErrorKind::Io,
        })?;
        let writer = master.take_writer().map_err(|_| LoginError {
            kind: LoginErrorKind::Io,
        })?;

        let mut command = CommandBuilder::new(executable);
        command.args(args);
        let mut child = pair.slave.spawn_command(command).map_err(|_| LoginError {
            kind: LoginErrorKind::Spawn,
        })?;
        drop(pair.slave);
        #[cfg(unix)]
        let process_group = master.process_group_leader();
        #[cfg(not(unix))]
        let process_group = None;
        let killer = child.clone_killer();
        let (state_tx, state_rx) = watch::channel(LoginSnapshot {
            status: LoginStatus::Starting,
            needs_code: false,
        });
        let (event_tx, event_rx) = mpsc::channel(EVENT_CAPACITY);
        let input = Arc::new((Mutex::new(VecDeque::new()), Condvar::new()));
        let cancelled = Arc::new(AtomicBool::new(false));

        let worker_input = Arc::clone(&input);
        let worker_cancelled = Arc::clone(&cancelled);
        let task = tokio::task::spawn_blocking(move || {
            monitor_login(MonitorArgs {
                child: child.as_mut(),
                killer,
                process_group,
                master,
                reader,
                writer,
                timeout,
                input: worker_input,
                cancelled: worker_cancelled,
                state: state_tx,
                events: event_tx,
            })
        });

        Ok(Self {
            state: state_rx,
            events: Some(event_rx),
            input,
            cancelled,
            task: Some(tokio::spawn(async move {
                task.await.map_err(|_| LoginError {
                    kind: LoginErrorKind::Child,
                })?
            })),
        })
    }

    pub async fn start_claude(executable: PathBuf, timeout: Duration) -> Result<Self, LoginError> {
        Self::start(
            executable,
            CLAUDE_LOGIN_ARGS.iter().map(OsString::from).collect(),
            timeout,
        )
        .await
    }

    pub fn state(&self) -> watch::Receiver<LoginSnapshot> {
        self.state.clone()
    }

    pub fn take_events(&mut self) -> Option<mpsc::Receiver<LoginEvent>> {
        self.events.take()
    }

    /// Submit the provider's browser authorization code through the PTY.
    pub async fn submit(&self, code: String) -> Result<(), LoginError> {
        if code.len() > MAX_AUTH_INPUT_BYTES {
            return Err(LoginError {
                kind: LoginErrorKind::Input,
            });
        }
        let (queue, ready) = &*self.input;
        let mut queue = queue.lock().map_err(|_| LoginError {
            kind: LoginErrorKind::Child,
        })?;
        if !queue.is_empty() {
            return Err(LoginError {
                kind: LoginErrorKind::Input,
            });
        }
        queue.push_back(code);
        drop(queue);
        ready.notify_one();
        Ok(())
    }

    pub async fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
        self.input.1.notify_all();
    }

    /// Wait for the child to be reaped and receive its explicit completion.
    pub async fn wait(mut self) -> Result<LoginCompletion, LoginError> {
        self.task
            .take()
            .expect("login task was already joined")
            .await
            .map_err(|_| LoginError {
                kind: LoginErrorKind::Child,
            })?
    }
}

impl Drop for LoginSession {
    fn drop(&mut self) {
        // Dropping the frontend handle must still request cooperative process
        // cleanup; the worker owns the child until it has killed and reaped it.
        self.cancelled.store(true, Ordering::Release);
        self.input.1.notify_all();
    }
}

struct MonitorArgs<'a> {
    child: &'a mut (dyn Child + Send + Sync),
    killer: Box<dyn ChildKiller + Send + Sync>,
    process_group: Option<i32>,
    master: Box<dyn MasterPty + Send>,
    reader: Box<dyn Read + Send>,
    writer: Box<dyn Write + Send>,
    timeout: Duration,
    input: Arc<(Mutex<VecDeque<String>>, Condvar)>,
    cancelled: Arc<AtomicBool>,
    state: watch::Sender<LoginSnapshot>,
    events: mpsc::Sender<LoginEvent>,
}

fn monitor_login(args: MonitorArgs<'_>) -> Result<LoginCompletion, LoginError> {
    let MonitorArgs {
        child,
        killer,
        process_group,
        master: _master,
        mut reader,
        mut writer,
        timeout,
        input,
        cancelled,
        state,
        events,
    } = args;
    let mut process = ChildGuard {
        child,
        killer,
        process_group,
        reaped: false,
    };
    let (output_tx, output_rx) = std_mpsc::sync_channel::<Vec<u8>>(8);
    let reader_thread = thread::Builder::new()
        .name("codexbar-login-pty-reader".into())
        .spawn(move || {
            let mut buffer = [0u8; READ_CHUNK];
            loop {
                match reader.read(&mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(size) => {
                        if output_tx.send(buffer[..size].to_vec()).is_err() {
                            break;
                        }
                    }
                }
            }
        })
        .map_err(|_| LoginError {
            kind: LoginErrorKind::Child,
        })?;

    let start = Instant::now();
    let mut parser = LoginOutputParser::default();
    let mut pending = VecDeque::new();
    let mut exit_status = None;
    let mut end_kind = None;
    let mut output_closed = false;

    loop {
        flush_events(&events, &mut pending);
        if cancelled.load(Ordering::Acquire) {
            end_kind = Some(LoginCompletionKind::Cancelled);
            break;
        }
        if start.elapsed() >= timeout {
            end_kind = Some(LoginCompletionKind::TimedOut);
            break;
        }

        let mut inputs = input.0.lock().map_err(|_| LoginError {
            kind: LoginErrorKind::Child,
        })?;
        while let Some(text) = inputs.pop_front() {
            writer
                .write_all(text.as_bytes())
                .and_then(|_| writer.write_all(b"\n"))
                .map_err(|_| LoginError {
                    kind: LoginErrorKind::Io,
                })?;
            state.send_replace(LoginSnapshot {
                status: LoginStatus::Finishing,
                needs_code: true,
            });
        }
        drop(inputs);

        match output_rx.recv_timeout(Duration::from_millis(50)) {
            Ok(bytes) => {
                let text = String::from_utf8_lossy(&bytes);
                for event in parser.feed(&text) {
                    match &event {
                        LoginEvent::Prompt(LoginPrompt::PasteCode) => {
                            state.send_replace(LoginSnapshot {
                                status: LoginStatus::WaitingForCode,
                                needs_code: true,
                            });
                        }
                        LoginEvent::Prompt(LoginPrompt::OpenBrowser)
                        | LoginEvent::AuthorizationUrl(_) => {
                            state.send_replace(LoginSnapshot {
                                status: LoginStatus::WaitingForAuthorization,
                                needs_code: false,
                            });
                        }
                        LoginEvent::Output(_) => {}
                    }
                    if matches!(event, LoginEvent::Output(_)) {
                        if pending.len() < EVENT_CAPACITY {
                            pending.push_back(event);
                        }
                    } else {
                        pending.push_back(event);
                    }
                }
            }
            Err(std_mpsc::RecvTimeoutError::Disconnected) => output_closed = true,
            Err(std_mpsc::RecvTimeoutError::Timeout) => {}
        }

        if let Some(status) = process.try_wait().map_err(|_| LoginError {
            kind: LoginErrorKind::Child,
        })? {
            exit_status = Some(status);
            if output_closed {
                break;
            }
        }
        if exit_status.is_some() && output_closed {
            break;
        }
    }

    if end_kind.is_some() {
        let _ = process.terminate();
    }
    let status = process.wait().map_err(|_| LoginError {
        kind: LoginErrorKind::Child,
    })?;
    exit_status.get_or_insert(status);
    drop(writer);
    while output_rx.recv_timeout(Duration::from_millis(20)).is_ok() {}
    let _ = reader_thread.join();
    flush_events(&events, &mut pending);

    let completion_kind = end_kind.unwrap_or({
        if parser.succeeded || exit_status.as_ref().is_some_and(|status| status.success()) {
            LoginCompletionKind::Succeeded
        } else {
            LoginCompletionKind::Failed
        }
    });
    state.send_replace(LoginSnapshot {
        status: match completion_kind {
            LoginCompletionKind::Succeeded => LoginStatus::Succeeded,
            LoginCompletionKind::Failed => LoginStatus::Failed,
            LoginCompletionKind::TimedOut => LoginStatus::TimedOut,
            LoginCompletionKind::Cancelled => LoginStatus::Cancelled,
        },
        needs_code: parser.needs_code,
    });
    Ok(LoginCompletion {
        kind: completion_kind,
        exit_code: exit_status.map(|s| s.exit_code()),
    })
}

struct ChildGuard<'a> {
    child: &'a mut (dyn Child + Send + Sync),
    killer: Box<dyn ChildKiller + Send + Sync>,
    process_group: Option<i32>,
    reaped: bool,
}

impl ChildGuard<'_> {
    fn try_wait(&mut self) -> std::io::Result<Option<portable_pty::ExitStatus>> {
        self.child.try_wait()
    }

    fn wait(&mut self) -> std::io::Result<portable_pty::ExitStatus> {
        let result = self.child.wait();
        self.reaped = result.is_ok();
        result
    }

    fn terminate(&mut self) -> std::io::Result<()> {
        if let Some(process_group) = self.process_group {
            // portable-pty starts the interactive child in a new session.
            // Kill its whole process group so descendants cannot retain the
            // PTY and outlive timeout/cancellation.
            let result = unsafe { libc::kill(-process_group, libc::SIGKILL) };
            if result == 0 {
                return Ok(());
            }
        }
        self.killer.kill()
    }
}

impl Drop for ChildGuard<'_> {
    fn drop(&mut self) {
        if !self.reaped {
            let _ = self.terminate();
            let _ = self.child.wait();
            self.reaped = true;
        }
    }
}

fn flush_events(sender: &mpsc::Sender<LoginEvent>, pending: &mut VecDeque<LoginEvent>) {
    while let Some(event) = pending.pop_front() {
        match sender.try_send(event) {
            Ok(()) => {}
            Err(mpsc::error::TrySendError::Full(event)) => {
                pending.push_front(event);
                break;
            }
            Err(mpsc::error::TrySendError::Closed(_)) => {
                pending.clear();
                break;
            }
        }
    }
}

#[derive(Default)]
struct LoginOutputParser {
    carry: String,
    ansi: AnsiState,
    url_seen: bool,
    prompt_seen: bool,
    needs_code: bool,
    succeeded: bool,
}

#[derive(Default)]
enum AnsiState {
    #[default]
    Text,
    Escape,
    Csi,
}

impl LoginOutputParser {
    fn feed(&mut self, input: &str) -> Vec<LoginEvent> {
        let clean = strip_ansi_incremental(input, &mut self.ansi);
        if clean.is_empty() {
            return Vec::new();
        }
        self.carry.push_str(&clean);
        let mut events = Vec::new();

        if !self.url_seen {
            if let Some(url) = find_url(&self.carry) {
                self.url_seen = true;
                events.push(LoginEvent::AuthorizationUrl(url));
            }
        }
        if !self.prompt_seen && self.carry.contains(BROWSER_PROMPT) {
            self.prompt_seen = true;
            events.push(LoginEvent::Prompt(LoginPrompt::OpenBrowser));
        }
        if !self.needs_code && self.carry.contains(CODE_PROMPT) {
            self.needs_code = true;
            events.push(LoginEvent::Prompt(LoginPrompt::PasteCode));
        }
        if !self.succeeded
            && SUCCESS_MARKERS
                .iter()
                .any(|marker| self.carry.contains(marker))
        {
            self.succeeded = true;
        }
        if clean.chars().any(|ch| !ch.is_control()) {
            events.push(LoginEvent::Output(clean));
        }
        if self.carry.len() > 16 * 1024 {
            let keep_from = self.carry.len().saturating_sub(4096);
            let boundary = self
                .carry
                .char_indices()
                .find(|(i, _)| *i >= keep_from)
                .map(|(i, _)| i)
                .unwrap_or(0);
            self.carry.drain(..boundary);
        }
        events
    }
}

fn strip_ansi_incremental(input: &str, state: &mut AnsiState) -> String {
    let mut output = String::with_capacity(input.len());
    for ch in input.chars() {
        match state {
            AnsiState::Text if ch == '\u{1b}' => *state = AnsiState::Escape,
            AnsiState::Text => output.push(ch),
            AnsiState::Escape if ch == '[' => *state = AnsiState::Csi,
            AnsiState::Escape => *state = AnsiState::Text,
            AnsiState::Csi if ('@'..='~').contains(&ch) => *state = AnsiState::Text,
            AnsiState::Csi => {}
        }
    }
    output
}

fn find_url(text: &str) -> Option<String> {
    let start = text.find("https://").or_else(|| text.find("http://"))?;
    let tail = &text[start..];
    let end =
        tail.find(|ch: char| ch.is_whitespace() || ['"', '\'', '<', '>', ')', ']'].contains(&ch))?;
    let candidate = &tail[..end];
    let url = candidate.trim_end_matches([',', '.']);
    (url.len() <= 16 * 1024).then(|| url.to_owned())
}

/// Build a terminal argv without shell parsing, matching the existing GTK
/// terminal launch convention.
pub fn terminal_command_argv(terminal: &str, command: &[OsString]) -> Vec<OsString> {
    let terminal_name = std::path::Path::new(terminal)
        .file_name()
        .unwrap_or_default()
        .to_string_lossy();
    let separator = if terminal_name == "gnome-terminal" {
        "--"
    } else {
        "-e"
    };
    std::iter::once(OsString::from(terminal))
        .chain(std::iter::once(OsString::from(separator)))
        .chain(command.iter().cloned())
        .collect()
}

/// Candidate browser launchers used by the compatibility UI.
pub const BROWSER_LAUNCHERS: [&str; 3] = ["xdg-open", "gio", "sensible-browser"];

/// Build browser opener argv without shell parsing. `gio` requires the `open`
/// subcommand; other launchers take the URL directly.
pub fn browser_command_argv(opener: &str, url: &std::ffi::OsStr) -> Vec<OsString> {
    let mut argv = vec![OsString::from(opener)];
    if std::path::Path::new(opener)
        .file_name()
        .is_some_and(|name| name == "gio")
    {
        argv.push(OsString::from("open"));
    }
    argv.push(url.to_owned());
    argv
}

/// Arguments for the bounded, non-PTY `claude auth status` call. The caller
/// should resolve `claude` through B07 and execute these via its JSON helper.
pub fn claude_auth_status_args() -> Vec<OsString> {
    ["auth", "status"].into_iter().map(OsString::from).collect()
}

/// Read Claude authentication status through B07's bounded non-PTY runner.
/// Match the Python compatibility behavior: missing executable, nonzero exit,
/// timeout, cancellation, invalid JSON, and non-object JSON all yield `{}`.
pub async fn claude_auth_status(
    cli: &CliService,
    timeout: Duration,
    cancellation: Option<Cancellation>,
) -> Value {
    match cli
        .run(&claude_auth_status_args(), timeout, cancellation)
        .await
    {
        Ok(result) if result.returncode == 0 => match serde_json::from_str(&result.stdout) {
            Ok(Value::Object(object)) => Value::Object(object),
            _ => Value::Object(Map::new()),
        },
        _ => Value::Object(Map::new()),
    }
}

/// Trim trailing punctuation from URLs surfaced by the login prompt.
pub fn clean_authorization_url(url: &str) -> String {
    url.trim_end_matches([',', '.']).to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::timeout as async_timeout;

    #[test]
    fn ansi_and_markers_are_parsed_across_chunks() {
        let mut parser = LoginOutputParser::default();
        let first = parser.feed("\u{1b}[31mhttps://example.test/auth");
        assert!(!first
            .iter()
            .any(|event| matches!(event, LoginEvent::AuthorizationUrl(_))));
        let events = parser.feed("orize\u{1b}[0m Paste code here");
        assert!(events.iter().any(|e| matches!(e, LoginEvent::AuthorizationUrl(url) if url == "https://example.test/authorize")));
        assert!(events.contains(&LoginEvent::Prompt(LoginPrompt::PasteCode)));
        assert!(parser.needs_code);
    }

    #[test]
    fn login_success_marker_is_incremental() {
        let mut parser = LoginOutputParser::default();
        parser.feed("Successfully logged ");
        parser.feed("in");
        assert!(parser.succeeded);
    }

    #[test]
    fn terminal_argv_preserves_arguments_and_gnome_separator() {
        let command = vec![
            OsString::from("claude"),
            OsString::from("auth login; echo nope"),
        ];
        assert_eq!(
            terminal_command_argv("/usr/bin/gnome-terminal", &command),
            vec![
                "/usr/bin/gnome-terminal",
                "--",
                "claude",
                "auth login; echo nope"
            ]
            .into_iter()
            .map(OsString::from)
            .collect::<Vec<_>>()
        );
        assert_eq!(
            terminal_command_argv("konsole", &command)[1],
            OsString::from("-e")
        );
        assert_eq!(
            browser_command_argv(
                "/usr/bin/gio",
                std::ffi::OsStr::new("https://synthetic.test/a?b=c")
            ),
            vec!["/usr/bin/gio", "open", "https://synthetic.test/a?b=c"]
                .into_iter()
                .map(OsString::from)
                .collect::<Vec<_>>()
        );
        assert_eq!(
            claude_auth_status_args(),
            vec![OsString::from("auth"), OsString::from("status")]
        );
    }

    #[test]
    fn safe_snapshot_and_errors_have_no_output_fields() {
        let snapshot = LoginSnapshot {
            status: LoginStatus::WaitingForCode,
            needs_code: true,
        };
        let error = LoginError {
            kind: LoginErrorKind::Spawn,
        };
        assert_eq!(snapshot.status, LoginStatus::WaitingForCode);
        assert_eq!(error.kind, LoginErrorKind::Spawn);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_login_streams_prompt_and_reaps_successful_child() {
        let script = "printf 'https://example.test/authorize Paste code here'; read code; printf 'Successfully logged in'";
        let mut session = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from(script)],
            Duration::from_secs(3),
        )
        .await
        .expect("start fake login process");
        let mut events = session.take_events().expect("event stream is available");
        let lifecycle = session.state();
        let mut saw_url = false;
        let mut saw_prompt = false;
        async_timeout(Duration::from_secs(2), async {
            while let Some(event) = events.recv().await {
                match event {
                    LoginEvent::AuthorizationUrl(url) => {
                        saw_url = url == "https://example.test/authorize";
                    }
                    LoginEvent::Prompt(LoginPrompt::PasteCode) => {
                        saw_prompt = true;
                        session.submit("fixture-code".to_owned()).await.unwrap();
                    }
                    LoginEvent::Output(_) | LoginEvent::Prompt(LoginPrompt::OpenBrowser) => {}
                }
                if saw_url && saw_prompt {
                    break;
                }
            }
        })
        .await
        .expect("fake process should publish prompt events");
        let completion = async_timeout(Duration::from_secs(2), session.wait())
            .await
            .expect("child should be reaped")
            .expect("worker should complete");
        assert!(saw_url);
        assert!(saw_prompt);
        assert!(!format!("{:?}", *lifecycle.borrow()).contains("example.test"));
        assert_eq!(completion.kind, LoginCompletionKind::Succeeded);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_cancel_kills_and_reaps_waiting_child() {
        let session = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from("read code")],
            Duration::from_secs(3),
        )
        .await
        .expect("start fake login process");
        session.cancel().await;
        let completion = async_timeout(Duration::from_secs(2), session.wait())
            .await
            .expect("cancel should terminate and reap the child")
            .expect("worker should complete");
        assert_eq!(completion.kind, LoginCompletionKind::Cancelled);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_timeout_kills_and_reaps_waiting_child() {
        let session = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from("read code")],
            Duration::from_millis(100),
        )
        .await
        .expect("start fake login process");
        let completion = async_timeout(Duration::from_secs(2), session.wait())
            .await
            .expect("timeout should terminate and reap child")
            .expect("worker should complete");
        assert_eq!(completion.kind, LoginCompletionKind::TimedOut);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_timeout_kills_process_group_descendants() {
        let session = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from("sleep 10 & wait")],
            Duration::from_millis(100),
        )
        .await
        .expect("start fake process group");
        let completion = async_timeout(Duration::from_secs(2), session.wait())
            .await
            .expect("timeout must terminate descendants retaining the PTY")
            .expect("worker should complete");
        assert_eq!(completion.kind, LoginCompletionKind::TimedOut);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_cancel_kills_process_group_descendants() {
        let session = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from("sleep 10 & wait")],
            Duration::from_secs(3),
        )
        .await
        .expect("start fake process group");
        session.cancel().await;
        let completion = async_timeout(Duration::from_secs(2), session.wait())
            .await
            .expect("cancel must terminate descendants retaining the PTY")
            .expect("worker should complete");
        assert_eq!(completion.kind, LoginCompletionKind::Cancelled);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fake_pty_exit_code_matches_login_success_semantics() {
        let success = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from(":")],
            Duration::from_secs(2),
        )
        .await
        .expect("start fake successful process");
        assert_eq!(
            success.wait().await.unwrap().kind,
            LoginCompletionKind::Succeeded
        );

        let failure = LoginSession::start(
            PathBuf::from("/bin/sh"),
            vec![OsString::from("-c"), OsString::from("exit 7")],
            Duration::from_secs(2),
        )
        .await
        .expect("start fake failed process");
        let result = failure.wait().await.unwrap();
        assert_eq!(result.kind, LoginCompletionKind::Failed);
        assert_eq!(result.exit_code, Some(7));
    }
}
