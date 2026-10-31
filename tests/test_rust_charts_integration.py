"""Behavior parity for Rust-backed sparkline geometry."""

from __future__ import annotations

import importlib
import random
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock, patch

from codexbar_gtk import charts

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(
    EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh"
)
class RustChartsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = importlib.import_module("codexbar_gtk._rust_core")

    def compare_backends(self, points, width=101, height=24):
        with patch("codexbar_gtk.charts.rust_bridge.extension", return_value=None):
            expected = charts.sparkline_coordinates(points, width, height)
        with patch("codexbar_gtk.charts.rust_bridge.extension", return_value=self.core):
            actual = charts.sparkline_coordinates(points, width, height)
        self.assertEqual(len(actual), len(expected))
        for first, second in zip(actual, expected):
            self.assertAlmostEqual(first[0], second[0])
            self.assertAlmostEqual(first[1], second[1])

    def test_geometry_edge_cases_match_python(self) -> None:
        cases = [
            [],
            [(0.0, 5.0)],
            [(0.0, 0.0), (10.0, 100.0)],
            [(0.0, -10.0), (1.0, float("nan")), (2.0, 120.0)],
            [(float("inf"), 50.0), (0.0, 10.0), (1.0, 20.0)],
            [(3.0, 20.0), (3.0, 30.0), (3.0, 40.0)],
            [(3.0, 20.0), (2.0, 30.0), (1.0, 40.0)],
            [(0.0, 20.0), (9.0, 30.0), (3.0, 40.0)],
        ]
        for points in cases:
            for width, height in [
                (101, 24),
                (1, 24),
                (101, 4),
                (0, 0),
                (-10, 20),
                (500, 150),
            ]:
                with self.subTest(points=points, width=width, height=height):
                    self.compare_backends(points, width, height)

    def test_randomized_history_geometry_matches_python(self) -> None:
        rng = random.Random(42)
        for _ in range(40):
            points = [
                (1_800_000_000 + rng.uniform(-10000, 10000), rng.uniform(-20, 120))
                for _ in range(30)
            ]
            points.sort()
            self.compare_backends(points, rng.randint(2, 900), rng.randint(5, 300))

    def test_adapter_calls_native_geometry(self) -> None:
        spy = Mock(wraps=self.core)
        points = [(0.0, float("nan")), (10.0, 20.0), (20.0, 30.0)]
        with patch("codexbar_gtk.charts.rust_bridge.extension", return_value=spy):
            charts.sparkline_coordinates(points, 100, 20)
        spy.sparkline_coordinates.assert_called_once_with(
            [(0.0, 20.0), (1.0, 30.0)], 100.0, 20.0
        )

    def test_fraction_and_wide_numeric_inputs_match_python(self) -> None:
        cases = [
            ([(0.0, Fraction(20)), (1.0, Fraction(40))], 101, 24),
            ([(2**60, 20.0), (2**60 + 1000, 30.0)], 101, 24),
            ([(0.0, 20.0), (1.0, 40.0)], 2**60, 24),
            (
                [(Fraction(-(10**308), 1), 20), (Fraction(10**308, 1), 80)],
                101,
                24,
            ),
            ([(0, float("nan")), (2**60, 20), (2**60 + 1, 80)], 101, 24),
        ]
        for points, width, height in cases:
            with self.subTest(points=points, width=width):
                self.compare_backends(points, width, height)

    def test_values_outside_python_float_range_keep_python_overflow(self) -> None:
        points = [(2**2000, 20.0), (2**2000 + 1, 30.0)]
        with patch("codexbar_gtk.charts.rust_bridge.extension", return_value=None):
            with self.assertRaises(OverflowError):
                charts.sparkline_coordinates(points, 101, 24)
        with patch("codexbar_gtk.charts.rust_bridge.extension", return_value=self.core):
            with self.assertRaises(OverflowError):
                charts.sparkline_coordinates(points, 101, 24)
