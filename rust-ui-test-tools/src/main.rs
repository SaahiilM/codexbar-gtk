use atspi::{
    connection::AccessibilityConnection,
    proxy::{
        accessible::{AccessibleProxy, ObjectRefExt},
        action::ActionProxy,
        component::ComponentProxy,
        proxy_ext::ProxyExt,
        selection::SelectionProxy,
        text::TextProxy,
    },
    CoordType, Interface, ObjectRefOwned, State, StateSet,
};
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    io::Read,
    ops::{Deref, DerefMut},
    path::{Path, PathBuf},
    process::{Child, Command, ExitCode, ExitStatus, Stdio},
    time::Duration,
};
use tokio::time::{sleep, timeout, Instant};

const MAX_NODES: usize = 10_000;
const MAX_CHILDREN: usize = 4_096;
const MAX_DEPTH: usize = 40;
const MAX_MATRIX_EVIDENCE_BYTES: usize = 128 * 1024;
const WINDOW_ROLES: &[&str] = &["frame", "window", "application"];
const CHOOSER_FALLBACK_PLACES: &[&str] = &["Recent", "Open your personal folder"];

fn next_chooser_fallback_place(
    attempted: &std::collections::HashSet<&str>,
) -> Option<&'static str> {
    CHOOSER_FALLBACK_PLACES
        .iter()
        .copied()
        .find(|place| !attempted.contains(place))
}

fn is_within_tree(identity: &str, root: &str) -> bool {
    identity == root
        || identity
            .strip_prefix(root)
            .is_some_and(|suffix| suffix.starts_with('/'))
}

struct ChooserDialogSample<'a> {
    pid: u32,
    role: &'a str,
    title: &'a str,
    showing: bool,
    visible: bool,
    sensitive: bool,
    geometry: [i32; 2],
}

struct ChooserActionSample<'a> {
    pid: u32,
    within_dialog: bool,
    role: &'a str,
    showing: bool,
    visible: bool,
    sensitive: bool,
    action_names: &'a [String],
}

fn chooser_visit_action_index(
    sample: &ChooserActionSample<'_>,
    expected_pid: u32,
) -> Option<usize> {
    if sample.pid != expected_pid
        || !sample.within_dialog
        || sample.role != "panel"
        || !sample.showing
        || !sample.visible
        || !sample.sensitive
    {
        return None;
    }
    let matches: Vec<_> = sample
        .action_names
        .iter()
        .enumerate()
        .filter(|(_, name)| name.as_str() == "item.visit")
        .map(|(index, _)| index)
        .collect();
    if matches.len() == 1 {
        Some(matches[0])
    } else {
        None
    }
}

fn chooser_dialog_guard(
    sample: &ChooserDialogSample<'_>,
    expected_pid: u32,
    expected_title: &str,
) -> bool {
    sample.pid == expected_pid
        && sample.role == "dialog"
        && sample.title == expected_title
        && sample.showing
        && sample.visible
        && sample.sensitive
        && sample.geometry[0] > 0
        && sample.geometry[1] > 0
}

#[allow(clippy::too_many_arguments)]
fn atspi_target_guard(
    actual_pid: u32,
    expected_pid: u32,
    actual_identity: &str,
    expected_identity: &str,
    role: &str,
    showing: bool,
    visible: bool,
    sensitive: bool,
    has_action: bool,
) -> bool {
    actual_pid == expected_pid
        && actual_identity == expected_identity
        && matches!(role, "switch" | "check box" | "toggle button")
        && showing
        && visible
        && sensitive
        && has_action
}
#[allow(clippy::too_many_arguments)]
fn atspi_route_target_guard(
    actual_pid: u32,
    expected_pid: u32,
    actual_identity: &str,
    expected_identity: &str,
    role: &str,
    showing: bool,
    visible: bool,
    sensitive: bool,
    has_action: bool,
) -> bool {
    atspi_target_guard(
        actual_pid,
        expected_pid,
        actual_identity,
        expected_identity,
        role,
        showing,
        visible,
        sensitive,
        has_action,
    ) || (actual_pid == expected_pid
        && actual_identity == expected_identity
        && matches!(role, "page tab" | "tab" | "button")
        && showing
        && visible
        && sensitive
        && has_action)
}
fn cleanup_confirmed(app_reaped: bool, weston_reaped: bool, home_removed: bool) -> bool {
    app_reaped && weston_reaped && home_removed
}
fn encode_bounded_json(value: &serde_json::Value, max_bytes: usize) -> Result<Vec<u8>, String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    if bytes.len() > max_bytes {
        return Err(format!(
            "evidence is {} bytes, exceeding the {max_bytes}-byte cap",
            bytes.len()
        ));
    }
    Ok(bytes)
}

struct PrivateRunnerState {
    root: PathBuf,
    home: PathBuf,
    runtime: PathBuf,
    config: PathBuf,
    data: PathBuf,
    cache: PathBuf,
}

impl PrivateRunnerState {
    fn create() -> Result<Self, String> {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_nanos();
        let root =
            env::temp_dir().join(format!("codexbar-ui-runner-{}-{nonce}", std::process::id()));
        fs::create_dir(&root).map_err(|e| e.to_string())?;
        let state = Self {
            home: root.join("home"),
            runtime: root.join("runtime"),
            config: root.join("config"),
            data: root.join("data"),
            cache: root.join("cache"),
            root,
        };
        set_private_dir(&state.root)?;
        for path in [
            &state.home,
            &state.runtime,
            &state.config,
            &state.data,
            &state.cache,
        ] {
            fs::create_dir(path).map_err(|e| e.to_string())?;
            set_private_dir(path)?;
        }
        Ok(state)
    }

    fn configure(&self, command: &mut Command) {
        command
            .env_clear()
            .env("HOME", &self.home)
            .env("XDG_RUNTIME_DIR", &self.runtime)
            .env("XDG_CONFIG_HOME", &self.config)
            .env("XDG_DATA_HOME", &self.data)
            .env("XDG_CACHE_HOME", &self.cache);
    }

    fn cleanup(&mut self) -> bool {
        for _ in 0..40 {
            match fs::remove_dir_all(&self.root) {
                Ok(()) => return true,
                Err(_) if !self.root.exists() => return true,
                Err(_) => std::thread::sleep(Duration::from_millis(50)),
            }
        }
        !self.root.exists()
    }
}

impl Drop for PrivateRunnerState {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

fn accessible_context_matches(identity: &str, context: Option<&str>) -> bool {
    context.is_none_or(|expected| {
        expected.strip_prefix("path-fragment:").map_or_else(
            || identity.contains(&format!(":{expected}/")),
            |fragment| identity.contains(fragment),
        )
    })
}
fn record_window_candidate(candidates: &mut Vec<String>, identity: &str, role: &str, name: &str) {
    const MAX_WINDOW_CANDIDATES: usize = 24;
    const MAX_ACCESSIBLE_NAME: usize = 160;
    if candidates.len() < MAX_WINDOW_CANDIDATES {
        let bounded_name: String = name.chars().take(MAX_ACCESSIBLE_NAME).collect();
        candidates.push(format!("{identity}:{role}:{bounded_name:?}"));
    }
}

struct OwnedChild {
    child: Child,
    reaped: bool,
}
impl OwnedChild {
    fn spawn(command: &mut Command) -> Result<Self, String> {
        command
            .spawn()
            .map(|child| Self {
                child,
                reaped: false,
            })
            .map_err(|e| e.to_string())
    }
    fn terminate(&mut self) -> std::io::Result<ExitStatus> {
        terminate_owned_group(self.child.id());
        let _ = self.child.kill();
        let status = self.child.wait()?;
        self.reaped = true;
        Ok(status)
    }
}
impl Deref for OwnedChild {
    type Target = Child;
    fn deref(&self) -> &Child {
        &self.child
    }
}
impl DerefMut for OwnedChild {
    fn deref_mut(&mut self) -> &mut Child {
        &mut self.child
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !self.reaped {
            let _ = self.terminate();
        }
    }
}
fn expected_toggled_map(
    before: &serde_json::Value,
    key: &str,
) -> Result<serde_json::Value, String> {
    let mut expected = before.clone();
    expected
        .as_object_mut()
        .ok_or("settings map is not a JSON object")?
        .insert(key.into(), serde_json::Value::Bool(true));
    Ok(expected)
}

#[tokio::main]
async fn main() -> ExitCode {
    match dispatch(env::args().skip(1).collect()).await {
        Ok(code) => ExitCode::from(code),
        Err(error) => {
            eprintln!("codexbar-ui-test-tool: {error}");
            ExitCode::from(1)
        }
    }
}

async fn dispatch(args: Vec<String>) -> Result<u8, String> {
    let Some(command) = args.first().map(String::as_str) else {
        return Err(usage());
    };
    match command {
        "chooser" => chooser(&args[1..]).await,
        "isolated-wayland" => isolated_wayland(&args[1..]).await,
        "settings-wayland" => unavailable_runner("settings-wayland", &args[1..]),
        "spend-wayland" => unavailable_runner("spend-wayland", &args[1..]),
        "update-check-wayland" => unavailable_runner("update-check-wayland", &args[1..]),
        _ => Err(usage()),
    }
}

fn usage() -> String {
    "usage: codexbar-ui-test-tool chooser MODE PID TITLE PATH | isolated-wayland --binary PATH [--scenario NAME] [--artifact-dir DIR] | settings-wayland --binary PATH ... | spend-wayland --binary PATH ... | update-check-wayland --binary PATH ...".into()
}

fn unavailable_runner(name: &str, args: &[String]) -> Result<u8, String> {
    if args.is_empty() {
        return Err(format!(
            "{name} requires its preserved CLI options; see --help"
        ));
    }
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{name}: native runner is not yet ported; Python implementation remains the evidence reference");
        return Ok(0);
    }
    Err(format!(
        "{name} native runner is incomplete; refusing to emit a passing evidence record"
    ))
}

async fn isolated_wayland(args: &[String]) -> Result<u8, String> {
    if args.iter().any(|a| a == "--help" || a == "-h") {
        println!("isolated-wayland --binary PATH [--scenario matrix|matrix-core|advanced|settings-residual|page-state|settings-combo-diagnostic] [--artifact-dir DIR]");
        return Ok(0);
    }
    let value = |flag: &str, default: Option<&str>| -> Result<Option<String>, String> {
        match args.iter().position(|a| a == flag) {
            Some(i) => args
                .get(i + 1)
                .map(|v| Some(v.clone()))
                .ok_or_else(|| format!("{flag} requires a value")),
            None => Ok(default.map(str::to_owned)),
        }
    };
    let scenario = value("--scenario", Some("matrix"))?.expect("scenario default");
    let binary = value("--binary", None)?.ok_or("--binary is required")?;
    let artifact_dir = value("--artifact-dir", None)?
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            env::temp_dir().join(format!("codexbar-native-wayland-{}", std::process::id()))
        });
    if scenario == "matrix-core" || scenario == "matrix" {
        return isolated_wayland_matrix(binary, artifact_dir, scenario.clone()).await;
    }
    if scenario == "page-state" {
        return isolated_wayland_matrix(binary, artifact_dir, scenario).await;
    }
    if scenario != "settings-combo-diagnostic" {
        return Err(format!("isolated-wayland {scenario:?} runner is incomplete; refusing to report captures or pass status"));
    }
    let binary_path = Path::new(&binary);
    if !binary_path.is_file() || !is_executable(binary_path) {
        return Err(format!(
            "native GTK binary not found or not executable: {}",
            binary_path.display()
        ));
    }
    if artifact_dir.exists() {
        if !artifact_dir.is_dir()
            || fs::read_dir(&artifact_dir)
                .map_err(|e| e.to_string())?
                .next()
                .is_some()
        {
            return Err(format!(
                "artifact directory must be new or empty: {}",
                artifact_dir.display()
            ));
        }
    } else {
        fs::create_dir_all(&artifact_dir).map_err(|e| e.to_string())?;
    }
    set_private_dir(&artifact_dir)?;
    let mut file = fs::File::open(binary_path).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let n = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }
    let digest = format!("{:x}", hasher.finalize());
    let runner_commit = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
        .unwrap_or_else(|| "unknown".into());
    let controls = [
        ("Display", "Reset time format", "resetTimesOption", "absolute", "combo", "scripts/smoke-native-settings.sh: wait_for_preference resetTimesOption both"),
        ("Display", "Workday ticks", "workdayTickAppearance", "highContrast", "combo", "scripts/smoke-native-settings.sh: wait_for_preference workdayTickAppearance highContrast"),
        ("Menu Bar", "Icon style", "menuBarIconStyle", "iconPercent", "combo", "scripts/smoke-native-settings.sh: wait_for_preference menuBarIconStyle iconPercent"),
        ("Menu Bar", "Icon shows", "unifiedIconSource", "first", "combo", "scripts/smoke-native-settings.sh: wait_for_preference unifiedIconSource automatic"),
        ("Menu Bar", "Provider rows", "switcherRowsOption", "details", "combo", "scripts/smoke-native-settings.sh: wait_for_preference switcherRowsOption details"),
        ("Usage & Spend", "Statistics time zone", "costUsageBucketTimeZone", "Africa/Abidjan", "combo", "scripts/smoke-native-settings.sh: wait_for_nonempty_preference costUsageBucketTimeZone"),
    ];
    let evidence = serde_json::json!({
        "scenario":"settings-combo-diagnostic", "status":"unsupported",
        "reason":"A historical native GTK AT-SPI observation did not expose usable combo selection/action. This diagnostic does not test the supplied binary; combo tree probes are not repeated.",
        "runner_commit":runner_commit,
        "historical_observation":{"source_commit":"3e442c1dfe46a5ba153fdccc406ae28f76f490d1","scope":"native Rust GTK app combo controls observed through AT-SPI on private Wayland","finding":"combo selection/action was not usable in that observed GTK accessibility path"},
        "supplied_binary_sha256":digest, "current_run":"static mapping only; no application binary launched",
        "controls":controls.iter().map(|(page,label,key,value,kind,x11)| serde_json::json!({"page":page,"label":label,"key":key,"wayland_target":value,"kind":kind,"x11_assertion":x11,"status":"unsupported"})).collect::<Vec<_>>(),
        "exit_code":3,
        "limits":["No GTK app, AT-SPI tree, or combo action was launched in this diagnostic.","The supplied binary hash is identity metadata, not runtime evidence.","The six controls map to X11 smoke assertions; this is not a current binary test or product defect claim."]
    });
    let evidence_path = artifact_dir.join("evidence.json");
    let mut out = serde_json::to_vec_pretty(&evidence).map_err(|e| e.to_string())?;
    out.push(b'\n');
    fs::write(&evidence_path, out).map_err(|e| e.to_string())?;
    set_private_file(&evidence_path)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&evidence).map_err(|e| e.to_string())?
    );
    eprintln!("UNSUPPORTED: native combo accessibility is not verified");
    Ok(3)
}

