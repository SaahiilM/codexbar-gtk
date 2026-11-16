"""Tray integration: StatusNotifierItem + dbusmenu.

``Gtk.StatusIcon`` was removed in GTK4, so the tray presence is implemented
directly on top of the StatusNotifierItem protocol, plus a ``com.canonical.dbusmenu``
menu.  Plasma (and every other StatusNotifierItem host) renders that menu exactly
like a native application menu, right below the tray icon — which is the closest
Linux equivalent of the macOS menu bar.
"""

from __future__ import annotations

import os
from typing import Callable

try:  # pragma: no cover - dbus is optional at import time
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop

    HAVE_DBUS = True
except Exception:  # pragma: no cover
    dbus = None  # type: ignore[assignment]
    HAVE_DBUS = False

SNI_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

MENU_PATH = "/MenuBar"

# A stable bus name keeps the tray item alive across app restarts: the host
# tracks the item by this name instead of by a per-process unique name.
# A fixed name that follows the StatusNotifierItem naming convention. Keeping
# it stable means the tray host recognises the item across restarts of the app.
SERVICE_NAME = "org.kde.StatusNotifierItem-codexbar-gtk"


def _variant(value):
    """Wrap a plain Python value in the right dbus type."""
    if isinstance(
        value,
        (dbus.Struct, dbus.Array, dbus.Dictionary, dbus.Boolean, dbus.ByteArray),
    ):
        return value
    if isinstance(value, dbus.String):
        return value
    if isinstance(value, dbus.Int32) or isinstance(value, dbus.Int64):
        return value
    if isinstance(value, dbus.Double):
        return value
    if isinstance(value, bool):
        return dbus.Boolean(value)
    if isinstance(value, int):
        return dbus.Int32(value) if -(2**31) <= value < 2**31 else dbus.Int64(value)
    if isinstance(value, float):
        return dbus.Double(value)
    if isinstance(value, str):
        return dbus.String(value)
    if isinstance(value, dict):
        return dbus.Dictionary(value, signature="sv")
    if isinstance(value, (list, tuple)):
        return dbus.Array(value, signature="s")
    return dbus.String(str(value))


class _MenuItem:
    """One entry of the tray menu."""

    __slots__ = ("id", "label", "action", "children", "enabled", "visible", "separator")

    def __init__(
        self,
        item_id: int,
        label: str = "",
        action: Callable[[], None] | None = None,
        children: list["_MenuItem"] | None = None,
        enabled: bool = True,
        visible: bool = True,
        separator: bool = False,
    ) -> None:
        self.id = item_id
        self.label = label
        self.action = action
        self.children = children or []
        self.enabled = enabled
        self.visible = visible
        self.separator = separator


