use serde_json::Value;
use std::{
    env, fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process,
};

fn err(message: impl AsRef<str>) -> String {
    message.as_ref().to_owned()
}

fn cargo_artifact(json_path: &Path, target_name: &str) -> Result<PathBuf, String> {
    let input =
        fs::read_to_string(json_path).map_err(|e| err(format!("cannot read Cargo JSON: {e}")))?;
    let mut matches = Vec::new();
    for (index, line) in input.lines().enumerate() {
        let value: Value = serde_json::from_str(line)
            .map_err(|e| err(format!("invalid Cargo JSON on line {}: {e}", index + 1)))?;
        if value.get("reason").and_then(Value::as_str) != Some("compiler-artifact") {
            continue;
        }
        if value
            .get("target")
            .and_then(|v| v.get("name"))
            .and_then(Value::as_str)
            != Some(target_name)
        {
            continue;
        }
        let executable = value
            .get("executable")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| {
                err(format!(
                    "compiler-artifact for target {target_name:?} has no executable"
                ))
            })?;
        matches.push(PathBuf::from(executable));
    }
    if matches.len() != 1 {
        return Err(err(format!(
            "expected exactly one executable artifact named {target_name:?}; found {}",
            matches.len()
        )));
    }
    let artifact = matches.pop().unwrap();
    let metadata = fs::metadata(&artifact).map_err(|_| {
        err(format!(
            "Cargo artifact is missing or not executable: {}",
            artifact.display()
        ))
    })?;
    if !metadata.is_file() || metadata.permissions().mode() & 0o111 == 0 {
        return Err(err(format!(
            "Cargo artifact is missing or not executable: {}",
            artifact.display()
        )));
    }
    Ok(artifact)
}

fn parse_target(file: &Path, key: &str, desktop: bool) -> Result<PathBuf, String> {
    let contents =
        fs::read_to_string(file).map_err(|e| err(format!("cannot read target file: {e}")))?;
    let lines: Vec<_> = contents
        .lines()
        .filter(|line| line.starts_with(&format!("{key}=")))
        .collect();
    if lines.len() != 1 {
        return Err(err(format!(
            "expected exactly one {key} directive; found {}",
            lines.len()
        )));
    }
    let raw = &lines[0][key.len() + 1..];
    let target = if desktop {
        raw.strip_prefix('"').and_then(|s| s.strip_suffix("\" %U"))
    } else {
        raw.strip_prefix('"').and_then(|s| s.strip_suffix('"'))
    };
    let target = target.ok_or_else(|| {
        err(format!(
            "{key} must use the quoted native command-target syntax"
        ))
    })?;
    let path = PathBuf::from(target);
    if !path.is_absolute() {
        return Err(err("command target must be absolute"));
    }
    let metadata = fs::metadata(&path).map_err(|_| {
        err(format!(
            "command target is not executable: {}",
            path.display()
        ))
    })?;
    if !metadata.is_file() || metadata.permissions().mode() & 0o111 == 0 {
        return Err(err(format!(
            "command target is not executable: {}",
            path.display()
        )));
    }
    Ok(path)
}

fn validate_runtime(
    expected_hash: &str,
    actual_hash: &str,
    app_present: bool,
    python_absent: bool,
    install_ok: bool,
) -> Result<(), String> {
    if !install_ok {
        return Err(err("installer failed"));
    }
    if !app_present {
        return Err(err("native runtime is absent"));
    }
    if !python_absent {
        return Err(err("runtime absence proof failed"));
    }
    if expected_hash.is_empty() || expected_hash != actual_hash {
        return Err(err("running executable hash mismatch"));
    }
    Ok(())
}

