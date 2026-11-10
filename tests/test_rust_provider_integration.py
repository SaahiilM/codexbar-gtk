"""Integration checks for the opt-in Rust-backed provider functions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
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

    def test_unknown_unicode_provider_titles_match_python_titlecase(self) -> None:
        import importlib
        from unittest.mock import patch

        core = importlib.import_module("codexbar_gtk._rust_core")
        provider_ids = (
            "ß-provider",
            "ǆ-provider",
            "ǅFOO",
            "ǈFOO",
            "ǋFOO",
            "ǲFOO",
            "λ-provider",
            "provider-猫",
            "ΟΣ-provider",
            "ΟΣΑ-provider",
            "aΣ\u0301a",
            "ΟΣ\u0301Α",
            "AΣ.B",
            "fooʼbar",
        )
        with patch.object(providers, "_RUST_CORE", None):
            expected = [providers.display_name(provider_id) for provider_id in provider_ids]
        with patch.object(providers, "_RUST_CORE", core):
            actual = [providers.display_name(provider_id) for provider_id in provider_ids]
        self.assertEqual(actual, expected)

    def test_unicode_15_case_mappings_match_python_312_exhaustively(self) -> None:
        """Keep Rust fallback casing aligned with the Python 3.12 UCD."""
        import importlib
        from unittest.mock import patch

        if unicodedata.unidata_version != "15.0.0":
            self.skipTest(
                f"fixture targets Python 3.12 Unicode 15.0, got {unicodedata.unidata_version}"
            )

        core = importlib.import_module("codexbar_gtk._rust_core")
        cased = []
        for codepoint in range(0x110000):
            character = chr(codepoint)
            if character.islower() or character.isupper() or character.istitle():
                cased.append(character)
        with patch.object(providers, "_RUST_CORE", core):
            for character in cased:
                self.assertEqual(
                    providers.display_name(character),
                    character.title(),
                    f"single-character titlecase U+{ord(character):04X}",
                )
                context = "A" + character
                self.assertEqual(
                    providers.display_name(context),
                    context.title(),
                    f"contextual lowercase U+{ord(character):04X}",
                )

            case_ignorable = (
                "\u0301",  # Mn: COMBINING ACUTE ACCENT
                "\u20dd",  # Me: COMBINING ENCLOSING CIRCLE
                "\u00ad",  # Cf: SOFT HYPHEN
                "\u02bc",  # Lm / MidLetter: MODIFIER LETTER APOSTROPHE
                "^",  # Sk: CIRCUMFLEX ACCENT
                ":",  # MidLetter
                "'",  # Single_Quote
            )
            not_case_ignorable = (",", ".", ";")
            for character in (*case_ignorable, *not_case_ignorable):
                context = "A\u03a3" + character + "A"
                self.assertEqual(
                    providers.display_name(context),
                    context.title(),
                    f"final-sigma context around U+{ord(character):04X}",
                )