class _DBusMenu(dbus.service.Object if HAVE_DBUS else object):  # type: ignore[misc]
    """A minimal ``com.canonical.dbusmenu`` implementation."""

    def __init__(self, bus) -> None:
        super().__init__(bus, MENU_PATH)
        self._items: dict[int, _MenuItem] = {}
        self._root = 0
        self._revision = 1
        self._counter = 1

    # -- model ------------------------------------------------------------

    def set_root(self, item: _MenuItem) -> None:
        self._root = item.id
        self._items = {}

        def register(node: _MenuItem) -> None:
            self._items[node.id] = node
            for child in node.children:
                register(child)

        register(item)

    def replace_children(self, parent: _MenuItem, children: list[_MenuItem]) -> None:
        for child in children:
            self._items[child.id] = child
        parent.children = children

    def clear_children(self, parent: _MenuItem) -> None:
        parent.children = []

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    # -- layout -----------------------------------------------------------

    def _properties_for(self, item: _MenuItem) -> dict:
        if item.separator:
            return dbus.Dictionary(
                {"type": "separator", "visible": bool(item.visible)}, signature="sv"
            )
        props: dict = {
            "type": "standard",
            "label": item.label,
            "enabled": bool(item.enabled),
            "visible": bool(item.visible),
        }
        if item.children:
            props["children-display"] = "submenu"
        return dbus.Dictionary(props, signature="sv")

    def _layout(self, item: _MenuItem, depth: int):
        children = []
        # A recursion depth of -1 means "unlimited" in the dbusmenu protocol.
        if depth != 0:
            next_depth = depth - 1 if depth > 0 else depth
            for child in item.children:
                children.append(self._layout(child, next_depth))
        return dbus.Struct(
            (
                dbus.Int32(item.id),
                self._properties_for(item),
                dbus.Array(children, signature="v"),
            ),
            signature="ia{sv}av",
        )

    # -- com.canonical.dbusmenu ------------------------------------------

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent) -> None:
        """Notify hosts that they must fetch the new menu layout."""

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, item_id: int, recursion_depth: int, property_names):
        item = self._items.get(item_id, self._items.get(self._root))
        if item is None:
            empty = dbus.Struct(
                (
                    dbus.Int32(0),
                    dbus.Dictionary({}, signature="sv"),
                    dbus.Array([], signature="v"),
                ),
                signature="ia{sv}av",
            )
            return dbus.UInt32(self._revision), empty
        return dbus.UInt32(self._revision), self._layout(item, recursion_depth)

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        return [self.Event(*event) for event in events]

    @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="v")
    def Event(self, item_id: int, event_id: str, data, timestamp: int):
        if event_id in ("clicked", "activated"):
            item = self._items.get(item_id)
            if item is not None and item.action is not None:
                try:
                    item.action()
                except Exception:
                    pass
        return dbus.String("")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, item_id: int):
        return False

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="ai")
    def AboutToShowGroup(self, item_ids):
        return []

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, item_ids, property_names):
        result = []
        for item_id in item_ids:
            item = self._items.get(item_id)
            if item is not None:
                result.append((item.id, self._properties_for(item)))
        return result

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, item_id: int, name: str):
        item = self._items.get(item_id)
        if item is None:
            return dbus.String("")
        if name == "label":
            return dbus.String(item.label)
        if name == "enabled":
            return dbus.Boolean(item.enabled)
        if name == "visible":
            return dbus.Boolean(item.visible)
        return dbus.String("")

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def OnEvent(self, item_id: int, event_id: str):
        return dbus.String("")


