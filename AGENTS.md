# Repository guidance

## Native Rust application

The approved destination is a **fully native Rust GTK4/libadwaita application**,
not a permanent Python GTK shell. The shipped application and default
repository launch/install paths are native Rust GTK4/libadwaita.

Before migration work, read:

1. [`docs/rust-migration/README.md`](docs/rust-migration/README.md) — architecture,
   boundaries, compatibility requirements, and verification gates.
2. [`docs/rust-migration/TASKS.md`](docs/rust-migration/TASKS.md) — current handoff,
   stable task IDs, dependencies, and the next implementation slice.
3. [`docs/rust-migration/AUDIT.md`](docs/rust-migration/AUDIT.md) — decisions,
   historical evidence, and the append-only implementation/verification log.

Do not infer gate acceptance from a local retirement candidate or the existence
of a Rust module. UG remains **NOT PASSED** and C01–CG remain unaccepted until
their documented evidence and root review are complete. Historical Python
implementation and parity tests live under `tests/reference/python/`; they are
not shipped, installed, imported by active tests, or a runtime fallback.

## Continuation protocol

- Check `git status -sb`, recent commits, and open PRs before editing. Do not
  discard someone else's uncommitted work or duplicate an in-flight task.
- Claim one ready task/slice in `TASKS.md` with a branch and status. Keep each
  module/integration in a separate, reviewable PR.
- Update the handoff and append an audit entry in the same implementation PR.
  Record paths, behavior decisions, exact checks/results/skips, UI smoke-test
  scope, blockers, and the precise next step. Never record a merge/CI success
  before observing it; use PR links plus live GitHub status when resuming.
- Stop or switch tasks only with an explicit handoff. A partial implementation
  must stay marked partial; a failing test is a blocker, not completed work.
- Retain Python files only as clearly marked references. Never restore them as
  a runtime fallback. Keep active Python scripts under `scripts/` only when
  they automate or verify the native application; they are test tooling, not
  shipped runtime dependencies.

## Project invariants

- `VERSION` is the only project version source. Native metadata checks must
  read it directly; there is no `codexbar_gtk/version.py`. For a merge-approved
  PR, increment `CURRENT_PROJECT_VERSION`, update `CHANGELOG.md` and README's
  displayed build. Marketing version follows supported upstream CodexBar;
  Cargo package metadata is not a separate release. BUILD116 is the current
  retirement-candidate allocation; do not update archived `version.py` metadata.
- Rollback uses a previous verified Git tag/commit or preserved native build
  artifact with the data-preserving native installer. Never use a permanent
  Python runtime fallback. Existing unowned commands, desktop files and
  services must be preserved by installer upgrade/uninstall logic.
- Use synthetic CLI/account/history/login fixtures. Never put real accounts,
  API keys, OAuth codes, credential-bearing URLs, or authentication output in
  screenshots, tests, logs committed to git, or the audit trail.
- Preserve settings/history compatibility and missing/partial-data semantics.
  Use temporary homes and private D-Bus sessions for isolated tests where useful.
- Run the native core/backend/GTK, tray, X11, private Wayland, installer, and
  Python-free runtime-proof checks in the migration guide. Archived Python
  parity assertions do not count as native verification. Do not delete an
  archived assertion until a corresponding native assertion is identified.
