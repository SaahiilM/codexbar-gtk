# Migration decisions and audit trail

This is an **append-only record of observations and decisions**, not the live
task board. [TASKS.md](TASKS.md) owns the current handoff. Entries describe what
was true when recorded; later entries supersede earlier decisions explicitly.
Do not rewrite historical outcomes to look successful. Correct factual errors
with a dated correction and reference the original entry.

Record only synthetic/redacted evidence. Never include accounts, API keys,
OAuth codes, credential-bearing URLs, PTY auth output or real usage payloads.
Do not rely on `/tmp` files, process IDs or an agent's conversation memory as
persistent evidence. Cite committed tests, source functions, CI/PR links and
reproducible commands; report artifact limitations honestly.

## Decision log

### D001 — 2026-10-29: native destination; backend before UI

- **Authority:** user explicitly selected option 2, a fully native Rust GTK4
  app, then directed backend work first and UI migration afterward, with a
  resumable checklist and audit trail for subsequent models.
- **Decision:** the Python GTK shell and PyO3 bridge are transitional, not the
  final architecture. Complete gate BG before native UI implementation; remove
  Python runtime dependencies only after native UI and cutover gates.
- **Scope boundary:** upstream CodexBar/provider CLIs remain external; do not
  invent a new provider/authentication implementation as part of this rewrite.
- **Consequence:** the six checked historical ports cannot be described as a
  completed backend or fully ported application. README now links the broader
  pending work instead of implying there is one last Python file.

### D002 — 2026-10-29: share one backend between transitional and native UIs

- **Decision:** extend the existing Rust domain core, plan a headless Rust
  service layer, keep PyO3 as a thin temporary adapter and later connect the
  native GTK binary directly to the same backend API.
- **Not yet decided:** concrete async/blocking runtime, HTTP/PTY/process crates,
  detailed snapshot/event API and workspace layout. B00 must decide and test
  these; `rust-backend/` and `rust-gtk/` do not exist at this checkpoint.
- **Consequence:** no GTK/Python types in backend contracts, no embedded Python
  in the final binary and no duplicate service implementation for each UI.

### D003 — 2026-10-29: compatibility, safety and completion evidence

- Keep Python parity references and opt-in routing during backend migration.
  Characterize edge behavior before changing it. If behavior is corrected rather
  than preserved, add a regression fixture and record the reason explicitly.
- Settings/history formats, unknown-versus-zero spend/usage, cancellation,
  command argv/TZ, account tracking and notification deduplication are contracts,
  not implementation details to lose during translation.
- Use focused module PRs with synchronized GTK build increments; Cargo package
  metadata is not a separate release version. Test the Rust path in the app as
  well as through unit tests. Fixtures must not use real accounts or sign-ins.
- Existing CI's Python/Rust parity tests are necessary but insufficient for BG:
  a compiled headless Rust flow must run without Python/GTK/PyO3.
- A task is checked only with observed merged evidence. An implementation entry
  may be committed before its own PR merges: record its PR URL and status at the
  time, and let GitHub/git provide the later merge result. Never pre-record it.

### D004 — 2026-10-29: B00 backend runtime and publication contract

- **Runtime:** use Tokio for async orchestration and `tokio::process` for CLI
  children. The application owns the runtime, allowing frontend-specific startup
  and shutdown. GTK must not block on backend I/O.
- **Publication:** expose immutable, versioned latest-state snapshots using
  `tokio::sync::watch`; consumers marshal changes onto their own UI thread.
  Coalescing is appropriate for dashboard snapshots. Any operation needing
  lossless events must define a separate bounded event channel.
- **Cancellation/shutdown:** cooperative cancellation token plus explicit task
  join. Long operations must also impose their own timeouts; B07/B11 must prove
  child/PTY reaping. Drop requests cancellation but cannot await task completion.
- **Errors:** public state contains stable error categories and static operation
  IDs only, not raw stderr, HTTP URLs, credential data or arbitrary error text.
  Services must redact diagnostics at their source.
