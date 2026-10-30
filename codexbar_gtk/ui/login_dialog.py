"""Sign-in dialog for provider CLIs.

Mirrors the macOS app's login runner: the CLI runs in a pseudo terminal, prints
an authorisation URL, the app opens it in the browser and the user pastes the
code back.
"""

from __future__ import annotations

import threading

from gi.repository import Adw, GLib, Gtk

from .. import login


class LoginDialog(Adw.Window):
    """Drives ``claude auth login --claudeai`` and collects the code."""

    def __init__(self, parent: Adw.Application | None = None, provider: str = "claude") -> None:
        super().__init__(application=parent)
        self.set_title("Sign in to Claude")
        self.set_default_size(520, 320)
        self.set_modal(True)
        self.provider = provider
        self.session = login.ClaudeLoginSession()
        self._last_url: str | None = None
        self._last_needs_code = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        self.status_label = Gtk.Label(label="Starting the sign-in flow…")
        self.status_label.set_wrap(True)
        self.status_label.set_xalign(0)
        box.append(self.status_label)

        self.url_entry = Adw.EntryRow(title="Authorisation link")
        self.url_entry.set_editable(False)
        self.url_entry.set_text("Waiting for the link…")
        box.append(self.url_entry)

        browser_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.open_button = Gtk.Button(label="Open in browser")
        self.open_button.add_css_class("suggested-action")
        self.open_button.set_sensitive(False)
        self.open_button.connect("clicked", lambda _b: self._open_browser())
        browser_row.append(self.open_button)

        copy_button = Gtk.Button(label="Copy link")
        copy_button.connect("clicked", lambda _b: self._copy_link())
        browser_row.append(copy_button)
        box.append(browser_row)

        self.code_entry = Adw.EntryRow(title="Code from the browser")
        self.code_entry.set_visible(False)
        box.append(self.code_entry)

        self.continue_button = Gtk.Button(label="Continue")
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_halign(Gtk.Align.END)
        self.continue_button.set_visible(False)
        self.continue_button.connect("clicked", lambda _b: self._submit_code())
        box.append(self.continue_button)

        self.set_content(box)

        self.connect("close-request", self._on_close)

    # -- flow --------------------------------------------------------------

    def start(self) -> None:
        GLib.timeout_add(75, self._poll_session)

        def run() -> None:
            self.session.start()
            result = self.session.wait()
            if result is not None:
                GLib.idle_add(self._finished, result)

        self._thread = threading.Thread(target=run, name="login-dialog", daemon=True)
        self._thread.start()

    def _poll_session(self) -> bool:
        if self.session.url and self.session.url != self._last_url:
            self._last_url = self.session.url
            self._set_url(self.session.url)
        if self.session.needs_code and not self._last_needs_code:
            self._last_needs_code = True
            self._need_code()
        return self.session.result is None

    def _set_url(self, url: str) -> None:
        self.url_entry.set_text(url)
        self.open_button.set_sensitive(True)
        self.status_label.set_text(
            "Open the link in your browser, then paste the code it shows here."
        )
        self._open_browser()

    def _open_browser(self) -> None:
        url = self.url_entry.get_text()
        if url and url.startswith("http"):
            login.open_in_browser(url)

    def _copy_link(self) -> None:
        url = self.url_entry.get_text()
        if not url:
            return
        display = self.get_display()
        if display is not None:
            display.get_clipboard().set(url)

    def _need_code(self) -> None:
        self.code_entry.set_visible(True)
        self.continue_button.set_visible(True)
        self.status_label.set_text("Paste the code from the browser and continue.")

    def _submit_code(self) -> None:
        code = self.code_entry.get_text().strip()
        if code:
            self.session.submit(code)
            self.status_label.set_text("Finishing sign-in…")

    def _finished(self, result: login.LoginResult) -> None:
        self.status_label.set_text(result.message)
        if result.success:
            self.close()
        else:
            self.code_entry.set_visible(True)
            self.continue_button.set_visible(False)

    def _on_close(self, *_args) -> bool:
        try:
            self.session.cancel()
        except Exception:
            pass
        return False
