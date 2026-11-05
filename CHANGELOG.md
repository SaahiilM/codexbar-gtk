# Changelog

Client-side changelog for the CodexBar GTK front-end. Each entry keys a build
number (`CURRENT_PROJECT_VERSION`) to the upstream macOS CodexBar release its
short version tracks, so "which version has what" maps cleanly onto both trees.

## 0.82.0 (85) — 2026-11-05

Tracks upstream CodexBar 0.82.0.

### Changed

- Add the Wayland update-check evidence harness (E185): a guarded
  `scripts/test-native-update-check-wayland.py` that starts a
  loopback-only synthetic VERSION server, drives the native Gio
  `check-updates` action in a debug native binary on Wayland, asserts
  the synthetic request arrived, and verifies the visible "Update
  available" state via KWin caption plus a Spectacle capture kept at
  `/tmp/codexbar-wayland-update-result.png`. It needs no RemoteDesktop
  portal consent and never contacts a public URL. No live Wayland PASS
  is claimed yet — the gate row stays OPEN until the harness runs on
  the intended KDE session. UG remains **NOT PASSED**; Python remains
  the default.

## 0.82.0 (81) — 2026-11-05

Tracks upstream CodexBar 0.82.0.

### Changed

- Diagnose and fix the Wayland runner's automated Display-tab navigation
  (E184): the tab click previously landed 1 px above the `AdwTabBar` pill
  (window y 696 vs pill top 697, from the old `(0.34, 0.94)` estimate), so
  all automated runs stayed on General while the manual E183 run passed via
  the user's own click. The runner now clicks the pixel-measured pill
  centre `(0.325, 0.968)` and verifies the Display page from the page-check
  screenshot (selected-pill + switch-pair evidence) before any toggle
  click; it fails closed otherwise. No live automated PASS claimed yet —
  awaiting a fresh named KDE grant. Broader UG remains **NOT PASSED** and
  Python remains the default.

## 0.82.0 (80) — 2026-11-05

Tracks upstream CodexBar 0.82.0.

### Changed

- Post-merge follow-ups from the Display-navigation slice (PR #78 merged at
  build 79): the Wayland runner now reactivates the Settings window after the
  post-tab-click page check (Spectacle's `--activewindow` capture steals focus,
  E182/E183) and captures `/tmp/codexbar-display-page-check.png` to evidence
  Display-page navigation. `hide-personal-info` now has a verified PASS
  (E183, manual Display navigation + runner switch click; persisted
  `hidePersonalInfo: true`) and the incorrect E181 PASS claim is retracted.
  Broader UG remains **NOT PASSED** and Python remains the default.

## 0.82.0 (78) — 2026-11-03

Tracks upstream CodexBar 0.82.0.

### Changed

- Extend the guarded synthetic Wayland Settings runner with a manual-test
  checklist doc and an allowlisted General action for “Hide personal
  info”. Live Wayland evidence for the latter is pending a fresh named
  KDE grant; broader UG remains **NOT PASSED** and Python remains the
  default.

## 0.82.0 (77) — 2026-11-03

Tracks upstream CodexBar 0.82.0.

### Changed

- Extend the guarded synthetic Wayland Settings runner with an allowlisted
  General action for “Start at login”, which persists the selected
  preference and requires the isolated autostart entry alongside it. Live
  Wayland evidence for this action is pending a fresh named KDE grant;
  broader UG remains **NOT PASSED** and Python remains the default.

## 0.82.0 (76) — 2026-11-03

Tracks upstream CodexBar 0.82.0.

### Changed

- Extend the guarded synthetic Wayland Settings runner with an allowlisted
  General action mapping for “Show the panel on start”; live Wayland evidence
  includes one manual user click that persisted the selected preference. The
  runner's automated click path remains unverified and UG remains **NOT PASSED**.

## 0.82.0 (75) — 2026-11-03

Tracks upstream CodexBar 0.82.0.

### Changed

- Add a guarded, synthetic Wayland Settings preference runner that keeps portal
  setup and input on the same D-Bus connection, checks fresh KWin focus and hit
  state, and verifies the isolated preference JSON. One user-approved live
  General preference action passed; broader UG remains **NOT PASSED** and
  Python remains the default.
- Add unit coverage for stale, foreign, unstable and non-topmost guard states.

## 0.82.0 (73) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the build-73 Wayland attempt. The installed portal's app-ID scope
  produced a named, nonpersistent pointer+keyboard consent prompt and a
  successful grant; one pointer motion was sent, but cursor/focus checks then
  changed and no Settings click or preference mutation is claimed. See audit
  E141–E143. Python remains the default; UG remains **NOT PASSED**.

## 0.82.0 (72) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the build-71 merge and build-72 synthetic Wayland lifecycle/portal
  evidence. A bounded process check found no spontaneous Settings exit; a
  fresh, user-approved keyboard refresh reached the synthetic CLI. Python
  remains the default and UG remains **NOT PASSED**.

## 0.82.0 (71) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Continue UG's serialized Wayland interaction evidence using a fresh,
  consent-based KDE RemoteDesktop request. The user approved the named,
  nonpersistent pointer/keyboard request, but the synthetic Settings process
  exited before input; no Wayland action is claimed. Preserve Python as default
  and UG as **NOT PASSED**.

