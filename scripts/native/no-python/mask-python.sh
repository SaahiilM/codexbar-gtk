#!/bin/bash
# unshare(-r -m) fallback helper: MUST run as the new root in a fresh
# mount namespace (rootless user namespace). Masks Python by mounting an
# empty tmpfs / dev-null style overlay read-only over the probe paths,
# then execs the real payload. Any mount failure is fatal (no fake pass).
set -euo pipefail
MASKED=0
mask() {
  local target="$1"
  if mount --bind --ro /dev/null "$target" 2>/dev/null || \
     mount --bind --ro /dev/null "$target" 2>>"$MASK_OUT/evidence.txt"; then
    echo "mask.bound=$target OK" >> "$MASK_OUT/evidence.txt"
    MASKED=$((MASKED+1))
  else
    echo "mask.failed=$target BAD" >> "$MASK_OUT/evidence.txt"
    return 1
  fi
}
# argv[1] = evidence dir; remaining argv = payload command
MASK_OUT="$1"; shift
printf 'mask.started masked=%d\n' "$MASKED" >> "$MASK_OUT/evidence.txt"
for p in /usr/bin/python3 /usr/bin/python \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so.1 \
         /usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    mask "$p" || { echo "mask.abort" >> "$MASK_OUT/evidence.txt"; exit 3; }
  fi
done
printf 'mask.done masked=%d\n' "$MASKED" >> "$MASK_OUT/evidence.txt"
exec "$@"
