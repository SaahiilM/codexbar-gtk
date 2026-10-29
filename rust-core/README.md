# Rust core migration

`rust-core` is the parallel implementation of the application's business logic. Python remains the runtime path until a module has behavior-parity tests and is switched over in a separate integration change.

## Backend-first native application plan

The final destination is a native Rust GTK4/libadwaita app with no Python runtime.
Complete the remaining backend before starting the native UI. PyO3 is temporary;
the six original integrations do not represent a complete backend. Follow the
[architecture and gates](../docs/rust-migration/README.md),
[task checklist/current handoff](../docs/rust-migration/TASKS.md), and
[decision/audit trail](../docs/rust-migration/AUDIT.md). Root
[`AGENTS.md`](../AGENTS.md) defines the continuation and evidence requirements.

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

Current opt-in runtime paths: provider metadata, spend activity helpers, display formatting, monthly allowance pace calculations, quota-history persistence/queries, sparkline geometry, and B01a/B01b timestamp/numeric and `RateWindow`/`Pace`/`CostInfo` primitives are integrated through the PyO3 bridge. The first six original ports are fully runtime-integrated; `data.py` is only partially routed. GTK/Cairo rendering and payload parsing remain in Python. History keeps the existing JSON-lines format; corrupt records are skipped by both backends, and unsupported sample inputs retain the Python path. Build the extension with `scripts/build-rust-core.sh`; Python remains the default, and enabling `CODEXBAR_RUST_CORE=1` fails fast if the extension is missing.
