#!/usr/bin/env python3
"""Render activation templates with an absolute binary path.

Distinct encoders, not sed: desktop Exec uses double-quote wrapping; systemd
ExecStart uses the same double-quote wrapping but systemd expands %/$ only
outside quotes, so paths are validated upstream (install-native.sh rejects
unsupported characters). This renderer replaces whole lines without
interpreting replacement metacharacters (&, |, \\, ...).
"""
import sys

template, binary, mode = sys.argv[1], sys.argv[2], sys.argv[3]
key = "Exec=" if mode == "desktop" else "ExecStart="
quoted = '"%s"' % binary
with open(template, encoding="utf-8") as handle:
    lines = handle.read().splitlines()
out = []
replaced = False
for line in lines:
    if line.startswith(key):
        suffix = " %U" if mode == "desktop" else ""
        out.append("%s%s%s" % (key, quoted, suffix))
        replaced = True
    else:
        out.append(line)
if not replaced:
    sys.exit("template %s has no %s line" % (template, key))
sys.stdout.write("\n".join(out) + "\n")
