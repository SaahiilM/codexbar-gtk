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
generation, complete-map assertions for import overlays, empty imports and
reset defaults, synthetic random secret values, a private-bus Notifications
mock, and a loopback `VERSION` server. The GTK and Settings smoke scripts build
the release helper in their outer prepare stage and pass its absolute path
through `CODEXBAR_SMOKE_FIXTURES` before `dbus-run-session` starts. The X11
Settings chooser routes to its private HOME through GTK's visible location
control, checks the complete JSON fixture list, and selects the exact sorted
file row with guarded keyboard navigation. It does not use Python or the
peer-owned GTK UI tool.

## Handoff

- The Settings entrypoint uses private X11 keyboard automation without the
  Python chooser probe or the peer-owned GTK UI tool. The separate historical
  `scripts/select-native-file-chooser.py` file remains untouched and is not
  called by this smoke.
- Two fresh-HOME full Settings smokes passed with Python absent from PATH and
  non-loopback IPv4/IPv6 socket operations blocked. GTK selected the exact
  valid and empty fixture rows; complete-map import/empty/reset assertions,
  provider and Hooks toggles, and the existing Settings actions passed.
- The local `CARGO_TARGET_DIR` override keeps smoke builds separate from other
  checkouts. No workflow, release metadata, or UI runtime source was changed.
