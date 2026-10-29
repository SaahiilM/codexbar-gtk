# Repository guidance

## Native Rust migration — read first

The approved destination is a **fully native Rust GTK4/libadwaita application**,
not a permanent Python GTK shell. **Finish the backend before migrating the UI.**

Before migration work, read:

1. [`docs/rust-migration/README.md`](docs/rust-migration/README.md) — architecture,
   boundaries, compatibility requirements, and verification gates.
2. [`docs/rust-migration/TASKS.md`](docs/rust-migration/TASKS.md) — current handoff,
   stable task IDs, dependencies, and the next implementation slice.
3. [`docs/rust-migration/AUDIT.md`](docs/rust-migration/AUDIT.md) — decisions,
   historical evidence, and the append-only implementation/verification log.

Do not infer completion from the existence of a Rust file or a checked entry in
README's original six-module checklist. Those are opt-in integrations, not a
completed Rust backend or native application.

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
- Keep Python implementations as parity references during backend migration.
  Remove them only at the cutover gates. No native UI migration before gate BG.

## Project invariants

- Increment `CURRENT_PROJECT_VERSION` in `VERSION` and `BUILD` in
  `codexbar_gtk/version.py` for each PR intended to merge, including docs PRs.
  Update `CHANGELOG.md` and README's displayed build. Marketing version follows
  supported upstream CodexBar; Cargo package metadata is not a separate release.
- Rust remains opt-in (`CODEXBAR_RUST_CORE=1`) until an explicit, tested cutover.
  Explicit opt-in must fail clearly if the extension is unavailable.
- Use synthetic CLI/account/history/login fixtures. Never put real accounts,
  API keys, OAuth codes, credential-bearing URLs, or authentication output in
  screenshots, tests, logs committed to git, or the audit trail.
- Preserve settings/history compatibility and missing/partial-data semantics.
  Use temporary homes and private D-Bus sessions for isolated tests where useful.
- Build with `scripts/build-rust-core.sh`; its atomic replacement protects a
  shared library mapped by a running app. Do not truncate `_rust_core.so`.
- Run the checks in the migration guide. Unit parity is not a substitute for
  exercising the runtime path in the GTK application.
