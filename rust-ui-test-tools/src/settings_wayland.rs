//! Standalone Settings Wayland route and fail-closed geometry guard contracts.
//!
//! Legacy KDE RemoteDesktop/bridge input and X11-measured coordinate overrides
//! are intentionally not carried forward. The replacements use Rust AT-SPI
//! actions against a private Weston instance: `general` checks General
//! persistence, `residual` checks Display and Spend preference switches,
//! `advanced` checks export/import/reset, and `matrix` covers notifications,
//! tray, Hooks, Spend ranges/modes and Sessions. These scenarios do not
//! establish KDE compositor, portal, or physical-input parity.

use std::path::PathBuf;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rect(pub [i32; 4]);

impl Rect {
    fn valid(&self) -> bool {
        let [x, y, width, height] = self.0;
        x >= 0 && y >= 0 && width > 0 && height > 0
    }

    fn contains(&self, inner: &Self) -> bool {
        let [x, y, width, height] = self.0;
        let [ix, iy, iw, ih] = inner.0;
        self.valid()
            && inner.valid()
            && ix >= x
            && iy >= y
            && i64::from(ix) + i64::from(iw) <= i64::from(x) + i64::from(width)
            && i64::from(iy) + i64::from(ih) <= i64::from(y) + i64::from(height)
    }
}

#[derive(Clone, Debug)]
pub struct GeometryEvidence<'a> {
    pub app_name: &'a str,
    pub expected_app: &'a str,
    pub pid: u32,
    pub active_pid: u32,
    pub active_title: &'a str,
    pub expected_title: &'a str,
    pub window_count: usize,
    pub scale_factors: &'a [i32],
    pub window_screen: Rect,
    pub window_local: Rect,
    pub control_screen: Rect,
    pub control_local: Rect,
    pub control_role: &'a str,
    pub expected_roles: &'a [&'a str],
    pub visible: bool,
    pub showing: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedGeometry {
    pub coordinate_space: &'static str,
    pub control_bounds: Rect,
    pub point: [i32; 2],
}

/// Accept only one visible control in the exact app-owned, focused window.
/// Global screen extents are preferred; a local translation is accepted only
/// when both AT-SPI window origins are zero and KWin supplies the verified frame.
pub fn resolve_geometry(e: &GeometryEvidence<'_>) -> Result<ResolvedGeometry, &'static str> {
    if e.app_name != e.expected_app || e.pid == 0 || e.active_pid != e.pid {
        return Err("application identity or PID mismatch");
    }
    if e.active_title != e.expected_title || e.window_count != 1 {
        return Err("target window is not uniquely active");
    }
    if e.scale_factors.is_empty() || e.scale_factors.iter().any(|scale| *scale != 1) {
        return Err("unsupported or missing display scale");
    }
    if !e.visible || !e.showing || !e.expected_roles.contains(&e.control_role) {
        return Err("target control is hidden or has an unexpected role");
    }
    if !e.window_screen.valid() || !e.window_local.valid() {
        return Err("invalid top-level geometry");
    }

    let (space, bounds) = if e.window_screen == e.window_local {
        if !e.window_screen.contains(&e.control_screen) {
            return Err("global control lies outside its window");
        }
        ("screen", e.control_screen.clone())
    } else if e.window_local.0[0..2] == [0, 0] && e.control_screen.0[0..2] == [0, 0] {
        let [wx, wy, _, _] = e.window_screen.0;
        let [cx, cy, cw, ch] = e.control_local.0;
        let translated = Rect([wx.saturating_add(cx), wy.saturating_add(cy), cw, ch]);
        if !e.window_screen.contains(&translated) {
            return Err("translated control lies outside verified window");
        }
        ("window-local-translated", translated)
    } else {
        return Err("AT-SPI and KWin geometry do not establish a coordinate space");
    };
    let [x, y, width, height] = bounds.0;
    Ok(ResolvedGeometry {
        coordinate_space: space,
        control_bounds: bounds,
        point: [x + width / 2, y + height / 2],
    })
}

pub async fn run(args: &[String]) -> Result<u8, String> {
    let Some((binary, artifact_dir, scenario)) = parse(args)? else {
        println!("settings-wayland --binary PATH [--scenario general|residual|advanced|matrix] [--artifact-dir DIR]\nRuns Rust-owned private Wayland scenarios; no KDE portal or host input is used.");
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
        "general" => Ok("matrix-core"),
        "residual" => Ok("settings-residual"),
        "advanced" => Ok("advanced"),
        "matrix" => Ok("matrix"),
        _ => Err(format!("unsupported Settings scenario: {scenario}")),
    }
}

fn parse(args: &[String]) -> Result<Option<(PathBuf, Option<PathBuf>, String)>, String> {
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Ok(None);
    }
    let mut binary = None;
    let mut artifact_dir = None;
    let mut scenario = "general".to_owned();
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
            option => return Err(format!("unsupported Settings option: {option}")),
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

    fn evidence() -> GeometryEvidence<'static> {
        GeometryEvidence {
            app_name: "codexbar-gtk-synthetic-wayland-test",
            expected_app: "codexbar-gtk-synthetic-wayland-test",
            pid: 4242,
            active_pid: 4242,
            active_title: "CodexBar Settings",
            expected_title: "CodexBar Settings",
            window_count: 1,
            scale_factors: &[1],
            window_screen: Rect([364, 149, 1000, 740]),
            window_local: Rect([364, 149, 1000, 740]),
            control_screen: Rect([500, 300, 80, 40]),
            control_local: Rect([136, 151, 80, 40]),
            control_role: "page tab",
            expected_roles: &["page tab"],
            visible: true,
            showing: true,
        }
    }

    #[test]
    fn screen_geometry_resolves_expected_control_center() {
        let resolved = resolve_geometry(&evidence()).unwrap();
        assert_eq!(resolved.coordinate_space, "screen");
        assert_eq!(resolved.control_bounds, Rect([500, 300, 80, 40]));
        assert_eq!(resolved.point, [540, 320]);
    }

    #[test]
    fn local_geometry_is_translated_only_from_zero_origins() {
        let mut e = evidence();
        e.window_screen = Rect([364, 149, 1000, 740]);
        e.window_local = Rect([0, 0, 1000, 740]);
        e.control_screen = Rect([0, 0, 80, 40]);
        assert_eq!(resolve_geometry(&e).unwrap().point, [540, 320]);
        e.control_screen = Rect([12, 8, 80, 40]);
        assert_eq!(
            resolve_geometry(&e),
            Err("AT-SPI and KWin geometry do not establish a coordinate space")
        );
    }

    #[test]
    fn geometry_guard_rejects_identity_ambiguity_scale_visibility_and_bounds() {
        for mutate in [0, 1, 2, 3, 4, 5] {
            let mut e = evidence();
            match mutate {
                0 => e.active_pid = 7,
                1 => e.window_count = 2,
                2 => e.scale_factors = &[2],
                3 => e.visible = false,
                4 => e.control_role = "label",
                _ => e.control_screen = Rect([1360, 720, 20, 20]),
            }
            assert!(
                resolve_geometry(&e).is_err(),
                "mutant {mutate} must fail closed"
            );
        }
    }

    #[test]
    fn standalone_routes_map_to_rust_owned_private_scenarios() {
        assert_eq!(native_scenario("general").unwrap(), "matrix-core");
        assert_eq!(native_scenario("residual").unwrap(), "settings-residual");
        assert_eq!(native_scenario("advanced").unwrap(), "advanced");
        assert_eq!(native_scenario("matrix").unwrap(), "matrix");
        assert!(native_scenario("portal").is_err());
    }
}
