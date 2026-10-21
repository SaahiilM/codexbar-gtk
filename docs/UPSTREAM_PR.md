# Linux desktop: provider switcher, agent sessions and a card refresh

Improvements to the existing Qt/QML desktop app in `Integrations/Linux`, in
focused commits. No new runtime dependency, no new provider fetching, no change
to the Swift CLI, no change to how the app is installed or released.

## What this changes

- **Provider switcher in the tray.** The macOS app shows the live usage of every
  provider next to the menu bar item; the Linux tray only ever showed the first
  provider's two meters. The tray now lists every provider with a usage line and
  keeps the icon on the first provider, so existing installs behave exactly as
  before. A new *Tray icon shows* preference (`first` / `highest`) opts into
  following the busiest provider.
- **Agent sessions.** The macOS app lists the coding agents that are running and
  the CLI already reports them (`codexbar sessions --json-v2`). The Linux app
  gets a **Sessions** tab. The probe is opt-in — sessions are only listed when
  the tab is opened — so a usage refresh still makes exactly the CLI calls it
  made before.
- **A summary strip** above the provider cards: how many providers are tracked,
  which one is closest to its limit, when the next window resets and what the
  local sessions cost.
- **Redesigned cards**: provider icon and plan badge, a rounded meter in the
  provider's accent colour, the reset countdown and the pace as chips, and a
  divider before the balances. Every provider keeps a stable accent colour, so
  several cards stay readable side by side.
- **Spending breakdown** by project and model, from the same local history the
  chart already uses.
- **A missing icon fallback.** OpenAI, Azure OpenAI, Alibaba Token Plan and
  Moonshot have no `ProviderIcon` asset, so the app rendered an empty slot for
  them. It now draws the provider initial in its accent colour.

## Review feedback addressed

The automated review on the first revision raised seven actionable findings; all
are fixed in the commits above, each with regression coverage:

| Finding | Fix |
| --- | --- |
| Existing installs silently switched the tray to another provider | The missing preference defaults to `first` again; `highest` is an explicit choice (`6ccce2b`) |
| The sessions process was not stopped during teardown | The process is stopped and disconnected while the controller is still alive (`d8a6b3b`) |
| A finished scan kept its handlers, so the next scan read an empty buffer | The handlers are disconnected before a new scan starts (`d8a6b3b`) |
| A failed session scan was reported as "no sessions" | The last known list is kept and the reason is surfaced (`d8a6b3b`) |
| The overview handed a timestamp to a helper that parses date strings | The overview keeps the original date string (`335939a`) |
| The card chips tinted their label along with the background | The chips use an alpha background with opaque text (`335939a`) |
| The tray line dropped the used/left suffix | The line states the quantity, e.g. `Codex — 5 hour 60% left` (`335939a`) |

The overview and the tray lines moved into the controller so both are covered by
the test suite.

## Commands run

```sh
# build
cd Integrations/Linux
mkdir -p ../../.local/linux-build && cd ../../.local/linux-build
qmake6 ../../Integrations/Linux/codexbar-linux.pro && make -j4

# tests (the upstream suite plus the new cases)
cd Integrations/Linux
CODEXBAR_LINUX_BINARY=$PWD/../../.local/linux-build/codexbar-linux \
  python3 -m unittest discover -s tests -p "test_*.py"
# Ran 33 tests — OK

# lint the QML
/usr/lib/qt6/bin/qmllint -I qml -I Shared qml/*.qml
```

## Behaviour proof

The new paths are covered by the runtime tests in `Integrations/Linux/tests/test_desktop.py`,
which drive the real binary against a fake CLI and assert on the private IPC
snapshot:

- `test_existing_settings_keep_the_first_provider_in_the_tray` — an existing
  `linux.json` without the new key keeps the first provider in the tray
- `test_tray_lines_state_used_or_left` — the tray line states the quantity
- `test_a_failed_session_scan_keeps_the_last_known_list` — a failing scan keeps
  the last list and reports the error
- `test_the_overview_keeps_a_parsable_reset_time` — the reset time stays a date
  string the UI can parse
- `test_sessions_are_listed_only_when_the_tab_is_opened` — the sessions probe
  stays opt-in

Runtime captures of the running app are attached below.

## Decision needed

`VISION.md` asks for an owner decision before new features land in the desktop
app. This PR bundles four additions (sessions tab, dashboard summary, tray
provider switcher, card refresh) and one fix (the missing icon fallback). The
suggested scope is to take the additions and the fix as they are, and to keep
the new tray preference opt-in so no existing install changes behaviour.

Related discussion about a separate GTK front-end for Linux: #4694.

## Screenshots

_Usage dashboard with the summary strip and the refreshed cards, the Sessions
tab, and the tray menu with the provider switcher._
