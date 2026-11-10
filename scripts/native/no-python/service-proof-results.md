# Private installer/service-target proof — 2026-11-10

Status: local proof passed within the scope below. This is not C02 acceptance,
UG acceptance, service lifecycle proof, or authorization for a default cutover.

## Invocation and artifacts

Reproducible local/CI command from the repository root:

```sh
scripts/smoke-native-service.sh
```

The script builds the current release artifact and the immediately preceding
native source at commit `41d2fcf982aef52cd86a64cb769176b494abb63c` (build 99,
before PR101), using locked offline Cargo builds. It then uses a private Docker
container with `--network none`, private Xvfb and private D-Bus. The container
receives only the two artifacts and staged installer inputs; no host display,
Wayland, user bus, home, or service manager is mounted. Docker's runtime image
build checks that Python executables, Python package directories, PyO3 and
libpython are absent.

Observed artifact SHA-256 values:

- Previous build-99 artifact: `4e1210376ede00e5b3b7e3654905e6a76b084083d0df432f8c5f54938fafba94`
- Current build-100 artifact: `c43d5b4cdd7d8bde8de96afd2a27fd203576491c90111877b68f565d5ae229af`

## Results

- Installed and activated the previous artifact into a synthetic prefix with
  spaces in its path. Seeded synthetic Python desktop/service entries were
  backed up with matching provenance.
- Parsed the installed desktop `Exec` and systemd `ExecStart`; both resolved to
  the same installed binary path. Launched the parsed desktop target and
  observed the exact D-Bus owner PID, `/proc` executable path and artifact hash.
- Upgraded the same prefix to build 100 without an activation flag. Activation
  state and original backup hashes remained intact. Launched the parsed service
  `ExecStart` target and observed its exact PID, executable path and hash.
- Rolled back to the build-99 artifact, launched the parsed desktop target, and
  observed the expected PID, executable path and hash.
- After each graceful app quit, both `com.steipete.CodexBarGTK` and
  `org.kde.StatusNotifierItem-codexbar-gtk` had no owner. The next launch began
  only after those owners were gone.
- Uninstall restored the untouched legacy desktop entry and preserved a
  deliberately user-edited service file while retaining the original service
  backup. Synthetic settings and history bytes were unchanged. The installer
  did not create a second autostart entry.
- `CARGO_NET_OFFLINE=true cargo test --locked --manifest-path
  rust-backend/Cargo.toml
  launch_at_login_updates_desktop_entry_and_shared_preferences` passed (1
  test). It checks the Settings launch-at-login operation writes one autostart
  desktop entry using its supplied executable path and updates the shared
  preference. The target parser tests passed 2/2; shell syntax and
  `git diff --check` passed.

## Scope limits

The private runtime image has no systemd manager. It executes the exact parsed
desktop and `ExecStart` command targets directly, so this is **command-target
proof, not service lifecycle proof**. It does not test `systemctl enable/start`,
systemd `Restart=on-failure`, graphical-session activation, or desktop-shell
activation. The restart cleanup check is a graceful quit followed by a new
launch; it proves stale app/SNI owners are gone between runs, not that systemd
restarted a failed service.

The launch-at-login operation is covered by its synthetic backend unit test;
this smoke does not toggle the Settings widget or exercise AT-SPI. The proof
also does not test the interaction between an enabled user service and an
enabled Settings autostart entry under a real login manager. It does verify the
installer creates no autostart file and that its installed desktop/service
targets share the canonical installed binary path.

No host desktop, input, portal, shared D-Bus, service, autostart, or configuration
was touched. No provider HTTP, account, credential, or authentication fixture
was used. UG remains **NOT PASSED**, Python remains the default, and C gates are
unaccepted.
