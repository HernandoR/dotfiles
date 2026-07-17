#!/usr/bin/env bash
# platform/lib.sh — shared helpers for the pre-Home-Manager shell prelude.
# Sourced by bootstrap.sh; DF_DRY_RUN/DF_VERBOSE/PRIV/SUDO live in the environment.

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# run CMD... — execute, or print under --dry-run. Use for side-effecting steps.
run() {
  if [ "${DF_DRY_RUN:-0}" = 1 ]; then
    printf '\033[2m[dry-run]\033[0m %s\n' "$*"
  else
    [ "${DF_VERBOSE:-0}" = 1 ] && printf '\033[2m$ %s\033[0m\n' "$*"
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
  # Source whichever profile exists (multi-user nix-daemon.sh or single-user
  # nix.sh). They reference unbound vars, so relax -u/-e around the source.
  set +u +e
  for f in \
    /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh \
    "$HOME/.nix-profile/etc/profile.d/nix.sh"; do
    # shellcheck disable=SC1090
    [ -e "$f" ] && . "$f" >/dev/null 2>&1
  done
  set -u -e
  export PATH="$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH"
}

# has_init_system — true if a service manager can run the multi-user nix-daemon
# (systemd on Linux, launchd on macOS). Bare `docker run` containers have none.
has_init_system() {
  case "$(uname -s)" in
    Darwin) return 0 ;;
    Linux) [ -d /run/systemd/system ] ;;
    *) return 1 ;;
  esac
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

# append_conf FILE LINE — add LINE if absent, always on its own line. A file
# whose last line lacks a trailing newline would otherwise get the new setting
# glued onto it (e.g. `substituters = …cache.nixos.org/` + `experimental-features
# = …` -> an unparseable value). Normalise the trailing newline first.
append_conf() {
  local file="$1" line="$2"
  grep -qF "$line" "$file" 2>/dev/null && return 0
  [ -s "$file" ] && [ -n "$(tail -c1 "$file" 2>/dev/null)" ] && echo >> "$file"
  echo "$line" >> "$file"
}

# configure_single_user_nix — ensure the user-level nix.conf enables flakes and
# sets an EMPTY build-users-group. A single-user (--no-daemon) install has no
# `nixbld` build-user pool, so Nix's compiled-in default (build-users-group =
# nixbld) makes every build fail with "the group 'nixbld' … does not exist".
# Idempotent and independent of whether Nix was just installed, so an install
# interrupted before the config was written self-heals on the next run.
configure_single_user_nix() {
  if [ "${DF_DRY_RUN:-0}" = 1 ]; then
    printf '\033[2m[dry-run]\033[0m ensure ~/.config/nix/nix.conf: flakes + empty build-users-group\n'
    return
  fi
  mkdir -p "$HOME/.config/nix"
  append_conf "$HOME/.config/nix/nix.conf" 'experimental-features = nix-command flakes'
  append_conf "$HOME/.config/nix/nix.conf" 'build-users-group ='
}

# install_lix — install nix if absent (needs root/sudo; caller guards).
# With an init system: the Lix multi-user (service-managed daemon) installer.
# Without one (container/CI): a single-user install (--no-daemon), which needs
# no daemon/systemd and works in a bare container.
install_lix() {
  if have_nix; then
    log "nix already installed ($(nix --version 2>/dev/null || echo present)); skipping install"
    return
  fi
  if [ "${DF_DRY_RUN:-0}" = 1 ]; then
    if has_init_system; then
      printf '\033[2m[dry-run]\033[0m install Lix (multi-user): curl -sSf -L https://install.lix.systems/lix | sh -s -- install --no-confirm\n'
    else
      printf '\033[2m[dry-run]\033[0m no init system -> single-user: sh <(curl -L https://nixos.org/nix/install) --no-daemon --yes\n'
    fi
    return
  fi
  # fetch_retry URL OUT — download with retries (CN networks flake on
  # nixos.org / install.lix.systems TLS).
  fetch_retry() {
    local url="$1" out="$2" i
    for i in 1 2 3 4; do
      if curl -fsSL --connect-timeout 15 --retry 3 --retry-connrefused \
        --retry-delay 2 "$url" -o "$out"; then return 0; fi
      warn "download failed ($url) attempt $i/4; retrying"
      sleep 3
    done
    return 1
  }

  if has_init_system; then
    log "installing Lix (multi-user, service-managed daemon)"
    if fetch_retry https://install.lix.systems/lix /tmp/lix-install.sh; then
      sh /tmp/lix-install.sh install --no-confirm \
        || { warn "Lix installer failed; classic multi-user fallback"; \
             fetch_retry https://nixos.org/nix/install /tmp/nix-install.sh \
               && sh /tmp/nix-install.sh --daemon --yes; }
    else
      warn "Lix fetch failed; classic multi-user fallback"
      fetch_retry https://nixos.org/nix/install /tmp/nix-install.sh \
        && sh /tmp/nix-install.sh --daemon --yes
    fi
  else
    log "no init system (container/CI): single-user nix install (--no-daemon)"
    # The single-user installer creates /nix via `sudo` even when we already
    # run as root; a bare container may have no sudo (the installer then dies
    # with "please manually run 'mkdir -m 0755 /nix …'"). Pre-create /nix owned
    # by the calling user so the installer skips that sudo call entirely.
    if [ ! -e /nix ]; then
      log "pre-creating /nix (installer would otherwise shell out to sudo)"
      run "$SUDO mkdir -m 0755 /nix && $SUDO chown \"$(id -un)\" /nix"
    fi
    # Single-user (especially as root) has no `nixbld` build-user pool; disable
    # it so builds run as the calling user. Set it for the installer's own nix
    # calls AND persist it for later use.
    fetch_retry https://nixos.org/nix/install /tmp/nix-install.sh \
      || die "could not download the nix installer (network); retry later"
    # Nix wants a ~60 MiB thread stack; a 10 MiB hard limit makes it warn
    # "Stack size hard limit … less than the desired …" on every child. Raise
    # this shell's limit before the installer runs so the nix children inherit
    # it. Raising a *hard* limit needs privilege, and `ulimit` is a builtin
    # (so $SUDO can't wrap it — it must run in *this* shell): as root use the
    # builtin directly; under a sudo account have a privileged `prlimit` raise
    # this shell's limit by PID instead. Best-effort — a failure just leaves
    # the (benign) warning in place.
    if [ "$PRIV" = root ]; then
      ulimit -Hs 61440 2>/dev/null || true
    elif [ "$PRIV" = sudo ] && command -v prlimit >/dev/null 2>&1; then
      $SUDO prlimit --pid "$$" --stack=62914560:62914560 2>/dev/null || true
    fi
    NIX_CONFIG="build-users-group =" sh /tmp/nix-install.sh --no-daemon --yes
    # The user nix.conf (flakes + empty build-users-group) is written by
    # configure_single_user_nix, which bootstrap.sh calls unconditionally on the
    # no-init-system path — so an install interrupted before this point still
    # gets a correct config on the next run (have_nix then skips reinstalling).
  fi
  load_nix_path
}
