#!/usr/bin/env bash
# platform/lib.sh — shared helpers for the pre-Home-Manager shell prelude.
# Sourced by bootstrap.sh; DF_DRY_RUN/DF_VERBOSE/DF_ASSUME_YES/PRIV/SUDO live in
# the environment.

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- one-shot clearance ------------------------------------------------------
# An interactive run prints the whole plan first — what gets installed, from
# which network/mirrors, which config is written or linked — and then asks ONCE
# for clearance. There is deliberately no prompt per step: the value is in
# seeing the full blast radius before anything runs, not in being interrupted
# eight times. A run with no terminal (CI, container build, `bash -c`, cron)
# never asks and behaves exactly as it did before this gate existed;
# `--yes` / DF_ASSUME_YES=1 opts a human out of the prompt (the plan still
# prints).

# is_interactive — is there a terminal to ask? True when stdin is a tty, or when
# stdin is a pipe (`curl … | bash`) but the terminal is still reachable through
# /dev/tty with stdout attached to it — that case is a human at a shell too, and
# it is the one where an unattended install would be most surprising.
is_interactive() {
  [ -t 0 ] && return 0
  [ -t 1 ] && [ -r /dev/tty ] && return 0
  return 1
}

# should_confirm — whether clearance is actually asked for. Dry-run never asks:
# it changes nothing, so there is nothing to clear (and `--dry-run` output should
# print start-to-finish without stopping).
should_confirm() {
  [ "${DF_ASSUME_YES:-0}" = 1 ] && return 1
  [ "${DF_DRY_RUN:-0}" = 1 ] && return 1
  is_interactive
}

# _ask PROMPT — write PROMPT where the human can see it. Prefer the terminal
# directly: with stdout redirected to a log file, a prompt on stdout would be
# invisible while the run blocks on it.
_ask() {
  if [ -w /dev/tty ]; then printf '%b' "$1" >/dev/tty 2>/dev/null || printf '%b' "$1" >&2
  else printf '%b' "$1" >&2
  fi
}

# _read_answer VAR — read one line from the terminal (stdin when it is one,
# else /dev/tty, mirroring is_interactive).
_read_answer() {
  if [ -t 0 ]; then read -r "$1"; else read -r "$1" </dev/tty; fi
}

# require_clearance PROMPT — the single gate. Proceeds (rc 0) or aborts the run;
# it never returns "skip", because the plan it clears is the run. Non-interactive
# / --yes / --dry-run proceed without asking, so callers can call it
# unconditionally. On clearance DF_ASSUME_YES is exported, so the nested scripts
# (nix-cn.sh, setup.py) treat this one answer as the whole run's clearance and do
# not ask again.
require_clearance() {
  local prompt="${1:-Proceed with the plan above?}" ans=""
  if ! should_confirm; then export DF_ASSUME_YES=1; return 0; fi
  while :; do
    _ask "\n\033[1;36m?\033[0m $prompt \033[2m[Y/n]\033[0m "
    if ! _read_answer ans; then _ask "\n"; die "aborted (no answer on the terminal)"; fi
    case "$ans" in
      ""|y|Y|yes|Yes|YES) _ask "\n"; export DF_ASSUME_YES=1; return 0 ;;
      n|N|no|No|NO|q|Q|quit) die "aborted — nothing has been installed or changed" ;;
      *) _ask "  please answer y or n\n" ;;
    esac
  done
}

# ---- the plan ----------------------------------------------------------------
# Steps register what they *would* do here instead of only announcing themselves
# as they run, so the full blast radius can be printed — and cleared — up front.
# Four buckets: facts (host/privilege/network), "will install", "will write /
# link", and "will move aside" — anything that displaces a file the user already
# has. That last one gets its own section, printed last (right above the prompt),
# because it is the only part of a bootstrap that touches existing data; buried
# among fifty symlink lines it would be missed. Rows are stored as "PRIV|TEXT"
# (bash 3.2-compatible: no namerefs).
DF_PLAN_FACTS=() DF_PLAN_INSTALL=() DF_PLAN_CONFIG=() DF_PLAN_BACKUP=()

plan_fact()    { DF_PLAN_FACTS+=("$1|$2"); }
# plan_install / plan_config / plan_backup TEXT [PRIVILEGED] — 1 tags the line.
plan_install() { DF_PLAN_INSTALL+=("${2:-0}|$1"); }
plan_config()  { DF_PLAN_CONFIG+=("${2:-0}|$1"); }
plan_backup()  { DF_PLAN_BACKUP+=("${2:-0}|$1"); }

