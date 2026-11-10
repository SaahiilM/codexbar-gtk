# Migration tasks and current handoff

Read the [architecture and gates](README.md) and [audit trail](AUDIT.md) first.
Task IDs are stable: add sub-IDs when splitting a task; do not renumber completed
history. A checked box means **verified and merged**, not merely implemented.

## Resume here

| Field | Current checkpoint |
| --- | --- |
| Goal | Fully native Rust GTK4/libadwaita application with verified packaging and legacy runtime removal. |
| Current phase | BG passed and U01–U08 implementation merged. UG **NOT PASSED**; Python default. |
| Last observed merge | PR #102 merged normally at `07e6fb2e6d9ed40d517c8c89b55c10e83466b049` (build 101). Its three required checks all succeeded on exact head `a4512a45f43992ba149ceae5aef0f4c7140e0800` in run `42914850286`; no reviews/comments/threads were reported. This is base-only evidence for BUILD102, not CI for this branch. The merge did not accept UG or C gates. |
| Active implementation | BUILD102/E205 private native installer command-target proof hardening; branch `orchestrated/luna-native-service-proof`, based on PR #102 merge `07e6fb2e6d9ed40d517c8c89b55c10e83466b049`. Implementation commit `3153fac55f8bafb8cfbb6596b0db4cc114403028` and full local private proof passed; no PR or branch CI is claimed. |
| Installer/runtime verification | E198 records the merged build-95 installed-prefix/Python-free runtime proof. E199 records prior local 13-case activation smoke evidence in a Python-free container; its first attempt lacked `file`, and the portable `od`/`ldd` check passed. These component results do not pass C02 or authorize cutover. |
| UI acceptance | E195 records one Display action; E200 records seven guarded Settings actions and three tab transitions. Broader Wayland controls/navigation remain open. UG is **NOT PASSED** and Python remains the default; see `UG_GATE.md`. |
| Next | Root owns review and publication for BUILD102/E205. The proof remains command-target-only; systemd activation/restart policy and autostart are untested. UG remains **NOT PASSED**, Python remains default, and C01–CG/cutover are not accepted. |

### BUILD102/E205 — bounded private installer command-target proof

Owner: `orchestrated/luna-native-service-proof`, based on observed PR #102
merge `07e6fb2e6d9ed40d517c8c89b55c10e83466b049`. Build 102 keeps marketing
version 0.82.0; build 99 and build 102 are component versions within that same
supported upstream marketing version. The private synthetic smoke is labeled
build 99 → build 102 → build 99 and proves installed command targets, process
identity, refresh/quit actions, backup/rollback and preservation only. Systemd
activation/restart policy and desktop autostart remain untested. E205 records
the actual source/artifact identities, checks and exact command-target scope.
Focused CI was not added: it would need a historical source fetch/build plus
another runtime Docker pass. Reproduce in a Docker-enabled environment with
the pinned source available using `scripts/smoke-native-service.sh`; Root owns
review and publication. UG remains **NOT PASSED**, Python remains default, and
C gates are not accepted.

### BUILD101/E204 — isolated private Weston interaction smoke

Owner: current `orchestrated/luna-isolated-wayland-acceptance` branch, based on
merged PR #101 build-100 commit `284ce9a`. The exact PR #101 head
`68c67ed47202a2cb98d4694ed89aa09a4e98865f` passed all three checks in run
`42891020528`; that is base-only evidence. This slice hardens the bounded
Wayland runner's process-tree ownership, adds a real timeout child/grandchild
cleanup regression, and adds its private Weston smoke to CI using the already
built native executable. E204 accepts only the General refresh-on-panel-open
control, the Dashboard route, Usage & Spend route, and 7-day selection through
GAction/AT-SPI on private Weston. This is not physical input, KDE placement,
portal behavior, keyboard parity or full UG acceptance. Python remains default.
Root owns review and publication. See AUDIT E204 for exact local evidence and
checks; branch CI has not been observed.

### Focused upstream compatibility claim — UP084-CLAUDEPLATFORM-LOGIN

Owner: current `orchestrated/luna-upstream084-claudeplatform-login` session,
based on supplied build-99 `41d2fcf982aef52cd86a64cb769176b494abb63c`.
**Status: implemented and locally verified; local commit only.** Build 100/E203 is reserved.
The pinned upstream v0.84.0 contract is `codexbar config login --provider
claudeplatform --stdin --json`: read stdin to EOF as strict UTF-8, let the CLI
normalize/validate and persist the one submitted cookie candidate, and expose
only sanitized status to the app. No app-side provider HTTP/authentication,
credential persistence, fallback candidates, secret-bearing diagnostics or
generic preferences are in scope. Use a separate bounded one-shot process
operation, keeping existing Codex/Claude PTY login unchanged. The Settings
entry is ephemeral and cleared on every terminal state. Python remains the
default and has a stdlib parity route that does not require the extension. The
native GTK Settings flow uses a dedicated joined process actor; no secrets enter
the preferences actor or persisted settings. See E203 for exact checks and the
X11-only UI evidence. Marketing version stays 0.82.0; UG remains **NOT PASSED**.
Root owns architecture/review and publication.

### Focused upstream compatibility claim — UP084-CLAUDE-WARNING

Owner: current `orchestrated/luna-upstream084-claude-warning` session, based
on merged build-98 commit `5e033f0`. **Status: implementation and local
rendered-runtime verification complete; local commit only.** Build 99/E202 is reserved. The
upstream v0.84 contract is a Claude-only typed warning derived from the exact
details row ID `claude-model-breakdown`; its status text is diagnostic input
and must not be shown or serialized. Preserve unrelated details and both quota windows.
Root owns review, push, PR, merge and gates. ClaudePlatform stdin login is a
separate slice. Marketing version stays 0.82.0, Python remains default, and UG
remains **NOT PASSED**.

### Focused upstream compatibility claim — UP084-PROVIDERS

Owner: current `orchestrated/luna-upstream084-providers` session, based on the
observed PR #97 merge `44e5c9b`. **Status: implementation and local verification
complete; build-97 `origin/main` is merged normally.** This is
not a C03 gate task. The v0.84.0 tag resolves to `5bebf9a05e68059eae11d5031c7239f1aa1d49ef`;
its manifest appends OpenDesign, SiliconFlow and Tripo, in that order. The
verified descriptors record OpenDesign's `open-design` alias and dashboard
URL, SiliconFlow/Tripo balance-only flags, dashboard URLs, Tripo status URL,
history/burndown flags, and OpenDesign menu-bar metrics. Prior 110 provider
entries and their relative order are preserved; Rust and Python now contain
113 entries and seven aliases. Matching tagged monochrome SVGs are bundled
with MIT attribution/provenance; no brand-color files exist for these IDs.

The native code uses the existing generic CLI payload, card, tray and settings
paths; it adds no provider fetching or credentials/login behavior. Synthetic
dashboard data and disabled `config providers` rows cover all three IDs. Rust
tests cover normalized names/colors, descriptor details, generic cards/tray,
asset aliases and brand→monochrome→initial fallback.

Local checks on the implementation after the normal build-97 merge: rustfmt
passed for core/backend/gtk; core 87 tests and Clippy passed; backend 87 tests
(86 unit + 1 integration) and Clippy passed; GTK 40 tests passed with two
display-only tests skipped by default and one negative-loader test skipped by
its absent-loader precondition, plus GTK Clippy passed. Both display tests were
run separately under private X11/Xvfb with private D-Bus and passed. Synthetic
dashboard and Settings smokes passed; personally inspected captures show the
three provider cards/artwork and three disabled Settings rows. Python default
mode passed 305 tests with 21 skips; Rust opt-in passed 305 tests without
skips. The Rust extension was built using the atomic build helper. Two reviewed synthetic X11 captures are tracked under
`screenshots/build98-providers-xvfb/`; no Wayland, real provider account, provider endpoint,
credential or real login was used. No exact-head CI or gate acceptance is
claimed.

