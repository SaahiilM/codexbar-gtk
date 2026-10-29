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
