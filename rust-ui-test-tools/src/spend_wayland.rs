//! Standalone Spend Wayland route and fail-closed input/state guard contracts.
//!
//! `ranges` delegates to matrix-core (initial range selection), `matrix`
//! exercises every range and heatmap mode, and `retained-error` delegates to
//! the page-state scenario. The private GTK matrix replaces coordinate-driven
//! clicks with same-process AT-SPI actions. Backend presentation tests retain
//! the missing/zero/partial distinction; these routes make no KDE/portal or
//! physical-input parity claim.

use std::path::PathBuf;

pub const SPEND_RANGES: &[&str] = &["7 days", "30 days", "90 days", "All"];
pub const SPEND_MODES: &[&str] = &["Daily", "Weekly", "Cumulative"];
pub const SPEND_STATES: &[&str] = &["loading", "success", "partial", "empty", "retained-error"];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TargetSample {
    pub received: f64,
    pub pid: u32,
    pub active: bool,
    pub top_hit: bool,
    pub cursor: [i32; 2],
}

/// Read-only state checks need an exact active process; pointer hit testing is
/// required only when the caller is about to send an input event.
pub fn active_target(sample: TargetSample, expected_pid: u32) -> bool {
    sample.pid == expected_pid && expected_pid != 0 && sample.active
}

pub fn guard_target(sample: TargetSample, expected_pid: u32, point: [i32; 2], now: f64) -> bool {
    let age = now - sample.received;
    active_target(sample, expected_pid)
        && (0.15..=0.35).contains(&age)
        && sample.top_hit
        && sample.cursor == point
}

pub fn window_contains(geometry: [f64; 4], point: [i32; 2]) -> bool {
    let [x, y, width, height] = geometry;
    x.is_finite()
        && y.is_finite()
        && width.is_finite()
        && height.is_finite()
        && width > 0.0
        && height > 0.0
        && f64::from(point[0]) >= x
        && f64::from(point[0]) < x + width
        && f64::from(point[1]) >= y
        && f64::from(point[1]) < y + height
}

pub fn point_from_geometry(
    geometry: [f64; 4],
    x_fraction: f64,
    y_fraction: f64,
) -> Result<[i32; 2], &'static str> {
    let [x, y, width, height] = geometry;
    if !x.is_finite()
        || !y.is_finite()
        || !width.is_finite()
        || !height.is_finite()
        || width <= 0.0
        || height <= 0.0
        || !x_fraction.is_finite()
        || !y_fraction.is_finite()
        || x_fraction <= 0.0
        || x_fraction >= 1.0
        || y_fraction <= 0.0
        || y_fraction >= 1.0
    {
        return Err("invalid Spend window geometry or point fraction");
    }
    let px = x + width * x_fraction;
    let py = y + height * y_fraction;
    if px < f64::from(i32::MIN)
        || px > f64::from(i32::MAX)
        || py < f64::from(i32::MIN)
        || py > f64::from(i32::MAX)
    {
        return Err("Spend point overflows coordinate range");
    }
    Ok([px.round() as i32, py.round() as i32])
}

pub async fn run(args: &[String]) -> Result<u8, String> {
    let Some((binary, artifact_dir, scenario)) = parse(args)? else {
        println!("spend-wayland --binary PATH [--scenario ranges|retained-error|matrix] [--artifact-dir DIR]\nRuns Rust-owned private Wayland scenarios; no KDE portal or host input is used.");
        return Ok(0);
    };
    let native_scenario = native_scenario(&scenario)?;
    let mut forwarded = vec![
        "--binary".into(),
        binary.display().to_string(),
        "--scenario".into(),
        native_scenario.into(),
    ];
    if let Some(path) = artifact_dir {
        forwarded.extend(["--artifact-dir".into(), path.display().to_string()]);
    }
    super::isolated_wayland(&forwarded).await
}

fn native_scenario(scenario: &str) -> Result<&'static str, String> {
    match scenario {
        "ranges" => Ok("matrix-core"),
        "retained-error" => Ok("page-state"),
        "matrix" => Ok("matrix"),
        _ => Err(format!("unsupported Spend scenario: {scenario}")),
    }
}