BUILD98/E201 is authorized for this slice after PR #98 merged build 97 at
`f40307db189ce7fba97a0cc5da1aabd8c73b5f7c`; that `origin/main` is merged
normally at local merge commit `44e485f`. Marketing remains 0.82.0 until the
warning/login contracts are separately verified. Root owns publication
and gate decisions; UG remains **NOT PASSED**, Python remains default.


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

## Phase U — native GTK4/libadwaita UI (implementation merged; UG evidence active)

- [x] **U01** Native application/bootstrap crate, direct backend connection,
  GTK main-context dispatch, single-instance/command-line behavior and version
  metadata. Preserve `--panel`, `--settings`, `--about`, and `--page` behavior.
  Merged in PR #56 at `3eea06f`; see E089. U02 replaces the dashboard
  placeholder; U03 adds the compact panel. U04/U05 routes remain placeholders.
- [x] **U02** Dashboard, provider cards, quota meters, reset/pace/credit chips,
  charts/history and burndown presentation (`window.py`, `cards.py`).
  - [x] **U02a** Native dashboard overview and provider cards/meters/chips,
    with loading, empty, error and refresh states. Build 57 on
    `frontend/u02a-dashboard-build57`; verified and merged in PR #58 at
    `549908e`; exact head `c2a3078` passed both required checks and synthetic
    Wayland/GTK evidence is recorded in E090/E091.
    Projection consumes B10 snapshot fields and preferences; GTK only renders.
  - [x] **U02b** History sparklines/detail charts, history-derived burndown,
    quota warning/workday marks and daily target labels. Active build 58 on
    `frontend/u02b-history-build58`; verified and merged in PR #59 at
    `81b7b8f`; exact head `89ae294` passed both required checks. Projections use
    the B10 snapshot history and existing Rust chart/pace policy. Charts expose
    accessible descriptions and units; unknown current usage produces no trend
    or burndown, while known zero remains a real 0%. Rust and Python now both
    skip new unknown/placeholder history writes. Older JSONL rows remain
    readable, but their original format lacks knownness, so prior unknown-zero
    records remain ambiguous and cannot be repaired without discarding history.
    See E093/E094.
  - [x] **U02c** Python default history writer parity and final U02 acceptance,
    `frontend/u02-final-acceptance-build59`, build 59; merged normally in PR #60
    at `317078a`. Exact head `b2fc92c` passed `test` and `tray-dbus` in run
    `41314701763`. Both Python and Rust writers skip unknown, placeholder and
    non-finite observations while retaining known zero. The legacy JSONL
    knownness ambiguity remains documented in E093/E097. Fresh Xvfb smoke was
    unavailable (`xvfb-run`, `Xvfb`, `xdotool` missing); #60 changed no GTK
    rendering and prior synthetic #58/#59 captures were visually inspected.
- [x] **U03** Compact panel, dismissal, anchoring and Wayland/X11 placement
  (`popup.py`, `x11_position.py`); preserve dashboard/settings navigation.
  Merged normally in PR #61 at `51480af`; exact head `781aacc` passed `test`
  and `tray-dbus` in run `41324106655`, including both native GTK smokes
  (E101). Use a separate `PanelView` over shared
  `DashboardModel`, refresh it on backend
  sequence changes, hide it before Dashboard/Settings/About actions, and
  support Escape/close/toggle dismissal
  without assuming focus-loss. Wayland uses compositor placement;
  `PanelAnchor` remains optional until U06 SNI. X11 uses the actual GDK/X11
  surface and selected monitor work area, with an EWMH work-area fallback if
  GDK reports no monitor geometry. See E093, E097 and E098.
  Preserve central `app.settings`/`--settings`, `app.about`/`--about`, and page
  navigation routes so U04/U05 can replace their placeholders independently.
  See the U03 handoff in E093 and closeout E101.
- [x] **U04** Usage & Spend and Sessions pages, heatmap interaction/tooltips,
  filters and empty/error/loading/partial states (`spend.py`, `sessions.py`).
  Completed on build 61 in PR #62 from `orchestrated/luna-u04-spend-sessions`.
  Session status is optional for old JSON and carries sticky
  successful-scan state plus a sanitized last error; failures retain rows.
  Heatmap days bucket duplicate provider rows, preserve unknown versus explicit
  zero, and propagate known subtotals/partialness to weeks and cumulative
  labels. Cost-history coverage does not imply token coverage. Python's
  absent-to-zero heatmap behavior is intentionally improved. Native page and
  keyboard/pointer accessibility work must retain central navigation. U05 owns
  Settings and all settings/CLI-path/timezone writes; U04 dispatches the central
  settings action only. Final PR head `ed69eabbb92bd74cccee90c0b61083fbf3f11760`
  passed `test` and `tray-dbus` in run `41327529193`; PR #62 merged normally at
  `82b9f254e351ad983d3827d87c78c2de29ec92e9`, now live main. See E101–E104.
- [x] **U05** Every preferences pane, provider/source/API-key controls,
  hooks/plugins, login dialog, import/export/reset, acknowledgements and About
  (`settings.py`, `login_dialog.py`). Completed on build 62 in PR #63, merged
  normally at `0c298afc0c4cd24bd8fd13b6979b06758dca1f21`. The native
  Settings actor serializes preference mutations and CLI reconfiguration;
  import is a known-key transactional patch, reset is a transactional replace,
  and committed operations distinguish queued refresh from closed-channel
  partial success. Reject nonempty invalid imported `cliPath` intentionally;
  empty/default path resolution follows startup. Import/reset do not change
  autostart. API keys and login events remain transient. Local tests, runtime
  smoke and synthetic screenshots are recorded in E105. The first exact-head
  `test` check exposed a runner-only `rg` dependency; E107 records its removal,
  a deterministic Settings window size for pointer checks, and a full smoke
  pass with `rg` excluded from `PATH`. Final exact head `562a8a7` passed
  `test` and `tray-dbus` in run `41333765485`; PR #63 merged normally at
  `0c298afc0c4cd24bd8fd13b6979b06758dca1f21`, live main (E108).
- [x] **U06** StatusNotifierItem and dbusmenu, icon/pixmap export and all signal
  signatures; host re-registration, refresh/restart/settings/quit actions and
  updated tooltips. Port the private-bus regression coverage from PR #15.
  Implementation and local verification are ready for PR on
  `orchestrated/luna-u06-tray`, build `0.82.0 (63)`, based on verified live U05
  merge `0c298afc`. Activation metadata may reach X11 panel placement only when
  its coordinate space is valid; Wayland remains compositor-placed. Explicitly
  unregister/release bus resources and coordinate shutdown's no-registration
  invariant with U07. PR #64 merged normally at
  `678b6b9cf3e10e5b9cd926cb488b5ffbf62ce1da`; exact head
  `9bc166138b0b8551bd8bb4471936991a4a5365ab` passed both required checks in run
  `41337858935`. Its synthetic screenshot is
  `screenshots/u06-native-sni-dashboard-xvfb.png`; no reviews or review threads
  were present. `iconPercent` raster rendering is reserved for U08's icon
  generation work; current SNI pixmaps use the typed meter projection (E111).
- [x] **U07** Desktop notification delivery, browser/terminal/file-dialog
  adapters, display readiness, restart and launch-at-login integration; verify
  shutdown leaves no workers, processes or tray registrations behind. PR #65
  merged normally at `e373e019f7701f5f3a5e204153b7163763abac90`; exact head
  `70bba1c52562c7670916a51a28fb9f37a29cd3ec` passed `test` and `tray-dbus` in
  run `41340840860`, with no reviews or review threads (E114).
