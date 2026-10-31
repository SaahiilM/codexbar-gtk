# Native Rust migration

**Approved destination:** a Rust GTK4/libadwaita application with no Python
runtime, PyO3 bridge, or PyGObject dependency in the shipped application.
**Sequence:** complete the backend first, then migrate the UI, then remove the
legacy runtime. The upstream `codexbar` CLI remains an external dependency;
reimplementing provider fetching or credential storage is not part of this plan.

Start with the [current handoff and checklist](TASKS.md), then read the
[decision and audit log](AUDIT.md). Root [`AGENTS.md`](../../AGENTS.md) instructs
future coding agents to follow these documents.

## Actual starting point

Code baseline: `46f44d0` (PR #17), GTK build `0.81.0 (16)`. The initial planning
PR increments the build to `0.81.0 (17)` without changing runtime behavior.

The application still starts with `python3 -m codexbar_gtk`. Python is the default
backend. `CODEXBAR_RUST_CORE=1` enables Rust-backed services through
`rust-python/`; it does **not** select a complete native Rust application. B15's
original-port parity work is merged in PR #52 at `63eb17c8`, and B13c's focused
last-30 caption parity fix is merged in PR #53 at `0fc5cbb`. BG passed after
PR #54 merged at `e1abf7b`; its headless integration, transitional GTK smoke
and residual-Python audit are recorded in AUDIT E085/E086. Phase U is now
unblocked, though no native UI implementation is claimed here. Some Python
edge-input behavior remains available only through the default Python path as
described below.

The file inventory and named functions below were inspected, not just inferred
from filenames. Test results and limitations are recorded separately in AUDIT.

## Architecture and dependency direction

```text
Transitional application                   Final application
Python GTK widgets                        Rust GTK4/libadwaita widgets
  -> thin Python compatibility adapters      -> Rust backend service API
    -> rust-python (temporary PyO3)             -> Rust domain/services
      -> Rust domain/services                    -> external codexbar CLI
```

- Extend `rust-core/` for typed models and deterministic domain policies. It
  already contains local history storage; retaining that module avoids churn.
  No GTK/Python types or implicit GUI-main-loop dependency in backend APIs.
- `rust-backend/` is the headless service-contract crate, depending on
  `rust-core/`; it has no GTK/Python dependency. B00 selects Tokio for async
  orchestration and `tokio::process` for CLI children. The application owns the
  Tokio runtime; the GTK main thread must never block on backend I/O. State is
  exposed as immutable snapshots over `tokio::sync::watch` (latest-value
  semantics), with cooperative cancellation and explicit join on shutdown.
  Add `reqwest` with Rustls in B12 for the bounded read-only update check and
  reuse it for currency HTTP refresh in B06. Defer `portable-pty`
  to B11, where its platform/dependency needs can be verified against the fake
  login harness. This crate currently defines lifecycle/error/state contracts,
  not provider fetch behavior or current-app integration.
- Keep `rust-python/` a temporary, thin adapter over those APIs. Python dataclass
  construction is allowed during transition, but it must not conceal duplicated
  policy, fetching, scheduling, aggregation, or notification state.
- Plan a `rust-gtk/` binary after gate BG. It must consume the same backend API
  directly, not embed Python or invoke a Python backend process. This crate
  also does **not** exist yet. A workspace layout can be introduced separately.
- The backend publishes immutable snapshots/state; the frontend marshals them
  to its GUI thread. `watch` deliberately coalesces intermediate updates; if a
  future user-visible operation needs a lossless event stream, define a bounded
  channel contract for that operation rather than treating snapshots as events.
  B08/B10/B14 notification events use `rust_backend::event_channel()` with a
  256 item Tokio `mpsc` buffer. Producers await sends, applying backpressure;
  they never silently drop a transition. A closed receiver returns the stable
  `EventPublishError::ReceiverClosed` result. The independent `watch` stream
  remains latest-value state. The frontend drains events separately and
  marshals delivery to its UI thread. Backend DTOs contain no GTK/Python types,
  and errors use stable category/operation identifiers.
  Do not call GTK callbacks under backend locks or block the GUI on I/O.
- Inject clocks, subprocess/HTTP/browser adapters, paths, and cancellation where
  needed for deterministic tests. Prove the backend works headlessly without
  an interpreter before starting native UI implementation.

## Remaining source inventory

| Area / evidence in current Python | Backend responsibility / target |
| --- | --- |
| `data.py`: `parse_timestamp`, numeric helpers, dataclasses and derived properties | Typed domain contracts and validated timestamp/numeric handling (B01) |
| `data.py`: `provider_usage_from_payload`, detail/pace/reset-credit/plan helpers | Provider envelope normalization, windows, identity, errors and credits (B02) |
| `data.py`: `agent_sessions_from_payloads` | Session normalization and sorting (B03) |
| `data.py`: `spend_from_payloads` | Spend aggregation, provenance, coverage and known/partial states (B04) |
| `prefs.py`: `Preferences`, `DEFAULTS`, refresh intervals | Settings defaults, persistence, portable import/export and derived settings (B05) |
| `currency.py`: `CurrencyConverter`, shared converter | Rate catalog/conversion, HTTP refresh, TTL/cache, offline fallback (B06) |
| `cli.py`: `default_cli_path`, `CodexBarCLI` | Discovery, argv, TZ, timeouts, outputs/errors and all command wrappers (B07) |
| `controller.py`: quota/session/pace/credit events, cycle tracking | `NotificationPolicy::observe(&[ProviderUsage], &NotificationPreferences, DateTime<Utc>)` returns typed `QuotaThreshold`, `SessionExhausted`, `PredictivePace`, and `CreditExpiry` outcomes; GTK only delivers them (B08) |
| `controller.py`: `_ordered`, `automatic_tray_selection` and ETA/ranking helpers | Provider visibility/order and tray-quota selection (B09) |
| `controller.py`: `Controller`, `AppState` | Polling, queued refresh, cancellation, account collection, fallback scans, snapshots and recording (B10) |
| `login.py`: terminal argv, browser helpers, `ClaudeLoginSession`, auth status | PTY/process lifecycle, streamed parsing, input, cancellation, status and results (B11) |
| `updates.py`: version parsing/comparison and read-only HTTP check | Client-version service; never download/install executable code (B12) |
| `ui/spend.py`: model grouping, currency/time-range/coverage rules; `ui/app.py`: tray summaries; `ui/settings.py`: CLI workers and launch-at-login action | Extract non-widget policy/service actions still embedded in UI (B13) |
| Existing six Rust modules and Python adapters | Resolve native contract gaps/edge fallbacks, catalog drift and Rust-only behavior coverage (B15) |
| `startup.py`, `provider_icons.py`, `version.py`, `__main__.py`, remaining `ui/*.py` | Native bootstrap, assets, metadata, desktop/platform integration and widgets in phase U |
| `run.sh`, `scripts/install.sh`, `scripts/bootstrap-deps.sh`, `tools/*.py`, CI and tests | Native build/install/dev tooling and final removal of Python dependencies in phase C |

Do not mark backend completion just because top-level non-UI modules are ported:
B13 explicitly searches `ui/` for leftover backend decisions and workers.

## Compatibility and safety requirements

- Preserve unknown/unavailable versus known zero usage/cost, partial subtotals,
  scan provenance, and retained previous data on partial refresh failures.
- Preserve old/new CLI envelopes without double-counting repeated totals.
  Raw provider fields needed by detail sections must survive normalization.
- Freeze timestamp acceptance, UTC/local-calendar behavior, DST/reset boundaries,
  finite-number rules, booleans versus numbers, large integers, rounding,
  stable ordering, and invalid-input behavior with parity fixtures. Do not
  silently turn a fallback into a Rust error or fabricated zero.
- Preserve `~/.config/codexbar-gtk/settings.json`, history JSON-lines, currency
  cache format, portable preference documents, command-line flags, environment
  overrides, external CLI discovery, account identity and provider ordering.
  Use isolated copies to test changes; never run migration tests on real data.
- Keep argv boundaries; never shell-concatenate credentials or commands. Ensure
  timeout/cancel reaps processes and closes PTYs/pipes. No secrets in tracing.
  Test login with fake processes, not actual browser authorization.
- Preserve the user-facing application identity and service paths unless an
  explicit compatibility decision and migration test approve a change.
- UI phase must retain the Settings-to-dashboard action, tray signal signatures
  and live updates (PR #15), host re-registration, settings actions and all
  existing pages. A backend task must not redesign the screens.

### B15 edge-input characterization

B15 was merged normally in PR #52 at
`63eb17c8ea13c563c587cf9687a4877f1b5b47ff`; exact head
`791154691213b9592e799e4b5cdec962409ed995` passed `test` and `tray-dbus`.
The compatibility limits below remain part of the accepted Rust opt-in
contract (AUDIT E081/E083). B13's screenshot review also found a token-count
suffix on the Rust last-30-days caption that Python does not render. B13c
removes only that display suffix while preserving the structured DTO field;
see the active handoff in TASKS.md.

The Python implementations remain the default and unchanged parity references.
In Rust opt-in mode, provider metadata and currency conversions read the Rust
catalogs; the Python copies are used only by default mode and catalog parity
tests. The known provider IDs are ASCII, and catalog parity tests cover all 110
providers, aliases and supported currencies.

- **Large numbers:** Python's `_optional_int` rejects booleans and non-numeric
  values, converts numeric values through `float`, then returns an integer.
  Thus `2**53 + 1` rounds to `2**53`, `2**70` remains representable,
  `2**63 - 1` rounds up to `2**63`, and `10**1000` converts to `None`. Rust
  domain counters and window lengths use
  signed 64-bit values. A value that does not fit, or an aggregate that exceeds
  that range, raises an explicit overflow error; the refresh controller reports
  stable `cli_usage_window_overflow` or `cli_cost_counter_overflow` operations
  and retains its last good snapshot. Activity cumulative and weekly totals are
  checked `i64` sums. Token display accepts signed 128-bit inputs; larger
  Python integers remain formatable in Python but raise an explicit overflow in
  Rust opt-in. Numeric formatting uses finite `f64` semantics, matching the
  Python formatting helpers for large finite integers; inputs outside the
  finite float range fail clearly.
- **Timestamps and local time:** Python 3.12 `datetime.fromisoformat` accepts
  extended/basic calendar and week dates, hour/minute/second times, a single
  character date/time separator, fractional seconds, and offsets with seconds
  or fractional seconds. Rust tests those forms and normalizes parsed values to
  UTC; naive provider strings also mean UTC in `parse_timestamp`. Current CLI
  payloads use ordinary RFC3339 extended timestamps. Monthly pace divides by
  local calendar days, not 24-hour periods; fixture cases cover New York's
  spring-forward, fall-back and repeated 01:30 hour. Rust formats direct
  datetime helper inputs only when they are UTC-aware. Production timestamps
  reach those callers through `parse_timestamp`, so they are already UTC.
- **Charts:** the Python geometry helper accepts finite `Fraction` values and
  integers wider than `f64`'s exact-integer range. Rust opt-in filters the same
  invalid points, subtracts the first timestamp before conversion, and then
  uses finite `f64` coordinates. Fractions and wide epochs are covered by
  parity tests. The production chart reads floating-point timestamp/percentage
  samples from history and integer GTK dimensions; it cannot receive a
  `Fraction` from JSONL. Values that cannot convert to finite Python floats
  overflow in both paths.
- **Persisted history:** production appends Unix-second floats and percentage
  floats rounded to two decimals as JSONL. The persisted compatibility fixture
  also covers blank/corrupt rows, defaulted fields, numeric strings, booleans,
  non-finite values and a large integer JSON token; Rust and Python read the
  same retained samples. A direct Python append can write `10**1000` as JSON
  integer text but then reads no finite sample; Rust rejects that write up
  front because the value cannot be represented as `f64`. Rust's direct store
  API takes text paths and signed 64-bit retention days. Bytes paths and
  retention values outside `i64` are rejected with clear errors; normal app
  configuration uses text paths and the default 30-day period.
- **Unknown provider labels:** Rust fallback casing uses checked-in Unicode
  15.0 properties and full mappings, exhaustively compared with Python 3.12 for
  every cased codepoint. The Python 3.10/3.11 runtimes supported by the app use
  older Unicode databases, so an unknown, non-ASCII provider ID can get a
  different fallback label there. The known provider catalog is ASCII and is
  unaffected. The Unicode tables record their UCD source and license.

These Rust opt-in limits are explicit and covered by boundary tests; they do
not narrow the default Python path. The normal app data paths are characterized
separately from direct helper calls so the next migration gate can review any
remaining compatibility differences deliberately.

## Definition of done for an implementation slice

1. Record stable task ID, scope, dependencies, branch, and policy decisions.
2. Add characterization/parity fixtures before changing behavior; write native
   Rust tests, including errors/cancellation/concurrency where applicable.
3. Route the current application caller through Rust in opt-in mode, keeping
   only a thin compatibility adapter. A parallel Rust file alone is not done.
4. Pass both backend suites and Rust checks. Add required tests to CI; report
   skipped tests and missing dependencies, not just a passing process status.
5. Exercise the affected path in the actual GTK app with synthetic data. Record
   what was inspected and what was not; do not imply exhaustive interaction or
   real-provider testing from a screenshot.
6. Update TASKS handoff, append AUDIT evidence, update README/status, increment
   the GTK build in both locations and record the build in CHANGELOG.
7. Push a focused PR, observe CI, merge, and verify `main`. A checked task requires
   merged evidence; use `active` or `verified, PR pending` until then. Never
   predict a merge in the committed audit entry; its PR link is authoritative.

## Validation commands available today

From the repository root (source `~/.cargo/env` if Cargo is not on PATH):

```sh
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo fmt --manifest-path rust-python/Cargo.toml -- --check
cargo test --manifest-path rust-core/Cargo.toml --locked
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
cargo clippy --manifest-path rust-python/Cargo.toml --all-targets --all-features -- -D warnings
./scripts/build-rust-core.sh
python3 -m unittest discover -s tests -v
CODEXBAR_RUST_CORE=1 python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -p test_tray_signals.py -v
git diff --check
```

The tray suite requires `dbus-run-session`, dbus-python and PyGObject. CI runs a
separate dependency-equipped job. Some other environments skip it; record that.
The extension build helper must retain atomic replacement for running apps.
The B00 service crate checks are:

```sh
cargo fmt --manifest-path rust-backend/Cargo.toml -- --check
cargo test --manifest-path rust-backend/Cargo.toml --locked
cargo clippy --manifest-path rust-backend/Cargo.toml --all-targets --all-features -- -D warnings
```

Add the corresponding format/test/Clippy commands for each new crate to CI;
no workspace commands are assumed.

## Stage gates

- **BG — backend complete:** PASSED after PR #54 merged at
  `e1abf7b3e1db0e7f23e3be063a3ef067d85be1a1`. B00–B15 accepted; Rust-only
  headless end-to-end tests cover fake CLI/HTTP/PTY flows without Python, GTK,
  or PyO3. Existing GTK app consumes the Rust backend in opt-in mode with
  fixture smoke evidence.
  No hidden Python policy/service work remains. See AUDIT E085/E086 for B11's
  Actions startup failure and the separately verified local evidence.
- **UG — native UI complete:** all U tasks accepted against the same backend;
  functional/visual parity and Wayland/X11/D-Bus behavior verified. Preserve the
  old app until this gate is passed. BG has passed, so Phase U may begin; UG is
  not yet passed.
- **CG — cutover complete:** native release/install works without Python,
  PyGObject or `_rust_core.so`; preferences/history survive the switch; native
  CI and packaging are proven. Remove bridge, fallback implementations, Python
  UI and obsolete Python tooling only with rollback documentation and tests.