# plan_import_tsv — merge a nested planner's items, read from stdin as
# `section<TAB>text<TAB>priv` (what `nix-cn.sh --plan` and `setup.py
# --plan-items` emit). Each script describes its own steps; the plan is still one
# document.
plan_import_tsv() {
  local section text priv
  while IFS=$'\t' read -r section text priv; do
    case "$section" in
      install) plan_install "$text" "${priv:-0}" ;;
      config)  plan_config  "$text" "${priv:-0}" ;;
      backup)  plan_backup  "$text" "${priv:-0}" ;;
    esac
  done
}

# plan_section TITLE ROW... — print one bucket (skipped when empty). A TITLE
# starting with "!" is highlighted (the move-aside section).
plan_section() {
  local title="$1" row priv text
  shift
  [ $# -gt 0 ] || return 0
  case "$title" in
    "!"*) printf '\n  \033[1;33m%s\033[0m\n' "${title#!}" ;;
    *)    printf '\n  \033[1m%s\033[0m\n' "$title" ;;
  esac
  local tag
  for row in "$@"; do
    priv="${row%%|*}"; text="${row#*|}"
    tag=""; [ "$priv" = 1 ] && tag="$(printf '  \033[33m[privileged]\033[0m')"
    case "$text" in
      # A leading-space item is a detail of the line above it (a system
      # component under its count) — indent it instead of giving it its own bullet.
      "  "*) printf '      \033[2m%s\033[0m%s\n' "${text#"${text%%[![:space:]]*}"}" "$tag" ;;
      *)     printf '    - %s%s\n' "$text" "$tag" ;;
    esac
  done
}

print_plan() {
  local row name value
  log "Plan — nothing has run yet"
  for row in ${DF_PLAN_FACTS[@]+"${DF_PLAN_FACTS[@]}"}; do
    name="${row%%|*}"; value="${row#*|}"
    printf '  \033[2m%-11s\033[0m %s\n' "$name" "$value"
  done
  plan_section "will install"      ${DF_PLAN_INSTALL[@]+"${DF_PLAN_INSTALL[@]}"}
  plan_section "will write / link" ${DF_PLAN_CONFIG[@]+"${DF_PLAN_CONFIG[@]}"}
  plan_section "!will move your existing files aside (renamed, never deleted)" \
    ${DF_PLAN_BACKUP[@]+"${DF_PLAN_BACKUP[@]}"}
}

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

# detect_os -> darwin | debian | ubuntu | fedora | rhel | amzn | suse | arch |
#              alpine | unknown
# Honest identification, never a guess: an unrecognised Linux is "unknown", NOT
# "debian". The old debian fallback is how an Amazon Linux host ended up running
# `apt-get update` (sudo: apt-get: command not found) — a family this repo has no
# apt for must be *skipped*, and it can only be skipped if it is named correctly.
# Keep the family ids in step with installers/context.py::_detect_os.
detect_os() {
  case "$(uname -s)" in
    Darwin) echo darwin; return ;;
    Linux) : ;;
    *) echo unknown; return ;;
  esac
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    # ID first (exact distro), then ID_LIKE (its family) — ID_LIKE on Amazon
    # Linux says "fedora", which is close enough for dnf but not for anything
    # else, so the exact id wins.
    case "${ID:-}" in
      ubuntu|pop|linuxmint|elementary) echo ubuntu; return ;;
      debian|raspbian) echo debian; return ;;
      amzn) echo amzn; return ;;
      fedora) echo fedora; return ;;
      rhel|centos|rocky|almalinux|ol) echo rhel; return ;;
      opensuse*|sles) echo suse; return ;;
      arch|manjaro|endeavouros) echo arch; return ;;
      alpine) echo alpine; return ;;
    esac
    case " ${ID_LIKE:-} " in
      *ubuntu*) echo ubuntu; return ;;
      *debian*) echo debian; return ;;
      *fedora*|*rhel*|*centos*) echo rhel; return ;;
      *suse*) echo suse; return ;;
      *arch*) echo arch; return ;;
    esac
  fi
  echo unknown
}

