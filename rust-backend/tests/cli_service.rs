//! Assertion-level parity for the legacy `tests/test_cli_service.py` wrapper
//! cases, using only a synthetic executable and the public Rust service.

#![cfg(unix)]

use std::{
    ffi::OsString,
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

use codexbar_backend::cli::{CliErrorKind, CliService};

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct FixtureDir(PathBuf);

impl FixtureDir {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "codexbar-cli-service-{}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).expect("create isolated fixture directory");
        Self(path)
    }

    fn executable(&self) -> PathBuf {
        let path = self.0.join("fixture-cli");
        fs::write(
            &path,
            r##"#!/bin/sh
set -eu
case "${1-}" in
  --version) printf '%s\n' 'CodexBar 0.82.0' ;;
  usage)
    provider=unset
    all=false
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --provider) provider=$2; shift 2 ;;
        --all-accounts) all=true; shift ;;
        *) shift ;;
      esac
    done
    printf '{"provider":"%s","all":%s,"tz":"%s"}\n' "$provider" "$all" "${TZ-unset}"
    ;;
  cost) printf '%s\n' '[{"provider":"both"}]' ;;
  dashboard) printf '%s\n' '{"fixture":true}' ;;
  sessions) printf '%s\n' '[{"id":"fixture-session"}]' ;;
  config)
    if [ "${2-}" = providers ]; then
      printf '%s\n' 'codex: enabled (OpenAI Codex)' 'claude: disabled (Claude)'
    else
      printf '<%s>\n' "$@"
    fi
    ;;
  hooks)
    if [ "${2-}" = list ]; then
      printf '%s\n' '{"enabled":true,"events":["session-start"]}'
    else
      printf '<%s>\n' "$@"
    fi
    ;;
  plugins) printf '%s\n' '[{"id":"fixture-plugin"}]' ;;
  slow) sleep 2 ;;
  *) printf '%s\n' '[]' ;;
esac
"##,
        )
        .expect("write synthetic CLI fixture");
        let mut permissions = fs::metadata(&path)
            .expect("stat synthetic CLI fixture")
            .permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(&path, permissions).expect("make synthetic CLI executable");
        path
    }
}

impl Drop for FixtureDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn timeout() -> Duration {
    Duration::from_secs(2)
}

#[tokio::test]
async fn python_cli_service_assertions_match_rust_service_contract() {
    let fixture = FixtureDir::new();
    let executable = fixture.executable();
    let service = CliService::new(&executable, Some(OsString::from("Asia/Tokyo")));

    assert_eq!(
        service.version(timeout(), None).await.unwrap(),
        "CodexBar 0.82.0"
    );
    assert_eq!(
        service
            .usage(Some("claude"), None, true, timeout(), None)
            .await
            .unwrap(),
        [serde_json::json!({
            "provider": "claude",
            "all": true,
            "tz": "Asia/Tokyo"
        })]
    );
    assert_eq!(
        service
            .cost(Some("both"), None, timeout(), None)
            .await
            .unwrap(),
        [serde_json::json!({"provider": "both"})]
    );
    assert_eq!(
        service.dashboard(timeout(), None).await.unwrap(),
        serde_json::json!({"fixture": true})
    );
    assert_eq!(
        service.sessions(timeout(), None).await.unwrap(),
        [serde_json::json!({"id": "fixture-session"})]
    );
    assert_eq!(
        service.config_providers(timeout(), None).await.unwrap(),
        [
            codexbar_backend::cli::ProviderStatusEntry {
                provider_id: "codex".into(),
                enabled: true,
                display_name: "OpenAI Codex".into(),
                is_default: false,
            },
            codexbar_backend::cli::ProviderStatusEntry {
                provider_id: "claude".into(),
                enabled: false,
                display_name: "Claude".into(),
                is_default: false,
            },
        ]
    );
    assert_eq!(
        service.hooks(timeout(), None).await.unwrap(),
        serde_json::json!({"enabled": true, "events": ["session-start"]})
    );
    assert_eq!(
        service.plugins(timeout(), None).await.unwrap(),
        [serde_json::json!({"id": "fixture-plugin"})]
    );

    let api_key = service
        .set_api_key(
            "fixture-provider",
            "synthetic value with spaces",
            timeout(),
            None,
        )
        .await
        .unwrap();
    assert_eq!(
        api_key.stdout,
        "<config>\n<set-api-key>\n<--provider>\n<fixture-provider>\n<--api-key>\n<synthetic value with spaces>\n"
    );
    let enabled = service
        .provider_action("enable", "fixture-provider", None, timeout(), None)
        .await
        .unwrap();
    assert_eq!(enabled.returncode, 0);
    let source = service
        .provider_action(
            "set-source",
            "fixture-provider",
            Some("fixture-source"),
            timeout(),
            None,
        )
        .await
        .unwrap();
    assert_eq!(
        source.stdout,
        "<config>\n<set-source>\n<--provider>\n<fixture-provider>\n<--source>\n<fixture-source>\n"
    );

    let error = service
        .run(&[OsString::from("slow")], Duration::from_millis(50), None)
        .await
        .unwrap_err();
    assert_eq!(error.kind, CliErrorKind::Timeout);
}
