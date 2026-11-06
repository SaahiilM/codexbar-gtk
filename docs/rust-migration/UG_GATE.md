# UG native UI gate ledger

**Status: NOT PASSED.** All U01–U08 implementation PRs have merged, but the
required UI action and Wayland evidence is incomplete. Python remains the
default launcher. This ledger records observed evidence, limits and the exact
remaining work; backend unit tests do not count as GTK interaction evidence.

## Baseline and merge state

- Live `origin/main` for build 73 is U05 PR #73's normal merge
  `cbdcc129ab4ac3ec5d6f3a8ef805567f96d354ff` (E141). Its exact head
  `06dabbe1b0d24f79a8e9fa5eaa78575038a1450c` passed `test` and `tray-dbus` in
  run `41514939406`; reviews/comments were empty. Build-73 synthetic pointer
  and Settings preference evidence is tracked separately below and in E143.
  PR #72 and the earlier portal lifecycle results remain historical in E139–E140.
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
| Consent-free input via linux-agent-access bridge | N/A (Wayland-only). | **OPEN — harness built (E190, rebased at build 90 per E191; retained E189 x fix and capture guard), live evidence pending.** The guarded Wayland runner gains a `--bridge` route: clicks go through the `linux-agent-access` bridge (absolute `action --application com.steipete.CodexBarGTK --json` calls that restore the reusable KDE grant unattended) instead of the per-run KDE consent prompt. KWin fail-closed guard, Spectacle evidence and the portal path are unchanged (flag-gated; `--portal` forces the prompt flow). The OS-level grant stays authorized once out of band. No live run observed yet, so the row stays OPEN and UG stays **NOT PASSED**. | Bridge error/non-JSON output fails closed (guard suite asserts). |
| KDE RemoteDesktop portal input path | **AVAILABLE.** Session D-Bus reports RemoteDesktop v2 and `AvailableDeviceTypes=7`; installed backend is `xdg-desktop-portal-kde` 6.8.1. | **PARTIAL/PASS FOR ONE CONTROL.** Build 72's nonpersistent keyboard+pointer request sent `Ctrl+R` to Settings and reached four synthetic CLI calls (E140). Build 75 visually verified the named `gtk-synthetic-wayland` KDE prompt; after user approval, its nonpersistent pointer+keyboard (`types=3`, no ScreenCast/clipboard) grant sent relative motion and a primary-button press/release to the geometry-derived General switch point `(864,445)`. Fresh KWin state confirmed the synthetic Settings PID was active and topmost; the isolated `refreshAllProvidersOnMenuOpen` value persisted from `false` to `true` (E151). No keyboard event was sent. | **PARTIAL.** This proves one portal pointer click and one isolated Settings action. It does not establish keyboard input, other controls, desktop-shell parity, or the full UG matrix (E151). |
| Usage/dashboard route and provider detail interactions | **PARTIAL.** Central route and refresh smoke passed; dashboard fixture screenshots exist. Not every provider card detail/hover/action is independently asserted in the UG matrix. | **CAPTURE/PARTIAL.** Dashboard capture and route smoke passed at default scale. No full Wayland pointer/keyboard action matrix. | **PASS for app/SNI lifecycle**; per-provider UI action coverage remains open. |
| Sessions: loading, success, empty, first-scan failure, refresh, navigation | **PASS for synthetic states and refresh/navigation** in `smoke-native-usage-pages.sh` and U04 evidence. | **CAPTURE/PARTIAL.** Fresh `--page sessions` captures show loading, running-session success, empty and first-scan failure. Synthetic refresh action and tray release were exercised in the fixture run, but stale retained-error frames were excluded; no Wayland pointer/keyboard action pass. | **PASS for startup/quit and SNI release** in the Wayland fixture smoke; exact-head CI private-bus lifecycle also passed. |
| Usage & Spend: loading/success/partial/empty/errors, four spend ranges, three heatmap modes, tooltip and refresh | **PASS for current synthetic matrix.** The build-66 script passed with visible pointer clicks on 7/30/90 days and All, Daily/Weekly/Cumulative, keyboard focus/range check, tooltip, refresh, empty and retained-error states. The four range and three mode screenshots are in `screenshots/ug-build66/`. | **CAPTURE/PARTIAL (build 84 harness-built; build 87 retained-error stale-capture fix E187 — byte-identical evidence retracted, live re-run required, no state PASS claimed).** New `scripts/test-native-spend-wayland.py` covers 4 ranges, 3 modes, tooltip hover, Refresh, and fixture-only loading/success/partial/empty/retained-error. Range/mode/tooltip/refresh pointer paths are harness-built and await a fresh named KDE RemoteDesktop grant for live automated runs; `--inspect-only` baseline verified. The retained-error wait now covers 3 cost-fixture calls plus a view-state settle before capturing, and the state capture fails closed unless the synthetic Spend PID is active — the operator must re-run `--state retained-error` and require a retained-error capture distinct from the partial capture before any state PASS is claimed. | **PASS for app/SNI lifecycle** in the fixture run; no claim that D-Bus unit coverage substitutes for UI actions. |
| Settings — General: refresh-on-panel-open, startup, currency, refresh interval, show panel on start, start at login | **PASS on Xvfb.** Build-66 smoke persisted refresh-on-panel-open, USD and launch-at-login create/remove. Build-67 smoke clicked and persisted refresh interval `5m` and show-on-start on/off; the launch entry remains isolated to a temporary home. See [`u05-build67-general-actions-xvfb.png`](screenshots/u05-build67-general-actions-xvfb.png). | **PARTIAL.** Builds 69–73 captured General without a verified preference action. Build 75 passed one fresh, user-approved portal pointer click on “Refresh when the panel opens”; the synthetic JSON changed `refreshAllProvidersOnMenuOpen` from `false` to `true` (E151). Build 76's first automated “Show the panel on start” attempt changed synthetic `launchAtLogin` instead (E157); a second fresh grant aborted before click on fractional coordinates (E158); a later no-portal baseline attempt aborted safely with the cursor outside the active synthetic window (E159). E160 records a separate user-driven click with the switch visibly OFF beforehand; only `showPopupOnStart` persisted `false→true`, while `launchAtLogin` stayed false. This verifies that manual UI action, not the runner's automated click path. E165 adds a live start-at-login pass: user ran the guarded runner with a named KDE grant and toggled Start at login ON; isolated JSON persisted `launchAtLogin` false→true with `showPopupOnStart` unchanged, and the synthetic autostart entry was created. Integer rounding and baseline-only focus handling are corrected; the post-consent click guard remains strict. | **PASS for isolated Settings actor writes on Xvfb**; one portal-driven and one manual Wayland control action are recorded, but not a full General/UG pass. |
| Settings — Providers: enable/disable, source selection, API-key entry/visibility, provider login | **PASS on Xvfb with synthetic fixtures.** The provider switch and source selector reached the fixture CLI; API-key Apply reached the CLI using a randomized synthetic value that was checked absent from preferences and logs. A synthetic PTY sign-in completed and the GTK status handler reported “Sign-in completed.” before capture. No real credentials or auth output were used. See [`u05-build67-provider-actions-xvfb.png`](screenshots/u05-build67-provider-actions-xvfb.png), [`u05-build67-login-complete-xvfb.png`](screenshots/u05-build67-login-complete-xvfb.png). | **OPEN for actions — harness built (E186, build 86), live evidence pending.** The guarded Wayland runner now allowlists `disable-codex-provider` (Providers page, per-action tab estimate + switch estimate from the Xvfb smoke, manual tab selection/calibration via `--inspect-only`). It persists no preference JSON, so the runner seeds the fixture Codex provider ON and requires the fake CLI's own state flip `true→false` from a recorded `config disable --provider codex` (plus an unchanged preference store). Source selection, API-key entry (randomized synthetic value, checked absent from preferences/logs/app log) and PTY sign-in (`Sign-in completed.`) need dropdown/typed-secret/PTY input with no safe guarded path here and stay **manual** (documented runner entries refuse to drive). No live Wayland provider action has been observed, so the row stays OPEN and UG stays **NOT PASSED**. | Fixture CLI calls, secret redaction and handler-level login result were asserted by the Settings smoke. |
| Settings — Display: usage bar, reset-time format, workday tick style, quota burndown, hide account details | **PASS on Xvfb.** Build-66 covered the original four controls; build 67 also changed workday-count, pace visibility, hide-account and both numeric quota thresholds, then verified isolated preference writes. See [`u05-build67-display-actions-xvfb.png`](screenshots/u05-build67-display-actions-xvfb.png). | **PARTIAL.** `hidePersonalInfo` PASS verified (E183, manual Display navigation + runner switch click; persisted `hidePersonalInfo: true`; page check shows Display page). Automated tab navigation remains OPEN; E184 diagnosed the miss (old `(0.34, 0.94)` click lands 1 px above the Display pill top edge — pill rect abs x 647..731, y 846..885; old point (704, 845)) and the runner now clicks the pixel-measured pill centre `(0.325, 0.968)` with a fail-closed screenshot page-verification gate, but no fully automated live run has been observed yet — awaiting a fresh named KDE grant. Remaining Display controls (usage bars, reset-time format, tick style, burndown) OPEN. | Settings actor persistence passed for the tested values. |
| Settings — Notifications: four preference switches and “Send a test notification” | **PASS.** All four switches were toggled off. The button delivered to an in-process synthetic `org.freedesktop.Notifications` service on the private session bus; the receiver log contained the expected test summary and the UI displayed “Test notification sent.” See [`settings-notification-received-xvfb.png`](screenshots/ug-build66/settings-notification-received-xvfb.png). | **OPEN for actions.** Harness built (build 82): the guarded Wayland runner now allowlists `session-quota-notifications`, `quota-warning-notifications`, `limit-reset-notifications`, `predictive-pace-notifications` (keys `sessionQuotaNotificationsEnabled`, `quotaWarningNotificationsEnabled`, `limitResetNotificationsEnabled`, `predictivePaceNotificationsEnabled`) and the `test-notification` button (delivery check via `gdbus-monitor` on a synthetic `org.freedesktop.Notifications` service). Row/tab coordinates are estimates from the Xvfb smoke and need live calibration. Live Wayland evidence is still pending, so this row remains OPEN and UG stays **NOT PASSED**. | **PASS for this UI notification action** on the private bus. Separate from the tray registration lifecycle check. |