# os_pkg_manager OS -> the native package-manager command for that OS family, or
# "" when this repo has no backend for it. The single map both plan_prereqs and
# ensure_prereqs read, so the plan cannot promise an install the run then fails
# to perform (and vice versa). Its python sibling is the PackageManager registry
# in installers/managers.py, keyed the same way by OS family.
os_pkg_manager() {
  case "$1" in
    debian|ubuntu) echo apt-get ;;
    fedora|rhel|amzn)
      # AL2023/Fedora/RHEL9 ship dnf; AL2 and RHEL7 only yum.
      if command -v dnf >/dev/null 2>&1; then echo dnf; else echo yum; fi ;;
    suse) echo zypper ;;
    arch) echo pacman ;;
    alpine) echo apk ;;
    darwin) echo brew ;;
    *) echo "" ;;
  esac
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

# prereq_packages OS — the package names for curl/git/xz on that OS family, or
# "" when there is no known mapping. Second half of the registry above: the
# manager says *how*, this says *what*.
prereq_packages() {
  case "$1" in
    debian|ubuntu) echo "curl git xz-utils ca-certificates" ;;
    fedora|rhel|amzn) echo "curl git xz ca-certificates" ;;
    suse) echo "curl git xz ca-certificates" ;;
    arch) echo "curl git xz ca-certificates" ;;
    alpine) echo "curl git xz ca-certificates" ;;
    *) echo "" ;;
  esac
}

# prereqs_missing — true when curl or git is absent (the only two this prelude
# actually needs before nix exists). Shared by the plan and the run so they
# cannot disagree.
prereqs_missing() {
  ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1
}

# plan_prereqs OS — the plan sibling of ensure_prereqs: same conditions, same
# registry, no action. Keep the two in step when either changes.
plan_prereqs() {
  local os="$1" pm pkgs
  if [ "$os" = darwin ]; then
    command -v git >/dev/null 2>&1 || plan_install "Xcode command line tools (for git)" 1
    return
  fi
  prereqs_missing || return 0
  pm="$(os_pkg_manager "$os")"
  pkgs="$(prereq_packages "$os")"
  if [ -n "$pm" ] && [ -n "$pkgs" ] && [ "$pm" != brew ]; then
    plan_install "prerequisites via $pm: $pkgs" 1
  else
    plan_fact "skipping" "prerequisite install: no package-manager backend for '$os' (install curl/git/xz yourself)"
  fi
}

# ensure_prereqs OS — the few tools needed before nix exists. Needs privilege;
# the caller guards on have_priv. Everything is routed through the os_pkg_manager
# registry: an OS family with no backend (Amazon Linux before this had one, and
# anything still unknown) is SKIPPED with a warning rather than being handed to
# apt-get, which is not there and fails the whole bootstrap.
ensure_prereqs() {
  local os="$1" pm pkgs
  if [ "$os" = darwin ]; then
    command -v git >/dev/null 2>&1 || run "xcode-select --install || true"
    command -v curl >/dev/null 2>&1 || die "curl is required"
    return
  fi
  prereqs_missing || return 0
  pm="$(os_pkg_manager "$os")"
  pkgs="$(prereq_packages "$os")"
  if [ -z "$pm" ] || [ -z "$pkgs" ] || [ "$pm" = brew ]; then
    warn "no package-manager backend for OS '$os': skipping the prereq install."
    warn "install curl, git and xz yourself if the nix install below fails."
    return
  fi
  log "installing prerequisites via $pm (curl git xz)"
  case "$pm" in
    apt-get)
      run "$SUDO apt-get update -qq"
      run "$SUDO apt-get install -y -qq $pkgs"
      ;;
    dnf|yum) run "$SUDO $pm install -y $pkgs" ;;
    zypper)  run "$SUDO zypper --non-interactive install $pkgs" ;;
    pacman)  run "$SUDO pacman -Sy --noconfirm $pkgs" ;;
    apk)     run "$SUDO apk add --no-cache $pkgs" ;;
    *)       warn "unhandled package manager '$pm'; skipping the prereq install" ;;
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
    printf '\033[2m[dry-run]\033[0m ensure ~/.config/nix/nix.conf: flakes + accept-flake-config + empty build-users-group\n'
    return
  fi
  mkdir -p "$HOME/.config/nix"
  append_conf "$HOME/.config/nix/nix.conf" 'experimental-features = nix-command flakes'
  append_conf "$HOME/.config/nix/nix.conf" 'accept-flake-config = true'
  append_conf "$HOME/.config/nix/nix.conf" 'build-users-group ='
}

