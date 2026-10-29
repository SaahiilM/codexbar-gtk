# Rust core migration

`rust-core` is the parallel implementation of the application's business logic. Python remains the runtime path until a module has behavior-parity tests and is switched over in a separate integration change.

## Local checks

```sh
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo test --manifest-path rust-core/Cargo.toml --locked
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
./scripts/build-rust-core.sh
python3 -m unittest discover -s tests -v
```

## Migration sequence

1. Port a self-contained logic module and test edge cases against its Python behavior.
2. Keep the original Python implementation intact while establishing parity.
3. Integrate one service/caller at a time in a follow-up change, with fallback behavior until the Rust path is verified.
4. Remove Python logic only after all callers have migrated and regression tests cover the Rust path.

## Versioning

There is no separate Rust-core release version. Cargo's required package version is internal crate metadata and is not bumped per PR. Each merged project PR increments the GTK build number in the root `VERSION` file and `codexbar_gtk/version.py`; keep both in sync and record the build in the root `CHANGELOG.md`. `MARKETING_VERSION` continues to track the upstream CodexBar release and only changes when the supported upstream version changes.

Current ports: formatting, monthly pace, and quota history remain parallel Rust implementations. Provider metadata and spend activity helpers are integrated behind the opt-in `CODEXBAR_RUST_CORE=1` backend. Build the PyO3 extension with `scripts/build-rust-core.sh`; Python remains the default, and enabling the flag fails fast if the extension is missing.
