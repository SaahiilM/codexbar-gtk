#!/usr/bin/env python3
"""Minimal StatusNotifierItem probe used to debug tray visibility.

    python3 tools/sni_probe.py [icon-name]
"""

from __future__ import annotations

import sys
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

ICON = sys.argv[1] if len(sys.argv) > 1 else "utilities-terminal"

SNI = "org.kde.StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"


class Item(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, "/StatusNotifierItem")
        self.props = {
            "Category": "ApplicationStatus",
            "Id": "codexbar-probe",
            "Title": "CodexBar probe",
            "Status": "Active",
            "IconName": ICON,
            "ItemIsMenu": False,
            "Menu": "/MenuBar",
            "ToolTip": dbus.Struct(
                ("codexbar-probe", dbus.Array([], signature="i"), "CodexBar", "probe"),
                signature="sa(iiay)ss",
            ),
        }

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.props.get(prop, "")

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.props

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ssv")
    def Set(self, interface, prop, value):
        self.props[prop] = value

    @dbus.service.method(SNI, in_signature="ii")
    def Activate(self, x, y):
        pass

    @dbus.service.method(SNI, in_signature="ii")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(SNI, in_signature="ii")
    def ContextMenu(self, x, y):
        pass

    @dbus.service.method(SNI, in_signature="iis")
    def Scroll(self, delta, orientation, timestamp):
        pass


def main():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = f"org.kde.StatusNotifierItem-{__import__('os').getpid()}-1"
    item = Item(bus)
    bus.request_name(name)
    watcher = bus.get_object(WATCHER, "/StatusNotifierWatcher")
    watcher.RegisterStatusNotifierItem("/StatusNotifierItem")
    print(f"registered probe with icon {ICON!r}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
