# dotfiles — the repeatable half of the Home Manager workflow.
#
# Every recipe here is a command the README already documents; the Justfile
# exists so it is one name instead of a remembered incantation. `just` itself
# comes from mise (home/mise.nix).
#
# The flake host is resolved the way platform/bootstrap.sh resolves it. Override
# it per run — `just host=dotfiles-debian switch` — or via DF_HOST in the
# environment.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Host selection. Mirrors platform/bootstrap.sh:91-102 (named hosts assume the
# owner; any other user, including root, gets the impure `generic` fallback) by
# reusing the same lib.sh helpers. Keep the two in step when either changes.
host := env('DF_HOST',
    ```
    . platform/lib.sh
    if [ "$(id -un)" = lz ]; then
      detect_named_host "$(detect_os)"
    else
      echo generic
    fi
    ```)

# `generic` reads $USER/$HOME at eval time (flake.nix:55), so it only
# materializes under --impure.
impure := if host == "generic" { "--impure" } else { "" }

# List every recipe.
default:
    @just --list --unsorted

# Print the resolved flake host and how it will be built.
show-host:
    @echo '{{ host }} {{ if impure == "--impure" { "(impure)" } else { "(pure)" } }}'

# Build the activation package and print its store path. Changes nothing in $HOME.
build:
    @nix build --no-link --print-out-paths {{ impure }} '.#homeConfigurations."{{ host }}".activationPackage'

# Build, then apply. Same path the bootstrap takes: activation comes from the
# *locked* home-manager (no `home-manager/master` fetch) and works before the HM
# CLI is on PATH. A real file where a symlink belongs is renamed to *.backup.
[doc('Build the activation package and activate it (-b backup).')]
switch:
    #!/usr/bin/env bash
    set -euo pipefail
    out="$(just host='{{ host }}' build)"
    HOME_MANAGER_BACKUP_EXT=backup "$out"/activate
    echo "activated: $out — run 'exec zsh -l' to pick up the new PATH/env"

# Start over from the repo: move every $HOME path this generation would own into
# one timestamped backup, then activate onto the cleared ground.
#
# `switch` renames a file in the way to <name>.backup, which scatters backups
# through $HOME and — worse — collides with the .backup left by a previous cycle,
# aborting the whole activation (ADR-0009 update log). Moving the paths away
# first means HM finds nothing in the way at all, so nothing is renamed and
# nothing can collide.
#
# Recoverable by construction: everything is MOVED, never deleted, into
# ~/dotfiles_backup/<stamp>/ under its original $HOME-relative name. Note it does
# not sweep pre-existing *.backup files — those are a previous cycle's business.
#
# An env-linked path (~/.claude, ~/.ssh, …) is a symlink, so moving it takes the
# link and leaves the data in envLinks.stateRoot untouched; the activation just
# relinks it.
[doc('Back up every managed $HOME path to ~/dotfiles_backup/<stamp>/, then activate.')]
reset-hard:
    #!/usr/bin/env bash
    set -euo pipefail
    out="$(just host='{{ host }}' build)"
    dest="$HOME/dotfiles_backup/$(date +%Y_%m_%d_%H%M%S)"

    # What HM will own: every leaf of the generation's home-files tree. Leaves are
    # files and symlinks — a whole-dir env link is itself a symlink, so this never
    # descends into one. `-print` + stripping "./" rather than GNU's `-printf`,
    # which BSD/macOS find does not have.
    present=()
    while IFS= read -r p; do
      rel="${p#./}"
      if [ -e "$HOME/$rel" ] || [ -L "$HOME/$rel" ]; then present+=("$rel"); fi
    done < <(cd "$out/home-files" && find . -mindepth 1 \( -type f -o -type l \) -print | sort)

    # ADR-0009 recorded this hazard for a first bootstrap; this recipe is the other
    # way to reach it. If ~/.ssh is still a REAL dir holding authorized_keys while
    # the persistent target has none, moving it aside and linking to the empty
    # target severs inbound SSH to the machine you are provisioning.
    state="$(nix eval --raw {{ impure }} '.#homeConfigurations."{{ host }}".config.envLinks.stateRoot' 2>/dev/null || true)"
    if [ -d "$HOME/.ssh" ] && [ ! -L "$HOME/.ssh" ] && [ -e "$HOME/.ssh/authorized_keys" ] \
       && [ -n "$state" ] && [ ! -e "$state/.ssh/authorized_keys" ]; then
      echo "refusing: ~/.ssh has authorized_keys but $state/.ssh does not." >&2
      echo "seed the target first — mkdir -p '$state/.ssh' && cp -a ~/.ssh/. '$state/.ssh/' — or" >&2
      echo "run this from a session that does not depend on SSH to this host." >&2
      exit 1
    fi

    # One plan, one clearance (ADR-0010) — this is the only recipe that moves your
    # files, so it says exactly which ones before touching any.
    echo "==> reset-hard — nothing has moved yet"
    echo "  host      {{ host }}"
    echo "  activate  $out"
    echo "  backup    $dest"
    echo
    if [ "${#present[@]}" -eq 0 ]; then
      echo "  nothing to move — no managed path exists in \$HOME yet"
    else
      echo "  will move aside (${#present[@]}, renamed under the backup dir, never deleted):"
      printf '    - ~/%s\n' "${present[@]}"
    fi
    echo
    # Deliberately NOT bootstrap.sh's "no terminal -> proceed" rule. This is the
    # one recipe that moves your files, and a non-interactive caller (script, CI,
    # an agent) has no way to answer — so silence must mean stop, not yes. Say
    # DF_ASSUME_YES=1 to mean it.
    if [ "${DF_ASSUME_YES:-}" != "1" ]; then
      if [ ! -t 0 ]; then
        echo "refusing: not a terminal and DF_ASSUME_YES is unset — re-run with DF_ASSUME_YES=1 to proceed" >&2
        exit 1
      fi
      read -r -p "? Move these and activate? [y/N] " ans
      case "$ans" in [yY]|[yY][eE][sS]) ;; *) echo "aborted — nothing moved"; exit 1 ;; esac
    fi

    for rel in ${present[@]+"${present[@]}"}; do
      mkdir -p "$dest/$(dirname "$rel")"
      mv "$HOME/$rel" "$dest/$rel"
    done
    HOME_MANAGER_BACKUP_EXT=backup "$out"/activate
    echo "activated: $out"
    echo "previous state: $dest — run 'exec zsh -l' to pick up the new PATH/env"

