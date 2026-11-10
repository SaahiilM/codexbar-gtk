"""Runtime parity and persistence checks for the optional Rust history store."""

from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codexbar_gtk.controller import Controller
from codexbar_gtk.history import HistoryStore, Sample
from codexbar_gtk.prefs import Preferences

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "codexbar_gtk" / "_rust_core.so"


@unittest.skipUnless(
    EXTENSION.is_file(), "build the extension with scripts/build-rust-core.sh"
)
class RustHistoryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = importlib.import_module("codexbar_gtk._rust_core")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def backend(self, core):
        return patch("codexbar_gtk.history.rust_bridge.extension", return_value=core)

    def test_append_rounding_and_read_cache_match_python(self) -> None:
        values = [2.675, 1.005, 1.015, 1.225, -2.675, -0.005, 1e20]
        samples = [
            Sample(1000.125 + i, "codex", "primary", value)
            for i, value in enumerate(values)
        ]
        results = []
        for name, core in (("python", None), ("rust", self.core)):
            with self.backend(core):
                path = self.folder / name / "history.jsonl"
                store = HistoryStore(path)
                self.assertEqual(store.read_all(), [])
                store.append([])
                self.assertFalse(path.exists())
                store.append(samples)
                first = store.read_all()
                first.clear()
                self.assertEqual(len(store.read_all()), len(samples))
                store.append([Sample(1010.0, "provider-λ", "weekly", 10.0)])
                results.append(
                    (
                        store.read_all(),
                        [json.loads(line) for line in path.read_text().splitlines()],
                    )
                )
                if core is not None:
                    self.assertIsInstance(store._rust, self.core.HistoryStore)
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            [s.used_percent for s in results[1][0][:-1]],
            [round(value, 2) for value in values],
        )

    def test_large_integer_samples_use_the_reference_float_rounding(self) -> None:
        value = 2**60 + 1
        results = []
        for core in (None, self.core):
            with self.backend(core):
                store = HistoryStore(self.folder / f"wide-{core is not None}.jsonl")
                store.append([Sample(value, "codex", "primary", value)])
                results.append(store.read_all())
        expected = Sample(float(round(value, 2)), "codex", "primary", float(round(value, 2)))
        self.assertEqual(results, [[expected], [expected]])

    def test_history_write_reports_python_integer_outside_float_range(self) -> None:
        value = 10**1000
        python_path = self.folder / "python-huge.jsonl"
        with self.backend(None):
            python_store = HistoryStore(python_path)
            python_store.append([Sample(value, "codex", "primary", 1.0)])
            self.assertTrue(python_path.is_file())
            self.assertEqual(python_store.read_all(), [])

        with self.backend(self.core):
            rust_store = HistoryStore(self.folder / "rust-huge.jsonl")
            with self.assertRaisesRegex(OverflowError, "finite floating-point range"):
                rust_store.append([Sample(value, "codex", "primary", 1.0)])

    def test_file_remains_readable_when_switching_backends(self) -> None:
        path = self.folder / "history.jsonl"
        first = Sample(1000.0, "codex", "primary", 10.0)
        second = Sample(1100.0, "codex", "primary", 20.0)
        with self.backend(None):
            HistoryStore(path).append([first])
        with self.backend(self.core):
            store = HistoryStore(path)
            self.assertEqual(store.read_all(), [first])
            store.append([second])
        with self.backend(None):
            self.assertEqual(HistoryStore(path).read_all(), [first, second])

    def test_series_and_retention_cutoffs_match_python(self) -> None:
        samples = [
            Sample(1000.0, "codex", "primary", 5.0),
            Sample(86400.1, "codex", "primary", 30.0),
            Sample(86400.0, "codex", "primary", 20.0),
            Sample(90000.0, "claude", "primary", 90.0),
            Sample(90000.0, "codex", "secondary", 40.0),
        ]
        results = []
        for name, core in (("python", None), ("rust", self.core)):
            with (
                self.backend(core),
                patch("codexbar_gtk.history.time.time", return_value=172800.0),
            ):
                store = HistoryStore(
                    self.folder / name / "history.jsonl", retention_days=1
                )
                store.append(samples)
                self.assertEqual(
                    store.series("codex", "primary"), [(86400.0, 20.0), (86400.1, 30.0)]
                )
                self.assertEqual(store.series("missing", "primary"), [])
                store.prune()
                results.append(store.read_all())
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[1]), 4)

    def test_corrupt_records_do_not_break_history(self) -> None:
        path = self.folder / "history.jsonl"
        shutil.copyfile(ROOT / "tests/fixtures/b15/persisted_history.jsonl", path)
        results = []
        for core in (None, self.core):
            with self.backend(core):
                results.append(HistoryStore(path).read_all())
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            results[1],
            [
                Sample(0.0, "", "", 0.0),
                Sample(10.25, "codex", "primary", 20.0),
                Sample(1.0, "codex", "primary", 0.0),
                Sample(float(2**60), "codex", "wide", float(2**60)),
            ],
        )

    def test_filesystem_errors_remain_nonfatal(self) -> None:
        for core in (None, self.core):
            with self.backend(core):
                blocker = self.folder / ("rust" if core else "python")
                blocker.write_text("not a directory")
                for path in (blocker / "history.jsonl", self.folder):
                    store = HistoryStore(path)
                    store.append([Sample(1000.0, "codex", "primary", 10.0)])
                    store.prune()
                    self.assertEqual(store.read_all(), [])

    def test_unsupported_write_is_rejected_without_switching_backends(
        self,
    ) -> None:
        with self.backend(self.core):
            store = HistoryStore(self.folder / "history.jsonl")
            store.append([Sample(1000.0, "codex", "primary", 10.0)])
            self.assertEqual(len(store.read_all()), 1)
            with self.assertRaisesRegex(TypeError, "Rust history samples"):
                store.append([Sample(1100.0, "codex", "primary", float("nan"))])
            self.assertFalse(store._python_only)
            store.append([Sample(1200.0, "codex", "primary", 30.0)])
            self.assertEqual(
                [sample.used_percent for sample in store.read_all()], [10.0, 30.0]
            )

    def test_changed_path_and_retention_reconfigure_native_store(self) -> None:
        with (
            self.backend(self.core),
            patch("codexbar_gtk.history.time.time", return_value=172800.0),
        ):
            store = HistoryStore(self.folder / "first.jsonl")
            store.append([Sample(1000.0, "codex", "primary", 10.0)])
            self.assertEqual(len(store.read_all()), 1)
            store.path = self.folder / "second.jsonl"
            self.assertEqual(store.read_all(), [])
            store.append([Sample(1000.0, "codex", "primary", 20.0)])
            store.retention_days = 1
            store.prune()
            self.assertEqual(store.read_all(), [])

    def test_concurrent_native_appends_and_prunes_keep_retained_samples(self) -> None:
        with (
            self.backend(self.core),
            patch("codexbar_gtk.history.time.time", return_value=10000.0),
        ):
            store = HistoryStore(self.folder / "history.jsonl")

            def append(index):
                store.append([Sample(9999.0, "codex", "primary", float(index))])
                store.read_all()
                store.prune()

            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(append, range(24)))
            self.assertEqual(len(store.read_all()), 24)

    def test_controller_records_and_queries_history_through_rust(self) -> None:
        payload = {"provider": "codex", "usage": {"primary": {"usedPercent": 25.0}}}
        cli = SimpleNamespace(
            usage=lambda *args, **kwargs: [payload],
            sessions=list,
            version=lambda: "CodexBar fixture",
        )
        with (
            self.backend(self.core),
            patch("codexbar_gtk.history.time.time", return_value=10000.0),
        ):
            prefs = Preferences(str(self.folder / "settings.json"))
            prefs.set("costUsageEnabled", False)
            controller = Controller(prefs, cli)
            controller.history = HistoryStore(self.folder / "history.jsonl")
            self.assertIsNone(controller.refresh().last_error)
            self.assertIsInstance(controller.history._rust, self.core.HistoryStore)
            self.assertEqual(
                controller.history.series("codex", "primary"), [(10000.0, 25.0)]
            )
