#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  edit_home.sh <target_home>
  DOTFILE_EDIT_HOME_TARGET=<target_home> edit_home.sh

Description:
  Change the current user's home directory to the given target path.
  After updating the home, merges .ssh/authorized_keys from the old home
  into the new home and deduplicates the result.

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

merge_ak() {
  src="$1"
  dst_ssh="$2/.ssh"
  dst="$dst_ssh/authorized_keys"

  [ -f "$src" ] || return 0

  mkdir -p "$dst_ssh"
  chmod 700 "$dst_ssh"

  if [ -f "$dst" ]; then
    cat "$src" >> "$dst"
    # Deduplicate in-place; preserve insertion order, drop blank lines
    awk 'NF && !/^[[:space:]]*#/ && !seen[$0]++' "$dst" > "${dst}.tmp" \
      && mv "${dst}.tmp" "$dst"
    printf 'Merged authorized_keys from %s into %s\n' "$src" "$dst"
  else
    cp "$src" "$dst"
    printf 'Copied authorized_keys to %s\n' "$dst"
  fi
  chmod 600 "$dst"
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

# Snapshot new home's authorized_keys before usermod -m might overwrite it
_ak_snap=""
if [ -f "$target_home/.ssh/authorized_keys" ]; then
  _ak_snap=$(mktemp)
  cp "$target_home/.ssh/authorized_keys" "$_ak_snap"
fi

if [ ! -d "$target_home" ]; then
  mkdir -p "$target_home"
fi

home_updated=0

if command -v usermod >/dev/null 2>&1; then
  usermod_out=$(usermod -d "$target_home" -m "$current_user" 2>&1) && home_updated=1 || {
    # usermod refuses to modify a user that owns PID 1 (common for root in containers)
    case "$usermod_out" in
      *"currently used by process 1"*) ;;
      *) error "$usermod_out"; exit 1 ;;
    esac
  }
fi

if [ "$home_updated" -eq 0 ]; then
  # Fall back: edit /etc/passwd directly (safe when usermod is blocked by PID 1)
  passwd_file=/etc/passwd
  if [ ! -f "$passwd_file" ]; then
    error "Cannot find $passwd_file; cannot update home directory."
    exit 1
  fi
  awk -v user="$current_user" -v home="$target_home" -F: 'BEGIN{OFS=":"} $1==user{$6=home}1' \
    "$passwd_file" > "${passwd_file}.tmp" \
    && mv "${passwd_file}.tmp" "$passwd_file"
fi

# Merge authorized_keys from old home (no-op if usermod -m already moved them)
merge_ak "$current_home/.ssh/authorized_keys" "$target_home"
# Restore any pre-existing keys in the new home that usermod -m may have overwritten
if [ -n "$_ak_snap" ]; then
  merge_ak "$_ak_snap" "$target_home"
  rm -f "$_ak_snap"
fi

printf 'Updated %s home directory from %s to %s\n' "$current_user" "$current_home" "$target_home"