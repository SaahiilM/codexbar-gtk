"""Synthetic integration coverage for the opt-in Rust currency adapter."""
import json
import os
import tempfile
import unittest

from codexbar_gtk import currency, rust_bridge


@unittest.skipUnless(rust_bridge.extension() is not None, "Rust opt-in mode required")
class RustCurrencyIntegrationTests(unittest.TestCase):
    def test_catalog_labels_and_conversions_match_python_contract(self):
        self.assertEqual(currency.SUPPORTED[0], "USD")
        self.assertEqual(currency.SUPPORTED[-1], "ILS")
        self.assertEqual(currency.picker_label("INR"), "INR (₹)")
        converter = currency.CurrencyConverter(os.path.join(tempfile.gettempdir(), "currency-no-cache-test.json"))
        self.assertEqual(converter.convert(100, "USD", "EUR"), 92.0)
        self.assertAlmostEqual(converter.convert(92, "EUR", "USD"), 100.0)
        self.assertEqual(converter.convert(10, "EUR", "EUR"), 10)
        self.assertIsNone(converter.convert(1, "USD", "XYZ"))

    def test_cached_rates_override_offline_values_without_losing_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "rates.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"fetchedAt": 4_000_000_000, "rates": {"EUR": 1.25, "XYZ": 5}}, handle)
            converter = currency.CurrencyConverter(path)
            self.assertEqual(converter.rate("EUR"), 1.25)
            self.assertEqual(converter.rate("GBP"), 0.79)
            self.assertIsNone(converter.rate("XYZ"))
            self.assertEqual(converter.status(), (4_000_000_000.0, "cache", False))


if __name__ == "__main__":
    unittest.main()
