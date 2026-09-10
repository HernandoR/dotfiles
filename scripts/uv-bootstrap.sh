#!/bin/sh
# Shared shell prelude for the two bootstrap entry points.  It owns only the
# circular prerequisites that Python cannot provide for itself.

is_outside_nix() {
  tool_path="$(command -v "$1" 2>/dev/null || true)"
  case "$tool_path" in
    ""|/nix/*|*/.nix-profile/*) return 1 ;;
    *) return 0 ;;
  esac
}

ensure_uv() {
  if is_outside_nix uv; then
    return
  fi
  command -v curl >/dev/null 2>&1 || { echo "error: curl is required to install uv" >&2; exit 1; }
  echo "==> uv not found outside Nix — installing it into ~/.local/bin (the bootstrap runs on uv)" >&2
  tool_tmp="$(mktemp)"
  trap 'rm -f "$tool_tmp"' EXIT HUP INT TERM
  curl -fsSL --retry 3 https://astral.sh/uv/install.sh -o "$tool_tmp"
  UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$tool_tmp"
  rm -f "$tool_tmp"
  trap - EXIT HUP INT TERM
  is_outside_nix uv || { echo "error: uv install failed" >&2; exit 1; }
}

ensure_brew_path() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi
  for brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$brew_path" ]; then
      eval "$("$brew_path" shellenv)"
      return
    fi
  done
}

# Kept as one shell list so a fresh apply can avoid Python startup. check.py
# asserts that it equals scripts/tools.py:TOOLS.
DECLARED_TOOLS="chezmoi mise"

tools_present() {
  ensure_brew_path
  for tool_name in $DECLARED_TOOLS; do
    is_outside_nix "$tool_name" || return 1
  done
  if [ "$(uname -s)" = Darwin ]; then
    command -v brew >/dev/null 2>&1 || return 1
  fi
}
