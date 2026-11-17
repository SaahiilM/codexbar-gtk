#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
target_dir=${CARGO_TARGET_DIR:-"$repo_root/rust-smoke-fixtures/target"}
mkdir -p "$target_dir"
target_dir=$(cd "$target_dir" && pwd)
CARGO_TARGET_DIR="$target_dir" CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}" cargo build --locked --release \
    --manifest-path "$repo_root/rust-smoke-fixtures/Cargo.toml"
printf '%s\n' "$target_dir/release/codexbar-smoke-fixtures"
