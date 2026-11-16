# Archived Python application reference

This tree is historical source and assertion material only. It is not in the
application search path, is not packaged or installed, and CI intentionally
does not discover tests beneath this directory. Do not restore a Python
launcher or use this archive as an application rollback path. Roll back with a
previous verified native Git tag/commit or preserved native build artifact and
the ownership-aware native installer.

`legacy/codexbar_gtk/` contains the former Python GTK application and PyO3
adapters. `legacy/test_*.py` contains Python application, parity, and adapter
tests. `tools/` contains former Python GTK smoke/preview programs. Shared
synthetic fixtures remain under `tests/fixtures/` for current Rust tests.

## Coverage disposition

The Rust GTK test `version_metadata_tracks_the_root_version_file` now checks
native metadata directly from root `VERSION` and README. The Rust CLI service
integration test added in PR #113 maps selected public CLI service assertions
to native coverage.

Coverage peer commit `e7973fa` (reviewed read-only; not cherry-picked) adds
`rust-backend/tests/legacy_assertion_map.md`. That map covers every method from
the former `test_app.py` and `test_python_settings_facade.py`, with Rust public
settings-service assertions and 26 retired methods. Those peer tests and map
are not in this candidate branch. The Python files remain intact in this
archive until root reviews and integrates the peer work.

The map identifies these unresolved dispositions; this candidate makes no
blanket claim that all legacy assertions are retired:

- `test_python_cli_reconfigure_preserves_permissive_path_and_timezone_behavior`:
  Python accepts a nonexistent configured CLI path while Rust rejects it. The
  native validation is an intentional stricter policy candidate; root must
  document and accept that behavior explicitly before retiring this assertion.
- `CLITests.test_missing_binary_raises`: the Python wrapper's exception has no
  native counterpart. Keep this legacy-only unless root defines a native
  contract; do not invent equivalence.
- Startup checks for immediate readiness/no-sleep, injected monotonic deadline
  cadence, and callback exceptions remain unmapped. Rust's callback is a
  non-fallible `FnMut() -> bool`; the Python callback exception policy may stay
  legacy-only instead of adding panic-catching behavior to Rust. No equivalent
  assertion is claimed.

Before integration, root requires both the default Python suite and the
`CODEXBAR_RUST_CORE=1` Python suite on the peer coverage branch, before applying
this runtime retirement. This candidate cannot run those modes because it
removes the Python package and PyO3 crate. UG remains **NOT PASSED** and C01–CG
remain unaccepted.
