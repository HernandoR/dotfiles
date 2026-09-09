#!/usr/bin/env bash
# bootstrap.sh — the ONLY shell in the bootstrap, and deliberately nothing more
# than a launcher for scripts/bootstrap.py (ADR-0013). Every real step — the
# plan, the clearance, prerequisites, zoi, chezmoi, mise, `chezmoi apply` and
# the scripts it runs — lives in scripts/. All arguments are forwarded.
#
#   ./bootstrap.sh --dry-run            # preview every step, run nothing
#   ./bootstrap.sh --yes                # skip the interactive plan clearance
#   ./bootstrap.sh --env mewtant        # a named environment (state root, extra links)
#   ./bootstrap.sh --network CN         # enable China mirrors
#   ./bootstrap.sh --system docker      # + Linux system components
#   ./bootstrap.sh --agents claude      # provision a subset of the agents
#
# The one thing shell must do that Python cannot: make sure `uv` exists, since
# uv is what provides the Python the scripts run on (no system python needed).
# Download-then-execute, never `curl | sh`.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || { echo "error: curl is required to install uv" >&2; exit 1; }
  echo "==> uv not found — installing it into ~/.local/bin (the bootstrap runs on uv)" >&2
  tmp="$(mktemp)"
  curl -fsSL --retry 3 https://astral.sh/uv/install.sh -o "$tmp"
  UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$tmp"
  rm -f "$tmp"
  command -v uv >/dev/null 2>&1 || { echo "error: uv install failed" >&2; exit 1; }
fi

exec uv run --script "$DIR/scripts/bootstrap.py" "$@"