fn parse(args: &[String]) -> Result<Option<(PathBuf, Option<PathBuf>, String)>, String> {
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Ok(None);
    }
    let mut binary = None;
    let mut artifact_dir = None;
    let mut scenario = "ranges".to_owned();
    let mut i = 0;
    while i < args.len() {
        let target = match args[i].as_str() {
            "--binary" => &mut binary,
            "--artifact-dir" => &mut artifact_dir,
            "--scenario" => {
                scenario = args
                    .get(i + 1)
                    .ok_or("--scenario requires a value")?
                    .clone();
                i += 2;
                continue;
            }
            option => return Err(format!("unsupported Spend option: {option}")),
        };
        *target = Some(PathBuf::from(
            args.get(i + 1).ok_or("option requires a value")?,
        ));
        i += 2;
    }
    let binary = binary.ok_or("--binary is required")?;
    if !binary.is_file() || !is_executable(&binary) {
        return Err("--binary must name an executable native GTK build".into());
    }
    Ok(Some((binary, artifact_dir, scenario)))
}

#[cfg(unix)]
fn is_executable(path: &std::path::Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path).is_ok_and(|m| m.permissions().mode() & 0o111 != 0)
}
#[cfg(not(unix))]
fn is_executable(path: &std::path::Path) -> bool {
    path.is_file()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Command, Output};

    fn sample() -> TargetSample {
        TargetSample {
            received: 100.0,
            pid: 4242,
            active: true,
            top_hit: true,
            cursor: [810, 315],
        }
    }

    #[test]
    fn input_guard_requires_fresh_active_topmost_exact_pointer() {
        assert!(guard_target(sample(), 4242, [810, 315], 100.2));
        for changed in [
            TargetSample {
                received: 99.0,
                ..sample()
            },
            TargetSample { pid: 7, ..sample() },
            TargetSample {
                active: false,
                ..sample()
            },
            TargetSample {
                top_hit: false,
                ..sample()
            },
            TargetSample {
                cursor: [0, 0],
                ..sample()
            },
        ] {
            assert!(!guard_target(changed, 4242, [810, 315], 100.2));
        }
        assert!(!guard_target(
            TargetSample {
                received: 100.1,
                ..sample()
            },
            4242,
            [810, 315],
            100.2
        ));
    }

    #[test]
    fn read_only_active_target_does_not_require_pointer_hit() {
        let state = TargetSample {
            top_hit: false,
            cursor: [1727, 2],
            ..sample()
        };
        assert!(active_target(state, 4242));
        assert!(!active_target(state, 7));
        assert!(!active_target(
            TargetSample {
                active: false,
                ..state
            },
            4242
        ));
    }

    #[test]
    fn spend_coordinate_bounds_and_axis_coverage_are_explicit() {
        let point = point_from_geometry([0.0, 0.0, 1080.0, 820.0], 0.5, 0.4).unwrap();
        assert_eq!(point, [540, 328]);
        assert!(window_contains([364.0, 149.0, 1080.0, 820.0], point));
        assert!(!window_contains([0.0, 0.0, 0.0, 820.0], point));
        assert!(point_from_geometry([0.0, 0.0, 1080.0, 820.0], 0.0, 0.5).is_err());
        let fractional = point_from_geometry([432.0, 175.625, 1080.0, 820.0], 0.5, 0.4).unwrap();
        assert_eq!(fractional, [972, 504]);
        assert_eq!(SPEND_RANGES, &["7 days", "30 days", "90 days", "All"]);
        assert_eq!(SPEND_MODES, &["Daily", "Weekly", "Cumulative"]);
        assert_eq!(
            SPEND_STATES,
            &["loading", "success", "partial", "empty", "retained-error"]
        );
    }

    #[test]
    fn standalone_routes_select_existing_rust_private_scenarios() {
        assert_eq!(native_scenario("ranges").unwrap(), "matrix-core");
        assert_eq!(native_scenario("retained-error").unwrap(), "page-state");
        assert_eq!(native_scenario("matrix").unwrap(), "matrix");
        assert!(native_scenario("portal").is_err());
    }

    #[cfg(unix)]
    struct FixtureDir(std::path::PathBuf);

    #[cfg(unix)]
    impl FixtureDir {
        fn new() -> Self {
            use std::os::unix::fs::PermissionsExt;
            let path = std::env::temp_dir().join(format!(
                "codexbar-spend-fixture-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir(&path).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
            Self(path)
        }

        fn file(&self, name: &str) -> std::path::PathBuf {
            self.0.join(name)
        }
    }

    #[cfg(unix)]
    impl Drop for FixtureDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[cfg(unix)]
    fn make_fixture(dir: &FixtureDir) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let path = dir.file("fake-codexbar");
        let script = r##"#!/bin/sh
set -eu
case "${1-}" in
  cost)
    echo call >> "$NATIVE_SPEND_CALLS"
    if [ -e "$NATIVE_SPEND_FAIL_COST" ]; then
      : > "$NATIVE_SPEND_COST_FAILURE_DONE"
      exit 1
    fi
    while [ -e "$NATIVE_SPEND_DELAY_COST" ] && [ ! -e "$NATIVE_SPEND_RELEASE_COST" ]; do sleep 0.01; done
    if [ -e "$NATIVE_SPEND_EMPTY_COST" ]; then
      printf '%s\n' '[]'
      : > "$NATIVE_SPEND_COST_DONE"
      exit 0
    fi
    if [ -e "$NATIVE_SPEND_PARTIAL_COST" ]; then
      printf '%s\n' '[{"provider":"codex","totalCost":12.5,"coverage":{"priced":3,"unpriced":1},"historyCoverageIsEstablished":false,"daily":[{"date":"2026-11-05","totalCost":0,"totalTokens":0}],"projects":[{"name":"Synthetic Workspace"}],"models":[{"name":"Synthetic Model"}]}]'
    else
      printf '%s\n' '[{"provider":"codex","totalCost":12.5,"coverage":{"priced":3,"unpriced":1},"daily":[{"date":"2026-11-05","totalCost":0,"totalTokens":0}],"projects":[{"name":"Synthetic Workspace"}],"models":[{"name":"Synthetic Model"}]}]'
    fi
    : > "$NATIVE_SPEND_COST_DONE"
    ;;
  *) printf '%s\n' '[]' ;;
