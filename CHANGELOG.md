# Changelog

Client-side changelog for the CodexBar GTK front-end. Each entry keys a build
number (`CURRENT_PROJECT_VERSION`) to the upstream macOS CodexBar release its
short version tracks, so "which version has what" maps cleanly onto both trees.

## Unreleased

### Added

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
