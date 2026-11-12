"""Pure checks for filename rows exposed by an app-owned GTK file chooser."""

from __future__ import annotations


def exact_selected_row_records(rows, filename: str, app_pid: int,
                               require_selected: bool = True) -> list[dict]:
    """Return selected, visible rows containing one exact visible filename cell.

    Records contain the row's role, identity, pid, states and descendant cell
    records. Identity comes from the AT-SPI tree path, so separate controls are
    never collapsed because their screen bounds happen to match.
    """
    matches = []
    for row in rows:
        states = set(row.get("states", ()))
        required = {"showing", "sensitive"} | ({"selected"} if require_selected else set())
        if (row.get("role") != "table row" or row.get("pid") != app_pid
                or not required.issubset(states)
                or not row.get("identity")):
            continue
        for cell in row.get("descendants", ()):
            cell_states = set(cell.get("states", ()))
            if (cell.get("role") not in ("label", "table cell")
                    or cell.get("pid") != app_pid
                    or not {"showing", "sensitive"}.issubset(cell_states)):
                continue
            if cell.get("name") == filename or cell.get("text") == filename:
                matches.append(row)
                break
    identities = [row["identity"] for row in matches]
    if len(identities) != len(set(identities)):
        return []
    return matches
