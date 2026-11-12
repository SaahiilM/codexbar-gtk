#!/usr/bin/env python3
"""Select a synthetic file in the app's live GTK chooser through AT-SPI."""

from __future__ import annotations

import sys
import json
import os
import pathlib
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


def action_names(accessible):
    try:
        iface = accessible.get_action_iface()
        if iface is None:
            return []
        names = []
        for index in range(iface.get_n_actions()):
            try:
                names.append(iface.get_action_name(index))
            except Exception as error:
                names.append(f"<unreadable:{type(error).__name__}>")
        return names
    except Exception:
        return []


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
            basename = path.rsplit("/", 1)[-1]
            selected_rows = [item for item in descendants(dialog)
                             if item.get_role_name() == "table row"
                             and basename in (item.get_name() or "")
                             and states(item).contains(Atspi.StateType.SELECTED)
                             and item.get_process_id() == app_pid]
            location_entry = focused_entry(dialog, app_pid)
            exact_location = (location_entry is not None
                              and read_text(location_entry) == path)
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
                (len(selected_rows) == 1 or exact_location)
                and len(enabled) == 1
            ):
                button = enabled[0]
                break
        time.sleep(0.05)

    if dialog is None:
        fail(f"actual chooser {title!r} disappeared before its accept action")
    if button is None:
        fail(
            f"refusing chooser accept: exact synthetic-home row or editable path was not selected with "
            f"one enabled, visible Import action (selected rows: "
            f"{len(selected_rows) if 'selected_rows' in locals() else 0}; "
            f"exact_path={exact_location if 'exact_location' in locals() else False}; "
            f"buttons: {len(buttons) if 'buttons' in locals() else 0})"
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


def select_file_row(app_pid: int, title: str, path: str) -> None:
    """Select an exact visible fixture filename through GTK's accessible list."""
    basename = path.rsplit("/", 1)[-1]
    deadline = time.monotonic() + 8
    last = []
    dialog_tree = []
    home_opened = False
    home_attempted = False
    while time.monotonic() < deadline:
        dialog = find_dialog(app_pid, title)
        if dialog is not None:
            dialog_tree = [
                {"name": item.get_name(), "role": item.get_role_name(),
                 "pid": int(item.get_process_id()),
                 "states": sorted(state.value_nick for state in states(item).get_states()),
                 "interfaces": item.get_interfaces(),
                 "actions": action_names(item),
                 "text": (read_text(item) if "Text" in item.get_interfaces() else None)}
                for item in descendants(dialog)
            ][:400]
            named = [item for item in descendants(dialog)
                     if item.get_name() == basename and item.get_role_name() == "label"
                     and states(item).contains(Atspi.StateType.SHOWING)
                     and states(item).contains(Atspi.StateType.SENSITIVE)
                     and item.get_process_id() == app_pid]
            last = [(item.get_role_name(), item.get_interfaces()) for item in named]
            if not named and not home_attempted:
                home_rows = [item for item in descendants(dialog)
                             if item.get_name() == "Open your personal folder"
                             and item.get_role_name() == "list item"
                             and item.get_process_id() == app_pid
                             and states(item).contains(Atspi.StateType.SHOWING)
                             and states(item).contains(Atspi.StateType.SENSITIVE)]
                if len(home_rows) == 1:
                    home_attempted = True
                    item = home_rows[0]
                    parent = item.get_parent()
                    selection = parent.get_selection_iface() if parent is not None else None
                    if selection is not None:
                        for index in range(parent.get_child_count()):
                            child = parent.get_child_at_index(index)
                            if (child is not None and child.get_name() == "Open your personal folder"
                                    and child.get_process_id() == app_pid):
                                home_opened = bool(selection.select_child(index))
                                break
                    actions = item.get_action_iface()
                    action_result = None
                    if actions is not None and actions.get_n_actions() == 1:
                        action_result = bool(actions.do_action(0))
                        home_opened = home_opened or action_result
                    # GTK exposes the chooser's own item.visit action through
                    # AT-SPI on its same-process widget action group. Selecting
                    # the Home place alone only highlights it; visit performs
                    # the chooser's actual location navigation.
                    action_groups = [node for node in descendants(dialog)
                                     if node.get_process_id() == app_pid
                                     and node.get_role_name() == "panel"
                                     and states(node).contains(Atspi.StateType.SHOWING)
                                     and "item.visit" in action_names(node)]
                    if len(action_groups) == 1:
                        group = action_groups[0].get_action_iface()
                        index = action_names(action_groups[0]).index("item.visit")
                        visited = bool(group.do_action(index))
                        print(f"ACTUAL_CHOOSER_ITEM_VISIT_ACTION pid={app_pid} "
                              f"action=item.visit result={visited}")
                    if home_opened:
                        print(f"ACTUAL_CHOOSER_HOME_SELECTION pid={app_pid} "
                              f"name={item.get_name()!r} selection={home_opened} "
                              f"action_result={action_result}")
            if len(named) == 1:
                item = named[0]
                ancestor = item.get_parent()
                row = None
                selection_parent = None
                while ancestor is not None:
                    if ancestor.get_role_name() == "table row":
                        row = ancestor
                    if "Selection" in ancestor.get_interfaces():
                        selection_parent = ancestor
                        break
                    ancestor = ancestor.get_parent()
                if row is not None and selection_parent is not None:
                    selection = selection_parent.get_selection_iface()
                    for index in range(selection_parent.get_child_count()):
                        child = selection_parent.get_child_at_index(index)
                        if (child is not None and child.get_role_name() == "table row"
                                and basename in (child.get_name() or "")
                                and child.get_process_id() == app_pid):
                            if selection.select_child(index):
                                print(f"ACTUAL_CHOOSER_SELECTED_ROW pid={app_pid} "
                                      f"role={row.get_role_name()!r} filename={basename!r} "
                                      f"synthetic_home_row={row.get_name()!r}")
                                return
        time.sleep(0.05)
    diagnostic_dir = os.environ.get("NATIVE_CHOOSER_DIAGNOSTIC_DIR")
    diagnostic_path = None
    if diagnostic_dir:
        try:
            directory = pathlib.Path(diagnostic_dir)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            diagnostic_path = directory / "import-chooser-atspi-tree.json"
            diagnostic_path.write_text(json.dumps(dialog_tree, indent=2) + "\n", encoding="utf-8")
            diagnostic_path.chmod(0o600)
        except OSError:
            diagnostic_path = None
    fail(f"no unique actionable chooser row for {basename!r} in app PID {app_pid}; "
         f"home_action_invoked={home_opened}; "
         f"observed={last!r}; diagnostic_tree={diagnostic_path}")


def save_default(app_pid: int, title: str, path: str) -> None:
    """Invoke the live Save response for its prefilled synthetic target."""
    deadline = time.monotonic() + 8
    button = None
    while time.monotonic() < deadline:
        dialog = find_dialog(app_pid, title)
        if dialog is not None:
            matches = [item for item in descendants(dialog)
                       if item.get_name() == "Save" and item.get_role_name() == "push button"
                       and item.get_process_id() == app_pid
                       and states(item).contains(Atspi.StateType.SHOWING)
                       and states(item).contains(Atspi.StateType.SENSITIVE)]
            if len(matches) == 1:
                button = matches[0]
                break
        time.sleep(0.05)
    if button is None:
        fail(f"no unique visible Save action in app PID {app_pid}")
    actions = button.get_action_iface()
    if actions is None or actions.get_n_actions() < 1 or not actions.do_action(0):
        fail("actual visible GTK Save action failed")
    print(f"INVOKED actual GTK chooser Save action pid={app_pid} "
          f"action={actions.get_action_name(0)!r}")
    deadline = time.monotonic() + 5
    import os
    while time.monotonic() < deadline:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            print(f"INVOKED actual GTK chooser Save action pid={app_pid} path={path!r}")
            return
        time.sleep(0.05)
    nearby = []
    try:
        nearby = [(name, os.path.getsize(os.path.join(os.path.dirname(path), name)))
                  for name in sorted(os.listdir(os.path.dirname(path)))]
    except OSError:
        pass
    fail(f"actual Save response did not create expected synthetic file {path!r}; "
         f"chooser_still_open={find_dialog(app_pid, title) is not None}; "
         f"synthetic_home_entries={nearby!r}")


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[1] not in ("read", "set", "accept", "select", "save"):
        fail(
            "usage: select-native-file-chooser.py {read|set|accept|select|save} APP_PID "
            "DIALOG_TITLE ABSOLUTE_FIXTURE_PATH"
        )
    mode, pid_arg, title, path = sys.argv[1:]
    app_pid = int(pid_arg)
    Atspi.init()
    if mode == "set":
        set_path(app_pid, title, path)
    elif mode == "read":
        read_path(app_pid, title)
    elif mode == "accept":
        accept(app_pid, title, path)
    elif mode == "select":
        select_file_row(app_pid, title, path)
    else:
        save_default(app_pid, title, path)


if __name__ == "__main__":
    main()
