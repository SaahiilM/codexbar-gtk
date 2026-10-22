#!/usr/bin/env python3
"""Raise and focus an X11 window by name.

The KDE Plasma panel runs on Wayland, so the compositor keeps native windows above
XWayland clients. Asking the window manager to activate the window through
_NET_ACTIVE_WINDOW is the way an X11 client can come to the front.

    python3 tools/activate_window.py "CodexBar"
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

NET_ACTIVE_WINDOW = 2
CURRENT_TIME = 0

X11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
X11.XOpenDisplay.restype = ctypes.c_void_p
X11.XOpenDisplay.argtypes = [ctypes.c_char_p]
X11.XDefaultRootWindow.restype = ctypes.c_ulong
X11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
X11.XQueryTree.restype = ctypes.c_int
X11.XQueryTree.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
    ctypes.POINTER(ctypes.c_uint),
]
X11.XFetchName.restype = ctypes.c_int
X11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
X11.XInternAtom.restype = ctypes.c_ulong
X11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
X11.XSendEvent.restype = ctypes.c_int
X11.XSendEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p,
]
X11.XFlush.argtypes = [ctypes.c_void_p]
X11.XSetInputFocus.restype = ctypes.c_int
X11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]


class XClientMessageData(ctypes.Union):
    _fields_ = [("b", ctypes.c_char * 20), ("l", ctypes.c_long * 5)]


class XEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", XClientMessageData),
    ]


def find(display, root: int, needle: str) -> int:
    children = ctypes.POINTER(ctypes.c_ulong)()
    parent = ctypes.c_ulong()
    root_return = ctypes.c_ulong()
    count = ctypes.c_uint()
    if not X11.XQueryTree(display, root, ctypes.byref(root_return), ctypes.byref(parent),
                          ctypes.byref(children), ctypes.byref(count)):
        return 0
    for index in range(count.value):
        window = children[index]
        name = ctypes.c_char_p()
        if X11.XFetchName(display, window, ctypes.byref(name)) and name.value:
            if needle.lower() in name.value.decode(errors="ignore").lower():
                return window
        found = find(display, window, needle)
        if found:
            return found
    return 0


def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else "CodexBar"
    display = X11.XOpenDisplay(None)
    if not display:
        print("no display")
        return 1
    root = X11.XDefaultRootWindow(display)
    window = find(display, root, needle)
    if not window:
        print("window not found")
        return 1

    event = XEvent()
    event.type = 33  # ClientMessage
    event.window = window
    event.message_type = X11.XInternAtom(display, b"_NET_ACTIVE_WINDOW", 0)
    event.format = 32
    event.data.l[0] = CURRENT_TIME
    event.data.l[1] = 2  # source: pager / normal
    X11.XSendEvent(display, root, 0, 0, ctypes.byref(event))
    X11.XSetInputFocus(display, window, 1, 0)
    X11.XFlush(display)
    print(f"activated 0x{window:x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
