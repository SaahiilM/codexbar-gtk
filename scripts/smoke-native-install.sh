#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
INSTALLER="$ROOT/scripts/install-native.sh"

# Parent wrapper retains control of XDG runtime + private session exit.
# Use the SAME isolated home/runtime paths before bus and app (inner does
# not re-point XDG to different dirs). After dbus-run-session exits the
# parent unmounts ONLY mounts under its own scratch/runtime.
if [[ "${NATIVE_INSTALL_SMOKE_INNER:-}" != "1" ]]; then
  SCRATCH_PRE="$(mktemp -d)"
  chmod 700 "$SCRATCH_PRE"
  mkdir -p "$SCRATCH_PRE/home with spaces/.config" "$SCRATCH_PRE/home with spaces/.local/share" "$SCRATCH_PRE/home with spaces/.cache" "$SCRATCH_PRE/runtime dir"
  chmod 700 "$SCRATCH_PRE/runtime dir"
  cleanup_run_runtime() {
    local rc=$?
    if command -v findmnt >/dev/null 2>&1; then
      while IFS= read -r mounted_path; do
        if command -v fusermount3 >/dev/null 2>&1; then
          fusermount3 -u "$mounted_path" >/dev/null 2>&1 || true
        elif command -v fusermount >/dev/null 2>&1; then
          fusermount -u "$mounted_path" >/dev/null 2>&1 || true
        fi
      done < <(findmnt -rn -o TARGET | awk -v prefix="${SCRATCH_PRE%/}/runtime dir/" 'index($0, prefix) == 1 { print length($0), $0 }' | sort -rn | cut -d' ' -f2-)
    fi
    rm -rf "$SCRATCH_PRE"
    exit "$rc"
  }
  trap cleanup_run_runtime EXIT
  run_status=0
  env NATIVE_INSTALL_SMOKE_SCRATCH="$SCRATCH_PRE" NATIVE_INSTALL_SMOKE_INNER=1 \
    HOME="$SCRATCH_PRE/home with spaces" \
    XDG_RUNTIME_DIR="$SCRATCH_PRE/runtime dir" \
    XDG_CONFIG_HOME="$SCRATCH_PRE/home with spaces/.config" \
    XDG_DATA_HOME="$SCRATCH_PRE/home with spaces/.local/share" \
    XDG_CACHE_HOME="$SCRATCH_PRE/home with spaces/.cache" \
    xvfb-run -a dbus-run-session -- env NATIVE_INSTALL_SMOKE_INNER=1 \
    HOME="$SCRATCH_PRE/home with spaces" \
    XDG_RUNTIME_DIR="$SCRATCH_PRE/runtime dir" \
    XDG_CONFIG_HOME="$SCRATCH_PRE/home with spaces/.config" \
    XDG_DATA_HOME="$SCRATCH_PRE/home with spaces/.local/share" \
    XDG_CACHE_HOME="$SCRATCH_PRE/home with spaces/.cache" \
    "$0" || run_status=$?
  # trap EXIT runs cleanup_run_runtime exactly once; do not call it manually.
  exit "$run_status"
fi

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }
command -v xwininfo >/dev/null 2>&1 || fail "xwininfo is required to verify native launch routes"

"$ROOT/scripts/test-native-activation-renderer.sh"

SCRATCH="${NATIVE_INSTALL_SMOKE_SCRATCH:-$(mktemp -d)}"
chmod 700 "$SCRATCH"
APP_PIDS=""
cleanup() {
  local rc=$?
  for p in $APP_PIDS; do
    if kill -0 "$p" 2>/dev/null; then
      timeout 5 gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
      local d=$((SECONDS + 5))
      while kill -0 "$p" 2>/dev/null && [[ "$SECONDS" -lt "$d" ]]; do sleep 0.1; done
      if kill -0 "$p" 2>/dev/null; then kill -9 "$p" 2>/dev/null || true; fi
      wait "$p" 2>/dev/null || true
    fi
  done
  echo "log dir: $SCRATCH" >&2
  if [[ "$rc" != "0" ]]; then
    echo "app logs in $SCRATCH (app-*.log)" >&2
    echo "END log scp: keep $SCRATCH on failure for inspection" >&2
  fi
  # Inner owns app cleanup only; runtime/docs cleanup is the parent's job
  # after dbus-run-session exits. Never rm the parent scratch here.
  exit "$rc"
}
trap cleanup EXIT INT TERM
# Inner cleanup must not remove the parent runtime (holds FUSE doc mounts
# until dbus-run-session exits); parent does after session teardown.

