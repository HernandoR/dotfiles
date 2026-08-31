#!/usr/bin/env bash
# bootstrap.sh — the ONLY shell in the bootstrap, and deliberately nothing more
# than a Python launcher. Every real step (plan, clearance, prereqs, Lix, nix
# config, the Home Manager switch, the post-HM setup) lives in
# platform/bootstrap.py; see platform/README.md and docs/plans/adr-0007 for the
# design. All arguments are forwarded.
#
#   ./bootstrap.sh --dry-run          # preview every step, run nothing
#   ./bootstrap.sh --yes              # skip the interactive plan clearance
#   ./bootstrap.sh --network CN       # enable China mirrors
#   ./bootstrap.sh --system docker    # + Linux system components
#   ./bootstrap.sh --agents claude    # provision a subset of the agents
#
# The one thing shell must do that Python cannot: make sure a python3 exists.
# Every supported OS either ships one (macOS CLT, most cloud images) or can
# install one with its native package manager — the same "install the
# prerequisite, honestly or not at all" rule the rest of the bootstrap follows
# (an unrecognised distro is told what to do rather than guessed at).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "==> python3 not found — installing it (the bootstrap itself is Python)" >&2
  SUDO=""
  [ "$(id -u)" = 0 ] || { command -v sudo >/dev/null 2>&1 && SUDO="sudo"; }
  if [ "$(uname -s)" = Darwin ]; then
    echo "error: macOS should ship python3 with the command line tools; run: xcode-select --install" >&2
    exit 1
  elif command -v apt-get >/dev/null 2>&1; then
    [ -n "$SUDO" ] || [ "$(id -u)" = 0 ] || { echo "error: need root/sudo to install python3" >&2; exit 1; }
    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y python3
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y python3
  elif command -v zypper >/dev/null 2>&1; then
    $SUDO zypper --non-interactive install python3
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm python
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache python3
  else
    echo "error: no python3 and no recognised package manager — install python3 (>=3.9) yourself, then re-run" >&2
    exit 1
  fi
fi

exec python3 "$DIR/platform/bootstrap.py" "$@"
