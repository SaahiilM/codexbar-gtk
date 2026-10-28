"""Tests for mapping provider IDs to bundled upstream artwork."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codexbar_gtk.provider_icons import provider_icon_path


class ProviderIconTests(unittest.TestCase):
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

    def test_unknown_provider_uses_no_bundled_icon(self):
        self.assertIsNone(provider_icon_path("provider-without-artwork"))
