# ADR-0013: chezmoi owns the dotfiles, mise the tools, nvm the Node ecosystem; Python stays as `uv run` scripts

| Field | Value |
| --- | --- |
| Status | accepted (updated 2026-09-10: zoi removed, mise-first, nvm for Node) |
| Date | 2026-09-09 |
| Supersedes | ADR-0007 (Nix + Home Manager), ADR-0009 (ownership tiers — the *rule* survives, the mechanism changes) |
| Keeps | ADR-0010 (plan-first — the clearance becomes opt-in, see below), ADR-0011 + ADR-0012 (agent toolchain) |

## Context

RFC-0006 records why the Nix + Home Manager generation was retired: the bootstrap
cost of Nix itself, the machinery ADR-0009 needed to escape the read-only store,
and a `prod/*` branch per environment carrying one file. The owner chose the
replacement stack: chezmoi, zoi, uv, mise, with Python kept as `uv run` scripts.
On 2026-09-10, after measuring zoi (nine registry packages, a no-op native
passthrough), the owner dropped zoi and set the ownership rule recorded below.

## Decision

> In the context of a cross-platform dotfiles repo that must bootstrap on macOS
> and on throwaway Linux containers whose `$HOME` does not survive, facing the
> Nix install and store-symlink costs recorded in RFC-0006, we decided for
> **chezmoi as the file manager, mise for every tool it has a backend for, nvm
> for the Node ecosystem, a Python forwarder over brew / apt / dnf / yum for the
> OS-level remainder, and PEP 723 Python scripts run by uv for everything
> imperative**, and against slimming Home Manager, an all-shell chezmoi tree, or
> zoi as a universal front door, to achieve a root-optional bootstrap with one
> branch for every machine, accepting that OS packages arrive unpinned.

### Layout

| Path | Role |
| --- | --- |
| `.chezmoiroot` → `home/` | the chezmoi source state; `chezmoi init` pins `sourceDir` to the clone |
| `home/.chezmoi.toml.tmpl` | the per-machine questions: `env`, `stateRoot`, `network`, `agents`, `system` (env vars `DOTFILE_*` win) |
| `home/.chezmoidata/*.toml` | the reviewed inventories: `mise.toml`, `node.toml`, `packages.toml`, `envlinks.toml`, `rime.toml` — read by chezmoi templates AND by the scripts (tomllib) |
| `home/.chezmoiscripts/` | `run_before_05` the bootstrap tools (idempotent), `run_before_10` env links; `run_onchange_after_` mise, node, packages, fonts, setup — each keyed on the hash of its inputs; a final `run_after` promotes the first-apply transaction only on success |
| `home/.chezmoiexternal.toml` | the four zsh plugins, fetched as archives |
| `scripts/*.py` | `bootstrap.py` (plan → tools → init → backup → apply), `tools.py` (the shared toolchain phase), `env_links.py`, `runtimes.py`, `node.py`, `packages.py`, `setup.py`, `agents.py`, `components.py`, `managers.py`, `context.py`, `check.py` |
| `bootstrap.sh` | the standalone entry point: source `scripts/uv-bootstrap.sh`, exec `scripts/bootstrap.py` |
| `scripts/uv-bootstrap.sh` | the one reusable shell prelude: ensure `uv`, normalize a freshly installed Homebrew onto `PATH`, and report whether the declared tools resolve — sourced by `bootstrap.sh` and by the chezmoi wrappers |

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

### Packages (updated 2026-09-10)

