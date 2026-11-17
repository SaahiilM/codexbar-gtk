"""Keep the parallel Rust provider catalog in sync with the Python source."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from codexbar_gtk.currency import CURRENCIES
from codexbar_gtk.providers import ALIASES, PROVIDER_DESCRIPTOR_DETAILS, PROVIDERS

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
        self.assertEqual(len(rust_catalog), 113)
        self.assertEqual(list(rust_catalog), sorted(rust_catalog))

    def test_v084_descriptors_match_python_metadata_and_tagged_order(self) -> None:
        start = self.source.index("pub const PROVIDER_DESCRIPTOR_DETAILS:")
        end = self.source.index("];", start)
        section = self.source[start:end]
        pattern = re.compile(
            r'ProviderDescriptorDetails\s*\{\s*id: "([^"]+)",'
            r'\s*session_label: "([^"]+)",\s*weekly_label: "([^"]+)",'
            r'\s*dashboard_url: "([^"]+)",\s*status_page_url: '
            r'(None|Some\("[^"]+"\)),\s*balance_only: (true|false),'
            r'\s*history_available: (true|false),'
            r'\s*burndown_widget_selectable: (true|false),'
            r'\s*api_detail: (true|false),\s*availability: '
            r'(None|Some\("[^"]+"\)),\s*progress_color_style: '
            r'(None|Some\("[^"]+"\)),\s*menu_bar_metrics: '
            r'(None|Some\(&\[[^]]*\]\))',
            re.DOTALL,
        )
        rust_details = {}
        for match in pattern.finditer(section):
            (
                provider_id,
                session_label,
                weekly_label,
                dashboard_url,
                status_page_url,
                balance_only,
                history_available,
                burndown_selectable,
                api_detail,
                availability,
                progress_color_style,
                metrics,
            ) = match.groups()
            parse_optional_string = lambda value: (
                None if value == "None" else value[6:-2]
            )
            rust_details[provider_id] = {
                "session_label": session_label,
                "weekly_label": weekly_label,
                "dashboard_url": dashboard_url,
                "status_page_url": parse_optional_string(status_page_url),
                "balance_only": balance_only == "true",
                "history_available": history_available == "true",
                "burndown_widget_selectable": burndown_selectable == "true",
                "api_detail": api_detail == "true",
                "availability": parse_optional_string(availability),
                "progress_color_style": parse_optional_string(progress_color_style),
                "menu_bar_metrics": (
                    None if metrics == "None" else tuple(re.findall(r'"([^"]+)"', metrics))
                ),
            }
        self.assertEqual(list(rust_details), ["opendesign", "siliconflow", "tripo"])
        self.assertEqual(rust_details, PROVIDER_DESCRIPTOR_DETAILS)

    def test_aliases_match_python_catalog(self) -> None:
        start = self.source.index("const ALIASES:")
        end = self.source.index("];", start)
        pairs = re.findall(r'\("([^"]+)", "([^"]+)"\)', self.source[start:end])
        self.assertEqual(dict(pairs), ALIASES)
        self.assertEqual(len(ALIASES), 7)

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
