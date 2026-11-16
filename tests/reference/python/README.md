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
to native coverage. Remaining historical Python assertions are intentionally
preserved here; they are not claimed as covered or passed. Root must reconcile
the per-assertion peer map before deleting any assertion group or claiming a
cutover gate. UG remains **NOT PASSED** and C01–CG remain unaccepted.
