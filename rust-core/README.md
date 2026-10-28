# Rust core migration

`rust-core` is the parallel implementation of the application's business logic. Python remains the runtime path until a module has behavior-parity tests and is switched over in a separate integration change.

## Local checks

```sh
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo test --manifest-path rust-core/Cargo.toml --locked
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
```

## Migration sequence

1. Port a self-contained logic module and test edge cases against its Python behavior.
2. Keep the original Python implementation intact while establishing parity.
3. Integrate one service/caller at a time in a follow-up change, with fallback behavior until the Rust path is verified.
4. Remove Python logic only after all callers have migrated and regression tests cover the Rust path.

Current parity port: `codexbar_gtk/format.py` → `src/formatting.rs`. No Python callers have been switched yet.
