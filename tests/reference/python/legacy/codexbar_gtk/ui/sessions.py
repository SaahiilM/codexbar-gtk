"""Agent sessions view — the coding agents that are running right now."""

from __future__ import annotations

from datetime import datetime, timezone

from gi.repository import Gtk

from ..data import AgentSession
from ..format import format_updated
from .util import iter_children


class SessionsView(Gtk.Box):
    """Lists the coding-agent sessions the CLI can see."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("cb-dash-grid")
        self.set_size_request(720, -1)

        self.summary_label = Gtk.Label(label="")
        self.summary_label.add_css_class("cb-overview-sub")
        self.summary_label.set_halign(Gtk.Align.START)
        self.append(self.summary_label)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list_box.set_margin_top(12)
        self.append(self.list_box)

        self.empty_label = Gtk.Label(label="No agent sessions detected")
        self.empty_label.add_css_class("cb-empty")
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

    def update(self, sessions: list[AgentSession]) -> None:
        for child in list(iter_children(self.list_box)):
            self.list_box.remove(child)

        running = [s for s in sessions if s.is_running]
        self.summary_label.set_text(
            f"{len(running)} running of {len(sessions)} known sessions"
            if sessions
            else ""
        )
        self.empty_label.set_visible(not sessions)

        for session in sessions[:24]:
            self.list_box.append(self._row(session))

    def _row(self, session: AgentSession) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        row.add_css_class("cb-session")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        badge = Gtk.Label(label=(session.provider or "agent").title())
        badge.add_css_class("cb-plan-badge")
        badge.set_valign(Gtk.Align.CENTER)
        header.append(badge)

        title = Gtk.Label(label=session.project_name or session.cwd or session.id)
        title.add_css_class("cb-session-title")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        title.set_ellipsize(3)
        header.append(title)

        state = Gtk.Label(label=session.state or "unknown")
        state.add_css_class("cb-chip-label")
        state.set_valign(Gtk.Align.CENTER)
        header.append(state)
        row.append(header)

        details = []
        if session.cwd and session.cwd != session.project_name:
            details.append(session.cwd)
        if session.pid:
            details.append(f"pid {session.pid}")
        activity = format_updated(session.last_activity_at, datetime.now(timezone.utc))
        if activity:
            details.append(activity)
        if details:
            path = Gtk.Label(label=" · ".join(details))
            path.add_css_class("cb-session-path")
            path.set_halign(Gtk.Align.START)
            path.set_ellipsize(3)
            row.append(path)
        return row
