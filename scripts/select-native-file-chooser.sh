#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
tool="${CODEXBAR_UI_TEST_TOOL:-$root/rust-ui-test-tools/target/debug/codexbar-ui-test-tool}"
if [[ ! -x "$tool" ]]; then
  echo "native UI test tool missing: $tool (build rust-ui-test-tools first)" >&2
  exit 127
fi
exec "$tool" chooser "$@"
