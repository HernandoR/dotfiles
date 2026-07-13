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

DF_DRY_RUN=0 DF_VERBOSE=0 HOST="" SYSTEM_COMPONENTS="" NO_CLAUDE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DF_DRY_RUN=1 ;;
    --verbose) DF_VERBOSE=1 ;;
    --host) HOST="$2"; shift ;;
    --system) SYSTEM_COMPONENTS="$2"; shift ;;
    --no-claude) NO_CLAUDE=1 ;;
    --network) export DOTFILE_NETWORK_ENV="$2"; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
export DF_DRY_RUN DF_VERBOSE
# --system wins; otherwise fall back to DOTFILE_SYSTEM_COMPONENTS (platform can
# inject it). 'all' selects every optional component (see setup.py / ADR-0007).
SYSTEM_COMPONENTS="${SYSTEM_COMPONENTS:-${DOTFILE_SYSTEM_COMPONENTS:-}}"
# shellcheck source=platform/lib.sh
. "$PLATFORM_DIR/lib.sh"

detect_priv
OS_TYPE="$(detect_os)"
log "OS: $OS_TYPE | arch: $(uname -m) | privilege: $PRIV | network: ${DOTFILE_NETWORK_ENV:-default}"

# The `generic` host reads $USER/$HOME via getEnv at flake-eval time; a bare
# `bash -c` exec context (containers, CI, jcc jobs) often leaves $USER unset, in
# which case the attribute never materializes and the build dies with a cryptic
# "flake does not provide attribute … generic". Populate them from the running
# process so the fallback host always resolves.
export USER="${USER:-$(id -un)}"
export HOME="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}"

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

# Optional: seed flake input sources from a local cache (CN / offline / CI) so
# nixpkgs + home-manager are not fetched from github. Point DOTFILE_FLAKE_CACHE
# at a `nix copy --to file://…` cache dir that contains a seed-paths.txt.
if [ -n "${DOTFILE_FLAKE_CACHE:-}" ] && [ -f "$DOTFILE_FLAKE_CACHE/seed-paths.txt" ]; then
  log "seeding flake inputs from $DOTFILE_FLAKE_CACHE (bypass github)"
  run "nix copy --no-check-sigs --from \"file://$DOTFILE_FLAKE_CACHE\" \$(cat \"$DOTFILE_FLAKE_CACHE/seed-paths.txt\") || true"
fi

# Build the activation package from the flake's LOCKED home-manager (avoids a
# separate `home-manager/master` fetch — more reproducible and one less CN
# github round-trip) and activate it. HOME_MANAGER_BACKUP_EXT=backup is the
# raw-activate equivalent of `switch -b backup`.
if [ "$DF_DRY_RUN" = 1 ]; then
  log "[dry-run] nix build .#homeConfigurations.$HOST.activationPackage $IMPURE ; <out>/activate (HOME_MANAGER_BACKUP_EXT=backup)"
else
  log "home-manager: build activationPackage + activate ($HOST)"
  hm_out="$(nix build --no-link --print-out-paths $IMPURE "$REPO_DIR#homeConfigurations.\"$HOST\".activationPackage")"
  HOME_MANAGER_BACKUP_EXT=backup "$hm_out/activate"
  # HM packages (uv, zsh, …) live in the generation's home-path, not
  # ~/.nix-profile. Put them on PATH so the post-HM Python steps can find uv.
  export PATH="$hm_out/home-path/bin:$PATH"
  # A PATH-independent zsh to hand the user at the end (see the final message).
  # Prefer the stable profile symlink; fall back to this build's home-path.
  zsh_bin="$HOME/.nix-profile/bin/zsh"
  [ -x "$zsh_bin" ] || zsh_bin="$hm_out/home-path/bin/zsh"
fi

# ---- post-HM (python via uv; uv now exists on the HM profile) ---------------
load_nix_path
if ! command -v uv >/dev/null 2>&1 && [ "$DF_DRY_RUN" != 1 ]; then
  warn "uv not found after switch; skipping the Python post-setup"
else
  log "post-setup (uv run platform/setup.py): login shell, SSH keys, Claude, system SW"
  # setup.py self-detects privilege (Ctx.priv, live) — no --priv to pass.
  post_args=""
  [ "$DF_DRY_RUN" = 1 ] && post_args="$post_args --dry-run"
  [ -n "$SYSTEM_COMPONENTS" ] && post_args="$post_args --system $SYSTEM_COMPONENTS"
  [ "$NO_CLAUDE" = 1 ] && post_args="$post_args --no-claude"
  # Prefer a system Python for the stdlib-only platform scripts so uv does not
  # download an interpreter from astral (slow/unreliable on CN networks).
  run "UV_PYTHON_PREFERENCE=system uv run \"$PLATFORM_DIR/setup.py\" $post_args"
fi

# The parent shell that launched bootstrap keeps its old PATH — zsh is NOT on it
# yet, so a bare `zsh` / `exec zsh` fails here. chsh has already made zsh the
# login shell, so a fresh login (new terminal / SSH) starts it automatically; to
# switch *this* session now, exec the absolute path (independent of PATH).
log "Bootstrap complete."
if [ "$DF_DRY_RUN" = 1 ]; then
  log "(dry-run) afterwards, start the Nix shell with: exec zsh -l"
else
  log "Your login shell is now zsh — re-login (new terminal / SSH) to get it, or switch this session now:"
  printf '\n    exec %s -l\n\n' "$zsh_bin"
fi
