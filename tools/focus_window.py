#!/usr/bin/env python3
"""Raise a window by title (X11 helper used for screenshots during development).

    python3 tools/focus_window.py CodexBar
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

xlib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
xlib.XDefaultRootWindow.restype = ctypes.c_ulong
xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
xlib.XQueryTree.restype = ctypes.c_int
xlib.XQueryTree.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
    ctypes.POINTER(ctypes.c_uint),
]
xlib.XFetchName.restype = ctypes.c_int
xlib.XFetchName.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_char_p),
]
xlib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
xlib.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
xlib.XFlush.argtypes = [ctypes.c_void_p]


def find(display, root, needle: str) -> int:
    children = ctypes.POINTER(ctypes.c_ulong)()
    root_return = ctypes.c_ulong()
    parent = ctypes.c_ulong()
    count = ctypes.c_uint()
    if not xlib.XQueryTree(display, root, ctypes.byref(root_return), ctypes.byref(parent),
                           ctypes.byref(children), ctypes.byref(count)):
        return 0
    for index in range(count.value):
        window = children[index]
        name = ctypes.c_char_p()
        if xlib.XFetchName(display, window, ctypes.byref(name)) and name.value:
            if needle.lower() in name.value.decode(errors="ignore").lower():
                xlib.XFree = getattr(xlib, "XFree", None)
                return window
        child = find(display, window, needle)
        if child:
            return child
    return 0


def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else "CodexBar"
    display = xlib.XOpenDisplay(None)
    if not display:
        print("no display")
        return 1
    root = xlib.XDefaultRootWindow(display)
    window = find(display, root, needle)
    if not window:
        print("window not found")
        return 1
    xlib.XRaiseWindow(display, window)
    xlib.XSetInputFocus(display, window, 1, 0)
    xlib.XFlush(display)
    print(f"raised 0x{window:x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