fn validate_runtime_data(settings: &Path, history: &Path, expected: &Path) -> Result<(), String> {
    let settings: Value =
        serde_json::from_slice(&fs::read(settings).map_err(|e| err(e.to_string()))?)
            .map_err(|e| err(format!("invalid settings JSON: {e}")))?;
    let expected: Value =
        serde_json::from_slice(&fs::read(expected).map_err(|e| err(e.to_string()))?)
            .map_err(|e| err(format!("invalid expected settings JSON: {e}")))?;
    if !settings.is_object() || settings != expected {
        return Err(err("settings changed from seeded values/keys"));
    }
    let text = fs::read_to_string(history).map_err(|e| err(e.to_string()))?;
    let mut records = 0usize;
    let mut seed_found = false;
    for (index, line) in text.lines().enumerate() {
        let row: Value = serde_json::from_str(line)
            .map_err(|e| err(format!("invalid history line {}: {e}", index + 1)))?;
        if !row.is_object() {
            return Err(err(format!("history line {} must be an object", index + 1)));
        }
        let numeric = |key: &str| {
            row.get(key)
                .and_then(Value::as_f64)
                .is_some_and(f64::is_finite)
        };
        if !numeric("t")
            || !numeric("u")
            || row
                .get("p")
                .and_then(Value::as_str)
                .is_none_or(str::is_empty)
            || row
                .get("w")
                .and_then(Value::as_str)
                .is_none_or(str::is_empty)
        {
            return Err(err(format!(
                "history line {} has invalid fields",
                index + 1
            )));
        }
        if row.get("t").and_then(Value::as_f64) == Some(1794009600.0)
            && row.get("p").and_then(Value::as_str) == Some("synthetic")
            && row.get("w").and_then(Value::as_str) == Some("primary")
            && row.get("u").and_then(Value::as_f64) == Some(0.0)
        {
            seed_found = true;
        }
        if row.get("p").and_then(Value::as_str) != Some("synthetic") {
            return Err(err("history contains a non-synthetic provider"));
        }
        records += 1;
    }
    if !seed_found {
        return Err(err("seeded history sample was not semantically preserved"));
    }
    println!("EVIDENCE:runtime-data-semantic-validation=PASS history-records={records}");
    Ok(())
}

fn stop_reap(child: &mut process::Child) -> Result<(), String> {
    use std::{
        thread,
        time::{Duration, Instant},
    };
    let pid = child.id() as libc::pid_t;
    unsafe {
        libc::kill(pid, libc::SIGQUIT);
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        if child.try_wait().map_err(|e| e.to_string())?.is_some() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        if child.try_wait().map_err(|e| e.to_string())?.is_some() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    unsafe {
        libc::kill(pid, libc::SIGKILL);
    }
    child.wait().map(|_| ()).map_err(|e| e.to_string())
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("cargo-artifact") => {
            let (mut json, mut target) = (None, None);
            let mut i = 2;
            while i < args.len() {
                match args[i].as_str() {
                    "--json" if i + 1 < args.len() => {
                        json = Some(PathBuf::from(&args[i + 1]));
                        i += 2;
                    }
                    "--target" if i + 1 < args.len() => {
                        target = Some(args[i + 1].clone());
                        i += 2;
                    }
                    _ => {
                        return Err(err(
                            "usage: codexbar-ci-tool cargo-artifact --json FILE --target NAME",
                        ))
                    }
                }
            }
            let path = cargo_artifact(
                &json.ok_or("missing --json")?,
                &target.ok_or("missing --target")?,
            )?;
            println!("{}", path.display());
            Ok(())
        }
        Some("desktop-target") | Some("service-target") if args.len() == 3 => {
            let desktop = args[1] == "desktop-target";
            let path = parse_target(
                Path::new(&args[2]),
                if desktop { "Exec" } else { "ExecStart" },
                desktop,
            )?;
            println!("{}", path.display());
            Ok(())
        }
        Some("validate-data") if args.len() == 5 => validate_runtime_data(
            Path::new(&args[2]),
            Path::new(&args[3]),
            Path::new(&args[4]),
        ),
        Some("validate-runtime") if args.len() == 7 => validate_runtime(
            &args[2],
            &args[3],
            args[4] == "present",
            args[5] == "absent",
            args[6] == "ok",
        ),
        Some("kill-cleanup") if args.len() >= 4 => {
            let mut child = process::Command::new(&args[2])
                .args(&args[3..])
                .spawn()
                .map_err(|e| e.to_string())?;
            stop_reap(&mut child)
        }
        Some("required-action") if args.len() >= 4 => {
            let label = &args[2];
            let status = process::Command::new(&args[3])
                .args(&args[4..])
                .status()
                .map_err(|e| e.to_string())?;
            if status.success() {
                Ok(())
            } else {
                Err(err(format!("required action failed: {label}")))
            }
        }
        Some("help") | None => {
            println!("codexbar-ci-tool: cargo-artifact, desktop-target, service-target, validate-data, validate-runtime");
            Ok(())
        }
        _ => Err(err("invalid codexbar-ci-tool arguments")),
    }
}

fn main() {
    if let Err(message) = run() {
        eprintln!("codexbar-ci-tool: {message}");
        process::exit(1);
    }
}
