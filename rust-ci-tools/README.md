# Native CI tools

`codexbar-ci-tool` replaces interpreter-backed helpers used by native build and
no-Python proofs. It resolves strict Cargo JSON executable artifacts, validates
rendered desktop/service command targets, checks synthetic settings/history
preservation, and validates runtime proof facts. Its tests use Rust integration
fixtures and do not invoke an interpreter.

CI builds this tool on Ubuntu 24.04 before invoking the
[`cargo-artifact` shell wrapper](../scripts/native/no-python/cargo-artifact).
That pins the resolver binary to the same Ubuntu ABI as the runtime proof
container; the binary is not asserted to be portable to arbitrary hosts. Local
smoke scripts build the helper into their evidence work directory and pass the
compiled executable into the isolated container.

```sh
cargo fmt --manifest-path rust-ci-tools/Cargo.toml -- --check
cargo test --manifest-path rust-ci-tools/Cargo.toml --locked
cargo clippy --manifest-path rust-ci-tools/Cargo.toml --all-targets --all-features -- -D warnings

cargo run --manifest-path rust-ci-tools/Cargo.toml --locked -- cargo-artifact --json cargo.json --target codexbar-gtk-native
cargo run --manifest-path rust-ci-tools/Cargo.toml --locked -- desktop-target app.desktop
cargo run --manifest-path rust-ci-tools/Cargo.toml --locked -- service-target app.service
cargo run --manifest-path rust-ci-tools/Cargo.toml --locked -- required-action refresh /bin/true
```

The smoke harnesses build the tool into their evidence work directory before
building/running the network-disabled runtime image. The host binary is copied
into the mounted work directory and its pure validators run without any runtime
or user-session access.