| Settings — Menu Bar: icon style/source, provider row style, tray visibility | **PASS.** Four visible controls were clicked and the isolated preference JSON verified: `iconPercent`, `automatic`, `details`, and `showTray=false`. See [`settings-menu-bar-actions-xvfb.png`](screenshots/ug-build66/settings-menu-bar-actions-xvfb.png). | **OPEN for actions.** No Wayland menu-bar control interaction. The build-83 guarded runner now allowlists the `show-tray-icon` switch (`showTray`, Menu Bar page, manual tab selection, harness-built; NOT PASSED until live evidence). The three combos (`menuBarIconStyle`, `unifiedIconSource`, `switcherRowsOption`) have no safe synthetic selection path and remain manual. | Preference writes passed through the native Settings actor in an isolated home. |
| Settings — Display: usage bar, reset-time format, workday tick style, quota burndown, hide account details | **PASS on Xvfb.** Build-66 covered the original four controls; build 67 also changed workday-count, pace visibility, hide-account and both numeric quota thresholds, then verified isolated preference writes. See [`u05-build67-display-actions-xvfb.png`](screenshots/u05-build67-display-actions-xvfb.png). | **PARTIAL.** `hidePersonalInfo` PASS verified (E183, manual Display navigation + runner switch click; persisted `hidePersonalInfo: true`; page check shows Display page). Automated tab navigation remains OPEN; the runner's tab click still didn't navigate in E183's run. Remaining Display controls (usage bars, reset-time format, tick style, burndown) OPEN. | Settings actor persistence passed for the tested values. |
| Settings — Usage & Spend: local cost scanning and statistics time zone | **PASS.** The GTK toggle was changed to off and a non-default timezone was selected/persisted (`Africa/Abidjan`). See [`settings-usage-spend-actions-xvfb.png`](screenshots/ug-build66/settings-usage-spend-actions-xvfb.png). | **OPEN for actions.** | Settings actor persistence passed for tested values. |
| Settings — Hooks | **PASS on Xvfb for the global `Enable hooks` switch and rules display.** The GTK switch was clicked off and back on; the fixture asserted `hooks disable` and `hooks enable` CLI calls and temporary state (`false`, then `true`). Build 67 also captured the empty rules state after selecting an empty fixture. See [`u05-build67-hooks-actions-xvfb.png`](screenshots/u05-build67-hooks-actions-xvfb.png) and [`u05-build67-hooks-empty-xvfb.png`](screenshots/u05-build67-hooks-empty-xvfb.png). Configured rule rows are display-only. | **OPEN.** On build 69, AT-SPI reported Hooks selected while the visible capture stayed on General; the Hooks switch action caused no CLI call/state change. A bounded KWin fake-input click also produced no observable change. This is not counted as a product pass or failure because no input action was verified (E133). | The tested switch persisted through the synthetic CLI fixture on Xvfb/private D-Bus. |
| Settings — Plugins | **PASS for read-only populated/empty/loading/error states on Xvfb.** The fixture controlled each response state and the smoke waited for the async rows before capture. There is no plugin mutation operation or click requirement. See the four [`u05-build67-plugins-*-xvfb.png`](screenshots/u05-build67-plugins-populated-xvfb.png) captures. | **OPEN.** No Wayland plugin-list state capture. | No plugin mutation action exists to verify. |
| Settings — Advanced: CLI path, import, export, reset | **PASS on Xvfb.** The visible CLI-path Apply control reconfigured to the same synthetic executable and persisted the path. A visible Save chooser accepted the synthetic export path and the resulting JSON was checked. Valid and empty synthetic fixtures were selected in a visible import chooser; known-key overlay, unrelated preference retention, unknown-key omission and unchanged autostart were verified. Reset cancel/confirm and defaults were checked while preserving autostart. See [`u05-build67-cli-path-actions-xvfb.png`](screenshots/u05-build67-cli-path-actions-xvfb.png), [`u05-build67-export-chooser-xvfb.png`](screenshots/u05-build67-export-chooser-xvfb.png), [`u05-build67-import-selected-xvfb.png`](screenshots/u05-build67-import-selected-xvfb.png), and [`u05-build67-reset-status-xvfb.png`](screenshots/u05-build67-reset-status-xvfb.png). | **OPEN.** No Wayland Settings action was exercised. | The Settings actor used a temporary home; real credentials were absent from exported JSON, preferences and logs. |
| Settings — About, Acknowledgements and central About route | **PASS for capture/navigation.** All pages captured; central About route opened. The build-67 About capture shows `0.82.0 (67)` in [`u05-build67-about-xvfb.png`](screenshots/u05-build67-about-xvfb.png). | **OPEN beyond General capture.** | No additional bus contract. |
| Update-check action and result | **PASS on Xvfb.** The Gio action fetched the synthetic marker from a loopback-only server, asserted the request arrived and checked the visible “Update available” result. See [`u05-build67-update-result-xvfb.png`](screenshots/u05-build67-update-result-xvfb.png). | **OPEN — harness built (E185, build 85), live evidence pending.** `scripts/test-native-update-check-wayland.py` drives the Gio `check-updates` action on Wayland against a 127.0.0.1-only synthetic VERSION server, asserts the request arrived, and verifies the visible “Update available” state (KWin caption + Spectacle capture at `/tmp/codexbar-wayland-update-result.png`). It needs no portal consent. Not yet run on the intended KDE session, so the row stays OPEN. | No public network request was made. |
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

