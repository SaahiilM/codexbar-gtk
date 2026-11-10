"""Keep the parallel Rust provider catalog in sync with the Python source."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from codexbar_gtk.currency import CURRENCIES
from codexbar_gtk.providers import ALIASES, PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
RUST_PROVIDERS = ROOT / "rust-core" / "src" / "providers.rs"
RUST_CURRENCY = ROOT / "rust-core" / "src" / "currency.rs"


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
        currency_source = RUST_CURRENCY.read_text(encoding="utf-8")
        start = currency_source.index("pub const CURRENCIES:")
        end = currency_source.index("];", start)
        rust_catalog = [
            (code, symbol, float(rate))
            for code, symbol, rate in re.findall(
                r'\("([A-Z]{3})", "([^"]*)", ([0-9.]+)\)',
                currency_source[start:end],
            )
        ]
        self.assertEqual(rust_catalog, CURRENCIES)


if __name__ == "__main__":
    unittest.main()
