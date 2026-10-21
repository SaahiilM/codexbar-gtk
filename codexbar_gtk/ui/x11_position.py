"""Move a top-level window with plain X11.

GTK 4 removed ``Gtk.Window.move`` so that Wayland compositors stay in charge of
window placement. On X11 and XWayland sessions we can still place the compact
panel exactly where we want it, which is what a menu bar popover needs.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os

_INITIALISED = False
_X11 = None
_LIBX11 = None


def _load() -> bool:
    global _INITIALISED, _X11, _LIBX11
    if _INITIALISED:
        return _X11 is not None
    _INITIALISED = True
    if os.environ.get("GDK_BACKEND", "").startswith("wayland"):
        return False
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XQueryTree.restype = ctypes.c_int
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XFetchName.restype = ctypes.c_int
        lib.XFetchName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        lib.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        lib.XGetGeometry.restype = ctypes.c_int
        lib.XGetGeometry.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XDisplayWidth.restype = ctypes.c_int
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayHeight.restype = ctypes.c_int
        lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XFree = getattr(lib, "XFree", None)
        _LIBX11 = lib
        _X11 = True
    except Exception:
        _X11 = False
    return _X11


def _walk(display, root: int, needle: str):
    children = ctypes.POINTER(ctypes.c_ulong)()
    root_return = ctypes.c_ulong()
    parent = ctypes.c_ulong()
    count = ctypes.c_uint()
    if not _LIBX11.XQueryTree(
        display, root, ctypes.byref(root_return), ctypes.byref(parent),
        ctypes.byref(children), ctypes.byref(count)
    ):
        return 0
    for index in range(count.value):
        window = children[index]
        name = ctypes.c_char_p()
        if _LIBX11.XFetchName(display, window, ctypes.byref(name)) and name.value:
            if needle in name.value.decode(errors="ignore"):
                return window
        found = _walk(display, window, needle)
        if found:
            return found
    return 0


def move_window_to_corner(title: str, corner: str = "bottom-right", margin: int = 12) -> bool:
    """Move the window with the given title to a screen corner.

    Returns True when the window was found and moved.
    """
    if not _load():
        return False
    try:
        display = _LIBX11.XOpenDisplay(None)
        if not display:
            return False
        root = _LIBX11.XDefaultRootWindow(display)
        window = _walk(display, root, title)
        if not window:
            return False

        root_return = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        width = ctypes.c_uint()
        height = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        _LIBX11.XGetGeometry(
            display, window, ctypes.byref(root_return), ctypes.byref(x), ctypes.byref(y),
            ctypes.byref(width), ctypes.byref(height), ctypes.byref(border), ctypes.byref(depth),
        )

        screen_width = _LIBX11.XDisplayWidth(display, 0)
        screen_height = _LIBX11.XDisplayHeight(display, 0)

        target_x = screen_width - width.value - margin
        target_y = margin
        if corner == "bottom-right":
            target_y = screen_height - height.value - margin - 48  # leave room for the panel
        elif corner == "top-left":
            target_x = margin

        _LIBX11.XMoveResizeWindow(
            display, window, int(target_x), int(target_y), width.value, height.value, 0
        )
        _LIBX11.XFlush(display)
        return True
    except Exception:
        return False
