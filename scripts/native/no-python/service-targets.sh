#!/usr/bin/env bash
# Delegate the installer's deliberately narrow rendered activation syntax to
# the Rust CI tool. These only return command targets; they do not claim a
# service manager or desktop environment actually activated the command.
set -euo pipefail
CI_TOOL=${CODEXBAR_CI_TOOL:-/work/ci-tool}

desktop_exec_target() {
  "$CI_TOOL" desktop-target "$1"
}

service_exec_target() {
  "$CI_TOOL" service-target "$1"
}
