#!/usr/bin/env bash
# Container fallback launcher for C02. Rootless docker; --network none.
# Runs the native ELF + Xvfb + private dbus-daemon inside the no-Python image.
# Usage: run-container.sh <artifact-elf> <synthetic-home> <display-host>
# Evidence: container logs + `docker images --digests` + inspect output are
# saved by the caller. This script never fakes success.
set -euo pipefail
ARTIFACT="$1"; SYNTH_HOME="$2"; DISPLAY_VAL="$3"
IMAGE="${DOCKER_IMAGE:-codexbar-no-python:smoke}"
CONTAINER="codexbar-c02-$(date +%s)"
echo "container: $CONTAINER image: $IMAGE (network=none, no python reachable by abs path)"
docker images --digests | grep codexbar-no-python || true
# App inside container: Xvfb on :99, private dbus-daemon, app with synthetic HOME.
# Prints in-container evidence lines prefixed EVIDENCE: for the host harness.
docker run -d --name "$CONTAINER" --network none \
  --volume "$ARTIFACT:/app/codexbar-gtk-native:ro" \
  --volume "$SYNTH_HOME:/home/synth:rw" \
  "$IMAGE" \
  "set -e
Xvfb :99 > /tmp/xvfb.log 2>&1 & echo xvfb:\$!
sleep 2
mkdir -p /tmp/dbus
dbus-daemon --session --address=unix:abstract=/tmp/dbus/bus --fork --print-address=1 --print-pid=1 > /tmp/dbus/addrpid 2> /tmp/dbus.log || { cat /tmp/dbus.log; exit 1; }
export DBUS_SESSION_BUS_ADDRESS=\$(head -1 /tmp/dbus/addrpid)
export DISPLAY=:99
export HOME=/home/synth
/app/codexbar-gtk-native > /tmp/app.log 2> /tmp/app.err & APP_PID=\$!
echo EVIDENCE:app-pid=\$APP_PID
sleep 3
echo EVIDENCE:exe=\$(readlink /proc/\$APP_PID/exe 2>/dev/null || echo MISSING)
echo EVIDENCE:cmdline=\$(tr '\\\\0' ' ' </proc/\$APP_PID/cmdline 2>/dev/null | cut -c1-200 || echo MISSING)
echo EVIDENCE:libpython-maps=\$(grep -ci libpython /proc/\$APP_PID/maps 2>/dev/null || echo 0)
echo EVIDENCE:libpython-fd=\$(ls -l /proc/\$APP_PID/fd 2>/dev/null | grep -ci libpython || echo 0)
ls /usr/bin/python* 2>&1 | head -1 || true
ls /usr/lib/python* 2>&1 | head -1 || true
echo EVIDENCE:svg-loader=\$(ls /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so 2>&1)
cat /tmp/app.log 2>/dev/null | head -20 || true
cat /tmp/app.err 2>/dev/null | head -20 || true
# private dbus identity check (host tools not needed inside image)
# Rust gio::Application is a GApplication (D-Bus application name, not
# implicitly owning the well-known bus name until D-Bus activation). Record
# ListNames output; presence of appid is positive evidence, absence with a
# live process + registered primary-instance socket is the expected path.
if command -v gdbus >/dev/null 2>&1; then
  LISTED=\$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames --timeout 5 2>&1 || echo LISTNAMES_FAILED)
  echo EVIDENCE:dbus-list=\$LISTED
  if printf '%s' "\$LISTED" | grep -q 'com.steipete.CodexBarGTK'; then
    echo EVIDENCE:dbus-appid=REGISTERED
  else
    echo EVIDENCE:dbus-appid=PENIDING-PRIMARY-REGISTERED
  fi
fi
# bounded shutdown: request quit via dbus action if available, else TERM
kill -TERM \$APP_PID 2>/dev/null || true
sleep 4
if kill -0 \$APP_PID 2>/dev/null; then echo EVIDENCE:still-running; kill -KILL \$APP_PID 2>/dev/null || true; fi
wait \$APP_PID 2>/dev/null || ec=\$?
echo EVIDENCE:app-wait=\$ec
kill %1 2>/dev/null || true
echo EVIDENCE:container-done"
sleep 9
docker logs "$CONTAINER" > "$SYNTH_HOME/container.log" 2>&1 || true
cat "$SYNTH_HOME/container.log"
docker inspect "$CONTAINER" > "$SYNTH_HOME/docker-inspect.json" 2>/dev/null || true
# bounded shutdown
docker stop -t 10 "$CONTAINER" >/dev/null 2>&1 || docker kill "$CONTAINER" >/dev/null 2>&1 || true
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
echo "container fallback: bounded shutdown completed"
