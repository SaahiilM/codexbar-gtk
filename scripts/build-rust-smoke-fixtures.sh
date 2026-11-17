#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}" cargo build --locked --release \
    --manifest-path "$repo_root/rust-smoke-fixtures/Cargo.toml"
printf '%s\n' "$repo_root/rust-smoke-fixtures/target/release/codexbar-smoke-fixtures"
