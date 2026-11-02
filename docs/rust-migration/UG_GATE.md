# UG native UI gate ledger

**Status: NOT PASSED.** All U01–U08 implementation PRs have merged, but the
required UI action and Wayland evidence is incomplete. Python remains the
default launcher. This ledger records observed evidence, limits and the exact
remaining work; backend unit tests do not count as GTK interaction evidence.

## Baseline and merge state

- Live `origin/main` for the build-70 U05 portal evidence follow-up is
  `6fc6833059cf4ac1808f7f51fe16bcff66eb7867`, U05 PR #70's normal merge
  (E135). Its exact head `800dc57915216f90bfec18178ef26c7261299045` passed
  `test` and `tray-dbus` in run `41377674020`; reviews/comments were empty.
  Build-69 Wayland results remain in E133 and do not pass UG.
- Build-67 U05 Xvfb results remain in E123; those actions do not pass UG.
- U08 PR [#66](https://github.com/SaahiilM/codexbar-gtk/pull/66) merged at
  `5de83def98ad5ebd09035ee9120698fbf710541c`, the prior base for UG PR #67.
  Exact head `fb89f0b6c702dff92992916e14951b385f5189bf` passed both
  required jobs, `test` and `tray-dbus`, in Actions run
  [41345048163](https://github.com/SaahiilM/codexbar-gtk/actions/runs/41345048163).
  The live repository had no open PRs at assessment start.
- The exact-head CI evidence is distinct from Wayland evidence. Native Xvfb
  smokes and the native private-bus lifecycle are part of the `test` job;
  CI does not run a Wayland compositor. The `tray-dbus` job is the legacy
  Python tray-signal suite.
- Build-66 captures and local smoke scripts use synthetic CLI data and isolated
  home/config/cache/runtime directories. No real account, credential or API key
  was used. Runtime SVG rendering needs `librsvg2-common`; carry it into C01
  package verification.
- Inherited migration limits remain visible: B11's zero-job Actions startup
  failures are failures, with the separate workflow-equivalent evidence recorded
  in E086; B15's accepted Rust opt-in edge-input bounds are recorded in E081/E083.
  Python remains the default, so this gate does not erase those compatibility
  limits. Legacy history rows also retain the documented missing-knownness
  ambiguity from U02.

## Evidence labels

- **PASS** — a GTK action was exercised and its state/result was checked.
- **CAPTURE** — a valid synthetic image exists, without claiming every action
  on that surface was exercised.
- **PARTIAL** — some states/actions passed; listed gaps remain.
- **OPEN** — no adequate GTK interaction evidence yet.
- **UNSUPPORTED HERE** — the current host/compositor blocks the stated capture
  or input method. This does not mean the product feature is unsupported.

## Page and action matrix

The README feature list was cross-checked against the Python UI entry points
`codexbar_gtk/ui/app.py`, `window.py`, `popup.py`, `tray.py`, `settings.py`,
`spend.py`, `sessions.py`, `login_dialog.py`, `cards.py` and
`x11_position.py`, then mapped to native `rust-gtk/src/main.rs`,
`dashboard_widget.rs`, `panel_widget.rs`, `usage_pages.rs`, `settings_window.rs`,
`tray.rs` and `x11_placement.rs`. This source map defines the interaction
surface to accept; it does not treat source or backend tests as runtime proof.

| Surface and actions | X11/Xvfb | Actual KDE Wayland | Private D-Bus / result |
| --- | --- | --- | --- |
| Dashboard/provider cards: startup, synthetic usage, refresh, central routes, responsive layout | **PASS.** U08 1× and 2× dashboard smokes passed in exact-head CI and locally; build-66 page/routing smokes also passed. At 560 logical pixels the secondary subtitle ellipsizes, while source label, actions, values and cards remain readable/reflowed (E116). Existing captures: [`u08-native-dashboard-iconpercent-xvfb.png`](screenshots/u08-native-dashboard-iconpercent-xvfb.png), [`u08-native-dashboard-2x-xvfb.png`](screenshots/u08-native-dashboard-2x-xvfb.png). | **PASS at session default scale.** U08 fixture smoke completed refresh, registered SNI, routed to Dashboard, captured and quit cleanly: [`u08-native-dashboard-wayland.png`](screenshots/u08-native-dashboard-wayland.png). No CI Wayland run. | **PASS in #66 test job** for native lifecycle; SNI release observed in the Wayland smoke. |
| Compact panel: SNI toggle/open, focus, keyboard dismissal, anchor/placement | **PASS for the build-68 matrix.** The Xvfb/private-bus smoke covers hidden/visible × `Activate`/`SecondaryActivate`/`ContextMenu` × preference off/on with synthetic CLI counts. It asserts X11 bottom-right placement and focus before sending Escape. The broader native Gio/lifecycle smoke also passes. Build-66 timeouts and `X_SetInputFocus BadMatch` remain historical E120 evidence; build 68 passed with the updated focus check. See [`u04-panel-activate-open-native-xvfb.png`](screenshots/u04-panel-activate-open-native-xvfb.png) and [`u04-panel-context-open-native-xvfb.png`](screenshots/u04-panel-context-open-native-xvfb.png). | **CAPTURE/PARTIAL.** Live session-bus calls exercised all three SNI methods with fixture CLI counts. A synthetic panel capture after activation/context events is valid; Wayland placement remains compositor-owned. No pointer/keyboard action is claimed because this compositor rejects `wtype` input. See [`u04-panel-activate-open-wayland.png`](screenshots/u04-panel-activate-open-wayland.png). | **PASS** in exact-head Actions run `41373288090` for `test` and `tray-dbus`, plus local private-bus routing/coordinate dispatch and Xvfb refresh matrix. |
| KDE RemoteDesktop portal input path | **AVAILABLE; consent not granted.** Session D-Bus reports RemoteDesktop v2 and `AvailableDeviceTypes=7` (keyboard, pointer and touchscreen); installed backend is `xdg-desktop-portal-kde` 6.8.1. Direct launch showed an unidentifiable-app warning and was canceled without approval. A second test used the documented systemd app scope plus a temporary matching desktop entry and produced a prompt naming the synthetic test app. | The named `Start` request remained open for 360 seconds without approval and timed out. The test requested pointer+keyboard only, `persist_mode=0`, with no ScreenCast or clipboard. No input event was sent. General Settings and portal-dialog images are **CAPTURE only**; synthetic action rows remain **OPEN**. See E136. | **OPEN.** No portal session was approved; cleanup closed the request and removed the fixture HOME and temporary desktop entry. |
| Usage/dashboard route and provider detail interactions | **PARTIAL.** Central route and refresh smoke passed; dashboard fixture screenshots exist. Not every provider card detail/hover/action is independently asserted in the UG matrix. | **CAPTURE/PARTIAL.** Dashboard capture and route smoke passed at default scale. No full Wayland pointer/keyboard action matrix. | **PASS for app/SNI lifecycle**; per-provider UI action coverage remains open. |
| Sessions: loading, success, empty, first-scan failure, refresh, navigation | **PASS for synthetic states and refresh/navigation** in `smoke-native-usage-pages.sh` and U04 evidence. | **CAPTURE/PARTIAL.** Fresh `--page sessions` captures show loading, running-session success, empty and first-scan failure. Synthetic refresh action and tray release were exercised in the fixture run, but stale retained-error frames were excluded; no Wayland pointer/keyboard action pass. | **PASS for startup/quit and SNI release** in the Wayland fixture smoke; exact-head CI private-bus lifecycle also passed. |
| Usage & Spend: loading/success/partial/empty/errors, four spend ranges, three heatmap modes, tooltip and refresh | **PASS for current synthetic matrix.** The build-66 script passed with visible pointer clicks on 7/30/90 days and All, Daily/Weekly/Cumulative, keyboard focus/range check, tooltip, refresh, empty and retained-error states. The four range and three mode screenshots are in `screenshots/ug-build66/`. | **CAPTURE/PARTIAL.** Valid startup captures show success, refreshing, empty and first-scan failure; fixture refresh was invoked. Wayland range/mode/tooltip interactions are **OPEN** because controlled pointer/keyboard input was not available. | **PASS for app/SNI lifecycle** in the fixture run; no claim that D-Bus unit coverage substitutes for UI actions. |
| Settings — General: refresh-on-panel-open, startup, currency, refresh interval, show panel on start | **PASS on Xvfb.** Build-66 smoke persisted refresh-on-panel-open, USD and launch-at-login create/remove. Build-67 smoke clicked and persisted refresh interval `5m` and show-on-start on/off; the launch entry remains isolated to a temporary home. See [`u05-build67-general-actions-xvfb.png`](screenshots/u05-build67-general-actions-xvfb.png). | **CAPTURE only.** Build 69 captured General at default Wayland scale; build 70 captured the same page from its isolated synthetic app. The named RemoteDesktop consent request timed out without approval, so no Wayland preference action is counted. See E133, E136 and [`u05-build70-settings-general-wayland.png`](screenshots/u05-build70-settings-general-wayland.png). | **PASS for isolated Settings actor writes**; no preference changes escape the temporary home. |
| Settings — Providers: enable/disable, source selection, API-key entry/visibility, provider login | **PASS on Xvfb with synthetic fixtures.** The provider switch and source selector reached the fixture CLI; API-key Apply reached the CLI using a randomized synthetic value that was checked absent from preferences and logs. A synthetic PTY sign-in completed and the GTK status handler reported “Sign-in completed.” before capture. No real credentials or auth output were used. See [`u05-build67-provider-actions-xvfb.png`](screenshots/u05-build67-provider-actions-xvfb.png), [`u05-build67-login-complete-xvfb.png`](screenshots/u05-build67-login-complete-xvfb.png). | **OPEN.** No Wayland provider-action evidence. | Fixture CLI calls, secret redaction and handler-level login result were asserted by the Settings smoke. |
| Settings — Menu Bar: icon style/source, provider row style, tray visibility | **PASS.** Four visible controls were clicked and the isolated preference JSON verified: `iconPercent`, `automatic`, `details`, and `showTray=false`. See [`settings-menu-bar-actions-xvfb.png`](screenshots/ug-build66/settings-menu-bar-actions-xvfb.png). | **OPEN for actions.** No Wayland menu-bar control interaction. | Preference writes passed through the native Settings actor in an isolated home. |
| Settings — Display: usage bar, reset-time format, workday tick style, quota burndown | **PASS on Xvfb.** Build-66 covered the original four controls; build 67 also changed workday-count, pace visibility, hide-account and both numeric quota thresholds, then verified isolated preference writes. See [`u05-build67-display-actions-xvfb.png`](screenshots/u05-build67-display-actions-xvfb.png). | **OPEN for actions.** | Settings actor persistence passed for the tested values. |
| Settings — Notifications: four preference switches and “Send a test notification” | **PASS.** All four switches were toggled off. The button delivered to an in-process synthetic `org.freedesktop.Notifications` service on the private session bus; the receiver log contained the expected test summary and the UI displayed “Test notification sent.” See [`settings-notification-received-xvfb.png`](screenshots/ug-build66/settings-notification-received-xvfb.png). | **OPEN for actions.** | **PASS for this UI notification action** on the private bus. Separate from the tray registration lifecycle check. |
| Settings — Usage & Spend: local cost scanning and statistics time zone | **PASS.** The GTK toggle was changed to off and a non-default timezone was selected/persisted (`Africa/Abidjan`). See [`settings-usage-spend-actions-xvfb.png`](screenshots/ug-build66/settings-usage-spend-actions-xvfb.png). | **OPEN for actions.** | Settings actor persistence passed for tested values. |
| Settings — Hooks | **PASS on Xvfb for the global `Enable hooks` switch and rules display.** The GTK switch was clicked off and back on; the fixture asserted `hooks disable` and `hooks enable` CLI calls and temporary state (`false`, then `true`). Build 67 also captured the empty rules state after selecting an empty fixture. See [`u05-build67-hooks-actions-xvfb.png`](screenshots/u05-build67-hooks-actions-xvfb.png) and [`u05-build67-hooks-empty-xvfb.png`](screenshots/u05-build67-hooks-empty-xvfb.png). Configured rule rows are display-only. | **OPEN.** On build 69, AT-SPI reported Hooks selected while the visible capture stayed on General; the Hooks switch action caused no CLI call/state change. A bounded KWin fake-input click also produced no observable change. This is not counted as a product pass or failure because no input action was verified (E133). | The tested switch persisted through the synthetic CLI fixture on Xvfb/private D-Bus. |
| Settings — Plugins | **PASS for read-only populated/empty/loading/error states on Xvfb.** The fixture controlled each response state and the smoke waited for the async rows before capture. There is no plugin mutation operation or click requirement. See the four [`u05-build67-plugins-*-xvfb.png`](screenshots/u05-build67-plugins-populated-xvfb.png) captures. | **OPEN.** No Wayland plugin-list state capture. | No plugin mutation action exists to verify. |
| Settings — Advanced: CLI path, import, export, reset | **PASS on Xvfb.** The visible CLI-path Apply control reconfigured to the same synthetic executable and persisted the path. A visible Save chooser accepted the synthetic export path and the resulting JSON was checked. Valid and empty synthetic fixtures were selected in a visible import chooser; known-key overlay, unrelated preference retention, unknown-key omission and unchanged autostart were verified. Reset cancel/confirm and defaults were checked while preserving autostart. See [`u05-build67-cli-path-actions-xvfb.png`](screenshots/u05-build67-cli-path-actions-xvfb.png), [`u05-build67-export-chooser-xvfb.png`](screenshots/u05-build67-export-chooser-xvfb.png), [`u05-build67-import-selected-xvfb.png`](screenshots/u05-build67-import-selected-xvfb.png), and [`u05-build67-reset-status-xvfb.png`](screenshots/u05-build67-reset-status-xvfb.png). | **OPEN.** No Wayland Settings action was exercised. | The Settings actor used a temporary home; real credentials were absent from exported JSON, preferences and logs. |
| Settings — About, Acknowledgements and central About route | **PASS for capture/navigation.** All pages captured; central About route opened. The build-67 About capture shows `0.82.0 (67)` in [`u05-build67-about-xvfb.png`](screenshots/u05-build67-about-xvfb.png). | **OPEN beyond General capture.** | No additional bus contract. |
| Update-check action and result | **PASS on Xvfb.** The Gio action fetched the synthetic marker from a loopback-only server, asserted the request arrived and checked the visible “Update available” result. See [`u05-build67-update-result-xvfb.png`](screenshots/u05-build67-update-result-xvfb.png). | **OPEN.** | No public network request was made. |
| Login/browser, restart and quit actions outside the tested launch-at-login path | **PARTIAL.** Build 67 exercised synthetic terminal login completion and asserted the GTK result; exact-head CI includes native fake terminal/restart/shutdown coverage; launch-at-login was tested locally. Browser OAuth is not tested with real credentials. | **PARTIAL.** App quit and tray release passed; login/browser/restart interactions were not exercised in Wayland. | Synthetic auth values were ephemeral and absent from captures/logs; native teardown evidence remains E116/E120. |

### Cross-surface routes and actions

| Action | X11/Xvfb | Actual Wayland | Evidence type |
| --- | --- | --- | --- |
| Refresh | Usage/Spend and Sessions refresh actions were exercised against delayed, empty and failing synthetic CLI responses; state changes were asserted and captured. | The fixture invoked the Gio refresh action during the Sessions/Spend run and checked CLI completion; no pointer/keyboard action. | Native app action plus GTK state capture on Xvfb; action invocation only on Wayland. |
| Dashboard, Settings, About and page routes | Dashboard, Settings, About, Sessions and Spend routes were exercised through native Gio actions and visible GTK windows. Dashboard keyboard shortcuts were covered by U08. | U08 opened Dashboard from its Wayland fixture; Sessions, Spend and Settings were started directly for captures. Cross-page Wayland navigation is not interaction-verified. | Route-level smoke is not equivalent to clicking every navigation button. |
| Restart and quit | U08 exact-head CI exercised restart/shutdown and tray teardown with synthetic processes. | Quit and tray-name release were checked after each fixture; restart was not exercised. | Native lifecycle evidence; no provider credentials. |
| Update check | **PASS**; the visible Gio action result and request to a local synthetic version server are asserted in the build-67 Settings smoke. | **OPEN**. | No public network request was made. |

## Capture inventory and provenance

Build-66 Xvfb screenshots were captured after rebuilding the native binary from
this worktree at `VERSION` build 66. They use fixture-only CLI responses and the
isolated temporary home created by the smoke scripts; each was visually
inspected before inclusion.

- Settings panes and tested actions: `settings-general-xvfb.png`,
  `settings-providers-xvfb.png`, `settings-menu-bar-xvfb.png`,
  `settings-menu-bar-actions-xvfb.png`, `settings-display-xvfb.png`,
  `settings-display-actions-xvfb.png`, `settings-notifications-xvfb.png`,
  `settings-notification-received-xvfb.png`, `settings-usage-spend-xvfb.png`,
  `settings-usage-spend-actions-xvfb.png`, `settings-hooks-xvfb.png`,
  `settings-hooks-actions-xvfb.png`, `settings-plugins-xvfb.png`,
  `settings-advanced-xvfb.png`,
  `settings-acknowledgements-xvfb.png`, `settings-about-xvfb.png` and
  `settings-central-about-xvfb.png`.
- Spend range and heatmap actions: `spend-range-7-days-xvfb.png`,
  `spend-range-30-days-xvfb.png`, `spend-range-90-days-xvfb.png`,
  `spend-range-all-xvfb.png`, `heatmap-daily-xvfb.png`,
  `heatmap-weekly-xvfb.png` and `heatmap-cumulative-xvfb.png`.
- Spend/Sessions state and interaction captures: `spend-loading-xvfb.png`,
  `spend-success-xvfb.png`, `spend-partial-retained-error-xvfb.png`,
  `spend-empty-xvfb.png`, `spend-tooltip-xvfb.png`,
  `sessions-loading-xvfb.png`, `sessions-success-xvfb.png`,
  `sessions-retained-error-xvfb.png` and `sessions-empty-xvfb.png`.
- Actual KDE Wayland captures: fresh synthetic Sessions success and Spend
  success captures were supplied from the U08 source and personally inspected;
  separate fresh starts captured Sessions loading/empty/first-scan failure and
  Spend refreshing/empty/first-scan failure. The General Settings capture is
  also a fresh synthetic startup. These files are
  `sessions-success-wayland.png`, `sessions-loading-wayland.png`,
  `sessions-empty-wayland.png`, `sessions-first-scan-failure-wayland.png`,
  `spend-success-wayland.png`, `spend-refreshing-wayland.png`,
  `spend-empty-wayland.png`, `spend-first-scan-failure-wayland.png` and
  `settings-general-wayland.png`.
- Excluded stale retained-error frames, a prior 5-second Sessions spinner,
  screenshots showing the wrong Spend state after a repeated capture, and the
  forced-2× black capture. No capture from the read-only acceptance worktree's
  uncommitted files or `.deps` symlink was copied.

All included images are under [`screenshots/ug-build66/`](screenshots/ug-build66/).
U08's original dashboard captures remain under `screenshots/` and are referenced
above. Xvfb screenshots are build 66; Wayland state captures were made from the
U08 build-65 runtime before the metadata-only build-66 bump. The GTK runtime code
did not change between those captures.

Build-67 follow-up captures are under `screenshots/` and use synthetic
provider/auth/CLI/preferences fixtures in an isolated home. The 36 files named
`u05-build67-*.png` cover the Settings panes and actions, provider source/API-key
and login flow, visible import/export chooser paths, import/reset outcomes,
Hooks and Plugins states, and the loopback update result. The login-complete
image was recaptured after the GTK handler-level success assertion. These are
Xvfb captures, not Wayland interaction evidence. `.gitignore` ignores `*.png`,
so the PR stages the intended files explicitly with `git add -f`.

Build-68 panel captures are synthetic and were made with the native build from
this branch. The Xvfb Activate-open and ContextMenu-open frames are from the
two-preference/three-method interaction matrix; the live KDE Wayland capture
shows the focused panel after SNI activation/context events. The Wayland fixture
checked synthetic usage-call increments for each opening/context event and no
increment when `Activate` closed the visible panel. Pointer/keyboard delivery
remains open because `wtype` is unsupported by the current compositor; these
images do not claim pointer/keyboard parity.

Build-69 live KDE Wayland capture uses the native build with isolated
HOME/config/cache and synthetic CLI responses. It shows the General Settings
page only. The AT-SPI Hooks selection and KWin fake-input click are excluded as
action evidence because neither produced a verified visible page or backend
result. The single accepted build-69 capture is
[`u05-build69-settings-general-wayland.png`](screenshots/u05-build69-settings-general-wayland.png).

Build-70 live KDE Wayland captures are also synthetic. The Settings image
shows the General page from a native build-70 process with temporary
HOME/config/cache. The portal image shows the named KDE consent prompt
requesting keyboard and pointer. No approval arrived before its 360-second
timeout, so neither capture proves an action or preference change. Both PNGs
are force-added because `.gitignore` ignores `*.png`:
[`u05-build70-settings-general-wayland.png`](screenshots/u05-build70-settings-general-wayland.png),
[`u05-build70-remote-desktop-consent-prompt-wayland.png`](screenshots/u05-build70-remote-desktop-consent-prompt-wayland.png).

## Wayland limits and live-session ownership

- Before each earlier Wayland capture run, D-Bus ownership checks showed
  `com.steipete.CodexBarGTK`, `org.kde.spectacle` and
  `org.kde.StatusNotifierItem-codexbar-gtk` unowned. Captures used one app at a
  time, fresh fixture homes, ordinary one-shot Spectacle captures, and the
  app's normal quit path. After cleanup all three names were unowned and no
  native app or Spectacle process remained. The sole capture slot is released.
- Build-69 preflight confirmed the session application name was unowned before
  starting the synthetic Settings fixture; its owner then resolved to that
  fixture PID. `org.kde.spectacle` was unowned and no Spectacle process existed
  before each one-shot active-window capture. The unrelated pre-existing
  `codexbar-linux --usage` process was left untouched. Graceful app quit, private
  AT-SPI bus shutdown, and trap cleanup removed the fixture HOME/runtime. After
  cleanup the CodexBar and Spectacle names were unowned, fixture processes were
  gone, and the sole build-69 slot was released (E133).
- Build-70 preflight confirmed the Settings app, Spectacle and tray SNI names
  were unowned before launch. The initial unidentifiable portal prompt was
  closed without approval. For the named request, the app ran in
  `app-orchestrated-com.steipete.CodexBarGTK-u05build70.scope`; the temporary
  matching desktop entry was removed by a trap when `Start` timed out after
  360 seconds. The portal session closed, fixture HOME was removed, and the
  app, Spectacle and tray SNI names/processes were unowned afterward. The
  unrelated pre-existing `codexbar-linux --usage` process was left running.
- Default-scale KDE Wayland is **supported and passed** for the U08 dashboard
  smoke and the listed page-state captures. Forcing `GDK_SCALE=2` yielded a
  solid-black capture and is **UNSUPPORTED HERE** as usable 2× evidence; do not
  generalize that result to default Wayland.
- `wtype` is absent from the current PATH; E120 records its earlier rejection
  of this compositor's virtual-keyboard protocol. Build 69's private AT-SPI
  actions returned success without a visible switch/result change, and one
  KWin fake-input click sent to the synthetic window produced no observable
  action. The compositor advertises KWin fake-input v6, whose protocol permits
  the compositor to ignore untrusted requests. Wayland pointer/keyboard action
  evidence remains **OPEN/UNSUPPORTED HERE**; the no-op attempts are not proof
  of either product failure or UI parity.
- Build-70 preflight found xdg-desktop-portal 1.18.4 and KDE backend 6.8.1;
  RemoteDesktop v2 reported `AvailableDeviceTypes=7`. Direct launch showed an
  unidentifiable-app warning and was closed before approval. A second launch
  used systemd's documented
  `app[-launcher]-<ApplicationID>-<random>.scope` convention and a temporary
  `NoDisplay=true` desktop entry matching the native app ID. KDE then named
  the caller “CodexBar GTK build 70 synthetic interaction test.” The request
  asked only for keyboard and pointer with `persist_mode=0`, no ScreenCast or
  clipboard. No approval arrived during the 360-second `Start` request; it
  timed out and no input was sent. See E136 and the [RemoteDesktop portal
  interface](https://github.com/flatpak/xdg-desktop-portal/blob/main/data/org.freedesktop.portal.RemoteDesktop.xml),
  [host app registry release note](https://github.com/flatpak/xdg-desktop-portal/blob/main/NEWS.md#changes-in-1194),
  and [systemd desktop app-scope convention](https://systemd.io/DESKTOP_ENVIRONMENTS/).
- CI currently has Xvfb native smokes only; it cannot close any Wayland row.

## Local checks and failures retained

- Passed after the build-66 version bump: native GTK `cargo build` with the
  extracted GTK SDK; `bash -n` for the changed Xvfb smoke scripts;
  `scripts/smoke-native-settings.sh` under Xvfb plus `dbus-run-session`; and
  `scripts/smoke-native-usage-pages.sh` under Xvfb/private D-Bus. The Settings
  smoke verified visible action changes, JSON persistence, the global Hooks
  switch off/on through synthetic `hooks disable`/`hooks enable` calls, private
  notification delivery, launch-at-login create/remove, pane rendering and
  central About. The off-state Hooks screenshot was visually inspected. The
  Plugins screenshot shows one non-empty fixture row only; empty/loading/error
  list states remain untested. The first attempt using the U04 `.deps` Xvfb
  tools lacked the bundled `libxdo.so.3` loader path and timed out before UI
  interaction; the passing rerun added that existing `.deps` library directory
  to `LD_LIBRARY_PATH` without changing that worktree.
  The Spend smoke clicked and captured all four ranges and three heatmap modes,
  tooltip, loading/success/partial/empty/error and navigation states.
- The build-66 panel timeout (`/tmp/tmp.RU7wtzLQMQ`), focus/Escape then Settings
  timeout (`/tmp/tmp.ymZauUWFLQ`), and `X_SetInputFocus BadMatch` remain
  historical failures. Build 68's method matrix and updated broad native GTK
  smoke both passed locally, including focus verification before Escape; this
  later result does not rewrite the earlier observations.
- Xvfb emitted DRI3 and portal/FUSE warnings; the successful smoke exit status
  is recorded separately from those environment warnings.
- Build-67's smoke uses GTK 4.14.5 and libadwaita 1.5.0; `ldd` resolves the
  native binary to the system `libgtk-4.so.1` and `libadwaita-1.so.0`. In this
  runtime `GTK_USE_PORTAL=0` did not prevent portal service activation, so no
  “no portals” behavior is claimed. The harness creates its private synthetic
  `XDG_RUNTIME_DIR` before `dbus-run-session`; visible selected-path chooser
  completion and exported JSON are asserted independently of portal warnings.
- Build-68 local checks passed: Rust core (85), backend (85 plus one end-to-end),
  PyO3 and GTK unit suites; ignored GTK artwork/accessibility tests under Xvfb;
  Python default and Rust-backend suites (214 each; default skips 21); strict
  Clippy for all four Rust crates; build-rust-core; the native SNI matrix and
  broader Gio smokes; dashboard at 1×/2×; Usage & Spend/Sessions; and Settings.
  The build-68 Settings run initially exposed a stale update fixture fixed to
  derive the next build from `VERSION`; the rerun passed. U04 PR #69 exact-head
  `test` and `tray-dbus` both passed in run `41373288090`; review threads were
  empty (E132).
- The broader exact-head #66 Rust, Python, Clippy, build, native GTK and tray
  results belong to U08 E116–E119, not to this gate ledger update. U04 PR #69's
  exact-head required checks passed in run `41373288090` (E132).
- Build-70 local checks: `cargo fmt --check` for all four Rust crates and
  `git diff --check` passed. `cargo test` passed for rust-core (85),
  rust-backend (85 plus 1 end-to-end), and rust-gtk (37 library plus 1 main;
  1 display-only library test and 1 display-only integration test ignored).
  Python default tests passed (214, 21 skipped). Strict Clippy passed for
  rust-core, rust-python, rust-backend and rust-gtk. The native GTK binary had
  already built with the U04 SDK. The first GTK cargo-test attempt without the
  SDK environment failed pkg-config lookup; the rerun with the SDK's
  `PKG_CONFIG_PATH`/`PKG_CONFIG_SYSROOT_DIR` passed. Local
  `scripts/smoke-native-settings.sh` could not start because `xvfb-run` is not
  installed; no package was installed. Exact-head CI is expected to run that
  configured Xvfb smoke. No Rust/Python source code changed in build 70 (E136).

## Remaining blockers and next step

Build-67 closed the listed Settings Xvfb action/state gaps. Build 68 closes the
native panel SNI method matrix and X11 placement/focus checks. Build 69 adds a
live synthetic Settings General capture but no verified Wayland control action.
Build 70 confirmed that a correctly named systemd app scope produces a
recognizable RemoteDesktop consent prompt. The request timed out after 360
seconds without approval, so no input was sent and no action parity is claimed.
These results do not substitute for the remaining acceptance work:

1. Wayland pointer/keyboard interactions for Settings (including Hooks),
   provider controls, cross-page navigation, and Usage & Spend range/mode/tooltip
   actions remain open. The current compositor does not accept the available
   `wtype` route; build-69 AT-SPI and KWin fake-input attempts had no verified
   visible state/result. The RemoteDesktop consented input path remains
   unexercised because no approval was received. Build 68 exercised native SNI
   methods over D-Bus and captured the synthetic panel, but did not deliver UI
   pointer/keyboard input.
2. A complete Wayland page/action pass, or an explicitly justified per-case
   unsupported environment record, remains necessary. SNI D-Bus calls and a
   panel capture do not establish pointer/keyboard parity.

Only after those items are verified should UG be reconsidered. C01 upgrade and
rollback in an isolated prefix/home, C02 no-Python/PyGObject/PyO3 verification,
C03 Python removal, and CG final audit remain blocked behind UG. Keep Python as
the default in the meantime.
