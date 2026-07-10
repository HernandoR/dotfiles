#!/usr/bin/env bash
# nix-system-interactive-install.sh — MANUAL interactive picker for system-level
# components (docker/docker-rootless/cuda/nvidia/llvm/software-properties on
# Linux, brew on macOS), to run AFTER the bootstrap when you want to add more.
# NOT auto-run. Delegates to the uv script (platform/nix_system_install.py),
# which installs via the same machinery the bootstrap uses.
#
#   ./nix-system-interactive-install.sh            # pick + install
#   ./nix-system-interactive-install.sh --dry-run  # preview only
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null 2>&1 || {
  echo "uv not found — run the bootstrap first (it installs uv via Home Manager)." >&2
  exit 1
}
exec uv run "$DIR/platform/nix_system_install.py" "$@"