# Nix deliberately assigns /homeless-shelter as HOME to unsandboxed builds.
# It must be absent: some container images create it, which makes every build
# fail before evaluation.  A common accidental inhabitant is Cargo's home;
# relocate that intact to the actual user's home, but never merge or delete
# unknown contents.
repair_nix_build_home() {
  local build_home="/homeless-shelter" cargo_home="$HOME/.cargo"
  [ -e "$build_home" ] || return 0
  have_priv || die "$build_home exists; root or sudo is required to remove the empty Nix build-home directory"
  if [ ! -d "$build_home" ] || [ -L "$build_home" ]; then
    die "$build_home exists but is not a removable empty directory; remove or rename it, then rerun bootstrap"
  fi
  # Preserve a Cargo installation that was created with HOME incorrectly set
  # to Nix's build sentinel.  Require .cargo to be the sole entry and do not
  # risk an automatic merge with an existing real Cargo home.
  if [ -d "$build_home/.cargo" ] && [ ! -L "$build_home/.cargo" ] \
    && [ -z "$(find "$build_home" -mindepth 1 -maxdepth 1 ! -name .cargo -print -quit)" ]; then
    [ ! -e "$cargo_home" ] && [ ! -L "$cargo_home" ] \
      || die "$build_home/.cargo is misplaced but $cargo_home already exists; merge them manually, then remove $build_home"
    log "moving misplaced Cargo home $build_home/.cargo -> $cargo_home"
    run "$SUDO mv \"$build_home/.cargo\" \"$cargo_home\""
    if [ "${DF_DRY_RUN:-0}" = 1 ]; then
      log "removing empty $build_home (Nix requires it to be absent for unsandboxed builds)"
      run "$SUDO rmdir $build_home"
      return
    fi
  fi
  if [ -n "$(find "$build_home" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    die "$build_home exists and has contents other than a movable lone .cargo directory; refusing to delete it. Move its contents elsewhere, remove the directory, then rerun bootstrap"
  fi
  log "removing empty $build_home (Nix requires it to be absent for unsandboxed builds)"
  run "$SUDO rmdir $build_home"
}

# install_lix — install nix if absent (needs root/sudo; caller guards).
# With an init system: the Lix multi-user (service-managed daemon) installer.
# Without one (container/CI): a single-user install (--no-daemon), which needs
# no daemon/systemd and works in a bare container.
# plan_nix — the plan sibling of install_lix + configure_single_user_nix: which
# nix (if any) gets installed, how, and which nix.conf that flavour writes.
plan_nix() {
  if have_nix; then
    plan_fact "nix" "already installed ($(nix --version 2>/dev/null || echo present)) — not reinstalled"
  elif ! have_priv; then
    plan_fact "nix" "missing, and installing it needs privilege — the run will stop"
  elif has_init_system; then
    plan_install "Lix (multi-user) — fetch install.lix.systems/lix, create /nix, register the nix-daemon service" 1
  else
    plan_install "nix (single-user, --no-daemon) — fetch nixos.org/nix/install, create /nix (no daemon: this host has no init system)" 1
  fi
  has_init_system || plan_config "$HOME/.config/nix/nix.conf <- experimental-features = nix-command flakes; accept-flake-config = true; build-users-group = (single-user)"
  if [ -e /homeless-shelter ]; then
    if [ -d /homeless-shelter ] && [ ! -L /homeless-shelter ] && [ -z "$(find /homeless-shelter -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
      plan_config "/homeless-shelter removed if empty — required by Nix for unsandboxed builds" 1
    elif [ -d /homeless-shelter/.cargo ] && [ ! -L /homeless-shelter/.cargo ] \
      && [ -z "$(find /homeless-shelter -mindepth 1 -maxdepth 1 ! -name .cargo -print -quit 2>/dev/null)" ]; then
      if [ -e "$HOME/.cargo" ] || [ -L "$HOME/.cargo" ]; then
        plan_fact "nix build home" "/homeless-shelter/.cargo and $HOME/.cargo both exist; bootstrap will stop without merging them"
      else
        plan_config "$HOME/.cargo <- move /homeless-shelter/.cargo intact; then remove /homeless-shelter for Nix builds" 1
      fi
    else
      plan_fact "nix build home" "/homeless-shelter exists and is not an empty directory; bootstrap will stop without deleting it"
    fi
  fi
}

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
