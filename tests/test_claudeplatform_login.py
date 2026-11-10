"""Synthetic CLI fixtures for the ClaudePlatform stdin login path."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from codexbar_gtk.login import (
    ClaudePlatformLoginError,
    MAX_CLAUDEPLATFORM_INPUT_BYTES,
    run_claudeplatform_login,
)


class ClaudePlatformLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codexbar-claudeplatform-fixture-")
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake-codexbar"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def script(self, body: str) -> None:
        self.cli.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        self.cli.chmod(0o700)

    def test_exact_argv_stdin_eof_success_and_secret_absent_from_argv(self) -> None:
        argv_path = self.root / "argv.json"
        stdin_path = self.root / "stdin.bin"
        self.script(
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(argv_path)!r}).write_text(json.dumps(sys.argv[1:]))\n"
            f"pathlib.Path({str(stdin_path)!r}).write_bytes(sys.stdin.buffer.read())\n"
            "print('{\"status\":\"authorized\"}')\n"
        )
        candidate = "sessionKey=synthetic-candidate"
        run_claudeplatform_login(str(self.cli), candidate)
        self.assertEqual(
            __import__("json").loads(argv_path.read_text()),
            ["config", "login", "--provider", "claudeplatform", "--stdin", "--json"],
        )
        self.assertEqual(stdin_path.read_bytes(), candidate.encode())
        self.assertNotIn(candidate, argv_path.read_text())

    def test_nonzero_malformed_and_trailing_output_are_rejected_safely(self) -> None:
        for body in (
            "import sys\nsys.stdin.buffer.read()\nprint('{\"status\":\"authorized\"}')\nsys.exit(9)\n",
            "import sys\nsys.stdin.buffer.read()\nprint('not-json')\n",
            "import sys\nsys.stdin.buffer.read()\nprint('{\"status\":\"authorized\"} extra')\n",
        ):
            self.script(body)
            with self.assertRaises(ClaudePlatformLoginError) as raised:
                run_claudeplatform_login(str(self.cli), "sessionKey=synthetic")
            self.assertNotIn("synthetic", str(raised.exception))

    def test_rejects_multiline_and_oversize_before_spawn(self) -> None:
        with self.assertRaises(ClaudePlatformLoginError):
            run_claudeplatform_login(str(self.root / "missing"), "one\ntwo")
        with self.assertRaises(ClaudePlatformLoginError):
            run_claudeplatform_login(
                str(self.root / "missing"), "x" * (MAX_CLAUDEPLATFORM_INPUT_BYTES + 1)
            )

    def test_timeout_kills_the_fake_cli(self) -> None:
        self.script("import time\ntime.sleep(30)\n")
        with self.assertRaises(ClaudePlatformLoginError) as raised:
            run_claudeplatform_login(str(self.cli), "synthetic", timeout=0.1)
        self.assertEqual(str(raised.exception), "timeout")

    def test_cancel_kills_the_fake_process_group(self) -> None:
        child_path = self.root / "child.pid"
        self.script(
            "import pathlib, subprocess, sys, time\n"
            "child = subprocess.Popen(['sleep', '30'])\n"
            f"pathlib.Path({str(child_path)!r}).write_text(str(child.pid))\n"
            "sys.stdin.buffer.read()\n"
            "time.sleep(30)\n"
        )
        cancelled = threading.Event()
        failures: list[ClaudePlatformLoginError] = []

        def run() -> None:
            try:
                run_claudeplatform_login(str(self.cli), "synthetic", timeout=10, cancelled=cancelled)
            except ClaudePlatformLoginError as exc:
                failures.append(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 2
        while not child_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_path.exists(), "fake descendant did not start")
        cancelled.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive(), "cancelled login worker did not join")
        self.assertEqual([str(failure) for failure in failures], ["cancelled"])
        pid = int(child_path.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split()[2]
            except FileNotFoundError:
                state = None
            self.assertIn(state, (None, "Z"), "fake descendant survived process-group cancellation")


if __name__ == "__main__":
    unittest.main()
