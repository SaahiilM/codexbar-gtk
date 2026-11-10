#!/usr/bin/env bash
# Render one activation template without interpreting either template content
# or the binary path. Paths use the installer's deliberately narrow allowlist
# [A-Za-z0-9 /._+@-], which permits spaces but excludes quotes, %, $, newlines,
# backticks and desktop/systemd/shell metacharacters. Desktop Exec and systemd
# ExecStart have distinct whole-line encodings; no eval/sed replacement syntax
# is involved. This only generates files: it does not enable/start services or
# create autostart entries.
set -euo pipefail

fail() { printf 'activation renderer: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 3 ]] || fail 'expected TEMPLATE ABSOLUTE_BINARY_PATH MODE'
template=$1
binary=$2
mode=$3

[[ -f "$template" && -r "$template" ]] || fail 'template must be a readable regular file'
[[ "$binary" == /* ]] || fail 'binary path must be absolute'
[[ "$binary" =~ ^[A-Za-z0-9\ /._+@-]+$ ]] || fail 'binary path contains unsupported characters'

case "$mode" in
  desktop) key='Exec='; suffix=' %U' ;;
  service) key='ExecStart='; suffix='' ;;
  *) fail "unknown mode: $mode" ;;
esac

# Validate the exact key count before writing any output, so ambiguous or
# incomplete templates cannot leave a partially rendered activation file.
matches=0
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" == "$key"* ]] && ((matches += 1))
done < "$template"
[[ $matches -eq 1 ]] || fail "expected exactly one $key line (found $matches)"

while :; do
  line=''
  if IFS= read -r line; then
    had_newline=1
  else
    [[ -n "$line" ]] || break
    had_newline=0
  fi
  if [[ "$line" == "$key"* ]]; then
    printf '%s"%s"%s' "$key" "$binary" "$suffix"
  else
    printf '%s' "$line"
  fi
  [[ "$had_newline" == 1 ]] && printf '\n'
done < "$template"
