# CodexBar GTK

A native **GTK4 / libadwaita** front-end for the
[CodexBar](https://github.com/steipete/CodexBar) CLI — the menu-bar app that shows
how much of your OpenAI Codex, Claude Code and other provider quotas is left, and
when each window resets.

This is a **community front-end**: it adds no provider fetching, no authentication
and no packaging of its own. It consumes the JSON the CodexBar CLI already emits
(`codexbar usage --format json`, `codexbar cost --format json`,
`codexbar sessions --json-v2`), the same way the other community integrations do
(the [Waybar module](https://github.com/Marouan-chak/codexbar-waybar), the
[COSMIC applet](https://github.com/andrew-verde/codexbar-cosmic-applet), the
[Plasma widgets](https://github.com/psimaker/codexbar-plasmoid), …).

![CodexBar dashboard with provider usage and summary cards](docs/dashboard.png)

| Compact tray panel with provider branding | The spending page |
| --- | --- |
| ![Compact tray panel showing the Codex logo](docs/panel.png) | ![The spending page](docs/spending.png) |

## What it does

- **A system tray meter** that fills with the provider's accent colour and turns
  amber or red near the limits, plus a host-rendered menu with the live usage of
  every provider. Hover shows the selected provider and its named quota windows;
  right-click opens an action panel with refresh, update check, restart, Settings
  and quit.
- **A compact panel** anchored above the panel, with one card per provider:
  quota meters per window (session / weekly / …), reset countdowns, pace
  ("12% in reserve"), credits and spend. Compact cards use the upstream
  CodexBar artwork, with a readable initial fallback when a logo is unavailable.
- **A dashboard** with a summary strip, provider cards, an agent-sessions page and
  a Usage & Spend page with a daily chart and a per-provider breakdown.
- **A preferences window** covering the refresh interval, providers, display
  options, quota notifications, spending and the tray.
- **Desktop notifications** when a provider crosses a warning threshold, when the
  current pace depletes a quota before its reset, and when a rate limit reset
  credit is about to expire.

## Requirements

- Linux with a Wayland or X11 session (developed against KDE Plasma 6 / Wayland)
- Python 3.10+, GTK 4 and libadwaita 1.4+
- The `codexbar` CLI (0.79 or newer; newer provider data is optional)

## Install

```sh
git clone https://github.com/SaahiilM/codexbar-gtk.git
cd codexbar-gtk
./scripts/bootstrap-deps.sh    # only if the Gtk-4.0/Adw-1 typelibs are missing
./scripts/install.sh           # launcher, icon, systemd user service, autostart
~/.local/bin/codexbar-gtk
```

`bootstrap-deps.sh` fetches the GTK4 introspection data into a private prefix
without root. If your distribution ships it, install it directly instead:

```sh
sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi-cairo
```

Useful flags:

```sh
codexbar-gtk            # start the app
codexbar-gtk --panel    # start it with the compact panel open
codexbar-gtk --settings # start it and open the settings
codexbar-gtk --page sessions|spend
```

Uninstall with `./scripts/install.sh --uninstall`.

## How it talks to CodexBar

| Command | Used for |
| --- | --- |
| `codexbar usage --format json` | provider usage, credits, pace, status, detail sections and charts |
| `codexbar usage --provider X --all-accounts` | the account list for a provider |
| `codexbar cost --provider both --format json` | local spend, projects and models |
| `codexbar sessions --json-v2` | the running coding agents |
| `codexbar config providers` | the provider list in Settings |
| `codexbar config enable/disable/set-source/set-api-key` | provider management |
| `codexbar hooks list`, `codexbar plugins list` | the Hooks and Plugins panes |

Point the app at a different binary with `CODEXBAR_CLI=/path/to/codexbar` or in
Settings → Advanced → CLI path.
The provider catalog, fetching, and credential handling follow the installed
CLI; new providers appear here when that CLI version supports them.
The GTK client supports older CLI releases; newer providers and quota fields
are optional. Missing cost estimates display as unavailable, not zero; if a
cost refresh fails, the previous totals remain visible as a marked known
subtotal until a successful refresh. The tray's update check fetches only the
public client `VERSION` marker from GitHub; it does not install or download code.

## Feature parity with the macOS app

| Upstream area | Here |
| --- | --- |
| Menu bar item, merged icons, icon styles | StatusNotifierItem with a meter or an icon+percentage pixmap |
| Tray hover and context menu | Explicit client/provider/window tooltip; right-click actions for refresh, update check, restart, Settings and quit |
| Automatic quota lane | Tray option "the quota running out soonest", ranked like the macOS Auto lane: a fully depleted quota first, then the smallest forecast ETA |
| Provider cards, meters, reset countdowns | One card per provider with a meter per window, countdown chip and pace chip |
| Pace forecast | "12% in reserve" / "in deficit" chips, colour coded |
| Monthly allowance target | Daily-use target in the quota's own units, divided across remaining local calendar days |
| Predictive pace warnings | Desktop notification when the current pace depletes a Codex or Claude quota before its reset — once per reset cycle |
| Quota burndown | Projected usage at reset, extrapolated from the recorded history |
| Weekly work-day progress | Work-day tick on the weekly meter |
| Limit Reset Credits | A "3 available · 4h 39m · 7d 2h" badge with every credit's expiry on hover, and an alert when a credit expires within 3 days |
| Usage breakdown / credits history charts | Rendered from the CLI's `usage.details[].chart` and `credits.events` |
| Cost history / spend dashboard | Usage & Spend page with daily chart, projects, models and a per-provider breakdown |
| Token activity heatmap | A 12-month daily/weekly/cumulative heatmap built from `cost --json` daily token totals, with per-day tooltips |
| Preferred currency | Converts spend totals with daily exchange rates (cached 24 h) and offline fallbacks; "Automatic" keeps the reported currency |
| Statistics time zone | "Daily buckets" picker passes `TZ` to the CLI so day boundaries move with the chosen zone |
| Usage history sparkline | The recorded quota history over the last 24 h on each card (macOS live tokens-per-minute requires OpenAI's live API and is not fetched) |
| Provider status badges | Status dot and description per provider |
| Provider accounts | Account list per provider via `--all-accounts` |
| Agent sessions | Sessions page listing the running coding agents |
| Quota notifications, hooks, plugins | Notifications pane, Hooks pane and Plugins pane backed by the CLI |
| Preferences panes | General, Providers, Menu Bar, Display, Notifications, Usage & Spend, Hooks, Plugins, Acknowledgements, Advanced, About |

Still macOS-only upstream and therefore absent here: iCloud fleet sync, widgets,
window-focus for sessions, managed account profiles, browser credential import,
the menu-bar layout editor, remote sessions over Tailscale/SSH and the
`codexbar serve` HTTP backend (this front-end reads local CLI JSON directly).

## Versioning

The GTK front-end uses the same version pair as the macOS bundle:

* `MARKETING_VERSION` in [`VERSION`](VERSION) is the upstream CodexBar release
  this client is feature-compatible with (`0.81.0`).
* `CURRENT_PROJECT_VERSION` is the build number of the Linux front-end.
* `codexbar_gtk/version.py` turns the pair into the macOS-style
  `"0.81.0 (3)"` string shown under Settings → About, in the tray menu and by
  `./run.sh --about`.

Bump both files together when cutting a release; the test suite fails if they
drift apart. [`CHANGELOG.md`](CHANGELOG.md) records, per build, the upstream
release it tracks and exactly which features and new providers arrived in that
build (and which upstream features stay CLI-gated).

## Development

```sh
./run.sh                                  # run from the checkout
python3 -m unittest discover -s tests -v  # the test suite
./tools/preview.py /tmp/preview           # render the UI to PNG files
```

The tests never touch a real provider account: the CLI is faked and the payloads
are recorded fixtures.

## Licence

MIT, like the upstream project.
