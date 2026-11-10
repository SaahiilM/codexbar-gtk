"""Fixture-only parity coverage for the opt-in Rust login service."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk import rust_bridge
from codexbar_gtk.login import (
    ClaudeLoginSession,
    browser_command_argv,
    claude_auth_status,
    terminal_command_argv,
)


FAKE_CLAUDE = """#!/bin/sh
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  case "$AUTH_FIXTURE_MODE" in
    valid) printf '{"loggedIn":true,"fixture":true}' ;;
    nonzero) printf '{"loggedIn":true}'; exit 7 ;;
    invalid) printf 'not-json' ;;
    array) printf '[]' ;;
    *) exit 9 ;;
  esac
  exit 0
fi
printf 'https://login.example.test/authorize\\n'
printf 'Paste code here\\n'
IFS= read -r code
if [ "$code" = "fixture-code" ]; then
  printf 'Successfully logged in\\n'
  exit 0
fi
exit 8
"""


@unittest.skipUnless(rust_bridge.extension() is not None, "Rust extension is opt-in")
@unittest.skipUnless(os.name == "posix", "fixture PTY uses a POSIX fake executable")
class RustLoginIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codexbar-login-fixture-")
        self.root = Path(self.temp.name)
        self.executable = self.root / "claude"
        self.executable.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.executable.chmod(0o700)
        refresh_cli = self.root / "codexbar-fixture"
        refresh_cli.write_text(
            "#!/bin/sh\ncase \"$1\" in --version) printf 'fixture\\n';; *) printf '[]\\n';; esac\n",
            encoding="utf-8",
        )
        refresh_cli.chmod(0o700)
        core = rust_bridge.extension()
        preferences = core.PreferencesStore(str(self.root / "settings.json"))
        history = core.HistoryStore(str(self.root / "history.jsonl"), 365)
        currencies = core.CurrencyConverter(str(self.root / "rates.json"))
        self.controller = core.RefreshController(
            str(refresh_cli), None, preferences, history, currencies,
            str(refresh_cli), str(self.root),
        )
        self.env = patch.dict(
            os.environ,
            {
                "HOME": str(self.root),
                "CLAUDE_CLI": str(self.executable),
                "AUTH_FIXTURE_MODE": "valid",
            },
        )
        self.env.start()

    def tearDown(self) -> None:
        self.controller.request_shutdown()
        self.env.stop()
        self.temp.cleanup()

    def test_auth_status_matches_empty_object_fallbacks(self) -> None:
        self.assertEqual(claude_auth_status(), {"loggedIn": True, "fixture": True})
        for mode in ("nonzero", "invalid", "array", "missing"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"AUTH_FIXTURE_MODE": mode}):
                self.assertEqual(claude_auth_status(), {})

    def test_pty_login_streams_fixture_url_prompt_and_completion(self) -> None:
        session = ClaudeLoginSession(controller=self.controller, timeout=4)
        self.assertTrue(session.start())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not (session.url and session.needs_code):
            time.sleep(0.025)
        self.assertEqual(session.url, "https://login.example.test/authorize")
        self.assertTrue(session.needs_code)
        rust_state = session._rust_session.snapshot()
        self.assertNotIn(session.url, repr(rust_state))
        session.submit("fixture-code")
        result = session.wait(timeout=3)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.auth_url, "https://login.example.test/authorize")
        self.assertFalse(result.timed_out)

    def test_cancel_kills_fake_login(self) -> None:
        session = ClaudeLoginSession(controller=self.controller, timeout=4)
        self.assertTrue(session.start())
        session.cancel()
        result = session.wait(timeout=2)
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Login cancelled")

    def test_cancel_before_worker_starts_is_not_lost(self) -> None:
        session = ClaudeLoginSession(controller=self.controller, timeout=4)
        session.cancel()
        self.assertTrue(session.start())
        result = session.wait(timeout=2)
        self.assertIsNotNone(result)
        self.assertEqual(result.message, "Login cancelled")

    def test_browser_and_terminal_argv_use_rust_helpers(self) -> None:
        self.assertEqual(
            terminal_command_argv("/usr/bin/gnome-terminal", ["claude", "auth login"]),
            ["/usr/bin/gnome-terminal", "--", "claude", "auth login"],
        )
        self.assertEqual(
            browser_command_argv("/usr/bin/gio", "https://login.example.test/a?b=c"),
            ["/usr/bin/gio", "open", "https://login.example.test/a?b=c"],
        )


if __name__ == "__main__":
    unittest.main()
