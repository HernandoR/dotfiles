#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  edit_home.sh <target_home>
  DOTFILE_EDIT_HOME_TARGET=<target_home> edit_home.sh

Description:
  Change the current user's home directory to the given target path.

Notes:
  - This requires administrator privileges.
  - This script currently supports Linux only.
  - The script uses usermod when available.
EOF
}

error() {
  printf '%s\n' "$*" >&2
}

resolve_target_home() {
  case "$1" in
    "~")
      printf '%s\n' "$HOME"
      ;;
    "~"/*)
      printf '%s/%s\n' "$HOME" "${1#~/}"
      ;;
    /*)
      printf '%s\n' "$1"
      ;;
    *)
      printf '%s/%s\n' "$(pwd -P)" "$1"
      ;;
  esac
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "$#" -gt 0 ]; then
  target_home="$1"
elif [ -n "${DOTFILE_EDIT_HOME_TARGET:-}" ]; then
  target_home="$DOTFILE_EDIT_HOME_TARGET"
else
  usage
  exit 1
fi

target_home=$(resolve_target_home "$target_home")

if [ "$(id -u)" -ne 0 ]; then
  error "Please run this script with sudo or as root."
  exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
  error "Unsupported operating system: $(uname -s)"
  exit 1
fi

current_user="${SUDO_USER:-$(id -un)}"
current_home=$(getent passwd "$current_user" | awk -F: '{print $6}')

if [ -z "$current_home" ]; then
  error "Unable to read the current home directory for user: $current_user"
  exit 1
fi

if [ "$current_home" = "$target_home" ]; then
  printf 'Home directory is already set to %s\n' "$target_home"
  exit 0
fi

if ! command -v usermod >/dev/null 2>&1; then
  error "usermod is required on Linux but was not found."
  exit 1
fi

if [ ! -d "$target_home" ]; then
  mkdir -p "$target_home"
fi

usermod -d "$target_home" -m "$current_user"
printf 'Updated %s home directory from %s to %s\n' "$current_user" "$current_home" "$target_home"