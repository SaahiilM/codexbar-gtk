# Linux desktop: provider switcher, agent sessions and a card refresh

Four focused changes to the Qt/QML desktop app, each buildable and testable on
its own. No new runtime dependency, no new provider fetching, no change to the
Swift CLI.

## Why

The macOS app is the reference for this project and the Linux desktop app was
still catching up on three points:

- the menu bar shows a **provider switcher** with live usage per provider, while
  the Linux tray only ever showed the first provider's two meters;
- the macOS app lists **agent sessions**, and the CLI already reports them
  (`codexbar sessions --json-v2`);
- four providers (**OpenAI, Azure OpenAI, Alibaba Token Plan, Moonshot**) have no
  `ProviderIcon` asset, so the Linux app rendered an empty slot for them.

## Changes

### 1. `fix(linux): draw a provider monogram when no brand icon exists`

`ProviderIconProvider` returned an empty image when the SVG was missing, which
left those providers without an icon in the tray and the dashboard. It now draws
the provider initial in its accent colour, picking black or white for contrast.

### 2. `feat(linux): add an agent sessions tab`

New **Sessions** tab in the dashboard listing the coding agents the CLI sees
(provider, project, path, pid). The probe is opt-in — sessions are only listed
when the tab is opened — so the usage path keeps exactly the CLI calls it has
today. The rows carry project names and paths, never account identity.

### 3. `feat(linux): list every provider in the tray menu`

The tray menu gets a **Providers** submenu with a live line per provider
(`Codex — Session 48% used · Weekly 6% used`), mirroring the macOS switcher. The
tray icon now follows the provider with the highest usage instead of always the
first one; a new **Tray icon shows** preference (`highest` / `first`) controls
that, next to the existing tray style option.

### 4. `feat(linux): refresh the provider card design`

The cards now look like the macOS ones: provider icon and plan badge in the
header, a rounded meter in the provider's accent colour, the reset countdown
and the pace as chips, and a divider before the balances. Every provider has a
stable accent colour, so several cards stay readable side by side.

## Commands run

```sh
# build
cd Integrations/Linux && mkdir -p ../../.local/linux-build && cd ../../.local/linux-build
qmake6 ../../Integrations/Linux/codexbar-linux.pro && make -j4

# tests (the upstream suite plus the new cases)
cd Integrations/Linux
CODEXBAR_LINUX_BINARY=$PWD/../../.local/linux-build/codexbar-linux \
  python3 -m unittest discover -s tests -p "test_*.py"
# Ran 29 tests — OK
```

## Screenshots

_Usage dashboard with the refreshed cards, the Sessions tab and the tray menu
with the provider switcher._

## Notes

- The tray switcher reuses the existing `entries` payload; no extra CLI call.
- The sessions tab is opt-in on purpose: the spending scan is already opt-in, and
  the upstream tests assert the exact CLI call sequence of a usage refresh.
- The accent colours are hashed per provider id, so a new provider gets a
  colour without touching this file.
