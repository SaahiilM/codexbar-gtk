# Rust core

`rust-core` contains shared domain types, deterministic policies, formatting,
history, and provider data used by the native Rust GTK application. The crate
does not depend on Python or PyO3. Historical Python adapters and parity tests
are retained under `tests/reference/python/` and are not shipped or executed by
the native application.

## Local checks

```sh
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo test --manifest-path rust-core/Cargo.toml --locked
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
```

There is no independent Rust-core release version. `VERSION` is the only
project version source. Marketing version follows the supported upstream
CodexBar release; `CURRENT_PROJECT_VERSION` is the build number. Cargo package
metadata is internal crate metadata and does not set the application version.