# What would change: build, then diff the closure against the live generation.
diff:
    #!/usr/bin/env bash
    set -euo pipefail
    out="$(just host='{{ host }}' build)"
    for p in "$HOME/.local/state/nix/profiles/home-manager" \
             "/nix/var/nix/profiles/per-user/$USER/home-manager"; do
      if [ -e "$p" ]; then exec nix store diff-closures "$p" "$out"; fi
    done
    echo "no live home-manager profile to diff against; built: $out" >&2

# Evaluate every named host. Pure, so the impure `generic` host is invisible here.
check:
    nix flake check

# Update flake inputs. `just update nixpkgs` for one; no argument updates all.
# Commit the changed flake.lock with the change that needed it.
[doc('Update flake inputs — all of them, or just the ones named.')]
update *INPUTS:
    nix flake update {{ INPUTS }}

# Update inputs, apply, and move mise tools within their declared ranges.
upgrade: update switch
    mise up

# Install whatever ~/.config/mise/config.toml declares but has not materialized.
#
# NOT how a tool added to home/mise.nix reaches this machine: that file is only
# the seed for config.toml, which mise owns once it exists (ADR-0009). Add it
# here with `mise use -g <tool>@<version>` — which installs it too — and this
# recipe stays what it says, a catch-up for anything declared-but-missing.
runtimes:
    mise install

# Home Manager release notes for the pending configuration.
news:
    home-manager news --flake '.#{{ host }}' {{ impure }}

# Packages the current generation put on PATH. `just packages ripgrep` to filter.
packages *PATTERN:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z '{{ PATTERN }}' ]; then exec home-manager packages; fi
    home-manager packages | grep -i -- '{{ PATTERN }}' \
      || { echo "nothing matching '{{ PATTERN }}' in the current generation" >&2; exit 1; }

# List generations, newest first.
generations:
    home-manager generations

# Step back exactly one generation. No rebuild, no flake needed.
rollback:
    home-manager switch --rollback

# Drop generations older than DAYS (the current one is always kept).
expire DAYS='30':
    home-manager expire-generations '-{{ DAYS }} days'

# Reclaim store space from expired generations.
gc:
    nix-collect-garbage -d

# Open a repl with this flake's attributes in scope (homeConfigurations, …).
repl:
    nix repl {{ impure }} .

# Preview the full bootstrap — prints every step, runs nothing.
plan:
    ./bootstrap.sh --dry-run --verbose

# Run the bootstrap. Needed only when the imperative half (platform/) changed.
bootstrap *ARGS:
    ./bootstrap.sh {{ ARGS }}