## 0.82.0 (70) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Continue UG's serialized Wayland interaction evidence using KDE's
  consent-based RemoteDesktop portal where available. A named one-time
  pointer/keyboard request timed out without user approval, so no input was
  sent. Preserve Python as default and UG as **NOT PASSED**.

## 0.82.0 (69) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Continue the native GTK acceptance follow-up with isolated Wayland page/action
  interaction evidence. The build-69 live session captured Settings General,
  but did not establish a verified Wayland control action because available
  input routes produced no visible state/result change. See migration audit
  E133; UG remains **NOT PASSED**.

## 0.82.0 (68) — 2026-11-02

Tracks upstream CodexBar 0.82.0.

### Changed

- Match the Python SNI panel contract: `Activate` toggles and refreshes only
  when opening; `SecondaryActivate` and `ContextMenu` ensure the panel stays
  open and refresh on every event when the menu-open refresh preference is on.
- Preserve activation coordinates for X11 monitor anchoring and use the
  compositor's placement on Wayland.

### Validation

- Build-68 Xvfb/private-D-Bus interaction matrix, exact refresh-call counts,
  panel placement and focus-before-Escape evidence are recorded in migration
  audit E130. Synthetic panel captures are in
  `docs/rust-migration/screenshots/`. Wayland SNI events were sent over the
  desktop session bus and captured with fixture data; keyboard/pointer input
  remains unverified because the compositor rejects the available virtual
  keyboard input method. Python remains the default; UG remains **NOT PASSED**.

## 0.82.0 (67) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Close the remaining synthetic GTK Settings interaction gaps from UG build 66,
  including provider/auth controls, CLI-path Apply, hooks/plugins read states,
  import/export/reset, update-check, and uncovered General/Display preferences.

### Validation

- Local Rust/Python tests, strict Clippy, native GTK smokes and the complete
  synthetic Settings Xvfb interaction smoke passed on
  `orchestrated/luna-u05-settings-interactions-build67`. Thirty-six captures,
  including the visible sign-in success result, are recorded in E123. Exact-head
  PR checks/review remain pending. UG remains **NOT PASSED** because Wayland
  interaction and repeatable local panel evidence are open. Python remains the
  default; see [UG_GATE.md](docs/rust-migration/UG_GATE.md).

## 0.82.0 (66) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Close out the U08 merge record and add a build-66 UG interaction/evidence
  ledger. UG remains open while the remaining Settings actions and complete
  Wayland interaction matrix are verified.
- Extend the synthetic GTK smoke to click and capture all four Spend ranges and
  all three heatmap modes. Exercise Menu Bar, selected Display, Notifications,
  currency/time-zone, launch-at-login and private notification delivery through
  visible Settings controls.
- Add visually inspected build-66 Xvfb Settings/range/mode captures and retain
  valid synthetic Wayland Sessions/Spend state captures with their provenance.

### Validation

- U08 PR #66 merged normally at `5de83def98ad5ebd09035ee9120698fbf710541c`;
  exact head `fb89f0b6c702dff92992916e14951b385f5189bf` passed `test` and
  `tray-dbus` in run `41345048163` (E119). Build-66 Settings and Usage & Spend
  Xvfb smokes passed, including private notification delivery and Hooks global
  enable/disable persistence (E120). UG remains **NOT PASSED**: provider,
  import/export/reset and update-check actions and Wayland interaction evidence
  remain incomplete. Plugins is a read-only fixture list; empty/loading/error
  states are untested, with no mutation action required. See
  `docs/rust-migration/UG_GATE.md`. Python remains the default.

## 0.82.0 (65) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Embed the existing licensed provider artwork catalog into the native app and
  show brand or accent-tinted provider marks with an initial-letter fallback.
- Render native meter and `iconPercent` tray pixmaps from the existing
  `TraySummary`, with Cairo-generated ARGB pixels at caller-requested sizes.
- Add responsive dashboard summary tiles, shared theme CSS, decorative
  accessible provider artwork, and keyboard navigation shortcuts.

### Validation

- U07 PR #65 merged at `e373e019f7701f5f3a5e204153b7163763abac90`; exact head
  `70bba1c52562c7670916a51a28fb9f37a29cd3ec` passed `test` and `tray-dbus` in
  run `41340840860` (E114). U08 local Rust/Python checks, X11/Xvfb and actual
  Wayland synthetic captures, and renderer/accessibility smokes are in E115/E116;
  this PR's exact-head CI and merge remain pending.

## 0.82.0 (64) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Complete native desktop notification delivery, OS adapters, display
  readiness, restart and launch-at-login integration, and orderly worker/tray
  shutdown (U07).

### Validation

- U06 PR #64 merged normally at `678b6b9`; exact head passed both required
  checks in run `41337858935`. U07 PR #65 exact head
  `70bba1c52562c7670916a51a28fb9f37a29cd3ec` passed `test` and `tray-dbus` in
  run `41340840860` and merged normally at
  `e373e019f7701f5f3a5e204153b7163763abac90` (E114). U07 local Rust/Python/GTK
  checks and synthetic Xvfb/private-bus runtime evidence are in E113.

## 0.82.0 (63) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Implement the native StatusNotifierItem and dbusmenu tray, including icon
  pixmap/tooltip updates, projected provider switcher rows, watcher recovery,
  central native actions, and explicit bus teardown.

### Validation

