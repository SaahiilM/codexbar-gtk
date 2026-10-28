"""Keep the parallel Rust provider catalog in sync with the Python source."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from codexbar_gtk.providers import ALIASES, PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
RUST_PROVIDERS = ROOT / "rust-core" / "src" / "providers.rs"


class RustProviderCatalogParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUST_PROVIDERS.read_text(encoding="utf-8")

    def test_provider_metadata_matches_python_catalog(self) -> None:
        pattern = re.compile(
            r'ProviderMetadata\s*\{\s*id: "([^"]+)",\s*name: "([^"]*)",'
            r'\s*short_name: "([^"]*)",\s*accent_color: "([^"]+)"',
            re.DOTALL,
        )
        rust_catalog = {
            provider_id: (name, short_name, color)
            for provider_id, name, short_name, color in pattern.findall(self.source)
        }
        self.assertEqual(rust_catalog, PROVIDERS)

    def test_aliases_match_python_catalog(self) -> None:
        start = self.source.index("const ALIASES:")
        end = self.source.index("];", start)
        pairs = re.findall(r'\("([^"]+)", "([^"]+)"\)', self.source[start:end])
        self.assertEqual(dict(pairs), ALIASES)


if __name__ == "__main__":
    unittest.main()