class _StatusNotifierItem(dbus.service.Object if HAVE_DBUS else object):  # type: ignore[misc]
    """Exports one StatusNotifierItem on the session bus."""

    def __init__(
        self,
        bus,
        service_name: str,
        callback: Callable[[], None],
        context_callback: Callable[[], None],
    ) -> None:
        super().__init__(bus, "/StatusNotifierItem")
        self._bus = bus
        self._service_name = service_name
        self._callback = callback
        self._context_callback = context_callback
        empty_pixmaps = dbus.Array([], signature="(iiay)")
        self._properties: dict[str, object] = {
            "Category": "ApplicationStatus",
            "Id": "codexbar-gtk",
            "Title": "CodexBar",
            "Status": "Active",
            "IconName": "codexbar-gtk",
            "ToolTip": dbus.Struct(
                ("codexbar-gtk", empty_pixmaps, "CodexBar", ""),
                signature="sa(iiay)ss",
            ),
            # Export dbusmenu for hosts that render it themselves. Hosts that
            # delegate ContextMenu to the item use the app's action panel.
            "ItemIsMenu": False,
            "Menu": dbus.ObjectPath(MENU_PATH),
            "IconThemePath": "",
            "AttentionIconName": "codexbar-gtk-9",
            "AttentionIconPixmap": empty_pixmaps,
            "OverlayIconName": "",
            "OverlayIconPixmap": empty_pixmaps,
            "IconPixmap": empty_pixmaps,
            "WindowId": dbus.Int32(0),
        }

    # -- org.freedesktop.DBus.Properties ---------------------------------

    @dbus.service.method(
        "org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v"
    )
    def Get(self, interface_name: str, prop_name: str):
        if interface_name not in ("", SNI_IFACE):
            raise dbus.exceptions.DBusException(f"Unknown interface {interface_name}")
        if prop_name not in self._properties:
            raise dbus.exceptions.DBusException(f"Unknown property {prop_name}")
        return _variant(self._properties[prop_name])

    @dbus.service.method(
        "org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}"
    )
    def GetAll(self, interface_name: str):
        return {
            key: _variant(value)
            for key, value in self._properties.items()
            if interface_name in ("", SNI_IFACE)
        }

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ssv")
    def Set(self, interface_name: str, prop_name: str, value):
        if prop_name in self._properties:
            self._properties[prop_name] = value
            self._emit_changed(prop_name, value)

    # -- org.kde.StatusNotifierItem --------------------------------------

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def Activate(self, x: int, y: int) -> None:
        self._callback()

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def SecondaryActivate(self, x: int, y: int) -> None:
        self._context_callback()

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def ContextMenu(self, x: int, y: int) -> None:
        # Some SNI hosts delegate the context menu to the item instead of
        # rendering its dbusmenu property. Show our action panel for those hosts.
        self._context_callback()

    @dbus.service.method(SNI_IFACE, in_signature="iis")
    def Scroll(self, delta: int, orientation: str, _unused: int = 0) -> None:
        return None

    # -- signals ----------------------------------------------------------

    @dbus.service.signal("org.freedesktop.DBus.Properties", signature="sa{sv}as")
    def PropertiesChanged(
        self, interface_name, changed_properties, invalidated_properties
    ) -> None:
        """Publish property changes using dbus-python's supported signal API."""

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewIcon(self) -> None:
        """The icon name or pixels changed."""

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewToolTip(self) -> None:
        """The tooltip changed."""

    @dbus.service.signal(SNI_IFACE, signature="s")
    def NewStatus(self, status) -> None:
        """The item's visibility status changed."""

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewTitle(self) -> None:
        """The title changed."""

    # -- helpers ----------------------------------------------------------

    def _emit_changed(self, prop_name: str, value) -> None:
        self.PropertiesChanged(SNI_IFACE, {prop_name: _variant(value)}, [])

    def set_property(self, prop_name: str, value) -> None:
        self._properties[prop_name] = value
        self._emit_changed(prop_name, value)
        # Plasma relies on these dedicated signals as well as PropertiesChanged.
        if prop_name == "Status":
            self.NewStatus(value)
        else:
            signal = {
                "IconName": self.NewIcon,
                "ToolTip": self.NewToolTip,
                "Title": self.NewTitle,
                "IconPixmap": self.NewIcon,
            }.get(prop_name)
            if signal is not None:
                signal()


