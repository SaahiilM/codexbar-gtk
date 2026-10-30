from __future__ import annotations

import json
import os
import tempfile
import unittest

from codexbar_gtk.cli import CLIError, CodexBarCLI, ProviderStatusEntry


FAKE_CLI = r"""#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
if args[0] == "--version":
    print("CodexBar 0.82.0")
elif args[0] == "usage":
    provider = args[args.index("--provider") + 1] if "--provider" in args else None
    print(json.dumps({"provider": provider, "all": "--all-accounts" in args, "tz": os.getenv("TZ")}))
elif args[0] == "cost":
    print(json.dumps({"provider": args[args.index("--provider") + 1] if "--provider" in args else "both"}))
elif args[0] == "dashboard":
    print(json.dumps({"fixture": True}))
elif args[0] == "sessions":
    print(json.dumps([{"id": "fixture-session"}]))
elif args[:2] == ["config", "providers"]:
    print("codex: enabled (OpenAI Codex)")
    print("claude: disabled (Claude)")
elif args[:2] == ["config", "set-api-key"]:
    print(json.dumps(args))
elif args[:2] == ["config", "set-source"]:
    print(json.dumps(args))
elif args[0] == "config":
    print(json.dumps(args))
elif args[0] == "hooks" and args[1] == "list":
    print(json.dumps({"enabled": True, "events": ["session-start"]}))
elif args[0] == "plugins":
    print(json.dumps([{"id": "fixture-plugin"}]))
elif args[0] == "slow":
    time.sleep(4)
else:
    print("[]")
"""


class RustCliServiceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.executable = os.path.join(self.tempdir.name, "fixture-cli")
        with open(self.executable, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLI)
        os.chmod(self.executable, 0o700)
        self.cli = CodexBarCLI(self.executable, timezone="Asia/Tokyo")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_usage_cost_dashboard_sessions_and_version(self):
        self.assertEqual(self.cli.version(), "CodexBar 0.82.0")
        self.assertEqual(
            self.cli.usage(provider="claude", all_accounts=True),
            [{"provider": "claude", "all": True, "tz": "Asia/Tokyo"}],
        )
        self.assertEqual(self.cli.cost(provider="both"), [{"provider": "both"}])
        self.assertEqual(self.cli.dashboard(), {"fixture": True})
        self.assertEqual(self.cli.sessions(), [{"id": "fixture-session"}])

    def test_config_hooks_plugins_and_argv_boundaries(self):
        self.assertEqual(
            self.cli.config_providers(),
            [
                ProviderStatusEntry("codex", True, "OpenAI Codex", False),
                ProviderStatusEntry("claude", False, "Claude", False),
            ],
        )
        self.assertEqual(self.cli.hooks(), {"enabled": True, "events": ["session-start"]})
        self.assertEqual(self.cli.plugins(), [{"id": "fixture-plugin"}])
        result = self.cli.set_api_key("fixture-provider", "synthetic value with spaces")
        self.assertEqual(
            json.loads(result.stdout),
            ["config", "set-api-key", "--provider", "fixture-provider", "--api-key", "synthetic value with spaces"],
        )
        self.assertEqual(self.cli.enable_provider("fixture-provider").returncode, 0)
        self.assertEqual(self.cli.set_source("fixture-provider", "fixture-source").returncode, 0)

    def test_timeout_returns_a_cli_error(self):
        with self.assertRaises(CLIError):
            self.cli.run(["slow"], timeout=1)


if __name__ == "__main__":
    unittest.main()
