# dotfiles — the repeatable half of the chezmoi + mise + nvm workflow (ADR-0013).
#
# Every recipe here is a command the README already documents; the Justfile
# exists so it is one name instead of a remembered incantation. `just` itself is
# a mise tool (home/.chezmoidata/mise.toml).

set shell := ["bash", "-euo", "pipefail", "-c"]

repo := justfile_directory()

# List every recipe.
default:
    @just --list --unsorted

# Apply the source tree to $HOME: files, zsh plugins, then the run_ scripts
# (env links before; mise / node / packages / fonts / setup after, each only
# when its inputs changed). A bare apply on a terminal gets setup.py's own clearance.
apply *ARGS:
    chezmoi --source '{{ repo }}' apply {{ ARGS }}

# What would change: chezmoi's diff of every managed file against $HOME.
diff:
    chezmoi --source '{{ repo }}' diff

# One line per managed path that differs from the source.
status:
    chezmoi --source '{{ repo }}' status

# Every path chezmoi manages, plus the env links the scripts own.
managed:
    @chezmoi --source '{{ repo }}' managed
    @echo "--- env links (scripts/env_links.py):"
    @uv run --script scripts/env_links.py --plan | cut -f2 || true

# Re-answer the machine questions (env, state root, network, agents, system).
# Stored answers are the defaults; DOTFILE_* env vars override without asking.
init:
    chezmoi --source '{{ repo }}' init

# Health of the tools and of the source tree.
doctor:
    chezmoi --source '{{ repo }}' doctor || true
    mise doctor || true

# The repo's verification: data files, scripts, a full render per environment.
check:
    uv run --script scripts/check.py

# Seed / repair / place the mutable $HOME links (normally run by apply).
env-links *ARGS:
    uv run --script scripts/env_links.py {{ ARGS }}

# The OS-level remainder from packages.toml (brew / apt / dnf / yum) — normally
# run by apply when the list changes.
packages *ARGS:
    uv run --script scripts/packages.py {{ ARGS }}

# mise: declare every tool from .chezmoidata/mise.toml the live config lacks
# (your own `mise use -g` versions are kept), then `mise install`.
runtimes *ARGS:
    uv run --script scripts/runtimes.py {{ ARGS }}

# Node via nvm: nvm, the Node from .chezmoidata/node.toml, pnpm, global npm packages.
node *ARGS:
    uv run --script scripts/node.py {{ ARGS }}

# Login shell, mise runtimes, agent toolchain, system components (scripts/setup.py).
setup *ARGS:
    uv run --script scripts/setup.py {{ ARGS }}

# What the agents have, and who gets what (the ADR-0011 manifest).
agents:
    uv run --script scripts/agents.py

# Pull the repo, re-apply, upgrade the three self-installed tools, move mise
# tools within their ranges.
update:
    git -C '{{ repo }}' pull --ff-only
    just apply
    uv self update || true
    chezmoi upgrade || true
    mise self-update -y || true
    mise up -y

# Preview the full bootstrap — prints the plan and every step, runs nothing.
plan:
    ./bootstrap.sh --dry-run --verbose

# Run the bootstrap (tools + init + apply). Idempotent; re-run after big changes.
bootstrap *ARGS:
    ./bootstrap.sh {{ ARGS }}

# Edit a managed file in the source tree (chezmoi resolves the source path).
edit TARGET:
    chezmoi --source '{{ repo }}' edit '{{ TARGET }}'