TEST_HOME="$SCRATCH/home with spaces"
RUNTIME_DIR="$SCRATCH/runtime dir"
PREFIX="$SCRATCH/prefix with spaces"
mkdir -p "$TEST_HOME" "$RUNTIME_DIR" "$PREFIX"
chmod 700 "$RUNTIME_DIR"
export HOME="$TEST_HOME"
export XDG_RUNTIME_DIR="$RUNTIME_DIR"
export XDG_CONFIG_HOME="$TEST_HOME/.config"
export XDG_DATA_HOME="$TEST_HOME/.local/share"
export XDG_CACHE_HOME="$TEST_HOME/.cache"
export GTK_A11Y=none
export GTK_USE_PORTAL=0
export GDK_BACKEND=x11
export GSK_RENDERER=cairo
cat > "$SCRATCH/fake-codexbar" <<'CLI'
#!/bin/sh
case "$1" in
  --version) printf 'CodexBar synthetic fixture 0.82.0\n' ;;
  usage) printf '[]\n' ;;
  *) printf '[]\n' ;;
esac
CLI
chmod 700 "$SCRATCH/fake-codexbar"
export CODEXBAR_CLI="$SCRATCH/fake-codexbar"

DEBUG_BIN="${NATIVE_DEBUG_ARTIFACT:-$ROOT/rust-gtk/target/debug/codexbar-gtk-native}"
RELEASE_BIN="${NATIVE_RELEASE_ARTIFACT:-$ROOT/rust-gtk/target/release/codexbar-gtk-native}"
[[ -x "$DEBUG_BIN" ]] || fail "debug binary missing: $DEBUG_BIN"
[[ -x "$RELEASE_BIN" ]] || fail "release binary missing: $RELEASE_BIN"
DEBUG_SHA="$(sha256sum "$DEBUG_BIN" | awk '{print $1}')"
RELEASE_SHA="$(sha256sum "$RELEASE_BIN" | awk '{print $1}')"
[[ "$DEBUG_SHA" != "$RELEASE_SHA" ]] || fail "identical artifacts"

BIN_DEST="$PREFIX/bin/codexbar-gtk-native"
MANIFEST="$PREFIX/share/codexbar-gtk/native-manifest"

echo "=== 1. byte-preservation through install/uninstall ==="
mkdir -p "$TEST_HOME/.config/codexbar-gtk"
printf '{"launchAtLogin":false,"synthetic":"native-install-smoke"}\n' > "$TEST_HOME/.config/codexbar-gtk/settings.json"
printf '{"ts":1700000000,"provider":"synthetic","usage":0.5}\n' > "$TEST_HOME/.config/codexbar-gtk/history.jsonl"
SET_BEFORE="$(sha256sum "$TEST_HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')"
HIS_BEFORE="$(sha256sum "$TEST_HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')"

echo "=== 2. install debug (no activate), default side-effect check ==="
mkdir -p "$TEST_HOME/.config/systemd/user" "$PREFIX/share/applications"
PY_SVC="$TEST_HOME/.config/systemd/user/codexbar-gtk.service"
PY_DSK="$PREFIX/share/applications/codexbar-gtk.desktop"
printf 'Description=Py\nExecStart=/usr/bin/python3 -m codexbar_gtk\n' > "$PY_SVC"
printf '[Desktop Entry]\nExec=/usr/bin/python3 -m codexbar_gtk\n' > "$PY_DSK"
PY_SVC_SHA="$(sha256sum "$PY_SVC" | awk '{print $1}')"
PY_DSK_SHA="$(sha256sum "$PY_DSK" | awk '{print $1}')"
"$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$PREFIX"
[[ -x "$BIN_DEST" ]] || fail "binary not installed"
[[ "$(sha256sum "$BIN_DEST" | awk '{print $1}')" == "$DEBUG_SHA" ]] || fail "binary sha mismatch"
grep -q "^activated=0$" "$MANIFEST" || fail "default must be activated=0"
[[ ! -e "$PY_DSK.pre-native" ]] || fail "default created desktop backup"
[[ ! -e "$PY_SVC.pre-native" ]] || fail "default created service backup"
[[ "$(sha256sum "$PY_SVC" | awk '{print $1}')" == "$PY_SVC_SHA" ]] || fail "default clobbered service"
[[ "$(sha256sum "$PY_DSK" | awk '{print $1}')" == "$PY_DSK_SHA" ]] || fail "default clobbered desktop"
[[ ! -e "$TEST_HOME/.config/autostart/codexbar-gtk.desktop" ]] || fail "default created autostart"
ok "default install: binary+manifest only"