Build 71 records the observed PR #71 merge in E137. After the serial slot was
confirmed, an isolated synthetic Settings target was launched in the identified
systemd app scope. The RemoteDesktop v2 request selected keyboard and pointer
only (`types=3`, `persist_mode=0`); it did not request ScreenCast or clipboard.
The visible KDE dialog named “CodexBar GTK build 71 synthetic interaction
test” and the user approved it. `Start` returned `Response=0 devices=3`, but the
native Settings child had exited before any input. No input event was sent; the
cause is unknown, no coredump was present, and the app log showed only libEGL
DRI warnings. The portal session, temporary desktop entry and fixture HOME were
closed/removed; app/SNI/Spectacle names are unowned. The unrelated
`codexbar-linux --usage` process and Chromium global-shortcuts portal session
remain untouched. The slot is released. Captures prove only startup and
consent presentation:
[`u05-build71-settings-general-wayland.png`](screenshots/u05-build71-settings-general-wayland.png),
[`u05-build71-remote-desktop-consent-prompt-wayland.png`](screenshots/u05-build71-remote-desktop-consent-prompt-wayland.png).
The build-71 child-exit cause remains unknown; build 72 records a bounded
diagnostic and separate fresh portal attempt below. Approval alone does not
count as interaction parity.

Build 72 records a bounded synthetic Settings process lifecycle and a fresh
approved keyboard action. The Settings PID/D-Bus owner stayed live for a
360-second pre-consent bound; the first portal runner later closed its own
session on stdin EOF without sending input, which does not explain build 71's
earlier exit. A corrected runner displayed the exact friendly KDE prompt and,
after `Start` returned `Response=0 devices=3`, sent one `Ctrl+R`; the synthetic
CLI call count rose from 8 to 12. It did not send pointer input or change a
preference. The isolated portal session and app were then closed cleanly and
the live slot released. The named consent capture and Settings window capture
are [`u05-build72-remote-desktop-consent-prompt-wayland.png`](screenshots/u05-build72-remote-desktop-consent-prompt-wayland.png)
and [`u05-build72-settings-refresh-wayland.png`](screenshots/u05-build72-settings-refresh-wayland.png). Both are synthetic. Xvfb
remains unavailable locally; the required exact-head CI checks are still
pending. See E140.