- U06 implementation and native GTK synthetic runtime evidence are recorded in
  migration audit E110. Exact-head CI and merge status will be recorded after
  observing them.

## 0.82.0 (62) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Add the native libadwaita Settings panes and serialized Rust preferences,
  provider actions, CLI reconfiguration, login, import/export and reset.
- Persist preference updates transactionally and preserve concurrent unrelated
  values during import and reset.

### Validation

- U05 native Settings runtime, Rust tests and migration checks are recorded in
  migration audit E105. The runner portability and no-capture interaction fix
  is recorded with its local reruns in E107; replacement-head Actions checks
  remain pending.

## 0.82.0 (61) — 2026-11-01

### Changed

- Add native Usage & Spend and Sessions pages with sticky scan status,
  unknown-aware token heatmap, filters, and accessible interaction (U04).

### Validation

- Local Rust formatting, tests and Clippy passed for all four crates; core has
  81 tests, backend has 76 plus one integration test, and native GTK has 23.
  The PyO3 build, default Python (214 passed, 21 expected opt-in skips),
  Rust-opt-in Python (214 passed), and the 3-test tray D-Bus suite passed.
  Synthetic GTK Xvfb routing, refresh, accessibility interaction and
  empty/loading/partial/error screenshots passed locally. U04 PR #62's first
  head passed `tray-dbus`; `test` and merge remain pending. See migration audit
  E102–E103.

## 0.82.0 (60) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Implement the native compact usage panel with shared dashboard projections,
  panel dismissal, navigation, and platform-aware placement (U03).

### Validation

- All four Rust crates pass formatting and strict Clippy. Tests pass for core
  (78), backend (72 plus 1 integration), and native GTK (21). The optional
  PyO3 extension build passed; default Python passed 214 tests with 21 expected
  opt-in skips, Rust-opt-in Python passed all 214, and tray D-Bus passed 3.
- A synthetic six-provider Wayland GTK fixture and screenshot were inspected;
  a live X11 fixture verified the panel at the selected work-area corner and
  exercised dashboard/page/settings/about routing. Exact-head PR #61 passed
  `test` and `tray-dbus` in run `41324106655`, including routing/shutdown and
  synthetic dashboard GTK smokes, then merged normally at `51480af` (E101).

## 0.82.0 (59) — 2026-11-01

Tracks upstream CodexBar 0.82.0.

### Changed

- Close the Python history writer parity gap so unknown and placeholder quota
  windows cannot be persisted as zero-valued trend samples. Record the observed
  U02b merge and the remaining ambiguity in pre-existing history rows.

### Validation

- Rust tests from the merged U02b implementation: core 78; backend 72 plus the
  headless integration test; native GTK 18. Clippy passed for all four Rust
  crates. The build-59 optional extension build passed; default Python ran 214
  tests (21 opt-in skips) and Rust-opt-in Python ran 214 tests with no skips.
- U02b PR #59 exact head `89ae294` passed `test` and `tray-dbus` in run
  `41174965540` and merged normally at `81b7b8f`. U02 acceptance PR #60 exact
  head `b2fc92c` passed both checks in run `41314701763` and merged normally at
  `317078a`. A fresh Xvfb smoke could not run because `xvfb-run`, `Xvfb`, and
  `xdotool` are absent; #60 changed no GTK rendering and the synthetic native
  screenshots from merged U02 were inspected. Python remains default until UG.

## 0.82.0 (57) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Begin U02a native dashboard/provider-card implementation while keeping Python
  as the default application until UG passes.

### Validation

- U02a PR #58 exact head `c2a3078d7ec304ef94323749d68d21d59d9cc21b` passed
  `test` and `tray-dbus` in run `41172651348` and merged normally at
  `549908e42195ce04479424c5fd22ca5ea52d8109`. Synthetic Wayland/GTK evidence
  is recorded in AUDIT E090/E091; U02 remains partial pending U02b.

## 0.82.0 (56) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the observed U01 native bootstrap merge and move the Phase U handoff
  to U02 while retaining the Python default and partial native screens.

### Validation

- Documentation/version closeout only. U01 PR #56 exact head `3b99d3e` passed
  `test` and `tray-dbus`; the normal merge at `3eea06f` is live `origin/main`.
  Merge evidence is recorded in AUDIT E089.

## 0.82.0 (55) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Start Phase U with a native GTK4/libadwaita bootstrap, direct Rust backend
  worker, single-instance command routing and build metadata.
- Keep Python as the default application until UG passes; native placeholder
  routes are bootstrap scaffolding, not full-screen parity.

### Validation

- Local locked Rust tests passed for core (78), backend (71 unit + 1 integration)
  and the native GTK bootstrap (8). Strict Clippy and both default/Rust-opt-in
  Python suites passed. Xvfb/private-D-Bus routing/cancellation smoke passed;
  the synthetic Wayland capture shows backend-ready revision 2. Exact-head CI
  remains pending with the focused U01 PR.

## 0.82.0 (53) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Add a Rust-only BG end-to-end fixture covering CLI/controller state and
  notifications, loopback currency/update HTTP, and fake PTY cancellation/join.
- Record the verified B13c merge, current gate evidence, and remaining Python
  UI/default-path boundaries.

### Validation

- Full backend and parity checks plus Python/Rust Wayland fixture screenshots
  are recorded in AUDIT E085. BG remains open until the focused PR is merged.

