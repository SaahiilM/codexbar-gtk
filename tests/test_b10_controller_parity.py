"""B10 JSON bridge parity checks using a synthetic provider envelope."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from codexbar_gtk import rust_bridge
from codexbar_gtk.controller import _provider_from_dto
from codexbar_gtk.data import provider_usage_from_payload


class RustProviderEnvelopeParityTests(unittest.TestCase):
    @unittest.skipUnless(rust_bridge.extension() is not None, "Rust extension is opt-in")
    def test_rust_full_envelope_matches_python_reference(self) -> None:
        core = rust_bridge.extension()
        self.assertIsNotNone(core)
        payload = json.loads(
            (Path(__file__).parent / "fixtures/b10/provider_usage.json").read_text(
                encoding="utf-8"
            )
        )
        expected = provider_usage_from_payload(payload)
        rust_dto = json.loads(core.provider_usage_from_json(json.dumps(payload)))
        actual = _provider_from_dto(rust_dto)

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
