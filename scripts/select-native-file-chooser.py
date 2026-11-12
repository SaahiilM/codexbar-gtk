#!/usr/bin/env python3
"""Select a synthetic file in the app's live GTK chooser through AT-SPI."""

from __future__ import annotations

import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi


def descendants(accessible, depth=0):
    if depth > 40:
        return
    yield accessible
    try:
        count = accessible.get_child_count()
    except Exception:
        return
    for index in range(count):
        try:
            child = accessible.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            yield from descendants(child, depth + 1)


def app_objects(app_pid: int):
    desktop = Atspi.get_desktop(0)
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if app is not None and app.get_process_id() == app_pid:
            yield from descendants(app)


def states(accessible):
    return accessible.get_state_set()


def find_dialog(app_pid: int, title: str):
    matches = [
        item
        for item in app_objects(app_pid)
        if item.get_role_name() == "dialog" and item.get_name() == title
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def read_text(accessible) -> str:
    count = Atspi.Text.get_character_count(accessible)
    return Atspi.Text.get_text(accessible, 0, count)


def focused_entry(dialog, app_pid: int):
    entries = [
        item
        for item in descendants(dialog)
        if item.get_role_name() in ("text", "entry")
        and states(item).contains(Atspi.StateType.FOCUSED)
        and states(item).contains(Atspi.StateType.SHOWING)
        and states(item).contains(Atspi.StateType.SENSITIVE)
        and "EditableText" in item.get_interfaces()
        and "Text" in item.get_interfaces()
        and item.get_process_id() == app_pid
    ]
    if len(entries) != 1:
        return None
    entry = entries[0]
    extents = entry.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
    if extents.width <= 0 or extents.height <= 0:
        return None
    return entry


def fail(message: str) -> None:
    raise SystemExit(message)


def set_path(app_pid: int, title: str, path: str) -> None:
    deadline = time.monotonic() + 5
    dialog = None
    entry = None
    while time.monotonic() < deadline:
        dialog = find_dialog(app_pid, title)
        if dialog is not None:
            entry = focused_entry(dialog, app_pid)
            if entry is not None:
                break
        time.sleep(0.05)
    if dialog is None:
        fail(f"actual chooser {title!r} is not exposed by app PID {app_pid}")
    if entry is None:
        fail(
            f"actual chooser has no unique focused EditableText for app PID {app_pid}; "
            "Ctrl+L must expose the GTK location entry first"
        )

    before = read_text(entry)
    changed = Atspi.EditableText.set_text_contents(entry, path)
    if not changed:
        fail("GTK EditableText rejected the synthetic chooser path")

    deadline = time.monotonic() + 3
    current = read_text(entry)
    while current != path and time.monotonic() < deadline:
        time.sleep(0.05)
        current = read_text(entry)
    if current != path:
        fail(f"chooser location entry did not retain exact fixture path: {current!r}")
    # Read it again after a short, bounded GTK main-loop turn. No Return has
    # been sent yet, so this is the exact text GTK will receive for selection.
    time.sleep(0.1)
    settled = read_text(entry)
    print(
        f"ACTUAL_CHOOSER_ENTRY pid={entry.get_process_id()} role={entry.get_role_name()!r} "
        f"focused={states(entry).contains(Atspi.StateType.FOCUSED)} "
        f"before={before!r} exact_path={settled!r}"
    )
    if settled != path:
        fail("chooser location entry changed after the GTK event-loop settle")


def read_path(app_pid: int, title: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        dialog = find_dialog(app_pid, title)
        entry = focused_entry(dialog, app_pid) if dialog is not None else None
        if entry is not None:
            print(
                f"ACTUAL_CHOOSER_ENTRY pid={entry.get_process_id()} "
                f"role={entry.get_role_name()!r} focused=True text={read_text(entry)!r}"
            )
            return
        time.sleep(0.05)
    fail(f"actual chooser has no unique visible, focused editable entry for app PID {app_pid}")


def accept(app_pid: int, title: str, path: str) -> None:
    deadline = time.monotonic() + 5
    dialog = None
    button = None
    while time.monotonic() < deadline:
        dialog = find_dialog(app_pid, title)
        if dialog is not None:
            entries = [
                item
                for item in descendants(dialog)
                if item.get_role_name() in ("text", "entry")
                and "Text" in item.get_interfaces()
                and read_text(item) == path
            ]
            buttons = [
                item
                for item in descendants(dialog)
                if item.get_role_name() == "push button" and item.get_name() == "Import"
            ]
            enabled = [
                item
                for item in buttons
                if states(item).contains(Atspi.StateType.SHOWING)
                and states(item).contains(Atspi.StateType.SENSITIVE)
            ]
            if (
                len(entries) == 1
                and entries[0].get_process_id() == app_pid
                and len(enabled) == 1
            ):
                button = enabled[0]
                break
        time.sleep(0.05)

    if dialog is None:
        fail(f"actual chooser {title!r} disappeared before its accept action")
    if button is None:
        fail(
            f"refusing chooser accept: exact path was not paired with one enabled, "
            f"visible Import action (buttons found: {len(buttons) if 'buttons' in locals() else 0})"
        )
    action = button.get_action_iface()
    if button.get_process_id() != app_pid:
        fail("refusing to invoke an Import action owned by a different process")
    print(
        f"ACTUAL_CHOOSER_IMPORT_ACTION pid={button.get_process_id()} "
        f"action_count={action.get_n_actions()}"
    )
    if not action.do_action(0):
        fail("the visible GTK chooser Import action returned false")
    print("INVOKED actual GTK chooser Import action")


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[1] not in ("read", "set", "accept"):
        fail(
            "usage: select-native-file-chooser.py {read|set|accept} APP_PID "
            "DIALOG_TITLE ABSOLUTE_FIXTURE_PATH"
        )
    mode, pid_arg, title, path = sys.argv[1:]
    app_pid = int(pid_arg)
    Atspi.init()
    if mode == "set":
        set_path(app_pid, title, path)
    elif mode == "read":
        read_path(app_pid, title)
    else:
        accept(app_pid, title, path)


if __name__ == "__main__":
    main()
