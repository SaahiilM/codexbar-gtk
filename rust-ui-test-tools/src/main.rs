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
    path::Path,
    process::{Command, ExitCode},
    time::Duration,
};
use tokio::time::{sleep, timeout, Instant};

const MAX_NODES: usize = 10_000;
const MAX_CHILDREN: usize = 4_096;
const MAX_DEPTH: usize = 40;

fn is_within_tree(identity: &str, root: &str) -> bool {
    identity == root
        || identity
            .strip_prefix(root)
            .is_some_and(|suffix| suffix.starts_with('/'))
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
        "isolated-wayland" => isolated_wayland(&args[1..]),
        "settings-wayland" => unavailable_runner("settings-wayland", &args[1..]),
        "spend-wayland" => unavailable_runner("spend-wayland", &args[1..]),
        "update-check-wayland" => unavailable_runner("update-check-wayland", &args[1..]),
        _ => Err(usage()),
    }
}

fn usage() -> String {
    "usage: codexbar-ui-test-tool chooser MODE PID TITLE [PATH] | isolated-wayland --binary PATH [--scenario NAME] [--artifact-dir DIR] | settings-wayland --binary PATH ... | spend-wayland --binary PATH ... | update-check-wayland --binary PATH ...".into()
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

fn isolated_wayland(args: &[String]) -> Result<u8, String> {
    if args.iter().any(|a| a == "--help" || a == "-h") {
        println!("isolated-wayland --binary PATH [--scenario matrix|advanced|settings-residual|page-state|settings-combo-diagnostic] [--artifact-dir DIR]");
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
    if args.len() < 3 || args.len() > 4 {
        return Err(usage());
    }
    let mode = args[0].as_str();
    if !matches!(mode, "read" | "set" | "accept" | "select" | "save") {
        return Err(format!("unknown chooser mode {mode:?}"));
    }
    if mode != "read" && args.len() != 4 {
        return Err("chooser mode requires PATH".into());
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
    let mut app = None;
    for object in apps.into_iter().take(100) {
        if object_pid(&conn, &object).await.ok() == Some(pid) {
            app = Some(object);
            break;
        }
    }
    let app = app.ok_or_else(|| format!("AT-SPI has no application root for PID {pid}"))?;
    let mut queue = vec![Node {
        object: app,
        identity: format!("{pid}:app"),
        depth: 0,
    }];
    let mut nodes = Vec::new();
    while let Some(node) = queue.pop() {
        if nodes.len() >= MAX_NODES || node.depth > MAX_DEPTH {
            continue;
        }
        let access = proxy(&conn, node.object.clone()).await?;
        let count = access
            .child_count()
            .await
            .unwrap_or(0)
            .clamp(0, MAX_CHILDREN as i32);
        for index in 0..count {
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
    let mut dialogs = Vec::new();
    for node in &nodes {
        let access = proxy(&conn, node.object.clone()).await?;
        if access.get_role_name().await.as_deref() == Ok("dialog")
            && access.name().await.as_deref() == Ok(title)
        {
            dialogs.push(node.clone());
        }
    }
    if dialogs.len() != 1 {
        return Err(format!(
            "expected one exact chooser {title:?} for app PID {pid}; found {}",
            dialogs.len()
        ));
    }
    let dialog = dialogs.remove(0);
    match mode {
        "read" => {
            let entry = focused_entry(&conn, &nodes, &dialog, pid).await?;
            let text = read_entry(&conn, &entry).await?;
            println!("ACTUAL_CHOOSER_ENTRY pid={pid} role='text' focused=True text={text:?}");
        }
        "set" => {
            let wanted = path.ok_or("set mode requires PATH")?;
            let deadline = Instant::now() + Duration::from_secs(5);
            let entry = loop {
                if let Ok(entry) = focused_entry(&conn, &nodes, &dialog, pid).await {
                    break entry;
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
            let rows = exact_rows(&conn, &nodes, &dialog, pid, basename, true).await?;
            let exact_path = match focused_entry(&conn, &nodes, &dialog, pid).await {
                Ok(entry) => read_entry(&conn, &entry).await.ok().as_deref() == Some(wanted),
                Err(_) => false,
            };
            if rows.len() != 1 && !exact_path {
                return Err(format!("refusing chooser accept: exact synthetic row or editable path required (selected rows: {}, exact_path={exact_path})", rows.len()));
            }
            invoke_named_action(&conn, &nodes, &dialog, pid, "Import").await?;
        }
        "save" => {
            let wanted = path.ok_or("save mode requires PATH")?;
            invoke_named_action(&conn, &nodes, &dialog, pid, "Save").await?;
            wait_nonempty_file(wanted, Duration::from_secs(5)).await?;
        }
        "select" => {
            return select_file(
                &conn,
                &nodes,
                &dialog,
                pid,
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

async fn select_file(
    conn: &AccessibilityConnection,
    nodes: &[Node],
    dialog: &Node,
    pid: u32,
    path: &str,
) -> Result<(), String> {
    let basename = Path::new(path)
        .file_name()
        .and_then(|p| p.to_str())
        .ok_or("PATH has no UTF-8 filename")?;
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        let rows = exact_rows(conn, nodes, dialog, pid, basename, false).await?;
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
                        println!("ACTUAL_CHOOSER_SELECTED_ROW pid={pid} role='table row' filename={basename:?} identity={}", row.identity);
                        return Ok(());
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
    use super::is_within_tree;

    #[test]
    fn atspi_tree_identity_uses_path_boundaries() {
        assert!(is_within_tree("app/2", "app/2"));
        assert!(is_within_tree("app/2/7", "app/2"));
        assert!(!is_within_tree("app/20/7", "app/2"));
        assert!(!is_within_tree("other/2", "app/2"));
    }
}