// The full matrix extends the independently useful, compatibility-preserved
// matrix-core route with the remaining legacy matrix interactions.
async fn isolated_wayland_matrix(
    binary: String,
    artifacts: PathBuf,
    scenario: String,
) -> Result<u8, String> {
    let binary = PathBuf::from(binary)
        .canonicalize()
        .map_err(|e| format!("native binary: {e}"))?;
    if !is_executable(&binary) {
        return Err(format!(
            "native GTK binary is not executable: {}",
            binary.display()
        ));
    }
    if artifacts.exists()
        && fs::read_dir(&artifacts)
            .map_err(|e| e.to_string())?
            .next()
            .is_some()
    {
        return Err("artifact directory must be empty".into());
    }
    fs::create_dir_all(&artifacts).map_err(|e| e.to_string())?;
    set_private_dir(&artifacts)?;
    if env::var_os("CODEXBAR_UI_TEST_PRIVATE_BUS").is_none() {
        let runner_state = PrivateRunnerState::create()?;
        let exe = env::current_exe().map_err(|e| e.to_string())?;
        let mut cmd = tokio::process::Command::new("dbus-run-session");
        cmd.args(["--"])
            .arg(exe)
            .args(["isolated-wayland", "--scenario", &scenario, "--binary"])
            .arg(&binary)
            .args(["--artifact-dir"])
            .arg(&artifacts)
            .arg("--private-bus");
        runner_state.configure(cmd.as_std_mut());
        for key in ["PATH", "LANG", "LC_ALL"] {
            if let Some(value) = env::var_os(key) {
                cmd.env(key, value);
            }
        }
        cmd.env("CODEXBAR_UI_TEST_PRIVATE_BUS", "1")
            .kill_on_drop(true);
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            cmd.as_std_mut().process_group(0);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("start private D-Bus: {e}"))?;
        let runner_pid = child.id().unwrap_or_default();
        let interrupt = tokio::spawn(async move {
            if tokio::signal::ctrl_c().await.is_ok() {
                #[cfg(unix)]
                {
                    let _ = Command::new("kill")
                        .args(["-INT", &format!("-{runner_pid}")])
                        .status();
                }
            }
        });
        let result = timeout(Duration::from_secs(240), child.wait()).await;
        interrupt.abort();
        match result {
            Ok(Ok(status)) if status.success() => {
                let marker = artifacts.join("private-bus-socket.txt");
                let socket = fs::read_to_string(&marker)
                    .map_err(|e| format!("private D-Bus cleanup marker missing: {e}"))?;
                let removed = !Path::new(socket.trim()).exists();
                let _ = fs::remove_file(marker);
                if !removed {
                    return Err("private D-Bus socket remained after dbus-run-session exit".into());
                }
                let mut runner_state = runner_state;
                let runner_state_removed = runner_state.cleanup();
                drop(runner_state);
                if !runner_state_removed {
                    return Err(
                        "private automation HOME/XDG state remained after runner exit".into(),
                    );
                }
                let evidence_path = artifacts.join("evidence.json");
                let mut evidence: serde_json::Value =
                    serde_json::from_slice(&fs::read(&evidence_path).map_err(|e| e.to_string())?)
                        .map_err(|e| e.to_string())?;
                evidence["cleanup"]["private_dbus_socket_removed"] = serde_json::Value::Bool(true);
                evidence["cleanup"]["private_runner_state_removed"] =
                    serde_json::Value::Bool(runner_state_removed);
                fs::write(
                    &evidence_path,
                    encode_bounded_json(&evidence, MAX_MATRIX_EVIDENCE_BYTES)?,
                )
                .map_err(|e| e.to_string())?;
                set_private_file(&evidence_path)?;
                return Ok(0);
            }
            Ok(Ok(status)) => return Err(format!("private matrix runner exited {status}")),
            Ok(Err(e)) => return Err(format!("wait for private runner: {e}")),
            Err(_) => {
                #[cfg(unix)]
                {
                    let _ = Command::new("kill")
                        .args(["-TERM", &format!("-{}", child.id().unwrap_or_default())])
                        .status();
                }
                let _ = timeout(Duration::from_secs(3), child.wait()).await;
                return Err(
                    "private matrix exceeded 240 second deadline; private process group terminated"
                        .into(),
                );
            }
        }
    }
    match timeout(Duration::from_secs(210), run_matrix_private(&binary, &artifacts, &scenario)).await {
        Ok(result) => result?,
        Err(_) => return Err("private Wayland matrix exceeded its 210 second runtime deadline; owned child guards performed cleanup".into()),
    }
    Ok(0)
}

async fn run_matrix_private(binary: &Path, artifacts: &Path, scenario: &str) -> Result<(), String> {
    let full = scenario == "matrix";
    let scratch = env::temp_dir().join(format!(
        "codexbar-ui-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir(&scratch).map_err(|e| e.to_string())?;
    set_private_dir(&scratch)?;
    let home = scratch.join("home");
    let runtime = scratch.join("runtime");
    fs::create_dir(&home).map_err(|e| e.to_string())?;
    fs::create_dir(&runtime).map_err(|e| e.to_string())?;
    set_private_dir(&home)?;
    set_private_dir(&runtime)?;
    let config = home.join(".config/codexbar-gtk");
    fs::create_dir_all(&config).map_err(|e| e.to_string())?;
    let prefs = config.join("settings.json");
    let mut before = serde_json::Value::Object(codexbar_core::preferences::default_values());
    before["refreshAllProvidersOnMenuOpen"] = serde_json::Value::Bool(false);
    before["showTray"] = serde_json::Value::Bool(false);
    before["preferredCurrencyCode"] = serde_json::Value::String("USD".into());
    if full {
        for key in [
            "sessionQuotaNotificationsEnabled",
            "quotaWarningNotificationsEnabled",
            "limitResetNotificationsEnabled",
            "predictivePaceNotificationsEnabled",
        ] {
            before[key] = serde_json::Value::Bool(false);
        }
    }
    fs::write(&prefs, serde_json::to_vec(&before).unwrap()).map_err(|e| e.to_string())?;
    let cli = scratch.join("fake-codexbar");
    let sessions_mode = home.join("sessions-mode");
    let cli_log = home.join("cli-calls.log");
    let hooks_state = home.join("hooks-enabled");
    let cost_mode = home.join("cost-mode");
    let cost_error_count = home.join("cost-error-count");
    fs::write(&sessions_mode, "success\n").map_err(|e| e.to_string())?;
    fs::write(&hooks_state, "true\n").map_err(|e| e.to_string())?;
    fs::write(&cost_mode, "success\n").map_err(|e| e.to_string())?;
    fs::write(&cost_error_count, "0\n").map_err(|e| e.to_string())?;
    let cli_script = r##"#!/bin/sh
if [ -n "${NATIVE_CLI_LOG:-}" ]; then printf '%s\n' "$*" >> "$NATIVE_CLI_LOG"; fi
case "${1:-}" in
  --version) printf 'synthetic CodexBar\n' ;;
  usage) printf '%s\n' '[{"provider":"codex","source":"synthetic","usage":{"updatedAt":"2026-11-01T12:00:00Z","primary":{"usedPercent":42,"resetsAt":"2026-11-01T18:00:00Z","windowMinutes":300}}}]' ;;
  cost)
    if [ -n "${NATIVE_COST_MODE_FILE:-}" ] && [ "$(cat "$NATIVE_COST_MODE_FILE")" = error ]; then
      n=0; [ -f "$NATIVE_COST_ERROR_COUNT_FILE" ] && n=$(cat "$NATIVE_COST_ERROR_COUNT_FILE")
      n=$((n+1)); printf '%s\n' "$n" > "$NATIVE_COST_ERROR_COUNT_FILE"
      if [ "$n" -eq 3 ]; then printf '%s\n' cost-fixture-error-done >> "$NATIVE_CLI_LOG"; fi
      printf 'synthetic cost scan failure\n' >&2; exit 7
    fi
    if [ -n "${NATIVE_SESSIONS_MODE_FILE:-}" ]; then
      printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{"priced":3,"unpriced":1},"provenance":"synthetic_history","daily":[{"date":"2026-11-09","totalCost":3.25,"totalTokens":800}],"projects":[],"models":[]}]'
    else
      printf '%s\n' '[{"provider":"codex","currencyCode":"USD","totalCost":12.5,"totalTokens":1200,"sessionCostUSD":1.25,"sessionTokens":100,"last30DaysCostUSD":12.5,"last30DaysTokens":1200,"coverage":{"priced":3,"unpriced":1},"provenance":"synthetic_history","daily":[],"projects":[],"models":[]}]'
    fi
    if [ -n "${NATIVE_COST_MODE_FILE:-}" ]; then printf '%s\n' cost-fixture-success-done >> "$NATIVE_CLI_LOG"; fi ;;
  hooks)
    case "${2:-}" in
      disable) printf 'false\n' > "$NATIVE_HOOKS_STATE_FILE" ;;
      enable) printf 'true\n' > "$NATIVE_HOOKS_STATE_FILE" ;;
      list) printf '{"enabled":%s,"events":[]}\n' "$(cat "$NATIVE_HOOKS_STATE_FILE")" ;;
    esac ;;
  sessions)
    mode=$(cat "$NATIVE_SESSIONS_MODE_FILE")
    case "$mode" in
      loading) printf '%s\n' "sessions-fixture-$mode-start" >> "$NATIVE_CLI_LOG"; sleep 15; printf '%s\n' "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '%s\n' '[{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":10,"host":"fixture"}]' ;;
      success) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '%s\n' '[{"id":"fixture-session","provider":"codex","state":"running","projectName":"synthetic","cwd":"/tmp/synthetic","pid":10,"host":"fixture"}]' ;;
      empty) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf '[]\n' ;;
      error) printf '%s\n' "sessions-fixture-$mode-start" "sessions-fixture-$mode-done" >> "$NATIVE_CLI_LOG"; printf 'synthetic session scan failure\n' >&2; exit 7 ;;
    esac ;;
  *) printf '[]\n' ;;
