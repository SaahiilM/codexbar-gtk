"""Exercise tray notifications on a private D-Bus session, without GTK or accounts."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAVE_DBUS = (
    shutil.which("dbus-run-session") is not None
    and importlib.util.find_spec("dbus") is not None
    and importlib.util.find_spec("gi") is not None
)

SETUP = """
import importlib.util
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Load the protocol module directly: importing ui/__init__.py requires GTK.
spec = importlib.util.spec_from_file_location('tray', 'codexbar_gtk/ui/tray.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
MENU_IFACE, MENU_PATH, SNI_IFACE = module.MENU_IFACE, module.MENU_PATH, module.SNI_IFACE
TrayIcon, _DBusMenu = module.TrayIcon, module._DBusMenu
_MenuItem, _StatusNotifierItem = module._MenuItem, module._StatusNotifierItem

DBusGMainLoop(set_as_default=True)
receiver = dbus.SessionBus(private=True)
sender = dbus.SessionBus(private=True)
messages = []

def record(*args, message):
    messages.append((message.get_interface(), message.get_member(),
                     str(message.get_signature()), args))

receiver.add_signal_receiver(record, path='/StatusNotifierItem', message_keyword='message')
receiver.add_signal_receiver(record, path=MENU_PATH, message_keyword='message')

def drain():
    loop = GLib.MainLoop()
    GLib.timeout_add(100, lambda: (loop.quit(), False)[1])
    loop.run()

tray = TrayIcon(lambda: None)
tray._bus = sender
tray._item = _StatusNotifierItem(sender, 'test.codexbar', lambda: None, lambda: None)
tray._menu = _DBusMenu(sender)
tray._root_item = _MenuItem(0, 'CodexBar')
tray._menu.set_root(tray._root_item)
tray.available = True
"""


@unittest.skipUnless(HAVE_DBUS, "requires dbus-python, PyGObject and dbus-run-session")
class TraySignalTests(unittest.TestCase):
    def run_on_private_bus(self, code: str) -> None:
        result = subprocess.run(
            [
                "dbus-run-session",
                "--",
                sys.executable,
                "-c",
                SETUP + textwrap.dedent(code),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_refresh_notifies_host_of_new_tooltip_and_icon(self) -> None:
        self.run_on_private_bus(r"""
            tray.update('codexbar-gtk', 'CodexBar GTK', 'Provider data unavailable')
            drain()
            messages.clear()
            tray.update('', 'CodexBar GTK · Codex', 'Session: 25%', (1, 1, b'\xff\x10\xa3\x7f'))
            drain()

            assert (SNI_IFACE, 'NewToolTip', '', ()) in messages, messages
            assert (SNI_IFACE, 'NewIcon', '', ()) in messages, messages
            changes = [args for interface, name, signature, args in messages
                       if name == 'PropertiesChanged' and signature == 'sa{sv}as']
            assert any(str(args[0]) == SNI_IFACE
                       and 'ToolTip' in args[1]
                       and str(args[1]['ToolTip'][2]) == 'CodexBar GTK · Codex'
                       and str(args[1]['ToolTip'][3]) == 'Session: 25%'
                       for args in changes), messages
            assert any('IconPixmap' in args[1] for args in changes), messages
        """)

    def test_status_signal_contains_new_status(self) -> None:
        self.run_on_private_bus("""
            tray.set_status('Passive')
            drain()
            assert (SNI_IFACE, 'NewStatus', 's', ('Passive',)) in messages, messages
        """)

    def test_menu_replacement_notifies_host_of_new_layout(self) -> None:
        self.run_on_private_bus("""
            tray.set_menu([('Refresh', lambda: None)])
            drain()
            updates = [args for interface, name, signature, args in messages
                       if interface == MENU_IFACE and name == 'LayoutUpdated' and signature == 'ui']
            assert len(updates) == 1, messages
            assert tuple(map(int, updates[0])) == (2, 0), updates
        """)