## 0.82.0 (52) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Match the Rust-opt-in last-30-days spend caption to the Python UI while
  retaining the structured last-30 token count in the Rust DTO.
- Record the verified B15 merge and its explicit Rust opt-in compatibility
  limits in the migration handoff.

### Validation

- Fixture parity assertions, both Python modes, Rust crate checks, and
  synthetic Wayland GTK screenshots are recorded in AUDIT E084.

## 0.82.0 (51) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Changed

- Characterize F01–F06 numeric, date/time, DST, chart and persisted-history
  behavior against the unchanged Python reference; add explicit Rust range
  errors and checked aggregation.
- Match Python 3.12 Unicode 15 fallback casing exhaustively and keep provider
  and currency catalogs on their Rust source in opt-in mode.
- Record the production/helper reachability boundary and remaining explicit
  Rust opt-in compatibility limits. BG remains open.

### Validation

- Local Rust/Python parity, strict checks, GTK fixture smoke and screenshots
  are recorded in AUDIT E081; remote PR checks are recorded only after they
  are observed.

## 0.82.0 (50) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the verified B14 integration and the shared CurrencyService facade
  merge. Route Rust-opt-in currency catalog, rate, conversion, status and
  refresh calls through the central controller facade.
- Update the migration handoff to B14 complete; B15 remains the next backend
  audit and the BG/native UI gates remain open.

### Validation

- This closeout changes version/status documentation only. PR #50's merged
  implementation checks and fixture-only GTK screenshots are cited in AUDIT
  E080. The closeout's default/Rust-opt-in Python suites, private-D-Bus tray
  tests, format and version synchronization checks passed locally; its remote
  PR checks remain to be observed.

## 0.82.0 (49) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Route Rust-opt-in currency catalog, rate, conversion, status and rate-refresh
  calls through the central refresh-controller facade, sharing the existing
  CurrencyService with refresh and spend projections.
- Keep rate refresh work on a controller-owned worker and preserve
  `fetched_at`, live/cache/offline source and refresh-failure status.

### Validation

- Core/backend tests, strict Rust checks, Python parity and Rust-opt-in suites,
  private-D-Bus tray tests, and fixture-only Python/Rust Wayland settings smoke
  passed. See AUDIT E078 for exact scope and screenshots.

## 0.82.0 (48) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Changed

- Reconcile and accept the complete B13 extraction across merged spend/tray,
  settings and application-action slices. B14's remaining currency facade work
  is recorded separately and remains gated until this handoff merges.

### Validation

- No application runtime code changed in this handoff. See AUDIT E076 for the
  observed B13 merges, accepted caller inventory and linked synthetic UI
  screenshots; B14 currency facade routing is the next backend task.

## 0.82.0 (47) — 2026-10-31

Tracks upstream CodexBar 0.82.0.

### Added

- Route B11 login, B12 update checking and application restart operations
  through the shared Rust facade while leaving GTK responsible for rendering,
  browser interaction, GLib marshalling and OS notification delivery.
- Audit remaining Python UI service callers and document their compatibility
  boundary for the backend completion gate.

### Validation

- See `docs/rust-migration/AUDIT.md` for exact Rust/Python checks and
  synthetic GTK runtime evidence in E074.

## 0.82.0 (46) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Route provider configuration/actions, hooks/plugins, preference import/export/reset,
  launch-at-login and CLI reconfiguration through the shared Rust settings facade.
- Preserve immediate CLI path/timezone changes with a serialized shared-service
  reconfiguration actor and transactional preference updates.

### Fixed

- Reject an invalid Rust-mode CLI executable before changing preferences or the
  live controller service; Python parity behavior remains unchanged.
- Reflect accepted CLI path and timezone changes in the settings controls.

### Validation

- See `docs/rust-migration/AUDIT.md` E071 for Rust/Python checks and synthetic
  Wayland settings smoke evidence.

## 0.82.0 (45) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Extract spend and tray presentation policies into Rust-owned DTO projections
  callable through the B14 central facade.

### Fixed

- Keep missing project/model costs unavailable, preserve explicit zero costs,
  and retain the legacy model-cost fallback from `cost: 0` to a nonzero
  `totalCost`.
- Bundle and load the PyGObject Cairo bridge in development and installed
  layouts so the GTK spend heatmap and daily chart draw on Wayland.

### Validation

- See `docs/rust-migration/AUDIT.md` E069 for exact Rust/Python, installed
  Wayland smoke and screenshot evidence.

## 0.82.0 (44) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Fixed

- Exclude errored providers, placeholder windows and unknown usage from
  automatic tray selection. Keep measured zero eligible and show unavailable
  when no quota can be selected instead of projecting the default `0.0`.
- Keep tray selection indices anchored to the unchanged ordered provider and
  window vectors while filtering candidates.

### Validation

- See `docs/rust-migration/AUDIT.md` for the Python/Rust parity regression tests
  and fixture-only GTK tray smoke evidence.

## 0.82.0 (43) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Add the Rust refresh controller with an immediate first pass, dynamic polling,
  one queued forced-refresh follow-up and joined asynchronous shutdown.
- Publish immutable refresh snapshots with owned ordered provider data, spend,
  sessions, history, tray selection, version context and sanitized errors.
- Send typed notification transitions through a bounded event channel separate
  from coalescing snapshots; retain usable prior state across partial failures.
