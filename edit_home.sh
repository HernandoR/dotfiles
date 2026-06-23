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

if [ ! -d "$target_home" ]; then
  mkdir -p "$target_home"
fi

if command -v usermod >/dev/null 2>&1; then
  usermod_out=$(usermod -d "$target_home" -m "$current_user" 2>&1) && {
    printf 'Updated %s home directory from %s to %s\n' "$current_user" "$current_home" "$target_home"
    exit 0
  }
  # usermod refuses to modify a user that owns PID 1 (common for root in containers)
  case "$usermod_out" in
    *"currently used by process 1"*) ;;
    *) error "$usermod_out"; exit 1 ;;
  esac
fi

# Fall back: edit /etc/passwd directly (safe when usermod is blocked by PID 1)
passwd_file=/etc/passwd
if [ ! -f "$passwd_file" ]; then
  error "Cannot find $passwd_file; cannot update home directory."
  exit 1
fi
# Replace field 6 (home dir) for the matching user
awk -v user="$current_user" -v home="$target_home" -F: 'BEGIN{OFS=":"} $1==user{$6=home}1' \
  "$passwd_file" > "${passwd_file}.tmp" \
  && mv "${passwd_file}.tmp" "$passwd_file"
printf 'Updated %s home directory from %s to %s (via /etc/passwd)\n' "$current_user" "$current_home" "$target_home"