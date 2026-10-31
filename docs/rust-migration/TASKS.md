# Migration tasks and current handoff

Read the [architecture and gates](README.md) and [audit trail](AUDIT.md) first.
Task IDs are stable: add sub-IDs when splitting a task; do not renumber completed
history. A checked box means **verified and merged**, not merely implemented.

## Resume here

| Field | Current checkpoint |
| --- | --- |
| Goal | Fully native Rust GTK4/libadwaita app; backend first, UI second |
| Current phase | BG passed in PR #54 at `e1abf7b3e1db0e7f23e3be063a3ef067d85be1a1`; BG closeout PR #55 is live at `23651ecf47b902c57a753a4e3fb0955184412a32`, build 54. Phase U is unblocked. |
| Last merged implementation | BG closeout PR #55 merged at `23651ecf47b902c57a753a4e3fb0955184412a32`, build `0.82.0 (54)` |
| Planning change | [PR #18](https://github.com/SaahiilM/codexbar-gtk/pull/18), merged at `69c5496`, build `0.81.0 (17)` |
| Backend tasks completed after that baseline | B00–B15 and BG are accepted and merged. B11's Actions startup failures remain documented as failures; see E086. |
| Active implementation task / owner | **U01 in progress** — `frontend/u01-native-bootstrap-build55`, build 55, PR [#56](https://github.com/SaahiilM/codexbar-gtk/pull/56) open from the isolated worktree. |
| Latest gate result | **BG passed** — PR #54 merged and verified on live main. Headless Rust-only integration, Rust-opt-in GTK fixture smoke and residual-Python inventory are recorded in E085/E086. |
| Next domain slice | Finish U01 native application/bootstrap, direct backend connection, GTK dispatch, single-instance/CLI routing and version metadata. Preserve Python as the default until UG passes; do not start cutover work before UG. |
| Open external blockers | No BG blockers remain. Local GTK runtime libraries are installed, but system GTK4/libadwaita development packages and pkg-config files are absent; build 55 used an ignored worktree-local SDK extraction. CI now installs `libgtk-4-dev` and `libadwaita-1-dev` explicitly. B11's zero-job Actions startup failures remain documented, not CI successes. |
| Latest checks | U01 local verification is recorded in E087; PR #56's exact-head `test` and `tray-dbus` checks are pending. Last verified merge remains PR #55 at `23651ecf47b902c57a753a4e3fb0955184412a32`; BG gate checks for PR #54 remain recorded in E086. |
| UI validation | U01 synthetic native bootstrap [Wayland capture](screenshots/u01-native-bootstrap-wayland.png); B13c pair [Python](screenshots/b13-last30-python-wayland.png) / [Rust opt-in](screenshots/b13-last30-rust-wayland.png); BG pair [Python reference](screenshots/bg-python-reference-wayland.png) / [Rust opt-in](screenshots/bg-rust-opt-in-wayland.png). U01 used temporary HOME and synthetic CLI; no real account or credentials. |

**First commands for a new model/session:**

```sh
git status -sb
git log -8 --oneline
gh pr list --state open
gh pr view 18 --json state,mergeCommit,statusCheckRollup
gh pr view 19 --json state,mergeCommit,statusCheckRollup
gh pr view 20 --json state,mergeCommit,statusCheckRollup
gh pr view 21 --json state,mergeCommit,statusCheckRollup
gh pr view 22 --json state,mergeCommit,statusCheckRollup
gh pr view 23 --json state,mergeCommit,statusCheckRollup
gh pr view 24 --json state,mergeCommit,statusCheckRollup
gh pr view 25 --json state,mergeCommit,statusCheckRollup
```

B00 PR #19 (`956ffd3`), B01a PR #20 (`6fa18c9`), B01b PR #21 (`70f295a`),
B01c PR #22 (`4213503`), B02a PR #23 (`da215b1`), B02b1 PR #25 (`51cd4b8`),
B02b2a PR #27 (`965b592`), B02b2b1 PR #30 (`e5963c6`), B02b2b2a PR #32 (`96ed3d2`),
B02b2b2b PR #33 (`5aee61f`), and B03 PR #35 are merged with CI passing.
GTK4/libadwaita typelibs were previously made available through ignored `.deps/`
(E017); this note is historical. The current handoff is in the Resume here table.
For active work record task/subtask ID, owner/session, branch, PR if available,
changed files, checks performed/skipped, blockers and the next exact action.

## Existing foundation — not a completed backend

- [x] F01 Provider metadata: `rust-core/src/providers.rs` and opt-in callers in
  `codexbar_gtk/providers.py`; provider integration/catalog tests.
- [x] F02 Activity calculations: `rust-core/src/activity.rs` and opt-in callers
  in `codexbar_gtk/activity.py`; activity integration tests.
- [x] F03 Formatting: `rust-core/src/formatting.rs` and `codexbar_gtk/format.py`;
  integration tests; naive/non-UTC and unsupported-input fallbacks remain.
- [x] F04 Monthly pace: `rust-core/src/pace.rs` and `codexbar_gtk/pace.py`;
  PR #14; currency conversion still depends on Python.
- [x] F05 History persistence/queries: `rust-core/src/history.rs` and
  `codexbar_gtk/history.py`; PR #16; file compatibility and concurrency tests.
- [x] F06 Sparkline geometry: `rust-core/src/charts.rs` and
  `codexbar_gtk/charts.py`; PR #17; rendering remains Python.

These checked tasks were revisited under B15 for the final Rust-only contract.
Keep the explicit compatibility limits below visible; do not remove fallbacks
simply because F01–F06 are checked.

## Phase B — backend (BG gate verification active; UI migration is blocked)

Each B item requires native tests, transitional caller integration, application
smoke evidence where applicable, CI and a focused merged PR. Each can be split
into smaller PRs without declaring the parent complete early.

| Task | Dependencies | Deliverable / acceptance focus |
| --- | --- | --- |
| [x] **B00** Backend API and test seam | Foundation | Define snapshot/error contracts, Tokio/watch API and cancellation; record runtime/dependency decisions and headless fake-worker seam. Merged PR #19. |
| [x] **B01** Timestamp/numeric contracts and domain models | B00 | Port `data.py` timestamp/numeric helpers, `RateWindow`, `Pace`, `CostInfo`, detail/credit/provider/session/spend model contracts and derived properties. Freeze UTC/local, missing-vs-zero, rounding and large-number behavior. Completed in PRs #20–#22; see B01a–c.
| [x] **B02** Provider usage normalization | B01 | Port provider envelopes, extra windows, pace, identity/plan, costs, details/charts, credits and reset-credit parsing. Completed in the B02 sub-slices below. |
| [x] **B03** Agent-session normalization | B01 | Port session fields, timestamp handling, running-state classification and stable sorting; merged PR #35. |
| [x] **B04** Spend normalization/aggregation | B01 | Port old/new CLI totals, coverage/provenance, partial/error handling, daily/project/model data and ordering; merged PR #36. |
| [x] **B05** Preferences service | B00 | Port defaults, known-key loading/import, portable export, atomic 0600 writes, reset/update, thread safety and refresh settings. PR #37 merged at `878d4b7`; both checks passed on head `d43b18f`. |
| [x] **B06** Currency service | B00, B05 | Port currency catalog, labels, conversion, TTL/cache load/write, single-flight refresh and offline fallback; inject HTTP/time; connect monthly pace and spend callers. PR #38 merged at `5e4af06`; both checks passed on head `75bba44`. |
| [x] **B07** CLI service | B00 | Port executable discovery, argv/TZ handling, timeout/reaping, stdout/stderr/errors, JSON envelopes and command wrappers. Merged PR #42 at `e9dda26`; both checks passed. See AUDIT E054–E056. |
| [x] **B08** Notification policies | B01, B02, B05 | Port threshold transitions, session-exhaustion tracking, predictive pace cycles and credit-expiry deduplication. PR #40 merged at `9d272fd`; checks passed (see AUDIT E049). OS notification delivery remains frontend/platform work. |
| [x] **B09** Provider ordering and tray selection | B01, B02, B05 | Port visibility/order, automatic quota ranking and ETA trust/filtering; preserve deterministic ties, depleted quotas and placeholder exclusion. PR #39 merged at `93b62bb`; B09a PR #45 merged at `d1eff677` with both required checks successful (E067). |
| [x] **B10** Refresh controller | B02–B05, B07–B09 | Port immediate/dynamic polling, manual mode, one queued forced-refresh follow-up, joined shutdown, account collection, partial cost fallback, retained sessions/spend, successful-scan history samples and snapshot/event publication. Complete top-level B02 provider-envelope composition with shared-fixture Python parity; no I/O/callbacks under GUI locks. PR #44 merged at `a66e677`; both required checks passed on `b85348d`. |
| [x] **B11** Login/auth process service | B00, B07 | PR #43 merged at `a33f0977`. Exact-head local workflow and GTK fixture smoke passed; GitHub run #41110771700 ended `startup_failure` with zero jobs, so no CI pass is claimed (E064). |
| [x] **B12** Read-only update service | B00 | Port public VERSION parsing/comparison and bounded HTTP fetch; test invalid/oversized/network-failure responses. PR #41 merged at `bd58f46`; both checks passed on head `21537ba` (AUDIT E053). No code download/install behavior. |
| [x] **B13** Extract backend work embedded in UI | B04–B12 | B13a/B13b1/B13b2 plus B13c are merged; PR #53 at `0fc5cbb` closes the last-30 caption parity gap while retaining the structured token DTO. BG's source audit accepts B13; see E085. |
| [x] **B14** Full transitional backend integration | B06, B10–B13 | Shared CurrencyService facade and caller audit merged in PRs #50/#51 at `b229a408` (E080). The B13c caption correction is accepted under BG evidence E085. |
| [x] **B15** Close original-port gaps | B01–B06, B14 | PR #52 merged at `63eb17c8`; exact head `7911546` passed `test` and `tray-dbus`. Preserve its explicit compatibility limits and fixtures in E081/E083. |
| [x] **BG** Backend completion gate | B00–B15 | Passed after PR #54 merged at `e1abf7b3e1db0e7f23e3be063a3ef067d85be1a1`; exact head `993df09` passed `test` and `tray-dbus` in run `41166519056`. Rust-only CLI/controller + loopback HTTP + fake PTY integration, opt-in GTK fixture screenshots and residual-Python inventory are accepted (E085/E086). B11's zero-job Actions startup failures are not CI successes; authorized local workflow-equivalent evidence is recorded separately. |

### B15 characterization and accepted contract

PR #52 merged normally at `63eb17c8ea13c563c587cf9687a4877f1b5b47ff`; exact
head `791154691213b9592e799e4b5cdec962409ed995` passed `test` and `tray-dbus`.
The compatibility characterization below remains accepted; see E081 and E083.

- Python `_optional_int` uses float conversion (`2**53 + 1` rounds to
  `2**53`; `2**70` is accepted; `2**63 - 1` rounds up to `2**63`; `10**1000`
  returns `None`). Rust opt-in
  `i64` window/counter DTOs and checked activity/spend aggregation raise
  explicit overflow errors; backend operation IDs are
  `cli_usage_window_overflow` and `cli_cost_counter_overflow`, preserving the
  last good snapshot. Token display accepts signed `i128`; larger Python ints
  still format in Python and fail explicitly in Rust opt-in.
- Rust timestamp parsing matches the Python 3.12 `fromisoformat` shapes in the
  parity fixtures and returns UTC; naive provider values mean UTC. Pace keeps
  local-calendar-day behavior across DST. Direct formatting datetime helpers
  accept UTC-aware values only; production timestamps arrive normalized via
  `parse_timestamp`.
- `Fraction` and wide finite numbers are supported in direct chart-helper tests
  after normalization; production charts use floats from JSONL plus integer GTK
  dimensions. Out-of-f64-range chart inputs overflow in both paths. Persisted
  JSONL history fixture and New York spring/fall DST fixture are in
  `tests/fixtures/b15/`.
- A Python history append can serialize an integer such as `10**1000`, but its
  reader drops it because it cannot become a finite float; Rust opt-in reports
  the finite-float limit before writing.
- Rust opt-in provider and currency catalogs remain authoritative at runtime;
  their Python copies stay as default-mode references. Unknown provider fallback
  casing uses Unicode 15.0 data and is exhaustively compared to Python 3.12.
  Python 3.10/3.11 use earlier UCD versions, so unknown non-ASCII labels can
  differ there; known catalog IDs are ASCII.
- Rust-only representational limits are concrete and clear: signed 64-bit
  window/activity/spend counters and retention days, signed 128-bit token
  formatting, text-only history paths, UTC-aware direct formatting inputs and
  finite-float chart coordinates. The normal app writes current Unix timestamps,
  finite percentages and known provider/currency IDs. Python remains unchanged.

See README's B15 edge-input characterization and AUDIT E081/E083 for full
evidence, check results, screenshots and the observed merge.

B01 sub-slices (the parent stays pending until all models/contracts and caller
integration are complete):

- [x] **B01a** Timestamp/numeric primitives and `RateWindow` — merged PR #20.
- [x] **B01b** `Pace` and `CostInfo` — merged PR #21.
- [x] **B01c** Detail/credit/provider/session/spend model contracts and
  remaining derived properties — merged PR #22.

B02 sub-slices (the parent stays pending until all provider payload fields,
credits and error semantics are integrated):

- [x] **B02a** Standard primary/secondary/tertiary rate-window envelope —
  merged PR #23.
- [x] **B02b1** Pace object normalization — merged PR #25.
- [x] **B02b2a** Extra rate-window normalization — merged PR #27.
- [x] **B02b2b1** Provider cost normalization — merged PR #30.
- [x] **B02b2b2a** Detail chart normalization — merged PR #32.
- [x] **B02b2b2b** Credits/status/error/plan context normalization — merged PR #33.

B13 original slices and the build-52 caption correction are merged. Final caller
inventory is in E076; B13 and BG are accepted after PRs #53/#54 and the source
inventory in E085/E086:

- [x] **B13a** Spend/tray projections — Rust DTOs for spend time-range filtering,
  currency conversion, coverage/partial state, provider/model/project grouping,
  and tray summaries from B10's B09-ordered snapshot/selection. Missing row costs
  remain unavailable; explicit zero stays known, and `cost: 0` falls back to a
  nonzero `totalCost` for model rows. Keep GTK/Cairo drawing and list widgets in
  Python.
- [x] **B13b1** Settings operations — route provider configuration/actions,
  hooks/plugins, PreferencesStore import/export/reset, and launch-at-login
  query/set through the shared Rust facade. Rust owns file I/O, validation,
  serialization, preference mutation and stable sanitized errors; GTK owns the
  native file chooser and GLib marshalling. CLI path/timezone setters use
  `settings_reconfigure_cli(Option<String>, Option<String>)`; the serialized
  actor resolves omitted fields from PreferencesStore, rejects an empty patch,
  and commits both fields transactionally before swapping the shared CLI slot
  and queuing B10 refresh. B14 approved this contract; PR #47 merged at
  `490b4b64` with both required checks passing (E071, E073).
- [x] **B13b2** Application actions — route login through the separate B11
  handle, update checking through B12 Updates, and restart through a Rust facade
  operation; route icon-cache process refresh through the facade as well. GTK
  only marshals completed results, renders SVGs, handles native UI interactions
  and delivers OS notifications. B14 approved `start_claude_login(...)`, typed
  `check_update(...)`, `launch_codex_login_terminal()`, `restart_application()`
  and `refresh_icon_cache()`; icon-cache outcomes include explicit best-effort
  `failed`; see E074.
  PR #48 merged at `be370b63b94c186262606dcbf70e16353300b0e5`; exact head
  `4d1aff43f18a8e1bdbc8166b38e03df54a79031a` passed both `test` and `tray-dbus`.
  The final B13 inventory is accepted by B14; handoff PR #49 merged at
  `a42a29972e2894ef82fdbdc1430aeb4608d24c0f` (E077). The follow-up currency
  facade work was completed and merged as B14 PR #50 (E080).

- [x] **B13c** Last-30 caption parity — make the Rust-opt-in caption match
  Python's `$18.75 last 30 days` while keeping the structured `last30_tokens`
  DTO. PR #53 merged at `0fc5cbb`; exact head `6bd84ad` passed both required
  checks. B13c smoke asserts the matching caption and retained 4,000-token DTO
  value; BG rechecked both display modes in E085.

B14 sub-slices (all implementation and audit scope is verified and merged in
PR #50):

- [x] **B14a** Shared CurrencyService facade — expose catalog, rate, convert,
  status and refresh operations from the CurrencyService already cloned into
  RefreshController; route the current currency UI adapters through the
  controller. PR #50 merged at `0252420f048f3c2859fa19aa35a1632941e24956`;
  the exact head passed `test` and `tray-dbus` (E080).
- [x] **B14b** Single-facade and residual caller audit — E078 found that
  currency, settings, login, update, restart, icon-cache, refresh and
  presentation calls enter the central facade in Rust opt-in. Remaining
  Python branches are parity, conversion, GTK/GLib or platform integration.
  The audit found no additional B14 gap and is accepted in E080.

The earlier B04-first checkpoint above is historical; the current handoff is in
the Resume here table. BG passed after PR #54; Phase U may now be coordinated.

## Phase U — native GTK4/libadwaita UI (active; BG passed)

- [ ] **U01 (build 55, in progress)** Native application/bootstrap crate, direct backend connection,
  GTK main-context dispatch, single-instance/command-line behavior and version
  metadata. Preserve `--panel`, `--settings`, `--about`, and `--page` behavior.
- [ ] **U02** Dashboard, provider cards, quota meters, reset/pace/credit chips,
  charts/history and burndown presentation (`window.py`, `cards.py`).
- [ ] **U03** Compact panel, dismissal, anchoring and Wayland/X11 placement
  (`popup.py`, `x11_position.py`); preserve dashboard/settings navigation.
- [ ] **U04** Usage & Spend and Sessions pages, heatmap interaction/tooltips,
  filters and empty/error/loading/partial states (`spend.py`, `sessions.py`).
- [ ] **U05** Every preferences pane, provider/source/API-key controls,
  hooks/plugins, login dialog, import/export/reset, acknowledgements and About
  (`settings.py`, `login_dialog.py`). Backend actions use Rust services.
- [ ] **U06** StatusNotifierItem and dbusmenu, icon/pixmap export and all signal
  signatures; host re-registration, refresh/restart/settings/quit actions and
  updated tooltips. Port the private-bus regression coverage from PR #15.
- [ ] **U07** Desktop notification delivery, browser/terminal/file-dialog
  adapters, display readiness, restart and launch-at-login integration; verify
  shutdown leaves no workers, processes or tray registrations behind.
- [ ] **U08** Provider artwork/assets, theme/CSS, icon generation, Cairo/GTK
  rendering, accessibility, keyboard navigation and display scaling.
- [ ] **UG** Full feature/interaction parity against README and Python app;
  fixture screenshots and functional checks on Wayland and X11, with unsupported
  environments explicitly reported. No redesign or legacy deletion to hide gaps.

## Phase C — native cutover (blocked by UG)

- [ ] **C01** Native build/release and installer/uninstaller, desktop entry,
  service/autostart, upgrade and rollback. Preserve identity/config/history;
  test with isolated home and install prefix. Remove Python/typelib requirements
  from launch paths, not native GTK shared-library requirements.
- [ ] **C02** Default-native launch, CI and clean-environment proof: installed
  app starts and functions with no Python, PyGObject or PyO3 extension available.
  Verify flags, provider settings, login fixtures, history and tray lifecycle.
- [ ] **C03** Remove `rust-python/`, Python business fallbacks/UI/entrypoints,
  obsolete bootstrap code and dependencies. Port or retire Python-only dev tools
  and tests after equivalent native coverage exists; retain synthetic fixtures.
- [ ] **CG** Final source/dependency/install audit; native testing/release
  instructions and current screenshots; record no remaining Python runtime
  paths and completed rollback/upgrade evidence. Only now call the app fully
  ported and remove transitional opt-in documentation.

## Handoff record template

Use this for the active task above; append the corresponding evidence to AUDIT:

```text
Task/subtask:
Status: todo | active | blocked | verified/PR-pending | merged
Owner/session and date:
Branch / PR / observed merge commit:
Scope and changed paths:
Behavior/contract decisions (audit IDs):
Checks run, results, skips and environment limits:
Runtime/UI smoke path and fixture provenance:
Uncommitted work and exact blocker (if any):
Next exact command or implementation step:
```

### B08 handoff — 2026-10-30

Owner: current coding-agent session; branch `backend/b08-notification-policy-service`.
Status: verified and merged in PR #40 at `9d272fd810912133d0e42f35238dee1fc5e12a30`.
The branch had been rebased on `origin/main` at `93b62bb`; build 39 was assigned
for the PR. Dependencies B01/B02/B05 are merged. The
stateful API is
`codexbar_core::notifications::NotificationPolicy::observe(&[ProviderUsage],
&NotificationPreferences, now: DateTime<Utc>) -> Vec<NotificationEvent>`.
Typed variants are `QuotaThreshold`, `SessionExhausted`, `PredictivePace`, and
`CreditExpiry`; event data retains provider/account/window identity where used
by the Python policy. Unknown or placeholder usage does not rearm quota state;
known zero does. The API uses Rust DTOs only. The opt-in Python adapter runs it
after each successful updated snapshot and leaves OS delivery to GTK.

B10/B14 event contract: `rust_backend::event_channel()` returns an
`EventPublisher` and receiver backed by a 256-item bounded Tokio `mpsc` queue.
`publish_notification` awaits capacity, preserves event order with sequence
numbers, and returns `EventPublishError::ReceiverClosed` if the consumer is
gone. The separate watch channel remains latest-state/coalescing. B10 should
publish typed policy events through this channel alongside snapshots.

PR #40 merged at `9d272fd810912133d0e42f35238dee1fc5e12a30` from head
`1d0f396ca8d559af2ef0d0ad6e6ad9f70874ac9e`. GitHub run `41102664352` reports
`test` and `tray-dbus` successful. The owner reran the full workflow locally at
that exact head and captured the synthetic GTK screenshot embedded in the PR;
see AUDIT E049 for counts and scope. B08 is complete.

### B12 active handoff — 2026-10-30

Status: implementation rebased onto verified `origin/main`
`9d272fd810912133d0e42f35238dee1fc5e12a30`; build `0.82.0 (40)` is assigned.
The B08 merge and exact remote/local evidence are recorded in AUDIT E049. B12
keeps update checking in a typed, read-only Rust service with a 4096-byte
response bound, bounded timeout, sanitized error classes, and injectable URL /
fetch seams. GTK renders the service result only. Unicode decimal version
components (including Arabic-Indic and fullwidth numerals) retain Python parity;
superscript digits that pass `isdigit()` but fail `int()` produce a sanitized
invalid-marker result. The Python reference remains unchanged.

The rebase retained B08's notification event channel, policies, and bridge
adapter while adding B12's update module and PyO3 adapter. The integrated checks
and loopback-fixture GTK smoke passed (AUDIT E051); root-checkout drafts remain
untouched. PR #41 is open and linked to the orchestration thread. Its initial
required checks were in progress on the recorded head (E052); wait for fresh-
head results. Merge only after verifying main, exact head, reviews, mergeability
and normal GitHub merge conditions.
