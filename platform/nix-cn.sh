#!/usr/bin/env bash
# platform/nix-cn.sh — configure nix: ensure flakes, and (only when
# DOTFILE_NETWORK_ENV=CN) wire the CERNET mirror at the SYSTEM level so the
# multi-user daemon serves it to every user (a user-level substituter is ignored
# for non-trusted users — ADR-0007).
#
# Always persists the network choice to ~/.config/dotfiles/network-env (the HM
# .zshenv sources it to gate the pypi/uv/rustup mirror vars). System nix.conf
# edits need privilege; when PRIV=none they are skipped (the existing nix config
# is used as-is).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$DIR/.." && pwd)}"
# shellcheck source=platform/lib.sh
. "$DIR/lib.sh"
[ -n "${PRIV:-}" ] || detect_priv

NETWORK_ENV="${DOTFILE_NETWORK_ENV:-}"
CERNET="https://mirrors.cernet.edu.cn/nix-channels/store"

# --- persist the network choice for the HM shell (no privilege needed) -------
run "mkdir -p \"$HOME/.config/dotfiles\""
if [ "$NETWORK_ENV" = "CN" ]; then
  run "printf 'export DOTFILE_NETWORK_ENV=CN\n' > \"$HOME/.config/dotfiles/network-env\""
else
  run "rm -f \"$HOME/.config/dotfiles/network-env\""
fi

if ! have_priv; then
  warn "no privilege: leaving the system nix.conf untouched (using existing mirrors)"
  exit 0
fi

# --- pick the system nix.conf target (Lix uses !include nix.custom.conf) ------
SYS_CONF="/etc/nix/nix.conf"
target="$SYS_CONF"
if [ -f "$SYS_CONF" ] && grep -q '!include nix.custom.conf' "$SYS_CONF" 2>/dev/null; then
  target="/etc/nix/nix.custom.conf"
fi

need_restart=0
ensure_line() {
  # read check needs no privilege (/etc/nix/*.conf is world-readable); only the
  # write does, so dry-run never prompts for a password.
  local file="$1" line="$2"
  if ! grep -qxF "$line" "$file" 2>/dev/null; then
    run "printf '%s\n' \"$line\" | $SUDO tee -a \"$file\" >/dev/null"
    need_restart=1
  fi
}

log "ensuring flakes in $target"
run "$SUDO mkdir -p /etc/nix"
run "$SUDO touch \"$target\""
if ! grep -rhq 'experimental-features.*flakes' /etc/nix/ 2>/dev/null; then
  ensure_line "$target" "experimental-features = nix-command flakes"
fi

if [ "$NETWORK_ENV" = "CN" ]; then
  log "CN network: adding CERNET substituter + trusting $USER (system level)"
  ensure_line "$target" "extra-substituters = $CERNET"
  ensure_line "$target" "extra-trusted-substituters = $CERNET"
  ensure_line "$target" "trusted-users = root $USER"
else
  log "non-CN network: leaving substituters at upstream defaults"
fi

if [ "$need_restart" = 1 ]; then
  log "restarting nix-daemon to apply config"
  case "$(detect_os)" in
    darwin) run "$SUDO launchctl kickstart -k system/org.nixos.nix-daemon" ;;
    *)      run "$SUDO systemctl restart nix-daemon 2>/dev/null || true" ;;
  esac
fi