esac
"##;
    fs::write(&cli, cli_script).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&cli, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    }
    let (weston, screenshot, backend, shell, desktop, keyboard) = resolve_private_weston(&scratch)?;
    let bus =
        env::var("DBUS_SESSION_BUS_ADDRESS").map_err(|_| "private session bus unavailable")?;
    let socket = bus
        .strip_prefix("unix:path=")
        .and_then(|rest| rest.split(',').next())
        .ok_or("private D-Bus must use a filesystem socket")?;
    let marker = artifacts.join("private-bus-socket.txt");
    fs::write(&marker, socket).map_err(|e| e.to_string())?;
    set_private_file(&marker)?;
    let mut envs = std::collections::BTreeMap::new();
    envs.insert("HOME".to_string(), home.display().to_string());
    envs.insert("XDG_RUNTIME_DIR".into(), runtime.display().to_string());
    envs.insert(
        "XDG_CONFIG_HOME".into(),
        home.join(".config").display().to_string(),
    );
    envs.insert(
        "XDG_DATA_HOME".into(),
        home.join(".local/share").display().to_string(),
    );
    envs.insert(
        "XDG_CACHE_HOME".into(),
        home.join(".cache").display().to_string(),
    );
    envs.insert(
        "XDG_STATE_HOME".into(),
        home.join(".local/state").display().to_string(),
    );
    envs.insert("XDG_SESSION_TYPE".into(), "wayland".into());
    envs.insert("WAYLAND_DISPLAY".into(), "wayland-private".into());
    envs.insert("DBUS_SESSION_BUS_ADDRESS".into(), bus.clone());
    envs.insert("GDK_BACKEND".into(), "wayland".into());
    envs.insert("GSK_RENDERER".into(), "cairo".into());
    envs.insert("GTK_A11Y".into(), "atspi".into());
    envs.insert("GTK_USE_PORTAL".into(), "0".into());
    envs.insert("CODEXBAR_CLI".into(), cli.display().to_string());
    if full || scenario == "page-state" {
        envs.insert(
            "NATIVE_SESSIONS_MODE_FILE".into(),
            sessions_mode.display().to_string(),
        );
        envs.insert("NATIVE_CLI_LOG".into(), cli_log.display().to_string());
        envs.insert(
            "NATIVE_HOOKS_STATE_FILE".into(),
            hooks_state.display().to_string(),
        );
        envs.insert(
            "NATIVE_COST_MODE_FILE".into(),
            cost_mode.display().to_string(),
        );
        envs.insert(
            "NATIVE_COST_ERROR_COUNT_FILE".into(),
            cost_error_count.display().to_string(),
        );
    }
    envs.insert("PATH".into(), env::var("PATH").unwrap_or_default());
    let config_file = scratch.join("weston.ini");
    fs::write(
        &config_file,
        format!(
            "[shell]\nclient={}\n[input-method]\npath={}\n",
            desktop.display(),
            keyboard.display()
        ),
    )
    .map_err(|e| e.to_string())?;
    let weston_log_path = artifacts.join("weston.log");
    let log = fs::File::create(&weston_log_path).map_err(|e| e.to_string())?;
    set_private_file(&weston_log_path)?;
    let mut west = Command::new(&weston);
    west.args([
        "--backend=headless",
        "--renderer=pixman",
        "--socket=wayland-private",
        "--width=1280",
        "--height=900",
        "--shell=desktop-shell.so",
        "--debug",
    ])
    .arg(format!("--config={}", config_file.display()))
    .arg("--idle-time=0")
    .env_clear();
    for (k, v) in &envs {
        west.env(k, v);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        west.process_group(0);
    }
    let ld_path = format!(
        "{}:{}:{}",
        backend.parent().unwrap_or(Path::new("/usr/lib")).display(),
        backend
            .parent()
            .and_then(Path::parent)
            .unwrap_or(Path::new("/usr/lib"))
            .display(),
        shell
            .parent()
            .unwrap_or(Path::new("/usr/lib/weston"))
            .display()
    );
    envs.insert("LD_LIBRARY_PATH".into(), ld_path.clone());
    west.env("LD_LIBRARY_PATH", ld_path)
        .env(
            "WESTON_DATA_DIR",
            weston
                .parent()
                .and_then(Path::parent)
                .unwrap_or(Path::new("/usr/share"))
                .join("share/weston"),
        )
        .env(
            "WESTON_MODULE_MAP",
            format!(
                "headless-backend.so={};desktop-shell.so={}",
                backend.display(),
                shell.display()
            ),
        )
        .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log));
    let mut compositor =
        OwnedChild::spawn(&mut west).map_err(|e| format!("launch private Weston: {e}"))?;
    let mut app_reaped = false;
    let result=async {
        wait_for_path(&runtime.join("wayland-private"),Duration::from_secs(15)).await?;
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; fs::set_permissions(runtime.join("wayland-private"),fs::Permissions::from_mode(0o600)).map_err(|e|e.to_string())?; }
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; let r=fs::metadata(&runtime).map_err(|e|e.to_string())?.permissions().mode()&0o777;let s=fs::metadata(runtime.join("wayland-private")).map_err(|e|e.to_string())?.permissions().mode()&0o777;if r!=0o700||s!=0o600{return Err(format!("private Wayland permissions invalid: runtime={r:o}, socket={s:o}"))} }
        let info=Command::new("wayland-info").env_clear().envs(&envs).output().map_err(|e|format!("wayland-info: {e}"))?;
        if !info.status.success(){return Err("private wayland-info failed".into())}
        let app_log_path=artifacts.join("native-app.log");
        let app_log=fs::File::create(&app_log_path).map_err(|e|e.to_string())?;
        set_private_file(&app_log_path)?;
        let mut appcmd=Command::new(binary); if scenario == "page-state" { appcmd.args(["--page", "sessions"]); } appcmd.env_clear().envs(&envs).stdout(Stdio::from(app_log.try_clone().map_err(|e|e.to_string())?)).stderr(Stdio::from(app_log));
        #[cfg(unix)] { use std::os::unix::process::CommandExt; appcmd.process_group(0); }
        let mut app=OwnedChild::spawn(&mut appcmd).map_err(|e|format!("start native app: {e}"))?; let pid=app.id();
        let run_result=async {
            wait_for_name(Duration::from_secs(25)).await?;
            if scenario == "page-state" {
                run_page_state(pid, &home, &cli, &envs, &runtime, &screenshot, artifacts).await?;
                return Ok(());
            }
            let before_map: serde_json::Value = serde_json::from_slice(&fs::read(&prefs).map_err(|e|e.to_string())?).map_err(|e|format!("invalid initial preferences: {e}"))?;
            if before_map.get("refreshAllProvidersOnMenuOpen") != Some(&serde_json::Value::Bool(false)) { return Err(format!("synthetic initial Settings state is not false: {before_map}")); }
            gaction(&["dashboard"])?;
            let dashboard=wait_window(pid,"CodexBar GTK — Dashboard",Duration::from_secs(15)).await?;
            let dshot=artifacts.join("dashboard-initial.png"); take_screenshot(&screenshot,&runtime,&envs,&dshot)?;
            gaction(&["settings"])?;
            let settings=wait_window(pid,"CodexBar Settings",Duration::from_secs(15)).await?;
            let (_, _, general_selected)=wait_control(pid,"General", &["page tab","tab"],Duration::from_secs(10)).await?;
            if !general_selected {return Err("Settings General tab is not selected".into())}
            let (control,identity,checked)=wait_control(pid,"Refresh when the panel opens", &["switch","check box"],Duration::from_secs(15)).await?;
            if checked {return Err("seeded Settings switch unexpectedly checked".into())}
            click_atspi(pid,&control,&identity).await?;
            let persisted=wait_pref_true(&prefs,"refreshAllProvidersOnMenuOpen",Duration::from_secs(5)).await?;
            let expected=expected_toggled_map(&before_map,"refreshAllProvidersOnMenuOpen")?;
            if persisted!=expected {return Err(format!("Settings changed unexpected preference-map fields: {persisted}"))}
            let sshot=artifacts.join("settings-after-toggle.png"); take_screenshot(&screenshot,&runtime,&envs,&sshot)?;
            gaction(&["page","'spend'"])?;
            let spend=wait_window(pid,"CodexBar GTK — Usage & Spend",Duration::from_secs(15)).await?;
            gaction(&["spend-range","'7 days'"])?;
            let (range,range_id,pressed)=wait_control(pid,"7 days", &["toggle button"],Duration::from_secs(10)).await?;
            if !pressed {return Err("Spend 7 days control lacks pressed state".into())}
            let pshot=artifacts.join("spend-7-days.png"); take_screenshot(&screenshot,&runtime,&envs,&pshot)?;
            let full_matrix=if full { Some(run_full_matrix(pid,&home,&prefs,&cli,&envs,&runtime,&screenshot,artifacts).await?) } else { None };
            let scenario=if full {"matrix"} else {"matrix-core"};
            let limits=if full {vec!["This synthetic full matrix is not overall UG acceptance; AT-SPI actions do not establish physical Wayland input or KDE parity.","Private Weston does not establish KDE shell placement, portal input, or host compositor parity."]} else {vec!["This named matrix-core slice does not cover Notifications, Hooks, heatmap modes, or Sessions; the legacy Python matrix remains intact.","AT-SPI actions do not establish physical Wayland input or KDE parity."]};
            let record=serde_json::json!({"scenario":scenario,"status":"passed","coverage":"dashboard route; Settings General; full matrix adds four notification preferences, tray, Hooks disable, all Spend ranges, heatmap modes and explicit Daily return, Sessions loading/success/empty/error","source_commit":git_head().unwrap_or_default(),"source_sha256":sha256(Path::new(concat!(env!("CARGO_MANIFEST_DIR"),"/src/main.rs")))?,"binary_sha256":sha256(binary)?,"private_bus":"dbus-run-session","gdk_backend":"wayland","runtime_permissions":"0700","wayland_socket_permissions":"0600","host_session_variables_removed":true,"app_pid":pid,"settings_general":{"selected":true},"settings_control":{"name":control,"identity":identity,"checked_before":false,"checked_after":true,"persisted_full_map":persisted},"dashboard":{"window":dashboard,"capture":"dashboard-initial.png"},"settings":{"window":settings,"capture":"settings-after-toggle.png"},"spend":{"window":spend,"selected_control":range,"identity":range_id,"pressed":pressed,"capture":"spend-7-days.png"},"full_matrix":full_matrix,"limits":limits});
            let out = artifacts.join("evidence.json");
            fs::write(
                &out,
                encode_bounded_json(&record, MAX_MATRIX_EVIDENCE_BYTES)?,
            )
            .map_err(|e| e.to_string())?;
            set_private_file(&out)?;
            Ok(())
        }.await;
        let status=app.terminate().map_err(|e|format!("reap native app: {e}"))?; app_reaped=app.reaped;
        let _intentional_exit_status=status;
        run_result
    }.await;
    let _ = compositor.terminate();
    let weston_reaped = compositor.reaped;
    let _ = fs::remove_dir_all(&scratch);
    if result.is_ok() {
        fs::remove_file(&weston_log_path).map_err(|e| format!("remove private Weston log: {e}"))?;
        fs::remove_file(artifacts.join("native-app.log"))
            .map_err(|e| format!("remove private app log: {e}"))?;
        let p = artifacts.join("evidence.json");
        let mut ev: serde_json::Value =
            serde_json::from_slice(&fs::read(&p).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        ev["cleanup"] = serde_json::json!({"native_app_reaped":app_reaped,"weston_reaped":weston_reaped,"private_home_removed":!scratch.exists(),"private_logs_removed":!weston_log_path.exists() && !artifacts.join("native-app.log").exists()});
        if !cleanup_confirmed(app_reaped, weston_reaped, !scratch.exists()) {
            return Err("private process or HOME cleanup was not verified".into());
        }
        fs::write(
            &p,
            serde_json::to_vec_pretty(&ev).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        set_private_file(&p)?;
    }
    result
}

async fn wait_accessible(
    pid: u32,
    name: &str,
    roles: &[&str],
    actionable: bool,
    expected: Option<bool>,
    duration: Duration,
) -> Result<(String, String, bool), String> {
    wait_accessible_scoped(pid, name, roles, actionable, expected, duration, None).await
}

async fn wait_accessible_scoped(
    pid: u32,
    name: &str,
    roles: &[&str],
    actionable: bool,
    expected: Option<bool>,
    duration: Duration,
    context: Option<&str>,
) -> Result<(String, String, bool), String> {
    let end = Instant::now() + duration;
    let mut last = String::new();
    while Instant::now() < end {
        match find_accessible(pid, name, roles, actionable, context).await {
            Ok(found) if expected.is_none_or(|value| found.2 == value) => return Ok(found),
            Ok(found) => last = format!("state mismatch: {:?}", found.2),
            Err(error) => last = error,
        }
        sleep(Duration::from_millis(120)).await;
    }
    Err(format!(
        "PID {pid} did not expose {name:?} with expected state {expected:?}: {last}"
    ))
}

async fn wait_unique_selected(
    pid: u32,
    controls: &[&str],
    selected: &str,
    context: Option<&str>,
    duration: Duration,
) -> Result<Vec<(String, String, bool)>, String> {
    let mut observed = Vec::with_capacity(controls.len());
    for name in controls {
        let current = wait_accessible_scoped(
            pid,
            name,
            &["toggle button"],
            true,
            Some(*name == selected),
            duration,
            context,
        )
        .await?;
        observed.push(current);
    }
    if observed.iter().filter(|(_, _, pressed)| *pressed).count() != 1 {
        return Err("expected exactly one selected control in the group".into());
    }
    Ok(observed)
}

async fn wait_log_line(
    path: &Path,
    line: &str,
    prior: usize,
    duration: Duration,
) -> Result<usize, String> {
    let end = Instant::now() + duration;
    while Instant::now() < end {
        let lines = fs::read_to_string(path).unwrap_or_default();
        let count = lines.lines().filter(|entry| *entry == line).count();
        if count > prior {
            return Ok(count);
        }
        sleep(Duration::from_millis(80)).await;
    }
    Err(format!("synthetic CLI marker {line:?} was not observed"))
}

async fn wait_named_text(
    pid: u32,
    name: &str,
    duration: Duration,
) -> Result<(String, String, bool), String> {
    let end = Instant::now() + duration;
    let mut last = String::new();
    while Instant::now() < end {
        match find_accessible_matching(
            pid,
            name,
            &["label", "text", "static"],
            false,
            Some("CodexBar GTK — Sessions"),
            false,
        )
        .await
        {
            Ok(found) => return Ok(found),
            Err(error) => last = error,
        }
        sleep(Duration::from_millis(100)).await;
    }
    Err(format!(
        "PID {pid} did not expose visible text containing {name:?}: {last}"
    ))
}

async fn wait_named_text_in_context(
    pid: u32,
    name: &str,
    context: &str,
    duration: Duration,
) -> Result<(String, String, bool), String> {
    let end = Instant::now() + duration;
    let mut last = String::new();
    while Instant::now() < end {
        match find_accessible_matching(
            pid,
            name,
            &["label", "text", "static"],
            false,
            Some(context),
            false,
        )
        .await
        {
            Ok(found) => return Ok(found),
            Err(error) => last = error,
        }
        sleep(Duration::from_millis(100)).await;
    }
    Err(format!(
        "PID {pid} did not expose visible text {name:?} in {context:?}: {last}"
    ))
}

#[allow(clippy::too_many_arguments)]
async fn run_full_matrix(
    pid: u32,
    home: &Path,
    prefs: &Path,
    cli: &Path,
    envs: &std::collections::BTreeMap<String, String>,
    runtime: &Path,
    screenshot: &Path,
    artifacts: &Path,
) -> Result<serde_json::Value, String> {
    let mut actions = Vec::new();
    let notification_keys = [
        (
            "Session quota notifications",
            "sessionQuotaNotificationsEnabled",
        ),
        (
            "Quota warning notifications",
            "quotaWarningNotificationsEnabled",
        ),
        (
            "Limit reset notifications",
            "limitResetNotificationsEnabled",
        ),
        ("Pace warnings", "predictivePaceNotificationsEnabled"),
    ];
    gaction(&["settings"])?;
    wait_window(pid, "CodexBar Settings", Duration::from_secs(10)).await?;
    let (tab, tab_id, _) = wait_accessible(
        pid,
        "Notifications",
        &["page tab", "tab", "button"],
        true,
        None,
        Duration::from_secs(10),
    )
    .await?;
    click_atspi(pid, &tab, &tab_id).await?;
    wait_accessible(
        pid,
        "Notifications",
        &["page tab", "tab", "button"],
        true,
        Some(true),
        Duration::from_secs(5),
    )
    .await?;
    let mut expected: serde_json::Value =
        serde_json::from_slice(&fs::read(prefs).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let mut notification_actions = Vec::new();
    for (label, key) in notification_keys {
        let (control, identity, checked) = wait_accessible_scoped(
            pid,
            label,
            &["switch", "check box"],
            true,
            Some(false),
            Duration::from_secs(10),
            Some("Notifications"),
        )
        .await?;
        click_atspi(pid, &control, &identity).await?;
        let (after_control, after_id, after) = wait_accessible_scoped(
            pid,
            label,
            &["switch", "check box"],
            true,
            Some(true),
            Duration::from_secs(5),
            Some("Notifications"),
        )
        .await?;
        expected = expected_toggled_map(&expected, key)?;
        let persisted: serde_json::Value =
            serde_json::from_slice(&fs::read(prefs).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        if persisted != expected {
            return Err(format!(
                "notification {key} changed unexpected preference map"
            ));
        }
        notification_actions.push(serde_json::json!({"label":label,"key":key,"identity_before":identity,"identity_after":after_id,"visible_checked_before":checked,"visible_checked_after":after,"same_control":control==after_control,"full_preference_map_match":true}));
    }
    actions
        .push(serde_json::json!({"page":"Notifications","controls":notification_actions.clone()}));

    let (menu, menu_id, _) = wait_accessible(
        pid,
        "Menu Bar",
        &["page tab", "tab", "button"],
        true,
        None,
        Duration::from_secs(10),
    )
    .await?;
    click_atspi(pid, &menu, &menu_id).await?;
    wait_accessible(
        pid,
        "Menu Bar",
        &["page tab", "tab", "button"],
        true,
        Some(true),
        Duration::from_secs(5),
    )
    .await?;
    let (tray, tray_id, tray_before) = wait_accessible_scoped(
        pid,
        "Show the tray icon",
        &["switch", "check box"],
        true,
        Some(false),
        Duration::from_secs(10),
        Some("Menu Bar"),
    )
    .await?;
    click_atspi(pid, &tray, &tray_id).await?;
    let (_, tray_after_id, tray_after) = wait_accessible_scoped(
        pid,
        "Show the tray icon",
        &["switch", "check box"],
        true,
        Some(true),
        Duration::from_secs(5),
        Some("Menu Bar"),
    )
    .await?;
    expected = expected_toggled_map(&expected, "showTray")?;
    let persisted: serde_json::Value =
        serde_json::from_slice(&fs::read(prefs).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    if persisted != expected {
        return Err("tray visibility changed unexpected preference map".into());
    }
    actions.push(serde_json::json!({"page":"Menu Bar","control":"Show the tray icon","identity_before":tray_id,"identity_after":tray_after_id,"checked_before":tray_before,"checked_after":tray_after,"full_preference_map_match":true}));

    let (hooks_tab, hooks_tab_id, _) = wait_accessible(
        pid,
        "Hooks",
        &["page tab", "tab", "button"],
        true,
        None,
        Duration::from_secs(10),
    )
    .await?;
    click_atspi(pid, &hooks_tab, &hooks_tab_id).await?;
    wait_accessible(
        pid,
        "Hooks",
        &["page tab", "tab", "button"],
        true,
        Some(true),
        Duration::from_secs(5),
    )
    .await?;
    take_screenshot(
        screenshot,
        runtime,
        envs,
        &artifacts.join("settings-hooks.png"),
    )?;
    let (hooks, hooks_id, hooks_before) = wait_accessible_scoped(
        pid,
        "Enable hooks",
        &["switch", "check box"],
        true,
        Some(true),
        Duration::from_secs(10),
        Some("Hooks"),
    )
    .await?;
    let cli_log = home.join("cli-calls.log");
    let prior = fs::read_to_string(&cli_log)
        .unwrap_or_default()
        .lines()
        .filter(|line| *line == "hooks disable")
        .count();
    click_atspi(pid, &hooks, &hooks_id).await?;
    let (_, hooks_after_id, hooks_after) = wait_accessible_scoped(
        pid,
        "Enable hooks",
        &["switch", "check box"],
        true,
        Some(false),
        Duration::from_secs(10),
        Some("Hooks"),
    )
    .await?;
    let calls = wait_log_line(&cli_log, "hooks disable", prior, Duration::from_secs(10)).await?;
    if calls - prior != 1 {
        return Err(format!(
            "Hooks disable exact CLI call count was {}, expected 1",
            calls - prior
        ));
    }
    let output = Command::new(cli)
        .args(["hooks", "list", "--format", "json"])
        .envs(envs)
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success()
        || serde_json::from_slice::<serde_json::Value>(&output.stdout).ok()
            != Some(serde_json::json!({"enabled":false,"events":[]}))
    {
        return Err("synthetic hooks list postcondition was not disabled".into());
    }
    let after_prefs: serde_json::Value =
        serde_json::from_slice(&fs::read(prefs).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    if after_prefs != expected {
        return Err("Hooks disable modified preferences".into());
    }
    actions.push(serde_json::json!({"page":"Hooks","control":"Enable hooks","identity_before":hooks_id,"identity_after":hooks_after_id,"checked_before":hooks_before,"checked_after":hooks_after,"cli_calls":["hooks disable"],"cli_call_count":calls-prior,"cli_postcondition":{"enabled":false,"events":[]},"preferences_unchanged":true}));

    gaction(&["page", "'spend'"])?;
    let spend_title = "CodexBar GTK — Usage & Spend";
    let spend_window = wait_window(pid, spend_title, Duration::from_secs(10)).await?;
    let mut range_actions = Vec::new();
    let range_names = ["7 days", "30 days", "90 days", "All"];
    for range in range_names {
        gaction(&["spend-range", &format!("'{range}'")])?;
        let observed = wait_unique_selected(
            pid,
            &range_names,
            range,
            Some(spend_title),
            Duration::from_secs(10),
        )
        .await?;
        let (name, identity, pressed) = observed
            .into_iter()
            .find(|(_, live, _)| live.ends_with(&format!(":toggle button:{range}")))
            .ok_or("selected Spend range identity disappeared")?;
        range_actions.push(serde_json::json!({"value":range,"control":name,"identity":identity,"pressed":pressed,"pid":pid,"exactly_one_range_selected":true}));
        if range == "7 days" {
            take_screenshot(
                screenshot,
                runtime,
                envs,
                &artifacts.join("spend-7-days.png"),
            )?;
        }
    }
    actions.push(serde_json::json!({"page":"Spend","window":spend_window,"ranges":range_actions}));
    let mut modes = Vec::new();
    let heatmap_names = ["Daily", "Weekly", "Cumulative"];
    for mode in heatmap_names {
        let (name, identity, pressed) = wait_accessible(
            pid,
            mode,
            &["toggle button"],
            true,
            None,
            Duration::from_secs(10),
        )
        .await?;
        let changed = !pressed;
        if changed {
            click_atspi(pid, &name, &identity).await?;
        }
        let observed = wait_unique_selected(
            pid,
            &heatmap_names,
            mode,
            Some(spend_title),
            Duration::from_secs(10),
        )
        .await?;
        let (_, after_id, after) = observed
            .into_iter()
            .find(|(_, live, _)| live.ends_with(&format!(":toggle button:{mode}")))
            .ok_or("selected heatmap control identity disappeared")?;
        modes.push(serde_json::json!({"mode":mode,"identity":after_id,"pressed":after,"changed_by_action":changed}));
    }
    let (daily, daily_id, daily_before) = wait_accessible(
        pid,
        "Daily",
        &["toggle button"],
        true,
        Some(false),
        Duration::from_secs(5),
    )
    .await?;
    click_atspi(pid, &daily, &daily_id).await?;
    let daily_observed = wait_unique_selected(
        pid,
        &heatmap_names,
        "Daily",
        Some(spend_title),
        Duration::from_secs(10),
    )
    .await?;
    let (_, daily_after_id, daily_after) = daily_observed
        .into_iter()
        .find(|(_, live, _)| live.ends_with(":toggle button:Daily"))
        .ok_or("Daily return control identity disappeared")?;
    modes.push(serde_json::json!({"mode":"Daily","explicit_return":true,"identity_before":daily_id,"identity_after":daily_after_id,"changed":daily_before!=daily_after,"pressed_after":daily_after}));
    if daily_id != daily_after_id || daily_before || !daily_after {
        return Err("explicit Daily return was not observed on the same selected control".into());
    }
    actions.push(serde_json::json!({"page":"Spend","heatmap_modes":modes}));

    gaction(&["page", "'sessions'"])?;
    let sessions_window =
        wait_window(pid, "CodexBar GTK — Sessions", Duration::from_secs(10)).await?;
    let sessions_cases = [
        (
            "loading",
            "Refreshing · showing the last successful result",
            Duration::from_secs(15),
        ),
        (
            "success",
            "1 running of 1 known sessions",
            Duration::from_secs(20),
        ),
        (
            "empty",
            "The last successful scan found no agent sessions.",
            Duration::from_secs(20),
        ),
        (
            "error",
            "Session scan failed · showing the last successful result",
            Duration::from_secs(20),
        ),
    ];
    let mut sessions_results = Vec::new();
    for (mode, status, deadline) in sessions_cases {
        let mode_path = home.join("sessions-mode");
        let tmp = home.join("sessions-mode.tmp");
        fs::write(&tmp, format!("{mode}\n")).map_err(|e| e.to_string())?;
        fs::rename(&tmp, &mode_path).map_err(|e| e.to_string())?;
        let log = fs::read_to_string(&cli_log).unwrap_or_default();
        let before_call = log
            .lines()
            .filter(|line| *line == "sessions --json-v2")
            .count();
        let before_start = log
            .lines()
            .filter(|line| *line == format!("sessions-fixture-{mode}-start"))
            .count();
        gaction(&["refresh"])?;
        wait_log_line(
            &cli_log,
            &format!("sessions-fixture-{mode}-start"),
            before_start,
            Duration::from_secs(10),
        )
        .await?;
        let (_, status_id, _) = wait_named_text(pid, status, deadline).await?;
        if mode == "loading" {
            take_screenshot(
                screenshot,
                runtime,
                envs,
                &artifacts.join("sessions-loading.png"),
            )?;
        }
        let done = format!("sessions-fixture-{mode}-done");
        wait_log_line(&cli_log, &done, 0, Duration::from_secs(25)).await?;
        if mode != "loading" {
            take_screenshot(
                screenshot,
                runtime,
                envs,
                &artifacts.join(format!("sessions-{mode}.png")),
            )?;
        }
        let after = fs::read_to_string(&cli_log).unwrap_or_default();
        let after_call = after
            .lines()
            .filter(|line| *line == "sessions --json-v2")
            .count();
        if after_call - before_call != 1 {
            return Err(format!(
                "Sessions {mode} refresh issued {} CLI calls, expected exactly one",
                after_call - before_call
            ));
        }
        let mut result = serde_json::json!({"mode":mode,"visible_status":status,"accessible_identity":status_id,"pid":pid,"refresh_cli":"sessions --json-v2","refresh_cli_count":after_call-before_call,"fixture_completed":true});
        if mode == "error" {
            let (_, err_id, _) = wait_named_text(
                pid,
                "Existing rows remain available",
                Duration::from_secs(5),
            )
            .await?;
            result["visible_error"] = "Existing rows remain available".into();
            result["visible_error_identity"] = err_id.into();
        }
        sessions_results.push(result);
    }
    actions.push(
        serde_json::json!({"page":"Sessions","window":sessions_window,"states":sessions_results}),
    );
    Ok(
        serde_json::json!({"notifications":notification_actions,"actions":actions,"preferences_after_settings_matrix":expected,"captures":["settings-hooks.png","spend-7-days.png","sessions-loading.png","sessions-success.png","sessions-empty.png","sessions-error.png"],"synthetic_only":true}),
    )
}

#[allow(clippy::too_many_arguments)]
async fn route_visible(
    pid: u32,
    from: &str,
    control_name: &str,
    to: &str,
    screenshot_name: &str,
    screenshot: &Path,
    runtime: &Path,
    envs: &std::collections::BTreeMap<String, String>,
) -> Result<serde_json::Value, String> {
    let (control, identity, _) = wait_accessible_scoped(
        pid,
        control_name,
        &["button", "push button", "toggle button", "page tab", "tab"],
        true,
        None,
        Duration::from_secs(12),
        Some(from),
    )
    .await?;
    click_atspi(pid, &control, &identity).await?;
    let target = wait_window(pid, to, Duration::from_secs(12)).await?;
    take_screenshot(screenshot, runtime, envs, &PathBuf::from(screenshot_name))?;
    let capture = Path::new(screenshot_name)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("capture.png");
    Ok(
        serde_json::json!({"from":from,"control":control_name,"to":to,
        "identity":identity,"target_identity":target,"same_pid":true,
        "action":"AT-SPI AccessibleAction.DoAction","capture":capture}),
    )
}

async fn run_page_state(
    pid: u32,
    home: &Path,
    _cli: &Path,
    envs: &std::collections::BTreeMap<String, String>,
    runtime: &Path,
    screenshot: &Path,
    artifacts: &Path,
) -> Result<(), String> {
    let sessions = "CodexBar GTK — Sessions";
    let spend = "CodexBar GTK — Usage & Spend";
    let dashboard = "CodexBar GTK — Dashboard";
    let settings = "CodexBar Settings";
    let about = "About CodexBar GTK";
    let calls = home.join("cli-calls.log");
    wait_log_line(
        &calls,
        "cost-fixture-success-done",
        0,
        Duration::from_secs(20),
    )
    .await?;
    let mut routes = Vec::new();
    routes.push(
        route_visible(
            pid,
            sessions,
            "Spend",
            spend,
            &artifacts
                .join("page-state-spend-success.png")
                .to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    let (total, total_id, _) = wait_accessible_scoped(
        pid,
        "$12.50 · partial",
        &["label", "text", "static"],
        false,
        None,
        Duration::from_secs(10),
        Some(spend),
    )
    .await?;
    let mode = home.join("cost-mode");
    let count = home.join("cost-error-count");
    fs::write(&mode, "error\n").map_err(|e| e.to_string())?;
    fs::write(&count, "0\n").map_err(|e| e.to_string())?;
    let (refresh, refresh_id, _) = wait_accessible_scoped(
        pid,
        "Refresh",
        &["button", "push button"],
        true,
        None,
        Duration::from_secs(10),
        Some("path-fragment:CodexBar GTK — Usage & Spend/generic[0]:/group[0]:"),
    )
    .await?;
    click_atspi(pid, &refresh, &refresh_id).await?;
    wait_log_line(
        &calls,
        "cost-fixture-error-done",
        0,
        Duration::from_secs(25),
    )
    .await?;
    let attempts = fs::read_to_string(&count)
        .map_err(|e| e.to_string())?
        .trim()
        .parse::<u32>()
        .map_err(|e| e.to_string())?;
    if attempts != 3 {
        return Err(format!(
            "Spend fallback expected three failed CLI attempts, observed {attempts}"
        ));
    }
    let (error, error_id, _) = wait_named_text_in_context(
        pid,
        "The usage refresh returned unreadable data.",
        spend,
        Duration::from_secs(10),
    )
    .await?;
    let (_, retained_id, _) = wait_accessible_scoped(
        pid,
        "$12.50 · partial",
        &["label", "text", "static"],
        false,
        None,
        Duration::from_secs(10),
        Some(spend),
    )
    .await?;
    let (session_cost, session_cost_id, _) = wait_accessible_scoped(
        pid,
        "$1.25 · partial",
        &["label", "text", "static"],
        false,
        None,
        Duration::from_secs(10),
        Some(spend),
    )
    .await?;
    let (tokens, token_id, _) = wait_accessible_scoped(
        pid,
        "1.2K tokens",
        &["label", "text", "static"],
        false,
        None,
        Duration::from_secs(10),
        Some("path-fragment:CodexBar GTK — Usage & Spend/generic[1]:/generic[0]:/generic[0]:/group[0]:/generic[7]"),
    )
    .await?;
    let (coverage, coverage_id, _) = wait_accessible_scoped(
        pid,
        "3 priced · 1 unpriced",
        &["label", "text", "static"],
        false,
        None,
        Duration::from_secs(10),
        Some(spend),
    )
    .await?;
    if !error_id.contains(spend) || !retained_id.contains(spend) {
        return Err(
            "retained Spend error and total did not belong to the same visible Spend window".into(),
        );
    }
    take_screenshot(
        screenshot,
        runtime,
        envs,
        &artifacts.join("page-state-spend-retained-error.png"),
    )?;
    routes.push(
        route_visible(
            pid,
            spend,
            "Sessions",
            sessions,
            &artifacts.join("page-state-sessions.png").to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    routes.push(
        route_visible(
            pid,
            sessions,
            "Dashboard",
            dashboard,
            &artifacts.join("page-state-dashboard.png").to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    routes.push(
        route_visible(
            pid,
            dashboard,
            "Settings",
            settings,
            &artifacts.join("page-state-settings.png").to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    routes.push(
        route_visible(
            pid,
            settings,
            "Return to dashboard",
            dashboard,
            &artifacts
                .join("page-state-dashboard-after-settings.png")
                .to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    routes.push(
        route_visible(
            pid,
            dashboard,
            "About",
            about,
            &artifacts.join("page-state-about.png").to_string_lossy(),
            screenshot,
            runtime,
            envs,
        )
        .await?,
    );
    let evidence = serde_json::json!({"scenario":"page-state","status":"passed","app_pid":pid,
        "routes":routes,"spend_success":{"total":total,"identity":total_id},
        "spend_retained_error":{"error":error,"error_identity":error_id,"retained_total":"$12.50 · partial","retained_identity":retained_id,"session_cost":session_cost,"session_cost_identity":session_cost_id,"tokens":tokens,"tokens_identity":token_id,"coverage":coverage,"coverage_identity":coverage_id,"failed_cli_attempts":attempts,"fixture_completion_marker":"cost-fixture-error-done","same_pid":true},
        "limits":["AT-SPI actions verify visible app controls, not physical input or KDE shell parity.","Private Weston does not establish host compositor or portal parity."]});
    let out = artifacts.join("evidence.json");
    fs::write(
        &out,
        encode_bounded_json(&evidence, MAX_MATRIX_EVIDENCE_BYTES)?,
    )
    .map_err(|e| e.to_string())?;
    set_private_file(&out)?;
    Ok(())
}

fn gaction(args: &[&str]) -> Result<(), String> {
    let output = Command::new("gapplication")
        .arg("action")
        .arg("com.steipete.CodexBarGTK")
        .args(args)
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "GAction {:?} failed: {}",
            args,
            String::from_utf8_lossy(&output.stderr)
        ))
    }
}
fn terminate_owned_group(pid: u32) {
    #[cfg(unix)]
    {
        let group = format!("-{pid}");
        let _ = Command::new("kill").args(["-TERM", &group]).status();
        std::thread::sleep(Duration::from_millis(150));
        let _ = Command::new("kill").args(["-KILL", &group]).status();
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
    }
}
async fn wait_for_name(_duration: Duration) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(25);
    loop {
        let o = Command::new("gdbus")
            .args([
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.NameHasOwner",
                "com.steipete.CodexBarGTK",
            ])
            .output();
        if o.is_ok_and(|r| String::from_utf8_lossy(&r.stdout).contains("true")) {
            return Ok(());
        }
        if Instant::now() > deadline {
            return Err("native app did not acquire its private-bus name".into());
        }
        sleep(Duration::from_millis(100)).await
    }
}
async fn wait_for_path(path: &Path, duration: Duration) -> Result<(), String> {
    let end = Instant::now() + duration;
    while Instant::now() < end {
        if path.exists() {
            return Ok(());
        }
        sleep(Duration::from_millis(50)).await
    }
    Err(format!("timed out waiting for {}", path.display()))
}
async fn wait_window(pid: u32, title: &str, duration: Duration) -> Result<String, String> {
    let end = Instant::now() + duration;
    let mut last_error = String::new();
    while Instant::now() < end {
        match find_accessible(pid, title, WINDOW_ROLES, false, None).await {
            Ok((_, id, _)) => return Ok(id),
            Err(error) => last_error = error,
        }
        sleep(Duration::from_millis(150)).await
    }
    Err(format!(
        "app PID {pid} did not expose window {title:?}; last AT-SPI observation: {last_error}"
    ))
}
async fn wait_control(
    pid: u32,
    name: &str,
    roles: &[&str],
    duration: Duration,
) -> Result<(String, String, bool), String> {
    let end = Instant::now() + duration;
    while Instant::now() < end {
        if let Ok(v) = find_accessible(pid, name, roles, true, None).await {
            return Ok(v);
        }
        sleep(Duration::from_millis(100)).await
    }
    Err(format!(
        "app PID {pid} did not expose unique visible actionable {name:?}"
    ))
}
async fn find_accessible(
    pid: u32,
    name: &str,
    roles: &[&str],
    actionable: bool,
    context: Option<&str>,
) -> Result<(String, String, bool), String> {
    find_accessible_matching(pid, name, roles, actionable, context, true).await
}

async fn find_accessible_matching(
    pid: u32,
    name: &str,
    roles: &[&str],
    actionable: bool,
    context: Option<&str>,
    exact_name: bool,
) -> Result<(String, String, bool), String> {
    let conn = AccessibilityConnection::new()
        .await
        .map_err(|e| e.to_string())?;
    let registry = conn
        .root_accessible_on_registry()
        .await
        .map_err(|e| e.to_string())?;
    let apps = registry.get_children().await.map_err(|e| e.to_string())?;
    let mut q = Vec::new();
    for (i, app) in apps.into_iter().enumerate().take(100) {
        if object_pid(&conn, &app).await.ok() == Some(pid) {
            q.push(Node {
                object: app,
                identity: format!("app[{i}]"),
                depth: 0,
            });
        }
    }
    if q.is_empty() {
        return Err(format!("AT-SPI registry has no root for PID {pid}"));
    }
    let mut found = Vec::new();
    let mut window_candidates = Vec::new();
    let mut seen = 0;
    while let Some(n) = q.pop() {
        if seen >= MAX_NODES || n.depth > MAX_DEPTH {
            break;
        }
        seen += 1;
        if object_pid(&conn, &n.object).await.ok() == Some(pid) {
            let a = proxy(&conn, n.object.clone()).await?;
            let nm = a.name().await.unwrap_or_default();
            let role = a.get_role_name().await.unwrap_or_default();
            let st = state(&conn, &n.object).await.unwrap_or_default();
            if !role.is_empty() || !nm.is_empty() {
                record_window_candidate(&mut window_candidates, &n.identity, &role, &nm);
            }
            if (if exact_name {
                nm == name
            } else {
                nm.contains(name)
            }) && roles.contains(&role.as_str())
                && accessible_context_matches(&n.identity, context)
                && st.contains(State::Showing)
                && st.contains(State::Visible)
                && st.contains(State::Sensitive)
            {
                let action = ActionProxy::builder(conn.connection())
                    .destination(n.object.name_as_str().unwrap_or(""))
                    .map_err(|e| e.to_string())?
                    .path(n.object.path_as_str())
                    .map_err(|e| e.to_string())?
                    .build()
                    .await;
                let has_action = match action {
                    Ok(p) => !p.get_actions().await.unwrap_or_default().is_empty(),
                    Err(_) => false,
                };
                if !actionable || has_action {
                    let object_path = n.object.path_as_str().to_owned();
                    if !found
                        .iter()
                        .any(|row: &(String, String, bool, String)| row.3 == object_path)
                    {
                        found.push((
                            n.identity.clone(),
                            format!("{}:{}:{}:{}", pid, n.identity, role, nm),
                            st.contains(State::Checked)
                                || st.contains(State::Pressed)
                                || st.contains(State::Selected),
                            object_path,
                        ));
                    }
                }
            }
            for i in 0..a
                .child_count()
                .await
                .unwrap_or(0)
                .clamp(0, MAX_CHILDREN as i32)
            {
                if let Ok(c) = a.get_child_at_index(i).await {
                    let parent_name: String = nm.chars().take(160).collect();
                    q.push(Node {
                        object: c,
                        identity: format!("{}/{}[{}]:{}", n.identity, role, i, parent_name),
                        depth: n.depth + 1,
                    });
                }
            }
        }
    }
    if found.len() != 1 {
        return Err(format!(
            "expected one visible actionable AT-SPI node {name:?} for PID {pid}, found {}; matches: {:?}; same-PID accessible sample: {window_candidates:?}",
            found.len(), found.iter().take(8).map(|row| (&row.1, &row.3)).collect::<Vec<_>>(),
        ));
    }
    let (tree_identity, live_identity, active, _object_path) = found.remove(0);
    Ok((tree_identity, live_identity, active))
}
async fn click_atspi(pid: u32, _control: &str, identity: &str) -> Result<(), String> {
    let conn = AccessibilityConnection::new()
        .await
        .map_err(|e| e.to_string())?;
    let registry = conn
        .root_accessible_on_registry()
        .await
        .map_err(|e| e.to_string())?;
    let apps = registry.get_children().await.map_err(|e| e.to_string())?;
    let mut q = Vec::new();
    for (i, app) in apps.into_iter().enumerate().take(100) {
        if object_pid(&conn, &app).await.ok() == Some(pid) {
            q.push(Node {
                object: app,
                identity: format!("app[{i}]"),
                depth: 0,
            })
        }
    }
    let mut found = Vec::new();
    while let Some(n) = q.pop() {
        if n.depth > MAX_DEPTH {
            continue;
        }
        if object_pid(&conn, &n.object).await.ok() == Some(pid) {
            let a = proxy(&conn, n.object.clone()).await?;
            let role = a.get_role_name().await.unwrap_or_default();
            let name = a.name().await.unwrap_or_default();
            if format!("{}:{}:{}:{}", pid, n.identity, role, name) == identity {
                found.push(n.clone())
            }
            for i in 0..a
                .child_count()
                .await
                .unwrap_or(0)
                .clamp(0, MAX_CHILDREN as i32)
            {
                if let Ok(c) = a.get_child_at_index(i).await {
                    let parent_name: String = name.chars().take(160).collect();
                    q.push(Node {
                        object: c,
                        identity: format!("{}/{}[{}]:{}", n.identity, role, i, parent_name),
                        depth: n.depth + 1,
                    })
                }
            }
        }
    }
    if found.len() != 1 {
        return Err(format!("AT-SPI target identity is not unique in PID {pid}"));
    }
    let action = ActionProxy::builder(conn.connection())
        .destination(found[0].object.name_as_str().unwrap_or(""))
        .map_err(|e| e.to_string())?
        .path(found[0].object.path_as_str())
        .map_err(|e| e.to_string())?
        .build()
        .await
        .map_err(|e| e.to_string())?;
    let a = proxy(&conn, found[0].object.clone()).await?;
    let role = a.get_role_name().await.unwrap_or_default();
    let state = state(&conn, &found[0].object).await?;
    let live_identity = format!(
        "{}:{}:{}:{}",
        pid,
        found[0].identity,
        role,
        a.name().await.unwrap_or_default()
    );
    let has_action = !action
        .get_actions()
        .await
        .map_err(|e| e.to_string())?
        .is_empty();
    if !atspi_route_target_guard(
        object_pid(&conn, &found[0].object).await.unwrap_or(0),
        pid,
        &live_identity,
        identity,
        &role,
        state.contains(State::Showing),
        state.contains(State::Visible),
        state.contains(State::Sensitive),
        has_action,
    ) {
        return Err(
            "AT-SPI target identity lost PID, role, visible, sensitive, or action guard".into(),
        );
    }
    if !action.do_action(0).await.map_err(|e| e.to_string())? {
        return Err("AT-SPI DoAction returned false".into());
    }
    Ok(())
}
async fn wait_pref_true(path: &Path, key: &str, d: Duration) -> Result<serde_json::Value, String> {
    let end = Instant::now() + d;
    while Instant::now() < end {
        if let Ok(v) =
            serde_json::from_slice::<serde_json::Value>(&fs::read(path).unwrap_or_default())
        {
            if v.get(key) == Some(&serde_json::Value::Bool(true)) {
                return Ok(v);
            }
        }
        sleep(Duration::from_millis(50)).await
    }
    Err(format!("preference {key} did not persist true"))
}
fn take_screenshot(
    bin: &Path,
    runtime: &Path,
    envs: &std::collections::BTreeMap<String, String>,
    output: &Path,
) -> Result<(), String> {
    let work = output.with_extension("capture");
    fs::create_dir(&work).map_err(|e| e.to_string())?;
    let mut e = envs.clone();
    e.insert("XDG_RUNTIME_DIR".into(), runtime.display().to_string());
    let r = Command::new(bin)
        .current_dir(&work)
        .env_clear()
        .envs(&e)
        .output()
        .map_err(|x| x.to_string())?;
    let png = fs::read_dir(&work)
        .map_err(|x| x.to_string())?
        .filter_map(Result::ok)
        .map(|x| x.path())
        .find(|p| p.extension().is_some_and(|e| e == "png"))
        .ok_or_else(|| {
            format!(
                "Weston capture failed: {}",
                String::from_utf8_lossy(&r.stderr)
            )
        })?;
    if !r.status.success() {
        return Err(format!("Weston screenshot status {}", r.status));
    }
    fs::copy(&png, output).map_err(|x| x.to_string())?;
    set_private_file(output)?;
    let _ = fs::remove_dir_all(work);
    Ok(())
}
fn sha256(path: &Path) -> Result<String, String> {
    let mut f = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut h = Sha256::new();
    let mut b = [0; 65536];
    loop {
        let n = f.read(&mut b).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        h.update(&b[..n])
    }
    Ok(format!("{:x}", h.finalize()))
}
fn git_head() -> Result<String, String> {
    let o = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&o.stdout).trim().into())
}
fn resolve_private_weston(
    root: &Path,
) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf, PathBuf, PathBuf), String> {
    let w = which("weston");
    let ss = which("weston-screenshooter");
    if let (Some(w), Some(ss)) = (w, ss) {
        let dirs = [
            Path::new("/usr/lib/x86_64-linux-gnu"),
            Path::new("/usr/lib/aarch64-linux-gnu"),
            Path::new("/usr/lib"),
        ];
        for d in dirs {
            if let Ok(entries) = fs::read_dir(d) {
                for e in entries.flatten() {
                    let p = e.path().join("headless-backend.so");
                    if p.is_file() {
                        let lib = e.path();
                        let shell = lib.parent().unwrap_or(d).join("weston/desktop-shell.so");
                        let de = PathBuf::from("/usr/libexec/weston-desktop-shell");
                        let ke = PathBuf::from("/usr/libexec/weston-keyboard");
                        if shell.is_file() && de.is_file() && ke.is_file() {
                            return Ok((w, ss, p, shell, de, ke));
                        }
                    }
                }
            }
        }
    }
    let dl = root.join("weston-download");
    let ex = root.join("weston-root");
    fs::create_dir(&dl).map_err(|e| e.to_string())?;
    fs::create_dir(&ex).map_err(|e| e.to_string())?;
    let d = Command::new("apt-get")
        .args(["download", "weston", "libweston-13-0"])
        .current_dir(&dl)
        .output()
        .map_err(|e| format!("rootless Weston download: {e}"))?;
    if !d.status.success() {
        return Err(format!(
            "rootless Weston download failed: {}",
            String::from_utf8_lossy(&d.stderr)
        ));
    }
    for e in fs::read_dir(&dl).map_err(|e| e.to_string())?.flatten() {
        let p = e.path();
        if p.extension().is_some_and(|x| x == "deb") {
            let o = Command::new("dpkg-deb")
                .args(["-x"])
                .arg(p)
                .arg(&ex)
                .output()
                .map_err(|e| e.to_string())?;
            if !o.status.success() {
                return Err("rootless Weston extraction failed".into());
            }
        }
    }
    let lib = fs::read_dir(ex.join("usr/lib"))
        .map_err(|e| e.to_string())?
        .flatten()
        .map(|e| e.path())
        .find(|p| p.to_string_lossy().contains("linux-gnu"))
        .ok_or("Weston package library not found")?;
    if let Some(versioned) = fs::read_dir(&lib)
        .map_err(|e| e.to_string())?
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.file_name()
                .is_some_and(|n| n.to_string_lossy().starts_with("libweston-13.so.0."))
        })
    {
        symlink_if_missing(&lib.join("libweston-13.so.0"), &versioned)?;
    }
    let weston_libdir = lib.join("weston");
    if let Some(versioned) = fs::read_dir(&weston_libdir)
        .map_err(|e| e.to_string())?
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.file_name()
                .is_some_and(|n| n.to_string_lossy().starts_with("libexec_weston.so.0."))
        })
    {
        symlink_if_missing(&weston_libdir.join("libexec_weston.so.0"), &versioned)?;
    }
    let back = lib.join("libweston-13/headless-backend.so");
    let sh = lib.join("weston/desktop-shell.so");
    let w = ex.join("usr/bin/weston");
    let ss = ex.join("usr/bin/weston-screenshooter");
    let de = ex.join("usr/libexec/weston-desktop-shell");
    let ke = ex.join("usr/libexec/weston-keyboard");
    for p in [&back, &sh, &w, &ss, &de, &ke] {
        if !p.is_file() {
            return Err(format!(
                "incomplete rootless Weston extraction: {}",
                p.display()
            ));
        }
    }
    Ok((w, ss, back, sh, de, ke))
}
fn symlink_if_missing(link: &Path, target: &Path) -> Result<(), String> {
    if !link.exists() {
        let relative = target
            .strip_prefix(link.parent().unwrap_or(Path::new(".")))
            .unwrap_or(target);
        #[cfg(unix)]
        std::os::unix::fs::symlink(relative, link).map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn which(name: &str) -> Option<PathBuf> {
    env::var_os("PATH").and_then(|p| {
        env::split_paths(&p)
            .map(|d| d.join(name))
            .find(|p| p.is_file())
    })
}

#[cfg(unix)]
fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    fs::metadata(path)
        .map(|m| m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}
#[cfg(not(unix))]
fn is_executable(path: &Path) -> bool {
    path.is_file()
}
#[cfg(unix)]
fn set_private_dir(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())
}
#[cfg(not(unix))]
fn set_private_dir(_path: &Path) -> Result<(), String> {
    Ok(())
}
#[cfg(unix)]
fn set_private_file(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())
}
#[cfg(not(unix))]
fn set_private_file(_path: &Path) -> Result<(), String> {
    Ok(())
}

async fn chooser(args: &[String]) -> Result<u8, String> {
    if args.len() != 4 {
        return Err(usage());
    }
    let mode = args[0].as_str();
    if !matches!(mode, "read" | "set" | "accept" | "select" | "save") {
        return Err(format!("unknown chooser mode {mode:?}"));
    }
    let pid: u32 = args[1]
        .parse()
        .map_err(|_| "PID must be a positive integer")?;
    if pid == 0 {
        return Err("PID must be a positive integer".into());
    }
    let title = args[2].clone();
    let path = args.get(3).cloned();
    timeout(
        Duration::from_secs(20),
        chooser_inner(mode, pid, &title, path.as_deref()),
    )
    .await
    .map_err(|_| "AT-SPI operation exceeded 20 second deadline".to_string())??;
    Ok(0)
}

#[derive(Clone)]
struct Node {
    object: ObjectRefOwned,
    identity: String,
    depth: usize,
}

async fn proxy<'a>(
    conn: &'a AccessibilityConnection,
    object: ObjectRefOwned,
) -> Result<AccessibleProxy<'a>, String> {
    object
        .into_accessible_proxy(conn.connection())
        .await
        .map_err(|e| e.to_string())
}

async fn object_pid(
    conn: &AccessibilityConnection,
    object: &ObjectRefOwned,
) -> Result<u32, String> {
    let name = object
        .name_as_str()
        .ok_or("AT-SPI object has no bus name")?;
    let dbus = zbus::fdo::DBusProxy::new(conn.connection())
        .await
        .map_err(|e| e.to_string())?;
    let unique: zbus::names::BusName<'_> = name
        .try_into()
        .map_err(|e| format!("invalid AT-SPI bus name: {e}"))?;
    dbus.get_connection_unix_process_id(unique)
        .await
        .map_err(|e| e.to_string())
}

async fn collect_accessible_nodes(
    conn: &AccessibilityConnection,
    root: Node,
) -> Result<Vec<Node>, String> {
    let mut queue = vec![root];
    let mut nodes = Vec::new();
    while let Some(node) = queue.pop() {
        if nodes.len() >= MAX_NODES || node.depth > MAX_DEPTH {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let count = access
            .child_count()
            .await
            .unwrap_or(0)
            .clamp(0, MAX_CHILDREN as i32);
        for index in 0..count {
            if nodes.len() + queue.len() >= MAX_NODES {
                break;
            }
            if let Ok(child) = access.get_child_at_index(index).await {
                queue.push(Node {
                    object: child,
                    identity: format!("{}/{}", node.identity, index),
                    depth: node.depth + 1,
                });
            }
        }
        nodes.push(node);
    }
    Ok(nodes)
}

async fn exact_visible_dialog(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    pid: u32,
    title: &str,
) -> Result<Node, String> {
    let mut dialogs = Vec::new();
    let mut exact_titles = 0;
    for node in nodes {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let role = access.get_role_name().await.unwrap_or_default();
        let name = access.name().await.unwrap_or_default();
        if role == "dialog" && name == title {
            exact_titles += 1;
        } else {
            continue;
        }
        let states = state(conn, &node.object).await?;
        let component = ComponentProxy::builder(conn.connection())
            .destination(node.object.name_as_str().unwrap_or(""))
            .map_err(|e| e.to_string())?
            .path(node.object.path_as_str())
            .map_err(|e| e.to_string())?
            .build()
            .await
            .map_err(|e| e.to_string())?;
        let (_, _, width, height) = component
            .get_extents(CoordType::Screen)
            .await
            .map_err(|e| e.to_string())?;
        if chooser_dialog_guard(
            &ChooserDialogSample {
                pid,
                role: &role,
                title: &name,
                showing: states.contains(State::Showing),
                visible: states.contains(State::Visible),
                sensitive: states.contains(State::Sensitive),
                geometry: [width, height],
            },
            pid,
            title,
        ) {
            dialogs.push(node.clone());
        }
    }
    if exact_titles != 1 || dialogs.len() != 1 {
        return Err(format!(
            "expected one exact visible chooser {title:?} for app PID {pid}; exact titles={}, visible matches={}",
            exact_titles,
            dialogs.len(),
        ));
    }
    Ok(dialogs.remove(0))
}

async fn chooser_inner(
    mode: &str,
    pid: u32,
    title: &str,
    path: Option<&str>,
) -> Result<(), String> {
    let conn = AccessibilityConnection::new()
        .await
        .map_err(|e| format!("AT-SPI unavailable: {e}"))?;
    let registry = conn
        .root_accessible_on_registry()
        .await
        .map_err(|e| e.to_string())?;
    let apps = registry.get_children().await.map_err(|e| e.to_string())?;
    let mut apps_for_pid = Vec::new();
    for object in apps.into_iter().take(100) {
        if object_pid(&conn, &object).await.ok() == Some(pid) {
            apps_for_pid.push(object);
        }
    }
    if apps_for_pid.len() != 1 {
        return Err(format!(
            "expected one AT-SPI application root for PID {pid}; found {}",
            apps_for_pid.len()
        ));
    }
    let app = apps_for_pid.remove(0);
    let root = Node {
        object: app,
        identity: format!("{pid}:app"),
        depth: 0,
    };
    let nodes = collect_accessible_nodes(&conn, root.clone()).await?;
    let _dialog = exact_visible_dialog(&conn, &nodes, pid, title).await?;
    match mode {
        "read" => {
            let fresh_nodes = collect_accessible_nodes(&conn, root.clone()).await?;
            let fresh_dialog = exact_visible_dialog(&conn, &fresh_nodes, pid, title).await?;
            let expected_name = path
                .and_then(|path| Path::new(path).file_name())
                .and_then(|name| name.to_str());
            print_chooser_field_diagnostics(&conn, &fresh_nodes, &fresh_dialog, pid, expected_name)
                .await?;
            let text =
                wait_focused_entry_text(&conn, root.clone(), pid, title, Duration::from_secs(5))
                    .await?;
            println!("ACTUAL_CHOOSER_ENTRY pid={pid} role='text' focused=True text={text:?}");
        }
        "set" => {
            let wanted = path.ok_or("set mode requires PATH")?;
            let deadline = Instant::now() + Duration::from_secs(5);
            let entry = loop {
                let refreshed = collect_accessible_nodes(&conn, root.clone()).await?;
                if let Ok(refreshed_dialog) =
                    exact_visible_dialog(&conn, &refreshed, pid, title).await
                {
                    if let Ok(entry) =
                        focused_entry(&conn, &refreshed, &refreshed_dialog, pid).await
                    {
                        break entry;
                    }
                }
                if Instant::now() >= deadline {
                    return Err("actual chooser has no unique focused EditableText; Ctrl+L must expose the location entry first".into());
                }
                sleep(Duration::from_millis(50)).await;
            };
            let before = read_entry(&conn, &entry).await?;
            let edit = proxy(&conn, entry.object.clone())
                .await?
                .proxies()
                .await
                .map_err(|e| e.to_string())?
                .editable_text()
                .await
                .map_err(|e| e.to_string())?;
            if !edit
                .set_text_contents(wanted)
                .await
                .map_err(|e| e.to_string())?
            {
                return Err("GTK EditableText rejected chooser path".into());
            }
            let deadline = Instant::now() + Duration::from_secs(3);
            loop {
                let current = read_entry(&conn, &entry).await?;
                if current == wanted {
                    break;
                }
                if Instant::now() >= deadline {
                    return Err(format!(
                        "chooser location entry did not retain exact path: {current:?}"
                    ));
                }
                sleep(Duration::from_millis(50)).await;
            }
            sleep(Duration::from_millis(100)).await;
            let settled = read_entry(&conn, &entry).await?;
            println!("ACTUAL_CHOOSER_ENTRY pid={pid} role='text' focused=true before={before:?} exact_path={settled:?}");
            if settled != wanted {
                return Err("chooser location entry changed after GTK settle".into());
            }
        }
        "accept" => {
            let wanted = path.ok_or("accept mode requires PATH")?;
            let basename = Path::new(wanted)
                .file_name()
                .and_then(|p| p.to_str())
                .ok_or("PATH has no UTF-8 filename")?;
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                let refreshed = collect_accessible_nodes(&conn, root.clone()).await?;
                let refreshed_dialog = exact_visible_dialog(&conn, &refreshed, pid, title).await?;
                let rows =
                    exact_rows(&conn, &refreshed, &refreshed_dialog, pid, basename, true).await?;
                let exact_path = match focused_entry(&conn, &refreshed, &refreshed_dialog, pid)
                    .await
                {
                    Ok(entry) => read_entry(&conn, &entry).await.ok().as_deref() == Some(wanted),
                    Err(_) => false,
                };
                if rows.len() == 1 || exact_path {
                    invoke_named_action(&conn, &refreshed, &refreshed_dialog, pid, "Import")
                        .await?;
                    break;
                }
                if Instant::now() >= deadline {
                    return Err(format!("refusing chooser accept: exact synthetic row or editable path required (selected rows: {}, exact_path={exact_path})", rows.len()));
                }
                sleep(Duration::from_millis(50)).await;
            }
        }
        "save" => {
            let wanted = path.ok_or("save mode requires PATH")?;
            if !Path::new(wanted).is_absolute() {
                return Err("chooser target path must be absolute".into());
            }
            let basename = Path::new(wanted)
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or("PATH has no UTF-8 filename")?;
            let deadline = Instant::now() + Duration::from_secs(8);
            loop {
                let refreshed = collect_accessible_nodes(&conn, root.clone()).await?;
                let refreshed_dialog = exact_visible_dialog(&conn, &refreshed, pid, title).await?;
                if let Ok(field) = exact_visible_filename_field(
                    &conn,
                    &refreshed,
                    &refreshed_dialog,
                    pid,
                    basename,
                )
                .await
                {
                    println!(
                        "ACTUAL_CHOOSER_DEFAULT_FILENAME pid={pid} basename={basename:?} identity={}",
                        field.identity
                    );
                    invoke_named_action(&conn, &refreshed, &refreshed_dialog, pid, "Save").await?;
                    break;
                }
                if Instant::now() >= deadline {
                    return Err(format!(
                        "chooser did not expose exact app-owned Save filename {basename:?}"
                    ));
                }
                sleep(Duration::from_millis(50)).await;
            }
            wait_nonempty_file(wanted, Duration::from_secs(5)).await?;
        }
        "select" => {
            return select_file(
                &conn,
                root,
                pid,
                title,
                path.ok_or("select mode requires PATH")?,
            )
            .await
        }
        _ => unreachable!(),
    }
    Ok(())
}

async fn state(
    conn: &AccessibilityConnection,
    object: &ObjectRefOwned,
) -> Result<StateSet, String> {
    proxy(conn, object.clone())
        .await?
        .get_state()
        .await
        .map_err(|e| e.to_string())
}

async fn focused_entry(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
) -> Result<Node, String> {
    let mut found = Vec::new();
    for node in nodes
        .iter()
        .filter(|n| is_within_tree(&n.identity, &dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let role = access.get_role_name().await.unwrap_or_default();
        let s = state(conn, &node.object).await?;
        if matches!(role.as_str(), "text" | "entry")
            && s.contains(State::Focused)
            && s.contains(State::Showing)
            && s.contains(State::Sensitive)
            && access
                .get_interfaces()
                .await
                .map(|i| i.contains(Interface::EditableText) && i.contains(Interface::Text))
                .unwrap_or(false)
        {
            let component = ComponentProxy::builder(conn.connection())
                .destination(node.object.name_as_str().unwrap_or(""))
                .map_err(|e| e.to_string())?
                .path(node.object.path_as_str())
                .map_err(|e| e.to_string())?
                .build()
                .await
                .map_err(|e| e.to_string())?;
            let (_, _, w, h) = component
                .get_extents(CoordType::Screen)
                .await
                .map_err(|e| e.to_string())?;
            if w > 0 && h > 0 {
                found.push(node.clone());
            }
        }
    }
    if found.len() != 1 {
        return Err(format!(
            "expected one visible focused editable entry, found {}",
            found.len()
        ));
    }
    Ok(found.remove(0))
}

async fn read_entry(conn: &AccessibilityConnection, node: &Node) -> Result<String, String> {
    let text = TextProxy::builder(conn.connection())
        .destination(node.object.name_as_str().unwrap_or(""))
        .map_err(|e| e.to_string())?
        .path(node.object.path_as_str())
        .map_err(|e| e.to_string())?
        .build()
        .await
        .map_err(|e| e.to_string())?;
    let count = text
        .character_count()
        .await
        .map_err(|e| e.to_string())?
        .clamp(0, 1_000_000);
    text.get_text(0, count).await.map_err(|e| e.to_string())
}

async fn wait_focused_entry_text(
    conn: &AccessibilityConnection,
    root: Node,
    pid: u32,
    title: &str,
    duration: Duration,
) -> Result<String, String> {
    let deadline = Instant::now() + duration;
    loop {
        let nodes = collect_accessible_nodes(conn, root.clone()).await?;
        if let Ok(dialog) = exact_visible_dialog(conn, &nodes, pid, title).await {
            if let Ok(entry) = focused_entry(conn, &nodes, &dialog, pid).await {
                return read_entry(conn, &entry).await;
            }
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "actual chooser has no unique visible, focused editable entry for app PID {pid}"
            ));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

async fn print_chooser_field_diagnostics(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
    expected_name: Option<&str>,
) -> Result<(), String> {
    let mut scoped_nodes = 0usize;
    let mut field_candidates = 0usize;
    for node in nodes
        .iter()
        .filter(|node| is_within_tree(&node.identity, &dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        scoped_nodes += 1;
        let access = proxy(conn, node.object.clone()).await?;
        let role = access.get_role_name().await.unwrap_or_default();
        let name = access.name().await.unwrap_or_default();
        if !matches!(role.as_str(), "text" | "entry")
            && expected_name.is_none_or(|expected| name != expected)
        {
            continue;
        }
        field_candidates += 1;
        let states = state(conn, &node.object).await?;
        let interfaces = access.get_interfaces().await.unwrap_or_default();
        let has_text = interfaces.contains(Interface::Text);
        let has_editable_text = interfaces.contains(Interface::EditableText);
        let has_component = interfaces.contains(Interface::Component);
        let text = if has_text {
            read_entry(conn, node).await.ok()
        } else {
            None
        };
        let component = ComponentProxy::builder(conn.connection())
            .destination(node.object.name_as_str().unwrap_or(""))
            .ok()
            .and_then(|builder| builder.path(node.object.path_as_str()).ok());
        let component = if let Some(builder) = component {
            builder.build().await.ok()
        } else {
            None
        };
        let nonzero_bounds = if let Some(component) = component {
            component
                .get_extents(CoordType::Screen)
                .await
                .is_ok_and(|(_, _, width, height)| width > 0 && height > 0)
        } else {
            false
        };
        eprintln!(
            "ACTUAL_CHOOSER_EDITABLE_FIELD pid={pid} identity={} role={role:?} name={name:?} focused={} showing={} visible={} sensitive={} text_interface={has_text} editable_text_interface={has_editable_text} component_interface={has_component} nonzero_bounds={nonzero_bounds} text={text:?}",
            node.identity,
            states.contains(State::Focused),
            states.contains(State::Showing),
            states.contains(State::Visible),
            states.contains(State::Sensitive),
        );
    }
    eprintln!(
        "ACTUAL_CHOOSER_FIELD_SCAN pid={pid} tree_nodes={} same_pid_nodes={scoped_nodes} field_candidates={field_candidates} expected_basename={expected_name:?}",
        nodes.len(),
    );
    Ok(())
}

async fn exact_visible_filename_field(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
    basename: &str,
) -> Result<Node, String> {
    let mut matches = Vec::new();
    for node in nodes
        .iter()
        .filter(|node| is_within_tree(&node.identity, &dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        if !matches!(
            access.get_role_name().await.as_deref(),
            Ok("text" | "entry")
        ) {
            continue;
        }
        let states = state(conn, &node.object).await?;
        if !states.contains(State::Showing)
            || !states.contains(State::Visible)
            || !states.contains(State::Sensitive)
            || !access
                .get_interfaces()
                .await
                .map(|interfaces| {
                    interfaces.contains(Interface::EditableText)
                        && interfaces.contains(Interface::Text)
                })
                .unwrap_or(false)
        {
            continue;
        }
        let component = ComponentProxy::builder(conn.connection())
            .destination(node.object.name_as_str().unwrap_or(""))
            .map_err(|e| e.to_string())?
            .path(node.object.path_as_str())
            .map_err(|e| e.to_string())?
            .build()
            .await;
        let Ok(component) = component else {
            continue;
        };
        let extents = component.get_extents(CoordType::Screen).await;
        let Ok((_, _, width, height)) = extents else {
            continue;
        };
        if width > 0 && height > 0 && read_entry(conn, node).await.ok().as_deref() == Some(basename)
        {
            matches.push(node.clone());
        }
    }
    if matches.len() != 1 {
        return Err(format!(
            "expected one visible app-owned editable chooser field with exact default filename {basename:?}; found {}",
            matches.len()
        ));
    }
    Ok(matches.remove(0))
}

async fn invoke_named_action(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
    name: &str,
) -> Result<(), String> {
    let mut found = Vec::new();
    for node in nodes
        .iter()
        .filter(|n| is_within_tree(&n.identity, &dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        if access.name().await.as_deref() != Ok(name)
            || access.get_role_name().await.as_deref() != Ok("push button")
        {
            continue;
        }
        let s = state(conn, &node.object).await?;
        if s.contains(State::Showing) && s.contains(State::Sensitive) {
            found.push(node.clone());
        }
    }
    if found.len() != 1 {
        return Err(format!(
            "expected one visible enabled {name} action, found {}",
            found.len()
        ));
    }
    let node = found.remove(0);
    let actions = ActionProxy::builder(conn.connection())
        .destination(node.object.name_as_str().unwrap_or(""))
        .map_err(|e| e.to_string())?
        .path(node.object.path_as_str())
        .map_err(|e| e.to_string())?
        .build()
        .await
        .map_err(|e| e.to_string())?;
    if actions
        .get_actions()
        .await
        .map_err(|e| e.to_string())?
        .is_empty()
        || !actions.do_action(0).await.map_err(|e| e.to_string())?
    {
        return Err(format!("visible GTK {name} action failed"));
    }
    println!(
        "INVOKED actual GTK chooser {name} action pid={pid} identity={}",
        node.identity
    );
    Ok(())
}

async fn exact_rows(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
    filename: &str,
    require_selected: bool,
) -> Result<Vec<Node>, String> {
    let mut found = Vec::new();
    for row in nodes
        .iter()
        .filter(|n| is_within_tree(&n.identity, &dialog.identity))
    {
        if object_pid(conn, &row.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, row.object.clone()).await?;
        if access.get_role_name().await.as_deref() != Ok("table row") {
            continue;
        }
        let row_state = state(conn, &row.object).await?;
        if !row_state.contains(State::Showing)
            || !row_state.contains(State::Sensitive)
            || (require_selected && !row_state.contains(State::Selected))
        {
            continue;
        }
        let mut exact = false;
        for cell in nodes
            .iter()
            .filter(|n| n.identity.starts_with(&(row.identity.clone() + "/")))
        {
            if object_pid(conn, &cell.object).await.ok() != Some(pid) {
                continue;
            }
            let cell_access = proxy(conn, cell.object.clone()).await?;
            let role = cell_access.get_role_name().await.unwrap_or_default();
            if !matches!(role.as_str(), "label" | "table cell") {
                continue;
            }
            let s = state(conn, &cell.object).await?;
            if !s.contains(State::Showing) || !s.contains(State::Sensitive) {
                continue;
            }
            let name = cell_access.name().await.unwrap_or_default();
            let text = if cell_access
                .get_interfaces()
                .await
                .map(|i| i.contains(Interface::Text))
                .unwrap_or(false)
            {
                let t = TextProxy::builder(conn.connection())
                    .destination(cell.object.name_as_str().unwrap_or(""))
                    .map_err(|e| e.to_string())?
                    .path(cell.object.path_as_str())
                    .map_err(|e| e.to_string())?
                    .build()
                    .await
                    .map_err(|e| e.to_string())?;
                let count = t.character_count().await.unwrap_or(0).clamp(0, 1_000_000);
                t.get_text(0, count).await.unwrap_or_default()
            } else {
                String::new()
            };
            if name == filename || text == filename {
                exact = true;
                break;
            }
        }
        if exact {
            found.push(row.clone());
        }
    }
    let identities: std::collections::HashSet<_> =
        found.iter().map(|n| n.identity.as_str()).collect();
    if identities.len() != found.len() {
        return Ok(Vec::new());
    }
    Ok(found)
}

async fn visit_place(
    conn: &AccessibilityConnection,
    root: &Node,
    pid: u32,
    title: &str,
    place_name: &str,
) -> Result<bool, String> {
    let nodes = collect_accessible_nodes(conn, root.clone()).await?;
    let dialog = exact_visible_dialog(conn, &nodes, pid, title).await?;
    let mut places = Vec::new();
    for node in nodes
        .iter()
        .filter(|node| is_within_tree(&node.identity, &dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let states = state(conn, &node.object).await?;
        if access.get_role_name().await.as_deref() == Ok("list item")
            && access.name().await.as_deref() == Ok(place_name)
            && states.contains(State::Showing)
            && states.contains(State::Visible)
            && states.contains(State::Sensitive)
        {
            places.push(node.clone());
        }
    }
    if places.len() != 1 {
        eprintln!(
            "ACTUAL_CHOOSER_PLACE_MATCH pid={pid} name={place_name:?} exact_visible_matches={}",
            places.len()
        );
        return Ok(false);
    }
    let place = places.remove(0);
    let mut parent_identity = place.identity.clone();
    let mut selected = false;
    while let Some(index) = parent_identity.rfind('/') {
        parent_identity.truncate(index);
        let Some(parent) = nodes.iter().find(|node| node.identity == parent_identity) else {
            continue;
        };
        if object_pid(conn, &parent.object).await.ok() != Some(pid) {
            continue;
        }
        if !proxy(conn, parent.object.clone())
            .await?
            .get_interfaces()
            .await
            .map(|interfaces| interfaces.contains(Interface::Selection))
            .unwrap_or(false)
        {
            continue;
        }
        let selection = SelectionProxy::builder(conn.connection())
            .destination(parent.object.name_as_str().unwrap_or(""))
            .map_err(|e| e.to_string())?
            .path(parent.object.path_as_str())
            .map_err(|e| e.to_string())?
            .build()
            .await
            .map_err(|e| e.to_string())?;
        let index = proxy(conn, place.object.clone())
            .await?
            .get_index_in_parent()
            .await
            .map_err(|e| e.to_string())?;
        selected = index >= 0
            && selection
                .select_child(index)
                .await
                .map_err(|e| e.to_string())?;
        eprintln!(
            "ACTUAL_CHOOSER_PLACE_SELECTION pid={pid} name={place_name:?} identity={} parent_identity={parent_identity:?} child_index={index} result={selected}",
            place.identity
        );
        break;
    }
    if !selected {
        return Ok(false);
    }

    // Selection can replace GTK's file-info rows. Let that update settle and
    // reacquire the exact selected place before inspecting any chooser action.
    // Only the parity panel action is eligible; generic item.visit actions can
    // reach GTK's file-info code with an invalid row and abort the app.
    sleep(Duration::from_millis(50)).await;
    let mut place_action_succeeded = false;
    let refreshed_nodes = collect_accessible_nodes(conn, root.clone()).await?;
    let refreshed_dialog = exact_visible_dialog(conn, &refreshed_nodes, pid, title).await?;
    let mut refreshed_places = Vec::new();
    for node in refreshed_nodes
        .iter()
        .filter(|node| node.identity == place.identity)
        .filter(|node| is_within_tree(&node.identity, &refreshed_dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let states = state(conn, &node.object).await?;
        if access.get_role_name().await.as_deref() == Ok("list item")
            && access.name().await.as_deref() == Ok(place_name)
            && states.contains(State::Showing)
            && states.contains(State::Visible)
            && states.contains(State::Sensitive)
            && states.contains(State::Selected)
        {
            refreshed_places.push(node.clone());
        }
    }
    eprintln!(
        "ACTUAL_CHOOSER_PLACE_REFRESH pid={pid} name={place_name:?} tree_nodes={} exact_identity={} fresh_matches={}",
        refreshed_nodes.len(),
        place.identity,
        refreshed_places.len(),
    );
    if refreshed_places.len() != 1 {
        return Ok(selected);
    }
    let refreshed_place = refreshed_places.remove(0);

    if object_pid(conn, &refreshed_place.object).await.ok() == Some(pid) {
        let place_action = ActionProxy::builder(conn.connection())
            .destination(refreshed_place.object.name_as_str().unwrap_or(""))
            .map_err(|e| e.to_string())?
            .path(refreshed_place.object.path_as_str())
            .map_err(|e| e.to_string())?
            .build()
            .await;
        if let Ok(place_action) = place_action {
            let actions = place_action.get_actions().await.unwrap_or_default();
            eprintln!(
                "ACTUAL_CHOOSER_PLACE_ROW_ACTIONS pid={pid} name={place_name:?} identity={} names={:?}",
                refreshed_place.identity,
                actions.iter().map(|action| action.name.as_str()).collect::<Vec<_>>(),
            );
            if actions.len() == 1 {
                place_action_succeeded =
                    place_action.do_action(0).await.map_err(|e| e.to_string())?;
                eprintln!(
                    "ACTUAL_CHOOSER_PLACE_ROW_ACTION pid={pid} name={place_name:?} identity={} result={place_action_succeeded}",
                    refreshed_place.identity
                );
            }
        }
    }

    let mut action_groups = Vec::new();
    let mut action_node_count = 0usize;
    let mut visit_action_node_count = 0usize;
    for node in refreshed_nodes
        .iter()
        .filter(|node| is_within_tree(&node.identity, &refreshed_dialog.identity))
    {
        if object_pid(conn, &node.object).await.ok() != Some(pid) {
            continue;
        }
        let access = proxy(conn, node.object.clone()).await?;
        let states = state(conn, &node.object).await?;
        if !states.contains(State::Showing)
            || !states.contains(State::Visible)
            || !states.contains(State::Sensitive)
        {
            continue;
        }
        let actions = ActionProxy::builder(conn.connection())
            .destination(node.object.name_as_str().unwrap_or(""))
            .map_err(|e| e.to_string())?
            .path(node.object.path_as_str())
            .map_err(|e| e.to_string())?
            .build()
            .await;
        let Ok(actions) = actions else { continue };
        let names = actions.get_actions().await.unwrap_or_default();
        if !names.is_empty() {
            action_node_count += 1;
        }
        let role = access.get_role_name().await.unwrap_or_default();
        let action_names: Vec<_> = names.iter().map(|action| action.name.clone()).collect();
        let visit_index = chooser_visit_action_index(
            &ChooserActionSample {
                pid,
                within_dialog: true,
                role: &role,
                showing: states.contains(State::Showing),
                visible: states.contains(State::Visible),
                sensitive: states.contains(State::Sensitive),
                action_names: &action_names,
            },
            pid,
        );
        if visit_index.is_some() {
            visit_action_node_count += 1;
            let name = access.name().await.unwrap_or_default();
            eprintln!(
                "ACTUAL_CHOOSER_PLACE_ACTION_CANDIDATE pid={pid} identity={} role={role:?} name={name:?} showing={} visible={} sensitive={} action_names={:?}",
                node.identity,
                states.contains(State::Showing),
                states.contains(State::Visible),
                states.contains(State::Sensitive),
                action_names,
            );
        }
        if let Some(index) = visit_index {
            action_groups.push((node.clone(), index));
        }
    }
    eprintln!(
        "ACTUAL_CHOOSER_PLACE_ACTION_SCAN pid={pid} place={place_name:?} same_pid_visible_action_nodes={action_node_count} item_visit_nodes={visit_action_node_count} unique_item_visit_groups={}",
        action_groups.len()
    );
    if action_groups.len() != 1 {
        return Ok(selected || place_action_succeeded);
    }
    let (group, index) = action_groups.remove(0);
    let action = ActionProxy::builder(conn.connection())
        .destination(group.object.name_as_str().unwrap_or(""))
        .map_err(|e| e.to_string())?
        .path(group.object.path_as_str())
        .map_err(|e| e.to_string())?
        .build()
        .await
        .map_err(|e| e.to_string())?;
    let invoked = action
        .do_action(index as i32)
        .await
        .map_err(|e| e.to_string())?;
    println!(
        "ACTUAL_CHOOSER_PLACE_VISIT pid={pid} name={place_name:?} identity={} result={invoked}",
        refreshed_place.identity
    );
    Ok(invoked || selected || place_action_succeeded)
}

async fn select_file(
    conn: &AccessibilityConnection,
    root: Node,
    pid: u32,
    title: &str,
    path: &str,
) -> Result<(), String> {
    let basename = Path::new(path)
        .file_name()
        .and_then(|p| p.to_str())
        .ok_or("PATH has no UTF-8 filename")?;
    let deadline = Instant::now() + Duration::from_secs(8);
    let mut attempted_places = std::collections::HashSet::new();
    loop {
        let nodes = collect_accessible_nodes(conn, root.clone()).await?;
        let dialog = exact_visible_dialog(conn, &nodes, pid, title).await?;
        let rows = exact_rows(conn, &nodes, &dialog, pid, basename, false).await?;
        if rows.len() == 1 {
            let row = &rows[0];
            let mut parent_identity = row.identity.clone();
            while let Some(index) = parent_identity.rfind('/') {
                parent_identity.truncate(index);
                if let Some(parent) = nodes.iter().find(|node| node.identity == parent_identity) {
                    let parent_access = proxy(conn, parent.object.clone()).await?;
                    if parent_access
                        .get_interfaces()
                        .await
                        .map(|i| i.contains(Interface::Selection))
                        .unwrap_or(false)
                    {
                        let direct_identity = row
                            .identity
                            .split('/')
                            .take(parent_identity.split('/').count() + 1)
                            .collect::<Vec<_>>()
                            .join("/");
                        let direct = nodes
                            .iter()
                            .find(|node| node.identity == direct_identity)
                            .ok_or("selection child identity disappeared")?;
                        let direct_access = proxy(conn, direct.object.clone()).await?;
                        let index = direct_access
                            .get_index_in_parent()
                            .await
                            .map_err(|e| e.to_string())?;
                        let selection = SelectionProxy::builder(conn.connection())
                            .destination(parent.object.name_as_str().unwrap_or(""))
                            .map_err(|e| e.to_string())?
                            .path(parent.object.path_as_str())
                            .map_err(|e| e.to_string())?
                            .build()
                            .await
                            .map_err(|e| e.to_string())?;
                        if index < 0
                            || !selection
                                .select_child(index)
                                .await
                                .map_err(|e| e.to_string())?
                        {
                            return Err("AT-SPI Selection rejected exact filename row".into());
                        }
                        let verify_deadline = Instant::now() + Duration::from_secs(2);
                        loop {
                            let refreshed = collect_accessible_nodes(conn, root.clone()).await?;
                            let refreshed_dialog =
                                exact_visible_dialog(conn, &refreshed, pid, title).await?;
                            let selected = exact_rows(
                                conn,
                                &refreshed,
                                &refreshed_dialog,
                                pid,
                                basename,
                                true,
                            )
                            .await?;
                            if selected.len() == 1 {
                                println!("ACTUAL_CHOOSER_SELECTED_ROW pid={pid} role='table row' filename={basename:?} identity={}", selected[0].identity);
                                return Ok(());
                            }
                            if Instant::now() >= verify_deadline {
                                return Err(format!(
                                    "exact selected filename row did not become uniquely visible after Selection action: {basename:?}"
                                ));
                            }
                            sleep(Duration::from_millis(50)).await;
                        }
                    }
                }
            }
            return Err("exact filename row has no accessible Selection parent".into());
        }
        if rows.len() > 1 {
            return Err(format!(
                "ambiguous exact visible filename rows: {}",
                rows.len()
            ));
        }
        if rows.is_empty() {
            while let Some(place_name) = next_chooser_fallback_place(&attempted_places) {
                attempted_places.insert(place_name);
                if visit_place(conn, &root, pid, title, place_name).await? {
                    println!("ACTUAL_CHOOSER_PLACE_FALLBACK pid={pid} name={place_name:?}");
                    break;
                }
            }
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "no actionable exact filename row for {basename:?} in app PID {pid}"
            ));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

async fn wait_nonempty_file(path: &str, duration: Duration) -> Result<(), String> {
    if !Path::new(path).is_absolute() {
        return Err("chooser target path must be absolute".into());
    }
    let deadline = Instant::now() + duration;
    loop {
        if tokio::fs::metadata(path)
            .await
            .map(|m| m.is_file() && m.len() > 0)
            .unwrap_or(false)
        {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "chooser did not create nonempty synthetic file at {path:?}"
            ));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::{
        accessible_context_matches, atspi_route_target_guard, atspi_target_guard,
        chooser_dialog_guard, chooser_visit_action_index, cleanup_confirmed, encode_bounded_json,
        expected_toggled_map, is_within_tree, next_chooser_fallback_place, record_window_candidate,
        ChooserActionSample, ChooserDialogSample, Command, PrivateRunnerState, WINDOW_ROLES,
    };

    #[test]
    fn chooser_missing_row_fallback_checks_recent_then_home_once_each() {
        let mut attempted = std::collections::HashSet::new();
        assert_eq!(next_chooser_fallback_place(&attempted), Some("Recent"));
        attempted.insert("Recent");
        assert_eq!(
            next_chooser_fallback_place(&attempted),
            Some("Open your personal folder")
        );
        attempted.insert("Open your personal folder");
        assert_eq!(next_chooser_fallback_place(&attempted), None);
    }

    #[test]
    fn chooser_visit_action_requires_one_visible_app_owned_dialog_action() {
        let action_names = vec!["activate".to_owned(), "item.visit".to_owned()];
        let sample = |pid, within_dialog, role, showing, visible, sensitive| ChooserActionSample {
            pid,
            within_dialog,
            role,
            showing,
            visible,
            sensitive,
            action_names: &action_names,
        };
        assert_eq!(
            chooser_visit_action_index(&sample(41, true, "panel", true, true, true), 41),
            Some(1)
        );
        assert_eq!(
            chooser_visit_action_index(&sample(42, true, "panel", true, true, true), 41),
            None
        );
        assert_eq!(
            chooser_visit_action_index(&sample(41, false, "panel", true, true, true), 41),
            None
        );
        assert_eq!(
            chooser_visit_action_index(&sample(41, true, "unknown", true, true, true), 41),
            None
        );
        assert_eq!(
            chooser_visit_action_index(&sample(41, true, "panel", false, true, true), 41),
            None
        );
        assert_eq!(
            chooser_visit_action_index(&sample(41, true, "panel", true, false, true), 41),
            None
        );
        assert_eq!(
            chooser_visit_action_index(&sample(41, true, "panel", true, true, false), 41),
            None
        );
        let duplicate_actions = vec!["item.visit".to_owned(), "item.visit".to_owned()];
        assert_eq!(
            chooser_visit_action_index(
                &ChooserActionSample {
                    pid: 41,
                    within_dialog: true,
                    role: "panel",
                    showing: true,
                    visible: true,
                    sensitive: true,
                    action_names: &duplicate_actions,
                },
                41,
            ),
            None
        );
    }

    #[test]
    fn chooser_dialog_requires_exact_owner_title_visible_state_and_bounds() {
        let exact = |pid, role, title, showing, visible, sensitive, width, height| {
            chooser_dialog_guard(
                &ChooserDialogSample {
                    pid,
                    role,
                    title,
                    showing,
                    visible,
                    sensitive,
                    geometry: [width, height],
                },
                41,
                "Import preferences",
            )
        };
        assert!(exact(
            41,
            "dialog",
            "Import preferences",
            true,
            true,
            true,
            800,
            600
        ));
        assert!(!exact(
            42,
            "dialog",
            "Import preferences",
            true,
            true,
            true,
            800,
            600
        ));
        assert!(!exact(
            41,
            "dialog",
            "Export preferences",
            true,
            true,
            true,
            800,
            600
        ));
        assert!(!exact(
            41,
            "window",
            "Import preferences",
            true,
            true,
            true,
            800,
            600
        ));
        assert!(!exact(
            41,
            "dialog",
            "Import preferences",
            false,
            true,
            true,
            800,
            600
        ));
        assert!(!exact(
            41,
            "dialog",
            "Import preferences",
            true,
            false,
            true,
            800,
            600
        ));
        assert!(!exact(
            41,
            "dialog",
            "Import preferences",
            true,
            true,
            false,
            800,
            600
        ));
        assert!(!exact(
            41,
            "dialog",
            "Import preferences",
            true,
            true,
            true,
            0,
            600
        ));
    }

    #[test]
    fn matrix_route_guard_allows_routes_and_toggles_with_pid_and_visibility_guards() {
        for role in [
            "page tab",
            "tab",
            "button",
            "switch",
            "check box",
            "toggle button",
        ] {
            assert!(atspi_route_target_guard(
                41, 41, "same", "same", role, true, true, true, true
            ));
        }
        assert!(!atspi_route_target_guard(
            42, 41, "same", "same", "button", true, true, true, true
        ));
        assert!(!atspi_route_target_guard(
            41, 41, "same", "same", "button", false, true, true, true
        ));
        assert!(!atspi_route_target_guard(
            41, 41, "same", "same", "label", true, true, true, true
        ));
    }

    #[test]
    fn matrix_runner_uses_private_home_and_xdg_paths_without_host_desktop_variables() {
        let state = PrivateRunnerState::create().unwrap();
        let root = state.root.clone();
        let mut command = Command::new("true");
        command.env("DISPLAY", ":0");
        command.env("DBUS_SESSION_BUS_ADDRESS", "unix:path=/host/session-bus");
        command.env("XDG_CACHE_HOME", "/host/cache");
        state.configure(&mut command);
        let values = command
            .get_envs()
            .filter_map(|(key, value)| {
                value.map(|value| {
                    (
                        key.to_string_lossy().into_owned(),
                        value.to_string_lossy().into_owned(),
                    )
                })
            })
            .collect::<std::collections::HashMap<_, _>>();
        assert_eq!(values["HOME"], state.home.display().to_string());
        assert_eq!(
            values["XDG_RUNTIME_DIR"],
            state.runtime.display().to_string()
        );
        assert_eq!(
            values["XDG_CONFIG_HOME"],
            state.config.display().to_string()
        );
        assert_eq!(values["XDG_DATA_HOME"], state.data.display().to_string());
        assert_eq!(values["XDG_CACHE_HOME"], state.cache.display().to_string());
        for key in ["DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"] {
            assert!(!values.contains_key(key), "unexpected inherited {key}");
        }
        drop(state);
        assert!(!root.exists());
    }

    #[test]
    fn matrix_preference_toggle_preserves_every_other_setting() {
        let original = serde_json::json!({"sessionQuotaNotificationsEnabled":false,"futureKey":"retained","showTray":false});
        let after_notice =
            expected_toggled_map(&original, "sessionQuotaNotificationsEnabled").unwrap();
        assert_eq!(
            after_notice,
            serde_json::json!({"sessionQuotaNotificationsEnabled":true,"futureKey":"retained","showTray":false})
        );
        let after_tray = expected_toggled_map(&after_notice, "showTray").unwrap();
        assert_eq!(after_tray["futureKey"], "retained");
        assert_eq!(after_tray.as_object().unwrap().len(), 3);
    }

    #[test]
    fn matrix_evidence_encoder_enforces_byte_limit() {
        let evidence = serde_json::json!({"synthetic_only":true,"status":"passed"});
        let encoded = encode_bounded_json(&evidence, 128).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&encoded).unwrap(),
            evidence
        );
        assert!(encode_bounded_json(&evidence, 1).is_err());
    }

    #[test]
    fn matrix_accessibility_context_requires_an_ancestor_boundary() {
        let identity = "app[0]/window[1]:Settings/tab panel[0]:Notifications/group[0]:test";
        assert!(accessible_context_matches(identity, Some("Notifications")));
        assert!(!accessible_context_matches(identity, Some("Hooks")));
        assert!(!accessible_context_matches(
            "app[0]/NotificationsExtra/control",
            Some("Notifications")
        ));
        assert!(accessible_context_matches(
            "app[0]/window[1]:CodexBar GTK — Usage & Spend/generic[0]:/group[0]:Refresh",
            Some("path-fragment:CodexBar GTK — Usage & Spend/generic[0]:/group[0]:")
        ));
        assert!(accessible_context_matches(identity, None));
    }

    #[test]
    fn atspi_tree_identity_uses_path_boundaries() {
        assert!(is_within_tree("app/2", "app/2"));
        assert!(is_within_tree("app/2/7", "app/2"));
        assert!(!is_within_tree("app/20/7", "app/2"));
        assert!(!is_within_tree("other/2", "app/2"));
    }

    #[test]
    fn matrix_action_guard_rejects_pid_identity_role_and_visibility_drift() {
        assert!(atspi_target_guard(
            41,
            41,
            "41:app[0]/3:switch:Refresh",
            "41:app[0]/3:switch:Refresh",
            "switch",
            true,
            true,
            true,
            true
        ));
        assert!(!atspi_target_guard(
            42,
            41,
            "41:app[0]/3:switch:Refresh",
            "41:app[0]/3:switch:Refresh",
            "switch",
            true,
            true,
            true,
            true
        ));
        assert!(!atspi_target_guard(
            41,
            41,
            "41:app[0]/4:switch:Refresh",
            "41:app[0]/3:switch:Refresh",
            "switch",
            true,
            true,
            true,
            true
        ));
        assert!(!atspi_target_guard(
            41, 41, "id", "id", "button", true, true, true, true
        ));
        assert!(!atspi_target_guard(
            41, 41, "id", "id", "switch", true, false, true, true
        ));
    }

    #[test]
    fn settings_map_assertion_preserves_every_unrelated_field() {
        let before = serde_json::json!({"refreshAllProvidersOnMenuOpen":false,"showTray":false,"refreshFrequency":"5m","opaquePreference":{"future":true}});
        let expected = expected_toggled_map(&before, "refreshAllProvidersOnMenuOpen").unwrap();
        assert_eq!(
            expected,
            serde_json::json!({"refreshAllProvidersOnMenuOpen":true,"showTray":false,"refreshFrequency":"5m","opaquePreference":{"future":true}})
        );
        let changed = serde_json::json!({"refreshAllProvidersOnMenuOpen":true,"showTray":true,"refreshFrequency":"5m","opaquePreference":{"future":true}});
        assert_ne!(changed, expected);
    }

    #[test]
    fn cleanup_gate_requires_app_weston_and_private_home_removal() {
        assert!(cleanup_confirmed(true, true, true));
        assert!(!cleanup_confirmed(false, true, true));
        assert!(!cleanup_confirmed(true, false, true));
        assert!(!cleanup_confirmed(true, true, false));
    }

    #[test]
    fn window_diagnostics_bound_candidate_count_and_names() {
        let mut candidates = Vec::new();
        let long_name = "x".repeat(200);
        for index in 0..30 {
            record_window_candidate(
                &mut candidates,
                &format!("app[0]/{index}"),
                "window",
                &long_name,
            );
        }
        assert_eq!(candidates.len(), 24);
        assert!(candidates[0].chars().count() < 200);
    }

    #[test]
    fn gtk4_toplevel_role_contract_includes_application_role() {
        assert!(WINDOW_ROLES.contains(&"frame"));
        assert!(WINDOW_ROLES.contains(&"window"));
        assert!(WINDOW_ROLES.contains(&"application"));
        assert!(!WINDOW_ROLES.contains(&"button"));
    }
}
