#!/usr/bin/env bash
# brew-cask-interactive-install.sh — MANUAL, interactive Homebrew cask picker
# (macOS). NOT called by the bootstrap. It runs the uv script
# (platform/brew_cask_install.py), which lists the recommended casks to check off
# (edge + alacritty on by default), lets you pick a mirror, then installs them.
#
#   ./brew-cask-interactive-install.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ "$(uname -s)" = Darwin ] || { echo "macOS only (Homebrew casks)." >&2; exit 1; }
command -v uv >/dev/null 2>&1 || {
  echo "uv not found — run the bootstrap first (it installs uv via Home Manager)." >&2
  exit 1
}
command -v brew >/dev/null 2>&1 || {
  echo "Homebrew not found — install it first:  ./bootstrap.sh --system brew" >&2
  exit 1
}

# uv reads the inline PEP723 deps (questionary) and provisions them on demand.
exec uv run "$DIR/platform/brew_cask_install.py" "$@"
