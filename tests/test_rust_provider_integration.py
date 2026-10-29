"""Integration checks for the opt-in Rust-backed provider functions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from codexbar_gtk import providers

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh")
class RustProviderIntegrationTests(unittest.TestCase):
    def test_python_adapter_uses_rust_and_matches_python_results(self) -> None:
        provider_ids = sorted(
            set(providers.PROVIDERS)
            | set(providers.ALIASES)
            | {"unknown-provider_id", "nope"}
        )
        expected = [
            {
                "id": provider_id,
                "canonical": providers.ALIASES.get(provider_id, provider_id),
                "display": providers.display_name(provider_id),
                "short": providers.short_name(provider_id),
                "color": providers.accent_color(provider_id),
            }
            for provider_id in provider_ids
        ]
        script = """
import json, sys
from codexbar_gtk import providers
from codexbar_gtk.data import provider_usage_from_payload
assert providers.backend_name() == 'rust'
result = []
for provider_id in json.loads(sys.argv[1]):
    result.append({
        'id': provider_id,
        'canonical': providers.canonical_id(provider_id),
        'display': providers.display_name(provider_id),
        'short': providers.short_name(provider_id),
        'color': providers.accent_color(provider_id),
    })
usage = provider_usage_from_payload({
    'provider': 'azure-openai',
    'usage': {'primary': {'usedPercent': 10}},
})
print(json.dumps({
    'metadata': result,
    'consumer': {'display': usage.display_name, 'color': usage.accent_color},
}, ensure_ascii=False))
"""
        env = os.environ.copy()
        env["CODEXBAR_RUST_CORE"] = "1"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", script, json.dumps(provider_ids)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "metadata": expected,
                "consumer": {
                    "display": providers.display_name("azure-openai"),
                    "color": providers.accent_color("azure-openai"),
                },
            },
        )

    def test_enabled_mode_fails_fast_when_extension_is_missing(self) -> None:
        script = "from codexbar_gtk import providers"
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "codexbar_gtk"
            shutil.copytree(
                ROOT / "codexbar_gtk",
                package,
                ignore=shutil.ignore_patterns("_rust_core.so", "__pycache__"),
            )
            env = os.environ.copy()
            env["CODEXBAR_RUST_CORE"] = "1"
            env["PYTHONPATH"] = temporary
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("run scripts/build-rust-core.sh first", completed.stderr)
