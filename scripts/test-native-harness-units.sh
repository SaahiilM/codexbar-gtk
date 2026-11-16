#!/usr/bin/env bash
# Unit tests for the retained Python automation harnesses. These are test tools,
# not part of the native application runtime.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

for pattern in \
  test_native_service_proof.py \
  test_native_service_targets.py \
  test_native_wayland_isolated_harness.py \
  test_no_python_harness.py \
  test_update_check_wayland_harness.py \
  test_wayland_smoke_guard.py \
  test_wayland_spend_guard.py; do
  python3 -m unittest discover -s tests -p "$pattern" -v
done
