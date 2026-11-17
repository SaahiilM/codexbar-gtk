# Native smoke fixtures

`codexbar-smoke-fixtures` provides deterministic fixture operations used by
the native GTK shell smokes. It has no Python dependency and runs before the
private D-Bus session is created:

```sh
./scripts/build-rust-smoke-fixtures.sh
cargo test --locked --manifest-path rust-smoke-fixtures/Cargo.toml
cargo clippy --locked --manifest-path rust-smoke-fixtures/Cargo.toml --all-targets -- -D warnings
```

Commands cover Settings JSON reads and validation, portable preference fixture
generation, synthetic random secret values, a private-bus Notifications mock,
and a loopback `VERSION` server. The GTK and Settings smoke scripts build the
release helper in their outer prepare stage and pass its absolute path through
`CODEXBAR_SMOKE_FIXTURES` before `dbus-run-session` starts. The Settings
chooser remains on the prior Python automation until the peer-owned
`codexbar-ui-test-tool chooser MODE PID TITLE [PATH]` contract is integrated.

## Handoff

- Remaining Python references in the owned smoke scripts are only the Settings
  chooser fallback at `scripts/smoke-native-settings.sh:686`; it runs the
  peer-owned `scripts/select-native-file-chooser.py`. The Settings entrypoint
  prefers `CODEXBAR_UI_TEST_TOOL`, then
  `rust-ui-test-tools/target/debug/codexbar-ui-test-tool`.
- Helper unit/HTTP lifecycle tests and a manual private-bus notification call
  pass. The X11 GTK routing smoke was attempted with Python absent from PATH,
  but the app did not map its initial window and logged `A connection to the
  bus can't be made`; the Settings GUI smoke therefore remains unverified.
- Next: integrate and run the peer chooser tool in the full no-Python Settings
  smoke, then repeat private X11 routing once the isolated startup issue is
  resolved. Root workflow/release/task handoffs remain deferred.