- [x] **U08** Provider artwork/assets, theme/CSS, icon generation, Cairo/GTK
  rendering, accessibility, keyboard navigation and display scaling. Locally
  implemented and verified on `orchestrated/luna-u08-assets`, build `0.82.0
  (65)`, based on U07 PR #65 merge `e373e019f7701f5f3a5e204153b7163763abac90`
  (E114–E118). PR #66 merged normally at
  `5de83def98ad5ebd09035ee9120698fbf710541c`; exact head
  `fb89f0b6c702dff92992916e14951b385f5189bf` passed `test` and `tray-dbus` in
  run `41345048163` (E119). Keep rendering pure over `TraySummary` and pass
  generated pixels through the unchanged
  `TrayPresentation.pixmap`; do not change U07 display readiness,
  restart/autostart, shutdown or tray lifecycle. This merge does not pass UG.
- [ ] **UG** Full feature/interaction parity against README and Python app;
  fixture screenshots and functional checks on Wayland and X11, with unsupported
  environments explicitly reported. Status is **NOT PASSED**. Remaining UI
  actions and environment gaps are listed in [UG_GATE.md](UG_GATE.md) and E120.
  No redesign or legacy deletion to hide gaps.

### U05-UG1 handoff — build 67 Settings interaction closeout

Owner: current U05 session; branch `orchestrated/luna-u05-settings-interactions-build67`.
Status: merged normally in PR [#68](https://github.com/SaahiilM/codexbar-gtk/pull/68)
at `233ce8fc5a7a616983d066a5d18184e5236d7fac`, build `0.82.0 (67)`, based on
live main/PR #67 merge `ba0fb7e1573715b9a8f8070246d933a9607f2665`.
Initial PR head is `340daceace0c9eda20a9a3110c65086fce72bac0`.
PR #67 was UG evidence only; it did not pass UG. Its final head
`e6115c4bd3d8a9a8e8de7648c07aebe7cb321701` passed `test` and `tray-dbus` in
run `41358051892` before normal merge (E122).

Scope completed locally: provider enable/source/API-key Apply and synthetic
sign-in; Hooks enabled and read-only rules; Plugins populated/empty/loading/error
read-only states; Advanced CLI-path Apply; import/export/reset selection,
confirmation and outcomes; update-check action and result through an injectable
loopback request; remaining General show-on-start/refresh-interval and Display
controls. Use temporary homes, synthetic CLI/provider/auth fixtures and
sanitized results. Never persist, log, or capture API keys, login codes, or
auth events. Preserve the U05
SettingsActor contract, Python default, central `app.settings` route, import
patch/reset replace semantics, and the rule that import/reset do not change
autostart. Full Xvfb/private-D-Bus checks and 36 captured synthetic images are
recorded in E123. The login completion capture is taken only after the GTK
handler reports the visible success result. The isolated runtime uses GTK
4.14.5 and libadwaita 1.5.0; the test wrapper assigns its temporary
`XDG_RUNTIME_DIR` before starting D-Bus.

No live Wayland interaction was performed: `wtype` remains unsupported by the
current compositor as recorded in E120, and the serialized Wayland slot was
not used. UG remains **NOT PASSED**; the local panel Xvfb focus/SNI issue also
remains. After PR #68's exact-head CI/review and ordinary merge, the coordinator
released U04's queued panel acceptance on build 68. Keep Python as the default
and C01 blocked until UG passes.

### U04-UG2 handoff — build 68 SNI panel parity

Owner: current U04 session; branch `orchestrated/luna-u04-panel-parity-build68`.
Status: active, based on live main/U05 PR #68 merge
`233ce8fc5a7a616983d066a5d18184e5236d7fac`. The merged PR #68 exact head
`34367d63033ae951c29f0b7abe9fe1525855e82a` passed `test` and `tray-dbus` in
Actions run `41368907372`; the U04 branch was created from that exact live main.
Build `0.82.0 (68)` is assigned by the coordinator.

Scope: match Python's SNI methods. `Activate` toggles and refreshes only when it
opens the panel and `refreshAllProvidersOnMenuOpen` is true. `SecondaryActivate`
and `ContextMenu` ensure the panel is visible idempotently and refresh on every
event when enabled. Preserve valid activation coordinates for X11 anchoring and
compositor placement on Wayland. Exercise the hidden/visible × three methods ×
preference-on/off matrix with synthetic CLI refresh counts, actual SNI D-Bus
routing, X11 placement and focus-before-Escape behavior. Keep U03 central Gio
actions, U05 settings ownership and Python as the default. UG remains **NOT
PASSED**; do not claim Wayland pointer/keyboard interaction without direct
evidence.

Implementation and local verification were complete before PR creation. PR #69
then had initial exact-head runs `41371521591` and `41372418162`, which each had
`tray-dbus` pass and `test` fail in Settings chooser automation on heads
`aecf96b` and `ca737bc`; E131 records the two harness issues and corrections.
Starting xfwm4 first fixed chooser mapping; replacing hard-coded accept-button
coordinates with the focused chooser's Return action now passes the complete
local Settings smoke. The final exact head
`ef5f8ebd96ceb716ea8529f85f81d119d41e24fc` passed `test` and `tray-dbus` in
run `41373288090`, had no reviews or inline review threads, and merged normally
at `ba0338091f28c458432a469d8fe1b973facf1b4e` (E132). The real Xvfb matrix
passed both preference values and all six hidden/visible method cases; the
broader GTK Gio, Dashboard, Usage/Sessions and Settings smokes passed. Rust and
Python tests, strict Clippy, extension build and display-dependent GTK
accessibility tests passed. Three synthetic panel captures were visually
inspected; the live Wayland run delivered SNI events and captured a panel with
compositor-owned placement. `wtype` remains unsupported. This is a completed
U04 handoff and does not close the remaining Wayland UI action matrix.
See E130–E132 and [UG_GATE.md](UG_GATE.md).

### U05-UG2 handoff — build 69 Wayland interaction evidence

Owner: current U05 session; branch `orchestrated/luna-u05-ug-evidence-build69`.
Status: live-session evidence and local checks complete; focused PR, exact-head
checks and merge pending. Based on live main/U04 PR #69 merge
`ba0338091f28c458432a469d8fe1b973facf1b4e`; build `0.82.0 (69)`. The exact
head `ef5f8ebd96ceb716ea8529f85f81d119d41e24fc` passed `test` and `tray-dbus`
in run `41373288090`; no reviews or inline review threads were present (E132).

Scope: assess remaining UG Wayland page/action parity with synthetic fixtures,
including Settings/Hooks and Usage & Spend interactions, central route/navigation,
and any product defects found. Build 69 captured Settings General; neither the
private AT-SPI action attempts nor a one-shot KWin fake-input click produced a
verified visible action/result. This is an environment/input-path evidence gap,
not a product pass or confirmed product failure. The application and Spectacle
ownership were checked; isolated HOME/config/cache were used; unrelated session
apps were untouched; the fixture, private AT-SPI bus, and capture processes were
cleaned up and the live slot released. The local Rust/Python and Xvfb check set
passed, including a selected-path Settings chooser smoke (E134). See E133 for
Wayland input limitations. Keep Python as the default;
UG remains **NOT PASSED** until every acceptance criterion is evidenced.

### U05-UG3 handoff — build 70 RemoteDesktop portal interaction evidence

Owner: current U05 session; branch `orchestrated/luna-u05-wayland-portal-build70`.
Status: local evidence complete; focused PR/checks remain pending. Base is live
main at U05 PR #70 merge
`6fc6833059cf4ac1808f7f51fe16bcff66eb7867`; build `0.82.0 (70)`. PR #70 exact
head `800dc57915216f90bfec18178ef26c7261299045` passed both required checks in
run `41377674020` and merged normally (E135).

The current KDE session exposes `org.freedesktop.portal.RemoteDesktop` v2 with
keyboard/pointer available (`AvailableDeviceTypes=7`); KDE's portal backend is
installed and active. Direct launch produced an unidentifiable consent prompt,
which was closed without approval. The test then used systemd's documented
`app[-launcher]-<ApplicationID>-<random>.scope` naming convention and a
temporary, `NoDisplay=true` desktop entry for the exact native binary. This
produced a prompt identifying “CodexBar GTK build 70 synthetic interaction
test.” It requested only keyboard+pointer, with `persist_mode=0` and no
ScreenCast/clipboard. No approval arrived during the portal's 360-second
request window; `Start` timed out, the request session closed, and no input
event was sent. The temporary desktop entry and fixture HOME were removed.
Captures prove Settings startup and consent-prompt presentation only. A future
retry requires fresh explicit approval; after approval, keep the synthetic
Settings window as the verified target, send bounded input, verify visible GTK
state plus fixture CLI/preferences effect, then close the session and confirm
cleanup. Python remains default; UG is **NOT PASSED**.

### U05-UG4 handoff — build 71 fresh RemoteDesktop attempt

Owner: current U05 session; branch `orchestrated/luna-u05-wayland-portal-build71`.
Status: this attempt is blocked pending diagnosis of the native app exit; the user approved the named KDE dialog and the live RemoteDesktop `Start` returned `Response=0 devices=3`, but the Settings child had exited before input. The session and fixture were cleaned and the desktop slot released. Base is live main at U05 PR #71 merge
`2d3901067b0a6e15217fa0ca63cd712527363b4e`; build `0.82.0 (71)`. PR #71's
exact head `7bfeb868bdb7ed3be75a25ed5364efbfa90756f0` passed `test` and
`tray-dbus` in run `41381485242`, with no reviews or inline threads (E137).

The user/coordinator confirmed the sole live desktop slot. The request named
the synthetic app and asked only for pointer+keyboard with `persist_mode=0`; no
ScreenCast or clipboard was requested. The user approved and portal `Start`
returned `Response=0 devices=3`, but the native Settings child had exited before
input. No keyboard/pointer notification or UI action was sent. No coredump was
present; the app log contained only libEGL DRI warnings, so the exit cause is
unknown. The portal session, driver, temporary desktop entry and fixture HOME
were cleaned. D-Bus app/SNI/Spectacle names are unowned; the unrelated
`codexbar-linux --usage` process and Chromium global-shortcuts portal session
remain untouched. The slot is released. The captures are capture-only and do
not pass UG. Next step: diagnose the child exit, coordinate a fresh sole-owner
slot, and obtain fresh one-time portal consent before retrying. Python remains
default; UG stays **NOT PASSED** until the full acceptance matrix is evidenced.

### U05-UG5 handoff — build 72 bounded lifecycle diagnosis and portal retry

Owner: current U05 session; branch `orchestrated/luna-u05-wayland-portal-build72`.
Build `0.82.0 (72)`, based on live main/U05 PR #72 merge
`4b2d25ed8e566efb27d335ce903ec29e2b32a333`. E139 records #72's exact-head
checks and preserves its initial chooser failure plus successful same-head
rerun.

The bounded pre-consent fixture ran with synthetic HOME/config/cache and fake
CLI. Its Settings PID and application/SNI D-Bus owner matched; it stayed alive
for the full 360-second bound and exited `rc=0` only after the driver's
controlled Gio Quit. The app log contained only two libEGL render-device
warnings. This does not explain the earlier build-71 child exit.

The first build-72 portal runner's stdin was already EOF after `Start` returned
`Response=0 devices=3`; it closed the portal session and intentionally quit the
app without sending input. A second run exposed a desktop-entry ID mismatch in
the prompt identity and was cancelled by stopping only that owned scope. The
corrected temporary desktop entry matched the systemd app ID. The fresh visible
KDE dialog named “CodexBar GTK build 72 synthetic interaction test” and
requested only pointer+keyboard (`types=3`, `persist_mode=0`); it requested no
ScreenCast or clipboard. After the user approved, portal `Start` returned
`Response=0 devices=3`. The socket-controlled driver sent one keyboard
`Ctrl+R` to the active Settings window. The synthetic CLI fixture recorded four
new calls: `usage`, `cost`, `sessions`, and `--version` (8 before, 12 after).
No pointer event or Settings preference mutation was tested.

The Settings screenshot is a crop of the active synthetic window from a
compositor capture; Spectacle's active-window mode returned a black image after
the action, so that frame was excluded. The screenshot does not itself prove
the action; the portal event and fixture CLI delta do. The owned portal session
was closed, app quit with `rc=0`, and app/SNI/Spectacle names were unowned after
cleanup. The unrelated `codexbar-linux --usage` process and Chromium portal
session were left untouched. UG remains **NOT PASSED**, Python remains default,
and C01 remains blocked.

### U07 handoff — 2026-11-01

Owner: current coding-agent session; branch `orchestrated/luna-u07-os-integration`.
Status: implementation complete locally; focused PR/CI/merge pending, build
`0.82.0 (64)`, based on verified live U06 merge
`678b6b9cf3e10e5b9cd926cb488b5ffbf62ce1da`. U06 PR #64 final head
`9bc166138b0b8551bd8bb4471936991a4a5365ab` passed `test` and `tray-dbus` in run
`41337858935`, merged normally at 2026-11-01 18:46:34Z; no reviews or review
threads were present. U06's synthetic GTK dashboard capture is
`screenshots/u06-native-sni-dashboard-xvfb.png` (E111).

Scope: deliver typed backend notifications on GLib; finish browser, terminal
and file-dialog OS adapters; preserve display readiness, restart and the U05
launch-at-login settings actor; make shutdown explicitly cancel and join
backend/settings/login workers, reap child processes and invoke U06's
idempotent tray teardown. Keep the renderer API and `TrayPresentation`
boundary independent of lifecycle for U08. Keep Python as the default until
UG. The initial claim is superseded by implementation evidence E113;
exact-head CI/review/merge evidence remains pending.

### U08 handoff — 2026-11-01

Owner: U08 implementation owner; branch `orchestrated/luna-u08-assets`.
Status: merged. PR #66 merged at
`5de83def98ad5ebd09035ee9120698fbf710541c` on build `0.82.0 (65)`, based on
U07 PR #65 merge `e373e019f7701f5f3a5e204153b7163763abac90`. Exact PR head
`fb89f0b6c702dff92992916e14951b385f5189bf` passed `test` and `tray-dbus` in
run `41345048163` (E119).

Scope: embed the existing licensed provider icon catalog; preserve brand-first,
monochrome-accent-tint and initial fallback behavior; render SNI meter or
`iconPercent` pixmaps from `TraySummary` using Cairo; populate the unchanged
`TrayPresentation.pixmap`; make requested raster dimensions an input. Add shared
GTK theme classes, responsive dashboard summary tiles, decorative accessible
artwork with textual provider names, and keyboard page/refresh/quit actions.
U07 retains display readiness, restart/autostart, shutdown and tray ownership.
Do not redesign screens or change the Python default before UG.

Exact implementation checks and screenshots are in E115–E118. The 2× Wayland
capture path remains unusable on this host; default-scale Wayland passed. U08
merge does not pass UG. See [UG_GATE.md](UG_GATE.md) and E120 for the full
interaction matrix, local smoke failures and remaining blockers. Python remains
the default.

### UG handoff — 2026-11-01

Owner: current coding-agent session; branch `orchestrated/luna-ug`, build
`0.82.0 (66)`, based on live main/U08 merge
`5de83def98ad5ebd09035ee9120698fbf710541c`. Status: **ACTIVE — NOT PASSED**.
All U01–U08 implementation PRs have merged. The build-66 PR is limited to
fixture-driven Xvfb coverage, inspected evidence, version/build/changelog and
the auditable gate handoff; no UI/backend contract change is needed by dependent
threads.

The expanded Settings and Spend/Sessions Xvfb smokes passed after rebuilding
the build-66 native binary. A synthetic notification service verifies delivery
over the private D-Bus session. Actual default-scale KDE Wayland Sessions and
Spend fixture captures passed visual review; their stale/error and forced-2×
black captures were excluded. The current compositor rejects the `wtype`
virtual-keyboard protocol, so Wayland pointer/keyboard action coverage remains
open. Local Xvfb panel SNI/focus timeouts remain recorded alongside one
independent local pass and exact-head #66 CI success; they are not treated as a
repeatable pass. See E119/E120 and `UG_GATE.md`.

PR #67's first exact-head CI run `41357117572` failed only the native Settings
launch-at-login removal assertion on head `209e54e0160a4dde85d60c51cd581d0c05a7555a`.
The complete local Settings rerun passes with explicit `launchAtLogin=true`
and `false` synchronization plus the desktop-entry-removal assertion; the
failure and fresh-CI handoff are recorded in E121. Do not merge until the
corrected live PR head's required checks and review pass.

Remaining acceptance work: fixture GTK actions for provider enable/source/API
key/login, import/export/reset, update-check, and the remaining General/Display
controls; exercise the Hooks switch on Wayland or record why the session cannot
provide input; cover or explicitly disposition the Plugins empty/loading/error
list states (there is no plugin mutation action); complete or explicitly
justify the Wayland per-action matrix; resolve or disposition the flaky local
panel smoke.
Do not change the Python default or mark UG passed until this matrix is complete.
Then proceed to C01 isolated-prefix/home upgrade and rollback, C02 no-Python /
PyGObject / PyO3 proof, C03 removal only after equivalent coverage, and CG final
audit. C01 package checks must include `librsvg2-common`.

## Phase C — native cutover (blocked by UG)

- [ ] **C01** Native build/release and installer/uninstaller, desktop entry,
  service/autostart, upgrade and rollback. Preserve identity/config/history;
  test with isolated home and install prefix. Remove Python/typelib requirements
  from launch paths, not native GTK shared-library requirements.
  Additive prototype (E193, branch `orchestrated/crouton-native-cutover-prep` stacked on merged PR92
  at `b69a984`, draft PR93, tentative build 93, UG-gated cutover unchanged): `scripts/build-native.sh`
  (prebuilt artifact, separate from install), `scripts/install-native.sh` +
  stage templates `scripts/native/stage/` (`--activate` only writes canonical
  `codexbar-gtk.desktop`/`codexbar-gtk.service` with `.pre-native` backup and
  manifest ownership; default writes prefix binary + manifest only), atomic
  rename swap, safe quoting for spaced paths, ownership-aware uninstall
  preserving pre-existing non-native files, default NO service/autostart
  registration and no overwrite of Python entry/unit. Upgrade/rollback uses
  distinguishable debug/release ELF artifacts asserting sha256 on disk and
  installed; byte-preservation through install/uninstall, runtime history
  compatibility not byte-identical through runtime. `runtime_deps.txt` is
  documentation-only (no `Depends`, no invented `codexbar` apt package).
  Linkage inspection only (`python_free_linkage.rs`, C02 unproven) plus
  smoke ELF/process evidence. SVG loader negative test separate
  (`svg_loader_negative.rs`, ignored; desktop validation separate).
  C03 deletion mapping and CG audit not yet done; do not claim C gates accepted.
  D2: binary retains `codexbar-gtk-native` name.
  Investigation (E187, 2026-11-06; research-only, build 86, no version bump):
  "blocked by UG" applies to the cutover, not the installer mechanics —
  the design below can be reviewed now while live UG runs proceed, but do
  not merge or flip any default until UG passes. Present today: shared
  identity `com.steipete.CodexBarGTK` (Python `APP_ID` == Rust
  `APPLICATION_ID`); identical config/history paths
  (`~/.config/codexbar-gtk/settings.json`, `history.jsonl`); CLI-surface
  parity (`--settings`/`--about`/`--panel`/`--page`); CI native build
  (`cargo build --locked --bin codexbar-gtk-native --manifest-path
  rust-gtk/Cargo.toml`, exit 0, dev profile, with `librsvg2-common`);
  provider assets embedded by `rust-gtk/build.rs`. Missing (new C01
  slice M1–M8): (1) single-command native build/install script;
  (2) native desktop entry (`com.steipete.CodexBarGTK.desktop`
  recommended) whose `Exec` points at the installed binary;
  (3) native autostart + systemd unit (keep `codexbar-gtk.desktop`
  autostart filename — `rust-backend/src/settings.rs:autostart_file` reads
  it — tray-before-plasmashell order, `Slice=app.slice`);
  (4) install/uninstall + isolated-prefix test (synthetic HOME, fake CLI,
  settings/history survive install and uninstall);
  (5) upgrade/rollback design (build N → N+1 over same prefix, atomic
  rename swap, no config migration, rollback = reinstall N);
  (6) remove Python/typelib from launch paths (`run.sh`, installed
  launcher, desktop `Exec`, `ExecStart`, autostart all exec the binary
  directly — no `python3`, `PYTHONPATH`, `GI_TYPELIB_PATH`, or `.deps`
  copies);
  (7) runtime-dep declaration incl. `librsvg2-common` (not a
  "Recommended" package);
  (8) installed-prefix runtime smoke (beyond cargo-output smokes).
  Precise first slice: add opt-in `scripts/install-native.sh`
  (release build → `$PREFIX` layout modeled on `scripts/install.sh`,
  all artifacts point at the binary, Python untouched and still default),
  plus an isolated-prefix upgrade/rollback smoke
  (`scripts/smoke-native-install.sh`) asserting synthetic settings/history
  survival across install → upgrade → uninstall. Do not touch `run.sh`,
  `scripts/install.sh`, `scripts/bootstrap-deps.sh`, or
  `scripts/build-rust-core.sh` in that slice; do not rename the app id or
  move config/history paths; do not flip the default launcher. Full
  inventory and rationale: AUDIT E187.
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

### U05-UG6 handoff — build 74 synthetic Wayland pointer and preference action

Owner: current U05 session; branch
`orchestrated/luna-u05-wayland-pointer-build74`, provisional build `0.82.0
(74)`, based on observed live `origin/main` at U05 PR #74 merge
`87467ce5eec475f153466c6f87866d22c723a09a` (E145). **Status:
blocked/partial.** PR #74 exact head `5c50b403bb0b90e83e48e15b99262242a0fc1682`
was based on `cbdcc129ab4ac3ec5d6f3a8ef805567f96d354ff`; Actions run
`41525444941` passed `test` and `tray-dbus`, with no submitted reviews or
inline review threads. The merge commit was fetched and observed on `origin/main`.

The synthetic build-74 app used an isolated HOME/config/cache, a fake CLI with
empty synthetic provider/history data, and a temporary desktop entry named
“CodexBar GTK build 74 synthetic pointer test.” Before input, the Settings app
and tray names were unowned; after launch they resolved to the fixture PID.
The unrelated desktop apps were left untouched. The isolated
`refreshAllProvidersOnMenuOpen` value started and ended `false`.

The host portal is xdg-desktop-portal 1.18.4 with KDE backend 6.8.1. The
[RemoteDesktop interface](https://github.com/flatpak/xdg-desktop-portal/blob/main/data/org.freedesktop.portal.RemoteDesktop.xml)
uses relative `dx,dy` for `NotifyPointerMotion`; absolute motion requires a
PipeWire stream node and stream-space coordinates, so it is unavailable without
ScreenCast. E146 verified relative movement to `(1211,527)` while Settings was
active and topmost, but a later uncommanded cursor change invalidated the hit
test before a click.

E147's retry captured the synthetic General baseline before starting the portal
request. The Spectacle active-window capture produced no KWin cursor or focus
events in the observer interval. KWin then observed the KDE portal backend
window activate during `Start`, followed by Settings reactivation when it
closed. The observer did not capture a caption matching the friendly fixture
name, and no prompt screenshot was taken, so the named-dialog requirement is
still unverified even though `Start` returned response 0 for pointer+keyboard
only (`types=3`, `persist_mode=0`, no ScreenCast or clipboard). KWin recorded
1,864 cursor-change events during the retry while the portal action log
contained only `Start` and `Close`; it also recorded a brief focus switch away
from Settings and back. These events did not come from helper motion commands,
but their source is unknown. No pointer or keyboard action was sent, and the
isolated preference stayed `false`.

Cleanup closed the portal session, stopped the fixture app and observer,
unloaded the KWin script, and left app/SNI/Spectacle names unowned. The unrelated
`codexbar-linux` process remained running. The temporary HOME and screenshots
were removed; the build-74 slot is released (E147). The baseline capture was
visually inspected but is not retained as action evidence. Native GTK
`cargo build --locked --bin codexbar-gtk-native` passed with the existing U04
GTK SDK, and the temporary Python helpers passed `py_compile`. No full suite,
Xvfb smoke, or exact-head CI is claimed. No PR is appropriate because no
preference or navigation action completed; UG remains **NOT PASSED** and Python
remains default.

Latest retry/route assessment (E148–E149): the live retry was aborted before a
RemoteDesktop request after KWin observed 101 unexplained cursor changes and a
window-added event while no portal process was active; final hit-testing no
longer targeted Settings. No consent or input occurred, and the preference
remained false. The observer, app and owned KWin script were cleaned up; the
cursor log and baseline remain in the local `/tmp/codexbar-u05-build74-final-_d1ayeqm/`
evidence directory. Do not retry live input while this activity is unexplained.

A private KWin 6.8.1 virtual backend successfully created its own Wayland
socket and D-Bus owner and exposed `org_kde_kwin_fake_input`; the installed KDE
portal descriptor advertises RemoteDesktop. Its `ScreenShot2.CaptureActiveScreen`
method crashed that isolated KWin process in `RenderDevice::eglContext()`, so
there is no safe visual prompt capture for the required caller-name check.
No portal session or consent was started. The local headless assessment and
short crash summary are in `/tmp/codexbar-u05-build74-headless-sk_sxk_s/`.

**Concrete handoff:** keep this build partial. The next candidate environment
must be disposable and provide both KDE RemoteDesktop and reliable capture of
the isolated compositor (for example, provision Xvfb and run nested KWin on its
private X display, or verify a KWin virtual-backend capture fix). Reconfirm
private D-Bus/XDG paths, fixture identity and capture before requesting
one-time approval. After approval and `Start` response 0, use bounded portal
motion and final focus/top-hit checks with no capture between the final guard
and click; assert the visible switch and isolated JSON value. If that setup is
unavailable, hand off the exact blocker rather than resuming live input. No
PR is appropriate without an observed preference/navigation action. UG remains
**NOT PASSED** and Python remains the default.

### U05-UG8 handoff — build 77 Start-at-login action coverage

Owner: current U05 session; branch `orchestrated/luna-ug-next`, provisional
build `0.82.0 (77)`, based on observed live `origin/main` at PR #76 merge
`862ec69`. **Status: partial (harness+guard only; live evidence pending).**

Scope: one additional General control — “Start at login” (`launchAtLogin`)
via the guarded Wayland runner. The runner now allowlists
`start-at-login` with the E157-measured 440 px window-relative row offset
and requires the isolated autostart entry
(`~/.config/autostart/codexbar-gtk.desktop`) to exist alongside the
persisted preference. The post-consent focus/top-hit/cursor guard, baseline
capture, named KDE consent, and single-preference-change assertion are
unchanged; the start-baseline-false precondition applies.

Local verification: `py_compile` passed; all 10 Wayland guard tests passed
(including the updated allowlist set); the full Python suite ran 224 tests
with 70 expected skips and no failures. The native binary could not be
built in this shell (GTK4 pkg-config absent) and `xvfb-run` is absent, so
no Xvfb Settings smoke or live Wayland run was performed in this PR.
See E163 for the full audit.

**Concrete handoff:** request a fresh, visually named KDE grant for
`--action start-at-login`, inspect the baseline screenshot first, then
require only `launchAtLogin` changed, the value persisted true, and the
autostart entry present. Until that passes, UG remains **NOT PASSED** and
Python remains the default.

### U05-UG9 handoff — build 78 manual-test data + hide-personal-info action

Owner: current U05 session; branch `orchestrated/luna-ug-next`, provisional
build `0.82.0 (78)`. **Status: partial (docs + harness only; live evidence
pending).**

Scope: (1) E164 classifies every open UG matrix row into what runs
unattended (unit parity, smoke scripts) versus what needs a human (portal
consent, OAuth/sudo/Spectacle/fake-input limitations, foreign PIDs, real
display placement). (2) Adds the allowlisted `hide-personal-info` General
action (`hidePersonalInfo`, pre-created false in the synthetic fixture) so
it is ready to run with the same fresh named KDE grant.

Local verification: `py_compile` passed; all 10 Wayland guard tests
passed; full Python suite ran 224 tests with 70 expected skips, no
failures. Native binary build and Xvfb smokes could not run in this shell
(GTK4 pkg-config and xvfb-run absent); no live Wayland run performed.
See E164.

**Concrete handoff:** request a fresh visually named KDE grant for
`--action start-at-login` or `--action hide-personal-info`; inspect the
baseline screenshot, then require only the selected preference persisted
true. Until then UG remains **NOT PASSED** and Python default.

### U05-UG10 handoff — build 81 automated Display-tab fix (E184)

Owner: current U05 session; branch `orchestrated/luna-ug-auto-tab`, provisional
build `0.82.0 (81)`, based on PR #79 head `bacc374` (PR #79 OPEN, not yet
merged to `origin/main` at `bd4146f`; see AUDIT E184). **Status: partial
(fix verified by pixels + unit tests; live automated run pending).**

Scope: diagnose and fix the Wayland runner's Display-tab click. E183's
manual-navigation `hidePersonalInfo` PASS stands; the runner's own tab
click never navigated. Root cause is the measured tab point: the old
`(0.34, 0.94)` lands 1 px above the `AdwTabBar` pill (abs y 845 vs pill
top 846, pill rect abs x 647..731, y 846..885 from the kept baseline /
page-check captures). The runner now clicks the pixel-measured pill centre
`(0.325, 0.968)` via `PAGE_TAB_FRACTIONS` and fails closed unless the
post-click page-check screenshot proves the Display page (selected-pill +
switch-pair luminance probes, PIL or stdlib PNG decoder). Timing /
revert hypotheses (b)/(c) were ruled out with evidence in E184.

Local verification: `py_compile` OK; guard tests 12/12; full Python suite
226 tests / 70 skipped (pre-change 224/70, +2 new tests); probe table
False/True/False on baseline/page-check/missing file under both decoders;
`cargo build --bin codexbar-gtk-native --locked` exit 0. No live Wayland
run performed (wrong systemd scope for the runner + human consent required),
so no automated PASS is claimed. See E184 for the full audit.

**Concrete handoff:** in the intended KDE session rebuild the native binary
from this head, then run the guarded runner with a fresh named KDE grant —
`--action hide-personal-info` — visually confirming the prompt and requiring
terminal `PASS … hidePersonalInfo=true persisted` + persisted
`settings.json` `hidePersonalInfo: true` + the Display-page screenshot in
`/tmp/codexbar-display-page-check.png` before claiming automated navigation
works. If the corrected click still does not navigate, capture the page-check
PNG + KWin state and reopen (b)/(d) with evidence. Until then UG remains
**NOT PASSED** and Python default. PR #80 merged at `7df9845`.

### U05-UG11 handoff — build 85 update-check Wayland harness (E185)

Owner: current U05 session; branch `orchestrated/luna-ug-update-check`,
build `0.82.0 (85)`, based on `origin/main` at `7df9845` (PR #80 merge).
**Status: partial (harness + unit tests + version/docs only; live
Wayland evidence pending).**

Scope: the update-check row of UG_GATE. The Xvfb path (build-67
`smoke-native-settings.sh` update section) fires the Gio
`check-updates` action against a `127.0.0.1` synthetic VERSION server
whose marker is repo build + 1, asserts the request file, and checks
the visible "Update available" dialog via xdotool. This slice ports
that pattern to Wayland: `scripts/test-native-update-check-wayland.py`
starts an in-process loopback-only `ThreadingHTTPServer` (127.0.0.1,
ephemeral port, synthetic VERSION body = repo `VERSION` with build
+ 1), launches the native debug binary with isolated
HOME/config/cache and a fake CLI plus
`CODEXBAR_NATIVE_TEST_UPDATE_URL=http://127.0.0.1:PORT/VERSION`
(the override is debug-only in `rust-gtk/src/main.rs` behind
`is_loopback_update_url`), fires
`gapplication action com.steipete.CodexBarGTK check-updates`,
asserts `GET /VERSION` reached the server, asserts KWin reports the
exact-PID window caption "Update available", and captures it via
Spectacle to `/tmp/codexbar-wayland-update-result.png`. It needs no
RemoteDesktop portal consent, so the legacy
`app-codexbar-gtk-synthetic-wayland-test.scope` (which the T3
orchestration cgroup never has) does not apply; the harness refuses
the portal scope and the T3 agents scope. No pointer/keyboard input
is sent. No public network request is possible: the server binds
127.0.0.1 and the URL predicate is unit-tested against the native
one. Sibling slices (tab navigation, Notifications, Menu Bar, Spend)
are untouched.

Local verification: `py_compile` OK; new harness guard tests 7/7;
existing Wayland guard tests 12/12; full Python suite 233 tests /
70 skipped (226/70 pre-change → +7 new tests). No Rust source changed,
so no cargo build was needed for this slice; no live Wayland run was
performed (this session is not inside an interactive desktop session
with the app id free and a debug binary — a live run needs an operator
on the intended KDE session). See E185.

**Concrete handoff:** on the intended KDE session rebuild the debug
native binary from this head, then run
`python3 scripts/test-native-update-check-wayland.py --binary "$PWD/rust-gtk/target/debug/codexbar-gtk-native"`
and require terminal
`PASS: update-check action reached loopback server; visible Update available state verified`
plus the kept `/tmp/codexbar-wayland-update-result.png` showing the
"Update available" dialog plus an unowned app id after quit, before
claiming the UG update-check row PASS. Until then UG remains
**NOT PASSED** and Python default.
### U05-UG12 handoff — build 86 Providers Wayland harness (E186)

Owner: current U05 session; branch `orchestrated/luna-ug-providers`,
build `0.82.0 (86)`, based on `origin/main` (`3872ebc`, PR #83/Spend merge).
**Status: partial (harness + unit tests + version/docs only; live
Wayland evidence pending).**

Scope: the Providers row of UG_GATE. Control-to-CLI mapping
(`rust-gtk/src/settings_window.rs::populate_providers`; Python parity
`codexbar_gtk/ui/settings.py::_providers_page`; backend
`rust-backend/src/settings.rs::provider_action`/`set_api_key` via
`rust-backend/src/cli.rs`): "Provider enabled" switch → `config
enable|disable --provider <id>`; "Source" combo → `config set-source
--provider <id> --source <auto|web|cli|oauth|api>`; "Sign in with
provider CLI" (claude/codex) → native LoginDialog over the B11 PTY
(`auth login --claudeai` / codex login; events in memory only);
"API key" Apply → `config set-api-key --provider <id> --api-key
<secret>` (trimmed, entry cleared, never persisted). Xvfb already
passes all four against the fake CLI in
`scripts/smoke-native-settings.sh` (randomized synthetic key checked
absent from preferences/calls/app.log; synthetic PTY code completes
with "Sign-in completed."). On Wayland only the switch is safe to
drive guarded, and it persists no preference JSON — the fixture CLI
owns provider state — so `scripts/test-native-settings-wayland.py`
adds `disable-codex-provider` (`kind=provider_switch`,
`preference=None`, page Providers, tab estimate + switch estimate from
the Xvfb smoke), which seeds the fixture provider ON, clicks to
disable, and requires the recorded `config disable --provider codex`
call plus the state-file flip `true→false` (plus an unchanged
preference store), mirroring the autostart-entry check. Source
combo, API-key entry and PTY login are `kind=manual` allowlist
entries that refuse to drive (`parser.error`) and must use
`--inspect-only` plus a manual step against synthetic fixtures —
never faked. Automated tab navigation still handles Display only;
Providers needs manual tab selection or a measured tab point.
Existing General/Display/Menu Bar/Notifications actions untouched.

Local verification: `py_compile` OK; guard tests 19/19 (16
pre-existing + 3 new: switch mapping/geometry, state-check
fail-closed table, manual-only table); full Python suite 251 tests /
70 skipped (248/70 pre-change → +3 new tests). No Rust source
changed, so no cargo build was needed for this slice; no live
Wayland run was performed in this session (no KDE Wayland, no
`app-codexbar-gtk-synthetic-wayland-test.scope` cgroup, no debug
binary, no fresh named grant). Synthetic fixtures only; no real
accounts/keys/OAuth output anywhere. See E186.

**Concrete handoff:** on the intended KDE session rebuild the debug
native binary from this head, then
`systemd-run --user --scope --unit=app-codexbar-gtk-synthetic-wayland-test.scope python3 scripts/test-native-settings-wayland.py --binary "$PWD/rust-gtk/target/debug/codexbar-gtk-native" --action disable-codex-provider --inspect-only`
first (manually select the Providers tab, calibrate tab/row points
with `--switch-x/--switch-y` if the estimate is off), then a fresh
grant without `--inspect-only` and require terminal
`PASS: synthetic fixture CLI recorded config disable --provider codex and the Codex provider state flipped enabled true->false (no preference JSON changed)`
plus the kept `/tmp/codexbar-providers-page-check.png`, before
claiming any Providers Wayland PASS. Manual source/API-key/login
steps stay manual until the runner gains a measured tab point and a
guarded keyboard path. Until then UG remains **NOT PASSED** and
Python default.

### U05-UG12 handoff — build 87 Spend retained-error stale-capture fix (E187)

**Status: partial (harness-built; live re-verification open).** The `--state retained-error` wait returned on the first failure marker, before the backend finished the initial cost scan plus its per-provider retries and published the retained-error view state; the capture therefore raced the view-state update and could record the neighbouring partial frame (byte-identical evidence). The wait now covers 3 cost-fixture calls (1 initial + 2 retries) and a view-state settle before capturing, and the state capture fails closed unless the synthetic Spend PID is active. The AUDIT E184-spend "build 80 base" line is stale relative to the committed script (no fail-then-release/backoff sequence exists in the harness); it is not rewritten here. The operator must re-run `--state retained-error` on the intended KDE session and require a retained-error capture distinct from the partial capture before any Spend state PASS is claimed. Python stays default; UG stays **NOT PASSED**.

### U05-UG13 handoff — build 89 hide-personal-info switch_x_fraction pixel-measured (E189)

**Status: partial (harness-fixed; live re-verification open).** E188 fixed y to the measured 311 (absolute y 460 correct) but the click still missed horizontally: toggle pill centre is at window-absolute (1114, 460) — x_fraction 0.75 — while `switch_x_fraction=0.90` clicked (1264, 460), 150px too far right into window padding; `hidePersonalInfo` stayed false. `switch_x_fraction` is set to the measured 0.75; `y_offset` stays 311. No live Wayland PASS is claimed; operator must re-run `--action hide-personal-info` on the intended KDE session and require persisted `hidePersonalInfo false→true`. Python stays default; UG stays **NOT PASSED**.

### U05-UG13 fold-in — build 89 settings_capture guard from PR #88

**Status: included in build 89.** PR #88's two-line `settings_capture = None` init + cleanup guard was folded into the hide-x branch (`orchestrated/luna-ug-hide-x-fix`, build 89) verbatim, since the uninitialized-variable masking bug is present identically on build-88 main (assigned line 841, referenced in `finally` line 1207) and in both #90 and #91. PR #88 (`orchestrated/luna-ug-settings-capture-guard`) should be closed as superseded once build 89 merges; its live-run evidence is preserved in AUDIT E189 fold-in. Python stays default; UG stays **NOT PASSED**.

### U05-UG14 handoff — build 90 `--bridge` consent-free runner route rebased onto merged PR #90 (E190/E191)

**Status: partial (harness-built; live re-verification open).** PR #91 rebased onto merged PR #90 build 89 (`9f5497c`) as build 90. The build-89 fixes are retained unchanged: `switch_x_fraction` 0.75 (E189) and the `settings_capture = None` + cleanup guard (PR #88 fold-in). The bridge feature is preserved: `--bridge`/`--portal`/`--bridge-cmd` with `BridgeDriver`/`guarded_click_bridge` delegating to the same `guard_target` checks; KDE OS-level grant untouched. PR #90 merged at `9f5497c` after root reviewed head `6d811e8` with `test`/`tray-dbus` PASS; PR #88 closed as superseded. E190 is preserved as historical build-89 content; E191 is the build-90 rebase entry. **Build-assumption caveat:** E191 and this handoff bake build 90 assuming HEAD at push-time is `9f5497c` (build 89) — if any later build lands before merge, recompute the build number. No live Wayland PASS is claimed for `--bridge`; operator must re-run `--action hide-personal-info --bridge` on the intended KDE session and require persisted `hidePersonalInfo false→true`. Python stays default; UG stays **NOT PASSED**.


### U05-UG14 continuation — build 93 guarded Display evidence (E195)

**Status: partial, live one-control verification recorded; PR pending root publication.**
The existing build-92 branch carries the build-93 implementation/evidence commit.
`c95` allows guarded bridge motion only before an initial top-hit sample;
`b48` bounds move-only telemetry; `ece` uses exact-PID activation/fresh state;
`e9` samples KWin every 250 ms with fresh sequence/sender validation. Strict
click checks remain: sample age 0.15–0.35 seconds, exact synthetic PID active,
`top_hit`, and cursor agreement.

The 2026-11-09 14:01:10–14:01:16 EST live run used synthetic PID 3272001 and
window geometry `[364,149,1000,740]`. After Display tab navigation, one guarded
bridge click at `(1114,460)` persisted only `hidePersonalInfo: false→true`;
the complete after-JSON was compared with the Rust default map and the runner
reported PASS. Tracked [`screenshots/build93-wayland-display-before.png`](screenshots/build93-wayland-display-before.png) is the fresh pre-click Display image showing the switch off. The runner did not persist its
pre-click `sample_seq`/age, click timestamp, or a post-click image; the original
synthetic settings file was removed during cleanup. The saved `result.log`
contains before/after JSON and the runner assertion. Do not describe it as a
retained raw settings file or infer an event trace. The general baseline is not
tracked.

Verification: 39 focused `tests/test_wayland_smoke_guard.py` tests and the full
Python default suite; extension opt-in status and exact counts are in E195.
No desktop/app/portal input was performed during this implementation turn. The
prior cleanup worker confirmed the scoped app/Spectacle/SNI names and owned
processes were gone; the unrelated watcher was preserved. No new exact-head CI
or merge result is claimed. The synthetic screenshot is reviewed, and the live
run reported only the selected preference change.

**Next:** root publishes this focused commit, observes CI, and handles PR/merge.
Continue open UG interactions; keep Python default and all cutover gates closed.
Additive installer PR #93 later merged as build 94; the current build-96
renderer handoff and build-95 runtime proof are summarized above.

### C02 component-proof handoff — build 96 (E198/E199)

**Status: local Docker proof verified; root publication/exact-head CI pending.**
The existing `scripts/smoke-native-no-python.sh` and Docker runtime harness now have a
required-CI mode, exact Cargo JSON artifact discovery, same-commit debug and
release inputs, the existing native SVG test executable, and an explicit
nonzero failure for the final installer invocation. Focused tests cover Cargo
artifact selection/rejection, bad artifact input, and unavailable Docker in
required mode. The CI job runs all application launches inside the
network-disabled runtime image with private Xvfb and D-Bus; it does not launch
the app on the host.

E199 separately removes Python from activation rendering and records isolated
installer evidence. The Python-free 13-case run covered invalid first and
second templates on fresh install and upgrade, unchanged binary/manifest/
activation/backups on failure, and a successful retry. Activation writes only
desktop/service files; it does not start or enable a service or create
autostart. This is prior local evidence, not a rerun on the reconciled build-96
head.

These proofs cover components only. Genuine version upgrade, C02 settings/
login/history coverage, UG acceptance, and the Python-default cutover remain
open. Python remains the launcher default. Next exact step: root reviews and
publishes the local build-96 implementation, then observes exact-head CI before
deciding any gate status.

### U05-UG15 handoff — build 97 guarded Settings batch (E200)

**Branch:** `orchestrated/luna-ug-settings-batch`.
**Status: partial; seven scoped Wayland actions and three Settings tab
transitions passed.** This branch updates the guarded test runner and records evidence; it changes
no application runtime code. The synthetic Wayland run used the build-95 native binary. It verified
General `refreshAllProvidersOnMenuOpen`, all four Notifications preference
switches, Menu Bar `showTray`, and the global Hooks disable action. The full
preferences map was checked for each preference action; Hooks used the fixture
CLI and left preferences unchanged. See E200 and the scoped UG rows. Wayland
test-notification delivery, three Menu Bar combos, Hooks rules display, all
other Settings actions, whole-app parity and keyboard parity remain open.
Python remains default and UG remains **NOT PASSED**.

**Next requested v0.84 slices:** root has started the provider catalog/artwork
slice independently from build-96 `main`. Continue afterward with the safe
Claude warning slice, then the ClaudePlatform stdin-login slice. Keep these as
separate reviewable changes; do not mix their feature code into this evidence
commit. Root owns the PR, push and merge for this build-97 batch.
