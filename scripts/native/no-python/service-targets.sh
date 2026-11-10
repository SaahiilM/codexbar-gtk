#!/usr/bin/env bash
# Parse the installer's deliberately narrow rendered activation syntax.
# These functions return command targets; they do not claim a systemd or
# desktop environment actually activated the command.
set -euo pipefail

desktop_exec_target() {
  local file=$1 line value
  line=$(grep '^Exec=' "$file")
  [[ $(grep -c '^Exec=' "$file") == 1 ]] || return 1
  value=${line#Exec=}
  [[ "$value" == '"'*'" %U' ]] || return 1
  value=${value#\"}
  value=${value%\"\ %U}
  [[ "$value" == /* && -x "$value" ]] || return 1
  printf '%s\n' "$value"
}

service_exec_target() {
  local file=$1 line value
  line=$(grep '^ExecStart=' "$file")
  [[ $(grep -c '^ExecStart=' "$file") == 1 ]] || return 1
  value=${line#ExecStart=}
  [[ "$value" == '"'*'"' ]] || return 1
  value=${value#\"}
  value=${value%\"}
  [[ "$value" == /* && -x "$value" ]] || return 1
  printf '%s\n' "$value"
}
