# Native GTK verification tools

The native application and its UI automation are Rust-owned. The six former
Python UI scripts, their four harness test modules, and the Python harness unit
launcher have been retired in BUILD121. Their source remains recoverable from
Git history, but no Python/KDE implementation is claimed as equivalent.

## Retained native commands

```sh
./scripts/build-native.sh
./run.sh
./scripts/test-native-tray-dbus.sh
cargo test --manifest-path rust-ui-test-tools/Cargo.toml --locked
./scripts/smoke-native-no-python.sh --artifact rust-gtk/target/native/codexbar-gtk-native
```

## Private X11 smokes

Each smoke starts its own Xvfb display and private D-Bus session. It supplies
synthetic CLI responses and temporary HOME/XDG directories; no real provider
account is needed. The Settings smoke needs `xwd`, `ffmpeg`, `xfwm4`, `xprop`,
and `xwininfo` in addition to GTK and X11 tools.

```sh
./scripts/smoke-native-dashboard.sh rust-gtk/target/native/codexbar-gtk-native
./scripts/smoke-native-usage-pages.sh rust-gtk/target/native/codexbar-gtk-native
./scripts/smoke-native-settings.sh rust-gtk/target/native/codexbar-gtk-native
```

## Private Wayland smoke

Build `rust-ui-test-tools` and the native app, then run a named scenario using
the Rust AT-SPI runner. It creates private Weston and D-Bus sessions, clears
inherited host display/session handles, and uses synthetic HOME/XDG directories
and CLI fixtures. It does not use KDE portals, the KDE bridge, physical input,
or real configuration. Passing private Weston checks does not establish KDE
shell, portal, physical-input, or helper-mode parity. The retired KDE
`--inspect-only`, portal and bridge modes were not ported or directly verified
by this migration.

```sh
cargo build --manifest-path rust-gtk/Cargo.toml --locked
cargo build --manifest-path rust-ui-test-tools/Cargo.toml --locked
rust-ui-test-tools/target/debug/codexbar-ui-test-tool update-check-wayland \
  --binary rust-gtk/target/debug/codexbar-gtk-native \
  --artifact-dir /tmp/native-wayland-update-check
```

See [the tool README](../rust-ui-test-tools/README.md) for scenario coverage and
limits. Temporary artifact directories should contain only synthetic evidence.

## Recovering a retired utility

Find its deletion commit, then inspect or restore its last version from the
parent commit:

```sh
git log --all --diff-filter=D --format='%H %s' -- tools/activate_window.py
git show <deletion-commit>^:tools/activate_window.py
git restore --source=<deletion-commit>^ -- tools/activate_window.py
```
