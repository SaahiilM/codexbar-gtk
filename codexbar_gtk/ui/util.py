"""Small GTK helpers."""

from __future__ import annotations

from gi.repository import Gtk


def iter_children(widget: Gtk.Widget):
    """Iterate over a container's children (GTK4 removed ``get_children`` on some widgets)."""
    child = widget.get_first_child()
    while child is not None:
        next_child = child.get_next_sibling()
        yield child
        child = next_child


def clear_container(widget: Gtk.Widget) -> None:
    """Remove every child from a container."""
    for child in list(iter_children(widget)):
        widget.remove(child)