- **Dependencies:** `tokio` and `tokio::process` selected in B00. Add `reqwest`
  with Rustls in B06 for HTTP; defer `portable-pty` until B11 verifies platform
  needs with fake login tests. Keep the backend crate separate from the GTK/PyO3
  crates for now; no workspace migration is justified by this contract slice.
- **Alternatives:** synchronous service traits would force blocking or add an
  ad-hoc thread pool for HTTP, child processes and login. An unbounded event
  stream risks stale UI state and unbounded memory. These were rejected for
  backend orchestration; domain transformations remain synchronous/pure.

### D005 — 2026-10-29: first B01 primitive compatibility boundary

- Rust timestamp parsing accepts common RFC 3339 timestamps, `Z`, date-only,
  naive UTC, fractions and whitespace trimming. Inputs unsupported by the Rust
  parser fall back to Python's broader `datetime.fromisoformat` grammar during
  migration; Python remains default outside opt-in. Thus no valid Python-only
  form is rejected in the transitional caller.
- Numeric helpers continue to reject booleans, strings, overflow and non-finite
  values. Rust's quota duration contract is `i64`; values outside that range
  fall through to Python's existing float-then-int behavior. Preserve this
  compatibility fallback until Rust domain models support the full desired
  numeric range or an explicit behavior change is approved.
- A missing/invalid used percentage remains distinguishable from a known 0% in
  the source parser (`usage_known`); the new Rust `RateWindow` carries this bit.
  Remaining percentage continues to clamp at zero; duration labels match current
  Python logic. Other domain models and payload normalization remain pending.

## Evidence log

### E001 — 2026-10-29: inherited implementation baseline

