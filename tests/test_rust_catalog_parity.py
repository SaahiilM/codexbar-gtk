"""Keep the parallel Rust provider catalog in sync with the Python source."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from codexbar_gtk.currency import CURRENCIES
from codexbar_gtk.providers import ALIASES, PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
RUST_PROVIDERS = ROOT / "rust-core" / "src" / "providers.rs"
RUST_PACE = ROOT / "rust-core" / "src" / "pace.rs"


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

    def test_currency_codes_match_python_catalog(self) -> None:
        pace_source = RUST_PACE.read_text(encoding="utf-8")
        start = pace_source.index("pub const CURRENCY_CODES:")
        end = pace_source.index("];", start)
        rust_codes = re.findall(r'"([A-Z]{3})"', pace_source[start:end])
        python_codes = [code for code, _symbol, _rate in CURRENCIES]
        self.assertEqual(rust_codes, python_codes)


if __name__ == "__main__":
    unittest.main()
