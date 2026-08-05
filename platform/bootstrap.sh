#!/usr/bin/env bash
# platform/bootstrap.sh — imperative layer for the Nix + Home Manager dotfiles
# (ADR-0007). Home Manager owns the user environment declaratively; this handles
# what it cannot on a non-NixOS host, split around the Home Manager switch:
#
#   pre-HM  (shell; no nix/uv yet):  privilege → prereqs → install Lix →
#                                    configure nix (+CN mirror) → home-manager switch
#   post-HM (python via `uv run`):   login shell → Claude → system SW
#
# Privilege model:
#   root  — run privileged steps directly (no sudo)
#   sudo  — run privileged steps via sudo
#   none  — skip everything needing sudo; do only the user-level nix/HM steps.
#           If nix is not installed (and can't be, without privilege) → exit
#           cleanly.
#
# Clearance:
#   On an interactive terminal the whole plan is printed first — what gets
#   installed, from which network/mirrors, which config is written or linked —
#   and then cleared ONCE. A run with no terminal (CI, container build, cron)
#   never asks; --yes/-y skips the prompt but still prints the plan.
#
# Usage:
#   ./platform/bootstrap.sh [--host NAME] [--system LIST] [--network CN]
#                           [--yes] [--dry-run] [--verbose]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_DIR="$REPO_DIR/platform"
export REPO_DIR

DF_DRY_RUN=0 DF_VERBOSE=0 HOST="" SYSTEM_COMPONENTS="" NO_CLAUDE=0
# DF_ASSUME_YES=1 (env or --yes) disables the interactive confirmations. It is
# exported so the nested scripts (nix-cn.sh, setup.py) inherit the choice.
DF_ASSUME_YES="${DF_ASSUME_YES:-0}"
# a value-taking flag must not swallow the next option as its value: `--system
# -h` should error, not silently treat `-h` as the component list (which skips
# --help and kicks off a real install).
need_val() {
  case "${2-}" in
    ""|-*) echo "error: $1 requires a value (got '${2-}')" >&2; exit 2 ;;
  esac
}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DF_DRY_RUN=1 ;;
    --verbose) DF_VERBOSE=1 ;;
    -y|--yes) DF_ASSUME_YES=1 ;;
    --host) need_val "$1" "${2-}"; HOST="$2"; shift ;;
    --system) need_val "$1" "${2-}"; SYSTEM_COMPONENTS="$2"; shift ;;
    --no-claude) NO_CLAUDE=1 ;;
    --network) need_val "$1" "${2-}"; export DOTFILE_NETWORK_ENV="$2"; shift ;;
    -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
export DF_DRY_RUN DF_VERBOSE DF_ASSUME_YES
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

# ---- the plan + the one-shot clearance --------------------------------------
# Everything below this point mutates the machine, so describe all of it first
# and take a single yes/no. The post-HM half is described by the script that owns
# it (setup.py --plan-items, stdlib-only so it runs on a system python3 before
# Home Manager provides uv); the same args are reused for the real run, so the
# plan and the run cannot drift. Without a system python3 the plan says so rather
# than guessing.
post_args=""
[ "$DF_DRY_RUN" = 1 ] && post_args="$post_args --dry-run"
[ -n "$SYSTEM_COMPONENTS" ] && post_args="$post_args --system $SYSTEM_COMPONENTS"
[ "$NO_CLAUDE" = 1 ] && post_args="$post_args --no-claude"

plan_fact "os" "$OS_TYPE ($(uname -m))"
plan_fact "host" "$HOST${IMPURE:+ (impure — \$USER/\$HOME read at eval time)}"
case "$PRIV" in
  root) plan_fact "privilege" "root — privileged steps run directly (no sudo)" ;;
  sudo) plan_fact "privilege" "sudo — privileged steps run via sudo (may ask for your password)" ;;
  none) plan_fact "privilege" "none — every privileged step is skipped" ;;
esac
if [ "${DOTFILE_NETWORK_ENV:-}" = "CN" ]; then
  plan_fact "network" "CN — CERNET for nix, BFSU for brew, and the pypi/uv + rustup mirrors"
else
  plan_fact "network" "upstream defaults (pass --network CN for the China mirrors)"
fi

if have_priv; then
  plan_prereqs "$OS_TYPE"
else
  plan_fact "skipping" "prereq + nix install (no privilege): the existing nix is used as-is"
fi
plan_nix
if [ -n "${DOTFILE_FLAKE_CACHE:-}" ] && [ -f "$DOTFILE_FLAKE_CACHE/seed-paths.txt" ]; then
  plan_install "flake inputs seeded from $DOTFILE_FLAKE_CACHE (no github fetch)"
fi
plan_install "Home Manager generation for '$HOST' — the whole user environment from home/ (zsh, starship, git, tmux, mise, the CLI toolset)"
plan_config "Home Manager symlinks into $HOME from the nix store (~/.zshrc, ~/.config/git, ~/.tmux.conf, …)"
plan_backup "any \$HOME file Home Manager wants to own -> the same name with a .backup suffix (HOME_MANAGER_BACKUP_EXT=backup)"
# Command substitution inside `if` so a failing planner is reported in the plan
# instead of being swallowed (process substitution would hide its exit status).
if plan_tsv="$("$PLATFORM_DIR/nix-cn.sh" --plan)"; then
  plan_import_tsv <<<"$plan_tsv"
else
  plan_config "nix config: could not be planned (nix-cn.sh --plan failed)"
fi
if ! command -v python3 >/dev/null 2>&1; then
  plan_config "post-Home-Manager steps (login shell, Claude, system components) — not detailed here: no system python3 yet"
# shellcheck disable=SC2086  # post_args is a deliberate word list
elif plan_tsv="$(python3 "$PLATFORM_DIR/setup.py" --plan-items $post_args)"; then
  plan_import_tsv <<<"$plan_tsv"
else
  plan_config "post-Home-Manager steps: could not be planned (setup.py --plan-items failed)"
fi

print_plan
require_clearance "Proceed with this plan?"

# ---- pre-HM (shell) ---------------------------------------------------------
if have_priv; then
  ensure_prereqs "$OS_TYPE"
  install_lix
else
  warn "no privilege: skipping prereq + Lix install (using the existing nix)"
fi
load_nix_path

# Single-user (no init system: bare docker/CI) has no `nixbld` build-user pool,
# so Nix's default build-users-group=nixbld fails every build. Ensure the user
# nix.conf neutralizes it — unconditional (not only on a fresh install), so an
# interrupted or partial install repairs itself on re-run. Needs no privilege.
if ! has_init_system; then
  configure_single_user_nix
fi

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
  log "post-setup (uv run platform/setup.py): login shell, Claude, system SW"
  # setup.py self-detects privilege (Ctx.priv, live) — no --priv to pass. Its half
  # of the plan is already cleared, and $DF_ASSUME_YES (exported by
  # require_clearance) tells it not to ask again. post_args was built with the
  # plan, above, so --plan-items described exactly this invocation.
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
