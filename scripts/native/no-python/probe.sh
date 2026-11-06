#!/usr/bin/env bash
# In-sandbox evidence probe (C02). Runs INSIDE the isolated namespace.
# Host-side harness tooling (python3, gdbus, ...) is NOT available here on
# purpose: this script only uses the tools the sanctioned runtime PATH
# provides (sh, cat, ls, id, readlink-free POSIX shell + coreutils).
# Whatever it can observe, it writes to $PROBE_OUT/evidence.txt.
set -u
OUT="${PROBE_OUT:?PROBE_OUT must be set}"
mkdir -p "$OUT"
: > "$OUT/evidence.txt"
log() { printf '%s\n' "$*"; printf '%s\n' "$*" >> "$OUT/evidence.txt"; }

log "probe.started=$(date -Iseconds 2>/dev/null || date +%s)"
log "probe.pid=$$"
log "probe.exe=$(readlink /proc/$$/exe 2>/dev/null || echo MISSING)"
log "probe.cmdline=$(tr '\0' ' ' </proc/$$/cmdline 2>/dev/null | cut -c1-400)"

# --- Python absence: absolute path, not just PATH ---
for p in /usr/bin/python3 /usr/bin/python /usr/local/bin/python3 \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0 \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so.1; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    log "python.present=$p RESOLVABLE (BAD)"
  else
    log "python.absent=$p OK"
  fi
done
# PyGObject/PyO3 via package dirs (may not exist on host at all; still check)
for p in /usr/lib/python3/dist-packages/gi \
         /usr/lib/girepository-1.0/GIRepository-2.0.typelib \
         /usr/lib/x86_64-linux-gnu/girepository-1.0/GIRepository-2.0.typelib; do
  if [ -e "$p" ]; then log "gi.present=$p (noted)" ; else log "gi.absent=$p OK"; fi
done

# --- PATH check (secondary evidence; absence above is the real test) ---
log "path=$PATH"
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    log "python.path=$cmd RESOLVABLE $(command -v "$cmd") (BAD)"
  else
    log "python.path=$cmd absent OK"
  fi
done

# --- Mapper state: no libpython, no _rust_core.so in THIS process ---
if [ -r /proc/$$/maps ]; then
  if grep -qi 'libpython\|_rust_core\|PyO3' /proc/$$/maps 2>/dev/null; then
    log "maps.python=BAD"
    grep -i 'libpython\|_rust_core\|PyO3' /proc/$$/maps | head >> "$OUT/evidence.txt" || true
  else
    log "maps.no-python=OK"
  fi
fi
# fd listing: nothing python-flavoured open
if ls -l /proc/$$/fd/ >/dev/null 2>&1; then
  :
fi
log "probe.done"