- Route Rust opt-in GTK refresh and force-refresh actions through the controller
  while keeping Python implementations as parity references.
- Compose complete usage provider envelopes in Rust and compare the shared
  synthetic fixture with the Python reference to close the B02 integration gap.

### Validation

- See `docs/rust-migration/AUDIT.md` for B10 controller tests, full-envelope
  parity, and fixture-only GTK smoke evidence.

## 0.82.0 (42) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Add a Rust PTY login service with bounded transient events, safe lifecycle
  snapshots, code submission, cancellation, timeout and child reaping.
- Route Rust-opt-in Claude login and auth-status callers through B07 executable
  discovery and the PTY-specific service boundary.

### Validation

- See `docs/rust-migration/AUDIT.md` for fixture-only auth parity, PTY lifecycle,
  GTK login smoke and exact check results.

## 0.82.0 (41) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port CLI discovery and non-interactive command execution to the asynchronous
  Rust backend with argv safety, timeouts, cancellation and child reaping.
- Route existing Python CLI adapters through the service in Rust opt-in mode.

### Validation

- See `docs/rust-migration/AUDIT.md` for synthetic CLI parity, process lifecycle,
  and GTK fixture smoke evidence.

## 0.82.0 (40) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Add a typed, read-only Rust update check with a bounded public VERSION fetch,
  numeric version comparison, and sanitized failure categories.
- Keep update HTTP and version policy in the service adapter; the GTK dialog
  renders the typed result.

### Validation

- See `docs/rust-migration/AUDIT.md` for B12 parity tests, bounded HTTP fixtures,
  Rust opt-in GTK smoke evidence, and exact check results.

## 0.82.0 (39) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port quota threshold, session exhaustion, predictive pace, and reset-credit
  expiry policies to a stateful Rust service with typed event outcomes.
- Define a bounded, backpressured event stream for notification transitions so
  coalescing watch snapshots cannot lose them.
- Preserve unknown versus known-zero quota state in notification policy parity.

### Validation

- See `docs/rust-migration/AUDIT.md` E048 for Rust, Python, tray D-Bus, and
  synthetic GTK evidence.

## 0.82.0 (38) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port provider visibility/order and automatic tray quota selection to Rust,
  including deterministic ties, depleted-quota ranking, and trusted ETA rules.
- Expose owned ordering and tray-selection DTOs for the B10 controller snapshot.

### Validation

- See `docs/rust-migration/AUDIT.md` for B09 parity, runtime and GTK fixture evidence.

## 0.82.0 (37) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port currency catalog, conversion, cached rates, and bounded asynchronous
  Rustls HTTP refresh to the opt-in Rust backend with offline fallback.

### Validation

- Rust format and Clippy checks passed; 60 core and 7 backend tests passed.
  Python passed 161 tests in each mode (two opt-in-only tests skipped in default
  mode); 3 tray D-Bus tests passed. Synthetic GTK SpendView screenshot included.

## 0.82.0 (36) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port preference defaults, persistence, import/export, reset/update, and
  refresh-interval derivation to Rust in opt-in mode.
- Preserve existing settings documents and secure atomic writes.

### Validation

- See `docs/rust-migration/AUDIT.md` for B05 parity, storage-failure, and GTK
  settings-flow evidence.

## 0.82.0 (35) — 2026-10-30

Tracks upstream CodexBar 0.82.0.

### Added

- Port spend normalization and aggregation to Rust in opt-in mode, preserving
  known-zero versus unknown cost, partial coverage, provenance, and CLI totals.
- Add parity coverage for summary totals, provider rows, errors, and daily,
  project, and model breakdown ordering.

### Validation

- See `docs/rust-migration/AUDIT.md` for B04 backend, Python, and synthetic GTK
  preview evidence.

## 0.82.0 (34) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Added

- Port agent-session payload normalization to Rust for valid typed payloads,
  retaining the Python fallback for malformed field shapes.
- Add parity coverage for session fields, timestamp handling, running-state
  classification, and stable sorting by running state then last activity.

### Validation

- See `docs/rust-migration/AUDIT.md` for B03 test and GTK preview evidence.

## 0.82.0 (33) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the observed B02b2b2b merge, mark context normalization complete, and
  set B03 as the next backend task.

### Validation

- Documentation/version metadata only; implementation and CI evidence are in
  `docs/rust-migration/AUDIT.md`.

## 0.82.0 (32) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Added

- Port provider context payload normalization (credits, status, error, plan)
  to Rust for valid typed payloads, retaining the Python fallback for malformed
  field shapes.
- Add parity coverage for credits, credit events, reset credits, status,
  error, and plan fields.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02b2b2b test and GTK preview evidence.

## 0.82.0 (31) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Added

- Port detail chart payload normalization to Rust for valid typed payloads,
  retaining the Python fallback for malformed field shapes.
- Add parity coverage for detail rows, chart points, section truncation, and
  row/point count limits.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02b2b2a test and GTK preview evidence.

## 0.82.0 (30) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Changed

- Record the observed B02b2b1 merge, mark cost normalization complete, and set
  B02b2b2 as the next provider-normalization task.

### Validation

- Documentation/version metadata only; implementation and CI evidence are in
  `docs/rust-migration/AUDIT.md`.

## 0.82.0 (29) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Added

- Port provider cost payload normalization (`providerCost`) to Rust for valid
  typed payloads, retaining the Python fallback for malformed field shapes.
