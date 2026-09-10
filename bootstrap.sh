#!/usr/bin/env bash
# bootstrap.sh — the ONLY shell in the bootstrap, and deliberately nothing more
# than a launcher for scripts/bootstrap.py (ADR-0013). Every real step — the
# plan, the clearance, prerequisites, Homebrew (macOS), chezmoi, mise, `chezmoi apply` and
# the scripts it runs — lives in scripts/. All arguments are forwarded.
#
#   ./bootstrap.sh --dry-run            # preview every step, run nothing
#   ./bootstrap.sh --interactive        # ask before running the plan (default: unattended)
#   ./bootstrap.sh --env mewtant        # a named environment (state root, extra links)
#   ./bootstrap.sh --network CN         # enable China mirrors
#   ./bootstrap.sh --system docker      # + Linux system components
#   ./bootstrap.sh --agents claude      # provision a subset of the agents
#
# The one thing shell must do that Python cannot: make sure `uv` exists, since
# uv is what provides the Python the scripts run on (no system python needed).
# The shared prelude is also used by chezmoi's run_before tool phase.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
. "$DIR/scripts/uv-bootstrap.sh"
ensure_uv

exec uv run --script "$DIR/scripts/bootstrap.py" "$@"
