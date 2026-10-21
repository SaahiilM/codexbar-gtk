#!/usr/bin/env python3
"""Send a key to the focused X11 window (development helper).

    python3 tools/send_key.py Escape
    python3 tools/send_key.py ctrl+r
"""

from __future__ import annotations

import ctypes
import sys

X11 = ctypes.CDLL("libX11.so.6")
XTST = ctypes.CDLL("libXtst.so.6")

X11.XOpenDisplay.restype = ctypes.c_void_p
X11.XOpenDisplay.argtypes = [ctypes.c_char_p]
X11.XFlush.argtypes = [ctypes.c_void_p]
XTST.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

# X11 keysyms for the keys we need
KEYSYMS = {
    "escape": 9,
    "return": 36,
    "enter": 36,
    "tab": 23,
    "space": 65,
    "up": 111,
    "down": 116,
    "left": 113,
    "right": 114,
    "home": 110,
    "end": 115,
    "backspace": 22,
    "pageup": 112,
    "pagedown": 117,
}
for char in "abcdefghijklmnopqrstuvwxyz0123456789":
    KEYSYMS[char] = ord(char)
for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYSYMS[char] = ord(char)


def keysym(name: str) -> int:
    if name in KEYSYMS:
        return KEYSYMS[name]
    if name.startswith("F") and name[1:].isdigit():
        return 0x70 + int(name[1:]) - 1
    return ord(name)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: send_key.py <key> [key ...]")
        return 1
    display = X11.XOpenDisplay(None)
    if not display:
        print("no display")
        return 1
    for name in sys.argv[1:]:
        modifier = None
        if "+" in name:
            modifier, name = name.split("+", 1)
        code = keysym(name)
        if modifier == "ctrl":
            # Control_L
            XTST.XTestFakeKeyEvent(display, 37, 1, 0)
        XTST.XTestFakeKeyEvent(display, code, 1, 0)
        XTST.XTestFakeKeyEvent(display, code, 0, 0)
        if modifier == "ctrl":
            XTST.XTestFakeKeyEvent(display, 37, 0, 0)
    X11.XFlush(display)
    print("sent:", " ".join(sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
