use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::Command,
    time::{Duration, Instant},
};

fn tool() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_codexbar-ci-tool"))
}
fn executable(path: &Path) {
    let mut p = fs::metadata(path).unwrap().permissions();
    p.set_mode(0o755);
    fs::set_permissions(path, p).unwrap();
}

#[test]
fn cargo_json_requires_one_exact_executable_target() {
    let dir = tempfile::tempdir().unwrap();
    let exe = dir.path().join("program");
    fs::write(&exe, "fixture").unwrap();
    executable(&exe);
    let json = dir.path().join("cargo.json");
    fs::write(&json, format!("{{\"reason\":\"build-finished\",\"success\":true}}\n{{\"reason\":\"compiler-artifact\",\"target\":{{\"name\":\"other\"}},\"executable\":\"/missing\"}}\n{{\"reason\":\"compiler-artifact\",\"target\":{{\"name\":\"codexbar_gtk_native\"}},\"executable\":{:?}}}\n", exe.to_string_lossy())).unwrap();
    let out = Command::new(tool())
        .args([
            "cargo-artifact",
            "--json",
            json.to_str().unwrap(),
            "--target",
            "codexbar_gtk_native",
        ])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        exe.to_string_lossy()
    );
    fs::write(&json, "{\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"codexbar_gtk_native\"},\"executable\":\"/missing\"}\n").unwrap();
    assert!(!Command::new(tool())
        .args([
            "cargo-artifact",
            "--json",
            json.to_str().unwrap(),
            "--target",
            "codexbar_gtk_native"
        ])
        .status()
        .unwrap()
        .success());
    fs::write(&json, "not-json\n").unwrap();
    let malformed = Command::new(tool())
        .args([
            "cargo-artifact",
            "--json",
            json.to_str().unwrap(),
            "--target",
            "native",
        ])
        .output()
        .unwrap();
    assert!(!malformed.status.success());
    fs::write(&json, "{\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"native\"},\"executable\":\"/tmp/one\"}\n{\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"native\"},\"executable\":\"/tmp/two\"}\n").unwrap();
    let duplicate = Command::new(tool())
        .args([
            "cargo-artifact",
            "--json",
            json.to_str().unwrap(),
            "--target",
            "native",
        ])
        .output()
        .unwrap();
    assert!(!duplicate.status.success());
}

#[test]
fn command_targets_retain_spaces_and_reject_ambiguous_or_unquoted_entries() {
    let dir = tempfile::tempdir().unwrap();
    let exe = dir.path().join("prefix with spaces/native app");
    fs::create_dir_all(exe.parent().unwrap()).unwrap();
    fs::write(&exe, "fixture").unwrap();
    executable(&exe);
    let desktop = dir.path().join("app.desktop");
    fs::write(
        &desktop,
        format!("[Desktop Entry]\nExec=\"{}\" %U\n", exe.display()),
    )
    .unwrap();
    let out = Command::new(tool())
        .args(["desktop-target", desktop.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(out.status.success());
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        exe.to_string_lossy()
    );
    let service = dir.path().join("app.service");
    fs::write(
        &service,
        format!("[Service]\nExecStart=\"{}\"\n", exe.display()),
    )
    .unwrap();
    let out = Command::new(tool())
        .args(["service-target", service.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        exe.to_string_lossy()
    );
    fs::write(
        &desktop,
        format!(
            "[Desktop Entry]\nExec={} %U\nExec=\"{}\" %U\n",
            exe.display(),
            exe.display()
        ),
    )
    .unwrap();
    assert!(!Command::new(tool())
        .args(["desktop-target", desktop.to_str().unwrap()])
        .status()
        .unwrap()
        .success());
}

#[test]
fn runtime_proof_rejects_wrong_hash_install_failure_and_runtime_absence() {
    for args in [
        [
            "validate-runtime",
            "abc",
            "wrong",
            "present",
            "absent",
            "ok",
        ],
        [
            "validate-runtime",
            "abc",
            "abc",
            "present",
            "absent",
            "failed",
        ],
        ["validate-runtime", "abc", "abc", "missing", "absent", "ok"],
        ["validate-runtime", "abc", "abc", "present", "present", "ok"],
    ] {
        assert!(!Command::new(tool()).args(args).status().unwrap().success());
    }
    assert!(Command::new(tool())
        .args(["validate-runtime", "abc", "abc", "present", "absent", "ok"])
        .status()
        .unwrap()
        .success());
}

#[test]
fn kill_cleanup_reaps_a_child_ignoring_quit_and_term() {
    let start = Instant::now();
    let output = Command::new(tool())
        .args([
            "kill-cleanup",
            "/bin/sh",
            "-c",
            "trap '' QUIT TERM; exec sleep 60",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(start.elapsed() < Duration::from_secs(7));
}

#[test]
fn required_action_reports_subprocess_failure() {
    let output = Command::new(tool())
        .args(["required-action", "install", "/bin/false"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("required action failed: install"));
}

#[test]
fn smoke_rejects_missing_artifact_before_running_docker() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_owned();
    let output = Command::new("bash")
        .arg(root.join("scripts/smoke-native-no-python.sh"))
        .args(["--artifact", "/missing/native"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(3));
    assert!(String::from_utf8_lossy(&output.stderr).contains("artifact not executable"));
}

#[test]
fn smoke_required_docker_unavailable_fails_not_skips() {
    let temp = tempfile::tempdir().unwrap();
    let fake_bin = temp.path().join("bin");
    fs::create_dir(&fake_bin).unwrap();
    let docker = fake_bin.join("docker");
    fs::write(&docker, "#!/bin/sh\nexit 1\n").unwrap();
    executable(&docker);
    let artifact = temp.path().join("native");
    fs::write(&artifact, "synthetic fixture").unwrap();
    executable(&artifact);
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_owned();
    let path = format!(
        "{}:{}",
        fake_bin.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    let output = Command::new("bash")
        .arg(root.join("scripts/smoke-native-no-python.sh"))
        .args([
            "--artifact",
            artifact.to_str().unwrap(),
            "--require-docker",
            "--evidence-dir",
            temp.path().join("evidence").to_str().unwrap(),
        ])
        .env("PATH", path)
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(1),
        "{}",
        String::from_utf8_lossy(&output.stdout)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("required Docker daemon unavailable"));
}

#[test]
fn runtime_data_requires_exact_settings_and_valid_synthetic_history() {
    let dir = tempfile::tempdir().unwrap();
    let settings = dir.path().join("settings.json");
    let expected = dir.path().join("expected.json");
    let history = dir.path().join("history.jsonl");
    fs::write(&settings, "{\"synthetic\":true}").unwrap();
    fs::write(&expected, "{\"synthetic\":true}").unwrap();
    fs::write(
        &history,
        "{\"t\":1794009600.0,\"p\":\"synthetic\",\"w\":\"primary\",\"u\":0.0}\n",
    )
    .unwrap();
    assert!(Command::new(tool())
        .args([
            "validate-data",
            settings.to_str().unwrap(),
            history.to_str().unwrap(),
            expected.to_str().unwrap()
        ])
        .status()
        .unwrap()
        .success());
    fs::write(
        &history,
        "{\"t\":null,\"p\":\"synthetic\",\"w\":\"primary\",\"u\":0.0}\n",
    )
    .unwrap();
    assert!(!Command::new(tool())
        .args([
            "validate-data",
            settings.to_str().unwrap(),
            history.to_str().unwrap(),
            expected.to_str().unwrap()
        ])
        .status()
        .unwrap()
        .success());
}
