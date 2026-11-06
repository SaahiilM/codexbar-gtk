#!/usr/bin/env bash
# Install the native Rust GTK binary (codexbar-gtk-native) from a prebuilt artifact.
#
#   ./scripts/install-native.sh --artifact PATH [--prefix DIR] [--activate | --no-activate]
#   ./scripts/install-native.sh --uninstall [--prefix DIR]
#
# Default is ADDITIVE and side-effect-free regarding desktop/service: installs
# only PREFIX/bin/codexbar-gtk-native plus a manifest. It never creates
# .pre-native backups unless --activate is requested.
#
# Activation rendering depends on scripts/native/render_activation.py
# (python3). This is a C01 preparation-time requirement only; it is NOT
# part of the installed runtime. C02 (absent-Python runtime proof) remains
# unproven — the installed ELF is what runs without Python, the installer
# helper is not shipped in the prefix.
set -euo pipefail
: "${HOME:?HOME must identify the installation user}"
[[ "$HOME" == /* ]] || { echo "HOME must be absolute" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
STAGE_DESKTOP="$SCRIPT_DIR/native/stage/native.desktop"
STAGE_SERVICE="$SCRIPT_DIR/native/stage/native.service"
RENDERER="$SCRIPT_DIR/native/render_activation.py"

ARTIFACT=""
PREFIX_DIR="${PREFIX:-${HOME:-}/.local}"
ACTIVATE="" # empty = inherit previous manifest (upgrade preserves activation)
UNINSTALL=0
REQUESTED_ACTIVATE=0
RENDER_DIR=""
cleanup_rendered_files() {
  if [[ -n "$RENDER_DIR" ]]; then rm -rf -- "$RENDER_DIR"; fi
}
trap cleanup_rendered_files EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) ARTIFACT="$2"; shift 2 ;;
    --prefix) PREFIX_DIR="$2"; shift 2 ;;
    --activate) ACTIVATE=1; REQUESTED_ACTIVATE=1; shift ;;
    --no-activate) ACTIVATE=0; REQUESTED_ACTIVATE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

BIN_DEST="$PREFIX_DIR/bin/codexbar-gtk-native"
MANIFEST="$PREFIX_DIR/share/codexbar-gtk/native-manifest"
DATA_DIR="$PREFIX_DIR/share/applications"
DESKTOP_DEST="$DATA_DIR/codexbar-gtk.desktop"
UNIT_DEST="${HOME:-}/.config/systemd/user/codexbar-gtk.service"

# Explicit allowlist validation: supported characters are exactly
# [A-Za-z0-9 /._+@-] (space included). Anything else — newline, backtick,
# dollar, percent, quote, shell/desktop/systemd metacharacters — is rejected
# BEFORE any side effect. A denylist cannot cover this; allowlist does.
validate_binary_path() {
  local path="$1"
  case "$path" in
    /*) ;;
    *) echo "binary path must be absolute: $path" >&2; exit 1 ;;
  esac
  if [[ ! "$path" =~ ^[A-Za-z0-9\ /._+@-]+$ ]]; then
    echo "unsupported characters in binary path for safe desktop/systemd quoting: $path" >&2
    echo "rename the prefix to use only [A-Za-z0-9 /._+@-] and reinstall" >&2
    exit 1
  fi
}

is_ours_file() { grep -q "X-CodexBar-DesktopFile=codexbar-gtk.desktop" "$1" 2>/dev/null; }
is_ours_service() { grep -q "X-CodexBar-Service=codexbar-gtk.service" "$1" 2>/dev/null; }

atomic_write() {
  local dest="$1" src="$2"
  local dir tmp
  dir="$(dirname "$dest")"
  mkdir -p "$dir"
  tmp="$dir/.tmp-native-install.$$"
  cp -a "$src" "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$dest"
}

read_manifest_value() {
  local key="$1"
  [[ -f "$MANIFEST" ]] || { printf ''; return 0; }
  awk -F= -v k="$key" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$MANIFEST"
}

sha_of() { sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

do_uninstall() {
  local bin_sha des_bak des_pre svc_bak svc_pre des_sha svc_sha prev_activated
  bin_sha="$(read_manifest_value binary_sha256 || true)"
  prev_activated="$(read_manifest_value activated || true)"

  # Remove binary only when hash matches manifest (preserve foreign/user edits).
  if [[ -n "$bin_sha" && -f "$BIN_DEST" ]]; then
    local cur
    cur="$(sha_of "$BIN_DEST")"
    if [[ "$cur" == "$bin_sha" ]]; then rm -f "$BIN_DEST"; else echo "binary preserved (hash differs from manifest)" >&2; fi
  fi

  # Activation-file restore/remove only when this install was activated.
  if [[ "$prev_activated" == "1" ]]; then
    des_pre="$(read_manifest_value desktop_preexisting || true)"
    des_bak="$(read_manifest_value desktop_backup || true)"
    des_sha="$(read_manifest_value desktop_sha256 || true)"
    svc_pre="$(read_manifest_value service_preexisting || true)"
    svc_bak="$(read_manifest_value service_backup || true)"
    svc_sha="$(read_manifest_value service_sha256 || true)"
    # Desktop: restore backup only if current file is ours AND hash matches
    # what we installed; else leave user-edited files alone.
    if [[ -f "$DESKTOP_DEST" ]]; then
      local cur_d
      cur_d="$(sha_of "$DESKTOP_DEST")"
      if [[ "$des_pre" == "1" && -n "$des_bak" && -f "$des_bak" ]]; then
        if [[ "$cur_d" == "$des_sha" ]]; then
          mv -f "$des_bak" "$DESKTOP_DEST"
        else
          echo "desktop preserved (current hash differs from installed; not restored over user edit)" >&2
        fi
      elif is_ours_file "$DESKTOP_DEST" && [[ "$cur_d" == "$des_sha" ]]; then
        rm -f "$DESKTOP_DEST"
      else
        echo "desktop preserved (not owned/current-hash mismatch)" >&2
      fi
    fi
    if [[ -f "$UNIT_DEST" ]]; then
      local cur_s
      cur_s="$(sha_of "$UNIT_DEST")"
      if [[ "$svc_pre" == "1" && -n "$svc_bak" && -f "$svc_bak" ]]; then
        if [[ "$cur_s" == "$svc_sha" ]]; then
          mv -f "$svc_bak" "$UNIT_DEST"
        else
          echo "service preserved (current hash differs from installed; not restored over user edit)" >&2
        fi
      elif is_ours_service "$UNIT_DEST" && [[ "$cur_s" == "$svc_sha" ]]; then
        rm -f "$UNIT_DEST"
      else
        echo "service preserved (not owned/current-hash mismatch)" >&2
      fi
    fi
  fi
  rm -f "$MANIFEST"
  echo "native CodexBar removed (additive uninstall)."
}

do_install() {
  [[ -n "$ARTIFACT" ]] || { echo "--artifact is required for install" >&2; exit 1; }
  [[ -x "$ARTIFACT" ]] || { echo "artifact not executable: $ARTIFACT" >&2; exit 1; }

  # Previous manifest for upgrade semantics (preserve activation + backups).
  local prev_activated prev_bin_sha prev_des_pre prev_des_bak prev_des_sha prev_svc_pre prev_svc_bak prev_svc_sha
  prev_activated="$(read_manifest_value activated || true)"
  prev_bin_sha="$(read_manifest_value binary_sha256 || true)"
  prev_des_pre="$(read_manifest_value desktop_preexisting || true)"
  prev_des_bak="$(read_manifest_value desktop_backup || true)"
  prev_des_sha="$(read_manifest_value desktop_sha256 || true)"
  prev_svc_pre="$(read_manifest_value service_preexisting || true)"
  prev_svc_bak="$(read_manifest_value service_backup || true)"
  prev_svc_sha="$(read_manifest_value service_sha256 || true)"

  # Reject foreign binary that does not match previous manifest hash; also
  # reject an existing BIN_DEST with NO prior manifest (no ownership record).
  if [[ -f "$BIN_DEST" ]]; then
    local cur_bin
    cur_bin="$(sha_of "$BIN_DEST")"
    if [[ -z "$prev_bin_sha" ]]; then
      echo "existing binary at $BIN_DEST with no manifest ownership (hash $cur_bin); refusing to overwrite" >&2
      echo "move it aside or uninstall first" >&2
      exit 1
    fi
    if [[ "$cur_bin" != "$prev_bin_sha" ]]; then
      echo "existing binary at $BIN_DEST is not ours (hash $cur_bin != manifest $prev_bin_sha); refusing to overwrite" >&2
      echo "move it aside or uninstall first" >&2
      exit 1
    fi
  fi

  if [[ -z "$ACTIVATE" ]]; then
    # No explicit flag: preserve previous activation on upgrade; first install
    # defaults to no activation.
    if [[ -n "$prev_activated" ]]; then ACTIVATE="$prev_activated"; else ACTIVATE=0; fi
  fi

  # Unsupported transition: explicit --no-activate over an activated install
  # would leave canonical activation files installed while marking
  # deactivated — uninstall would then orphan them. Reject before any side
  # effect; use --uninstall instead.
  if [[ "$ACTIVATE" == "0" && "$prev_activated" == "1" && "$REQUESTED_ACTIVATE" == "1" ]]; then
    echo "explicit --no-activate over an activated install is unsupported; run --uninstall first" >&2
    exit 1
  fi

  # Validate path before any side effect.
  validate_binary_path "$BIN_DEST"

  # Rendering can fail (missing Python, broken template, or renderer error).
  # Complete BOTH renders before replacing binaries, backups, or the manifest.
  if [[ "$ACTIVATE" == "1" ]]; then
    RENDER_DIR="$(mktemp -d)"
    if ! python3 "$RENDERER" "$STAGE_DESKTOP" "$BIN_DEST" desktop > "$RENDER_DIR/desktop" ||
       ! python3 "$RENDERER" "$STAGE_SERVICE" "$BIN_DEST" service > "$RENDER_DIR/service"; then
      echo "activation rendering failed; installation unchanged" >&2
      exit 1
    fi
  fi

  # Atomic binary swap (rename over existing owned binary).
  local dir tmp
  dir="$(dirname "$BIN_DEST")"
  mkdir -p "$dir"
  tmp="$dir/.tmp-native-install.$$"
  cp -a "$ARTIFACT" "$tmp"
  chmod 755 "$tmp"
  mv -f "$tmp" "$BIN_DEST"
  local bin_sha
  bin_sha="$(sha_of "$BIN_DEST")"

  local des_pre des_bak des_sha svc_pre svc_bak svc_sha
  des_pre="$prev_des_pre"; des_bak="$prev_des_bak"; des_sha="$prev_des_sha"
  svc_pre="$prev_svc_pre"; svc_bak="$prev_svc_bak"; svc_sha="$prev_svc_sha"

  if [[ "$ACTIVATE" == "1" ]]; then
    # On first activation only, capture pre-existing foreign files and back
    # them up. On upgrade of an already-activated install, provenance is
    # already recorded; never re-back-up our own rendered files over the
    # original Python backup.
    if [[ "$prev_activated" != "1" ]]; then
      if [[ -e "$DESKTOP_DEST" ]]; then
        des_pre=1
        if ! is_ours_file "$DESKTOP_DEST"; then
          des_bak="${DESKTOP_DEST}.pre-native"
          cp -a "$DESKTOP_DEST" "$des_bak"
        fi
      else
        des_pre=0; des_bak=""
      fi
      if [[ -e "$UNIT_DEST" ]]; then
        svc_pre=1
        if ! is_ours_service "$UNIT_DEST"; then
          svc_bak="${UNIT_DEST}.pre-native"
          cp -a "$UNIT_DEST" "$svc_bak"
        fi
      else
        svc_pre=0; svc_bak=""
      fi
    fi
    atomic_write "$DESKTOP_DEST" "$RENDER_DIR/desktop"
    atomic_write "$UNIT_DEST" "$RENDER_DIR/service"
    des_sha="$(sha_of "$DESKTOP_DEST")"
    svc_sha="$(sha_of "$UNIT_DEST")"
  fi

  mkdir -p "$(dirname "$MANIFEST")"
  local tmpm
  tmpm="$(dirname "$MANIFEST")/.tmp-native-manifest.$$"
  {
    printf 'binary_path=%s\n' "$BIN_DEST"
    printf 'binary_sha256=%s\n' "$bin_sha"
    printf 'activated=%s\n' "$ACTIVATE"
    printf 'desktop_path=%s\n' "$DESKTOP_DEST"
    printf 'desktop_preexisting=%s\n' "$des_pre"
    printf 'desktop_backup=%s\n' "$des_bak"
    printf 'desktop_sha256=%s\n' "$des_sha"
    printf 'service_path=%s\n' "$UNIT_DEST"
    printf 'service_preexisting=%s\n' "$svc_pre"
    printf 'service_backup=%s\n' "$svc_bak"
    printf 'service_sha256=%s\n' "$svc_sha"
    printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$tmpm"
  mv -f "$tmpm" "$MANIFEST"

  echo "==> Native CodexBar installed (additive)."
  echo "    binary  : $BIN_DEST (sha256 $bin_sha)"
  echo "    activate: $ACTIVATE"
  if [[ "$ACTIVATE" == "1" ]]; then
    echo "    desktop : $DESKTOP_DEST"
    echo "    service : $UNIT_DEST"
  fi
}

if [[ "$UNINSTALL" == "1" ]]; then do_uninstall; exit 0; fi
do_install
