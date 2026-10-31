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

### E010 — 2026-10-29: B01b merged

- **PR/merge:** [PR #21](https://github.com/SaahiilM/codexbar-gtk/pull/21)
  merged at `70f295a02c57abc62ffa0be0922d7eb9bd3cd46a`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B01b checked in TASKS. Rust `Pace`/`CostInfo` values and their
  derived policies are available through the core and opt-in bridge. This does
  not port payload normalization or complete B01.
- **Next:** B01c shared data model contracts and derived-property integration.

### E011 — 2026-10-29: B01c shared domain models, pre-PR verification

- **Owner/branch/base:** current coding-agent session;
  `backend/b01c-data-models`, based on merged `70f295a` (PR #21).
- **Scope:** add Rust contracts for detail charts/sections/rows, credit events,
  provider usage, agent sessions and spend summaries/providers in
  `rust-core/src/domain.rs`. Route detail-chart peak, session running state and
  provider summary/usage properties through PyO3 in opt-in mode. Python remains
  the default and continues to parse the external payloads.
- **Parity correction:** Python `max(iterable, default=0)` uses the default only
  for an empty iterable; it does not clamp negative values to zero. NaN
  comparisons preserve the first item according to iteration order. The Rust
  helper explicitly follows that behavior; tests cover empty, negative and NaN
  values. Empty provider subtitle segments are omitted as in Python.
- **Focused checks:** 36 core tests, 8 domain integration tests, rustfmt and
  Clippy for core/bridge, and PyO3 extension build passed. Full suite pending at
  first recording.
- **UI smoke:** not rerun because GTK4 typelibs remain unavailable in this
  environment (E007); do not claim a UI pass.
- **Status:** implementation in progress before full-suite verification and PR.
  Planned build is `0.81.0 (21)`.
- **Next:** finish all Rust checks, create PR, observe CI/merge, then B02 provider
  usage normalization. No native UI work until BG.

### E012 — 2026-10-29: B01c full local validation

- **Checks actually run:** rustfmt checks for all three crates; 36 core and 3
  backend tests; Clippy with warnings denied for core, PyO3 bridge and backend;
  extension build; 140 Python tests in default mode and 140 in Rust mode; 3
  private-D-Bus tray tests; `git diff --check`. All passed, no skips reported.
- **Integration:** Python tests exercised the new domain helper routes with the
  Rust bridge enabled, as well as the default Python reference path.
- **UI smoke:** still not performed; the GTK4 typelib blocker from E007 remains.
- **PR/status:** [PR #22](https://github.com/SaahiilM/codexbar-gtk/pull/22),
  commit `89d8b77`; open when this handoff was recorded. CI/merge must be checked
  live. Build metadata is `0.81.0 (21)`.
- **Next:** observe CI/merge, then start B02.

### E013 — 2026-10-29: B01c merged

- **PR/merge:** [PR #22](https://github.com/SaahiilM/codexbar-gtk/pull/22)
  merged at `4213503c37b1441ba1eafd1fb04f2ce108027cef`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B01 and subtask B01c checked. Core domain contracts and selected
  derived properties are available through the opt-in bridge. Provider payload
  normalization remains a separate task (B02).
- **Next:** standard quota-window normalization (B02a).

### E014 — 2026-10-29: B02a standard quota-window normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02a-window-normalization`, based on merged `4213503` (PR #22).
- **Scope:** add `rate_window_from_value` in `rust-core/src/domain.rs`, expose a
  JSON/PyO3 adapter, and route existing `_window_from` through Rust in opt-in
  mode. Python remains the default and catches unsupported JSON/ISO/numeric
  inputs through the existing fallback. This slice is only standard
  primary/secondary/tertiary windows; extra-rate-window rules and the rest of
  provider payload normalization remain pending B02b.
- **Semantics/tests:** preserve a valid 0% as known and missing/invalid usage as
  unknown; parse UTC reset strings with Python fallback; validate numeric fields
  and Python-like truthiness for synthetic placeholders. Core tests include
  empty/missing fields and truthy JSON value kinds.
- **Test-fix evidence:** a Clippy `type_complexity` error led to a named PyO3
  tuple alias. Earlier B01c testing also caught a mismatch in Python
  `max(..., default=0)` semantics (documented E011); it was corrected and merged
  in PR #22 before this task began.
- **UI smoke:** not rerun because GTK4 typelibs remain unavailable (E007).
- **Focused checks:** 37 core tests; 3 backend tests; 9 domain integration
  tests in both default and Rust modes; format/Clippy for core and bridge; PyO3
  build passed. Full suite recorded in E015.
- **Status:** locally verified before PR; build `0.81.0 (22)`.
- **Next:** observe B02a PR/CI/merge, then B02b provider envelope normalization.

### E015 — 2026-10-29: B02a full local validation

- **Checks actually run:** rustfmt for all three crates; 37 core and 3 backend
  tests; Clippy with warnings denied for core, bridge and backend; PyO3 extension
  build; 141 Python tests in default mode and 141 in Rust mode; 3 private-D-Bus
  tray tests; `git diff --check`. All passed, no skips reported.
- **Integration:** Python tests exercised the Rust standard-window parser when
  opt-in, and the Python reference in default mode. No real provider access.
- **UI smoke:** still blocked by unavailable GTK4 typelibs; no GTK pass claimed.
- **PR/status:** [PR #23](https://github.com/SaahiilM/codexbar-gtk/pull/23),
  commit `c3a9d09`; open when this handoff was recorded. CI/merge must be checked
  live.
- **Next:** observe CI/merge, then B02b provider envelope normalization.

### E016 — 2026-10-29: B02a merged

- **PR/merge:** [PR #23](https://github.com/SaahiilM/codexbar-gtk/pull/23)
  merged at `da215b16cc89ffdd5d528c5382cdb6a450831271`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B02a checked: standard quota-window normalization is routed
  through Rust in opt-in mode. Extra windows and the rest of provider payload
  normalization remain Python under B02b.
- **GTK/UI:** still blocked locally by missing GTK4 typelib; no UI pass claimed.
- **Next:** B02b, provider pace/identity/plan/cost/details/credits/status/error
  normalization. No native UI until BG.

### E017 — 2026-10-29: GTK4/libadwaita typelibs made available locally

- **Environment:** KDE neon 24.04/Ubuntu Noble, `/usr/bin/python3` 3.12.3;
  system `libgtk-4-1` and PyGObject were present, but GTK4, Adw and Graphene
  typelibs plus libadwaita runtime were missing.
- **Action:** ran the repository's no-root `./scripts/bootstrap-deps.sh`. It
  downloaded/unpacked GTK4, Adw, libadwaita, Graphene and related typelibs into
  ignored `.deps/`; no system packages were installed and no tracked dependency
  artifacts were added. `run.sh` already prepends those local paths.
- **Verification:** with those paths, `/usr/bin/python3` imported Gtk 4.14 and
  Adw successfully. The first `GDK_BACKEND=offscreen` preview failed because
  this GTK build has no offscreen backend (and crashed after GTK criticals).
  Retried against the available X11/Wayland desktop with a synthetic fake CLI;
  `tools/preview.py` rendered card, popup, dashboard, sessions and spend PNGs.
  The popup visibly showed one synthetic Codex provider at 42% session and 12%
  weekly. No real provider/account data was requested.
- **Follow-up:** `tools/preview.py` now re-execs with local `.deps` paths before
  PyGObject import, so it works after bootstrap without manually setting
  `GI_TYPELIB_PATH`/`LD_LIBRARY_PATH`. Preview docstring now states display/Xvfb
  requirements. The GTK preview is a synthetic widget snapshot, not exhaustive
  interaction testing of the complete `run.sh` app.
- **Reproduction:** `./scripts/bootstrap-deps.sh`, then
  `HOME=$(mktemp -d) CODEXBAR_CLI=/path/to/synthetic-cli CODEXBAR_RUST_CORE=1
  /usr/bin/python3 tools/preview.py /tmp/codexbar-preview`. Use an available
  X11/Wayland display; the offscreen backend is not installed here.

### E018 — 2026-10-29: B02b1 provider pace normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02b1-pace-normalization`, based on merged `799e7f1` (PR #24).
- **Scope:** add `pace_from_value` in `rust-core/src/domain.rs`; expose a
  PyO3 JSON adapter and route `_pace_from` through Rust in opt-in mode. Invalid
  dynamic field shapes are declined by Rust and handled by the Python reference.
  This only covers pace objects; extra windows, identity/plan, costs, details,
  credits, reset credits, status and errors remain pending B02b2.
- **Checks actually run:** rustfmt for all three crates; 38 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 142 Python tests in default and Rust modes; 3 private-D-Bus tests;
  `tools/preview.py` compile; and `git diff --check`. All passed, no skips.
- **UI smoke:** synthetic fake CLI provided a single account-independent Codex
  payload (42%/12%, reserve stage); preview produced five widget PNGs, and the
  popup's session/weekly bars and “20% in reserve” chip were inspected. This is
  focused widget/runtime-path evidence, not full navigation, tray, auth, or
  real-provider coverage. Local typelibs are available under ignored `.deps/`.
- **PR/status:** [PR #25](https://github.com/SaahiilM/codexbar-gtk/pull/25),
  commit `f399d3b`; open when this handoff was recorded. CI/merge must be checked
  live. Build `0.81.0 (24)`.
- **Next:** observe CI/merge, then B02b2.

### E019 — 2026-10-29: B02b1 merged

- **PR/merge:** [PR #25](https://github.com/SaahiilM/codexbar-gtk/pull/25)
  merged at `51cd4b8b4ac0c36eb18c3b021dfd171242bbb802`; `test` and `tray-dbus`
  CI checks both succeeded. Main was fast-forwarded and clean.
- **Result:** B02b1 checked. Provider pace objects now normalize through Rust in
  opt-in mode when fields meet the typed contract; otherwise the Python
  compatibility path handles the original dynamic payload unchanged.
- **GTK:** the no-root typelib bootstrap and fixture preview tooling are merged.
  Actual local setup/preview evidence is E017/E018; this merge does not claim
  full application navigation/interaction testing.
- **Next:** B02b2, remaining extra-window/identity/cost/detail/credit/status/error
  normalization. No native UI migration until BG.

### E020 — 2026-10-29: B02b2a extra rate-window normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02b2a-extra-windows`, based on merged `f0d218a` (PR #26).
- **Scope:** add `extra_rate_window_from_value` in `rust-core/src/domain.rs`,
  expose a PyO3 JSON adapter, and route extra-rate-window entries through Rust
  in opt-in mode. Invalid field shapes fall back to the Python reference.
  This only covers extra windows; identity/plan, costs, details, credits,
  reset credits, status and errors remain pending B02b2b.
- **Semantics/tests:** preserve `key` from `id` (default `"extra"`), `title`
  from `title`/`id` (default `"Extra"`), `usage_known` from `usageKnown`
  (explicit `false` forces unknown), and all inner rate-window fields. Core
  tests include missing id/title/usageKnown, explicit false usageKnown, and
  quota metadata.
- **UI smoke:** synthetic fake CLI provided a single account-independent Claude
  payload with two extra windows (monthly unknown 0%, daily known 60%); preview
  produced five widget PNGs. Local GTK typelibs are under ignored `.deps/`.
  Focused widget/runtime-path evidence, not full navigation, tray, auth, or
  real-provider coverage.
- **Checks actually run:** rustfmt for all three crates; 38 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 143 Python tests in default mode and 143 in Rust mode; 3 private-D-Bus
  tray tests; `tools/preview.py` compile; `git diff --check`. All passed, no
  skips reported.
- **Status:** implementation locally verified before PR; build `0.81.0 (26)`.
- **Next:** create PR, observe CI/merge, then B02b2b.

### E021 — 2026-10-29: B02b2a merged

- **PR/merge:** [PR #27](https://github.com/SaahiilM/codexbar-gtk/pull/27)
  merged at `965b59223d4679e4f373621717deb70a38948f27`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B02b2a checked. Extra rate-window entries normalize through Rust
  in opt-in mode; Python fallback handles malformed/dynamic payloads.
- **GTK:** local typelib bootstrap and fixture preview verified (E017/E020).
- **Next:** B02b2b — identity/plan, costs, details/charts, credits, reset
  credits, status and error normalization. No native UI migration until BG.

### E022 — 2026-10-29: Version bump to CodexBar 0.82.0

- **Owner/branch/base:** current coding-agent session;
  `backend/upstream-0820-support`, based on merged `24e203f` (PR #28).
- **Scope:** Bump `MARKETING_VERSION` to `0.82.0` and `CURRENT_PROJECT_VERSION`
  to `28` in both `VERSION` and `codexbar_gtk/version.py`. Update CHANGELOG and
  README. Verify provider catalog against upstream `SaahiilM/CodexBar` main
  branch (110 providers, no additions or removals since 0.81.0).
- **Upstream check:** Fetched `Providers.swift`, `ProviderInstanceIDAliases.generated.swift`,
  and `ProviderManifest.swift` from upstream main. Provider enum still lists
  110 cases matching our Rust/Python catalogs exactly. No new providers,
  removals, or alias changes require catalog updates.
- **Data model:** No CLI output envelope changes detected that would affect
  `data.py` payload parsing. Extra rate-window, pace, cost, details, credits,
  and status fields remain unchanged.
- **UI fixes:** No specific upstream UI fixes identified for porting in this
  bump. The Python GTK shell remains unchanged; native UI migration is blocked
  by backend gate BG.
- **Checks actually run:** 38 core + 3 backend Rust tests; rustfmt and Clippy
  for all three crates; PyO3 extension build; 143 Python tests in default mode
  and 143 in Rust mode; 3 private-D-Bus tray tests; `git diff --check`. All
  passed, no skips reported.
- **UI smoke:** Not rerun; version bump does not affect widget layout or
  behavior. Previous synthetic X11/Wayland preview evidence (E020) remains
  valid.
- **Status:** implementation verified locally; PR not yet created.
  Build metadata is `0.82.0 (28)`.
- **Next:** create focused PR, observe CI/merge, then continue B02b2b.

### E023 — 2026-10-29: B02b2b1 provider cost normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02b2b1-cost-normalization`, based on merged `1497667` (PR #29).
- **Scope:** add `cost_from_value` in `rust-core/src/domain.rs`, expose a PyO3
  JSON adapter, and route provider cost parsing through Rust in opt-in mode.
  Invalid field shapes fall back to the Python reference. This only covers cost
  objects; detail/charts, credits, reset credits, status and errors remain
  pending B02b2b2.
- **Semantics/tests:** preserve `used`, `limit`, `currency`, `period`, `balance`,
  `personal_used`, and `resets_at`. Missing fields default to 0.0/"USD"/None.
  Non-numeric values return 0.0 via Python fallback. Core tests cover complete
  payloads, empty objects, totalCost-as-used (not recognized, matching Python),
  and non-numeric used values.
- **UI smoke:** Not rerun; cost normalization changes value derivation only,
  not widget structure. Previous synthetic X11/Wayland preview evidence
  (E020) remains valid.
- **Checks actually run:** rustfmt for all three crates; 39 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 144 Python tests in default mode and 144 in Rust mode; 3 private-D-Bus
  tray tests; `git diff --check`. All passed, no skips reported.
- **Status:** implementation locally verified before PR; build `0.82.0 (29)`.
- **Next:** create PR, observe CI/merge, then B02b2b2.

### E024 — 2026-10-29: B02b2b1 merged

- **PR/merge:** [PR #30](https://github.com/SaahiilM/codexbar-gtk/pull/30)
  merged at `e5963c6717b6730642c4ae2db0ce5b256bf7c0b4`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B02b2b1 checked. Provider cost objects normalize through Rust in
  opt-in mode; Python fallback handles malformed field shapes.
- **Next:** B02b2b2 — detail/charts, credits, reset credits, status and error
  normalization. No native UI migration until BG.

### E025 — 2026-10-29: B02b2b2a detail chart normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02b2b2a-detail-charts`, based on merged `f82d079` (PR #31).
- **Scope:** add `detail_row_from_value`, `detail_section_from_value`, and
  `detail_chart_from_value` in `rust-core/src/domain.rs`, expose PyO3 JSON
  adapters, and route detail section parsing through Rust in opt-in mode.
  Invalid field shapes fall back to the Python reference. This only covers
  detail sections; credits, reset credits, status and errors remain pending
  B02b2b2b.
- **Semantics/tests:** preserve title, rows (label, value, secondary_value,
  used_percent, severity), and chart (kind, title, unit, points). Rows limited
- **to 24 per section, chart points limited to 120 per section. Non-numeric
- chart values fall back to 0.0; non-numeric row used_percent uses Python
- fallback.
- **UI smoke:** Not rerun; detail chart normalization changes value derivation
- only, not widget structure. Previous synthetic X11/Wayland preview evidence
- (E020) remains valid.
- **Checks actually run:** rustfmt for all three crates; 41 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 145 Python tests in default mode and 145 in Rust mode; 3 private-D-Bus
  tray tests; `git diff --check`. All passed, no skips reported.
- **Status:** implementation locally verified before PR; build `0.82.0 (31)`.
- **Next:** create PR, observe CI/merge, then B02b2b2b.

### E026 — 2026-10-29: B02b2b2b provider context normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b02b2b2b-credits-status`, based on merged `96ed3d2` (PR #32).
- **Scope:** add `provider_context_from_value` and `provider_plan_from_value`
  in `rust-core/src/domain.rs`, expose PyO3 JSON adapter, and route provider
  context parsing (credits, credit events, reset credits, status, error, plan)
  through Rust in opt-in mode. Invalid field shapes fall back to the Python
  reference.
- **Semantics/tests:** preserve credits_remaining, credits_available,
  credit_events, reset_credits_available, status_level, status_description,
  error, plan. Credits/status/error read from both top level and inside
  `usage` to match Python compatibility. Core tests cover complete payloads,
  empty objects, missing fields, plan from identity/login method, and no plan
  from oauth/apiKey/cookie.
- **UI smoke:** Not rerun; context normalization changes value derivation
  only, not widget structure. Previous synthetic X11/Wayland preview evidence
  (E020) remains valid.
- **Checks actually run:** rustfmt for all three crates; 42 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 146 Python tests in default mode and 146 in Rust mode; 3 private-D-Bus
  tray tests; `git diff --check`. All passed, no skips reported.
- **Status:** implementation locally verified before PR; build `0.82.0 (32)`.
- **Next:** create PR, observe CI/merge, then B03 agent-session normalization.

### E027 — 2026-10-29: B02b2b2b merged

- **PR/merge:** [PR #33](https://github.com/SaahiilM/codexbar-gtk/pull/33)
  merged at `5aee61fd6756915d42cfb5c66b635f80594cbcbb`; `test` and `tray-dbus`
  CI checks succeeded. Main was fast-forwarded and clean.
- **Result:** B02b2b2b checked. Provider context (credits, credit events, reset
  credits, status, error, plan) normalizes through Rust in opt-in mode.
- **Next:** B03 — agent-session normalization (session fields, timestamp
  handling, running-state classification, stable sorting). No native UI
  migration until BG.

### E028 — 2026-10-29: B03 agent-session normalization

- **Owner/branch/base:** current coding-agent session;
  `backend/b03-agent-sessions`, based on merged `f619c99` (PR #34).
- **Scope:** add `agent_session_from_value` and `agent_sessions_from_value`
  in `rust-core/src/domain.rs`, expose PyO3 JSON adapters, and route session
  parsing through Rust in opt-in mode. Sessions are sorted with running
  sessions first, then by last_activity_at.
- **Semantics/tests:** preserve id, provider, state, project_name, cwd, pid,
  started_at, last_activity_at, host. Sessions are sorted with running
  sessions first, then by descending last_activity_at. Empty/malformed
  payloads are skipped.
- **UI smoke:** Not rerun; session normalization changes value derivation
  only, not widget structure. Previous synthetic X11/Wayland preview evidence
  (E020) remains valid.
- **Checks actually run:** rustfmt for all three crates; 42 core and 3 backend
  tests; Clippy with warnings denied for core/bridge/backend; PyO3 extension
  build; 147 Python tests in default mode and 147 in Rust mode; 3 private-D-Bus
  tray tests; `git diff --check`. All passed, no skips reported.
- **Status:** implementation locally verified before PR; build `0.82.0 (34)`.
- **Next:** create PR, observe CI/merge, then B04 spend normalization.

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

### E029 — 2026-10-30: B04 spend normalization/aggregation (local handoff)

- **Owner/branch/base:** current coding-agent session;
  `backend/b04-spend-aggregation`, based on `29c970c`; no PR exists yet.
- **Scope:** add Rust `spend_from_payloads` in `rust-core/src/domain.rs`, expose
  it through `rust-python/src/lib.rs`, and route `codexbar_gtk/data.py` through
  the opt-in adapter. Add Rust and Python integration coverage for totals,
  unknown versus known-zero cost, errors, coverage/provenance, daily/project/
  model ordering, and Python-reference parity. The interrupted adapter mismatch
  (Python caller unpacked the PyO3 dictionary as a tuple) was corrected.
- **Contract:** top-level totals take precedence over nested totals so the same
  provider total is not counted twice. Unknown cost stays distinct from known
  zero. Empty providers are filtered, error payloads are skipped, summary
  provenance follows Python's top-level then nested-totals precedence, and
  empty error fields do not count as failures. Coverage and session/last-30-day/
  incomplete counters follow Python's `int(value or 0)` behavior for JSON
  booleans, numbers and integer strings within the Rust `i64` contract.
- **Checks actually run:** `cargo test --manifest-path rust-core/Cargo.toml
  --locked` (49 passed); core, bridge and backend Clippy with warnings denied;
  backend tests (3 passed); format checks for core/bridge/backend;
  `./scripts/build-rust-core.sh`; B04 integration tests (23 passed with default
  and Rust opt-in); Python suite (155 passed in each mode); tray D-Bus suite
  (3 passed); `git diff --check`. No test skips reported.
- **Runtime/UI smoke:** Rust opt-in synthetic GTK preview on Wayland rendered
  `card.png`, `popup.png`, `dashboard.png`, `sessions.png`, and `spend.png` to
  `/tmp/codexbar-b04-smoke/`. The SpendView displayed the synthetic daily cost
  and project data. GTK emitted nonfatal Adwaita theme, EGL device-permission,
  and accessibility-bus warnings. No real provider/account data was used.
- **Status:** locally verified implementation prepared for a focused PR; no
  CI/merge result observed. GTK build is `0.82.0 (35)` for this PR.
- **Next:** commit and open the PR, then record its URL and observed checks here.

### E031 — 2026-10-30: B04 synthetic UI screenshots added to PR

- **PR:** [PR #36](https://github.com/SaahiilM/codexbar-gtk/pull/36).
- **Artifacts:** `docs/rust-migration/screenshots/b04-spend-synthetic.png` and
  `docs/rust-migration/screenshots/b04-dashboard-synthetic.png` are rendered
  from the GTK widget tree with the Rust opt-in and synthetic CLI payloads.
  They contain no account identifiers or live data and are embedded in the PR
  description as a reference for the SpendView and dashboard.
- **Scope/limits:** confirms the synthetic spend values flow into the GTK
  SpendView and dashboard widgets. This is a fixture render, not a full manual
  interaction pass. The Cairo snapshot renderer shows transparent surfaces on a
  black canvas in this environment; nonfatal theme/EGL/accessibility warnings
  were also observed.
- **Status:** screenshots are committed in this PR; updated checks must pass
  before merge.
- **Next:** observe the checks for the screenshot commit; merge PR #36 only when
  both required checks pass.

### E032 — 2026-10-30: B04 merged

- **PR/merge:** [PR #36](https://github.com/SaahiilM/codexbar-gtk/pull/36)
  merged at `8649c8862c4ce7514f8aae848dd624b0d641047f`.
- **Observed checks:** `test` and `tray-dbus` both passed on head `caf5d04`.
  Merge verification fetched `origin/main`; `8649c88` is its latest commit.
- **UI evidence:** synthetic GTK SpendView/dashboard screenshots are included
  in the merged PR. The preview used Rust opt-in and fixture-only CLI data.
- **Result:** B04 is verified and merged at build `0.82.0 (35)`.
- **Next:** B05 Preferences on `backend/b05-preferences`.

### E033 — 2026-10-30: B05 Preferences claimed

- **Owner/branch/base:** current coding-agent session;
  `backend/b05-preferences`, based on merged `8649c88`.
- **Scope:** port preference defaults, known-key loading/import, portable
  documents, atomic 0600 persistence, reset/update, thread safety, and refresh
  interval derivation; integrate through the opt-in PyO3 adapter.
- **Status:** active; implementation and characterization tests in progress.
- **Build:** `0.82.0 (36)` reserved for this PR.
- **Next:** add a typed Rust preference store and test it against the existing
  Python contract using temporary files, including read/write failures.

### E034 — 2026-10-30: B05 Preferences local implementation verification

- **Branch/base:** `backend/b05-preferences`, based on merged `8649c88`.
- **Scope:** add `rust-core/src/preferences.rs`, expose a PyO3
  `PreferencesStore`, and route `codexbar_gtk/prefs.py` through it when Rust
  opt-in is enabled. Add preference adapter integration tests. Python-only
  values that cannot be represented as JSON switch that instance to the Python
  reference with its current state preserved.
- **Contract:** Rust defaults parity-test against `prefs.DEFAULTS`; file loading
  applies known keys over defaults; portable import filters unknown keys but
  ignores the document version as Python does; export preserves in-memory
  unknown keys; writes use a sibling temporary file, atomic rename and 0600
  permissions; storage errors surface to callers. Refresh intervals and manual
  mode match Python.
- **Checks actually run:** 56 Rust core tests, 3 backend tests, core/bridge/
  backend Clippy with warnings denied, all crate format checks, extension build,
  159 Python tests in each backend mode, 3 tray D-Bus tests, and
  `git diff --check` all passed.
- **Runtime/UI smoke:** with `CODEXBAR_RUST_CORE=1`, constructed the Settings
  General page with an isolated settings path and fixture controller, toggled
  refresh-on-open, and confirmed the change persisted through Rust. Captured
  the presented Settings General window on the live Wayland desktop with
  Spectacle at `docs/rust-migration/screenshots/b05-settings-synthetic.png`;
  labels and controls are visible. GTK also emitted nonfatal theme/EGL/
  accessibility warnings. No account data or real CLI calls were used.
- **Status:** locally verified; no commit or PR yet; build `0.82.0 (36)`.
- **Next:** commit and open the focused B05 PR, embedding the settings screenshot
  in its description; update the handoff with the PR and observed checks.

### E030 — 2026-10-30: B04 PR opened

- **PR:** [PR #36](https://github.com/SaahiilM/codexbar-gtk/pull/36), open,
  head `c3092b44a949d22b0f218d889e90f5dc0fde5cbb`, base branch `main`.
- **Scope:** records the B04 implementation in E029; this entry only records
  the PR handoff and live GitHub state.
- **Observed checks:** at 2026-10-30 15:17 UTC, `test` was in progress and
  `tray-dbus` was queued. No review decision or merge commit was present.
- **Next:** observe CI/review on PR #36. Do not mark B04 merged until GitHub
  reports the merged commit and successful required checks.

After a task merges, the next entry/checkpoint should record the observed merge
commit and CI result. Update the live TASKS handoff in each implementation PR;
future models must verify the linked PR's status rather than trusting a stale
`verified/PR-pending` record as either a failure or a successful merge.

### E035 — 2026-10-30: B05 PR opened

- **PR:** [PR #37](https://github.com/SaahiilM/codexbar-gtk/pull/37), branch
  `backend/b05-preferences`, head `1768d52b3bd2472a59fa373f6627c0ab369282b8`,
  base `main`.
- **Scope:** B05 Preferences implementation and local verification are recorded
  in E034. The PR includes the synthetic Settings screenshot in its description.
- **Observed GitHub state:** at 15:46 UTC, `test` and `tray-dbus` were both
  running; no review decision was present. No merge is recorded here.
- **Next:** wait for both required checks; merge only after both pass, then
  record GitHub's merge commit and verify `origin/main`.

### E036 — 2026-10-30: B06 Currency service claimed

- **Owner/branch/base:** current coding-agent session;
  `orchestrated/luna-b06-currency`, based on merged B05 commit `878d4b7`.
- **Dependency handoff:** B05 PR #37 merged at
  `878d4b7b114d7584e72594f475771d66f9bf18aa`; GitHub reported `test` and
  `tray-dbus` successful on PR head `d43b18f1b6452b073a47269cb2022158a9617735`.
  This corrects the stale B05-active checkpoint present on `main` when B06
  started.
- **Prior work inspection:** read-only review of local branches
  `backend/b06-currency-service` and `backend/b06-currency-http`, plus
  `/tmp/codexbar-b06-http` and `/tmp/codexbar-ug-b06`. The former contained a
  placeholder blocking HTTP refresh; the latter had unrelated uncommitted
  TASKS edits. Both worktrees and all prior local changes were preserved.
- **Scope:** Rust currency catalog/conversion and backend refresh/cache, opt-in
  Python adapter, pace/spend caller routing through existing currency APIs,
  integration tests and synthetic GTK preview.
- **Status:** active; build `0.82.0 (37)` reserved for this PR.
- **Next:** finish local verification, update the audit, and open a focused PR.

### E037 — 2026-10-30: B06 Currency local implementation verification

- **Branch/base:** `orchestrated/luna-b06-currency`, based on merged B05
  `878d4b7`.
- **Implementation:** `rust-core/src/currency.rs` owns the ordered 29-code
  catalog, labels, USD-pivot conversion, and strict cache parsing. The
  `rust-backend` service uses reqwest with Rustls, a 15-second timeout and
  64-KiB response bound; it supports injected endpoint/time, 24-hour TTL,
  single-flight refresh, atomic cache replacement, a streamed response-size
  cap, and offline/cache retention after request or protocol failure.
  `rust-python` exposes an opt-in adapter;
  `currency.py` keeps the Python parity implementation but uses Rust for catalog,
  picker policy, conversion, cache, and asynchronous refresh when opted in.
  Existing monthly pace and spend callers route conversion through this adapter.
- **Contract shared with B14:** `CurrencyService` exposes catalog/rate/convert
  and status snapshots plus async wrappers and refresh APIs. Status records
  `fetched_at`, `RateSource::{Offline, Cache, Live}`, and refresh failure. B14
  was asked to expose those through its facade so UI does not infer cache state.
- **Checks actually run:** format checks for core/backend/bridge; 60 core tests,
  7 backend tests (including synthetic HTTP update, oversized-response bound,
  explicit-time TTL,
  single-flight, cache reload and offline fallback); bridge crate test target
  (0 tests); Clippy with warnings denied for all three crates; atomic extension
  build; default Python suite (161 passed, 2 opt-in-only tests skipped), Rust
  opt-in Python suite (161 passed, no skips), 3 private-D-Bus tray tests,
  Python preview compile, and `git diff --check`. All completed successfully.
- **GTK runtime/UI smoke:** with `CODEXBAR_RUST_CORE=1` and a temporary HOME,
  presented the real GTK `SpendView` with synthetic $42.50 totals and isolated
  EUR preferences. It displayed €39.10 total, €5.75 session, and €39.10 provider
  and project totals. The screenshot was captured from the live desktop window:
  `screenshots/b06-spend-currency-synthetic.png`. This covers the spend display
  and Rust conversion route, not full application navigation or live rates.
- **Environment limits:** GTK logged nonfatal EGL device-permission and
  accessibility-bus warnings. This environment lacks the PyGObject Cairo
  foreign converter, so custom chart drawing callbacks logged warnings and the
  chart areas were blank in the screenshot; the currency totals and tables
  rendered. No real CLI/account/provider data or network currency service was
  used in the UI smoke; HTTP tests used a local loopback fixture.
- **Status:** locally verified; PR not yet opened. Build metadata is
  `0.82.0 (37)`.
- **Next:** coordinate merge sequencing with the orchestration thread, commit
  and open a focused PR containing the screenshot, then wait for checks before
  any merge.

### E038 — 2026-10-30: B06 PR opened

- **PR:** [PR #38](https://github.com/SaahiilM/codexbar-gtk/pull/38), branch
  `orchestrated/luna-b06-currency`, initial head
  `6245c641f45681083402fe117425d034fa2358ce`, base `main`.
- **Observed at 17:20 UTC:** GitHub state `OPEN`, mergeable; `test` was
  `IN_PROGRESS` and `tray-dbus` was `QUEUED`; no reviews were present. Live
  `origin/main` remained B05 merge `878d4b7`.
- **PR contents:** includes this B06 implementation, build 37 metadata, B05
  merge/check handoff, local verification record, and synthetic SpendView
  screenshot.
- **Next:** observe both required checks on the latest PR head and merge only
  after they pass and the serialized merge slot remains available.

### E039 — 2026-10-30: B09 provider ordering and tray selection claimed

- **Owner/branch/base:** current coding-agent session, branch
  `orchestrated/luna-b09`, based on live `origin/main` at `878d4b7` (B05 PR #37).
- **Dependency state:** B01 and B02 are merged; B05 PR #37 is merged at
  `878d4b7` and its `test` and `tray-dbus` checks passed. No open PRs were
  present when B09 work began.
- **Protected checkout:** `/home/sam/Desktop/Dev/codexbar-gtk` contains
  uncommitted B09/B08/B12/B13 drafts. It was inspected read-only and left
  unchanged. B09 was selectively implemented in this isolated worktree.
- **Contract:** Rust owns provider visibility/order and Auto-lane ranking.
  `order_providers(&[ProviderUsage], &[String], &[String]) -> Vec<ProviderUsage>`
  returns owned DTOs, filters hidden IDs, applies saved positions and retains
  input order for unspecified/equal entries. `automatic_tray_selection(&[ProviderUsage],
  DateTime<Utc>) -> Option<AutomaticQuotaSelection>` returns owned provider ID,
  window key and indices into the ordered provider/window vectors. Selection
  considers non-placeholder finite nonnegative usage; full quotas rank first,
  then trusted ETA (known window duration/reset, expected use >=3%, finite
  positive ETA before reset), shortest ETA, and highest usage. Strict ties keep
  the first candidate. B10 should place this result on the backend snapshot;
  GTK renders it without duplicating policy.
- **Status:** implementation in progress; B06 reserves build 37, so B09
  reserves build `0.82.0 (38)` for its PR.
- **Next:** finish bridge parity and fixture tests, perform the synthetic GTK
  tray smoke, then run all required checks and prepare a focused PR. No PR or
  merge is claimed here.

### E040 — 2026-10-30: B09 local implementation and fixture verification

- **Scope:** `rust-core/src/ordering.rs` owns typed provider ordering and tray
  selection. `rust-python/src/lib.rs` exposes the compatibility adapter;
  `codexbar_gtk/controller.py` routes `_ordered` and `automatic_tray_selection`
  through Rust in opt-in mode with Python fallback for unsupported edge values.
  `tests/test_rust_ordering_integration.py` compares both paths. A helper DTO
  returns owned selection indices, provider ID and window key and supports
  Serde serialization.
- **Policy:** hidden provider IDs are filtered; saved order positions are
  honored; unspecified entries retain input order. Tray candidates exclude
  placeholders and invalid usage. Depleted quotas win, then trusted forecasts
  with window duration/reset, expected usage >=3%, and finite positive ETA
  before reset; shortest ETA and then highest usage rank next. Strict ties keep
  the first candidate. The B10 snapshot should include the owned result from
  the ordered provider vector; GTK only renders it. This exact API was sent to
  active B10, B14 and orchestration threads before PR creation.
- **Checks actually run:** core/bridge/backend rustfmt checks; 61 core and 3
  backend tests; Clippy with warnings denied for core, bridge and backend;
  atomic PyO3 extension build; 161 Python tests in default mode and 161 in Rust
  opt-in mode; 3 private-D-Bus tray tests; 2 focused B09 parity tests; and
  `git diff --check`. All final checks passed with no skips. The backend lock
  file was refreshed for the core's new direct Serde derive dependency and its
  locked test command then passed.
- **GTK smoke:** ran `CODEXBAR_RUST_CORE=1 python3
  tools/preview_b09_synthetic.py` with an isolated temporary HOME/config/data
  tree, synthetic Codex/Claude/Gemini providers, and a fake tray sink. The real
  `CodexBarApp._update_tray` path selected Codex by its trusted 2-hour ETA
  despite Claude's higher 70% usage; the configured panel order displayed
  Claude then Codex and filtered Gemini. The GTK panel screenshot is committed
  at `docs/rust-migration/screenshots/b09-tray-synthetic.png`. No CLI, account,
  credential, or real usage data was read. The smoke checked the app's tray
  update path through a fake sink; it did not connect to a live StatusNotifier
  host. GTK emitted nonfatal EGL/accessibility and widget teardown warnings.
- **Build/handoff:** `VERSION`, `codexbar_gtk/version.py`, README and CHANGELOG
  are synchronized at build `0.82.0 (38)` because B06 has the earlier merge
  slot/build 37. Current `origin/main` remains `878d4b7`; refresh from latest
  main and reconcile the task/audit handoff before B09 merge. No PR or merge is
  claimed yet.
- **Next:** report PR-ready status to orchestration, open the focused B09 PR,
  then wait for B06's serialized merge slot. Rebase/update from its merge before
  considering B09 merge; do not merge concurrently.

### E041 — 2026-10-30: B09 PR opened

- **PR:** [PR #39](https://github.com/SaahiilM/codexbar-gtk/pull/39), branch
  `orchestrated/luna-b09`, head `26458f8f9cb726eef33e5e82a1ca900d02c18561`,
  base `main`.
- **Scope:** B09 implementation and local evidence in E040; synthetic GTK
  screenshot is included in the PR description and in the repository.
- **Observed GitHub state:** PR is open. `tray-dbus` is running and `test` is
  queued. No review/merge decision is recorded here.
- **Merge sequencing:** B06 has the first merge slot and build 37. B09
  provisionally reserves build 38. Before merge, fetch the latest main after
  B06, reconcile TASKS/AUDIT and build metadata, rerun affected checks, and
  coordinate the next merge slot. Do not merge concurrently.
- **Next:** observe PR #39 checks/review, then wait for B06's merge before
  refreshing this branch from latest main.

### E042 — 2026-10-30: B09 checks passed; B06 merge slot remains active

- **PR #39 state:** GitHub reported both `test` and `tray-dbus` successful on
  head `f6db236ed73f8927cc9267f9addb41305555612f`. The branch remains open and
  unmerged. The observed checks are attached to that head; any later push must
  be checked separately.
- **B06 sequencing:** PR #38 is still open, with both required checks
  successful; `origin/main` remains `878d4b7`. B06 retains the first merge slot
  and build 37. B09 remains second with provisional build 38.
- **Next:** wait for the serialized B06 merge. Before B09 merge, fetch latest
  main, reconcile TASKS/AUDIT and version metadata, rerun affected checks, and
  coordinate the merge slot. No B09 merge is claimed.

### E043 — 2026-10-30: B09 integrated merged B06 main and reran local checks

- **Main update:** fetched `origin/main` at B06 merge commit
  `5e4af068254959c07e9a932c42bed0679788b146`. B06 PR #38's `test` and
  `tray-dbus` checks passed on head `75bba44231a2844f6c8b0c872ada3c16c24da895`.
- **Conflict resolution:** merged the B06 main branch into B09, preserving the
  currency core/backend/Python service, tests, preview and screenshot. Reconciled
  `CHANGELOG.md` so B09 build 38 is above B06 build 37; retained B09 build 38
  in VERSION/README/version.py; merged the task handoff so B05/B06 are checked
  and B09 remains active. Combined both audit streams with unique IDs E036–E043.
  `rust-core` and bridge module imports include both `currency` and `ordering`.
- **Checks actually run on the combined source tree:** rustfmt for core/backend/
  bridge; 65 core and 7 backend tests; Clippy with warnings denied for all three
  crates; atomic extension build; Python default suite (163 tests, 2 opt-in-only
  skips) and Rust-opt-in suite (163 tests, no skips); 3 tray D-Bus tests; version
  metadata test; `git diff --check`. All passed.
- **GTK smoke:** reran `CODEXBAR_RUST_CORE=1 python3
  tools/preview_b09_synthetic.py`. With isolated HOME and synthetic providers,
  the real app tray update selected Codex by ETA, and the panel showed Claude
  then Codex while hiding Gemini. Refreshed screenshot at
  `docs/rust-migration/screenshots/b09-tray-synthetic.png` was visually inspected.
  Nonfatal EGL/accessibility and widget teardown warnings remain; a fake tray
  sink is used, so this does not verify a live StatusNotifier host.
- **PR state:** PR #39 had head `a49d370` conflicting with main before this
  refresh. The integrated branch has not yet been pushed; no checks on the new
  head or mergeability result have been observed. B09 remains build 38.
- **Next:** commit and push the main integration, observe fresh CI and clean
  GitHub mergeability, then coordinate the merge with orchestration. Do not
  treat the previous `f6db236` checks as checks on the updated head.

### E044 — 2026-10-30: B09 merge update committed locally

- **Integration commit:** `cb867747f653d78ee6781c66ccc923ee73370460`
  merges B06 main `5e4af068254959c07e9a932c42bed0679788b146` into the B09
  branch after resolving the shared metadata/audit conflicts described in E043.
- **Build:** B06 remains build 37 and B09 remains build 38. B06's successful
  checks were on PR head `75bba44`; B09's prior passing checks were on
  `f6db236`, before the B06 integration.
- **Current status:** this integration commit has not yet been pushed, so no
  GitHub checks or mergeability result have been observed for it. B09 stays
  open and unmerged.
- **Next:** push the refreshed branch, wait for checks on its latest head, and
  merge only with clean mergeability and after coordinating the slot.

### E045 — 2026-10-30: B09 refreshed-head checks passed

- **Observed PR state:** GitHub reported `test` and `tray-dbus` successful on
  PR #39 head `ce674b9c8a74a44dff7529408117ef2f468ac100`; mergeability was
  `MERGEABLE` and merge state `CLEAN`. `origin/main` remained B06 merge
  `5e4af068254959c07e9a932c42bed0679788b146`.
- **UI evidence:** fixture GTK smoke and screenshot inspection passed on the
  same integrated source tree (E043). The fake tray sink limitation remains.
- **Status:** PR #39 remains open and unmerged. This handoff update is docs-only;
  GitHub checks must be observed on any newer PR head before merge.
- **Next:** push this audit/handoff refresh, verify the new head's checks and
  clean mergeability, coordinate with orchestration, then merge B09 build 38.

### E046 — 2026-10-30: B09 merged; B08 merge slot is active

- **Observed main update:** PR #39 merged at `93b62bbe6aafd3982f6b9f3a22023f04ddab4f83`.
  `origin/main` now points at that merge. Both required checks (`test` and
  `tray-dbus`) completed successfully on PR head
  `f71c15d15829fc7a397a9d054f70773037a4bb4a`.
- **Build sequence:** B06 is build 37 and B09 is build 38. B08 now owns the
  third merge slot and build 39. No B08 PR or merge is claimed here.
- **Next:** update the isolated B08 branch from this main, reconcile the B09
  audit/handoff and version metadata, then rerun B08 checks and GTK fixture
  smoke before opening its PR.

### E047 — 2026-10-30: B08 rebased on B09 main

- **Branch/base:** `backend/b08-notification-policy-service`, rebased on
  `origin/main` `93b62bb` after B09's verified merge. Conflicts in shared
  integration/documentation files were resolved while retaining B06 currency
  and B09 ordering code, checks, build 38 and B09 audit entries. The earlier
  B08 docs commit based on the old baseline was dropped; this handoff records
  the current state instead.
- **Contract:** `codexbar_core::notifications::NotificationPolicy::observe`
  accepts `&[ProviderUsage]`, `&NotificationPreferences`, and an injected
  `DateTime<Utc>`, then returns typed quota threshold, exhaustion, predictive
  pace and credit expiry events. Event identity retains provider/account/window
  fields where the Python reference uses them. Unknown or placeholder quota
  windows do not fabricate zero or rearm dedupe; known zero remains a recovery.
- **B10/B14 channel:** `rust_backend::event_channel()` creates a separate
  256-item bounded Tokio event queue beside the coalescing watch snapshot.
  Publishing awaits capacity, assigns sequence numbers as events enter the
  channel, and reports a sanitized closed-receiver result. B10 can publish
  typed notification outcomes without losing transitions to watch coalescing.
- **Validation:** post-rebase required checks and fixture GTK smoke are pending.
  No PR has been opened. Build metadata is being updated to build 39.
- **Next:** finish parity coverage, run migration checks and synthetic GTK
  smoke, record exact observed results, then coordinate PR readiness.

### E048 — 2026-10-30: B08 post-rebase checks and GTK smoke passed

- **Base/build:** validated on `origin/main` B09 merge `93b62bb`; B08 uses the
  third serialized slot and build `0.82.0 (39)`. `VERSION`, `version.py`,
  README and CHANGELOG agree on build 39. B06 remains build 37 and B09 build 38.
- **Code/contract:** added `codexbar_core::notifications::NotificationPolicy`
  over `ProviderUsage`, `NotificationPreferences` and an injected UTC clock.
  Typed outcomes retain provider/account/window identity. Unknown or
  placeholder quota values do not become zero or change re-arm state; a known
  zero is a real recovery. Python fallback behavior and Rust opt-in behavior
  are parity-tested. The B10/B14 channel contract remains a separate bounded
  256-event queue with backpressure, event sequences, explicit receiver-close
  errors and no GTK/Python types in backend DTOs.
- **Checks run:** `cargo fmt --check` for core, backend and bridge; locked Rust
  tests (68 core, 10 backend); Clippy with all targets/features and warnings
  denied for all three crates; atomic extension build; Python suite (171 tests,
  2 Rust-opt-in-only skips) in default mode and all 171 tests in Rust-opt-in
  mode; 3 tray D-Bus tests; Python compileall; and `git diff --check`. All final
  runs passed. The first Python run caught blank-account `""` versus `None`
  presentation mismatch; normalization was corrected and both suites passed on
  rerun.
- **GTK smoke/artifact:** `CODEXBAR_RUST_CORE=1 python3
  tools/preview_notifications.py
  docs/rust-migration/screenshots/b08-notifications-synthetic.png` passed and
  rendered all four synthetic outcomes through
  `CodexBarApp._check_notifications`. Delivery was captured at the frontend
  `_notify` boundary. The refreshed screenshot was visually inspected. The
  fixture uses `fixture@example.invalid` only and no real CLI or credentials.
  Nonfatal EGL render-device permission and accessibility-bus warnings appeared.
- **Status:** implementation and local verification are ready for a focused PR;
  no PR or merge is claimed. B08 remains unchecked until merge. Orchestration
  must confirm PR/merge sequencing before the PR is opened; merge only after
  fresh CI and UI verification pass.
- **Next:** report the ready branch and settled DTO/channel contract to
  orchestration, then open/link the screenshot-bearing PR after coordination.

### E049 — 2026-10-30: B08 PR #40 merged and verified

- **Observed merge:** PR #40 merged at
  `9d272fd810912133d0e42f35238dee1fc5e12a30`, now `origin/main`; PR head was
  `1d0f396ca8d559af2ef0d0ad6e6ad9f70874ac9e`. GitHub Actions run `41102664352`
  reports both required jobs, `test` and `tray-dbus`, `SUCCESS` on that head.
- **Owner's local workflow at the exact PR head:** 68 Rust core tests and 10
  Rust backend tests passed; rustfmt and Clippy checks passed for all three
  crates; the Rust extension build passed; Python passed 171 tests in each
  mode, with the 2 expected opt-in-only skips in default mode; 3 D-Bus tray
  tests passed; and the synthetic GTK smoke passed. The GTK screenshot is
  embedded in PR #40. No CI bypass was used.
- **Build sequence:** B06 is build 37, B09 build 38, B08 build 39. B12 owns the
  next slot at build 40, subject to current metadata verification.
- **Next:** B12 fetches this main, reconciles shared Rust and handoff files, and
  reruns its full checks and synthetic GTK smoke on the integrated tree.

### E050 — 2026-10-30: B12 rebased onto B08 main; build 40 assigned

- **Base/build:** refreshed `origin/main` to B08 merge
  `9d272fd810912133d0e42f35238dee1fc5e12a30`; retained B12 as build
  `0.82.0 (40)` after B08's build 39. `VERSION`, Python version metadata,
  README and CHANGELOG now agree on build 40.
- **Conflict reconciliation:** retained B08's notification policies, bounded
  backend event channel, Python notification adapter, and successful metadata;
  restored B12's `updates` backend module and PyO3 entry point. Tokio feature
  sets and direct service dependencies are combined. Lockfiles preserve B08's
  direct `serde_json` dependency alongside `reqwest` and Tokio.
- **B12 contract:** a typed read-only request/result service with bounded HTTP
  response and timeout, injectable fixture URL/fetch seam, and stable sanitized
  errors. Unicode decimal version digits preserve Python behavior, including
  Arabic-Indic/fullwidth numeric comparison; superscript digits pass Python
  `isdigit()` but fail `int()` and return a sanitized invalid-marker error.
  The Python reference parser is unchanged.
- **Status at integration:** no B12 PR existed; integrated checks were pending
  and are recorded in E051.
- **Next:** report verified readiness to orchestration, then open the focused
  screenshot-bearing PR.

### E051 — 2026-10-30: B12 integrated verification on build 40

- **Source/base:** B12 commit `1968d1f` is based on B08 merge
  `9d272fd810912133d0e42f35238dee1fc5e12a30`. `VERSION`,
  `codexbar_gtk/version.py`, README and CHANGELOG agree on `0.82.0 (40)`.
- **Rust checks:** rustfmt checks passed for core, Python bridge and backend;
  locked tests passed with 68 core and 14 backend tests; Clippy with all targets
  and features and `-D warnings` passed for all three crates; the atomic Rust
  extension build passed.
- **Python and D-Bus checks:** default Python suite passed 174 tests with 2
  expected Rust-opt-in-only skips; Rust-opt-in suite passed all 174 tests; all
  3 tray D-Bus tests passed. `git diff --check` passed.
- **GTK runtime smoke:** with Rust opt-in and an isolated temporary HOME, a
  loopback-only HTTP fixture served `0.83.0 (1)`. The Rust update service
  compared it with current `0.82.0 (40)`, and the typed available result passed
  through `CodexBarApp._finish_update_check` into an actual Adw message dialog.
  The heading was asserted and the refreshed screenshot
  `docs/rust-migration/screenshots/b12-update-synthetic.png` was visually
  inspected. Nonfatal EGL render-device permission, missing accessibility-bus,
  and no-transient-parent GTK warnings appeared. No external network, account,
  provider data, or credentials were used.
- **Status:** B12 implementation and local verification are ready for PR; no
  PR or GitHub CI result is claimed. The existing B08 checks belong to B08's
  exact head only. Root checkout's uncommitted drafts remain untouched.
- **Next:** notify orchestration before opening the screenshot-bearing PR, then
  verify fresh PR head, reviews, mergeability, required checks and current main
  before any merge. If GitHub Actions remains degraded, rely only on equivalent
  passing local checks and GitHub's normal merge permission; do not bypass or
  describe pending GitHub checks as passed.

### E052 — 2026-10-30: B12 PR #41 opened; initial GitHub checks in progress

- **PR/head/base:** [PR #41](https://github.com/SaahiilM/codexbar-gtk/pull/41),
  `orchestrated/luna-b12`, head
  `95f8a994d83f66a88907e1dd3f156279a4022e5a`, base `main` at
  `9d272fd810912133d0e42f35238dee1fc5e12a30`. The description embeds the
  synthetic GTK screenshot through an immutable raw URL.
- **Observed at 18:14 UTC:** PR state `OPEN`, mergeability `MERGEABLE`, merge
  state `UNSTABLE`, and no reviews. Run `41105073196` showed both `test` and
  `tray-dbus` `IN_PROGRESS`; `gh pr checks` reported both pending. At this point
  `origin/main` remained the B08 merge `9d272fd`.
- **Service status:** GitHub Status still showed the Actions/Pages/Webhooks
  incident as investigating, with Actions and Webhooks degraded. This is not a
  B12 test result. Required GitHub checks remain intact; no bypass was used.
- **Next:** observe checks on the exact current PR head. If the incident delays
  them, local passing workflow-equivalent results are recorded in E051; merge
  only if GitHub permits the ordinary PR merge and current head, reviews,
  mergeability and `main` have been reverified.

### E053 — 2026-10-30: B12 PR #41 merged

- **Observed merge:** PR #41 merged at
  `bd58f46b8a5cae1518aa723968484c91068f3c36`; its required `test` and
  `tray-dbus` jobs both succeeded on PR head `21537ba`. This supersedes the
  initial open/pending state in E052.
- **Next:** B07 is the active slot after B12; verify current build metadata and
  integrate the ready B07 commit on latest main before opening its PR.

### E054 — 2026-10-30: B07 integrated onto B12 main; build 41

- **Owner/branch:** current coding-agent session,
  `backend/b07-cli-service-rust`. The B07 implementation commit is
  `15057ab` after rebasing the original `216fad2` change onto current main;
  the previously existing `backend/b07-cli-service` branch remains untouched.
- **Base/dependency:** latest fetched `origin/main` is B12 merge
  `bd58f46`. B00 and B12 are merged; B06, B08 and B09 are also present.
- **Build:** latest main is build 40. B07 owns build 41, reflected in
  `VERSION`, `codexbar_gtk/version.py`, README and CHANGELOG.
- **Rebase reconciliation:** keep B08's currency and notification services and
  B12's read-only update service and bridge APIs. Combine Tokio features and
  dependencies in backend/bridge manifests and lockfiles. Register the B07 CLI
  PyO3 adapter alongside the B08/B12 classes/functions. Preserve B07's async
  CLI service, opt-in Python routing, screenshot, and synthetic tests.
- **Contract:** B07 provides normalized `PathBuf` executable discovery and
  argv-safe non-PTY command methods; B11 owns PTY sessions and B10 owns
  controller scheduling, fallback and retention. The service accepts timeouts
  and B00 cancellation and maps sanitized CLI errors to B00 backend errors.
- **Status:** build-41 implementation and local verification are recorded in
  E055. No B07 PR or merge is claimed here.
- **Next:** send final readiness and contract status to orchestration, then
  open/link the screenshot-bearing PR and verify its exact head and GitHub state.

### E055 — 2026-10-30: B07 build-41 workflow and GTK fixture verification

- **Integrated revision/base:** `15057ab` on latest `origin/main`
  `bd58f46`; `VERSION`, `codexbar_gtk/version.py`, README and CHANGELOG agree
  on build `0.82.0 (41)`.
- **Workflow-equivalent checks:** rustfmt passed for core, bridge and backend;
  locked Rust tests passed with 68 core and 22 backend tests; the atomic
  `scripts/build-rust-core.sh` extension build passed; default Python tests
  passed (177, 2 expected Rust-opt-in skips); Rust-opt-in tests passed (177);
  Clippy with all targets/features and warnings denied passed for all three
  crates; and `git diff --check` passed. Private-D-Bus tray tests passed in
  both modes (3 each). No required local check was skipped.
- **GTK runtime/UI smoke:** launched the build-41 Rust-opt-in application on
  Usage & Spend with a temporary HOME/config/data/cache, private D-Bus session
  and synthetic fixture CLI. The live GTK window displayed `$4.25` total spend
  and `9.0K` tokens. Visually inspected the screenshot at
  `screenshots/b07-cli-spend-synthetic.png`; no real CLI, provider account or
  credential was used. GTK emitted nonfatal EGL render-device and portal
  document-mount warnings; the environment lacks the PyGObject Cairo converter,
  so chart drawing callbacks warned and the activity chart was blank while the
  spend summary rendered.
- **B10/B11 contract:** no API change after rebase. Discovery remains
  `discover_executable(name, override_env, package_dir) -> Result<PathBuf,
  CliError>`. `CliService` owns the resolved executable and optional timezone;
  async `usage`, `cost`, `sessions` and `version` methods accept `Duration` and
  optional B00 `Cancellation`. B11 may use `run_json` for bounded non-PTY auth
  status, but owns PTY login and presentation helpers; B10 owns controller
  scheduling, fallback and retained data. CLI errors expose only typed kind
  and static operation ID.
- **Status:** workflow-equivalent local checks and fixture GTK smoke passed;
  PR has not yet been opened and GitHub checks/reviews/mergeability have not
  been observed. No merge is claimed.
- **Next:** notify orchestration and B11 of final readiness/API, then open/link
  the focused screenshot-bearing PR and verify its current head and state.

### E056 — 2026-10-30: B07 PR #42 merge verified

- **Observed dependency merge:** PR #42 merged normally at
  `e9dda264335bd196cd70409df8d4b7f4992b8382`. Both required checks (`test` and
  `tray-dbus`) succeeded on its exact head `7b1ded15d7e85eba999e67e6f4a316b83ee297e2`.
  A fresh `git fetch origin main` confirms that `origin/main` is the merge
  commit. Build 41 is the current base; B11 owns the next slot, build 42.
- **Next:** integrate the B07 executable discovery path while keeping PTY
  session creation and lifecycle in B11.

### E057 — 2026-10-30: B11 integrated on B07 main; build 42

- **Base/build:** rebased B11 onto B07 merge `e9dda264335bd196cd70409df8d4b7f4992b8382`.
  Updated `VERSION`, `codexbar_gtk/version.py`, README and CHANGELOG to
  `0.82.0 (42)`.
- **B11 service and bridge:** `rust-backend/src/login.rs` owns PTY launch,
  process-group termination, timeout/cancel, wait/reap, incremental ANSI/URL/
  prompt parsing, submit input, bounded `LoginEvent` receiver and explicit
  completion. Its `LoginSnapshot` watch exposes only lifecycle status and
  `needs_code`; safe error values contain only typed categories. Python's
  Rust-opt-in login adapter discovers `claude` through B07 and passes the
  returned path directly to the PTY service. Terminal/browser argv helpers use
  the Rust functions, and the GTK dialog polls for the transient URL/prompt.
- **Auth-status boundary:** the auth-status helper uses B07
  `CliService::run` for `auth status`, checks for exit code zero before parsing,
  accepts only a JSON object, and returns `{}` on discovery/process/timeout/
  cancellation/invalid JSON/non-object failures. It does not use `run_json` for
  this compatibility fallback. This corrects the proposed `run_json` wording
  in E055; interactive login never uses the non-PTY runner.
- **B14 contract:** the bounded login `LoginEvent` receiver and safe
  `LoginSnapshot` watch stay separate from B00's notification `event_channel`
  and B10's refresh snapshot. B14 may expose B11 async start/submit/cancel
  through its central facade while retaining the independent login event
  stream. No B10 facade or notification API change is needed.
- **Sensitive data handling:** authorization URLs and captured output exist
  only in transient login events and the compatibility UI adapter; they are
  excluded from watch snapshots, error strings and logs. Test process output is
  synthetic and stays confined to sanitized fixtures and uncommitted test
  execution; no output values are copied into the audit trail.

### E058 — 2026-10-30: B11 build-42 workflow and GTK fixture verification

- **Rust checks:** rustfmt checks passed for core/backend/bridge; locked offline
  Rust tests passed with 68 core, 32 backend and 0 bridge unit tests; Clippy
  with all targets/features and `-D warnings` passed for all three crates; the
  atomic `scripts/build-rust-core.sh` extension build passed.
- **Python and D-Bus checks:** default Python suite passed all 182 tests with
  7 expected Rust-opt-in-only skips; Rust-opt-in suite passed all 182 tests,
  including auth-status fallback, PTY URL/prompt/completion, cancel-before-
  worker-start and argv helpers. The private-D-Bus tray suite passed all 3
  tests in each mode. `git diff --check` passed.
- **GTK runtime/UI smoke:** Rust-opt-in GTK login dialog launched with a
  temporary HOME/config/data/cache and private D-Bus session; the PTY fixture
  flow accepted test input and completed successfully. The screenshot was
  captured in a separate neutral pre-launch dialog state before starting any
  login process. `docs/rust-migration/screenshots/b11-login-neutral.png` was
  visually inspected and contains no auth output, URL or code. EGL DRI3 and
  portal document-mount permission warnings were nonfatal. The first attempt
  used a temporary HOME directory that had not been created and returned a
  safe generic process error; after creating the isolated directories, the
  full flow passed.
- **Status:** build-42 implementation, local checks and fixture UI verification
  are ready for a focused PR. Before PR creation the open-PR query returned
  empty, and a fresh fetch confirmed `origin/main` at B07 merge `e9dda26`.
  No B11 PR, GitHub check or merge is claimed here.
- **Next:** send this verified status to orchestration, open/link the focused
  screenshot-bearing PR, then verify the exact head, reviews, required checks,
  mergeability and current main before the serialized B11 merge.

### E059 — 2026-10-30: B11 screenshot scope sanitized before PR

- **Screenshot replacement:** the first unpublished screenshot draft showed
  the fixture login field after PTY output. It was removed before PR creation.
  The committed replacement, `docs/rust-migration/screenshots/b11-login-neutral.png`,
  was captured from the GTK login dialog before starting a login process. Visual
  inspection confirms it contains no auth output, authorization URL or code.
- **Rerun:** after simplifying the sanitized URL fixture, the Rust backend suite
  passed all 32 tests, the focused Rust-opt-in login integration suite passed
  all 5 tests, and backend rustfmt check passed. A private-D-Bus GTK run of the
  fixture login completed successfully without capturing its transient output;
  a separate neutral pre-launch dialog run produced the replacement screenshot.
- **Scope:** no fixture URL, submitted code or CLI output is recorded in this
  audit or screenshot. The full build-42 verification remains as recorded in
  E058; the focused rerun confirms the sanitized test fixtures and final UI
  evidence before PR creation.

### E060 — 2026-10-30: B11 PR #43 opened; checks not reported yet

- **PR/head/base:** [PR #43](https://github.com/SaahiilM/codexbar-gtk/pull/43),
  branch `orchestrated/luna-b11`, head
  `34b70b9373728209c081c7d4eda716ddcef0fd2a`, base `main` at B07 merge
  `e9dda264335bd196cd70409df8d4b7f4992b8382`.
- **Observed state:** GitHub reports the PR `OPEN` and `MERGEABLE`. At the first
  query, the review list was empty, `reviewDecision` was unset,
  `statusCheckRollup` was empty, and `gh pr checks` reported no checks on the
  branch. This is not a passing CI result; no merge is claimed.
- **Screenshot/description:** the PR description links only the neutral
  pre-launch screenshot from E059; the body contains no auth output, URL or
  code. The PR was linked to the B11 task thread.
- **Next:** watch PR #43 for required checks and reviews, verify the exact head
  and current main again, then merge normally only after checks pass and UI
  verification remains valid. B10 retains the following build/merge slot 43.

### E061 — 2026-10-30: B11 PR #43 merged with Actions startup failure recorded

- **Observed merge:** PR #43 merged at
  `a33f0977dbd916e939a97ba8f157f151a51ffa47` from exact head
  `8f998ff3a38a9682b4177b1ce3f672af376e2d9a`; the merge commit is the fetched
  `origin/main`. Build 42 is now main; B10 owns build 43.
- **GitHub run status:** merge-SHA Actions run
  [#41111847909](https://github.com/SaahiilM/codexbar-gtk/actions/runs/41111847909)
  completed with conclusion `startup_failure` and zero jobs. PR #43's
  `statusCheckRollup` is empty. This is not a CI pass. The exact-head local
  workflow-equivalent checks and neutral GTK login smoke passed as recorded in
  E058–E059; no branch protection or check settings were changed.
- **Next:** B10 is the active implementation slot. Fetch and rebase on
  `a33f0977`, reconcile build 43 and migration records, then run the B10 exact
  head checks and fixture GTK smoke.

### E062 — 2026-10-30: B10 rebased onto B11 main and verified on build 43

- **Integrated base/head:** fetched `origin/main` is B11 merge
  `a33f0977dbd916e939a97ba8f157f151a51ffa47`, build 42. B10 commit
  `ee3f9c3c156acf043e0362d275c4864220df7e83` is rebased directly on that
  base. `VERSION`, `codexbar_gtk/version.py`, README and CHANGELOG agree on
  build `0.82.0 (43)`. The PyO3 bridge retains B11's independent
  `LoginSession` adapter and registers B10 `RefreshController` alongside it.
- **B10 boundary and behavior:** the B14-approved
  `RefreshControllerHandle` exposes immediate `start`/`start_async`, immutable
  `BackendState<ControllerSnapshot>` watch, explicit force command/sender with
  one queued follow-up per active pass, the bounded B08 notification receiver,
  and joined async shutdown. Snapshot DTOs include revision, CLI version,
  update/error context, ordered providers, spend, sessions, history and B09
  tray selection; no login events/fields or GTK/Python types. The controller
  dynamically reads polling preferences, keeps explicit refresh in manual mode,
  retains sessions on scan failure, falls back from `both` to codex/claude cost
  sources, preserves usable prior/fresh spend, and appends one history sample
  per provider window after each successful usage scan.
- **B02 envelope gap/parity:** `provider_usage_from_value` composes the complete
  top-level CLI usage envelope using the merged B02 parsers. The shared
  synthetic fixture is normalized in Rust and compared with the Python
  `provider_usage_from_payload` result and reconstructed Python DTO. Unknown or
  partial quota data stays distinct from known zero. Python remains the parity
  reference; Rust remains opt-in.
- **Workflow-equivalent checks on the rebased candidate:** `cargo fmt --check`
  passed for core, backend and bridge; locked Rust tests passed (70 core, 37
  backend); strict Clippy passed for all three crates; the atomic extension
  build passed; default Python tests passed (183, with eight expected
  Rust-opt-in skips); Rust-opt-in Python tests passed (183); private-D-Bus tray
  tests passed in both modes (3 each); `py_compile` and `git diff --check`
  passed. No real provider account or credentials were used.
- **Fixture-only GTK smoke:** after rebase and extension rebuild,
  `python3 tools/preview_b10_controller.py` launched the Rust controller with
  synthetic CLI data, temporary HOME/config/data/cache and private D-Bus. The
  screenshot `screenshots/b10-controller-synthetic.png` was regenerated and
  visually inspected: Codex shows 64% and the unknown weekly quota shows
  “Unavailable”. The fixture flow also checked typed events, refresh state and
  joined shutdown. Nonfatal EGL device, AT-SPI, missing cairo.Context converter
  and Gtk progress-bar teardown warnings occurred; the script exited 0.
- **GitHub status distinction:** B11's merge-SHA run and PR status are recorded
  in E061 as `startup_failure`/zero jobs and empty rollup. B11's local workflow
  and neutral GTK evidence is in E058–E059. B10 has not yet been pushed or
  opened as a PR; no B10 GitHub checks or merge are claimed.
- **Next:** send the exact build-43/head status to orchestration, push the
  rebased branch and open the focused B10 PR with the synthetic screenshot.

### E063 — 2026-10-30: B10 PR #44 opened on build 43

- **PR/head/base:** [PR #44](https://github.com/SaahiilM/codexbar-gtk/pull/44),
  branch `backend/b10-refresh-controller`, initial head
  `0d39ab54d73335b9966dbf0d9849862d5d269a13`, base `main` at B11 merge
  `a33f0977dbd916e939a97ba8f157f151a51ffa47`. The description includes an
  immutable raw link to the synthetic B10 GTK screenshot and records the local
  workflow-equivalent checks.
- **Observed initial state:** GitHub reports `OPEN` and `MERGEABLE`, no reviews,
  and merge state `UNSTABLE`. Run `41112738953` reported `tray-dbus` SUCCESS
  while `test` was IN_PROGRESS; `gh pr checks` reported the same. These are the
  initial check results only; verify the current PR head and statuses before
  merge.
- **CI accuracy:** B11's merge-SHA run #41111847909 remains a separate
  zero-job `startup_failure`, recorded in E061. B11's local check/UI evidence
  and B10's exact-head local verification are not represented as GitHub CI
  success. No protection or required-check setting was changed.
- **Next:** refresh PR #44's head, reviews, mergeability and check rollup; wait
  for the exact-head required checks, then merge only through GitHub's ordinary
  merge path if it permits. If Actions fails to start, use the recorded local
  workflow and GTK evidence only if GitHub permits the ordinary merge.

### E064 — 2026-10-30: B10 merged and build-44 follow-up assigned

- **Observed main update:** a fresh fetch places `origin/main` at B10 merge
  `a66e6771ff77d782dabe16a3f61d40b20702dd27`. PR #44 merged at 19:11:40 UTC
  from head `b85348d4a38220a0b3e77e53d0f965f23cf943b5`; `test` and `tray-dbus`
  both report SUCCESS on run `41112871969`. PR #40's earlier Actions queue
  delay also resolved: both required jobs report SUCCESS on run `41102664352`
  before its merge at `9d272fd`.
- **Merge slot:** B10 is build 43. Orchestration assigned the next slot, build
  44, to the focused B09 eligibility correction ahead of B13a's provisional
  build 45. No open PR existed when this follow-up started.
- **Next:** implement B09a from the B10 merge, preserve the ordered snapshot
  vector and append new audit evidence; no B13/B14 integration or UI migration
  is part of this correction.

### E065 — 2026-10-30: B09a tray eligibility correction claimed

- **Owner/base/branch:** current coding-agent session; fresh branch
  `backend/b09-tray-unknown-state` based on `origin/main` at `a66e677`.
  Build `0.82.0 (44)` is provisionally assigned; PR not yet opened.
- **Reproduced Python legacy behavior:** with synthetic DTOs, the old Python
  selector chose a window whose stored `used_percent` was `0.0` and
  `usage_known` was false, and selected an errored provider's 100% window when
  called directly. The normal GTK tray caller already filters errored
  providers. Unknown-as-zero is documented as a legacy bug; Python parity will
  intentionally exclude unknown windows while retaining known zero.
- **Agreed B09/B10/B13/B14 contract:** candidate eligibility excludes providers
  with a non-empty error, placeholder windows, and `usage_known == false`, then
  keeps all existing finite/nonnegative checks and ranking/tie policy. Known
  zero remains eligible; no eligible candidate yields `None` and the tray
  projection says unavailable. Selection indices refer to the full ordered
  provider slice and each original provider's windows vector; explicit
  candidate-to-source coordinates preserve those indices. Provider ID and
  window key identify the same original positions. B10 keeps its snapshot
  vector unchanged; B13 consumes and validates this selection without
  compaction or duplicated policy. B10, B13 and B14 confirmed no API conflict.
- **Initial code/tests:** the Rust core now skips errored providers, placeholders
  and unknown windows before ranking, with coordinates retained separately.
  The private PyO3 candidate adapter returns the selected index into the
  original flattened Python candidate list. Python selection filters the same
  data; when selection is empty the tray now displays unavailable instead of
  choosing a max-usage fallback. Focused checks passed: four Rust ordering
  tests and eight Python `TraySelectionTests`. Full checks and GTK runtime
  smoke remain pending.
- **Next:** complete Rust/Python bridge parity cases for errored providers,
  unknown windows, known zero, and source indices; update build-44 release and
  handoff records; run required checks and synthetic GTK smoke; then open a
  focused PR with the safe screenshot. Merge only after required CI, UI/head,
  and clean mergeability are verified and orchestration confirms the slot.

### E066 — 2026-10-30: B09a build-44 correction verified locally

- **Source/base/build:** branch `backend/b09-tray-unknown-state` remains based
  on B10 main merge `a66e677`; `VERSION`, `codexbar_gtk/version.py`, README and
  CHANGELOG agree on `0.82.0 (44)`. The public selection signature and DTO
  remain unchanged.
- **Eligibility and index correction:** `rust-core/src/ordering.rs` now skips
  errored providers, placeholder windows and unknown windows before ranking;
  finite/nonnegative checks and existing depletion/ETA/usage ranking remain in
  `automatic_selection`. The candidate-to-source coordinate vector keeps
  `provider_index` and `window_index` anchored to the exact input provider and
  window vectors. Rust tests place an error provider first and an unknown
  window before a known-zero window, then assert the returned original indexes,
  ID and key. Empty/fully ineligible candidates return `None`.
- **Python parity and projection:** `codexbar_gtk/controller.py` retains the
  Python fallback but intentionally stops treating stored `0.0` as evidence of
  known usage; known zero remains eligible. The PyO3 candidate adapter carries
  an eligibility mask and maps its ranked compact candidate back to the
  original flattened Python candidate index. `CodexBarApp._update_tray` still
  filters provider errors and now shows the existing unavailable tooltip when
  automatic selection is empty rather than falling back to max usage and
  displaying fabricated zero.
- **Checks actually run:** Cargo format checks passed for `rust-core`,
  `rust-python` and `rust-backend`; `./scripts/build-rust-core.sh` passed.
  Locked tests passed with 72 core
  and 37 backend tests. Clippy with all targets/features and `-D warnings`
  passed for core, bridge and backend. Python default and Rust-opt-in full suites
  passed 186 tests each; default mode reported eight expected opt-in-only skips,
  and Rust-opt-in reported none. The tray D-Bus suite passed three tests in
  both modes. The focused ordering integration tests passed all three cases,
  exercising both Python fallback and Rust-extension policy. Version metadata,
  Python compilation for touched code, and `git diff --check` passed.
- **Fixture-only GTK smoke:** `CODEXBAR_RUST_CORE=1 python3
  tools/preview_b09_synthetic.py` used temporary HOME/config/data/cache paths,
  synthetic provider DTOs and a fake tray sink. It called the actual
  `CodexBarApp._update_tray`, verified the trusted-ETA Codex choice and
  unknown-only unavailable tooltip with no `0%`, and rendered
  `screenshots/b09-tray-unknown-unavailable.png`; the known-provider panel
  screenshot `screenshots/b09-tray-synthetic.png` was refreshed too. Both were
  visually inspected. The smoke does not connect to a live StatusNotifier host
  or use real provider/account data. EGL access, accessibility-bus, missing
  Cairo foreign-converter, and widget teardown warnings were nonfatal; the
  smoke exited 0.
- **Status/next:** B10, B13 and B14 confirmed the full-vector index contract
  and eligibility policy; there is no contract or dependency blocker. This
  local correction is verified and PR-pending. Send the exact verification to
  orchestration, then open a focused screenshot-bearing PR. Do not merge until
  required checks pass on the PR head, UI/head are verified, mergeability is
  clean, and the serialized build-44 slot is confirmed.

### E067 — 2026-10-30: B09a merged; B13a rebased and resumed

- **Observed dependency merge:** fetched `origin/main` at B09a PR #45 merge
  `d1eff67725cfbde82c49f0eb75861d4dbbd4d797`. GitHub reports PR #45 `MERGED`
  from exact head `f19036e0182bdfce553c9e46972e0bc6587973b5`; required `test`
  and `tray-dbus` checks both concluded `SUCCESS` on run `41116159428` for that
  head. PR #45 was clean/mergeable before merge. The reported fixture GTK smoke
  and synthetic screenshots are present on the merged PR (see E066 for local
  smoke details). B11 PR #43's `startup_failure`/zero-job run remains recorded
  in E061 and is not described as a CI success.
- **Selection contract now in main:** automatic selection excludes errored
  providers, placeholders and windows whose usage is unknown; known-zero
  windows remain eligible, existing ranking/ties for eligible inputs remain,
  and no eligible candidate returns `None`. Selection indexes address the
  complete ordered provider vector and each provider's original windows vector.
  B13a resolves those positions against the unchanged B10 snapshot, validates
  `provider_id`/`window_key`, and never compacts or reindexes before use. No
  unknown-as-zero fallback is allowed.
- **B14 API coordination:** B14 confirmed no naming or boundary conflict.
  The backend-neutral Rust API is typed
  `rust_backend::presentation::{SpendViewModel, TraySummary}` with
  `spend_view_model(...)` and `tray_summary(...)`; PyO3 `*_json` methods are
  serialization adapters only. Production adapters read B10 watch state and
  the shared `CurrencyService`/`PreferencesStore`. Projection and serialization
  run off the GTK main thread; Python keeps GTK drawing/layout, native dialogs
  and file selection, GLib marshalling, and OS notification delivery.
- **Spend contract:** keep absent spend distinct from present empty spend and
  keep `cost_error`/notice separate from a retained usable summary. Amounts,
  tokens and counts are structured values with independent known/partial,
  coverage and provenance fields. Unknown remains `None`; total is meaningful
  only when known and partial/error subtotal labels use the known subtotal.
  Coverage retains priced/unpriced counts and the existing provenance fallback.
  Daily chart points preserve date plus `Option<amount>` for 7/30/90/All
  (default 30), pass history coverage, and remain separate from the full-range
  heatmap. Provider/project/model ordering and limits remain stable (12 project
  and model rows); grouping uses `modelName` then `name`, missing row costs stay
  missing, and source currency remains explicit. Preferred-currency conversion
  uses the shared cached/offline-capable service and falls back to source
  currency if the target or rate is unavailable.
- **B13a status/build:** B09a completes build 44; B13a uses build `0.82.0 (45)`
  on `backend/b13a-spend-tray-projections`. The implementation commit has been
  rebased onto B09a main at `d1eff677`; B13a is limited to spend/tray typed
  projections and opt-in caller routing. B13 parent remains unchecked and
  B13b settings/actions remain outstanding.
- **Checks:** after rebase, `cargo fmt --check` passed for core/backend/bridge;
  locked Cargo tests passed (72 core, 45 backend); strict all-target/all-feature
  Clippy passed for all three crates; `scripts/build-rust-core.sh` passed.
  Default Python discovery passed 187 tests with 9 expected opt-in skips;
  Rust-opt-in discovery passed all 187. The private tray D-Bus suite passed 3
  tests in each mode. Touched Python files and the GTK smoke script compiled,
  and `git diff --check` passed. An initial Clippy run caught one simplifiable
  `map_or`; it was changed to `is_none_or` and the strict Clippy suite then
  passed.
- **Fixture-only GTK smoke:** `CODEXBAR_RUST_CORE=1 python3
  tools/gtk_smoke_b13_spend_tray.py` ran with isolated HOME/config/data/cache,
  a fake CLI, synthetic provider/spend data and a fake tray sink. The actual
  Rust controller facade returned spend/tray projections to the GTK main
  context; the SpendView rendered the selected 7-day range, known partial
  subtotal, coverage and unknown-cost project/model rows. Tray assertions
  verified automatic selection of the known primary window and displayed the
  unknown weekly window as unavailable, never 0%. The screenshot
  `screenshots/b13-spend-tray-synthetic.png` was visually inspected. No live
  StatusNotifier host or real account was used. EGL device, AT-SPI bus and
  Cairo foreign-converter warnings were nonfatal; smoke exited 0 and controller
  shutdown joined.
- **Readiness:** no B13a dependency or B14 contract blockers remain. Before
  opening PR, send the exact candidate/check/screenshot status to orchestration.
  Do not merge until PR-head checks, UI evidence and mergeability are verified
  and orchestration serializes the next merge slot. B13 parent remains pending;
  B14 remains gated until all B13 slices, including B13b, are verified/merged.

### E068 — 2026-10-30: B13a PR #46 opened

- **PR/head/base:** [PR #46](https://github.com/SaahiilM/codexbar-gtk/pull/46)
  is open from `backend/b13a-spend-tray-projections` at initial head
  `e315255b8f33f9933118058a055593708243de8e`, based on `main` at B09a merge
  `d1eff67725cfbde82c49f0eb75861d4dbbd4d797`. The PR includes the synthetic
  GTK screenshot `screenshots/b13-spend-tray-synthetic.png` and local evidence
  from E067.
- **Observed initial GitHub state:** `OPEN`, `MERGEABLE`, no review requests or
  submitted reviews. Run `41118233020` initially reported `tray-dbus` SUCCESS
  and `test` PENDING; this is not the final check state. Recheck the exact
  current head before any merge.
- **Coordination:** the exact-head status and screenshot were sent to
  orchestration before opening. B13a has the active build-45 slot. Do not merge
  until all exact-head required checks pass, mergeability is clean and the
  serialized slot remains confirmed. B13 parent is partial; B13b is still
  required before B14 can proceed.

### E069 — 2026-10-30: B13a Cairo and unknown-cost screenshot corrections

- **Source/base/build:** B13a remains PR #46, build `0.82.0 (45)`, based on
  `origin/main` at `d1eff67725cfbde82c49f0eb75861d4dbbd4d797`. The refreshed
  `origin/main` still points to that dependency merge. No B14 contract change
  was needed.
- **Cairo diagnosis and fix:** this host's system Python had PyCairo but no
  `gi._gi_cairo`, so `cairo_support.HAS_CAIRO` was false and both Cairo draw
  callbacks returned before painting. `scripts/bootstrap-deps.sh` now fetches
  and stages the bridge, `scripts/install.sh` copies it into the app's private
  `deps` directory, and `cairo_support.py` searches that installed location.
  An isolated `--no-autostart` install confirmed the private bridge is present
  and loadable. `run.sh` supplies the development typelib/library path; the
  fixture smoke ran with `GDK_BACKEND=wayland` and selected
  `GdkWaylandDisplay` (`wayland-1`).
- **Cost-row diagnosis and compatibility:** the fixture omits `totalCost` for
  `unknown-cost-project` and omits both `cost` and `totalCost` for
  `unknown-cost-model`; these are truly unknown. The earlier smoke window was
  created before Rust controller initialization, so it was marked as the Python
  renderer and could display the legacy `0.0` fallback. The Rust projection
  DTO kept both costs as `None`. The smoke now configures the view from the
  explicit opt-in backend and checks the exact DTO rows and visible GTK labels.
  The Python parity renderer now shows missing costs as `unpriced`. Rust and
  Python both retain known zero as `$0` when no fallback exists and preserve
  the legacy model behavior where `cost: 0` falls back to a nonzero
  `totalCost` (fixture value 3 displays `$3`).
- **Rust/presentation tests:** Rust projection unit and facade integration
  fixtures assert unknown project/model costs stay absent, explicit-zero
  project/model costs stay known, and the zero-to-nonzero `totalCost` fallback
  stays 3.0. The GTK smoke asserts the same cases against rendered row labels
  in both Python and Rust modes.
- **Checks:** `cargo fmt --check` passed for core, backend and PyO3 bridge;
  locked tests passed (72 core, 45 backend); strict all-target/all-feature
  Clippy passed for all three crates; `scripts/build-rust-core.sh` passed.
  Python discovery passed 187 tests in default mode with 9 expected opt-in
  skips and all 187 in Rust-opt-in mode. The focused tray D-Bus suite passed
  three tests; Python compilation and `git diff --check` passed. Earlier PR #46
  head `d590c0d` had both required checks successful; the corrected branch
  head must be checked again after push.
- **Fixture-only GTK runtime:** both modes ran against the existing Wayland
  compositor with an isolated HOME, synthetic CLI, fake tray sink and actual
  GTK main window. Draw callbacks ran at `680x104` (heatmap: 1,400 tokens,
  two active cells) and `680x168` (chart: one known positive amount, one
  unknown day). The smoke verified and captured `unpriced`, `$0`, and `$3`
  rows. A temporary install's copied app package, private typelibs/libraries
  and Cairo bridge were used for the Rust screenshot
  `screenshots/b13-spend-tray-synthetic.png`; a default-Python Wayland capture
  is `screenshots/b13-spend-tray-python-wayland.png`. Both compositor captures
  were visually inspected. This used fixture data only; it did not exercise a
  real account or a live StatusNotifier host. Nonfatal EGL access and AT-SPI
  connection warnings were emitted; the smoke exited successfully.
- **Status/next:** PR #46 remains open and held until the corrected head's GitHub
  checks, clean mergeability and screenshot-bearing PR are reverified. Send the
  corrected runtime evidence to orchestration before merge and preserve the
  serialized build-45 slot. B13 remains partial until B13b is implemented and
  verified; no parent completion is claimed.

### E070 — 2026-10-30: B13a PR #46 merged; B13b1 build-46 slot claimed

- **Observed PR state:** PR #46 was rechecked at exact head
  `0fe3349f4205602129218b4f6d09888f070da1df`, targeting `main`, based on
  B09a's merge `d1eff67725cfbde82c49f0eb75861d4dbbd4d797`. It was OPEN,
  MERGEABLE/CLEAN, with no reviews or comments. GitHub Actions run
  `41121192187` reported both required checks, `test` and `tray-dbus`, SUCCESS.
  The PR body included the corrected Rust and Python synthetic Wayland
  screenshots. After those checks and UI evidence were verified, PR #46 was
  merged normally (no bypass) at
  `1650646ffee23015ec9f5f640a0470755d7f247c`; a fetch confirmed
  `origin/main` exactly matches that commit.
- **Correction to E069:** its final status paragraph was recorded before the
  merge and said PR #46 remained open. The observed state above supersedes that
  pre-merge handoff. E069's local check and fixture smoke details remain valid.
- **Next task/scope:** B13b1 is claimed on branch
  `backend/b13b-settings-actions-rust`, based on the B13a merge, provisional
  build `0.82.0 (46)`. The focused slice routes settings provider actions,
  hooks/plugins, preferences import/export/reset and launch-at-login query/set
  through the shared Rust facade. Rust owns preference file I/O, parsing,
  serialization, mutation and stable sanitized operation errors; GTK retains
  the native file chooser and GLib marshalling. B14 is reviewing the proposed
  public method names, DTOs and failure categories before API freeze.
- **Remaining B13 scope:** B13b2 covers B11 login, B12 update checking and
  restart operations. B13 parent stays partial until B13b1, B13b2 and every
  remaining settings/application caller route have been verified and merged.
  No B14 API incompatibility is known; the B13b1 contract review is pending.

### E071 — 2026-10-30: B13b1 settings facade and shared CLI reconfiguration verified locally

- **Owner/base/build:** current coding-agent session; branch
  `backend/b13b-settings-actions-rust`, based on B13a merge
  `1650646ffee23015ec9f5f640a0470755d7f247c`; build `0.82.0 (46)`.
- **Scope:** B07 typed settings reads/actions, hooks/plugins, PreferencesStore
  import/export/reset and launch-at-login query/set are exposed through the
  shared Rust facade with owned DTOs and sanitized static operation errors.
  Python keeps native file chooser, GLib marshalling and widget rendering. The
  same `Arc<SharedCliService>` backs B10 and settings; each CLI call clones the
  current immutable service under a short read lock and performs I/O after the
  lock is released.
- **Reconfiguration contract:** B14 approved
  `settings_reconfigure_cli(cli_path: Option<String>, timezone: Option<String>)`
  and `CliReconfigureResult { applied, refresh_queued }`. `None` resolves from
  shared PreferencesStore inside the serialized actor; `Some("")` explicitly
  persists blank and selects default executable/system timezone. Both `None`
  is `invalid_input/settings_cli_reconfigure` with no preference/slot change or
  refresh. Actor snapshots both current values once, overlays the patch, trims
  the path, validates the effective executable, persists both keys via the
  reconfiguration-only transactional store method, swaps the shared slot, then
  queues B10 refresh. Validation/persistence failures occur before commit and
  leave memory and slot unchanged. A closed refresh channel after commit is
  `Ok { applied: true, refresh_queued: false }`; accepted/coalesced refresh is
  true. In-flight operations retain their cloned old service; later calls and
  the forced follow-up use the new service. The Python parity setter still
  trims/applies/persists immediately without executable validation; Rust's
  reject-invalid-before-commit behavior is the approved narrow correction.
- **Tests:** Rust core 75 passed; backend 56 passed, including scoped
  transactional persistence failure, invalid paths, omitted-field preservation,
  explicit blanks, concurrent partial patches, empty-patch no-refresh, old
  in-flight/new subsequent CLI behavior, closed refresh channel and a B10-level
  blocked-pass test proving the coalesced follow-up uses the final executable
  and timezone. Checked-read tests cover valid-looking output on nonzero exit,
  timeout and independent successful sections. Python default discovery passed
  192 tests with 12 expected opt-in skips; Rust-opt-in discovery passed all 192.
  The focused tray D-Bus suite passed 3 tests. Strict all-target/all-feature
  Clippy and format checks passed for core, backend and PyO3 bridge; the atomic
  extension build and `py_compile` passed; `git diff --check` passed.
- **Fixture-only GTK runtime:** default Python and Rust-opt-in modes each ran
  against the active Wayland compositor with temporary HOME/XDG directories and
  synthetic CLI scripts only. The smoke exercises provider configuration,
  path-only then timezone-only reconfiguration, immediate refresh, and asserts
  both settings controls reflect the accepted values. `Spectacle --activewindow`
  captures are [Python](screenshots/b13-settings-python-wayland.png) and
  [Rust](screenshots/b13-settings-rust-wayland.png); both show the CodexBar
  settings window and were visually inspected. No real account or credential
  data was used. Nonfatal EGL and AT-SPI warnings were emitted. A private
  `dbus-run-session` capture could not reach the live compositor portal, so the
  screenshot was captured from the existing session bus; ordinary tray tests
  ran separately in their required D-Bus environment.
- **Status/handoff:** B13b1 is locally verified and ready for its focused PR,
  pending orchestration's serialized opening/merge slot and remote CI/review.
  The B14 API contract is approved; the exact methods, patch semantics and
  errors above are the frozen interface. B13b2 (B11 login, B12 update, restart)
  and remaining caller audit still block B13 parent completion and B14.

### E072 — 2026-10-30: B13b1 PR #47 opened; initial required checks pending

- **PR/base/head at creation:** [PR #47](https://github.com/SaahiilM/codexbar-gtk/pull/47)
  was opened against `main`, whose observed SHA was
  `1650646ffee23015ec9f5f640a0470755d7f247c`; submitted head was
  `1283ed0bad825c09987fad4ea234962767e3ce39`. The branch included both
  synthetic settings screenshots and E071's implementation audit.
- **Observed initial review/check state:** PR state OPEN, `mergeable=true`,
  `mergeStateStatus=UNSTABLE` while checks were pending; required `test` and
  `tray-dbus` jobs were IN_PROGRESS. No reviews, review requests, or comments
  were present. This is not a CI-success claim.
- **Next exact step:** after the audit/handoff follow-up commit, fetch and
  inspect the latest PR head/base, recheck reviews and both required jobs, and
  merge normally only after exact-head checks and fixture UI evidence pass.
  Record later check/merge evidence in a subsequent audit entry. B13 remains
  partial; B13b2 and the remaining caller inventory are outstanding.

### E073 — 2026-10-31: B13b1 PR #47 merge observed; B13b2 claimed

- **Observed PR merge:** PR #47 merged normally at
  `490b4b641282fe87a632d31e83864c9067e3e10f`, now the fetched `origin/main`.
  Its exact head was `327f593ef5701596c0cec51c6215776eab1f7ae4`; GitHub's
  required `test` and `tray-dbus` checks both report SUCCESS on that head. The
  PR was CLEAN/MERGEABLE with no reviews, review requests or comments. A GitHub
  connector merge attempt returned 403; the repository owner completed the
  normal `gh pr merge --merge` path, without bypassing branch protection.
- **B13b2 claim/base/build:** active branch
  `backend/b13b2-application-actions-rust`, based on the merge commit above;
  provisional build is `0.82.0 (47)`. This focused slice covers B11 login
  operations, B12 update checking, restart, and a remaining UI caller audit.
  B13 remains partial, and B14 remains gated until all B13 slices are verified
  and merged.
- **Initial source inventory:** `codexbar_gtk/ui/app.py` invokes the Python
  update worker and owns both the installed `systemctl --user restart` and
  development `os.execv` paths; `codexbar_gtk/updates.py` retains Python HTTP,
  parsing and comparison as the parity implementation; `codexbar_gtk/login.py`
  uses the separate B11 Rust `LoginSession` in opt-in mode but still has its
  Python PTY/subprocess parity path; `codexbar_gtk/ui/settings.py` launches
  non-Claude terminal login via Python `subprocess.Popen`. The latter and any
  other production UI subprocess/HTTP callers need an explicit B14-approved
  disposition before B13 can be called complete. GTK dialog rendering, browser
  opening, GLib marshalling and OS notification delivery remain UI/platform
  responsibilities.
- **B14 coordination:** a concrete proposal for facade login handle creation,
  typed update results and restart result/non-systemd behavior was sent to B14;
  final public method names and result semantics are pending its response before
  API freeze. No code changes have yet been made for B13b2.
- **Next exact step:** freeze the method/result contract with B14, then implement
  B13b2 behind the shared Rust facade. Run the migration checks, fixture-only
  Python and Rust-opt-in GTK smoke with private temp HOME/D-Bus and synthetic
  CLI, capture and inspect both screenshots, and verify the final source caller
  inventory. Open a focused PR only after local checks and UI evidence pass.

### E074 — 2026-10-31: B13b2 application-action facade locally verified

- **Scope/build:** B13b2 is implemented on
  `backend/b13b2-application-actions-rust`, based on verified `origin/main`
  `490b4b641282fe87a632d31e83864c9067e3e10f`; this merge-intended slice uses
  build `0.82.0 (47)`. B13 remains partial; B14 remains gated until all B13
  slices and the caller inventory are accepted and merged.
- **Frozen B14 surface:** the central controller creates the separate B11
  `RustLoginSession` for Claude login, retaining its watch and bounded event
  receiver outside B10 snapshots/notifications. `check_update` calls B12's
  bounded `updates::check` on the Rust controller runtime and returns current,
  latest and relation; the PyO3 boundary exposes only the stable error kind and
  static `update_check` operation. `launch_codex_login_terminal` performs Rust
  CLI/terminal discovery and argv launch, returns `launched: false` if no
  supported terminal exists, and keeps errors sanitized. `restart_application`
  requests `systemctl --user restart codexbar-gtk` when `INVOCATION_ID` is set,
  then falls back on spawn failure to detached `current_exe()` plus OS argv;
  tests verify development and installed `python3 -m codexbar_gtk` wrappers,
  systemd success/fallback and static errors. `refresh_icon_cache` returns
  `refreshed`, `skipped_missing_directory`, `skipped_missing_tool`, or explicit
  best-effort `failed`; it targets `~/.local/share/icons/hicolor`, prefers
  `gtk4-update-icon-cache` then `gtk-update-icon-cache`, uses `-f -t` and a
  20-second timeout, and surfaces no paths or tool output. Rust async/process
  calls run on workers; GTK retains SVG writes/rendering, the native chooser,
  browser interaction, GLib marshalling and OS notification delivery.
- **Wayland rendering correction:** captured a real transitional issue where
  `Adw.MessageDialog`'s already-presented progress buffer remained visible in
  the compositor after its heading/body properties changed. The update result
  now creates the completed dialog while the progress dialog still exists,
  closes the progress dialog, then presents the completed one. This preserves
  the result labels and gives Wayland a fresh surface; the compositor screenshot
  now shows the completed synthetic `Update available: 0.82.0 (48)` result.
- **Caller inventory:** Rust-opt-in UI call sites now route Claude login,
  Codex terminal login, update checking, restart and icon-cache refresh through
  the central facade. `ui/app.py`'s GLib 250ms timer only drains the B10 watch
  and events; B11 login dialog polling only marshals its separate event stream;
  `ensure_display` retries GTK display readiness. Python `cli.py` controller
  commands, update HTTP/parser code in `updates.py`, login PTY/browser helpers,
  `ui/app.py` restart fallback, `ui/settings.py` terminal fallback,
  `ui/icons.py::_refresh_icon_cache`, and Python currency HTTP remain parity
  paths and are not used for the migrated Rust-opt-in callers. The one-shot
  `claude_auth_status()` helper has no production callers. GTK notification
  delivery remains platform-side; policy/event selection is B10/B13a Rust.
- **Tests/checks:** `cargo test --manifest-path rust-core/Cargo.toml --locked`
  passed 75; the backend command passed 69. The first parallel Cargo run
  exposed a cancellation fixture race: `Path::exists()` became true as the
  shell opened/truncated `child.pid`, before its PID write completed. Both the
  timeout and cancellation tests now wait until the file contents parse as a
  PID before asserting process termination/cancelling. The exact workflow order
  (core then backend) passed, followed by two more standard parallel backend
  test runs (69 each); this verifies the test synchronization fix under normal
  test parallelism.
  Python parity discovery passed 202 tests with 20 expected Rust-opt-in skips;
  `CODEXBAR_RUST_CORE=1 python3 -m unittest discover -s tests -q` passed all
  202. The focused tray D-Bus suite passed 3. Format and strict all-target,
  all-feature Clippy passed for core/backend/PyO3; the optional extension built
  atomically; Python compileall and `git diff --check` passed. Restart wrapper
  tests cover installed/development argv; Rust injected launch tests cover
  systemd failure fallback/sanitization; icon-cache tests cover preference,
  fallback, argv, timeout, missing directory/tool, nonzero/failure result and
  quiet facade status. B12 loopback and B11 fake-login PyO3 tests pass. No real
  auth/account data was used.
- **Fixture-only GTK:** the new app smoke ran both backend modes on the active
  Wayland display with temporary HOME/XDG trees, a synthetic CLI, a loopback
  VERSION server, a fake icon-cache executable, and a private `dbus-run-session`.
  The app's actual update worker/facade completed and the smoke asserted the
  result dialog heading/body; the fake icon tool was also invoked after SVG
  generation. Spectacle used the existing desktop bus only for KWin compositor
  capture. Both active-window images were visually inspected:
  [Python mode](screenshots/b13b2-actions-python-wayland.png) and
  [Rust opt-in](screenshots/b13b2-actions-rust-wayland.png). They contain only
  synthetic version metadata and no account, secret or auth output. This is a
  focused update/cache smoke, not exhaustive login interaction or provider
  validation.
- **Status/handoff:** B13b2 is locally verified with screenshots and the final
  caller inventory; PR is pending. B13b parent remains partial until the
  screenshot-bearing PR and all extracted scopes are verified and merged. Next:
  report exact readiness to B14/orchestration, open the focused PR against
  current `main`, then verify its exact head, review state, mergeability and
  required checks before normal merge.

### E075 — 2026-10-31: B13b2 PR #48 opened; initial CI pending

- **PR/base/head:** [PR #48](https://github.com/SaahiilM/codexbar-gtk/pull/48)
  targets `main` at observed SHA
  `490b4b641282fe87a632d31e83864c9067e3e10f`. Initial submitted head was
  `4eae00c5cdb7210bdbfcb06fe39ec2475256b0c2`, build 47. The body embeds both
  synthetic active-Wayland update-result screenshots. The PR is linked to the
  B13 thread; the GitHub connector create endpoint returned 403, so the same
  authorized normal PR creation was completed with `gh pr create`.
- **Initial live review/check state:** PR OPEN and MERGEABLE, with
  `mergeStateStatus=UNSTABLE` because `test` was IN_PROGRESS. `tray-dbus` was
  SUCCESS on the exact submitted head. No reviews or comments were present.
  The exact PR API base/head response matched the fetched `origin/main` and the
  submitted commit. These initial statuses are historical; refresh them against
  the live final head before any merge.
- **Local cancellation-test race resolution:** E074 records the cause and
  fix. The standard Rust workflow sequence passed, followed by two additional
  parallel backend runs; every backend run reported 69 passed. The head
  includes the parseable-PID fixture synchronization fix.
- **Next exact step:** wait for the PR check/review event, then recheck current
  `main`, final head, checks, reviews, screenshot body and mergeability. Merge
  only through the normal GitHub path when final-head verification is clean;
  B13 remains partial until B13b2 and the full caller inventory are accepted.

### E076 — 2026-10-31: B13 slices merged; final inventory accepted

- **Live merge evidence:** fetched `origin/main` is
  `be370b63b94c186262606dcbf70e16353300b0e5`, the normal merge commit for PR
  #48. Exact head `4d1aff43f18a8e1bdbc8166b38e03df54a79031a` has both required
  GitHub checks (`test`, `tray-dbus`) SUCCESS. PR #48 is MERGED; it had no
  reviews or comments. The complete slice chain is:
  - B13a PR #46, head `0fe3349f4205602129218b4f6d09888f070da1df`, merge commit
    `1650646ffee23015ec9f5f640a0470755d7f247c`; `test` and `tray-dbus`
    SUCCESS.
  - B13b1 PR #47, head `327f593ef5701596c0cec51c6215776eab1f7ae4`, merge commit
    `490b4b641282fe87a632d31e83864c9067e3e10f`; `test` and `tray-dbus`
    SUCCESS.
  - B13b2 PR #48, head `4d1aff43f18a8e1bdbc8166b38e03df54a79031a`, merge
    commit `be370b63b94c186262606dcbf70e16353300b0e5`; `test` and `tray-dbus`
    SUCCESS.
  There were no open PRs when this handoff began.
- **B14 acceptance:** B14 accepted the merged B13a/B13b1/B13b2 implementation
  coverage, conditional on this accurate build-48 reconciliation PR merging.
  With that condition reflected in TASKS, B13 is checked as implementation
  complete; B14 remains gated until this handoff PR merges.
- **Accepted B13 caller inventory:**
  - Spend/tray: Rust presentation DTOs own spend time-range selection,
    target-currency conversion/coverage and partial-state semantics, grouping,
    stable row order/limits, and tray selection/presentation policy. The
    controller obtains projections from its current B10 state and shared
    CurrencyService off GTK; Python renders the owned DTOs. The full daily
    series remains available to the GTK heatmap independently of chart range.
  - Settings: Rust facade/B07 operations own provider configuration/actions,
    hooks/plugins, checked CLI reads, shared CLI reconfiguration, launch-at-login
    state/set, and PreferencesStore import/export/reset/file I/O. GTK owns the
    native chooser and result marshalling. Reconfiguration preserves path-only
    and timezone-only patches, rejects an invalid executable before commit,
    swaps the shared CLI slot after transactional persistence and queues B10
    refresh; its intentional Python-parity correction is documented in E071.
  - Application actions: Rust opt-in routes Claude login through B11's separate
    session, Codex terminal login through the facade, update check through B12,
    restart and icon-cache process refresh through the facade. Worker results
    return to GTK by GLib. Python subprocess/HTTP implementations are retained
    only as the default Python parity branch.
  - Frontend/platform behavior left in Python: GTK/Cairo drawing and widget
    layout, GLib marshalling and nonblocking watch/event drains, native dialogs
    and file chooser interaction, browser opening and OS notification delivery,
    SVG generation/writes and icon rendering, and display-readiness retries.
    These are the explicitly accepted UI/platform boundary, not B13 backend
    policy.
- **Explicit B14 follow-up (not a B13 blocker):** `codexbar_gtk/currency.py`
  creates a module-level Rust `CurrencyConverter`/CurrencyService wrapper. The
  same inner Rust service is cloned into `RustRefreshController` at
  `controller.py`; this is one service instance, not a second network service.
  Rust-opt-in UI adapters in `ui/app.py` and `ui/settings.py` still call
  `currency.shared().ensure_rates`, while `ui/cards.py`, `ui/window.py`, and
  legacy `ui/spend.py` paths call `requires_live_rates`/`convert`. The central
  `RustRefreshController` facade currently does not expose the shared service's
  catalog, rate, conversion, status and refresh operations. B14 owns adding
  `catalog_async`, `rate_async`, `convert_async`, `status_async`, `ensure_rates`
  and `ensure_rates_at` on that facade and routing these current UI adapters
  through it. These direct adapter calls must not be mislabeled as Python HTTP
  parity. B14 is gated until the build-48 handoff PR merges; currency facade
  routing is its first implementation item.
- **Fixtures and UI evidence:** B13a's active Wayland spend/tray fixtures are
  `screenshots/b13-spend-tray-python-wayland.png` and
  `screenshots/b13-spend-tray-rust-wayland.png` (E069); B13b1 settings fixtures
  are `screenshots/b13-settings-python-wayland.png` and
  `screenshots/b13-settings-rust-wayland.png` (E071); B13b2 action fixtures
  are `screenshots/b13b2-actions-python-wayland.png` and
  `screenshots/b13b2-actions-rust-wayland.png` (E074). They were captured with
  synthetic data and no real account or credential output. This final handoff
  changes no UI/runtime code, so it reuses those merged screenshot records and
  does not claim a new GTK smoke.
- **Build and handoff:** the final handoff uses build `0.82.0 (48)`; `VERSION`,
  `codexbar_gtk/version.py`, README and CHANGELOG are synchronized. The B13
  implementation parent is complete based on the three merged slices and
  B14's acceptance; B14 stays unchecked/gated until this reconciliation PR is
  merged. After that merge, the next task is B14's shared CurrencyService
  facade routing described above. No B14 implementation or B15/BG/native UI
  completion is claimed here.
- **Handoff validation:** default Python discovery passed 202 tests with 20
  expected Rust-opt-in skips; `CODEXBAR_RUST_CORE=1` discovery passed 202 tests;
  the focused private-D-Bus tray suite passed 3. The version-pair/README/
  CHANGELOG synchronization check and `git diff --check` passed. No Rust or UI
  runtime source changed in this docs/status handoff, so the PR reuses the
  already merged fixture-only GTK screenshots above instead of claiming a new
  GTK smoke. The PR's required workflow remains the exact-branch authority for
  Rust core/backend tests and both required GitHub checks.

### E077 — 2026-10-31: PR #49 merge observed; B14 build-49 slot claimed

- **Dependency merge evidence:** PR #49, [B13 final inventory handoff](https://github.com/SaahiilM/codexbar-gtk/pull/49), is MERGED at
  `a42a29972e2894ef82fdbdc1430aeb4608d24c0f`; fetched `origin/main` matches.
  Exact PR head `df97e8f8cfc46d7f47e870a93f28af59e8d36f98` passed both required
  GitHub checks (`test` and `tray-dbus`). It had no reviews or comments. There
  were no open PRs when B14 resumed. B13's full accepted inventory and all
  implementation slices are therefore unblocked; B14 does not infer any
  additional B13 source changes.
- **Claim/base:** B14 build `0.82.0 (49)` is active on branch
  `orchestrated/luna-b14`, based directly on the observed main merge
  `a42a29972e2894ef82fdbdc1430aeb4608d24c0f`. The first implementation slice
  is B14a: expose `catalog_async`, `rate_async`, `convert_async`,
  `status_async`, `ensure_rates` and `ensure_rates_at` through the central
  RefreshController facade and route the existing currency callers through it.
- **Preserved contract:** the facade uses the same `CurrencyService` instance
  already passed into RefreshController, including its shared rate state and
  single-flight refresh. Status retains `fetched_at`, `RateSource` (offline,
  cache or live) and `last_refresh_failed`. Rust continues to own HTTP/cache
  behavior; the Python default implementation remains the parity path. No API
  contract changes were required.
- **Next exact step:** finish B14a implementation and verification on this
  build-49 branch, complete the single-facade/production caller audit, update
  version and migration handoff files, and open one focused PR only after the
  fixture-only GTK evidence is visually checked. This claim does not mark B14
  complete or claim the new PR's CI/merge status.

### E078 — 2026-10-31: B14a currency facade and caller audit verified locally

- **Branch/base/build:** `orchestrated/luna-b14`, based on observed
  `origin/main` at `a42a29972e2894ef82fdbdc1430aeb4608d24c0f`; build
  `0.82.0 (49)`. B14a is locally verified; no B14 implementation PR has been
  opened yet, so no remote check, review or merge result is claimed.
- **Facade/service behavior:** `RustRefreshController` now exposes
  `catalog_async`, `rate_async`, `convert_async`, `status_async`, `ensure_rates`
  and `ensure_rates_at`, all backed by its `CurrencyService` clone. The clone
  shares the same rate snapshot and single-flight refresh lock as the
  `RustCurrencyConverter` passed by `Controller.start()`. Python binds the
  existing `currency.shared()` adapter to this controller once the Rust
  controller starts; no second cache/network service is constructed. Status
  maps `fetched_at`, `RateSource::{Offline,Cache,Live}` and
  `last_refresh_failed` into an owned Python dictionary. `ensure_rates` runs on
  a controller-owned worker and awaits the shared service on the controller's
  Tokio runtime; quick in-memory catalog/rate/conversion reads do not start
  network work.
- **Caller routing:** `ui/app.py` and `ui/settings.py` use controller currency
  methods for refresh and the settings picker. Existing conversion consumers
  in cards/window/spend and monthly pace continue using the thin
  `currency.py` compatibility adapter, which delegates to the bound central
  facade in Rust mode. The SettingsWindow fixture now constructs after
  controller start and asserts the EUR label came from the selected backend.
- **Residual caller inventory:** Rust opt-in refresh, settings/actions,
  spend/tray projections, login, updates, restart and icon-cache work route
  through `Controller`/`RustRefreshController`; Rust opt-in currency callers now
  do as well. `ui/app.py` systemd/re-exec, `ui/settings.py` terminal launch and
  `ui/icons.py` icon-cache subprocess calls remain only in their Python
  fallback branches. The Python `currency.py` and `updates.py` HTTP clients are
  compatibility implementations; Rust opt-in uses Rust services. GTK widgets,
  Cairo/SVG rendering, native chooser/dialog interaction, GLib marshalling,
  browser opening and OS notifications remain frontend/platform work. The
  static Python currency table remains for parity and existing formatting
  helpers; Settings uses the facade catalog in Rust mode. This audit found no
  additional B14 integration gap; B15 retains the catalog/edge-parity review.
- **Checks:** Rust format checks passed for all three crates. Locked Rust suites
  passed: 75 core and 69 backend tests. Strict Clippy with `-D warnings`
  passed for core, backend and PyO3 bridge; `scripts/build-rust-core.sh`
  produced the opt-in extension. Default Python discovery passed 203 tests with
  21 expected Rust-opt-in skips; Rust-opt-in discovery passed all 203 tests.
  The focused application-actions integration module passed 11 tests, including
  shared CurrencyService instance, cache value, USD-pivot conversion, status
  and no-network refresh behavior. The tray signal suite passed 3 tests both
  normally and inside `dbus-run-session`. `git diff --check` and version-pair
  synchronization passed.
- **Fixture-only GTK evidence:** settings-window smoke passed on active Wayland
  in Python and Rust opt-in modes using a temporary HOME, synthetic CLI and
  synthetic EUR preference. Rust mode verified the settings currency catalog
  and source status through the facade. Visually inspected captures are
  `screenshots/b14-currency-python-wayland.png` and
  `screenshots/b14-currency-rust-wayland.png`; no real account, credential or
  external currency request was used. Nonfatal EGL and accessibility-bus
  warnings were emitted by this host. These screenshots evidence the focused
  currency/settings path, not exhaustive GTK interaction or native UI
  completion.
- **Handoff:** VERSION, `codexbar_gtk/version.py`, README's displayed build,
  CHANGELOG and the TASKS top-row now use build 49; E077 records PR #49's
  observed merge/check evidence. The caller audit and B14a are locally complete
  but remain PR-pending. Next: send exact readiness to orchestration, open the
  focused build-49 PR, then recheck its exact head, required checks, reviews,
  mergeability and serialized merge slot before any merge. B14 remains partial
  until that PR is verified and merged; no B15/BG/native UI completion is
  claimed.

### E079 — 2026-10-31: B14 build-49 PR #50 opened; initial checks running

- **PR/base/head:** [PR #50](https://github.com/SaahiilM/codexbar-gtk/pull/50)
  targets `main` at observed SHA
  `a42a29972e2894ef82fdbdc1430aeb4608d24c0f`; submitted head is
  `a27a7f7c5a799e85f8d220bfb898a26f2f3077a4` on branch
  `backend/b14-currency-facade-build49`. The pushed PR contains both synthetic
  Wayland currency/settings screenshots and E077/E078 handoff evidence, and is
  linked to the orchestration thread.
- **Observed initial GitHub state:** PR OPEN and MERGEABLE with
  `mergeStateStatus=UNSTABLE` while checks run. `test` and `tray-dbus` are both
  IN_PROGRESS in run `41157406180`. There are no reviews, review requests or
  comments. The observed API base/head match `origin/main` and the pushed
  candidate commit. These are initial statuses; recheck the current exact head
  before any merge.
- **Next exact step:** monitor the required checks, then refresh PR/base/head,
  review state and mergeability. Merge only after exact-head checks succeed,
  screenshots remain attached, and orchestration confirms the serialized
  build-49 merge slot. B14 remains partial until the PR is verified and merged.

### E080 — 2026-10-31: B14 PR #50 merged; full facade acceptance verified

- **Observed merge/check evidence:** PR #50,
  [B14 currency facade and caller audit](https://github.com/SaahiilM/codexbar-gtk/pull/50),
  merged normally at `0252420f048f3c2859fa19aa35a1632941e24956`. Its exact head
  `576d81f03f9d30d3b4e064ee33586c6819b04f00` was based on
  `a42a29972e2894ef82fdbdc1430aeb4608d24c0f`; both required checks (`test`,
  `tray-dbus`) passed in run `41157509759`. PR #50 was CLEAN/MERGEABLE with no
  reviews, review requests or comments. A fresh fetch confirms
  `origin/main` is the merge commit.
- **Full B14 acceptance review:** the central `RustRefreshController` facade
  composes B10's immediate/dynamic/manual refresh lifecycle, immutable watch
  state, one queued force-refresh follow-up, joined shutdown and separate
  bounded typed notification receiver. B10 snapshots retain owned provider,
  spend, session, history, tray-selection and version/error context; B09
  selection indexes resolve against the original ordered provider/window
  vectors. Unknown/partial values remain distinct from known zero; failed
  session scans retain prior sessions, usable partial spend survives source
  fallback, and history adds one sample per successful usage scan. B08
  notifications remain typed events on the separate event channel.
  Currency operations now run through that same facade and the same cloned
  `CurrencyService` instance used by refresh/spend projection, preserving
  `fetched_at`, live/cache/offline source and `last_refresh_failed`. B13 settings,
  CLI reconfiguration, login, update, restart, icon-cache and spend/tray methods
  are also composed there; B11 login events remain separate from B10
  notifications. B12 keeps its Unicode-decimal VERSION parity in Rust, with no
  Python update request/comparison in Rust opt-in. DTOs stay backend-owned and
  GTK/Python-free; bridge errors remain sanitized/static. E078's Rust-opt-in
  caller inventory found no extra B14 service gap. Remaining UI-side Python is
  limited to compatibility fallbacks, display conversion, GTK/GLib, native
  dialog/browser integration and OS notification delivery.
- **Verification evidence:** PR #50's exact-head checks passed. Its local
  verification is detailed in E078: 75 core and 69 backend tests; strict
  Clippy/format and extension build; default Python 203 with 21 expected
  Rust-opt-in skips and Rust-opt-in Python 203; tray signals 3 normally and in
  a private D-Bus session; fixture-only Python and Rust Wayland settings smoke.
  The same E078 screenshots, [`Python`](screenshots/b14-currency-python-wayland.png)
  and [`Rust opt-in`](screenshots/b14-currency-rust-wayland.png), were visually
  inspected and are included in PR #50. No new GTK runtime code changed in this
  closeout; it reuses that merged evidence and makes no broader UI-completion
  claim.
- **Completion/handoff:** B14a currency facade routing and B14b caller audit
  are verified and merged; mark B14 complete. Build-50 closeout updates
  VERSION, `codexbar_gtk/version.py`, README, CHANGELOG and TASKS. B15 is next
  after this handoff PR merges. BG remains open pending B15 and the complete
  headless/transitional backend gate; native UI migration remains blocked by
  BG. No API contract changes were needed.
- **Build-50 local checks:** default Python discovery passed 203 tests with 21
  expected Rust-opt-in skips; `CODEXBAR_RUST_CORE=1` discovery passed all 203.
  The tray signal suite passed 3 tests under `dbus-run-session`. Rust format
  checks for all three crates, version-pair/README synchronization and
  `git diff --check` passed. Runtime source did not change, so the closeout
  reuses E078's merged B14 Rust/core/backend/Clippy/build and fixture GTK
  evidence rather than repeating it or claiming a new runtime smoke.
- **Closeout PR status:** this build-50 documentation PR is being prepared from
  live main `0252420f048f3c2859fa19aa35a1632941e24956`; its own CI and merge
  status are not yet known. After it is opened, verify its exact head, required
  checks, reviews and normal merge before telling B15 to begin.

### E081 — 2026-10-30: B15 edge characterization and local implementation; PR pending

- **Observed base and dependency status:** Resumed on branch
  `orchestrated/luna-b15` at the latest `origin/main` B14 closeout merge
  `b229a4085a8dd45f0fbcb85be5a4afc0659a42fc`. PR #51's exact head was
  `964ff747cc9f7810047c6c791304b44b572fd75a`; required `test` and `tray-dbus`
  passed in run `41158198969`. B01–B06 and B14 are merged. The prior uncommitted
  audit draft remains preserved and was not reapplied; E081 follows E080 in the
  live append-only audit sequence. The overlapping root checkout was not edited.
- **Active scope:** B15 revisits F01–F06 opt-in boundaries while keeping the
  default Python implementations as parity references. It adds checked Rust
  errors at the PyO3/controller boundary, preserves last good refresh state on
  counter/window overflow, and routes Rust-mode provider/currency lookup to
  Rust-owned catalogs. No B06 or B14 API contract change was needed. BG remains
  open and no UI migration is started.
- **Characterized numeric behavior:** Python `_optional_int` accepts only
  non-boolean `int`/`float`, converts through binary64, then requires an
  integral finite value. The fixture records `2**53 + 1 -> 2**53`, accepts
  `2**70`, maps `10**1000` to `None`, and shows `2**63 - 1` rounding up to
  `2**63`. Rust window/count DTOs use signed 64-bit values. The service now
  surfaces `cli_usage_window_overflow` for an unrepresentable quota window and
  `cli_cost_counter_overflow` for an unrepresentable count or spend aggregate;
  controller tests prove both return the prior snapshot. Rust activity accepts
  i64 day values and checked weekly/cumulative i64 totals. Python token display
  can format larger arbitrary ints, while Rust supports signed i128 and raises
  `OverflowError` outside that range. Finite numeric formatting follows the
  Python helpers' float-conversion semantics (for example, `2**70 + 1` rounds
  to the same display value); values beyond finite float range fail clearly.
- **Timestamps and DST:** Python 3.12 `datetime.fromisoformat` reference cases
  cover extended/basic calendar and week dates; hour-only, hour/minute and
  second times; one-character separators including a non-ASCII separator;
  fractional seconds; and hour/minute/second/fractional offsets. Parsed naive
  provider values are assigned UTC and all parsed values normalize to UTC.
  Current provider fixtures use ordinary RFC3339 extended timestamps. Pace
  naive input, offset-second input, and New York spring-forward, fall-back and
  repeated 01:30 behavior match Python's local-calendar-day calculation; the
  DST cases are persisted in `tests/fixtures/b15/dst_pace_cases.json`.
- **Charts and history reachability:** Python chart helpers accept finite
  `Fraction` values and wide integers; the Rust adapter filters invalid points
  first, subtracts the first time before float conversion, and matches helper
  geometry for fractions, wide epochs, >2**53 widget dimensions, and
  nonpositive spans. Inputs that cannot become finite Python floats overflow in
  both implementations. The live chart path reads Unix-time/percentage floats
  from history and receives integer GTK dimensions; `Fraction` cannot be
  represented in CLI JSON or the persisted JSONL format. Production history
  writes float timestamps and percentages rounded to two decimals. The new
  `tests/fixtures/b15/persisted_history.jsonl` covers blank/corrupt records,
  malformed fields/defaults, numeric strings, booleans, non-finite values and
  large integer JSON values; Rust and Python read the same sample list. The
  direct Python writer can serialize `10**1000` as JSON integer text and then
  reads no sample, while Rust rejects that unrepresentable float sample before
  writing with an explicit overflow error. The
  Rust store requires text paths and i64 retention days; app defaults use a
  text path and 30 days. Python reference behavior remains unchanged.
- **Catalog and Unicode policy:** In Rust opt-in, provider metadata/aliases and
  currency conversion/picker operations read the corresponding Rust catalog;
  tests compare 110 providers, aliases and all currencies to the default-mode
  Python tables. Unknown-provider title fallback uses checked-in UCD 15.0
  `Cased`, `Case_Ignorable`, lowercase and titlecase data generated from
  UnicodeData, SpecialCasing and DerivedCoreProperties. The source/version is
  recorded in `rust-core/src/unicode_case.rs`. Exhaustive integration parity
  checks all 4,526 Python 3.12 cased codepoints and representative
  Case_Ignorable/category boundaries, including the comma regression. Known
  provider IDs are ASCII. Python 3.10/3.11 use older Unicode databases, so
  only unknown non-ASCII fallback labels can differ on those runtimes.
- **Explicit Rust opt-in compatibility changes:** Direct helper calls with
  window/activity/spend values outside signed i64, token values outside signed
  i128, history byte paths or retention outside i64, and direct formatting
  datetimes that are not UTC-aware now fail with clear errors instead of
  falling back to Python. Python accepts some such direct calls. Normal app
  provider timestamps are parsed to UTC; current history uses text paths,
  30-day retention and float samples; ordinary token/window/count data stays
  inside the documented DTO ranges. These direct-helper changes and the UCD
  15.0 unknown-label difference were reported before PR preparation. The
  Python default path and Python reference code are unchanged.
- **Changed paths:** opt-in adapters in `codexbar_gtk/{activity,charts,
  currency,data,format,history,pace,rust_bridge}.py`; numeric, timestamp,
  activity, chart, format, history, pace, Unicode case and provider behavior in
  `rust-core/src/`; controller overflow preservation in
  `rust-backend/src/controller.rs`; typed bridge errors in
  `rust-python/src/lib.rs`; parity tests in `tests/test_rust_*`; named fixtures
  under `tests/fixtures/b15/`; fixture smoke script and screenshots; README,
  TASKS, CHANGELOG, VERSION and `version.py` (build 51). No Rust dependency or
  lockfile change remains.
- **Local verification:** all three Rust format checks passed. Locked tests
  passed: 78 core and 71 backend. Strict Clippy passed for core, PyO3 and
  backend with `--all-targets --all-features -- -D warnings`. The atomic
  `scripts/build-rust-core.sh` build passed. Default Python discovery passed
  213 tests with 21 expected Rust-opt-in skips; Rust-opt-in discovery passed
  all 213 tests with no skips. Tray signals passed 3 normally and 3 under
  `dbus-run-session`. `git diff --check` and build 51 synchronization among
  VERSION, `codexbar_gtk/version.py`, and README passed.
- **Fixture-only GTK evidence:** `GDK_BACKEND=wayland CODEXBAR_RUST_CORE=0
  python3 tools/gtk_smoke_b13_spend_tray.py
  docs/rust-migration/screenshots/b15-compat-python-wayland.png` and the same
  command with `CODEXBAR_RUST_CORE=1` both exited 0 using a temporary HOME and
  synthetic CLI. Both captures rendered 2 heatmap cells / 1,400 tokens and a
  chart with one known-positive and one unknown point; the UI showed unknown
  cost separately from known zero. Both screenshots were visually inspected
  and are included as synthetic evidence. The Rust screenshot also shows an
  additional `· 4.0K tokens` suffix on the last-30-days label; Python omits this
  suffix. The same difference appears in the already-merged B13 captures
  `b13-spend-tray-python-wayland.png` and `b13-spend-tray-synthetic.png` and
  comes from B13's Rust spend projection, not a B15 change. This is an existing
  visual parity difference for BG to review; B15 does not migrate or alter the
  UI. Smoke covers the spend/tray display path, not exhaustive interaction or
  native UI completion. The host emitted
  nonfatal EGL device-permission and AT-SPI bus warnings; no account, credential
  or external currency request was used.
- **Handoff:** Build 51 is provisional for this PR. B15 remains unchecked and
  partial until the focused PR passes its own exact-head checks, receives UI
  verification, and is normally merged after orchestration serializes the
  merge. BG remains open. Before opening the PR, refresh `origin/main` and open
  PR state, send the final compatibility/contract report to the orchestration
  thread, and include both screenshots plus this audit entry. No PR, remote CI
  result, review or own-branch merge is claimed here.

### E082 — 2026-10-30: B15 PR #52 opened; exact-head checks pending

- **PR/base/head:** [PR #52 — B15: close original-port parity gaps](https://github.com/SaahiilM/codexbar-gtk/pull/52)
  targets `main` at observed base `b229a4085a8dd45f0fbcb85be5a4afc0659a42fc`.
  Branch `orchestrated/luna-b15` is at exact head
  `780d845008357c132526dd0791d58c4bb5aed9d3`. The PR includes the B15 numeric,
  DST and persisted-history fixtures, append-only audit/handoff, and the two
  synthetic Wayland screenshots. It is linked to the orchestration thread.
- **Initial live GitHub state:** PR OPEN and MERGEABLE, with
  `mergeStateStatus=UNSTABLE` while required checks run. `test` is IN_PROGRESS
  and `tray-dbus` is QUEUED in workflow run `41164254714`. There are no reviews,
  review requests or comments. `gh pr checks 52` reports both pending. This is
  the observed initial state only; refresh the exact head and checks before any
  merge.
- **Screenshot review:** both B15 screenshots were visually inspected. The
  Rust capture's `last30Tokens` suffix is a pre-existing B13 visual difference,
  also visible in the merged B13 screenshots; it is called out in E081 and no
  UI change is included here.
- **Next step:** keep BG open; wait for exact-head required checks and UI
  verification, then coordinate the normal build-51 merge with orchestration.
  Do not merge while checks are pending or before the serialized merge slot is
  confirmed. B15 is not complete until the merge and live-main verification are
  observed.

### E083 — 2026-10-31: B15 PR #52 merge observed; build-52 B13c slot active

- **Observed PR/base/head/merge:** PR #52 targeted `main` from build-51 head
  `791154691213b9592e799e4b5cdec962409ed995` and merged normally at
  `63eb17c8ea13c563c587cf9687a4877f1b5b47ff`. The user verified the exact-head
  `test` and `tray-dbus` checks passed; live `origin/main` is the merge commit.
- **Accepted B15 scope:** the numeric, timestamp/DST, history, chart, provider
  casing and catalog findings and explicit Rust-opt-in compatibility limits
  remain as recorded in E081. The Python default/reference paths are unchanged.
  No B06/B14 API contract changed.
- **Next work:** the B15 screenshots exposed a pre-existing B13 Rust-only
  last-30 caption suffix. The serialized build-52 slot is assigned to a focused
  B13 correction; BG remains blocked until the parity change is verified and
  accepted. No UI migration is authorized before BG.

### E084 — 2026-10-31: B13c last-30 caption parity locally verified

- **Base/build/scope:** rebased the isolated branch
  `fix/b13-last30-label-build52` onto live B15 merge
  `63eb17c8ea13c563c587cf9687a4877f1b5b47ff`; provisional build 52. Removed
  only the Rust-projection UI suffix ` · <count> tokens` from the last-30-days
  caption. The Python path and Rust `last30_tokens` DTO are unchanged.
- **Fixture coverage:** the PyO3 presentation fixture asserts last-30 cost
  `4.0` and known last-30 token count `300`; the GTK fixture asserts the visible
  caption is exactly `$18.75 last 30 days` in both modes and the Rust DTO still
  carries `4,000` last-30 tokens. Unknown and known-zero row assertions remain
  active.
- **Local checks:** `cargo fmt --check` passed for core, PyO3 and backend;
  locked Rust tests passed (78 core, 71 backend); strict Clippy passed for all
  three crates; the atomic extension build passed. Default unittest discovery
  passed 213 tests with 21 expected Rust-opt-in skips; Rust-opt-in discovery
  passed all 213 tests. Tray signal tests passed 3/3 normally and 3/3 under
  `dbus-run-session`. The targeted presentation integration test passed.
- **GTK fixture evidence:** both
  `GDK_BACKEND=wayland CODEXBAR_RUST_CORE=0/1
  python3 tools/gtk_smoke_b13_spend_tray.py` runs passed using a temporary HOME,
  synthetic CLI and the active Wayland compositor. `Cairo=True`; both live
  draw callbacks reported two active heatmap cells / 1,400 tokens and one
  known-positive chart bar plus one unknown point. The exact caption assertion
  passed. Screenshots
  `screenshots/b13-last30-python-wayland.png` and
  `screenshots/b13-last30-rust-wayland.png` were visually inspected; both show
  `$18.75 last 30 days`, the activity grid and daily bar. The old helper's
  earlier failure occurred before capture because it sampled the initial empty
  frame; B15's merged synchronization change waits for the refreshed snapshot,
  and the rerun passed. The host emitted nonfatal EGL permission and AT-SPI bus
  warnings. No real account, credentials, or external rates were used.
- **Contract/readiness:** B13a requires structured known/partial token data,
  which is preserved; no requirement was found to include the token count in
  this caption, and Python omits it. B13 remains unchecked and BG remains open
  until the focused PR is merged and the BG owner accepts the parity evidence.
  PR creation, remote CI and merge are not claimed here.
