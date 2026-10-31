//! Application-level process operations used by the transitional GTK facade.
//!
//! Process output is never captured or surfaced here. Callers receive only
//! typed outcomes and static error categories.

use std::{
    ffi::OsString,
    io,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

use crate::login;

pub const APPLICATION_UNIT: &str = "codexbar-gtk";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RestartMode {
    SystemdRestartRequested,
    ProcessRelaunchStarted,
}

impl RestartMode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SystemdRestartRequested => "systemd_restart_requested",
            Self::ProcessRelaunchStarted => "process_relaunch_started",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RestartResult {
    pub mode: RestartMode,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RestartError {
    pub category: &'static str,
    pub operation: &'static str,
}

impl RestartError {
    const fn process() -> Self {
        Self {
            category: "process",
            operation: "application_restart",
        }
    }
}

/// Current process launch context without argv[0]. `current_exe` is important
/// for wrapper scripts that `exec python3 -m codexbar_gtk`: the shell is gone,
/// and the OS argv tail still identifies the Python module invocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RestartInvocation {
    pub executable: PathBuf,
    pub args: Vec<OsString>,
}

impl RestartInvocation {
    pub fn current() -> Result<Self, RestartError> {
        let executable = std::env::current_exe().map_err(|_| RestartError::process())?;
        let args = std::env::args_os().skip(1).collect();
        Ok(Self { executable, args })
    }

    pub fn from_process_argv(
        executable: PathBuf,
        argv: impl IntoIterator<Item = OsString>,
    ) -> Self {
        Self {
            executable,
            args: argv.into_iter().skip(1).collect(),
        }
    }
}

/// Injectable process seam. Tests use a recorder instead of starting a real
/// systemd command, terminal, or application copy.
pub trait ApplicationLauncher {
    fn spawn_systemd_restart(&mut self, unit: &str) -> io::Result<()>;
    fn spawn_detached(&mut self, executable: &Path, args: &[OsString]) -> io::Result<()>;
}

#[derive(Default)]
pub struct SystemApplicationLauncher;

impl ApplicationLauncher for SystemApplicationLauncher {
    fn spawn_systemd_restart(&mut self, unit: &str) -> io::Result<()> {
        let mut command = Command::new("systemctl");
        command
            .args(["--user", "restart", unit])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        detach(&mut command);
        command.spawn().map(drop)
    }

    fn spawn_detached(&mut self, executable: &Path, args: &[OsString]) -> io::Result<()> {
        let mut command = Command::new(executable);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        detach(&mut command);
        command.spawn().map(drop)
    }
}

fn detach(command: &mut Command) {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // `setsid` is async-signal-safe and mirrors `start_new_session=True`
        // in the prior Python restart and terminal launch paths.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }
    #[cfg(not(unix))]
    let _ = command;
}

pub fn restart_application_with(
    invocation_id_present: bool,
    invocation: &RestartInvocation,
    launcher: &mut impl ApplicationLauncher,
) -> Result<RestartResult, RestartError> {
    if invocation_id_present && launcher.spawn_systemd_restart(APPLICATION_UNIT).is_ok() {
        return Ok(RestartResult {
            mode: RestartMode::SystemdRestartRequested,
        });
    }

    launcher
        .spawn_detached(&invocation.executable, &invocation.args)
        .map_err(|_| RestartError::process())?;
    Ok(RestartResult {
        mode: RestartMode::ProcessRelaunchStarted,
    })
}

pub fn restart_application() -> Result<RestartResult, RestartError> {
    let invocation = RestartInvocation::current()?;
    let invocation_id_present =
        std::env::var_os("INVOCATION_ID").is_some_and(|value| !value.is_empty());
    restart_application_with(
        invocation_id_present,
        &invocation,
        &mut SystemApplicationLauncher,
    )
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LoginOperationErrorKind {
    CliNotFound,
    Process,
}

impl LoginOperationErrorKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CliNotFound => "cli_not_found",
            Self::Process => "process",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LoginOperationError {
    pub kind: LoginOperationErrorKind,
    pub operation: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TerminalLoginResult {
    pub launched: bool,
}

pub fn launch_codex_login_terminal_with(
    codex_executable: Option<PathBuf>,
    terminal_executable: Option<PathBuf>,
    launcher: &mut impl ApplicationLauncher,
) -> Result<TerminalLoginResult, LoginOperationError> {
    let operation = "login_codex_terminal";
    let codex_executable = codex_executable.ok_or(LoginOperationError {
        kind: LoginOperationErrorKind::CliNotFound,
        operation,
    })?;
    let Some(terminal_executable) = terminal_executable else {
        return Ok(TerminalLoginResult { launched: false });
    };

    let command = [codex_executable.into_os_string(), OsString::from("login")];
    let terminal = terminal_executable.to_string_lossy();
    let mut argv = login::terminal_command_argv(&terminal, &command);
    let program = PathBuf::from(argv.remove(0));
    launcher
        .spawn_detached(&program, &argv)
        .map_err(|_| LoginOperationError {
            kind: LoginOperationErrorKind::Process,
            operation,
        })?;
    Ok(TerminalLoginResult { launched: true })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    #[derive(Default)]
    struct RecordingLauncher {
        systemd: Vec<String>,
        processes: Vec<(PathBuf, Vec<OsString>)>,
        systemd_result: Option<io::ErrorKind>,
        process_results: VecDeque<io::ErrorKind>,
    }

    impl ApplicationLauncher for RecordingLauncher {
        fn spawn_systemd_restart(&mut self, unit: &str) -> io::Result<()> {
            self.systemd.push(unit.to_owned());
            match self.systemd_result.take() {
                Some(kind) => Err(io::Error::from(kind)),
                None => Ok(()),
            }
        }

        fn spawn_detached(&mut self, executable: &Path, args: &[OsString]) -> io::Result<()> {
            self.processes
                .push((executable.to_path_buf(), args.to_vec()));
            match self.process_results.pop_front() {
                Some(kind) => Err(io::Error::from(kind)),
                None => Ok(()),
            }
        }
    }

    #[test]
    fn wrapper_argv_relaunch_matches_development_and_installed_python_shapes() {
        for (argv, expected_args) in [
            (
                vec!["python3", "-m", "codexbar_gtk", "--settings"],
                vec!["-m", "codexbar_gtk", "--settings"],
            ),
            (
                vec!["python3", "-m", "codexbar_gtk", "--about"],
                vec!["-m", "codexbar_gtk", "--about"],
            ),
        ] {
            let invocation = RestartInvocation::from_process_argv(
                PathBuf::from("/usr/bin/python3.12"),
                argv.iter().map(OsString::from),
            );
            assert_eq!(invocation.executable, PathBuf::from("/usr/bin/python3.12"));
            assert_eq!(
                invocation.args,
                expected_args.iter().map(OsString::from).collect::<Vec<_>>()
            );
        }
    }

    #[test]
    fn systemd_restart_uses_unit_and_returns_without_duplicate_relaunch() {
        let invocation = RestartInvocation {
            executable: PathBuf::from("/fixture/python"),
            args: vec!["-m".into(), "codexbar_gtk".into()],
        };
        let mut launcher = RecordingLauncher::default();
        let result = restart_application_with(true, &invocation, &mut launcher).unwrap();
        assert_eq!(result.mode, RestartMode::SystemdRestartRequested);
        assert_eq!(launcher.systemd, [APPLICATION_UNIT]);
        assert!(launcher.processes.is_empty());
    }

    #[test]
    fn failed_systemd_spawn_falls_back_to_current_executable_and_argv() {
        let invocation = RestartInvocation {
            executable: PathBuf::from("/fixture/python"),
            args: vec!["-m".into(), "codexbar_gtk".into(), "--settings".into()],
        };
        let mut launcher = RecordingLauncher {
            systemd_result: Some(io::ErrorKind::NotFound),
            ..Default::default()
        };
        let result = restart_application_with(true, &invocation, &mut launcher).unwrap();
        assert_eq!(result.mode, RestartMode::ProcessRelaunchStarted);
        assert_eq!(
            launcher.processes,
            [(invocation.executable, invocation.args)]
        );
    }

    #[test]
    fn development_restart_relaunches_and_failure_is_sanitized() {
        let invocation = RestartInvocation {
            executable: PathBuf::from("/private/path/python"),
            args: vec!["-m".into(), "codexbar_gtk".into()],
        };
        let mut launcher = RecordingLauncher {
            process_results: [io::ErrorKind::PermissionDenied].into(),
            ..Default::default()
        };
        let error = restart_application_with(false, &invocation, &mut launcher).unwrap_err();
        assert_eq!(error.category, "process");
        assert_eq!(error.operation, "application_restart");
        assert!(!format!("{error:?}").contains("private"));
    }

    #[test]
    fn systemd_and_fallback_spawn_failure_is_a_static_restart_error() {
        let invocation = RestartInvocation {
            executable: PathBuf::from("/private/python"),
            args: vec!["-m".into(), "codexbar_gtk".into()],
        };
        let mut launcher = RecordingLauncher {
            systemd_result: Some(io::ErrorKind::NotFound),
            process_results: [io::ErrorKind::PermissionDenied].into(),
            ..Default::default()
        };
        let error = restart_application_with(true, &invocation, &mut launcher).unwrap_err();
        assert_eq!(error.category, "process");
        assert_eq!(error.operation, "application_restart");
        assert!(!format!("{error:?}").contains("private"));
        assert_eq!(launcher.systemd, [APPLICATION_UNIT]);
        assert_eq!(launcher.processes.len(), 1);
    }

    #[test]
    fn codex_terminal_login_uses_discovered_executable_and_terminal_argv() {
        let mut launcher = RecordingLauncher::default();
        let result = launch_codex_login_terminal_with(
            Some(PathBuf::from("/fixture/codex")),
            Some(PathBuf::from("/usr/bin/gnome-terminal")),
            &mut launcher,
        )
        .unwrap();
        assert!(result.launched);
        assert_eq!(
            launcher.processes,
            [(
                PathBuf::from("/usr/bin/gnome-terminal"),
                vec![
                    OsString::from("--"),
                    OsString::from("/fixture/codex"),
                    OsString::from("login")
                ]
            )]
        );
    }

    #[test]
    fn codex_terminal_login_missing_cli_is_static_and_sanitized() {
        let mut launcher = RecordingLauncher::default();
        let error = launch_codex_login_terminal_with(None, None, &mut launcher).unwrap_err();
        assert_eq!(error.kind, LoginOperationErrorKind::CliNotFound);
        assert_eq!(error.operation, "login_codex_terminal");
        assert!(!format!("{error:?}").contains("private"));

        let outcome = launch_codex_login_terminal_with(
            Some(PathBuf::from("/fixture/codex")),
            None,
            &mut launcher,
        )
        .unwrap();
        assert!(!outcome.launched);
    }

    #[test]
    fn codex_terminal_spawn_failure_has_no_path_or_process_output() {
        let mut launcher = RecordingLauncher {
            process_results: [io::ErrorKind::PermissionDenied].into(),
            ..Default::default()
        };
        let error = launch_codex_login_terminal_with(
            Some(PathBuf::from("/private/codex")),
            Some(PathBuf::from("/private/konsole")),
            &mut launcher,
        )
        .unwrap_err();
        assert_eq!(error.kind, LoginOperationErrorKind::Process);
        assert_eq!(error.operation, "login_codex_terminal");
        assert!(!format!("{error:?}").contains("private"));
    }
}
