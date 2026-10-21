# Proposal: a native GTK4 front-end for CodexBar on Linux

> This is deliberately an **issue**, not a pull request. The previous Linux tray
> attempt (#992) was closed with the note that *"a new tray application should
> first establish an explicit cross-platform product direction and architecture
> rather than landing a large PR"*. This issue is that proposal, and the working
> implementation is linked at the bottom.

Related, and landed separately: the existing Qt desktop app is being brought up
to parity in #4693 (provider switcher, agent sessions, card refresh).

## Summary

A read-only **GTK4 / libadwaita** desktop front-end for the existing `codexbar` CLI,
aimed at Linux desktops that do not want the macOS menu bar app and find the
current Qt/QML desktop app too plain.

It is **not** a second product: it adds no provider fetching, no authentication
path, no packaging pipeline and no runtime changes to the Swift CLI. It consumes
exactly the JSON the CLI already emits (`codexbar usage --format json`,
`codexbar cost --format json`, `codexbar sessions --json-v2`) and adds a
menu-bar-style presence on Linux.

## Why

The macOS app is a native menu bar app. On Linux the shipped desktop app is a
windowed dashboard: it has no tray presence, no provider cards in a popover, no
pace indicators, and no reset countdowns next to a usage meter. Users who like
the macOS app on their Mac generally want the same *at-a-glance* information on
Linux — a small always-visible meter plus a compact panel.

## Scope

**In scope**

- A system tray item (StatusNotifierItem) that renders the usage meter and a
  host-rendered menu with the live provider summaries.
- A compact popover panel with one card per provider: quota meters per window
  (session / weekly / …), reset countdowns, pace ("12% in reserve"), credits
  and spend.
- A dashboard window (usage, agent sessions, usage & spend) and a preferences
  window that mirrors the macOS panes.
- Desktop notifications when a provider crosses a configured threshold.

**Explicitly out of scope**

- No new provider fetching, cookies, Keychain/browser access or OAuth. All of
  that stays in the Swift CLI, which the app shells out to — exactly like the
  current Linux desktop app does.
- No new packaging or release pipeline. The app can be installed from a single
  script and a systemd user service; packaging can follow once the direction is
  agreed.
- No macOS-only features: iCloud sync, managed account profiles, browser
  credential import, menu-bar layout editor.

## Architecture

```
Integrations/LinuxGTK/
├── codexbar_gtk/           # the app (Python 3.11+, GTK4, libadwaita 1.4+)
│   ├── cli.py              # thin JSON wrapper around the codexbar CLI
│   ├── data.py             # typed model of the CLI payloads
│   ├── controller.py       # background refresh loop, threshold events
│   ├── history.py          # optional local usage history for trends
│   ├── prefs.py            # preferences in the upstream portable format
│   └── ui/                 # cards, popover, dashboard, settings, tray
├── scripts/install.sh      # user install (launcher, icon, systemd unit)
└── tests/                  # unit tests (no live provider access)
```

Design constraints that keep the maintenance surface small:

1. **The CLI is the only data source.** Every provider, every credential and
   every number comes from `codexbar` JSON. When the CLI adds a provider, the
   front-end picks it up from the generic provider table.
2. **No duplicated provider logic.** The front-end does not know what a Codex
   quota is; it renders windows, pace, credits and charts the CLI reports.
3. **The tray item is a real StatusNotifierItem**, so Plasma, KDE, GNOME and
   libappindicator hosts all show it, and the menu is rendered by the host.
4. **Preferences use the upstream portable format** (`{"version": 1,
   "preferences": {...}}`), so they can be shared with the macOS app.
5. **Tests never touch a real account** — the CLI is faked and the payloads are
   recorded fixtures.

## Feature parity with the macOS app

| Upstream area | Here |
| --- | --- |
| Menu bar item, merged icons, icon styles | StatusNotifierItem with a meter or an icon+percentage pixmap; source = highest usage / first provider |
| Provider cards, meters, reset countdowns | One card per provider with a meter per window, countdown chip and pace chip |
| Pace forecast | "12% in reserve" / "in deficit" chips, colour coded |
| Quota burndown | Projected usage at reset, extrapolated from a local history file |
| Weekly work-day progress | Work-day tick on the weekly meter |
| Usage breakdown / credits history charts | Rendered from the CLI's `usage.details[].chart` and `credits.events` |
| Cost history / spend dashboard | Usage & Spend page with daily chart, projects, models and a per-provider breakdown |
| Provider status badges | Status dot and description per provider |
| Provider accounts | Account list per provider via `--all-accounts` |
| Agent sessions | Sessions page listing the running coding agents |
| Quota notifications, hooks, plugins | Notifications pane, Hooks pane and Plugins pane backed by the CLI |
| Preferences panes | General, Providers, Menu Bar, Display, Notifications, Usage & Spend, Hooks, Plugins, Advanced |

## Maintenance and packaging

- **Runtime dependencies:** Python 3.11+, GTK 4, libadwaita 1.4+. No third-party
  Python packages, no vendored binaries.
- **Distribution:** a `scripts/install.sh` that installs a launcher, an icon and
  a systemd user service. Debian/Ubuntu packaging can be added later as a
  separate, self-contained change once the app itself is accepted.
- **Support:** the upstream CLI does the provider work, so a new provider or a
  changed quota format needs no change here.

## Status

A working implementation exists and runs against the released CLI:
`Integrations/LinuxGTK/` in the fork (branch `feat/linux-gtk-front-end`). It is
~4.7k lines of Python with a unit test suite (25 tests) and no runtime
dependency beyond GTK 4, libadwaita and PyGObject. I am happy to trim it down,
split it up, or throw it away if the direction is not what you want.

## What I would land first

1. The app itself, as `Integrations/LinuxGTK/`, with unit tests and a
   screenshot set — split into reviewable commits (data model → cards → popover
   → dashboard → settings → tray).
2. A short section in `Integrations/Linux/README.md` describing both front-ends.
3. Optional: distro packaging as a follow-up PR.

## Open questions

- Should this live next to the Qt app in `Integrations/Linux/`, or in its own
  `Integrations/LinuxGTK/` directory? (My preference: a separate directory, so
  the two front-ends do not block each other.)
- Is Python acceptable for a Linux front-end, given the Swift/CLI core? The
  alternative would be a Qt/Kirigami rewrite, which the existing Qt app
  already covers.
- Should the app replace the Qt desktop app, or sit beside it?
