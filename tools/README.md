# Native GTK verification tools

The legacy Python preview and B13 smoke helpers in this directory have been
retired. They were developer previews and synthetic UI smoke tools, not the
Python rollback runtime or its active parity tests. Their source remains
recoverable from Git history. The retained Python runtime and parity suite are
still separate from the native UI checks below; these commands do not establish
Python runtime coverage or claim native/Python test equivalence. UG remains
**NOT PASSED** until its documented gate is completed.

## Build

Install Rust plus GTK4/libadwaita development headers and build the native
binary. The default output is `rust-gtk/target/native/codexbar-gtk-native`:

```sh
./scripts/build-native.sh
```

The GTK smokes below need that binary and Xvfb, `dbus-run-session`, `xdotool`,
`gapplication`, and `timeout`; the dashboard smoke also needs `gdbus`, and the
Settings smoke additionally needs `xwd`, `ffmpeg`, `python3-dbus`, PyGObject,
AT-SPI introspection, `xfwm4`, `xprop`, and `xwininfo`.

## Private X11 smokes

Each script starts its own Xvfb display and private D-Bus session. It supplies
synthetic CLI responses and uses temporary XDG configuration/data/cache
directories; no real provider account is needed. These checks do not use the
host display or the host D-Bus session.

```sh
./scripts/smoke-native-dashboard.sh rust-gtk/target/native/codexbar-gtk-native
./scripts/smoke-native-usage-pages.sh rust-gtk/target/native/codexbar-gtk-native
./scripts/smoke-native-settings.sh rust-gtk/target/native/codexbar-gtk-native
```

The dashboard and Settings smokes set a temporary `HOME`; the Usage & Spend
smoke sets temporary XDG directories and uses a synthetic CLI fixture. Optional
screenshot output paths are controlled by the environment variables documented
in each script.

## Private Wayland smoke

The isolated runner starts private Weston and D-Bus sessions, clears inherited
host display/session handles, and creates a private runtime directory and
synthetic home/configuration plus fake CLI data. It needs Weston, Python 3 with
PyGObject and AT-SPI bindings, `dbus-run-session`, and the GTK runtime. The
runner verifies teardown and removes the temporary runtime and home. AT-SPI and
GAction operations are application accessibility actions; they do not represent
physical Wayland input or KDE shell/portal parity.

```sh
python3 scripts/test-native-wayland-isolated.py \
  --binary rust-gtk/target/native/codexbar-gtk-native \
  --scenario matrix
```

Other supported scenarios are `advanced` and `settings-residual`. The
`settings-combo-diagnostic` mode records an unsupported historical mapping and
exits nonzero; it is diagnostic output, not a passing UI smoke.
