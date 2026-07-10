#!/usr/bin/env bash
# platform/lib.sh — shared helpers for the pre-Home-Manager shell prelude.
# Sourced by bootstrap.sh; DRY_RUN/VERBOSE/PRIV/SUDO live in the environment.

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# run CMD... — execute, or print under --dry-run. Use for side-effecting steps.
run() {
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf '\033[2m[dry-run]\033[0m %s\n' "$*"
  else
    [ "${VERBOSE:-0}" = 1 ] && printf '\033[2m$ %s\033[0m\n' "$*"
    eval "$@"
  fi
}

# detect_priv -> PRIV (root|sudo|none) + SUDO ("" or "sudo"). Bootstrap may be
# started as root, as a normal user with sudo, or (rarely) with no privilege.
detect_priv() {
  if [ "$(id -u)" = 0 ]; then
    PRIV=root; SUDO=""
  elif command -v sudo >/dev/null 2>&1; then
    PRIV=sudo; SUDO="sudo"
  else
    PRIV=none; SUDO=""
  fi
  export PRIV SUDO
}
have_priv() { [ "${PRIV:-none}" != none ]; }
have_nix()  { command -v nix >/dev/null 2>&1 || [ -x /nix/var/nix/profiles/default/bin/nix ]; }

# load_nix_path — make nix (and, post-switch, the HM profile incl. uv) callable
# in this process.
load_nix_path() {
  local f=/nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
  # nix-daemon.sh references unbound vars; source it with -u/-e relaxed so it
  # doesn't trip our `set -euo pipefail`.
  if [ -e "$f" ]; then
    set +u +e
    # shellcheck disable=SC1090
    . "$f" >/dev/null 2>&1 || true
    set -u -e
  fi
  export PATH="$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH"
}

# detect_os -> darwin | debian | ubuntu | unknown
detect_os() {
  case "$(uname -s)" in
    Darwin) echo darwin; return ;;
    Linux) : ;;
    *) echo unknown; return ;;
  esac
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}${ID_LIKE:-}" in
      *ubuntu*) echo ubuntu; return ;;
      *debian*) echo debian; return ;;
    esac
  fi
  echo unknown
}

# detect_named_host OS -> a named flake host by hostname, else by OS+arch.
detect_named_host() {
  local os="$1" hn arch
  hn="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo)"
  if [ -n "$hn" ] && nix_host_exists "$hn"; then echo "$hn"; return; fi
  arch="$(uname -m)"
  if [ "$os" = darwin ]; then echo "LiuzhendeMacBook-Pro"; return; fi
  case "$arch" in
    aarch64|arm64) echo "dotfiles-linux-arm" ;;
    *)             echo "dotfiles-debian" ;;
  esac
}

# nix_host_exists NAME -> 0 if flake.nix defines hosts.<NAME> (grep; no nix eval,
# so it works before nix is installed).
nix_host_exists() {
  grep -qE "\"$1\"[[:space:]]*=" "${REPO_DIR:-.}/flake.nix" 2>/dev/null
}

# ensure_prereqs OS — the few tools needed before nix exists. Needs privilege;
# the caller guards on have_priv.
ensure_prereqs() {
  local os="$1"
  case "$os" in
    debian|ubuntu)
      if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
        log "installing prerequisites (curl git xz)"
        run "$SUDO apt-get update -qq"
        run "$SUDO apt-get install -y -qq curl git xz-utils ca-certificates"
      fi
      ;;
    darwin)
      command -v git >/dev/null 2>&1 || run "xcode-select --install || true"
      command -v curl >/dev/null 2>&1 || die "curl is required"
      ;;
    *) warn "unknown OS; assuming curl/git/xz are present" ;;
  esac
}

# install_lix — install Lix if nix is absent (needs root/sudo; caller guards).
install_lix() {
  if have_nix; then
    log "nix already installed ($(nix --version 2>/dev/null || echo present)); skipping Lix install"
    return
  fi
  log "installing Lix (flakes-capable nix)"
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf '\033[2m[dry-run]\033[0m curl -sSf -L https://install.lix.systems/lix | sh -s -- install --no-confirm\n'
    return
  fi
  if ! curl -sSf -L https://install.lix.systems/lix | sh -s -- install --no-confirm; then
    warn "Lix installer failed; falling back to the CppNix installer"
    sh <(curl -L https://nixos.org/nix/install) --daemon --yes
  fi
  load_nix_path
}