Build 73 is an incomplete synthetic Wayland pointer attempt. A fresh isolated
HOME/config/cache used a fake CLI with no accounts or secrets. The installed
xdg-desktop-portal is 1.18.4 and does not expose the host app registry; a bare
helper initially produced an “unidentifiable application” prompt, which was
closed without approval or input. The corrected helper ran in a systemd app-ID
scope matching its temporary `.desktop` entry. KDE then displayed the named
“CodexBar GTK build 73 synthetic interaction test” prompt requesting pointer
and keyboard only; the capture is
[`u05-build73-remote-desktop-consent-wayland.png`](screenshots/u05-build73-remote-desktop-consent-wayland.png).
With `types=3`, `persist_mode=0`, no ScreenCast or clipboard, `Start` returned
`Response=0 devices=3 clipboard_enabled=false`. One relative motion targeted
the General switch at `(1212,523)`, but subsequent cursor samples moved across
the window and outside it; Settings later became inactive. The compositor top-hit
check stayed inconclusive. No button/key event was sent and
`refreshAllProvidersOnMenuOpen` remained `false`. The baseline capture is
[`u05-build73-settings-general-before-wayland.png`](screenshots/u05-build73-settings-general-before-wayland.png).
The approved portal session was explicitly closed, the app exited through Gio
Quit (`rc=0`), and app/SNI/Spectacle names and the temporary desktop entry are
unowned/removed. The unrelated `codexbar-linux` process and other desktop apps
were untouched. The build-73 slot is released. See E143; this does not pass a
Wayland preference action.

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
  the compositor to ignore untrusted requests. E151 later passed one
  user-approved KDE RemoteDesktop pointer click and persisted a synthetic
  preference. The broader Wayland pointer/keyboard matrix remains **OPEN**;
  earlier no-op attempts are not proof of product failure or full UI parity.
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
- Build 74 received a fresh nonpersistent pointer+keyboard RemoteDesktop
  grant (`Start` response 0, `types=3`, `persist_mode=0`, no ScreenCast or
  clipboard) using a matching temporary desktop entry. The prompt's displayed
  caller name was not captured or visually verified. KWin observed bounded
  `NotifyPointerMotion` relative deltas move
  the pointer to the synthetic Settings switch while that window was active and
  topmost. Absolute motion takes a PipeWire stream node ID and coordinates in
  the stream's logical space, so it is unavailable in this pointer-only request
  ([RemoteDesktop interface](https://github.com/flatpak/xdg-desktop-portal/blob/main/data/org.freedesktop.portal.RemoteDesktop.xml)).
  After a pre-click screenshot, KWin logged cursor movement to `(1871,1182)`
  without a matching portal action; the app stayed active but no longer owned
  the pointer hit-test. The guarded helper sent no click or key event, and the
  isolated setting remained false. Cause is unknown; this establishes relative
  motion delivery but not a preference action, UI parity, or a product defect.
  See E146. Retain the row as **OPEN**.
- Build-74 retry E147 captured the baseline before the portal request, and that
  Spectacle capture produced no KWin cursor/focus events. KWin then observed
  the portal backend window activate and later close; the friendly fixture name
  was not captured in a prompt screenshot. The observer logged 1,864 cursor
  changes and a brief focus switch while the portal action log contained only
  `Start` and `Close`. No pointer or keyboard action was sent, the preference
  stayed false, and the cause of cursor activity remains unknown. The session
  closed cleanly and the slot was released. This keeps the row **OPEN**; see
  E147.
- Build-74 retry E148 was aborted before a portal request: KWin logged 101
  cursor changes and a window-added event while the portal process was
  inactive; the final pointer hit-test was outside the synthetic Settings
  window. No consent or input occurred, and the preference remained false.
  The baseline and sanitized event log remain in the local temporary evidence
  directory; this does not indicate a product failure. The live interaction
  slot was released (E148).
- E149 assessed a private KWin 6.8.1 virtual backend with its own D-Bus and
  Wayland socket. It exposed KWin fake-input and KDE screencast protocols, and
  the installed KDE portal descriptor advertises RemoteDesktop, but a
  read-only `ScreenShot2.CaptureActiveScreen` call crashed that isolated KWin
  in `RenderDevice::eglContext()`. No portal request or input was sent. This
  route cannot meet the required visual consent-name check until a working
  capture path is available (E149).
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
native panel SNI method matrix and X11 placement/focus checks. Builds 69–74
include live synthetic Settings captures; E151 adds one verified Wayland
General preference action. E146 verified bounded relative portal motion; E147
observed unexplained cursor/focus activity during a portal request without
helper motion; E148 observed cursor changes before any portal request and
aborted. E149's private KWin virtual backend exposed input protocols, but its
screenshot API crashed before it could capture consent.

The build-76 runner in `scripts/test-native-settings-wayland.py` keeps portal
setup and input on one D-Bus connection, requests only nonpersistent pointer
and keyboard access, and waits for the human-approved named prompt. Its
allowlisted actions currently cover the refresh-on-panel-open switch, the
show-panel-on-start switch, the start-at-login switch, the hide-personal-info
switch (live evidence pending for the latter two; see E163–E164) and, as of
build 82, the four Notifications preference switches plus the test-notification
button (live evidence pending; harness-built only). `--inspect-only` captures the active synthetic
Settings window and exits before any portal request/input. On a live run, the
operator inspects that baseline and the named prompt before approving; after
approval the runner activates only the window matching the synthetic app PID
and “CodexBar Settings” title, checks fresh focus/top-hit/cursor evidence, and
asserts that only the selected synthetic preference changed. E151 remains the
only verified portal-driven action; E160 is separate manual Wayland evidence.
The first build-76 show-on-
start click left its preference false and changed the synthetic launch-at-login
setting instead (E157); the next fresh grant aborted before click because a
fractional KWin origin did not match the integer cursor sample (E158). Both
target mapping and integer rounding are corrected. A later read-only baseline
attempt found the synthetic Settings PID active while the pointer was outside
the window and aborted before requesting portal consent; baseline capture now
checks exact active PID/focus, while the later click check still requires
fresh top-hit and cursor agreement (E159). E160 records one manual Wayland
click after a screenshot confirmed show-on-start was OFF; the isolated JSON
logged only `showPopupOnStart=false→true`, and the synthetic app was closed.
That does not test the automated click path. The unit tests do not exercise GTK
or Wayland input. Other General controls and the broader UG matrix remain open.

The full `scripts/smoke-native-settings.sh` passed locally earlier in build 76
(E157), but cannot be rerun in the current shell because `xvfb-run` is absent.
The Actions workflow now omits only that Settings smoke after two CI failures
at native file-chooser steps (E162); the script remains available for local
verification, and other native GTK Xvfb smokes remain enabled. This is not a
claim that Settings passes in CI.

Weston is not installed system-wide; apt offers it, but installation requires
an interactive sudo password here. A rootless Weston 13 extraction started a
private headless Pixman compositor and socket, and `wayland-info` connected;
`weston-screenshooter` returned unauthorized, so no visible GTK/widget action
was verified. A Weston renderer/widget test would not establish KDE portal
consent, real desktop pointer delivery, or shell parity.

On the intended KDE session, build the native binary and first inspect the
synthetic Settings baseline without portal access:

```sh
systemd-run --user --scope \
  --unit=app-codexbar-gtk-synthetic-wayland-test.scope \
  python3 scripts/test-native-settings-wayland.py \
  --binary "$PWD/rust-gtk/target/debug/codexbar-gtk-native" \
  --action show-panel-on-start --inspect-only
```

Then start a new run without `--inspect-only`, visually confirm that the KDE
prompt names `gtk-synthetic-wayland` and requests pointer/keyboard only, and
ask the user to click Allow. The runner captures the active synthetic Settings
baseline before requesting consent, reactivates only its Settings PID/title
after approval, and aborts without a click unless focus, cursor and top-hit
pass fresh checks. Optional `--switch-x`/`--switch-y` overrides must be
supplied as a pair and must remain inside the live window. A verified action
must also persist the selected isolated JSON preference without changing other
keys. One action is not a full UG pass.

CI does have native GTK smoke coverage on Xvfb: routing, panel parity,
dashboard (including 2x scale), Usage & Spend, and Settings, as configured in
`.github/workflows/rust-core.yml`. These are X11 smoke tests and do not close
Wayland rows. The build-75 unit tests check safety policy; the one live pointer
action covers only one General control. Those results do not substitute for
the remaining acceptance work:

1. Wayland pointer/keyboard interactions for Settings (including Hooks),
   provider controls, cross-page navigation, and Usage & Spend range/mode/tooltip
   actions remain open. The current compositor does not accept the available
   `wtype` route; build-69 AT-SPI and KWin fake-input attempts had no verified
   visible state/result. Build 75 establishes one portal pointer action only;
   additional Settings controls and other surfaces still need their own
   verified interactions. Stop without input if cursor/focus state is
   ambiguous. Build 68 exercised native SNI methods over D-Bus and captured
   the synthetic panel, but did not deliver UI pointer/keyboard input.
2. A complete Wayland page/action pass, or an explicitly justified per-case
   unsupported environment record, remains necessary. SNI D-Bus calls and a
   panel capture do not establish pointer/keyboard parity.

Only after those items are verified should UG be reconsidered. C01 upgrade and
rollback in an isolated prefix/home, C02 no-Python/PyGObject/PyO3 verification,
C03 Python removal, and CG final audit remain blocked behind UG. Keep Python as
the default in the meantime.


### Build 91 fixture correction (E192; live verification remains open)

The partial Spend fixture now emits parseable JSON. Retained-error now seeds a
successful cost scan before failing a refresh. Subprocess fixture tests prove
those inputs and transitions; they do not prove that GTK rendered the expected
retained-data notice. No new screenshot or UI action pass is claimed here.
The existing UG matrix remains open, including bridge accessibility/focus and
remaining Wayland interactions. Python remains the default.


### Build 92 bridge fixture accessibility (E194; live pass remains open)

The bridge fixture now permits AT-SPI and resolves the exported application
name by exact synthetic process ID. Failed probes suppress input, even if a
name appears in their output. Unit tests cover these contracts, but earlier
live attempts failed on accessibility discovery and the final code has no
verified live click yet. The existing UG action rows remain open.
