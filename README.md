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
| `codexbar usage --format json` | provider usage, credits, pace, status (enabled providers only) |
| `codexbar cost --format json` | local spend history, project and model breakdown |
| `codexbar config providers` | the provider list in Settings |
| `codexbar config enable/disable/set-source/set-api-key` | provider management |

Point the app at a different binary with `CODEXBAR_CLI=/path/to/codexbar` or in
Settings → Advanced → CLI path.

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
itself, right below the icon, and lists the live provider summaries.

Plasma only shows tray items that were registered *before* its status-notifier host
came up. The installer therefore ships a systemd user service ordered
`Before=plasma-plasmashell.service`, so the item exists when Plasma starts. If you
start the app by hand while Plasma is already running, the icon may only appear in
the panel's overflow (the little chevron) — restarting Plasma or logging out and back
in makes it permanent. The app re-registers automatically when Plasma restarts.

## Preferences

Settings live in `~/.config/codexbar-gtk/settings.json` and can be exported and
imported from Settings → Advanced in the upstream portable format
(`{"version": 1, "preferences": {...}}`).

## Licence

The upstream CodexBar project is MIT licensed. This front-end follows the same
licence.
