# ADR-0013: chezmoi owns the dotfiles, zoi fronts the packages, mise the runtimes; Python stays as `uv run` scripts

| Field | Value |
| --- | --- |
| Status | accepted |
| Date | 2026-09-09 |
| Supersedes | ADR-0007 (Nix + Home Manager), ADR-0009 (ownership tiers — the *rule* survives, the mechanism changes) |
| Keeps | ADR-0010 (plan-first clearance), ADR-0011 + ADR-0012 (agent toolchain) |

## Context

RFC-0006 records why the Nix + Home Manager generation was retired: the bootstrap
cost of Nix itself, the machinery ADR-0009 needed to escape the read-only store,
and a `prod/*` branch per environment carrying one file. The owner chose the
replacement stack: chezmoi, zoi, uv, mise, with Python kept as `uv run` scripts.

## Decision

> In the context of a cross-platform dotfiles repo that must bootstrap on macOS
> and on throwaway Linux containers whose `$HOME` does not survive, facing the
> Nix install and store-symlink costs recorded in RFC-0006, we decided for
> **chezmoi as the file manager, zoi as the package front door, mise for
> runtimes, and PEP 723 Python scripts run by uv for everything imperative**, and
> against slimming Home Manager or an all-shell chezmoi tree, to achieve a
> root-optional bootstrap with one branch for every machine, accepting that zoi
> today installs almost nothing itself and is backed by a native-manager fallback.

### Layout

| Path | Role |
| --- | --- |
| `.chezmoiroot` → `home/` | the chezmoi source state; `chezmoi init` pins `sourceDir` to the clone |
| `home/.chezmoi.toml.tmpl` | the per-machine questions: `env`, `stateRoot`, `network`, `agents`, `system` (env vars `DOTFILE_*` win) |
| `home/.chezmoidata/*.toml` | the reviewed inventories: `packages.toml`, `mise.toml`, `envlinks.toml` — read by chezmoi templates AND by the scripts (tomllib) |
| `home/.chezmoiscripts/` | `run_before_` env links; `run_onchange_after_` packages, fonts, mise install, setup — each keyed on the hash of its inputs |
| `home/.chezmoiexternal.toml` | the four zsh plugins, fetched as archives |
| `scripts/*.py` | `bootstrap.py` (plan → tools → init → backup → apply), `env_links.py`, `packages.py`, `setup.py`, `agents.py`, `components.py`, `managers.py`, `context.py`, `check.py` |
| `bootstrap.sh` | the only shell: ensure `uv`, exec `scripts/bootstrap.py` |

### Ownership rule (ADR-0009, restated for chezmoi)

- **Repo-owned files** (`home/dot_*`): chezmoi writes them on every apply. A file
  a tool rewrites at runtime can NEVER be one of these — the same exclusion
  ADR-0009 drew for store links.
- **Persistent mutable state** (`envlinks.toml`): a `$HOME` symlink onto the
  machine's `stateRoot`, seeded on creation only, repaired when a writer turns
  the link into a file, placed by `scripts/env_links.py` before chezmoi writes
  anything. Not chezmoi source entries, so apply cannot clobber them.
- **Seeded-then-owned** (mise's `config.toml`): an env-link entry whose seed is
  rendered from `mise.toml`; mise owns the file afterwards.

### Packages

`packages.toml` lists each tool with its name per native manager, an optional
zoi registry id and an optional mise fallback. `scripts/packages.py` hands the
missing ones to `zoi install --yes <manager>:<name>`, probes each `bin`, and
falls back per tool to the native manager and then to `mise use -g`. Fonts are a
separate `run_onchange_` script (brew casks on macOS, getnf on Linux).

### Environments

`--env mewtant` and `--env ec2-wo-fsx` replace the two prod branches: the state
root and the extra links (`.jcc.yaml`, `.lark-cli`, `.vscode-server`,
`.zed_server`, `~/.local/bin/jcc`) are gated on `envs = [...]` in
`envlinks.toml`. `main` is the only branch.

## Consequences

- **Bootstrap needs no root** for the user half: uv, zoi, chezmoi and mise all
  install into `~/.local/bin`. Root is only for prerequisites, `chsh` and the
  opt-in system components (unchanged from before).
- **zoi is a front door, measured, not assumed**: with an empty registry and a
  no-op native passthrough (RFC-0006), the native fallback is what installs
  today. `packages.py` says so in its output; when zoi delivers, nothing changes.
- **Versions are no longer pinned by a lockfile.** Tools come from brew/apt at
  whatever version they ship; mise tools use their declared ranges. That is the
  reproducibility the Nix generation had and this one trades away knowingly.
- **A tool added to `mise.toml` still reaches an existing host only via
  `mise use -g`** — the seeded-then-owned cost ADR-0009 already accepted.
- **Verification** is `just check` (`scripts/check.py`): data validation, script
  compile + `--help`, and a full chezmoi render per environment into a scratch
  `$HOME` with `zsh -n`, `git config --list` and TOML parses on the results —
  plus `./bootstrap.sh --dry-run`.
- **The Nix generation is archived, not deleted**: `archive/homemanager/main`,
  `archive/homemanager/prod/mewtant`, `archive/homemanager/prod/ec2-wo-fsx`.
  ADRs 0007–0009 remain as history and are not current design.
