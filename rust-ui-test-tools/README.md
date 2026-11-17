# Native UI test tools

`codexbar-ui-test-tool` is the Rust-owned replacement entry point for native
GTK UI automation. It contains no Python runtime, GI binding, or embedded
interpreter. Build it with `cargo build --manifest-path
rust-ui-test-tools/Cargo.toml --locked`.

The chooser path uses the Rust AT-SPI2/zbus proxies and supports `read`, `set`,
`accept`, `select`, and `save`. It scopes the accessible tree to the exact app
PID, bounds traversal, checks visible/sensitive/focused state and screen bounds,
requires exact filename cells and unique tree identities, and confirms the
actual Import/Save response. `isolated-wayland --scenario
settings-combo-diagnostic` preserves the static unsupported result and exit 3.
The chooser's former Recent/Home-place fallback has not yet been ported; when
the exact synthetic file row is absent from the exposed chooser tree, `select`
fails closed instead of navigating a different place.

`isolated-wayland --scenario matrix-core` is a deliberately bounded live Rust
scenario. It launches the supplied native binary under private D-Bus and
rootless Weston with a synthetic HOME/CLI and `GDK_BACKEND=wayland`, then uses
the Rust AT-SPI proxies to assert the Dashboard route, selected Settings
General switch and full preference-map persistence, and Spend's pressed
7-day selection. It captures those three states and checks private process and
HOME cleanup. It is not the legacy `matrix`: Notifications, Hooks, heatmap
modes and Sessions coverage remain unported. The legacy Python matrix stays
available as the evidence reference. `matrix`, Advanced, residual Settings,
page-state, Settings, Spend, and update-check native runner routes continue to
fail closed; the unsupported combo diagnostic remains exit 3.

## Source and hash provenance

The Python parity sources below were inspected at BUILD117 base
`93695ac062818a21f7f38ef67765c0c6fc55774e`. SHA-256 values make the exact
reference snapshot auditable; those files remain present and were not edited.

| Reference source | SHA-256 |
| --- | --- |
| `scripts/native_atspi_rows.py` | `8a651b79ade4584f7785db13456486dabfb1750379c9023c11a8656ba8833fd9` |
| `scripts/select-native-file-chooser.py` | `9aaf7b2337b36881040ad5d02e3c1eff7599a810a14b743ff385cd7922cc5a93` |
| `scripts/test-native-wayland-isolated.py` | `e8fa55718155ebd88b16cdffdb4148a1aea2bb1da24db43ca7d8e7effaef877a` |
| `scripts/test-native-settings-wayland.py` | `0d6a7d2b240105ad4d516af9e6dbe6f21dcba631069eae2d96e3537caef47561` |
| `scripts/test-native-spend-wayland.py` | `35cb6fab33f15863b4e9fba6f25bbaaeb8e1862f3ad0dfd2fdd6eef369bb7b05` |
| `scripts/test-native-update-check-wayland.py` | `10ff6b2812e69405b1ba724959c7d0091414f53009fc7565ddb5528c69985236` |
| `tests/test_native_wayland_isolated_harness.py` | `d731c4ee2876ad7422e06c57435cc96baf6fc307b815580ebcf1dceba7629374` |
| `tests/test_wayland_smoke_guard.py` | `49637774e389d21fe8c775d7034837da00c869b84dd0af3757f32e7f442c40a0` |
| `tests/test_wayland_spend_guard.py` | `934fe240763c7d5be00e537ffc6d6fd517ecae2835e5c8289eae2da5b5e902a3` |
| `tests/test_update_check_wayland_harness.py` | `3d351c9eef22501a83de8e80393affb8b1dc4a4f6c19a965611be63eee799803` |

The Rust unit tests replace only the pure exact-row, window-bound, and fresh
KWin guard predicates so far. They do not represent a full port of the named
Python unit modules or their runner behavior.

AT-SPI actions are named accessible GTK operations. They do not prove physical
Wayland input or KDE shell parity. The isolated Wayland runner must emit
synthetic capture and cleanup evidence before the Python runner is retired.
The settings combo diagnostic keeps its unsupported result at exit code 3.