class TrayIcon:
    """Registers a StatusNotifierItem (and its dbusmenu) with the session bus."""

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_context_menu: Callable[[], None] | None = None,
    ) -> None:
        self.on_activate = on_activate
        self.on_context_menu = on_context_menu or on_activate
        self.available = False
        self._item: _StatusNotifierItem | None = None
        self._menu: _DBusMenu | None = None
        self._bus = None
        self._counter = 0
        self._root_item: _MenuItem | None = None
        self._registered = False

    # -- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        if not HAVE_DBUS:
            return False
        try:
            DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SessionBus()
            self._counter += 1
            service_name = (
                f"org.kde.StatusNotifierItem-{os.getpid()}-1"
                if os.environ.get("CODEXBAR_TRAY_PID_NAME")
                else SERVICE_NAME
            )
            self._item = _StatusNotifierItem(
                self._bus, service_name, self._on_activate, self._on_context_menu
            )
            reply = self._bus.request_name(service_name)
            if int(reply) not in (1, 4):  # PRIMARY_OWNER or ALREADY_OWNER
                self._item = None
                return False
            self._menu = _DBusMenu(self._bus)
            self._root_item = _MenuItem(0, "CodexBar")
            self._menu.set_root(self._root_item)
            self._watch_watcher()
            self.available = True
        except Exception:
            self.available = False
        return self.available

    def register(self) -> None:
        """Announce the item to the watcher.

        This is deliberately separate from :meth:`start`: hosts read the item's
        properties once, when the item appears, so the icon has to be in place
        before the item is published.
        """
        if not self.available or self._registered:
            return
        self._register_with_host()
        self._registered = True

    def _watch_watcher(self) -> None:
        """Re-register whenever the StatusNotifierItem watcher comes back.

        The watcher lives inside plasmashell, so it disappears and reappears
        whenever Plasma restarts. Without re-registering, the tray entry would
        silently vanish.
        """
        try:
            self._bus.add_signal_receiver(
                self._on_watcher_changed,
                dbus_interface="org.freedesktop.DBus",
                signal_name="NameOwnerChanged",
                path="/org/freedesktop/DBus",
                sender_keyword="sender",
            )
        except Exception:
            pass

    def _on_watcher_changed(self, name, old_owner, new_owner, **kwargs) -> None:
        if name != WATCHER_NAME or not new_owner:
            return
        self._registered = False
        self.register()

    def _on_activate(self) -> None:
        try:
            self.on_activate()
        except Exception:
            pass

    def _on_context_menu(self) -> None:
        try:
            self.on_context_menu()
        except Exception:
            pass

    def _register_with_host(self) -> None:
        """Announce the item to the StatusNotifierItem watcher.

        Registering by object path is what Plasma's tray host understands; the
        service name form is kept as a fallback for other hosts.
        """
        for argument in (self._item._service_name, "/StatusNotifierItem"):
            try:
                watcher = self._bus.get_object(WATCHER_NAME, WATCHER_PATH)
                watcher.RegisterStatusNotifierItem(argument)
                return
            except Exception:
                continue

    # -- content ----------------------------------------------------------

    def set_menu(self, entries: list) -> None:
        """Replace the tray menu.

        ``entries`` is a list of ``(label, action)`` tuples; a label of ``None``
        inserts a separator.
        """
        if self._menu is None or self._root_item is None:
            return
        children: list[_MenuItem] = []
        for label, action in entries:
            item_id = self._menu._next_id()
            if label is None:
                children.append(_MenuItem(item_id, "", None, separator=True))
            else:
                children.append(_MenuItem(item_id, label, action))
        self._menu.replace_children(self._root_item, children)
        self._menu._revision += 1
        self._notify_layout_updated()

    def _notify_layout_updated(self) -> None:
        if self._menu is None:
            return
        self._menu.LayoutUpdated(
            dbus.UInt32(self._menu._revision), dbus.Int32(self._menu._root)
        )

    def update(
        self,
        icon_name: str,
        tooltip_title: str,
        tooltip_body: str,
        pixmap: tuple[int, int, bytes] | None = None,
    ) -> None:
        if self._item is None:
            return
        tooltip_pixmaps = dbus.Array([], signature="(iiay)")
        tooltip_icon_name = icon_name
        if pixmap is not None:
            width, height, data = pixmap
            tooltip_pixmaps = dbus.Array(
                [
                    dbus.Struct(
                        (dbus.Int32(width), dbus.Int32(height), dbus.ByteArray(data)),
                        signature="iiay",
                    )
                ],
                signature="(iiay)",
            )
            # The custom meter/percentage icon is not installed in icon themes;
            # include its pixmap in the tooltip instead of advertising a name
            # that tray hosts cannot resolve.
            tooltip_icon_name = ""
        tooltip = dbus.Struct(
            (
                tooltip_icon_name,
                tooltip_pixmaps,
                tooltip_title,
                tooltip_body,
            ),
            signature="sa(iiay)ss",
        )
        if pixmap is not None:
            width, height, data = pixmap
            self._item.set_property(
                "IconPixmap",
                dbus.Array(
                    [
                        dbus.Struct(
                            (
                                dbus.Int32(width),
                                dbus.Int32(height),
                                dbus.ByteArray(data),
                            ),
                            signature="iiay",
                        )
                    ],
                    signature="(iiay)",
                ),
            )
            # Plasma renders the pixmap when no themed icon name is set. Themed
            # names are not resolved reliably for user-installed icons, so the
            # pixels are the primary representation.
            self._item.set_property("IconName", "")
        else:
            self._item.set_property("IconName", icon_name)
        self._item.set_property("ToolTip", tooltip)

    def set_status(self, status: str) -> None:
        if self._item is not None:
            self._item.set_property("Status", status)
