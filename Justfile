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