- **Code:** `46f44d0951baac880d33017cbc1136bd04420864`, build `0.81.0 (16)`.
- **Observed merges:**
  - [PR #14](https://github.com/SaahiilM/codexbar-gtk/pull/14): monthly pace.
  - [PR #15](https://github.com/SaahiilM/codexbar-gtk/pull/15): correct D-Bus
    tooltip/icon/menu/status notifications. Preserve this regression coverage.
  - [PR #16](https://github.com/SaahiilM/codexbar-gtk/pull/16), `8b3c017`:
    native history storage/query integration, decimal rounding and concurrency
    fixes, corrupt-record handling and atomic extension replacement.
  - [PR #17](https://github.com/SaahiilM/codexbar-gtk/pull/17), `46f44d0`:
    native sparkline geometry with edge/randomized parity tests.
- **CI:** PR #17 was queried during this audit with `gh pr view 17 --json
  state,mergeCommit,statusCheckRollup`; it was merged and both `test` and
  `tray-dbus` checks had succeeded.
- **Persisted coverage:** `tests/test_rust_provider_*.py`,
  `tests/test_rust_catalog_parity.py`, `tests/test_rust_activity_integration.py`,
  `tests/test_rust_format_integration.py`, `tests/test_rust_pace_integration.py`,
  `tests/test_rust_history_integration.py`, `tests/test_rust_charts_integration.py`,
  and `tests/test_tray_signals.py`, plus native unit tests.
- **Historical runtime evidence (not rerun for this docs change):** the previous
  history/chart work launched the actual GTK app with synthetic CLI/history
  fixtures, confirmed native recording/querying and chart binding calls, and
  inspected sparklines/reset projection. The prior session reported the normal
  Rust-enabled development app running after merge. Recheck process/runtime
  state instead of treating that report as a current guarantee.
- **Limits:** those were focused fixture smoke tests, not comprehensive GUI,
  real-provider, auth, or clean-machine native-runtime tests. Temporary screenshots
  from those sessions are not durable automated evidence for future changes.

### E002 — 2026-10-29: fresh backend inventory and validation

- **Branch at recording:** `docs/native-rust-migration-roadmap`, based on E001.
- **Source inspection:** `data.py`, `controller.py`, `cli.py`, `prefs.py`,
  `currency.py`, `login.py`, `updates.py`, `startup.py`; UI file/function inventory
  and embedded spend/settings/application policies; both Cargo manifests,
  install/build scripts, README, migration notes, existing test classes and CI.
- **Finding:** substantial Python business/service logic remains. In particular,
  `ui/spend.py` still groups model totals and applies currency/partial-data rules;
  settings/application code still launches workers and service actions. A
  top-level module inventory alone would miss these backend responsibilities.
- **Finding:** existing test coverage is uneven. Payload/controller behavior has
  characterization tests, but CLI failure/cancellation, currency HTTP/cache
  lifecycle and PTY login need substantially more coverage. B tasks explicitly
  require new fixtures; existing passing tests do not close these gaps.
- **Checks actually run, before documentation/version edits:**

  ```sh
  source "$HOME/.cargo/env"
  cargo fmt --manifest-path rust-core/Cargo.toml -- --check
  cargo fmt --manifest-path rust-python/Cargo.toml -- --check
  cargo test --manifest-path rust-core/Cargo.toml --locked
  cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
  cargo clippy --manifest-path rust-python/Cargo.toml --all-targets --all-features -- -D warnings
  ./scripts/build-rust-core.sh
  python3 -m unittest discover -s tests -q
  CODEXBAR_RUST_CORE=1 python3 -m unittest discover -s tests -q
  ```

- **Results:** formatting/Clippy/build passed; 30 Rust tests passed; 132 Python
  tests passed in each mode, with no skips reported locally. D-Bus dependencies
  were available. This does not imply native UI or a Rust-only backend exists.
- **Runtime/GUI checks:** not performed in this planning audit. No provider
  requests, real-account screenshots or sign-ins were required by these checks.

### E003 — 2026-10-29: resumable backend-first plan established

- **Scope:** documentation and synchronized build metadata only; no new Rust
  model, backend service, widget or behavioral migration is implemented here.
- **Files:** root `AGENTS.md`; this guide, TASKS and AUDIT under
  `docs/rust-migration/`; README and `rust-core/README.md` links; VERSION,
  `codexbar_gtk/version.py` and CHANGELOG for `0.81.0 (17)`.
- **Task state:** F01–F06 are inherited merged foundation; B00–B15 and BG remain
  unchecked. U tasks are blocked by BG; cutover is blocked by UG.
- **Next exact step:** verify current git/open-PR state, claim B00, specify the
  service/snapshot/error/cancellation contract and test seam, then start B01's
  timestamp/numeric/quota-window slice. Do not begin native UI or delete Python.
- **PR/merge provenance:** locate the commit containing this entry with
  `git log -- docs/rust-migration/AUDIT.md` and its associated PR. At initial
  recording this documentation was not yet merged; never infer a future success
  from the intended build number. Subsequent checks belong in a new entry.

### E004 — 2026-10-29: planning verification and review handoff

- **Owner:** coding-agent planning session; branch
  `docs/native-rust-migration-roadmap`, base `46f44d0`, initial plan commit
  `96099bf`.
- **PR observed:** [PR #18](https://github.com/SaahiilM/codexbar-gtk/pull/18)
  was created and open when this entry was recorded. CI/merge outcome was not
  yet observed; check that PR directly before continuing.
- **Post-edit validation:** `python3 -m unittest discover -s tests -q` and
  `CODEXBAR_RUST_CORE=1 python3 -m unittest discover -s tests -q` each passed
  132 tests with no skips; `git diff --check` passed. Rust format/test/Clippy
  and build results are the unchanged-code baseline in E002, not a claim that
  a new backend implementation exists.
- **Documentation check:** a one-off local Python `pathlib`/`re` check resolved
  25 relative Markdown links and verified B00–B15, U01–U08, C01–C03 and BG/UG/CG
  task IDs. This check is not a committed automated test; repeat link checks if
  moving these files.
- **Runtime/UI:** not rerun; documentation/build metadata only. No Python
  removal, backend service implementation or native UI work in this PR.
- **Handoff:** no backend task claimed and no known external blocker. After
  verifying this PR's merge status, claim B00 and implement its contracts/test
  seam; follow with B01's timestamp/numeric/quota-window slice.

### E005 — 2026-10-29: B00 service contract implementation

- **Owner/branch/base:** current coding-agent session;
  `backend/b00-service-contract`, based on merged `69c5496` (PR #18).
- **Scope:** create `rust-backend/` with locked Cargo metadata and generic
  headless lifecycle contract: immutable Arc-backed snapshots, status/error
  state, version sequence, cooperative cancellation, publication and joined
  shutdown. The crate depends on `rust-core` and Tokio, not GTK/Python. Three
  fake-worker tests cover cancellation/join, preserving successful data through
  a later failed refresh, and visible sanitized task failure.
- **Integration limits:** no provider/domain fetch adapter exists yet and no
  current Python caller is routed through this crate. B00 is service scaffolding,
  not a completed runtime backend. No app behavior changed.
- **CI/tooling:** workflow now watches `rust-backend/**` and runs its format,
  locked tests and Clippy checks. `.gitignore` excludes its build output.
- **Checks actually run:** rustfmt checks for core/PyO3/backend; 30 core and 3
  backend tests; Clippy with warnings denied for all 3 crates; PyO3 extension
  build; 132 Python tests in default and Rust modes; 3 private-D-Bus tray tests;
  `git diff --check`; locked Cargo metadata. All passed; no skips reported.
- **UI/runtime smoke:** not run, because this change exposes only a generic
  headless contract and the existing application is not yet a caller. The
  `cargo test --manifest-path rust-backend/Cargo.toml --locked` suite runs
  without Python, GTK, or PyO3. No real provider/account data used.
- **PR:** [PR #19](https://github.com/SaahiilM/codexbar-gtk/pull/19), commit
  `b6c90be`; open when this handoff update was recorded. CI/merge status must be
  checked live. Do not mark B00 complete until merge is observed.
- **Next:** observe PR checks/merge, then start B01's timestamp/numeric/
  `RateWindow` characterization and Rust model implementation.

### E006 — 2026-10-29: B00 merge verified

- **PR/merge:** [PR #19](https://github.com/SaahiilM/codexbar-gtk/pull/19)
  merged at `956ffd3b3631ce4541ab9cc382023bc9cc803fd7`; `test` and `tray-dbus`
  checks both succeeded. Main was fast-forwarded and clean at verification.
- **Result:** B00 is checked in TASKS. Build `0.81.0 (18)`. This is backend
  contract infrastructure only, not provider fetching or a complete backend.
- **Next:** B01a, timestamp/numeric primitives and `RateWindow`; no native UI.

### E007 — 2026-10-29: B01a primitive implementation, pre-PR verification

- **Owner/branch/base:** current coding-agent session;
  `backend/b01-domain-foundation`, based on merged `956ffd3` (PR #19).
- **Changed scope:** `rust-core/src/domain.rs` adds UTC timestamp parsing,
  JSON finite-number helpers, an i64 `RateWindow` contract and derived values;
  `rust-python/src/lib.rs` exposes PyO3 calls; `codexbar_gtk/data.py` routes
  timestamp, numeric and derived-property callers through Rust when opt-in while
  retaining Python fallbacks; `tests/test_rust_domain_integration.py` adds
  cross-mode fixtures. `Pace`, `CostInfo`, remaining payload model contracts and
  provider/session/spend normalization are not included.
- **Behavior boundary:** see D005. Rust supports common ISO forms; less common
  valid Python forms are intentionally handled by Python fallback. Out-of-i64
  integer durations also fallback rather than truncating.
- **Checks actually run:** rustfmt, 33 core and 3 backend tests, Clippy on all
  three Rust crates, extension build, 135 Python tests in default mode and 135
  in Rust mode, plus 3 private-D-Bus tray tests; all passed, no skips reported.
- **UI smoke:** attempted `GDK_BACKEND=offscreen CODEXBAR_RUST_CORE=1
  python3 tools/preview.py` with a fake CLI returning synthetic provider data
  and isolated `HOME`. It could not start because GTK4 typelib `Gtk` 4.0 is not
  installed in either the default or `/usr/bin/python3` environment. No real
  provider data was requested. This is an environment blocker, not a passing UI
  check; retry when GTK4 dependencies are available.
- **PR/status:** [PR #20](https://github.com/SaahiilM/codexbar-gtk/pull/20),
  commit `5a776b9`; open when this handoff was recorded. CI/merge must be checked
  live. Build metadata is `0.81.0 (19)`.
- **Next:** observe PR CI/merge, report missing GTK4 smoke as a limitation, then
  continue B01b (remaining data model contracts).

### E008 — 2026-10-29: B01a merged; B01b Pace/CostInfo models

- **B01a merge:** [PR #20](https://github.com/SaahiilM/codexbar-gtk/pull/20)
  merged at `6fa18c909dbcf8ef9a2135b0ba8dd7373d98f626`; both `test` and
  `tray-dbus` CI checks succeeded. Main was fast-forwarded and clean.
- **B01b owner/branch/base:** current coding-agent session;
  `backend/b01b-pace-cost-models`, based on merged `6fa18c9`.
- **Scope:** Rust `Pace` and `CostInfo` types/derived policies in
  `rust-core/src/domain.rs`; PyO3 helpers and opt-in routing in
  `rust-python/src/lib.rs` and `codexbar_gtk/data.py`; parity tests in
  `tests/test_rust_domain_integration.py`. `ProviderUsage`, detail/credit,
  session and spend model contracts remain for B01c.
- **Behavior detail:** preserve Python cost percent behavior for NaN (treated as
  the upper clamp through Python's `min` argument order), positive infinity,
  no/negative limit, negative usage and >100% usage. Unknown pace stages retain
  their source label and do not classify as deficit/reserve.
- **Focused checks:** 35 core tests, 3 backend tests, and 5 domain integration
  tests passed; Rust formatting/Clippy and extension build passed. Full suites
  and CI pending at first recording.
- **UI smoke:** not rerun; B01a's synthetic preview attempt remains blocked by
  missing GTK4 typelibs (E007). This slice only changes value derivations, not
  widget structure; do not claim a UI pass.
- **Status:** implementation verified locally before PR creation; not merged.
  Build `0.81.0 (20)`.
- **Next:** run full three-crate/Python checks, create a focused PR, observe CI,
  then proceed to B01c's remaining shared data model contracts.

### E009 — 2026-10-29: B01b full local validation

- **Checks actually run:** rustfmt checks for all three crates; 35 core and 3
  backend tests; Clippy with warnings denied for core, PyO3 bridge and backend;
  extension build; 137 Python tests in default mode and 137 in Rust mode; 3
  private-D-Bus tray tests; `git diff --check`. All passed, no skips reported.
- **Runtime:** Rust bridge property paths were exercised by the Python suite in
  both modes. No end-to-end GTK runtime/preview is claimed because GTK4 typelibs
  are missing, as documented in E007.
- **PR/status:** [PR #21](https://github.com/SaahiilM/codexbar-gtk/pull/21),
  commit `6bf814b`; open when this handoff was recorded. CI/merge must be checked
  live. Build is `0.81.0 (20)`.
- **Next:** observe CI/merge, then B01c after merge.

## Append a record for each task change or handoff

```text
### E<next> — YYYY-MM-DD: <task/subtask ID and change>
- Owner/session, branch, base revision and PR URL/status observed:
- Scope and changed paths:
- Contract decisions / decision IDs (include alternatives where relevant):
- Tests/commands actually run, results, skips and environment limits:
- Native/transitional runtime route verified and how:
- Fixture UI smoke scope; durable artifact/test references:
- Failures, uncommitted work, blockers and rollback notes:
- Task status at recording (do not predict merge):
- Next exact action:
```

After a task merges, the next entry/checkpoint should record the observed merge
commit and CI result. Update the live TASKS handoff in each implementation PR;
future models must verify the linked PR's status rather than trusting a stale
`verified/PR-pending` record as either a failure or a successful merge.