- Add parity coverage for cost fields, missing values, and fallback defaults.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02b2a test and GTK preview evidence.

## 0.82.0 (28) — 2026-10-29

Tracks upstream CodexBar 0.82.0.

### Changed

- Bump `MARKETING_VERSION` to `0.82.0` to track the upstream CodexBar release.
- Increment GTK build to `28`; keep `VERSION` and `codexbar_gtk/version.py`
  synchronized.
- Verify provider catalog still matches upstream (110 providers, no additions
  or removals between 0.81.0 and main).

### Validation

- 38 rust-core and 3 rust-backend tests passed.
- 143 Python tests passed in default mode and 143 in Rust mode.
- 3 private-D-Bus tray tests passed.
- `git diff --check` passed.

## 0.81.0 (27) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Changed

- Record the observed B02b2a merge, mark extra rate-window normalization
  complete, and set B02b2b as the next provider-normalization task.

### Validation

- Documentation/version metadata only; implementation and CI evidence are in
  `docs/rust-migration/AUDIT.md`.

## 0.81.0 (26) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Port extra rate-window payload normalization (`extraRateWindows`) to Rust for
  valid typed payloads, retaining the Python fallback for malformed/dynamic
  field shapes.
- Verify the GTK preview path with synthetic CLI data including extra windows
  after loading GTK4 and libadwaita typelibs locally.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02b2a parity tests and GTK preview
  environment/scope.

## 0.81.0 (25) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Changed

- Record the observed B02b1 merge, mark pace normalization complete, and set
  B02b2 as the next provider-payload migration slice.

### Validation

- Documentation/version metadata only; implementation and CI evidence are in
  `docs/rust-migration/AUDIT.md`.

## 0.81.0 (24) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Port provider pace-object normalization to Rust for valid typed payloads,
  retaining the Python fallback for malformed/dynamic field shapes.
- Make `tools/preview.py` use the local `.deps/` GTK typelib/runtime paths after
  the no-root bootstrap, and document system/no-root GTK4/libadwaita setup.
- Verify the GTK preview path with synthetic CLI data after loading GTK4 and
  libadwaita typelibs locally.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02b1 parity tests and the precise GTK
  preview environment/scope.

## 0.81.0 (23) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Changed

- Record the observed merge of B02a, check off its standard rate-window slice,
  and set B02b as the next provider-normalization task in the durable handoff.

### Validation

- Documentation/version metadata only; B02a behavior and CI evidence are in
  `docs/rust-migration/AUDIT.md`.

## 0.81.0 (22) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Begin B02a by normalizing standard primary/secondary/tertiary quota windows
  in Rust and routing the existing `data.py` window parser through the opt-in
  bridge, preserving known-zero versus unknown usage and Python fallbacks.
- Add direct coverage for normal payloads, missing values, placeholder truth
  semantics, UTC resets, and duration handling.

### Validation

- See `docs/rust-migration/AUDIT.md` for B02a checks and GTK smoke limitations.

## 0.81.0 (21) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Add Rust domain contracts for provider usage, detail/chart sections, credit
  events, agent sessions and spend summary/provider data.
- Route chart peaks, provider summary/error/usage properties and session running
  classification through the opt-in Rust bridge, with Python parity references.
- Add regression coverage for `max(..., default=0)` semantics, negative chart
  values, NaN iteration ordering and empty subtitle segments.

### Validation

- See `docs/rust-migration/AUDIT.md` for B01c test and smoke limitations.

## 0.81.0 (20) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Continue B01 with Rust `Pace` and `CostInfo` domain types and opt-in derived
  property routing for deficit/reserve labels and bounded usage percentages.
- Add parity cases for known pace stages, unknown stages, missing/invalid cost
  limits, and NaN/infinity percentage behavior.

### Validation

- See `docs/rust-migration/AUDIT.md` for B01b implementation evidence.

## 0.81.0 (19) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Begin B01a by porting UTC timestamp parsing, finite numeric validation and
  `RateWindow` derived properties to Rust, with opt-in PyO3 routing and Python
  compatibility fallbacks for unsupported timestamp forms and out-of-range
  integers.
- Add Rust/Python parity coverage for timezone offsets, naive/date-only/fractional
  timestamps, booleans, large values, unknown usage and quota-window labels.

### Validation

- See `docs/rust-migration/AUDIT.md` for current B01a test and smoke evidence.

## 0.81.0 (18) — 2026-10-29

Tracks upstream CodexBar 0.81.0.

### Added

- Start B00 by adding a headless Rust service-contract crate with versioned
  snapshots, safe error categories, cooperative cancellation and joined
  shutdown; no GTK/Python dependency or runtime behavior change.
- Select Tokio and latest-value watch state for async backend orchestration;
  defer the Rustls HTTP client to B06 and PTY dependency to B11.

### Validation

- See `docs/rust-migration/AUDIT.md` for the verified B00 checks and limits.

## 0.81.0 (17) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build records the backend-first plan for a
fully native Rust GTK4/libadwaita application; runtime behavior is unchanged.

### Added

- Audit the remaining Python backend and policies embedded in UI modules;
  distinguish the six opt-in integrations from full backend completion.
- Add a dependency-ordered backend/UI/cutover checklist, explicit completion
  gates, current handoff, decision log and append-only verification trail under
  `docs/rust-migration/`.
