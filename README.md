# CodexBar for Linux — native GTK4 front-end

A native Linux desktop app for [CodexBar](https://github.com/steipete/CodexBar), the
menu-bar app that shows how much of your OpenAI Codex / Claude Code (and ~100 other
AI provider) quota is left, and when each window resets.

The macOS app is a native Swift/AppKit menu-bar app. The upstream project also ships a
Qt/QML desktop app for Linux, but it is a plain dashboard — no menu-bar presence, no
provider tiles, no pace indicators. This project is a **native GTK4 / libadwaita**
re-implementation of the macOS experience:

- a **system tray meter** whose fill follows the highest usage of your providers,
- a **compact popover** with provider tiles, quota meters, reset countdowns and pace,
- a **full dashboard** (Usage + Usage & Spend),
- a **settings window** covering providers, display, notifications and spend,
- **quota notifications** when a provider crosses a warning threshold.

The heavy lifting (provider fetching, authentication, cost scanning) stays in the
upstream `codexbar` CLI — this app is a front-end for it, exactly like the macOS app.

---

## Features

| Area | What you get |
| --- | --- |
| Tray | Dynamic meter icon (fills with the provider accent colour, turns amber/red near the limits), tooltip with per-window usage, native tray menu with live provider summaries |
| Popover | macOS-style provider cards: plan, account, one meter per quota window (session / weekly / …), reset countdown, pace ("12% in reserve"), credits and spend |
| Dashboard | Usage tiles (providers, highest usage, credits, local spend), one card per provider, plus a Usage & Spend page with a daily spend chart, project and model breakdowns |
| Settings | General (refresh interval, start at login, currency), Providers (enable/disable, source, API keys), Display (used vs. remaining, reset format, pace, warning thresholds), Notifications, Usage & Spend, Advanced (CLI path, preference import/export) |
| Notifications | Desktop notifications when a provider crosses a warning threshold |
| Data | Reads `codexbar usage --format json` and `codexbar cost --format json`; supports all ~100 upstream providers, accounts, credits and status badges |

## Requirements

- Linux with a Wayland or X11 session (tested on KDE Plasma 6 / Wayland)
- Python 3.10+
- GTK 4 and libadwaita 1.4+
- The `codexbar` CLI (already installed if you use the upstream Linux app)

If your distribution ships the GTK4 runtime but not the GObject introspection data
(`gir1.2-gtk-4.0`, `gir1.2-adw-1`), fetch it into a private prefix — no root needed:

```sh
./scripts/bootstrap-deps.sh
```

or install it system-wide:

```sh
sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi-cairo
```

## Quick start

```sh
git clone <this-repo> codexbar-gtk
cd codexbar-gtk
./scripts/bootstrap-deps.sh     # only if Gtk-4.0/Adw-1 typelibs are missing
./run.sh                        # start the app
./run.sh --settings             # start it and open the settings window
./run.sh --panel                # start it with the compact panel open
```

Install it for your user account (launcher entry, icon, systemd user service and
autostart):

```sh
./scripts/install.sh
~/.local/bin/codexbar-gtk
```

Remove it again with `./scripts/install.sh --uninstall`.

## How it talks to CodexBar

| Command | Used for |
| --- | --- |
| `codexbar usage --format json` | provider usage, credits, pace, status, detail sections and charts (enabled providers only) |
| `codexbar usage --provider X --all-accounts` | the account list for a provider |
| `codexbar cost --format json` / `--provider codex\|claude\|opencode` | local spend history, project and model breakdown |
| `codexbar sessions --json-v2` | the running coding agents |
| `codexbar config providers` | the provider list in Settings |
| `codexbar config enable/disable/set-source/set-api-key` | provider management |
| `codexbar hooks list --format json`, `hooks enable/disable` | the Hooks pane |
| `codexbar plugins list` | the Plugins pane |

Point the app at a different binary with `CODEXBAR_CLI=/path/to/codexbar` or in
Settings → Advanced → CLI path.

## Upstream feature parity

The reference for this app is the upstream **macOS** app in the same repository
(`Sources/CodexBar`); the upstream Linux/Qt app only covers part of it. This
front-end maps the upstream feature set onto the CLI:

| Upstream area | Upstream file | Here |
| --- | --- | --- |
| Menu bar item + merged icons | `StatusItemController*`, `IconRenderer` | StatusNotifierItem with a meter or an icon+percentage pixmap, merged source (highest usage / first provider) |
| Provider cards, meters, reset countdowns | `UsageMenuCardView`, `MenuCardMetricRow` | `ui/cards.py` — meter rows, chips, pace, credits, spend |
| Pace forecast | `UsagePace`, `UsagePaceText` | `format_pace` — "12% in reserve" / "in deficit" |
| Quota burndown / projection | `QuotaBurndownModel` | projected usage at reset, extrapolated from the recorded history |
| Weekly work-day progress | `weeklyProgressWorkDays`, `workdayTickAppearance` | workday tick on the weekly meter |
| Provider detail charts | `UsageBreakdownChartMenuView` | charts from the CLI's `usage.details[].chart` |
| Credits history chart | `CreditsHistoryChartMenuView` | chart from `credits.events` |
| Cost history chart | `CostHistoryChartMenuView` | daily spend chart on Usage & Spend |
| Provider status badges | `ProviderStatus` | status dot plus description per provider |
| Provider accounts | `CodexAccountSwitcherView` | account list per provider (`--all-accounts`) |
| Agent sessions | `AgentSession`, `StatusItemController+AgentSessions` | Sessions page |
| Spend dashboard | `SpendDashboardController` | Usage & Spend page with per-provider breakdown |
| Quota notifications | `PreferencesNotificationsPane` | Notifications pane, threshold events |
| Hooks | `PreferencesHooksPane` | Hooks pane backed by `codexbar hooks` |
| Plugins | `PreferencesPluginsPane` | Plugins pane backed by `codexbar plugins` |
| Preferences (General, Providers, Menu, Menu Bar, Display, Notifications, Usage & Spend, Advanced) | `PreferencesView` | the same panes, using the upstream preference keys where they exist |

Still macOS-only upstream and therefore not here: iCloud sync, managed macOS
account profiles, browser credential import and the menu-bar layout editor.

## Project layout

```
codexbar_gtk/
├── cli.py            thin JSON wrapper around the codexbar CLI
├── data.py           typed model of the CLI payloads (windows, pace, credits, cost)
├── format.py         formatting helpers (percentages, countdowns, currency)
├── prefs.py          preference store (mirrors the macOS preference document)
├── controller.py     background refresh loop + quota threshold events
├── providers.py      provider names and brand colours
└── ui/
    ├── app.py        Adw.Application: tray, popover, dashboard, settings
    ├── tray.py       StatusNotifierItem + dbusmenu (no Gtk.StatusIcon in GTK4)
    ├── popup.py      the compact popover
    ├── window.py     the dashboard window
    ├── cards.py      provider card, quota meter, stat tiles
    ├── spend.py      Usage & Spend page
    ├── settings.py   preferences window
    └── style.py      application CSS
```

Tools:

- `tools/preview.py` — renders the UI to PNG files for design work
- `tools/sni_probe.py` — minimal StatusNotifierItem probe for tray debugging
- `tools/focus_window.py` — raises a window by title (X11, used for screenshots)

## Tray icon notes

GTK 4 removed `Gtk.StatusIcon`, so the tray presence is implemented directly on top
of the **StatusNotifierItem** protocol plus a **dbusmenu** menu — the same mechanism
Chromium, Electron and the upstream Linux app use. The menu is rendered by Plasma
itself, right below the icon, and lists the live provider summaries:

```
Codex — Session 48% · Weekly 6%
─────────────────────────────
Show usage panel
Refresh
Open Dashboard
Settings…
─────────────────────────────
Quit CodexBar
```

Plasma only shows tray items that were registered *before* its status-notifier host
came up. The installer therefore ships a systemd user service ordered
`Before=plasma-plasmashell.service`, so the item exists when Plasma starts. If you
start the app by hand while Plasma is already running, the icon may only appear in
the panel's overflow (the little chevron) — restarting Plasma or logging out and back
in makes it permanent. The app re-registers automatically when Plasma restarts.

### Panel placement

GTK 4 removed the window positioning API, so on pure Wayland the compositor decides
where the compact panel appears. On X11/XWayland sessions the app moves the panel
itself (plain X11 calls) and anchors it to the bottom-right corner, right above the
panel — the same place the macOS menu bar popover appears.

## Preferences

Settings live in `~/.config/codexbar-gtk/settings.json` and can be exported and
imported from Settings → Advanced in the upstream portable format
(`{"version": 1, "preferences": {...}}`).

## Licence

The upstream CodexBar project is MIT licensed. This front-end follows the same
licence.
