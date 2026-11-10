#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERER="$SCRIPT_DIR/native/render_activation.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
ok() { printf 'ok: %s\n' "$*"; }
expect_failure() {
  if bash "$RENDERER" "$@" >"$TMP/out" 2>"$TMP/err"; then
    fail "renderer unexpectedly accepted: $*"
  fi
}

cat > "$TMP/desktop" <<'EOF'
[Desktop Entry]
# keep comment and marker
Exec=old-command %U
X-CodexBar-DesktopFile=codexbar-gtk.desktop
EOF
cat > "$TMP/service" <<'EOF'
[Service]
# service comment
ExecStart=old-command
X-CodexBar-Service=codexbar-gtk.service
EOF
DESKTOP_SHA="$(sha256sum "$TMP/desktop" | awk '{print $1}')"
SERVICE_SHA="$(sha256sum "$TMP/service" | awk '{print $1}')"

bash "$RENDERER" "$TMP/desktop" '/tmp/native prefix/bin/codexbar-gtk-native' desktop > "$TMP/desktop.out"
cat > "$TMP/desktop.expected" <<'EOF'
[Desktop Entry]
# keep comment and marker
Exec="/tmp/native prefix/bin/codexbar-gtk-native" %U
X-CodexBar-DesktopFile=codexbar-gtk.desktop
EOF
cmp -s "$TMP/desktop.expected" "$TMP/desktop.out" || fail 'desktop format/content mismatch'
bash "$RENDERER" "$TMP/service" '/tmp/native prefix/bin/codexbar-gtk-native' service > "$TMP/service.out"
cat > "$TMP/service.expected" <<'EOF'
[Service]
# service comment
ExecStart="/tmp/native prefix/bin/codexbar-gtk-native"
X-CodexBar-Service=codexbar-gtk.service
EOF
cmp -s "$TMP/service.expected" "$TMP/service.out" || fail 'systemd format/content mismatch'
[[ "$(sha256sum "$TMP/desktop" | awk '{print $1}')" == "$DESKTOP_SHA" ]] || fail 'desktop template modified'
[[ "$(sha256sum "$TMP/service" | awk '{print $1}')" == "$SERVICE_SHA" ]] || fail 'service template modified'
ok 'spaced paths, exact encodings, comments, markers and source preservation'

expect_failure "$TMP/desktop" '/tmp/native' unknown
expect_failure "$TMP/desktop" relative/path desktop
expect_failure "$TMP/desktop" '/tmp/no-key' service
printf 'Exec=one\nExec=two\n' > "$TMP/duplicate"
expect_failure "$TMP/duplicate" '/tmp/native' desktop
ok 'unknown mode, nonabsolute path and missing/duplicate keys rejected'

printf '[Desktop Entry]\nExec=old' > "$TMP/no-final-newline"
bash "$RENDERER" "$TMP/no-final-newline" '/tmp/native' desktop > "$TMP/no-final-newline.out"
printf '[Desktop Entry]\nExec="/tmp/native" %%U' > "$TMP/no-final-newline.expected"
cmp -s "$TMP/no-final-newline.expected" "$TMP/no-final-newline.out" || fail 'final-newline state changed'

printf '%s\n' "/tmp/a\$b" '/tmp/a%b' '/tmp/a`b' '/tmp/a"b' '/tmp/a;b' > "$TMP/bad-paths"
while IFS= read -r bad_path; do
  expect_failure "$TMP/desktop" "$bad_path" desktop
done < "$TMP/bad-paths"
marker="$TMP/command-ran"
if bash "$RENDERER" "$TMP/desktop" "\$(touch $marker)" desktop >"$TMP/out" 2>"$TMP/err"; then
  fail 'command-shaped path unexpectedly accepted'
fi
[[ ! -e "$marker" ]] || fail 'renderer executed command-shaped path'
newline_path=$'/tmp/native\nsecond-line'
expect_failure "$TMP/desktop" "$newline_path" desktop
ok 'dollar, percent, newline, backtick, quote and metacharacters rejected without execution'
