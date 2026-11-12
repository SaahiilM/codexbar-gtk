#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

for tool in cargo dbus-run-session; do
    command -v "$tool" >/dev/null || {
        echo "missing native tray test dependency: $tool" >&2
        exit 2
    }
done

# The tray protocol tests use Gio on a private session bus. This Rust-only
# target does not build the PyO3 extension or import the Python implementation.
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-1}
exec dbus-run-session -- cargo test \
    --manifest-path "$repo_root/rust-gtk/Cargo.toml" \
    --locked \
    --lib \
    tray::tests \
    -- --nocapture