esac
"##;
        std::fs::write(&path, script).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        path
    }

    #[cfg(unix)]
    fn run_fixture(dir: &FixtureDir, binary: &std::path::Path) -> Output {
        Command::new(binary)
            .arg("cost")
            .env("NATIVE_SPEND_CALLS", dir.file("calls"))
            .env("NATIVE_SPEND_COST_DONE", dir.file("cost-done"))
            .env(
                "NATIVE_SPEND_COST_FAILURE_DONE",
                dir.file("cost-failure-done"),
            )
            .env("NATIVE_SPEND_PARTIAL_COST", dir.file("partial"))
            .env("NATIVE_SPEND_EMPTY_COST", dir.file("empty"))
            .env("NATIVE_SPEND_FAIL_COST", dir.file("fail"))
            .env("NATIVE_SPEND_DELAY_COST", dir.file("delay"))
            .env("NATIVE_SPEND_RELEASE_COST", dir.file("release"))
            .output()
            .unwrap()
    }

    #[cfg(unix)]
    #[test]
    fn synthetic_cost_fixture_preserves_success_partial_empty_and_failure_shapes() {
        let dir = FixtureDir::new();
        let binary = make_fixture(&dir);
        let success = run_fixture(&dir, &binary);
        assert!(success.status.success());
        let success_payload: serde_json::Value = serde_json::from_slice(&success.stdout).unwrap();
        let entry = success_payload[0].clone();
        assert_eq!(entry["provider"], "codex");
        assert_eq!(entry["totalCost"], 12.5);
        assert_eq!(entry["coverage"]["unpriced"], 1);
        assert_eq!(entry["daily"][0]["totalCost"], 0);
        assert_eq!(entry["projects"][0]["name"], "Synthetic Workspace");
        assert_eq!(entry["models"][0]["name"], "Synthetic Model");
        assert!(dir.file("cost-done").exists());

        std::fs::remove_file(dir.file("cost-done")).unwrap();
        std::fs::write(dir.file("partial"), "").unwrap();
        let partial = run_fixture(&dir, &binary);
        assert!(partial.status.success());
        let partial_payload: serde_json::Value = serde_json::from_slice(&partial.stdout).unwrap();
        let entry = partial_payload[0].clone();
        assert_eq!(entry["historyCoverageIsEstablished"], false);
        assert_eq!(entry["coverage"]["priced"], 3);

        std::fs::remove_file(dir.file("partial")).unwrap();
        std::fs::remove_file(dir.file("cost-done")).unwrap();
        std::fs::write(dir.file("empty"), "").unwrap();
        let empty = run_fixture(&dir, &binary);
        assert!(empty.status.success());
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&empty.stdout).unwrap(),
            serde_json::json!([])
        );

        std::fs::remove_file(dir.file("empty")).unwrap();
        std::fs::remove_file(dir.file("cost-done")).unwrap();
        std::fs::write(dir.file("fail"), "").unwrap();
        let failed = run_fixture(&dir, &binary);
        assert!(!failed.status.success());
        assert!(failed.stdout.is_empty());
        assert!(dir.file("cost-failure-done").exists());
        assert!(!dir.file("cost-done").exists());
    }
}