- Add root `AGENTS.md` instructions so future models read the migration records,
  claim tasks, retain evidence and update the handoff before moving on.

## 0.81.0 (16) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build ports sparkline geometry to Rust.

### Added

- Calculate sparkline coordinates through the opt-in Rust backend, preserving
  time-spaced samples, the fixed quota axis, invalid-point filtering, usage
  clamping, and the equal-timestamp fallback. GTK/Cairo drawing stays in Python.
- Add edge-case and seeded randomized parity tests, with Python fallback for
  unsupported numeric types and integers outside exact floating-point range.

## 0.81.0 (15) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build integrates the final original Rust
port: quota-history persistence and queries.

### Added

- Route history writes, cached reads, retention pruning, and sorted series
  queries through the opt-in Rust store, keeping the Python API and JSON-lines
  format. Unsupported sample inputs continue through Python.
- Cover cross-backend file compatibility, exact decimal rounding, corrupt
  records, filesystem failures, cache invalidation, concurrency, and controller
  recording with regression tests.

### Fixed

- Match Python decimal rounding in Rust history and serialize cache access with
  writes/pruning so concurrent operations cannot lose retained samples.
- Skip malformed or nonfinite history records in both backends rather than
  failing a refresh or turning invalid fields into fabricated zero samples.
- Replace the built extension atomically so rebuilding cannot overwrite a
  library mapped by a running development app.

## 0.81.0 (14) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build fixes stale system-tray content.

### Fixed

- Emit tray updates through dbus-python's supported signal API so Plasma
  refreshes the tooltip and usage icon after provider data loads, instead of
  keeping the startup “Provider data unavailable” message. Also publish menu
  layout changes and the status signal's required status argument.
- Add private-session D-Bus regression tests for tooltip, icon, status, and menu
  notifications, with a dedicated CI job that installs their dependencies.

## 0.81.0 (13) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build integrates monthly allowance
calculations into the opt-in Rust backend.

### Added

- Route monthly-window detection, local-calendar daily targets, and daily-target
  formatting through Rust while retaining Python fallback behavior for naive
  datetimes and unsupported inputs. Currency conversion continues to use the
  existing Python rate service.

## 0.81.0 (12) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build integrates Rust display formatting
and adds a direct Settings-to-dashboard navigation action.

### Added

- Route UTC display formatting helpers through the opt-in Rust backend while
  retaining Python behavior for naive/local datetimes and unsupported edge data.
- Add a visible **Return to dashboard** action to General Settings; opening the
  dashboard hides Settings and presents the main window.
- Document the Rust port checklist and distinguish completed Rust ports from
  the two remaining runtime integrations.

## 0.81.0 (11) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build refreshes the README screenshots
with synthetic data and documents the current opt-in Rust integration status.

### Updated

- Add current dashboard, compact panel, spend, sessions and provider-settings
  screenshots to the README; note that the screenshots use fixture data.
- Document which Python business-logic paths currently use Rust at runtime and
  how to build/test the optional PyO3 extension.

## 0.81.0 (10) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build routes the spend activity helpers
through Rust when `CODEXBAR_RUST_CORE=1`, while Python remains the default.

### Added

- Add PyO3 bindings for heatmap levels, weekly and cumulative totals, daily cost
  series, and activity-window alignment.
- Route the spend page's activity calculations through Rust in opt-in mode and
  add backend parity tests; retain Python behavior for non-JSON edge inputs.
- Centralize optional Rust extension loading so provider metadata and activity
  helpers share the same explicit opt-in and fail-fast behavior.
- Tray context menu: add **Check for updates**, **Restart**, **Settings** and
  **Quit** actions; the update check compares the public client version marker
  and never downloads or installs code.

### Fixed

- Tray hover now identifies the client, selected provider and each quota window,
  and includes the actual icon pixmap for hosts that cannot resolve the local
  themed icon name.
- Right-click and secondary activation now open an action panel with Settings,
  update check, restart and quit controls on hosts that delegate context menus
  to the item.
- Dashboard: Open Dashboard closes the compact tray panel first, and Settings
  buttons now create/open the Settings window even when it has not been opened
  yet.
- Provider initials now render in a theme-contrasting color rather than blending
  into the brand-colored avatar ring.
- Usage sparklines use elapsed-time spacing and a fixed 0–100% quota scale, so
  small changes no longer appear as full-height spikes.
- Manual refresh and CLI-backed Settings loading/actions now run outside GTK's
  main loop; CLI details appear when background loading completes.
- Session quota notifications now fire once when a primary quota becomes
  exhausted, and reset when it recovers. Unsupported status-check and spend
  comparison controls were removed rather than left as no-op controls; their
  preference keys remain available for portable settings round-trips.
- Tray visibility applies immediately, and the startup popover preference is
  honored after the first refresh.
- Terminal login commands now pass the executable and arguments separately,
  including the GNOME Terminal command separator.
- Tray panel uses a compact quota-card layout: less secondary detail, no tiny
  trend plots, condensed reset badges, and secondary actions grouped under More.
- Compact tray cards now use CodexBar's bundled provider logos (including the
  curated Codex mark), with accent-tinted monochrome icons and initials only as
  fallback. The full dashboard keeps its existing avatar treatment.

## 0.81.0 (9) — 2026-10-29

Tracks upstream CodexBar 0.81.0. This build begins opt-in Rust execution in the
GTK app while keeping Python as the default implementation.

