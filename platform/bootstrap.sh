#!/usr/bin/env bash
# platform/bootstrap.sh — imperative layer for the Nix + Home Manager dotfiles
# (ADR-0007). Home Manager owns the user environment declaratively; this handles
# what it cannot on a non-NixOS host, split around the Home Manager switch:
#
#   pre-HM  (shell; no nix/uv yet):  privilege → prereqs → install Lix →
#                                    configure nix (+CN mirror) → home-manager switch
#   post-HM (python via `uv run`):   login shell → SSH keys → Claude → system SW
#
# Privilege model:
#   root  — run privileged steps directly (no sudo)
#   sudo  — run privileged steps via sudo
#   none  — skip everything needing sudo; do only the user-level nix/HM steps.
#           If nix is not installed (and can't be, without privilege) → exit
#           cleanly.
#
# Usage:
#   ./platform/bootstrap.sh [--host NAME] [--system LIST] [--network CN]
#                           [--dry-run] [--verbose]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_DIR="$REPO_DIR/platform"
export REPO_DIR

DRY_RUN=0 VERBOSE=0 HOST="" SYSTEM_COMPONENTS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --verbose) VERBOSE=1 ;;
    --host) HOST="$2"; shift ;;
    --system) SYSTEM_COMPONENTS="$2"; shift ;;
    --network) export DOTFILE_NETWORK_ENV="$2"; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
export DRY_RUN VERBOSE
# shellcheck source=platform/lib.sh
. "$PLATFORM_DIR/lib.sh"

detect_priv
OS_TYPE="$(detect_os)"
log "OS: $OS_TYPE | arch: $(uname -m) | privilege: $PRIV | network: ${DOTFILE_NETWORK_ENV:-default}"

# ---- host selection ---------------------------------------------------------
# Named hosts assume the owner (user lz). For any other user (incl. root) fall
# back to the impure `generic` host, which reads $USER/$HOME at eval time.
IMPURE=""
if [ -z "$HOST" ]; then
  if [ "$(id -un)" = "lz" ]; then
    HOST="$(detect_named_host "$OS_TYPE")"
  else
    HOST="generic"
  fi
fi
if [ "$HOST" = "generic" ]; then
  IMPURE="--impure"
elif ! nix_host_exists "$HOST"; then
  die "host '$HOST' is not defined in flake.nix"
fi
log "flake host: $HOST${IMPURE:+ (impure)}"

# ---- privilege / nix availability gate --------------------------------------
if ! have_priv && ! have_nix; then
  die "No root/sudo and nix is not installed — installing nix needs privilege.
     Ask an admin to install Nix (or re-run as root / with sudo), then retry.
     Exiting cleanly without changes."
fi

# ---- pre-HM (shell) ---------------------------------------------------------
if have_priv; then
  ensure_prereqs "$OS_TYPE"
  install_lix
else
  warn "no privilege: skipping prereq + Lix install (using the existing nix)"
fi
load_nix_path

# nix flakes + CN mirror (privileged; the script itself no-ops the sudo parts
# when PRIV=none, but still persists the network-env marker for the HM shell)
"$PLATFORM_DIR/nix-cn.sh"

log "home-manager switch --flake .#$HOST -b backup"
run "nix run home-manager/master -- switch -b backup $IMPURE --flake \"$REPO_DIR#$HOST\""

# ---- post-HM (python via uv; uv now exists on the HM profile) ---------------
load_nix_path
if ! command -v uv >/dev/null 2>&1 && [ "$DRY_RUN" != 1 ]; then
  warn "uv not found after switch; skipping the Python post-setup"
else
  log "post-setup (uv run platform/setup.py): login shell, SSH keys, Claude, system SW"
  post_args="--priv $PRIV"
  [ "$DRY_RUN" = 1 ] && post_args="$post_args --dry-run"
  [ -n "$SYSTEM_COMPONENTS" ] && post_args="$post_args --system $SYSTEM_COMPONENTS"
  run "uv run \"$PLATFORM_DIR/setup.py\" $post_args"
fi

log "Bootstrap complete. Open a new shell (or 'exec zsh') to activate the Nix env."
