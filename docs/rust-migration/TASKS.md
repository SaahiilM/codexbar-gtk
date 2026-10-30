# Migration tasks and current handoff

Read the [architecture and gates](README.md) and [audit trail](AUDIT.md) first.
Task IDs are stable: add sub-IDs when splitting a task; do not renumber completed
history. A checked box means **verified and merged**, not merely implemented.

## Resume here

| Field | Current checkpoint |
| --- | --- |
| Goal | Fully native Rust GTK4/libadwaita app; backend first, UI second |
| Current phase | B06 currency service; native UI implementation must wait |
| Last merged implementation | B05 PR #37 merged at `878d4b7`, build `0.82.0 (36)` |
| Planning change | [PR #18](https://github.com/SaahiilM/codexbar-gtk/pull/18), merged at `69c5496`, build `0.81.0 (17)` |
| Backend tasks completed after that baseline | B00, B01, B02a, B02b1, B02b2a, B02b2b1, B02b2b2a, B02b2b2b, B03, B04 and B05 merged |
| Active implementation task / owner | B06 currency service, owner: current coding-agent session |
| Active task | **B06** — currency catalog, conversion, TTL cache and bounded async HTTP refresh; [PR #38](https://github.com/SaahiilM/codexbar-gtk/pull/38), head `6245c64`, open and mergeable |
| Next domain slice | **B06** — observe both required checks; merge after they pass and orchestration confirms the slot, then continue with B07 CLI |
| Open external blockers | None known; task dependencies below still apply |
| Latest checks | B05 checks passed on head `d43b18f`; B06 local Rust/Python/GTK checks passed (AUDIT E037); PR #38 `test` in progress and `tray-dbus` queued at 17:20 UTC |
| UI validation | Rust-opt-in synthetic GTK SpendView displayed converted EUR values; [screenshot](screenshots/b06-spend-currency-synthetic.png) (AUDIT E037) |

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
GTK4/libadwaita typelibs are available locally through ignored `.deps/` (E017);
synthetic X11/Wayland widget previews succeeded. B04 is next: spend
normalization/aggregation. UI migration remains blocked by BG.
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

These checked tasks must be revisited under B15 for the final Rust-only
contract. Do not remove fallbacks simply because F01–F06 are checked.

## Phase B — backend (all pending)

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
| [ ] **B06** Currency service | B00, B05 | Port currency catalog, labels, conversion, TTL/cache load/write, single-flight refresh and offline fallback; inject HTTP/time; connect monthly pace and spend callers. Active on `orchestrated/luna-b06-currency`; build 37. |
| [ ] **B07** CLI service | B00 | Port executable discovery, argv/TZ handling, timeout/reaping, stdout/stderr/errors, JSON envelopes, usage/cost/sessions/config/hooks/plugins/account commands. Use fake executables, including failure and cancellation. |
| [ ] **B08** Notification policies | B01, B02, B05 | Port threshold transitions, session-exhaustion tracking, predictive pace cycles and credit-expiry deduplication. Rust owns state; tests use explicit clocks and accounts. OS notification delivery remains frontend/platform work. |
| [ ] **B09** Provider ordering and tray selection | B01, B02, B05 | Port visibility/order, automatic quota ranking and ETA trust/filtering; preserve deterministic ties, depleted quotas and placeholder exclusion. |
| [ ] **B10** Refresh controller | B02–B05, B07–B09 | Port polling/manual mode, forced refresh queuing, cancellation/shutdown, account collection, partial cost fallback, retained sessions/spend, history recording and snapshot/event publication. No I/O/callbacks under GUI locks. |
| [ ] **B11** Login/auth process service | B00, B07 | Port argv/browser request helpers, auth status and PTY login lifecycle; incremental ANSI/URL/prompt parsing, submitted input, timeout/cancel/reaping. Fake PTY tests only; no stored auth codes/URLs in audit. |
| [ ] **B12** Read-only update service | B00 | Port public VERSION parsing/comparison and bounded HTTP fetch; test invalid/oversized/network-failure responses. No code download/install behavior. |
| [ ] **B13** Extract backend work embedded in UI | B04–B12 | Audit all `ui/*.py` workers and policies: spend model grouping/time ranges/currency/partial-state presentation, tray summaries, settings CLI actions, launch-at-login actions, restart/update workers. Move non-widget responsibilities behind the Rust API; log remaining frontend-only behavior explicitly. |
| [ ] **B14** Full transitional backend integration | B06, B10–B13 | Python GTK uses a single Rust service facade and thin conversion/marshalling adapters. Settings actions and login flows use it too. Prove no Python subprocess/HTTP/polling/notification-policy backend remains. |
| [ ] **B15** Close original-port gaps | B01–B06, B14 | Audit F01–F06 edge/timezone/Unicode/numeric fallbacks and duplicated catalogs. Define/test Rust-only behavior and resolve all production fallback dependencies. Keep Python parity references until cutover. |
| [ ] **BG** Backend completion gate | B00–B15 | Rust-only headless end-to-end fake CLI/HTTP/PTY tests require neither Python nor GTK/PyO3; transitional GTK fixture smoke passes; review residual-Python inventory and record gate decision in AUDIT. |

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

B05/B07/B12 can proceed after B00 independently of payload parsing. B11/B13 are
not optional just because their Python files sit near presentation code. Do not
start the UI crate merely because several backend slices are green.

## Phase U — native GTK4/libadwaita UI (blocked by BG)

- [ ] **U01** Native application/bootstrap crate, direct backend connection,
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
