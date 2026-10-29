#!/usr/bin/env bash
# Build the optional PyO3 extension used to exercise Rust-backed business logic.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v cargo >/dev/null 2>&1 && [[ -f "${HOME}/.cargo/env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.cargo/env"
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust is not installed. Install rustup, then rerun this script." >&2
  exit 1
fi

cargo build --release --locked --manifest-path "${ROOT}/rust-python/Cargo.toml"
LIBRARY="${ROOT}/rust-python/target/release/lib_rust_core.so"
if [[ ! -f "${LIBRARY}" ]]; then
  echo "Expected PyO3 library was not produced: ${LIBRARY}" >&2
  exit 1
fi
cp "${LIBRARY}" "${ROOT}/codexbar_gtk/_rust_core.so"
echo "Built optional extension: ${ROOT}/codexbar_gtk/_rust_core.so"
echo "Run with CODEXBAR_RUST_CORE=1 ./run.sh to use Rust-backed logic."
