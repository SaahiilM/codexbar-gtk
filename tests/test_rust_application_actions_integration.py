"""Fixture-only PyO3 coverage for B13 application actions."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from codexbar_gtk import currency, rust_bridge
from codexbar_gtk.cli import CodexBarCLI
from codexbar_gtk.controller import Controller
from codexbar_gtk.login import ClaudeLoginSession
from codexbar_gtk.prefs import Preferences
from codexbar_gtk.updates import UpdateCheckRequest


FAKE_REFRESH_CLI = """#!/bin/sh
case "$1" in
  --version) printf 'fixture-cli 1.0\\n' ;;
  usage|cost|sessions) printf '[]\\n' ;;
  *) printf '[]\\n' ;;
esac
"""

FAKE_CLAUDE = """#!/bin/sh
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
@unittest.skipUnless(os.name == "posix", "fixtures use POSIX process behavior")
class RustApplicationActionsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codexbar-app-actions-")
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"HOME": str(self.root)})
        self.env.start()
        self.core = rust_bridge.extension()

        self.refresh_cli = self.root / "codexbar-fixture"
        self.refresh_cli.write_text(FAKE_REFRESH_CLI, encoding="utf-8")
        self.refresh_cli.chmod(0o700)
        preferences = self.core.PreferencesStore(
            str(self.root / ".config/codexbar-gtk/settings.json")
        )
        history = self.core.HistoryStore(
            str(self.root / ".local/share/codexbar/history.jsonl"), 365
        )
        currency_cache = self.root / ".cache/codexbar/rates.json"
        currency_cache.parent.mkdir(parents=True, exist_ok=True)
        currency_cache.write_text(
            json.dumps({"fetchedAt": 4_000_000_000.0, "rates": {"EUR": 1.25}}),
            encoding="utf-8",
        )
        self.previous_shared_currency = currency._SHARED
        currency._SHARED = currency.CurrencyConverter(str(currency_cache))
        self.currencies = currency._SHARED._rust
        self.rust_controller = self.core.RefreshController(
            str(self.refresh_cli),
            None,
            preferences,
            history,
            self.currencies,
            str(self.refresh_cli),
            str(Path(__file__).resolve().parents[1] / "codexbar_gtk"),
        )
        parity_preferences = Preferences(
            str(self.root / ".config/codexbar-gtk/ui-settings.json")
        )
        self.controller = Controller(
            parity_preferences,
            cli=CodexBarCLI(str(self.refresh_cli)),
        )
        self.controller._rust_controller = self.rust_controller

    def tearDown(self) -> None:
        self.controller.stop()
        self.env.stop()
        self.temp.cleanup()
        currency._SHARED = self.previous_shared_currency

    def _fake_executable(self, name: str, contents: str) -> Path:
        path = self.root / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o700)
        return path

    def test_currency_adapter_uses_shared_controller_facade_and_status(self) -> None:
        currency.bind_facade(self.controller)
        self.assertIs(currency.shared()._rust, self.currencies)
        catalog = self.controller.catalog_async()
        euro = next(item for item in catalog if item[0] == "EUR")
        self.assertEqual(euro[:2], ("EUR", "€"))
        self.assertEqual(euro[2], 1.25)
        self.assertEqual(currency.shared().rate("EUR"), 1.25)
        self.assertEqual(currency.convert(100.0, "USD", "EUR"), 125.0)
        self.assertTrue(currency.requires_live_rates("EUR"))
        self.assertFalse(currency.requires_live_rates("auto"))
        self.assertFalse(currency.shared().ensure_rates("USD").result(timeout=3))
        self.assertFalse(
            self.controller.ensure_rates_at("EUR", 4_000_000_001.0).result(timeout=3)
        )
        self.assertEqual(
            self.controller.status_async(),
            {
                "fetched_at": 4_000_000_000.0,
                "source": "cache",
                "last_refresh_failed": False,
            },
        )
        self.assertEqual(
            currency.shared().status(),
            (4_000_000_000.0, "cache", False),
        )

    def test_update_check_uses_b12_facade_and_returns_current_latest_relation(self) -> None:
        body = b"MARKETING_VERSION=0.82.0\nCURRENT_PROJECT_VERSION=48\n"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.controller.check_update(
                UpdateCheckRequest(
                    "0.82.0", 47, timeout=2.0,
                    url=f"http://127.0.0.1:{server.server_port}/VERSION",
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(result.relation, "available")
        self.assertEqual((result.current_version, result.current_build), ("0.82.0", 47))
        self.assertEqual((result.latest_version, result.latest_build), ("0.82.0", 48))

    def test_update_error_crosses_facade_with_only_stable_kind_and_operation(self) -> None:
        body = b"MARKETING_VERSION=invalid-marker\nCURRENT_PROJECT_VERSION=48\n"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/VERSION"
        try:
            with self.assertRaisesRegex(
                RuntimeError, r"invalid_marker \(update_check\)"
            ) as raised:
                self.rust_controller.check_update(url, "0.82.0", "47", 2.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertNotIn(url, str(raised.exception))
        self.assertEqual(str(raised.exception), "invalid_marker (update_check)")

    def test_claude_login_uses_facade_handle_and_keeps_events_separate(self) -> None:
        executable = self._fake_executable("claude", FAKE_CLAUDE)
        with patch.dict(os.environ, {"CLAUDE_CLI": str(executable)}):
            session = ClaudeLoginSession(controller=self.controller, timeout=4)
            self.assertTrue(session.start())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not (session.url and session.needs_code):
                time.sleep(0.025)
            self.assertEqual(session.url, "https://login.example.test/authorize")
            self.assertTrue(session.needs_code)
            state = session._rust_session.snapshot()
            self.assertNotIn(session.url, repr(state))
            session.submit("fixture-code")
            result = session.wait(timeout=3)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.auth_url, "https://login.example.test/authorize")

    def test_codex_terminal_login_uses_rust_discovery_and_terminal_argv(self) -> None:
        codex = self._fake_executable("codex fixture", "#!/bin/sh\nexit 0\n")
        tools = self.root / "tools"
        tools.mkdir()
        capture = self.root / "terminal-argv.txt"
        terminal = tools / "konsole"
        terminal.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TERMINAL_ARGV_CAPTURE\"\n",
            encoding="utf-8",
        )
        terminal.chmod(0o700)
        env_path = os.pathsep.join((str(tools), os.environ.get("PATH", "")))
        with patch.dict(
            os.environ,
            {
                "CODEX_CLI": str(codex),
                "TERMINAL_ARGV_CAPTURE": str(capture),
                "PATH": env_path,
            },
        ):
            result = self.controller.launch_codex_login_terminal()
        self.assertEqual(result, {"launched": True})
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not capture.exists():
            time.sleep(0.025)
        self.assertEqual(
            capture.read_text(encoding="utf-8").splitlines(),
            ["-e", str(codex), "login"],
        )

    def test_codex_terminal_missing_tool_returns_quiet_no_launch_result(self) -> None:
        codex = self._fake_executable("codex", "#!/bin/sh\nexit 0\n")
        empty_path = self.root / "empty-path"
        empty_path.mkdir()
        with patch.dict(
            os.environ,
            {"CODEX_CLI": str(codex), "PATH": str(empty_path)},
        ):
            result = self.controller.launch_codex_login_terminal()
        self.assertEqual(result, {"launched": False})

    def test_icon_cache_refresh_uses_facade_and_preserves_quiet_result(self) -> None:
        theme_dir = self.root / ".local/share/icons/hicolor"
        theme_dir.mkdir(parents=True)
        tools = self.root / "icon-tools"
        tools.mkdir()
        capture = self.root / "icon-cache-argv.txt"
        tool = tools / "gtk4-update-icon-cache"
        tool.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$ICON_CACHE_ARGV_CAPTURE\"\n",
            encoding="utf-8",
        )
        tool.chmod(0o700)
        with patch.dict(
            os.environ,
            {
                "PATH": os.pathsep.join((str(tools), os.environ.get("PATH", ""))),
                "ICON_CACHE_ARGV_CAPTURE": str(capture),
            },
        ):
            result = self.controller.refresh_icon_cache()
        self.assertEqual(result, {"status": "refreshed"})
        self.assertEqual(
            capture.read_text(encoding="utf-8").splitlines(),
            ["-f", "-t", str(theme_dir)],
        )

    def test_icon_cache_failure_is_an_explicit_best_effort_result(self) -> None:
        theme_dir = self.root / ".local/share/icons/hicolor"
        theme_dir.mkdir(parents=True)
        tools = self.root / "icon-tools-failure"
        tools.mkdir()
        tool = tools / "gtk4-update-icon-cache"
        tool.write_text("#!/bin/sh\nexit 17\n", encoding="utf-8")
        tool.chmod(0o700)
        with patch.dict(os.environ, {"PATH": str(tools)}):
            result = self.controller.refresh_icon_cache()
        self.assertEqual(result, {"status": "failed"})

    def test_pyo3_restart_context_matches_live_python_process_without_returning_argv(self) -> None:
        process_argv = [
            os.fsdecode(item)
            for item in Path("/proc/self/cmdline").read_bytes().split(b"\0")
            if item
        ]
        executable = Path(os.readlink("/proc/self/exe"))
        self.assertTrue(
            self.rust_controller._restart_context_matches(executable, process_argv[1:])
        )


