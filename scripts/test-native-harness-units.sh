#!/usr/bin/env bash
# Unit tests for the retained Python automation harnesses. These are test tools,
# not part of the native application runtime.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

shopt -s nullglob
modules=(tests/test_*.py)
if ((${#modules[@]} == 0)); then
  echo "No active native harness unit modules found under tests/" >&2
  exit 1
fi

# Discover every active top-level unit module. Python application/parity tests
# live below tests/reference/python/ and are intentionally outside this search.
for module in "${modules[@]}"; do
  pattern="${module##*/}"
  python3 -m unittest discover -s tests -p "$pattern" -v
done