echo "=== 3. launch probe: NameHasOwner + PID exe/hash ==="
# Type-aware parse of gdbus replies: (uint32 12345,) -> 12345
parse_gdbus_pid() {
  local reply="$1"
  if [[ "$reply" =~ ^\(uint32[[:space:]]+([0-9]+),\)$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  else
    return 1
  fi
}
parse_gdbus_bool() {
  case "$1" in
    '(true,)') printf 'true' ;;
    '(false,)') printf 'false' ;;
    *) return 1 ;;
  esac
}

probe_launch() {
  local expect_sha="$1" label="$2"
  local app_log="$SCRATCH/app-${label}.log"
  local t0=$SECONDS
  CODEXBAR_NATIVE_BINARY="$BIN_DEST" "$ROOT/run.sh" "$@" > "$app_log" 2>&1 &
  local pid=$!
  APP_PIDS="$APP_PIDS $pid"
  echo "[$label] t=0s launched pid=$pid" >&2
  local owned=""
  local owned_err=""
  local deadline=$((t0 + 10))
  while [[ "$SECONDS" -lt "$deadline" ]]; do
    owned_err="$(timeout 5 gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK 2>&1 || true)"
    owned="$owned_err"
    local elapsed=$((SECONDS - t0))
    echo "[$label] t=${elapsed}s alive=$(kill -0 "$pid" 2>/dev/null && echo yes || echo no) NameHasOwner: $owned" >&2
    [[ "$(parse_gdbus_bool "$owned")" == "true" ]] && break
    sleep 0.2
    kill -0 "$pid" 2>/dev/null || break
  done
  if [[ "$(parse_gdbus_bool "$owned")" != "true" ]]; then
    echo "--- app log ($label) ---" >&2; cat "$app_log" >&2 || true
    echo "--- gdbus error ($label) ---" >&2; echo "$owned_err" >&2
    for tid in /proc/$pid/task/*/; do
      echo "thread $(basename "$tid"): state=$(cat "$tid/status" 2>/dev/null | grep '^State' || echo '?') wchan=$(cat "$tid/wchan" 2>/dev/null || echo '?')" >&2
    done || true
    # If still alive, dump wchan/syscall if available (read-only).
    if kill -0 "$pid" 2>/dev/null; then
      echo "--- /proc/$pid/stack (read-only) ---" >&2; cat /proc/$pid/stack 2>&1 | head -20 >&2 || true
      echo "--- /proc/$pid/syscall ---" >&2; cat /proc/$pid/syscall 2>&1 | head -5 >&2 || true
    fi
    timeout 5 gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
    local d=$((SECONDS + 5))
    while kill -0 "$pid" 2>/dev/null && [[ "$SECONDS" -lt "$d" ]]; do sleep 0.1; done
    if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi
    wait "$pid" 2>/dev/null || true
    APP_PIDS="$(tr " " '\n' <<<"$APP_PIDS" | grep -vx "$pid" | tr '\n' ' ' || true)"
    fail "NameHasOwner failed after 10s ($label); log: $app_log"
  fi
  local expected_window=""
  case " $* " in
    *" --settings "*) expected_window="CodexBar Settings" ;;
    *" --about "*) expected_window="About CodexBar GTK" ;;
  esac
  if [[ -n "$expected_window" ]]; then
    local window_tree="" window_deadline=$((SECONDS + 10))
    while [[ "$SECONDS" -lt "$window_deadline" ]]; do
      window_tree="$(xwininfo -root -tree 2>/dev/null || true)"
      grep -Fq "\"$expected_window\"" <<<"$window_tree" && break
      sleep 0.1
    done
    grep -Fq "\"$expected_window\"" <<<"$window_tree" || {
      echo "--- window tree ($label) ---" >&2; echo "$window_tree" >&2
      echo "--- app log ($label) ---" >&2; cat "$app_log" >&2 || true
      fail "$label run.sh arguments did not open $expected_window"
    }
    ok "$label default run.sh route opened $expected_window"
  fi
  local conn=""
  conn="$(timeout 5 gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetConnectionUnixProcessID com.steipete.CodexBarGTK 2>/dev/null || true)"
  local owner_pid
  owner_pid="$(parse_gdbus_pid "$conn")"
  [[ -n "$owner_pid" ]] || fail "GetConnectionUnixProcessID no pid ($label); reply: $conn"
  local exe_link
  exe_link="$(readlink "/proc/$owner_pid/exe" 2>/dev/null || true)"
  [[ "$exe_link" == "$BIN_DEST" ]] || fail "owner pid $owner_pid exe is $exe_link, expected $BIN_DEST ($label)"
  local owner_sha
  owner_sha="$(sha256sum "/proc/$owner_pid/exe" 2>/dev/null | awk '{print $1}')"
  [[ "$owner_sha" == "$expect_sha" ]] || fail "owner hash $owner_sha != expected $expect_sha ($label)"
  local elf_magic
  elf_magic="$(od -An -tx1 -N4 "$BIN_DEST" | tr -d ' \n')"
  [[ "$elf_magic" == "7f454c46" ]] || fail "not ELF ($label)"
  ldd "$BIN_DEST" >"$SCRATCH/ldd-${label}.txt" || fail "ldd failed ($label)"
  ! grep -qi "libpython\|pyo3" "$SCRATCH/ldd-${label}.txt" || fail "links python ($label)"
  timeout 5 gapplication action com.steipete.CodexBarGTK quit >/dev/null 2>&1 || true
  local wd=$((SECONDS + 5))
  while kill -0 "$pid" 2>/dev/null && [[ "$SECONDS" -lt "$wd" ]]; do sleep 0.1; done
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi
  wait "$pid" 2>/dev/null || true
  APP_PIDS="$(tr " " '\n' <<<"$APP_PIDS" | grep -vx "$pid" | tr '\n' ' ' || true)"
  ok "launched $label: owner pid $owner_pid exe+hash verified"
}
probe_launch "$DEBUG_SHA" debug --settings

echo "=== 4. upgrade release (no flag preserves activated=0) ==="
"$INSTALLER" --artifact "$RELEASE_BIN" --prefix "$PREFIX"
[[ "$(sha256sum "$BIN_DEST" | awk '{print $1}')" == "$RELEASE_SHA" ]] || fail "upgrade did not swap"
grep -q "^activated=0$" "$MANIFEST" || fail "upgrade must preserve activated=0"
probe_launch "$RELEASE_SHA" release --about

echo "=== 5. rollback to debug ==="
"$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$PREFIX"
[[ "$(sha256sum "$BIN_DEST" | awk '{print $1}')" == "$DEBUG_SHA" ]] || fail "rollback failed"
probe_launch "$DEBUG_SHA" rollback

echo "=== 6. idempotent uninstall ==="
"$INSTALLER" --uninstall --prefix "$PREFIX"
"$INSTALLER" --uninstall --prefix "$PREFIX"
[[ ! -e "$BIN_DEST" ]] || fail "uninstall left binary"
[[ ! -e "$MANIFEST" ]] || fail "uninstall left manifest"
[[ "$(sha256sum "$PY_SVC" | awk '{print $1}')" == "$PY_SVC_SHA" ]] || fail "uninstall clobbered service"
[[ "$(sha256sum "$PY_DSK" | awk '{print $1}')" == "$PY_DSK_SHA" ]] || fail "uninstall clobbered desktop"
[[ "$(sha256sum "$TEST_HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')" == "$SET_BEFORE" ]] || fail "settings changed"
[[ "$(sha256sum "$TEST_HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')" == "$HIS_BEFORE" ]] || fail "history changed"
ok "idempotent uninstall"

echo "=== 7. activate: backup, upgrade preserves provenance, uninstall restores ==="
"$INSTALLER" --artifact "$RELEASE_BIN" --prefix "$PREFIX" --activate
[[ -f "$PY_DSK.pre-native" ]] || fail "activate no desktop backup"
[[ -f "$PY_SVC.pre-native" ]] || fail "activate no service backup"
[[ ! -e "$TEST_HOME/.config/autostart/codexbar-gtk.desktop" ]] || fail "activate created autostart entry"
grep -q "X-CodexBar-DesktopFile" "$PY_DSK" || fail "desktop marker"
grep -q "X-CodexBar-Service" "$PY_SVC" || fail "service marker"
grep -Fqx "Exec=\"$BIN_DEST\" %U" "$PY_DSK" || fail "desktop Exec does not target installed native binary"
grep -Fqx "ExecStart=\"$BIN_DEST\"" "$PY_SVC" || fail "service ExecStart does not target installed native binary"
"$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$PREFIX"
grep -q "^activated=1$" "$MANIFEST" || fail "upgrade reset activation"
[[ "$(sha256sum "$PY_DSK.pre-native" | awk '{print $1}')" == "$PY_DSK_SHA" ]] || fail "upgrade overwrote desktop backup"
[[ "$(sha256sum "$PY_SVC.pre-native" | awk '{print $1}')" == "$PY_SVC_SHA" ]] || fail "upgrade overwrote service backup"
"$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$PREFIX"
[[ -f "$PY_DSK.pre-native" ]] || fail "idempotent reinstall lost backup"
"$INSTALLER" --uninstall --prefix "$PREFIX"
[[ "$(sha256sum "$PY_SVC" | awk '{print $1}')" == "$PY_SVC_SHA" ]] || fail "uninstall did not restore service"
[[ "$(sha256sum "$PY_DSK" | awk '{print $1}')" == "$PY_DSK_SHA" ]] || fail "uninstall did not restore desktop"
ok "activate backup/restore + provenance"

echo "=== 8. user edit preserved ==="
"$INSTALLER" --artifact "$RELEASE_BIN" --prefix "$PREFIX" --activate
printf 'Description=Py\nExecStart=/usr/bin/python3 -m codexbar_gtk\n' > "$PY_SVC"
"$INSTALLER" --uninstall --prefix "$PREFIX"
[[ "$(sha256sum "$PY_SVC" | awk '{print $1}')" == "$PY_SVC_SHA" ]] || fail "uninstall clobbered user edit"
ok "uninstall preserves user-edited file"

echo "=== 9. unsupported path rejection ==="
BAD_PREFIX="$SCRATCH/bad%prefix"
mkdir -p "$BAD_PREFIX"
if "$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$BAD_PREFIX" --activate 2>"$SCRATCH/bad.log"; then
  fail "unsupported % path should have been rejected"
fi
grep -qi "unsupported" "$SCRATCH/bad.log" || fail "rejection message missing"
ok "unsupported % rejected"

echo "=== 10. runtime_deps doc + foreign binary rejected ==="
[[ -f "$ROOT/scripts/native/runtime_deps.txt" ]] || fail "runtime_deps.txt missing"
! grep -qi "^Depends" "$ROOT/scripts/native/runtime_deps.txt" || fail "must not claim Depends"
# Case A: foreign binary with NO prior manifest (first install) was the hole.
FIRST_PREFIX="$SCRATCH/first-prefix"
mkdir -p "$FIRST_PREFIX/bin"
cp /bin/true "$FIRST_PREFIX/bin/codexbar-gtk-native"
chmod +x "$FIRST_PREFIX/bin/codexbar-gtk-native"
FIRST_FOREIGN="$(sha256sum "$FIRST_PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')"
if "$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$FIRST_PREFIX" 2>"$SCRATCH/first-foreign.log"; then
  fail "foreign binary with no manifest should have been rejected"
fi
[[ "$(sha256sum "$FIRST_PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')" == "$FIRST_FOREIGN" ]] || fail "rejected install modified no-manifest foreign"
ok "no-manifest foreign rejected (hole fixed)"
# Case B: foreign binary with prior manifest hash mismatch.
"$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$PREFIX"
cp /bin/true "$BIN_DEST"; chmod +x "$BIN_DEST"
FOREIGN_SHA="$(sha256sum "$BIN_DEST" | awk '{print $1}')"
if "$INSTALLER" --artifact "$RELEASE_BIN" --prefix "$PREFIX" 2>"$SCRATCH/foreign.log"; then
  fail "foreign binary should have been rejected"
fi
[[ "$(sha256sum "$BIN_DEST" | awk '{print $1}')" == "$FOREIGN_SHA" ]] || fail "rejected install modified foreign"
ok "foreign rejected, runtime_deps doc-only"

echo "=== 11. explicit --no-activate over activated install rejected (no orphan) ==="
DEACT_PREFIX="$SCRATCH/deact-prefix"
mkdir -p "$DEACT_PREFIX"
DEACT_HOME="$SCRATCH/deact-home"
mkdir -p "$DEACT_HOME"
HOME="$DEACT_HOME" "$INSTALLER" --artifact "$RELEASE_BIN" --prefix "$DEACT_PREFIX" --activate
DEACT_BIN_SHA="$(sha256sum "$DEACT_PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')"
DEACT_MAN_SHA="$(sha256sum "$DEACT_PREFIX/share/codexbar-gtk/native-manifest" | awk '{print $1}')"
if HOME="$DEACT_HOME" "$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$DEACT_PREFIX" --no-activate 2>"$SCRATCH/deact.log"; then
  fail "explicit --no-activate over activated install should have been rejected"
fi
grep -qi "unsupported" "$SCRATCH/deact.log" || fail "deactivation rejection message missing"
[[ "$(sha256sum "$DEACT_PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')" == "$DEACT_BIN_SHA" ]] || fail "rejected deactivation swapped binary"
[[ "$(sha256sum "$DEACT_PREFIX/share/codexbar-gtk/native-manifest" | awk '{print $1}')" == "$DEACT_MAN_SHA" ]] || fail "rejected deactivation rewrote manifest"
ok "explicit deactivation transition rejected, no orphan activation"

echo "=== 12. activation renderer failures leave fresh install and upgrade unchanged ==="
FIXTURE_ROOT="$SCRATCH/renderer-fixture"
FIXTURE_INSTALLER="$FIXTURE_ROOT/scripts/install-native.sh"
mkdir -p "$FIXTURE_ROOT/scripts/native/stage"
cp "$INSTALLER" "$FIXTURE_INSTALLER"
cp "$ROOT/scripts/native/render_activation.sh" "$FIXTURE_ROOT/scripts/native/render_activation.sh"
cp "$ROOT/scripts/native/stage/native.desktop" "$FIXTURE_ROOT/scripts/native/stage/native.desktop"
cp "$ROOT/scripts/native/stage/native.service" "$FIXTURE_ROOT/scripts/native/stage/native.service"
RENDER_TEST_HOME="$SCRATCH/render-home"
RENDER_PREFIX="$SCRATCH/render-prefix"
RENDER_BIN="$RENDER_PREFIX/bin/codexbar-gtk-native"
RENDER_MANIFEST="$RENDER_PREFIX/share/codexbar-gtk/native-manifest"
RENDER_DESKTOP="$RENDER_PREFIX/share/applications/codexbar-gtk.desktop"
RENDER_SERVICE="$RENDER_TEST_HOME/.config/systemd/user/codexbar-gtk.service"
mkdir -p "$RENDER_TEST_HOME/.config/systemd/user" "$RENDER_PREFIX/share/applications"
printf '[Desktop Entry]\nExec=foreign desktop\n' > "$RENDER_DESKTOP"
printf '[Service]\nExecStart=foreign service\n' > "$RENDER_SERVICE"
RENDER_DESKTOP_SHA="$(sha256sum "$RENDER_DESKTOP" | awk '{print $1}')"
RENDER_SERVICE_SHA="$(sha256sum "$RENDER_SERVICE" | awk '{print $1}')"

for scenario in fresh upgrade; do
  if [[ "$scenario" == upgrade ]]; then
    HOME="$RENDER_TEST_HOME" "$FIXTURE_INSTALLER" --artifact "$DEBUG_BIN" --prefix "$RENDER_PREFIX"
    RENDER_MANIFEST_SHA="$(sha256sum "$RENDER_MANIFEST" | awk '{print $1}')"
    [[ "$(sha256sum "$RENDER_BIN" | awk '{print $1}')" == "$DEBUG_SHA" ]] || fail "upgrade baseline missing"
  fi
  for fail_at in desktop service; do
    if [[ "$fail_at" == desktop ]]; then
      printf '[Desktop Entry]\nName=missing Exec key\n' > "$FIXTURE_ROOT/scripts/native/stage/native.desktop"
      cp "$ROOT/scripts/native/stage/native.service" "$FIXTURE_ROOT/scripts/native/stage/native.service"
    else
      cp "$ROOT/scripts/native/stage/native.desktop" "$FIXTURE_ROOT/scripts/native/stage/native.desktop"
      printf '[Service]\nDescription=missing ExecStart key\n' > "$FIXTURE_ROOT/scripts/native/stage/native.service"
    fi
    if HOME="$RENDER_TEST_HOME" "$FIXTURE_INSTALLER" --artifact "$RELEASE_BIN" \
       --prefix "$RENDER_PREFIX" --activate > "$SCRATCH/render-failure.log" 2>&1; then
      fail "$fail_at template failure unexpectedly succeeded ($scenario)"
    fi
    grep -q 'activation rendering failed' "$SCRATCH/render-failure.log" || fail "render failure not reported"
    [[ "$(sha256sum "$RENDER_DESKTOP" | awk '{print $1}')" == "$RENDER_DESKTOP_SHA" ]] || fail "renderer failure changed desktop"
    [[ "$(sha256sum "$RENDER_SERVICE" | awk '{print $1}')" == "$RENDER_SERVICE_SHA" ]] || fail "renderer failure changed service"
    [[ ! -e "$RENDER_DESKTOP.pre-native" && ! -e "$RENDER_SERVICE.pre-native" ]] || fail "renderer failure created backups"
    if [[ "$scenario" == fresh ]]; then
      [[ ! -e "$RENDER_BIN" && ! -e "$RENDER_MANIFEST" ]] || fail "renderer failure modified fresh install"
    else
      [[ "$(sha256sum "$RENDER_BIN" | awk '{print $1}')" == "$DEBUG_SHA" ]] || fail "renderer failure swapped binary"
      [[ "$(sha256sum "$RENDER_MANIFEST" | awk '{print $1}')" == "$RENDER_MANIFEST_SHA" ]] || fail "renderer failure changed manifest"
    fi
  done
done
cp "$ROOT/scripts/native/stage/native.desktop" "$FIXTURE_ROOT/scripts/native/stage/native.desktop"
cp "$ROOT/scripts/native/stage/native.service" "$FIXTURE_ROOT/scripts/native/stage/native.service"
HOME="$RENDER_TEST_HOME" "$FIXTURE_INSTALLER" --artifact "$RELEASE_BIN" --prefix "$RENDER_PREFIX" --activate
[[ "$(sha256sum "$RENDER_BIN" | awk '{print $1}')" == "$RELEASE_SHA" ]] || fail "retry after renderer failure wedged"
HOME="$RENDER_TEST_HOME" "$FIXTURE_INSTALLER" --uninstall --prefix "$RENDER_PREFIX"
ok "first/second template failures preserve fresh install and upgrade; retry succeeds"

echo "=== 13. missing HOME fails before installation ==="
if env -u HOME "$INSTALLER" --artifact "$DEBUG_BIN" --prefix "$SCRATCH/no-home" > "$SCRATCH/no-home.log" 2>&1; then
  fail "missing HOME should be rejected"
fi
[[ ! -e "$SCRATCH/no-home" ]] || fail "missing HOME created install files"
grep -q 'HOME' "$SCRATCH/no-home.log" || fail "missing HOME diagnostic absent"
ok "missing HOME rejected before writes"
# Fixtures wrote no runtime activity; history appending by the real runtime
# is legitimate and outside byte-check scope (install/uninstall only).

echo "PASS: native install isolated smoke complete"