class LauncherWrapperTests(unittest.TestCase):
    """Verify development and installed wrappers exec the same Python module."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codexbar-launcher-fixture-")
        self.root = Path(self.temp.name)
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.capture = self.root / "python-argv.txt"
        python = self.fake_bin / "python3"
        python.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$PYTHON_ARGV_CAPTURE\"\n",
            encoding="utf-8",
        )
        python.chmod(0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run_wrapper(self, wrapper: Path, arg: str) -> list[str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": os.pathsep.join((str(self.fake_bin), env.get("PATH", ""))),
                "PYTHON_ARGV_CAPTURE": str(self.capture),
            }
        )
        subprocess.run([str(wrapper), arg], env=env, check=True, timeout=10)
        return self.capture.read_text(encoding="utf-8").splitlines()

    def test_development_run_sh_execs_module_and_preserves_flags(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run.sh"
        self.assertEqual(
            self._run_wrapper(wrapper, "--settings"),
            ["-m", "codexbar_gtk", "--settings"],
        )

    def test_installed_launcher_execs_module_and_preserves_flags(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        home = self.root / "home"
        prefix = self.root / "prefix"
        home.mkdir()
        env = os.environ.copy()
        env.update({"HOME": str(home), "PREFIX": str(prefix)})
        subprocess.run(
            [str(repo / "scripts/install.sh"), "--no-autostart"],
            env=env,
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
        )
        launcher = prefix / "bin/codexbar-gtk"
        self.assertEqual(
            self._run_wrapper(launcher, "--about"),
            ["-m", "codexbar_gtk", "--about"],
        )


if __name__ == "__main__":
    unittest.main()