### Added

- Add a PyO3 bridge for provider metadata and allow `CODEXBAR_RUST_CORE=1` to
  route provider metadata calls through Rust.
- Add Rust/Python parity integration tests and a local Rust-enabled app launch
  path.

## 0.81.0 (8) — 2026-10-28

Tracks upstream CodexBar 0.81.0. This build continues the incremental Rust
logic migration while preserving the Python implementation as the production
path.

### Added

- Port the quota history JSON-lines store, caching, querying, and retention
  pruning from `codexbar_gtk/history.py` into Rust; Python callers are unchanged.

## 0.81.0 (7) — 2026-10-28

Tracks upstream CodexBar 0.81.0. This build continues the incremental Rust
logic migration while preserving the Python implementation as the production
path.

### Added

- Port monthly allowance and daily-target calculations/formatting from
  `codexbar_gtk/pace.py` into Rust with currency conversion injected as a
  dependency; Python callers remain unchanged.

## 0.81.0 (6) — 2026-10-28

Tracks upstream CodexBar 0.81.0. This build continues the incremental Rust
logic migration while preserving the Python implementation as the production
path.

### Added

- Port the activity heatmap's level bucketing, weekly/cumulative aggregation,
  daily spend series, and Sunday-aligned window helpers from
  `codexbar_gtk/activity.py` into Rust; Python callers are unchanged.

## 0.81.0 (5) — 2026-10-28

Tracks upstream CodexBar 0.81.0. This build continues the incremental Rust
logic migration while preserving the Python implementation as the production
path.

### Added

- Port the static provider metadata, aliases, and fallback naming behavior from
  `codexbar_gtk/providers.py` into the parallel Rust core; Python callers are
  unchanged.

## 0.81.0 (4) — 2026-10-28

Tracks upstream CodexBar 0.81.0. This build begins the incremental Rust logic
migration while preserving the Python implementation as the production path.

### Added

- Add a parallel Rust core and port the formatting helpers from
  `codexbar_gtk/format.py`; no Python services are switched in this build.

## 0.81.0 (3) — 2026-10-26

Tracks upstream CodexBar 0.81.0 (released 2026-10-24, provider total 110).

### Added

- Provider catalog matches upstream 0.81.0 exactly (110/110): added
  **abliteration.ai** (`#1B1B1B`), **Chatbox AI** (`#228BE6`) and **Trae CN**
  (`#4D7CFE`).
- Tray: when an automatic selection picks one window out of several, the
  tooltip title and menu-bar progress rows now name the window compactly
  (`Codex 5h 84%`, `▇▇░ W 84%`), and keep bare titles for single-window
  providers, mirroring upstream Auto token labelling (#4743/#4750).
- Versioning: `CHANGELOG.md` records which upstream release each build tracks.

### Not portable until the CLI provides the data

- Usage & Spend session summaries with search, sort and per-session request
  accounting (#4730): the upstream CLI's `cost --group-by session` view exists
  (verified on CLI 0.79.0) but `--format json` still emits no `sessions`
  array, and GTK deliberately consumes CLI JSON only. The pure parsing is
  ready to wire once a CLI release adds sessions to the JSON payload.
- abliteration.ai / Chatbox AI live usage needs the user to `codexbar config
  login --provider abliteration|chatbox` on CLI 0.81 or newer; older CLIs
  simply show no data for them, which the app treats as unavailable rather
  than zero.

## 0.80.0 (2) — 2026-10-23

Tracks upstream CodexBar 0.80.0 (released 2026-10-23, provider total 108; Soniox
catalog entry and monthly daily-use targets already shipped in build 1's parity
sync).

### Added

- Spend page: cost history time-range selector (7 / 30 / 90 days / all),
  persisted as `spendTimeRange`, matching the macOS tool (all = every observed
  day rather than a 30-day clamp).
- Settings: new **Acknowledgements** pane listing third-party dependencies,
  mirroring the macOS About → Acknowledgements view.

### Changed

- Manual refresh no longer polls every 60 s in the background; it refreshes on
  user action only, matching the macOS app.

### Fixed

- Spend coverage no longer double-counts when the CLI reports both top-level
  and `totals` views; one representation wins.
- Coverage/gap-filling gains `historyCoverageIsEstablished` handling and
  `cost_known` / `cost_partial` flags; unpriced and incomplete days stay
  unknown, surface as "≥ known subtotal" instead of `$0`.
- A failing cost scan keeps the last usable totals plus a per-provider error
  payload instead of blanking the dashboard.
- Preferences panes construct and switch without layout crashes.

## 0.79.0 (1) — 2026-10-22

Initial standalone community front-end release.

### Added

- StatusNotifierItem tray with meter or icon+percentage, automatic ("Auto
  lane") provider selection mirroring `AutomaticQuotaSelection`.
- Provider cards, quota meters, reset countdowns, pace chips.
- Preferred currency conversion (cached live rates + offline fallback).
- Statistics time zone passed to the CLI via `TZ`.
- 12-month token activity heatmap (daily/weekly/cumulative).
- Usage & Spend dashboard with daily chart, projects, models.
- Settings panes: General, Providers, Menu Bar, Display, Notifications, Hooks,
  Plugins, Advanced, About.
- GTK4 fixes: popup monitor handling, content sizing, `raise_()` removal.
