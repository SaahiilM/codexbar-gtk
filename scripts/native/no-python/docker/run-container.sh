#!/usr/bin/env bash
# Single supported C02 proof path: one container, --network none, Xvfb and
# private D-Bus entirely inside the container, no host DISPLAY/bus mounts.
# Args: <artifact-path> <workdir> <expected-sha256>
# Emits EVIDENCE: lines on stdout plus container name. Tests the ACTUAL app
# PID (from GetConnectionUnixProcessID), never the harness shell.
set -uo pipefail
ARTIFACT="$1"; WORKDIR="$2"; EXPECTED_SHA="$3"
IMAGE="${DOCKER_IMAGE:-codexbar-no-python:smoke}"
CONTAINER="codexbar-no-python-$$"
echo "image: $IMAGE (network=none, no host mounts beyond /app + /work)"
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
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 2
dbus-daemon --session --address="unix:abstract=/tmp/dbus/bus" --fork
bus_ready=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames --timeout 3 >/dev/null 2>&1; then bus_ready=1; break; fi
  sleep 1
done
echo "EVIDENCE:bus-ready=$bus_ready"
rm -f /work/home/cli.log
/app/codexbar-gtk-native >/tmp/app.log 2>/tmp/app.err &
APP_PID=$!
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
  P=$(printf '%s' "$V" | grep -oE '[0-9]+' | head -1 || true)
  if printf '%s' "$P" | grep -qE '^[0-9]+$' && [ "$P" != "0" ]; then UNIX_PID="$P"; break; fi
  sleep 1
done
echo "EVIDENCE:unix-pid=$UNIX_PID"
echo "EVIDENCE:exe=$(readlink /proc/$UNIX_PID/exe 2>/dev/null || echo MISSING)"
echo "EVIDENCE:exe-sha=$(sha256sum /proc/$UNIX_PID/exe 2>/dev/null | awk '{print $1}' || echo MISSING)"
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
CID=$(docker run -d --name "$CONTAINER" --network none \
  --volume "$ARTIFACT:/app/codexbar-gtk-native:ro" \
  --volume "$WORKDIR:/work:rw" \
  "$IMAGE" /bin/bash /work/in-container.sh 2>&1)
START=$SECONDS
while [ $((SECONDS-START)) -lt 60 ]; do
  if docker logs "$CONTAINER" 2>/dev/null | grep -q "EVIDENCE:container-done"; then break; fi
  sleep 2
done
echo "container-name=$CONTAINER"
echo "container-id=$(docker inspect --format '{{.Id}}' "$CONTAINER" 2>/dev/null || echo unknown)"
docker logs "$CONTAINER" 2>&1
echo "EVIDENCE:container-name=$CONTAINER"
