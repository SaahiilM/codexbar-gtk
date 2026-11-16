"""Tests for mapping provider IDs to bundled upstream artwork."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codexbar_gtk.provider_icons import ASSET_DIR, provider_icon_path


class ProviderIconTests(unittest.TestCase):
    def test_artwork_catalog_is_shared_outside_the_python_package(self):
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(ASSET_DIR, repo_root / "assets" / "provider_icons")
        self.assertTrue((ASSET_DIR / "LICENSE-CodexBar").is_file())

    def test_codex_prefers_curated_brand_artwork(self):
        path = provider_icon_path("codex")
        self.assertIsNotNone(path)
        self.assertEqual(path.name, "Brand-ProviderIcon-codex.png")

    def test_codex_monochrome_asset_is_available_as_fallback(self):
        path = provider_icon_path("codex", prefer_brand=False)
        self.assertIsNotNone(path)
        self.assertEqual(path.name, "ProviderIcon-codex.svg")

    def test_provider_aliases_follow_upstream_icon_assignments(self):
        self.assertEqual(
            provider_icon_path("azure-openai", prefer_brand=False).name,
            "ProviderIcon-codex.svg",
        )
        self.assertEqual(
            provider_icon_path("moonshot", prefer_brand=False).name,
            "ProviderIcon-kimi.svg",
        )

    def test_v084_provider_artwork_and_open_design_alias(self):
        expected = {
            "opendesign": "ProviderIcon-opendesign.svg",
            "open-design": "ProviderIcon-opendesign.svg",
            "siliconflow": "ProviderIcon-siliconflow.svg",
            "tripo": "ProviderIcon-tripo.svg",
        }
        for provider_id, expected_name in expected.items():
            with self.subTest(provider_id=provider_id):
                path = provider_icon_path(provider_id)
                self.assertIsNotNone(path)
                self.assertEqual(path.name, expected_name)

    def test_unknown_provider_uses_no_bundled_icon(self):
        self.assertIsNone(provider_icon_path("provider-without-artwork"))
