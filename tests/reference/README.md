# Historical Python reference

The legacy Python application and parity tests were removed from the current
tree after native runtime verification. Their last retained source snapshot was
commit [`52b8b11`](https://github.com/SaahiilM/codexbar-gtk/commit/52b8b11bb922ed39ec8c74496138bc129b552f8a),
under `tests/reference/python/legacy/codexbar_gtk/` and
`tests/reference/python/legacy/test_*.py`. Before retirement, the application
sources lived under `codexbar_gtk/`, with parity tests under `tests/`.
Earlier revisions remain available in Git history; this document is not a
runtime rollback mechanism.

## Preserved behavior decisions and native coverage

- Missing, invalid, or partial usage and cost remain distinct from known zero;
  failed refreshes retain prior useful totals. See `rust-core/src/domain.rs`,
  `rust-backend/src/controller.rs`, and `rust-backend/src/presentation.rs`.
- CLI calls preserve argument boundaries, timezone, timeout, cancellation and
  sanitized errors. See `rust-backend/src/cli.rs` and
  `rust-backend/tests/cli_service.rs`.
- Preferences and history retain their JSON/JSONL shapes and portable import /
  export behavior. See `rust-core/src/preferences.rs`,
  `rust-core/src/history.rs`, and `rust-backend/tests/settings_facade.rs`.
- Provider/session ordering, timestamps, currency conversion, login process
  handling and notification policies have native contracts in `rust-core/`
  and `rust-backend/`; selected application/settings assertion mappings remain
  in `rust-backend/tests/legacy_assertion_map.md`.
- Native app and UI coverage lives in `rust-gtk/` and the active synthetic
  harnesses under `tests/test_*.py` and `scripts/`. These Python modules are
  test automation only. Synthetic JSON fixtures remain in `tests/fixtures/`.

This record summarizes selected policy and coverage links; it does not claim
that every historical Python assertion has an equivalent or that UG, C01, C02,
C03, or CG has passed. The migration checklist and audit remain authoritative
for open work and evidence.