Whatever mise can fetch, mise manages — `mise.toml` carries the runtimes AND
the CLI toolset (aqua/ubi release binaries, `cargo:` through cargo-binstall
— prebuilt first, a build only when no artifact exists — vfox plugins,
`conda:` through mise's own solver, which installs no conda binary). The Node
ecosystem is nvm's (`node.toml`, `scripts/node.py`), never mise's. What remains
for the OS package manager — the shell, GNU userland, git, vim, wget/rsync/tree,
xclip — is `packages.toml`, installed by `scripts/packages.py`, which detects
brew / apt / dnf / yum. `scripts/runtimes.py` reconciles the live mise config
add-only: tools the repo declares and the host lacks are added, versions the
host already has are kept. Fonts are a separate `run_onchange_` script.

**Self-installed tools.** uv, chezmoi and mise bootstrap the bootstrap, so they
come from their own installers into `~/.local/bin` (uv from
`scripts/uv-bootstrap.sh`, since it runs the Python) and are upgraded in place
by `just update`. Homebrew on macOS is installed before apply — `packages.toml`
and the fonts need it, and no tool manager can install it.

Since 2026-09-10 (RFC-0007) this phase lives in `scripts/tools.py`, is
idempotent, and is reached from chezmoi's own `run_before` script phase, so the
repo has **two entry points**:

- **`./bootstrap.sh`** — the plan printed, existing `$HOME` files copied aside,
  clearance on request. The recommendation wherever a machine has files to
  displace.
- **chezmoi's documented one-liner** —
  `BINDIR="$HOME/.local/bin" sh -c "$(curl -fsLS https://get.chezmoi.io)" -- init --apply <user>`.
  It has no plan print by construction (its `run_before` script *is* part of the
  apply a plan would have to precede, ADR-0010), so it previews with
  `chezmoi apply --dry-run` instead, and it takes the same once-per-machine
  copy-aside backup. A pending marker made before apply is promoted to its done
  marker only by a final successful apply action, so a failed first apply is
  retried rather than recorded as complete.

### Environments

`--env mewtant` and `--env ec2-wo-fsx` replace the two prod branches: the state
root and the extra links (`.jcc.yaml`, `.lark-cli`, `.vscode-server`,
`.zed_server`, `~/.local/bin/jcc`) are gated on `envs = [...]` in
`envlinks.toml`. `main` is the only branch.

### Interactivity (2026-09-10)

**Everything runs unattended by default.** ADR-0010's *plan* survives unchanged
— every step still registers what it would do, and the whole plan is printed
before anything runs — but its *clearance prompt* becomes opt-in
(`--interactive`, `DOTFILE_INTERACTIVE=1`), and so do the `chezmoi init`
questions, which the config template gates on the same variable. `chezmoi` is
invoked with `--no-tty` unless asked.

The reason ADR-0010 gave for a single prompt was that displacing a user's files
is the one irreversible-feeling part of a bootstrap. That protection now comes
from the copy-aside backup (`~/dotfiles_backup/<stamp>/`, taken before apply)
and from `--dry-run`, which prints the plan *and* chezmoi's own diff. What the
prompt actually cost was worse: this repo's common cases are CI, a container
build, a devpod recreation and an agent's shell, where a question does not
protect anybody — it hangs the run. Two interactive surfaces remain, both
outside the apply path and both invoked by hand: `dotfiles-postsetup` (OAuth
logins) and `brew-cask-interactive-install.sh` (a picker).

## Consequences

- **Bootstrap needs no root** for the user half: uv, chezmoi and mise all
  install into `~/.local/bin`. Root is only for prerequisites, `chsh` and the
  opt-in system components (unchanged from before).
- **zoi is out** (2026-09-10): it held nine packages and its native passthrough
  was a no-op (RFC-0006); the toolset moved to mise and the OS remainder to a
  Python forwarder over brew / apt / dnf / yum. Nothing in the repo depends on it.
- **Versions**: mise tools are pinned per host in `config.toml` (`latest` at
  first install, then whatever `mise up` moves them to); OS packages come at
  whatever the manager ships. Less than a Nix lockfile, more than nothing.
- **A tool added to `mise.toml` reaches existing hosts** through the add-only
  reconcile in `runtimes.py`; versions a host chose are never overwritten.
- **Node is nvm's**: no `node`/`npm:` mise tools, so the two never race for
  `npm`; non-interactive callers get the newest installed Node from `env.zsh`.
- **Nothing prompts in the apply path.** A step that cannot run unattended does
  not belong there; `stdin_devnull=True` makes an unexpected question fail
  loudly rather than block.
- **Verification** is `just check` (`scripts/check.py`): data validation, script
  compile + `--help`, and a full chezmoi render per environment into a scratch
  `$HOME` with `zsh -n`, `git config --list` and TOML parses on the results —
  plus `./bootstrap.sh --dry-run`.
- **The Nix generation is archived, not deleted**: `archive/homemanager/main`,
  `archive/homemanager/prod/mewtant`, `archive/homemanager/prod/ec2-wo-fsx`.
  ADRs 0007–0009 remain as history and are not current design.
