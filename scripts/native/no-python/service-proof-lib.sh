#!/usr/bin/env bash

run_required_action() {
  local label=$1
  shift
  "$@" || { echo "FAIL: required action failed: $label" >&2; return 1; }
}

stop_reap() {
  local pid=${1:-} _
  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || { wait "$pid" 2>/dev/null || true; return 0; }
  kill -QUIT "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then wait "$pid" 2>/dev/null || true; return 0; fi
    sleep 0.1
  done
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then wait "$pid" 2>/dev/null || true; return 0; fi
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then wait "$pid" 2>/dev/null || true; return 0; fi
    sleep 0.1
  done
  wait "$pid" 2>/dev/null || true
  return 1
}
