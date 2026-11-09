#!/usr/bin/env bash
# Single supported C02 proof path: one container, --network none, Xvfb and
# private D-Bus entirely inside the container, no host DISPLAY/bus mounts.
# Args: artifact, workdir, expected-sha256, [installer-source, debug-artifact,
# release-artifact, svg-test-binary]. Staged inputs are mounted under /work,
# with optional immutable artifact/probe mounts under /artifacts and /probe.
# Emits EVIDENCE: lines on stdout plus container name. Tests the ACTUAL app
# PID (from GetConnectionUnixProcessID), never the harness shell.
set -uo pipefail
ARTIFACT="$1"; WORKDIR="$2"; EXPECTED_SHA="$3"
INSTALLER_SOURCE="${4:-}"; DEBUG_ARTIFACT="${5:-}"; RELEASE_ARTIFACT="${6:-}"; SVG_TEST_BINARY="${7:-}"
IMAGE="${DOCKER_IMAGE:-codexbar-no-python:smoke}"
CONTAINER="codexbar-no-python-$$"
echo "image: $IMAGE (network=none, host mounts limited to app, work, and requested artifacts/probe)"
cat > "$WORKDIR/in-container.sh" <<'INNER'
set -u
mkdir -p /tmp/dbus /work/home/.config/codexbar-gtk /work/home/.local/bin
export HOME=/work/home
export XDG_CONFIG_HOME=/work/home/.config
export XDG_CACHE_HOME=/work/home/.cache
export XDG_DATA_HOME=/work/home/.local/share
export PATH="/work/home/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DISPLAY=:99
export GDK_BACKEND=x11
export DBUS_SESSION_BUS_ADDRESS="unix:abstract=/tmp/dbus/bus"
APP_EXEC=/app/codexbar-gtk-native
APP_EXPECTED_SHA="$1"
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 2
dbus-daemon --session --address="unix:abstract=/tmp/dbus/bus" --fork
bus_ready=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames --timeout 3 >/dev/null 2>&1; then bus_ready=1; break; fi
  sleep 1
