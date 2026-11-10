//! Best-effort refresh of the GTK hicolor icon cache after the UI writes SVGs.
//!
//! The GTK layer owns SVG rendering and writes. This service owns optional
//! cache-tool discovery and process execution so the Rust-opt-in UI does not
//! run a Python subprocess.

use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

pub const ICON_CACHE_TIMEOUT: Duration = Duration::from_secs(20);
const CACHE_TOOLS: [&str; 2] = ["gtk4-update-icon-cache", "gtk-update-icon-cache"];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IconCacheStatus {
    Refreshed,
    SkippedMissingDirectory,
    SkippedMissingTool,
    Failed,
}

impl IconCacheStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Refreshed => "refreshed",
            Self::SkippedMissingDirectory => "skipped_missing_directory",
            Self::SkippedMissingTool => "skipped_missing_tool",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IconCacheRefreshResult {
    pub status: IconCacheStatus,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IconCacheError {
    pub category: &'static str,
    pub operation: &'static str,
}

impl IconCacheError {
    pub const fn internal() -> Self {
        Self {
            category: "internal",
            operation: "icon_cache_refresh",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IconCacheRunError {
    LaunchOrTimeout,
}

pub trait IconCacheRunner {
    /// Return `Ok(false)` for a launched process with a nonzero exit code.
    /// Launch failures and timeout are returned as `Err` so the next candidate
    /// can be tried, matching the former Python best-effort loop.
    fn run(
        &mut self,
        executable: &Path,
        args: &[OsString],
        timeout: Duration,
    ) -> Result<bool, IconCacheRunError>;
}

#[derive(Default)]
pub struct SystemIconCacheRunner;

impl IconCacheRunner for SystemIconCacheRunner {
    fn run(
        &mut self,
        executable: &Path,
        args: &[OsString],
        timeout: Duration,
    ) -> Result<bool, IconCacheRunError> {
        let mut child = Command::new(executable)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| IconCacheRunError::LaunchOrTimeout)?;
        let deadline = Instant::now() + timeout;
        loop {
            match child.try_wait() {
                Ok(Some(status)) => return Ok(status.success()),
                Ok(None) if Instant::now() < deadline => {
                    thread::sleep(Duration::from_millis(50));
                }
                Ok(None) | Err(_) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(IconCacheRunError::LaunchOrTimeout);
                }
            }
        }
    }
}

pub fn refresh_icon_cache_with(
    theme_dir: &Path,
    find_executable: impl Fn(&str) -> Option<PathBuf>,
    runner: &mut impl IconCacheRunner,
) -> Result<IconCacheRefreshResult, IconCacheError> {
    if !theme_dir.is_dir() {
        return Ok(IconCacheRefreshResult {
            status: IconCacheStatus::SkippedMissingDirectory,
        });
    }

    let mut found_tool = false;
    for name in CACHE_TOOLS {
        let Some(executable) = find_executable(name) else {
            continue;
        };
        found_tool = true;
        let args = [
            OsString::from("-f"),
            OsString::from("-t"),
            theme_dir.as_os_str().to_owned(),
        ];
        match runner.run(&executable, &args, ICON_CACHE_TIMEOUT) {
            Ok(true) => {
                return Ok(IconCacheRefreshResult {
                    status: IconCacheStatus::Refreshed,
                });
            }
            Ok(false) => {
                // Existing behavior stops after the first tool that launches,
                // even if it reports a nonzero status.
                return Ok(IconCacheRefreshResult {
                    status: IconCacheStatus::Failed,
                });
            }
            Err(IconCacheRunError::LaunchOrTimeout) => continue,
        }
    }

    Ok(IconCacheRefreshResult {
        status: if found_tool {
            IconCacheStatus::Failed
        } else {
            IconCacheStatus::SkippedMissingTool
        },
    })
}

pub fn refresh_icon_cache(home: &Path) -> Result<IconCacheRefreshResult, IconCacheError> {
    let theme_dir = home.join(".local/share/icons/hicolor");
    refresh_icon_cache_with(
        &theme_dir,
        crate::cli::find_executable_on_path,
        &mut SystemIconCacheRunner,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Fixture {
        root: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "codexbar-icon-cache-{}-{}",
                std::process::id(),
                std::thread::current().name().unwrap_or("test")
            ));
            let _ = std::fs::remove_dir_all(&root);
            std::fs::create_dir_all(&root).unwrap();
            Self { root }
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    #[derive(Default)]
    struct RecordingRunner {
        calls: Vec<(PathBuf, Vec<OsString>, Duration)>,
        results: Vec<Result<bool, IconCacheRunError>>,
    }

    impl IconCacheRunner for RecordingRunner {
        fn run(
            &mut self,
            executable: &Path,
            args: &[OsString],
            timeout: Duration,
        ) -> Result<bool, IconCacheRunError> {
            self.calls
                .push((executable.to_path_buf(), args.to_vec(), timeout));
            if self.results.is_empty() {
                Ok(true)
            } else {
                self.results.remove(0)
            }
        }
    }

    #[test]
    fn prefers_gtk4_tool_and_preserves_argv_timeout_and_theme_path() {
        let fixture = Fixture::new();
        let theme_dir = fixture.root.join("hicolor");
        std::fs::create_dir_all(&theme_dir).unwrap();
        let mut runner = RecordingRunner::default();
        let result = refresh_icon_cache_with(
            &theme_dir,
            |name| Some(PathBuf::from(format!("/tools/{name}"))),
            &mut runner,
        )
        .unwrap();
        assert_eq!(result.status, IconCacheStatus::Refreshed);
        assert_eq!(runner.calls.len(), 1);
        assert_eq!(
            runner.calls[0].0,
            PathBuf::from("/tools/gtk4-update-icon-cache")
        );
        assert_eq!(
            runner.calls[0].1,
            vec![
                OsString::from("-f"),
                OsString::from("-t"),
                theme_dir.as_os_str().to_owned()
            ]
        );
        assert_eq!(runner.calls[0].2, Duration::from_secs(20));
    }

    #[test]
    fn launch_failure_tries_fallback_tool_but_nonzero_exit_stops() {
        let fixture = Fixture::new();
        let theme_dir = fixture.root.join("hicolor");
        std::fs::create_dir_all(&theme_dir).unwrap();
        let mut runner = RecordingRunner {
            results: vec![Err(IconCacheRunError::LaunchOrTimeout), Ok(true)],
            ..Default::default()
        };
        let result = refresh_icon_cache_with(
            &theme_dir,
            |name| Some(PathBuf::from(format!("/tools/{name}"))),
            &mut runner,
        )
        .unwrap();
        assert_eq!(result.status, IconCacheStatus::Refreshed);
        assert_eq!(runner.calls.len(), 2);
        assert_eq!(
            runner.calls[1].0,
            PathBuf::from("/tools/gtk-update-icon-cache")
        );

        runner.calls.clear();
        runner.results = vec![Ok(false), Ok(true)];
        let result = refresh_icon_cache_with(
            &theme_dir,
            |name| Some(PathBuf::from(format!("/tools/{name}"))),
            &mut runner,
        )
        .unwrap();
        assert_eq!(result.status, IconCacheStatus::Failed);
        assert_eq!(runner.calls.len(), 1);
    }

    #[test]
    fn missing_directory_and_missing_tools_are_quiet_skips() {
        let fixture = Fixture::new();
        let mut runner = RecordingRunner::default();
        let absent = fixture.root.join("absent");
        let result = refresh_icon_cache_with(&absent, |_| None, &mut runner).unwrap();
        assert_eq!(result.status, IconCacheStatus::SkippedMissingDirectory);
        assert!(runner.calls.is_empty());

        std::fs::create_dir_all(&absent).unwrap();
        let result = refresh_icon_cache_with(&absent, |_| None, &mut runner).unwrap();
        assert_eq!(result.status, IconCacheStatus::SkippedMissingTool);
        assert!(runner.calls.is_empty());
    }

    #[test]
    fn exhausted_launch_attempts_are_sanitized_best_effort_failure() {
        let fixture = Fixture::new();
        let theme_dir = fixture.root.join("hicolor");
        std::fs::create_dir_all(&theme_dir).unwrap();
        let attempts = AtomicUsize::new(0);
        let mut runner = RecordingRunner {
            results: vec![
                Err(IconCacheRunError::LaunchOrTimeout),
                Err(IconCacheRunError::LaunchOrTimeout),
            ],
            ..Default::default()
        };
        let result = refresh_icon_cache_with(
            &theme_dir,
            |name| {
                attempts.fetch_add(1, Ordering::Relaxed);
                Some(PathBuf::from(format!("/private/{name}")))
            },
            &mut runner,
        )
        .unwrap();
        assert_eq!(result.status, IconCacheStatus::Failed);
        assert_eq!(attempts.load(Ordering::Relaxed), 2);
        assert!(!format!("{:?}", result).contains("private"));
    }
}
