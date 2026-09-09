# lz's dotfiles

Cross-platform dotfiles built on **[chezmoi](https://www.chezmoi.io/)** (the
files), **[zoi](https://github.com/Zillowe/Zoi)** (the package front door),
**[mise](https://mise.jdx.dev/)** (runtimes) and a handful of **`uv run` Python
scripts** (everything imperative). Targets macOS (aarch64) and Debian/Ubuntu
(x86_64 + aarch64); other Linux families get the user half. The zsh + Starship
(catppuccin_mocha) + fzf-tab experience is unchanged.

Design is recorded in [ADR-0013](docs/plans/adr-0013-chezmoi-zoi-mise-uv-2026-09-09.md)
(intent) and [RFC-0006](docs/rfc/rfc-0006-chezmoi-zoi-mise-uv-2026-09-09.md)
(why the Nix + Home Manager generation was retired); [AGENTS.md](AGENTS.md) holds
the short must-follow rules for coding agents. The previous generation lives on
the `archive/homemanager/*` branches.

> **Warning:** These are my personal settings. Fork the repo and review the code
> before running it. The bootstrap installs tools, changes your login shell and
> overwrites dotfiles (after copying the existing ones aside). Read
> **[Trying it on a new machine](#trying-it-on-a-new-machine-and-how-to-recover)**
> first.

## Quick start

```bash
git clone git@github.com:HernandoR/dotfiles.git
cd dotfiles
./bootstrap.sh --dry-run --verbose   # preview every step, run nothing (recommended first)
./bootstrap.sh                       # then run for real
```

`bootstrap.sh` needs `curl` and `git`. No privilege is required for the user
half (uv, zoi, chezmoi, mise all land in `~/.local/bin`); root/sudo is used only
for missing prerequisites, `chsh`, and the opt-in system components.

**On a terminal it asks before it touches anything.** It prints the whole plan
first — what will be installed, which files are written or linked, every
existing file it will copy aside — then asks for clearance **once**
([ADR-0010](docs/plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md)).
A run with no terminal (CI, container build) never asks; `--yes` skips the
prompt on a terminal too.

## What the bootstrap does

The whole run is one Python process (`scripts/bootstrap.py`; the root
`bootstrap.sh` only guarantees `uv` and execs it):

1. **Tools:** detect privilege → install prerequisites (curl, git) → install
   **zoi**, **chezmoi**, **mise** with their own installers (download-then-run,
   never `curl | sh`), all into `~/.local/bin`.
2. **`chezmoi init`:** record this machine's answers — `env`, `stateRoot`,
   `network`, `agents`, `system` — in `~/.config/chezmoi/chezmoi.toml`
   (from `home/.chezmoi.toml.tmpl`; flags/`DOTFILE_*` env vars answer them
   unattended). The clone itself becomes the chezmoi source directory.
3. **Backup:** every existing `$HOME` path that apply would change is copied
   (never moved or deleted) to `~/dotfiles_backup/<stamp>/`.
4. **`chezmoi apply`**, which runs, in order:
   - `run_before` — **env links** (`scripts/env_links.py`): seed, repair and
     place the persistent `$HOME` symlinks (`~/.claude`, `~/.ssh`, `~/.exports`, …);
   - the **files** from `home/` and the four **zsh plugins** (chezmoi externals);
   - `run_onchange_after` — **packages** (`scripts/packages.py`, via zoi),
     **fonts**, **mise runtimes** (`mise install`), and **setup**
     (`scripts/setup.py`: login shell, agent toolchain, system components) —
     each only when its inputs changed.

When it finishes, start the new shell with `exec zsh -l` (or re-login).

## Flags & environment variables

| Flag | Effect |
| --- | --- |
| `--dry-run` | Print every command without executing it (no clearance prompt). |
| `--verbose` | Echo each command as it runs. |
| `--yes` / `-y` | Skip the clearance prompt (the plan is still printed). Same as `DF_ASSUME_YES=1`. |
| `--env NAME` | Environment: `default`, `mewtant`, `ec2-wo-fsx` — picks the state root and the env-only links. |
| `--state-root DIR` | Override the persistent root for the `$HOME` links. |
| `--network CN` | China mirrors for pypi/uv, rustup and Homebrew's installer. |
| `--agents <list>` | Which coding agents to provision: `claude,codex,pi` / `all` (default) / `none`. |
| `--system <list>` | Opt-in Linux system components (`all` = every one; `none` = skip). |

Every flag has an env-var twin the chezmoi config template reads directly:
`DOTFILE_ENV`, `DOTFILE_STATE_ROOT`, `DOTFILE_NETWORK_ENV`, `DOTFILE_AGENTS`,
`DOTFILE_SYSTEM_COMPONENTS`. `DF_ASSUME_YES=1` is exported once you clear the
plan, so nothing nested asks again.

## Trying it on a new machine (and how to recover)

**Safety model — nothing is destroyed:**

- **Preview first:** `./bootstrap.sh --dry-run --verbose` runs nothing and shows
  chezmoi's own diff of what apply would change.
- **Existing files are copied, not deleted.** Before `chezmoi apply`, every path
  it would change is copied under its `$HOME`-relative name to
  `~/dotfiles_backup/<stamp>/`. A real file or directory in the way of an env
  link is renamed to `<name>.backup` by `env_links.py`.
- **The old generation stays intact** on `archive/homemanager/*`; the pre-Nix
  one on `archive/pre-nix`.

**Roll back:**

```bash
just diff                                   # what differs between the repo and $HOME
cp -aP ~/dotfiles_backup/<stamp>/.zshrc ~/  # restore any backed-up file
chezmoi forget ~/.zshrc                     # stop managing one path (source stays in git)
chezmoi purge                               # remove chezmoi's config + state (files stay)
```

## Staying in sync

```bash
just diff       # what would change
just apply      # apply the source tree (files, then the run_ scripts when their inputs changed)
just status     # one line per managed path that differs
just update     # git pull, apply, zoi update --all, mise up
just check      # verify the repo (data, scripts, a full render per environment)
just doctor     # chezmoi / zoi / mise health
```

Machine answers can be changed with `just init` (stored answers are the
defaults) or by re-running the bootstrap with the flag.

## Layers and ownership

| What | Where | Who writes it at runtime |
| --- | --- | --- |
| Repo-owned files (zsh, starship, git, tmux, mise settings, worktrunk, direnv) | `home/dot_*` → `$HOME` on every apply | chezmoi only — edit the source, never the target |
| Persistent mutable state (agent dirs, `~/.ssh`, history, `~/.exports`, …) | `home/.chezmoidata/envlinks.toml` → symlink onto the machine's state root | the tool that owns it; seeded once, repaired if a writer replaces the link |
| Seeded-then-owned (mise's global tool list) | an env-link entry with `seed_from = "mise"` | mise (`mise use -g`) |
| Packages | `home/.chezmoidata/packages.toml` | `scripts/packages.py` (zoi → native → mise) |
| Agent capabilities | `scripts/agents.py` manifest | the agents' own CLIs, projected by `setup.py` |

The rule from ADR-0009 survives: **a file a tool rewrites at runtime is never a
chezmoi source entry.** It is an env-link entry.

### Environments

`--env mewtant` and `--env ec2-wo-fsx` replaced the old `prod/*` branches. They
change the state root (`/fsx/hernando/dotfile_home_link_src`,
`/home/ec2-user/dotfile_home`) and enable the entries gated with
`envs = [...]` in `envlinks.toml` (`.jcc.yaml`, `.lark-cli`, `.vscode-server`,
`.zed_server`, `~/.local/bin/jcc`). `main` is the only branch.

### Machine-local escape hatches

Four files under the state root, linked into `$HOME`, seeded as comment-only
and never touched again by the repo:

| File | Sourced | For |
| --- | --- | --- |
| `~/.path` | every zsh, from `.zshenv` and again from `.zprofile` | PATH additions — they land in front of the repo's dirs |
| `~/.exports` | every zsh, both passes | environment variables — they override the repo's |
| `~/.proxy` | interactive zsh, just before `~/.extra` | proxy on/off |
| `~/.extra` | interactive zsh, last | anything that has to beat an alias, function or PATH entry |

The double sourcing is deliberate: macOS's `/etc/zprofile` reorders PATH between
the two passes, and `typeset -U path` makes a re-prepend move an entry instead
of duplicating it. Portable settings belong in `home/private_dot_config/zsh/env.zsh.tmpl`.

## Adding software (tutorial)

### A CLI tool → `home/.chezmoidata/packages.toml`

```toml
[[packages]]
name = "bat"
brew = "bat"
apt = "bat"
dnf = "bat"
pacman = "bat"
apk = "bat"
zypper = "bat"
mise = "bat"               # fallback where the native manager has no package
alias = { bat = "batcat" } # Debian names the binary differently
```

Say `""` explicitly for a manager that has no package. `just apply` runs
`packages.py` because the file's hash changed; `just packages` runs it now.
**zoi is the front door**: every missing tool goes to `zoi install --yes
<manager>:<name>` first. Its registry held nine packages and its native
passthrough installed nothing in testing (RFC-0006), so the script probes each
binary afterwards and falls back to the native manager, then to `mise use -g`.
Nothing changes here when zoi starts delivering.

### A runtime → `home/.chezmoidata/mise.toml`

```toml
[mise.tools]
deno = "latest"
```

That file is the **seed** of `~/.config/mise/config.toml`; a host that has
already bootstrapped keeps mise's own file, so add it there with
`mise use -g deno@latest` (which installs it too). `just runtimes` installs
whatever the live file declares but has not materialized.

### A persistent `$HOME` path → `home/.chezmoidata/envlinks.toml`

```toml
[envlinks.entries.".some-tool"]
kind = "dir"     # or "file"
mode = "700"     # applied on creation only
# seed = "..."   # file entries: initial content, on creation only
# envs = ["mewtant"]   # only in these environments
```

Say why it is mutable in a comment. `just env-links --plan` shows what would
change; `just apply` runs it before writing any file.

### A dotfile → `home/`

Add `home/private_dot_config/tool/config` (chezmoi's `dot_` = `.`, `executable_`,
`private_`, `.tmpl` for templates — `chezmoi add ~/.config/tool/config` does
the naming). Only for files the tool never rewrites; otherwise see env links.

### A system component / an agent capability

Unchanged from before: subclass `OptionalComponent` in `scripts/components.py`
(verify with `uv run scripts/components.py`); add one entry to the matching
table in `scripts/agents.py` (verify with `just agents`, `just setup --plan`).
Never install one by hand on a machine.

## Coding agents

Three agents — **Claude Code**, **Codex CLI** and **pi** — are provisioned from
one in-repo manifest (`scripts/agents.py`), exactly as
[ADR-0011](docs/plans/adr-0011-multi-agent-toolchain-single-source-2026-08-04.md)
and [ADR-0012](docs/plans/adr-0012-third-slot-upstream-pi-2026-08-28.md)
describe: what the agents *have* is a reviewed table there, what each agent *is*
stays in its own config, which lives on the state root through the env links.
`setup.py` projects the manifest whenever it changes; the two steps that need a
human (Smithery auth, the Lark CLI installer) are written to
`~/.local/share/dotfiles/post-login-setup.sh` — run `dotfiles-postsetup` once.

```bash
just agents                         # what the agents have, and who gets what
./bootstrap.sh --agents claude,codex
```

## China mirrors

One switch: `--network CN` (or `DOTFILE_NETWORK_ENV=CN`, stored by `chezmoi
init`). The zsh env exports the pypi/uv and rustup mirrors; the Homebrew
component uses the BFSU installer mirror. Unset = upstream defaults.

## Contributing — conventions and guardrails

Design changes start as an RFC in `docs/rfc/` and settle into an ADR in
`docs/plans/`; read the governing ADR before reshaping what it governs.
ADR-0013 owns the layout and the ownership rule, 0010 the plan/clearance,
0011 + 0012 the agent toolchain. ADRs 0001–0009 describe retired generations —
don't cite them as current design.

### Conventions

- **Data over code:** inventories live in `home/.chezmoidata/*.toml`; chezmoi
  templates read them as `.packages` / `.mise` / `.envlinks`, the scripts with
  `tomllib`. A script never hardcodes a list.
- **Scripts:** PEP 723 (`uv run --script`), stdlib only, Python ≥ 3.11; commands
  via `ctx.run_command` (sudo only when needed, honours dry-run); argument lists
  over `shell=True`; download-then-execute, never `curl | bash`; every step
  registers itself in the plan next to the code that performs it (ADR-0010).
- **OS identifiers:** one *family* per id (`context.py` `Ctx._detect_os`);
  never hardcode a package manager — route through `NATIVE` in `packages.py`
  or `PackageManager.supported_os` in `managers.py`.
- **chezmoi:** the source tree is `home/` (`.chezmoiroot`). Templates only
  where a value differs per machine or OS; verbatim files otherwise. Scripts
  under `.chezmoiscripts/` are one-liners that delegate to `scripts/`, keyed on
  the hash of their inputs.
- **Markdown:** rules in `.markdownlint-cli2.jsonc`; compact tables.
- **Commits:** Conventional-Commits `type(scope): subject`; history is English.

### Don't touch / be careful with

- **zsh load order** (`home/dot_zshrc.tmpl`): completions → compinit → zoxide →
  fzf-tab → autosuggestions → … → syntax-highlighting LAST → `~/.proxy`,
  `~/.extra`. fzf-tab must bind before anything wraps widgets. Don't "simplify" it.
- **Env-link inventory** (`envlinks.toml`): entries are seeded on creation only.
  Changing `mode`/`seed` changes nothing on an existing target — by design.
- **Agent config files** (`~/.claude/settings.json`, `~/.codex/config.toml`,
  `~/.pi/agent/settings.json`): rewritten by the agents; never make one a
  chezmoi source entry. pi's is seeded leaf-by-leaf under ADR-0012's contract.
- **CN mirror gating:** everything goes through `DOTFILE_NETWORK_ENV`.
- **`~/.claude/CLAUDE.md`** is the thin Claude-only shell importing
  `~/.agents/AGENTS.md`; cross-agent rules go in the latter.

### Verification

There is no test framework. `just check` runs `scripts/check.py`: the data files
parse and validate, every script compiles and answers `--help`, and chezmoi
renders the whole tree per environment into a scratch `$HOME` where `zsh -n`,
`git config --list` and TOML parsing check the results. `./bootstrap.sh
--dry-run --verbose` shows the full plan and chezmoi's diff.

## Repository layout

```text
.chezmoiroot      -> home/ is the chezmoi source state
bootstrap.sh      the only shell: ensure uv, exec scripts/bootstrap.py
Justfile          `just` recipes for the day-to-day commands
home/
  .chezmoi.toml.tmpl      the per-machine questions (env, stateRoot, network, agents, system)
  .chezmoidata/           packages.toml, mise.toml, envlinks.toml — the inventories
  .chezmoiscripts/        run_before env links; run_onchange packages, fonts, mise, setup
  .chezmoiexternal.toml   the zsh plugins
  dot_zshenv/.zprofile/.zshrc.tmpl, private_dot_config/{zsh,git,starship.toml,mise/conf.d,worktrunk,direnv}/,
  dot_tmux.conf, dot_local/bin/
scripts/
  bootstrap.py    plan + clearance, prereqs, zoi/chezmoi/mise, chezmoi init/backup/apply
  env_links.py    the persistent $HOME links      packages.py   the toolset via zoi
  setup.py        login shell, runtimes, agents, system components
  agents.py       the ADR-0011 manifest           components.py / managers.py / context.py
  check.py        `just check`
  docker-rootless-pod/, export-mnemopi-banks.py, brew_cask_install.py   standalone helpers
docs/plans/       ADRs (0013 governs)      docs/rfc/   RFCs (0006 = this migration)
```

## Notes

- **Runtimes:** node/rust/go via mise, Python via uv (no system Python is needed).
- Run the bootstrap from inside the cloned repo; the clone is the chezmoi source.