done
echo "EVIDENCE:bus-ready=$bus_ready"
[ "$bus_ready" = 1 ] || { echo "FAIL: private D-Bus did not become ready" >&2; exit 1; }
if [ -f /work/installer/scripts/install-native.sh ]; then
  PREFIX='/work/prefix with spaces'
  INSTALLER=/work/installer/scripts/install-native.sh
  SETTINGS_SHA=$(sha256sum "$HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')
  HISTORY_SHA=$(sha256sum "$HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')
  install_profile() {
    local label="$1" artifact="$2" expected="$3" actual
    if "$INSTALLER" --artifact "$artifact" --prefix "$PREFIX" --no-activate; then
      :
    else
      rc=$?
      echo "FAIL: $label installer exited $rc" >&2
      return 1
    fi
    [ -x "$PREFIX/bin/codexbar-gtk-native" ] || { echo "FAIL: $label installed binary missing" >&2; return 1; }
    [ -f "$PREFIX/share/codexbar-gtk/native-manifest" ] || { echo "FAIL: $label installed manifest missing" >&2; return 1; }
    actual=$(sha256sum "$PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')
    [ "$actual" = "$expected" ] || { echo "FAIL: $label installed binary hash $actual != $expected" >&2; return 1; }
    grep -qx "binary_sha256=$expected" "$PREFIX/share/codexbar-gtk/native-manifest" || { echo "FAIL: $label manifest hash" >&2; return 1; }
    echo "EVIDENCE:$label-install=PASS binary-sha=$actual manifest-sha=$expected"
  }
  run_app_probe() {
    local label="$1" expected="$2" exe="$3" pid ownerpid owner exe_path running_sha before after waited rc
    if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK --timeout 3 2>&1 | grep -q '(true,)'; then
      echo "FAIL: $label probe began while app already owned D-Bus name" >&2; return 1
    fi
    "$exe" >/tmp/app-"$label".log 2>/tmp/app-"$label".err &
    pid=$!
    local done=0
    for _ in $(seq 1 30); do
      if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK --timeout 3 2>&1 | grep -q '(true,)'; then done=1; break; fi
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      sleep 1
    done
    ownerpid=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetConnectionUnixProcessID com.steipete.CodexBarGTK --timeout 3 2>/dev/null | sed -nE 's/^\(uint32 ([0-9]+),\)$/\1/p')
    if [ "$done" != 1 ] || [ "$ownerpid" != "$pid" ]; then
      echo "FAIL: $label owner/PID mismatch (owner=$ownerpid launched=$pid)" >&2
      cat /tmp/app-"$label".log /tmp/app-"$label".err 2>/dev/null || true
      cleanup_probe "$pid"
      return 1
    fi
    exe_path=$(readlink -f "/proc/$ownerpid/exe" 2>/dev/null || true)
    running_sha=$(sha256sum "/proc/$ownerpid/exe" 2>/dev/null | awk '{print $1}')
    [ "$exe_path" = "$exe" ] || { echo "FAIL: $label exe $exe_path != $exe" >&2; cleanup_probe "$pid"; return 1; }
    [ "$running_sha" = "$expected" ] || { echo "FAIL: $label running hash $running_sha != $expected" >&2; cleanup_probe "$pid"; return 1; }
    before=$(wc -l < /work/home/cli.log 2>/dev/null || echo 0); before=$(printf '%s' "$before" | tr -d ' ')
    gdbus call --session --dest com.steipete.CodexBarGTK --object-path /com/steipete/CodexBarGTK --method org.gtk.Actions.Activate refresh '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
    sleep 2
    after=$(wc -l < /work/home/cli.log 2>/dev/null || echo 0); after=$(printf '%s' "$after" | tr -d ' ')
    [ -n "$after" ] && [ "$after" -gt "$before" ] 2>/dev/null || { echo "FAIL: $label refresh did not increase CLI calls ($before->$after)" >&2; cleanup_probe "$pid"; return 1; }
    gdbus call --session --dest com.steipete.CodexBarGTK --object-path /com/steipete/CodexBarGTK --method org.gtk.Actions.Activate quit '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
    waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 10 ]; do sleep 1; waited=$((waited+1)); done
    if kill -0 "$pid" 2>/dev/null; then echo "FAIL: $label quit timed out" >&2; cleanup_probe "$pid"; return 1; fi
    wait "$pid"; rc=$?
    [ "$rc" -eq 0 ] || { echo "FAIL: $label quit exited $rc" >&2; return 1; }
    if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner com.steipete.CodexBarGTK --timeout 3 2>&1 | grep -q '(true,)'; then echo "FAIL: $label left app as D-Bus owner" >&2; return 1; fi
    echo "EVIDENCE:$label-runtime=PASS owner-pid=$ownerpid exe=$exe sha=$running_sha refresh-cli=$before->$after quit=$rc"
  }
  cleanup_probe() {
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  }
  if [ -x /artifacts/debug ] && [ -x /artifacts/release ]; then
    DEBUG_SHA=$(sha256sum /artifacts/debug | awk '{print $1}')
    RELEASE_SHA=$(sha256sum /artifacts/release | awk '{print $1}')
    install_profile debug /artifacts/debug "$DEBUG_SHA" || exit 1
    run_app_probe debug "$DEBUG_SHA" "$PREFIX/bin/codexbar-gtk-native" || exit 1
    install_profile release /artifacts/release "$RELEASE_SHA" || exit 1
    run_app_probe release "$RELEASE_SHA" "$PREFIX/bin/codexbar-gtk-native" || exit 1
    install_profile rollback /artifacts/debug "$DEBUG_SHA" || exit 1
    run_app_probe rollback "$DEBUG_SHA" "$PREFIX/bin/codexbar-gtk-native" || exit 1
    echo "EVIDENCE:build-profile-lifecycle=debug-install-runtime:$DEBUG_SHA,release-profile-install-runtime:$RELEASE_SHA,debug-rollback-runtime:$DEBUG_SHA"
  else
    if "$INSTALLER" --artifact /app/codexbar-gtk-native --prefix "$PREFIX" --no-activate; then :; else rc=$?; echo "FAIL: installer exited $rc" >&2; exit 1; fi
    [ -x "$PREFIX/bin/codexbar-gtk-native" ] || { echo 'FAIL: installed binary missing'; exit 1; }
    [ -f "$PREFIX/share/codexbar-gtk/native-manifest" ] || { echo 'FAIL: installed manifest missing'; exit 1; }
    APP_EXPECTED_SHA=$(sha256sum "$PREFIX/bin/codexbar-gtk-native" | awk '{print $1}')
    grep -qx "binary_sha256=$APP_EXPECTED_SHA" "$PREFIX/share/codexbar-gtk/native-manifest" || { echo 'FAIL: installed manifest hash'; exit 1; }
  fi
  if [ "$(sha256sum "$HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')" != "$SETTINGS_SHA" ] ||
     [ "$(sha256sum "$HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')" != "$HISTORY_SHA" ]; then
    echo 'FAIL: installer operation modified user settings/history'; exit 1
  fi
  if "$INSTALLER" --uninstall --prefix "$PREFIX"; then :; else rc=$?; echo "FAIL: uninstall exited $rc" >&2; exit 1; fi
  [ ! -e "$PREFIX/bin/codexbar-gtk-native" ] && [ ! -e "$PREFIX/share/codexbar-gtk/native-manifest" ] || { echo 'FAIL: uninstall left owned prefix files'; exit 1; }
  [ "$(sha256sum "$HOME/.config/codexbar-gtk/settings.json" | awk '{print $1}')" = "$SETTINGS_SHA" ] || { echo 'FAIL: uninstall modified settings'; exit 1; }
  [ "$(sha256sum "$HOME/.config/codexbar-gtk/history.jsonl" | awk '{print $1}')" = "$HISTORY_SHA" ] || { echo 'FAIL: uninstall modified history'; exit 1; }
  echo 'EVIDENCE:installer-data-preserved=1'
  RUNTIME_ARTIFACT=/app/codexbar-gtk-native
  if [ -x /artifacts/debug ]; then RUNTIME_ARTIFACT=/artifacts/debug; fi
  "$INSTALLER" --artifact "$RUNTIME_ARTIFACT" --prefix "$PREFIX" --no-activate
  APP_EXEC="$PREFIX/bin/codexbar-gtk-native"
  APP_EXPECTED_SHA=$(sha256sum "$APP_EXEC" | awk '{print $1}')
  grep -qx "binary_sha256=$APP_EXPECTED_SHA" "$PREFIX/share/codexbar-gtk/native-manifest" || { echo 'FAIL: installed runtime manifest hash'; exit 1; }
  echo "EVIDENCE:installer-manifest-sha=$APP_EXPECTED_SHA"
fi
if [ -x /probe/a11y_assets ]; then
  (cd /tmp && /probe/a11y_assets --ignored --exact provider_artwork_decodes_outside_repository_cwd_and_keeps_textual_fallback --nocapture) >/tmp/svg-test.log 2>&1
  RC=$?
  cat /tmp/svg-test.log
  [ "$RC" -eq 0 ] && grep -q '1 passed' /tmp/svg-test.log || { echo 'FAIL: SVG decode test executable failed'; exit 1; }
  echo 'EVIDENCE:svg-decode-test=PASS dimensions-asserted'
fi
rm -f /work/home/cli.log
"$APP_EXEC" >/tmp/app.log 2>/tmp/app.err &
APP_PID=$!
cleanup_app() {
  if kill -0 "$APP_PID" 2>/dev/null; then
    kill -TERM "$APP_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$APP_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup_app EXIT INT TERM
echo "EVIDENCE:app-pid=$APP_PID"
APP_ID="com.steipete.CodexBarGTK"
for i in $(seq 1 30); do
  if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner "$APP_ID" --timeout 3 2>&1 | grep -q '(true,)'; then break; fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then break; fi
  sleep 1
done
IM=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner "$APP_ID" --timeout 3 2>&1 || echo FAIL)
OWNER=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetNameOwner "$APP_ID" --timeout 3 2>&1 || echo FAIL)
echo "EVIDENCE:namehasowner=$IM"
echo "EVIDENCE:owner=$OWNER"
UNIX_PID="none"
for i in 1 2 3 4 5; do
  V=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetConnectionUnixProcessID "$APP_ID" --timeout 3 2>&1 || echo FAIL)
  P=$(printf '%s' "$V" | sed -nE 's/^\(uint32 ([0-9]+),\)$/\1/p')
  if printf '%s' "$P" | grep -qE '^[0-9]+$' && [ "$P" != "0" ]; then UNIX_PID="$P"; break; fi
  sleep 1
done
echo "EVIDENCE:unix-pid=$UNIX_PID"
if [ "$UNIX_PID" != "$APP_PID" ]; then
  echo "FAIL: D-Bus owner $UNIX_PID does not match launched app $APP_PID; bounded cleanup will terminate the launched process" >&2
  cat /tmp/app.log /tmp/app.err 2>/dev/null || true
  exit 1
fi
echo "EVIDENCE:exe=$(readlink -f /proc/$UNIX_PID/exe 2>/dev/null || echo MISSING)"
echo "EVIDENCE:exe-sha=$(sha256sum /proc/$UNIX_PID/exe 2>/dev/null | awk '{print $1}' || echo MISSING)"
RUNNING_SHA=$(sha256sum "/proc/$UNIX_PID/exe" 2>/dev/null | awk '{print $1}')
[ "$RUNNING_SHA" = "$APP_EXPECTED_SHA" ] || { echo "FAIL: running executable hash $RUNNING_SHA != expected $APP_EXPECTED_SHA"; exit 1; }
echo 'EVIDENCE:running-executable-hash-match=1'
if printf '%s' "$UNIX_PID" | grep -qE '^[0-9]+$' && [ -f "/proc/$UNIX_PID/maps" ]; then
  echo "EVIDENCE:maps-libpython=$(grep -ci 'libpython' /proc/$UNIX_PID/maps || echo 0)"
  echo "EVIDENCE:maps-pyo3=$(grep -ciE 'PyO3|pyo3' /proc/$UNIX_PID/maps || echo 0)"
  echo "EVIDENCE:maps-rustcore=$(grep -ci '_rust_core' /proc/$UNIX_PID/maps || echo 0)"
else
  echo "EVIDENCE:maps-libpython=MISSING"
  echo "EVIDENCE:maps-pyo3=MISSING"
  echo "EVIDENCE:maps-rustcore=MISSING"
fi
for p in /usr/bin/python3 /usr/bin/python /usr/local/bin/python3; do
  if [ ! -e "$p" ]; then echo "EVIDENCE:python-absent=$p"; fi
done
if [ ! -d /usr/lib/python3.12 ] && [ ! -d /usr/lib/python3 ] && [ ! -d /usr/local/lib/python3 ]; then
  echo "EVIDENCE:python-libdir-absent=1"
fi
if ! ls /usr/lib/x86_64-linux-gnu/libpython*.so* >/dev/null 2>&1; then
  echo "EVIDENCE:libpython-absent=1"
fi
echo "EVIDENCE:svg-loader=$(ls /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so 2>&1)"
B=$(wc -l < /work/home/cli.log 2>/dev/null || echo 0); B=$(printf '%s' "$B" | tr -d ' ')
gdbus call --session --dest "$APP_ID" --object-path "/com/steipete/CodexBarGTK" --method org.gtk.Actions.Activate refresh '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
sleep 3
A=$(wc -l < /work/home/cli.log 2>/dev/null || echo 0); A=$(printf '%s' "$A" | tr -d ' ')
echo "EVIDENCE:cli-before=$B"
echo "EVIDENCE:cli-after=$A"
echo "--- cli.log ---"
cat /work/home/cli.log 2>/dev/null || true
gdbus call --session --dest "$APP_ID" --object-path "/com/steipete/CodexBarGTK" --method org.gtk.Actions.Activate settings '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
sleep 2
WIN=$(xwininfo -root -tree -display :99 2>/dev/null | grep -iE 'CodexBar Settings|settings' | wc -l || true)
if [ "$WIN" -gt 0 ]; then echo "EVIDENCE:settings-window=FOUND"; else echo "EVIDENCE:settings-window=MISSING"; fi
gdbus call --session --dest "$APP_ID" --object-path "/com/steipete/CodexBarGTK" --method org.gtk.Actions.Activate about '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
sleep 2
WIN2=$(xwininfo -root -tree -display :99 2>/dev/null | grep -iE 'About CodexBar|About' | wc -l || true)
if [ "$WIN2" -gt 0 ]; then echo "EVIDENCE:about-window=FOUND"; else echo "EVIDENCE:about-window=MISSING"; fi
xwininfo -root -tree -display :99 2>/dev/null | head -30 || true
gdbus call --session --dest "$APP_ID" --object-path "/com/steipete/CodexBarGTK" --method org.gtk.Actions.Activate quit '[]' '{}' --timeout 5 >/dev/null 2>&1 || true
waited=0
while kill -0 "$APP_PID" 2>/dev/null && [ "$waited" -lt 10 ]; do sleep 1; waited=$((waited+1)); done
if kill -0 "$APP_PID" 2>/dev/null; then
  echo "EVIDENCE:app-exit=TIMEOUT"
  kill -TERM "$APP_PID" 2>/dev/null || true; sleep 2
  if kill -0 "$APP_PID" 2>/dev/null; then kill -KILL "$APP_PID" 2>/dev/null || true; fi
else
  wait "$APP_PID" 2>/dev/null; echo "EVIDENCE:app-exit=$?"
fi
echo "EVIDENCE:container-done=1"
cat /tmp/app.err 2>/dev/null | head -50 || true
INNER
VOLUMES=(--volume "$ARTIFACT:/app/codexbar-gtk-native:ro")
if [ -n "$DEBUG_ARTIFACT" ]; then
  VOLUMES+=(--volume "$DEBUG_ARTIFACT:/artifacts/debug:ro" --volume "$RELEASE_ARTIFACT:/artifacts/release:ro")
fi
if [ -n "$SVG_TEST_BINARY" ]; then VOLUMES+=(--volume "$SVG_TEST_BINARY:/probe/a11y_assets:ro"); fi
CID=$(docker run -d --name "$CONTAINER" --network none \
  "${VOLUMES[@]}" \
  --volume "$WORKDIR:/work:rw" \
  "$IMAGE" /bin/bash /work/in-container.sh "$EXPECTED_SHA" 2>&1)
START=$SECONDS; DONE=0
while [ $((SECONDS-START)) -lt 60 ]; do
  if docker logs "$CONTAINER" 2>/dev/null | grep -q "EVIDENCE:container-done"; then DONE=1; break; fi
  STATE=$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)
  if [ "$STATE" != running ]; then break; fi
  sleep 2
done
if [ "$DONE" != 1 ]; then echo 'FAIL: bounded container runtime timed out; stopping owned container' >&2; docker kill "$CONTAINER" >/dev/null 2>&1 || true; fi
echo "container-name=$CONTAINER"
echo "container-id=$(docker inspect --format '{{.Id}}' "$CONTAINER" 2>/dev/null || echo unknown)"
docker logs "$CONTAINER" 2>&1
echo "EVIDENCE:container-name=$CONTAINER"
CONTAINER_RC=$(docker wait "$CONTAINER" 2>/dev/null || echo 125)
echo "EVIDENCE:container-exit=$CONTAINER_RC"
if [ "$CONTAINER_RC" != 0 ]; then exit 1; fi
