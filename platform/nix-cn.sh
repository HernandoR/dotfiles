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
#
#   nix-cn.sh          apply
#   nix-cn.sh --plan   describe the same steps as `config<TAB>text<TAB>priv`
#                      lines for bootstrap.sh's plan; changes nothing
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$DIR/.." && pwd)}"
# shellcheck source=platform/lib.sh
. "$DIR/lib.sh"
[ -n "${PRIV:-}" ] || detect_priv

MODE=apply
case "${1:-}" in
  "")     ;;
  --plan) MODE=plan ;;
  *)      die "unknown arg: $1 (expected --plan)" ;;
esac

NETWORK_ENV="${DOTFILE_NETWORK_ENV:-}"
CERNET="https://mirrors.cernet.edu.cn/nix-channels/store"
MARKER="$HOME/.config/dotfiles/network-env"

# --- what this host needs (read-only; shared by --plan and the apply path) ----

# conf_target — which system file gets the settings. Lix's /etc/nix/nix.conf ends
# with `!include nix.custom.conf`, and edits belong in that include rather than
# in the file the installer manages.
conf_target() {
  local sys="/etc/nix/nix.conf"
  if [ -f "$sys" ] && grep -q '!include nix.custom.conf' "$sys" 2>/dev/null; then
    echo /etc/nix/nix.custom.conf
  else
    echo "$sys"
  fi
}

# missing_lines TARGET — the settings TARGET still lacks, one per line. Reading
# /etc/nix needs no privilege (world-readable), so --plan and --dry-run never
# trigger a sudo password prompt.
missing_lines() {
  local target="$1" line
  if ! grep -rhq 'experimental-features.*flakes' /etc/nix/ 2>/dev/null; then
    echo "experimental-features = nix-command flakes"
  fi
  if [ "$NETWORK_ENV" = "CN" ]; then
    for line in "extra-substituters = $CERNET" \
                "extra-trusted-substituters = $CERNET" \
                "trusted-users = root $USER"; do
      grep -qxF "$line" "$target" 2>/dev/null || echo "$line"
    done
  fi
}

# --- plan mode (describe only) ------------------------------------------------
if [ "$MODE" = plan ]; then
  emit() { printf 'config\t%s\t%s\n' "$1" "${2:-0}"; }
  if [ "$NETWORK_ENV" = "CN" ]; then
    emit "$MARKER <- export DOTFILE_NETWORK_ENV=CN (the HM zsh sources it: pypi/uv + rustup mirrors)"
  else
    emit "$MARKER removed — upstream mirrors everywhere"
  fi
  if ! have_priv; then
    emit "system nix.conf left untouched (no root/sudo)"
    exit 0
  fi
  target="$(conf_target)"
  pending=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    emit "$target <- $line" 1
    pending=1
  done <<EOF
$(missing_lines "$target")
EOF
  [ "$pending" = 1 ] && emit "restart the nix-daemon to apply $target" 1
  exit 0
fi

# --- persist the network choice for the HM shell (no privilege needed) -------
run "mkdir -p \"$HOME/.config/dotfiles\""
if [ "$NETWORK_ENV" = "CN" ]; then
  run "printf 'export DOTFILE_NETWORK_ENV=CN\n' > \"$MARKER\""
else
  run "rm -f \"$MARKER\""
fi

if ! have_priv; then
  warn "no privilege: leaving the system nix.conf untouched (using existing mirrors)"
  exit 0
fi

target="$(conf_target)"
if [ "$NETWORK_ENV" = "CN" ]; then
  log "CN network: CERNET substituter + trusting $USER (system level) in $target"
else
  log "non-CN network: ensuring flakes in $target (substituters stay upstream)"
fi
run "$SUDO mkdir -p /etc/nix"
run "$SUDO touch \"$target\""

need_restart=0
# A heredoc, not a pipe: a piped `while` runs in a subshell and its assignment to
# need_restart would be lost.
while IFS= read -r line; do
  [ -n "$line" ] || continue
  run "printf '%s\n' \"$line\" | $SUDO tee -a \"$target\" >/dev/null"
  need_restart=1
done <<EOF
$(missing_lines "$target")
EOF

if [ "$need_restart" = 1 ]; then
  log "restarting nix-daemon to apply config"
  case "$(detect_os)" in
    darwin) run "$SUDO launchctl kickstart -k system/org.nixos.nix-daemon" ;;
    *)      run "$SUDO systemctl restart nix-daemon 2>/dev/null || true" ;;
  esac
fi
