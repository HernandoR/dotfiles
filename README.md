# lz's dotfiles

Cross-platform dotfiles built on **[chezmoi](https://www.chezmoi.io/)** (the
files), **[mise](https://mise.jdx.dev/)** (runtimes and most of the CLI toolset,
from prebuilt release binaries), **[nvm](https://github.com/nvm-sh/nvm)** (the
Node ecosystem) and a handful of **`uv run` Python scripts** (everything
imperative, including the few OS-level packages via brew / apt / dnf / yum). Targets macOS (aarch64) and Debian/Ubuntu
(x86_64 + aarch64); other Linux families get the user half. The zsh + Starship
(catppuccin_mocha) + fzf-tab experience is unchanged.

Design is recorded in [ADR-0013](docs/plans/adr-0013-chezmoi-mise-nvm-uv-2026-09-09.md)
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
half (uv, chezmoi, mise all land in `~/.local/bin`); root/sudo is used only
for missing prerequisites, `chsh`, and the opt-in system components.

On a truly bare machine, chezmoi's own entry point also works:

```bash
BINDIR="$HOME/.local/bin" sh -c "$(curl -fsLS https://get.chezmoi.io)" -- init --apply HernandoR
```

It has no pre-apply plan—the bootstrap tools are supplied by a `run_before`
script inside that apply—so prefer `bootstrap.sh` wherever existing files need
review. Afterwards use `chezmoi apply --dry-run` to preview changes. Both paths
copy existing managed files aside once before their first successful apply.

**It prints the whole plan first, then runs it — unattended.** The plan lists
what will be installed, which files are written or linked, and every existing
file it will copy aside
([ADR-0010](docs/plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md)).
Nothing prompts: this is normally run in CI, a container build, a devpod
recreation or an agent's shell, where a question hangs the run. Preview with
`--dry-run`; pass `--interactive` to get the one-shot clearance prompt and the
`chezmoi init` questions back. Your data is protected by the copy-aside backup,
not by the prompt.

## What the bootstrap does

The whole run is one Python process (`scripts/bootstrap.py`; the root
`bootstrap.sh` only guarantees `uv` and execs it):

1. **Tools:** detect privilege → install prerequisites (curl, git) → on macOS
   install **Homebrew** (the OS packages and fonts need it) → install
   **chezmoi** and **mise** with their own installers (download-then-run, never
   `curl | sh`) into `~/.local/bin`. **uv** was already installed the same way
   by `bootstrap.sh`, since it provides the Python this runs on. These three
   are the only tools mise does not manage; `just update` upgrades them in place.
2. **`chezmoi init`:** record this machine's answers — `env`, `stateRoot`,
   `network`, `agents`, `system` — in `~/.config/chezmoi/chezmoi.toml`
   (from `home/.chezmoi.toml.tmpl`; flags/`DOTFILE_*` env vars answer them
   unattended). The clone itself becomes the chezmoi source directory.
3. **Backup:** every existing `$HOME` path that apply would change is copied
   (never moved or deleted) to `~/dotfiles_backup/<stamp>/`.
4. **`chezmoi apply`**, which runs, in order:
   - `run_before` — **bootstrap tools**, then **env links**
     (`scripts/env_links.py`): seed, repair and
     place the persistent `$HOME` symlinks (`~/.claude`, `~/.ssh`, `~/.exports`, …);
   - the **files** from `home/` and the four **zsh plugins** (chezmoi externals);
   - `run_onchange_after` — **mise tools** (`scripts/runtimes.py`: declare
     what the live config lacks, `mise install`), **Node via nvm**
     (`scripts/node.py`), **OS packages** (`scripts/packages.py`: brew / apt /
     dnf / yum), **fonts**, and **setup** (`scripts/setup.py`: login shell,
     agent toolchain, system components) — each only when its inputs changed;
   - `run_after` promotes the first-apply backup transaction to complete only
     after all prior actions succeed.

When it finishes, start the new shell with `exec zsh -l` (or re-login).

## Flags & environment variables

| Flag | Effect |
| --- | --- |
| `--dry-run` | Print every command without executing it. |
| `--verbose` | Echo each command as it runs. |
| `--interactive` / `-i` | Ask before running the plan, and let `chezmoi init` ask its questions. Off by default. Same as `DOTFILE_INTERACTIVE=1`. |
| `--yes` / `-y` | Accepted for compatibility; already the default. |
| `--env NAME` | Environment: `default`, `mewtant`, `ec2-wo-fsx` — picks the state root and the env-only links. |
| `--state-root DIR` | Override the persistent root for the `$HOME` links. |
| `--network CN` | China mirrors for pypi/uv, rustup and Homebrew's installer. |
| `--agents <list>` | Which coding agents to provision: `claude,codex,pi` / `all` (default) / `none`. |
| `--system <list>` | Opt-in Linux system components (`all` = every one; `none` = skip). |

Every flag has an env-var twin the chezmoi config template reads directly:
`DOTFILE_ENV`, `DOTFILE_STATE_ROOT`, `DOTFILE_NETWORK_ENV`, `DOTFILE_AGENTS`,
`DOTFILE_SYSTEM_COMPONENTS`, plus `DOTFILE_INTERACTIVE=1` for the prompts.

**Nothing in this repo prompts unless you ask it to.** `just apply`, every
`run_` script chezmoi executes, and each script run by hand are unattended by
construction; `just init` is the one recipe that asks, because re-answering the
machine questions is its whole purpose. Two things can still stop and wait, both
by design and neither during a bootstrap: `dotfiles-postsetup` (OAuth logins
that genuinely need a human) and `./brew-cask-interactive-install.sh` (a manual
picker). `sudo` may still ask for your password on a host that requires it.

## Trying it on a new machine (and how to recover)

**Safety model — nothing is destroyed:**

- **Preview first:** `./bootstrap.sh --dry-run --verbose` runs nothing and shows
  chezmoi's own diff of what apply would change. This is the check that replaces
  the old confirmation prompt — use it before the first real run on a machine.
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

## Migrating a machine off Nix + Home Manager

Run `./bootstrap.sh`. It installs the new generation alongside the old one and
`chezmoi apply` replaces the files Home Manager owned, so the machine works
before anything is removed. Note that a tool the bootstrap finds under `/nix` is
treated as **not** installed and a real copy goes into `~/.local/bin`, because
Nix's copy disappears with Nix.

What is left afterwards is Home Manager's `$HOME` symlinks into `/nix/store`,
its profiles under `~/.local/state`, and the Nix store and daemon. Removing them
is a one-time manual job and deliberately not automated here: the safe part is
just deleting symlinks that point into `/nix` (never a real file, and never
inside `~/dotfile_home` or `~/dotfiles_backup/`), and the rest depends on which
installer put Nix there. A store from the Determinate or Lix installer removes
itself with `sudo /nix/nix-installer uninstall`; one from the classic
nixos.org script needs the manual procedure in the
[NixOS manual](https://nix.dev/manual/nix/stable/installation/uninstall), which
ends in deleting the APFS store volume and a reboot.

## Staying in sync

```bash
just diff       # what would change
just apply      # apply the source tree (files, then the run_ scripts when their inputs changed)
just status     # one line per managed path that differs
just runtimes   # mise: add newly declared tools, install what is missing
just node       # nvm: Node, pnpm, global npm packages
just update     # git pull, apply, upgrade uv/chezmoi/mise in place, mise up
just check      # verify the repo (data, scripts, a full render per environment)
just doctor     # chezmoi / mise health
```

Machine answers can be changed with `just init` (it asks, offering the stored
answers as defaults) or by re-running the bootstrap with the flag.

## Layers and ownership

| What | Where | Who writes it at runtime |
| --- | --- | --- |
| Repo-owned files (zsh, starship, git, tmux, mise settings, worktrunk, direnv) | `home/dot_*` → `$HOME` on every apply | chezmoi only — edit the source, never the target |
| Persistent mutable state (agent dirs, `~/.ssh`, history, `~/.exports`, …) | `home/.chezmoidata/envlinks.toml` → symlink onto the machine's state root | the tool that owns it; seeded once, repaired if a writer replaces the link |
| Tools and runtimes (most of the toolset) | `home/.chezmoidata/mise.toml` → `~/.config/mise/config.toml` (seeded, then reconciled: missing tools added, existing versions kept) | mise (`mise use -g`, `mise up`) and `scripts/runtimes.py` |
| Node ecosystem | `home/.chezmoidata/node.toml` → `~/.nvm` | nvm and `scripts/node.py` |
| OS-level packages (zsh, GNU userland, git, vim, wget, rsync, tree, xclip) | `home/.chezmoidata/packages.toml` | `scripts/packages.py` (brew / apt / dnf / yum) |
| Rime/Squirrel input method | `home/.chezmoidata/rime.toml` + `rime/` → persistent `~/Library/Rime` | `scripts/rime.py` (Wanxiang assets and grammar model) |
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

The rule, in order: **mise if mise can fetch it** (`mise registry | grep <name>`;
aqua/ubi release binaries, the cargo backend through cargo-binstall, vfox
plugins, conda-forge through mise's own solver — no conda binary is installed); **nvm for anything Node**;
**the OS package manager only for what links against the system** or replaces
something the OS ships.

### A CLI tool → `home/.chezmoidata/mise.toml`

```toml
[mise.tools]
bat = "latest"            # aqua:sharkdp/bat — resolved from the mise registry
"cargo:some-tool" = "latest"   # crates.io: fetched prebuilt via cargo-binstall, built only as a last resort
```

`just apply` (or `just runtimes`) runs `scripts/runtimes.py`: a tool the live
`~/.config/mise/config.toml` lacks is added with `mise use -g`, tools it already
has keep their versions, then `mise install`. So an addition here reaches every
host on its next apply, and your own `mise use -g <tool>@<version>` on a host
still wins for that tool. Prefer `mise use -g` on a machine only for something
that should *not* be in the repo.

### A Node package → `home/.chezmoidata/node.toml`

```toml
[node]
version = "lts/*"
globals = ["pnpm", "@larksuite/cli", "@smithery/cli", "typescript"]
```

`scripts/node.py` installs nvm (pinned installer, edits no rc file), the Node
line, and `npm install -g` for the globals. Interactive zsh sources `nvm.sh`;
everything else gets the newest installed Node on PATH from `env.zsh`.

### An OS-level package → `home/.chezmoidata/packages.toml`

```toml
[[packages]]
name = "htop"
brew = "htop"
apt = "htop"
dnf = "htop"      # yum uses the dnf names
```

Only for tools mise has no backend for, or that must be the system's build.
Say `""` for a manager that has no package. `scripts/packages.py` detects the
host's manager (brew on macOS; apt, dnf or yum on Linux; brew as a last resort)
and installs what is missing.

### Rime on macOS

The macOS Squirrel cask is declared in `packages.toml`; its input-method bundle
is installed at `/Library/Input Methods/Squirrel.app`. `rime.py` then seeds the
persistent `~/Library/Rime` link with the pinned Wanxiang Base scheme and
`wanxiang-lts-zh-hans.gram` model, and applies the custom YAML files under
`rime/`. The defaults use half-width punctuation and CapsLock for Chinese/
English switching. After the first apply, choose **Deploy** from Squirrel's menu (or
restart Squirrel) to build the schema.

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
  templates read them as `.mise` / `.node` / `.packages` / `.envlinks`, the
  scripts with `tomllib`. A script never hardcodes a list.
- **Scripts:** PEP 723 (`uv run --script`), stdlib only, Python ≥ 3.11; commands
  via `ctx.run_command` (sudo only when needed, honours dry-run); argument lists
  over `shell=True`; download-then-execute, never `curl | bash`; every step
  registers itself in the plan next to the code that performs it (ADR-0010).
- **Behave in a pipe.** Every script restores the default `SIGPIPE` disposition
  (`context.py`, `quiet_broken_pipe`), so `… | head` stops it instead of ending
  in a `BrokenPipeError` traceback. A script that does not import `context`
  carries the same three lines inline.
- **Never block on a prompt.** A new step must run to completion unattended:
  pass the installer's non-interactive flag, and `stdin_devnull=True` to
  `ctx.run_command` for anything driven off a list, so an unexpected question
  fails loudly instead of hanging the run. What truly needs a human goes into
  the deferred post-login script, not into the apply path.
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
- **mise's `config.toml`** is reconciled add-only: `runtimes.py` adds missing
  tools and never changes a version a host already has. Do not make it a chezmoi
  source entry, and do not "fix" the reconcile into an overwrite.
- **Node stays with nvm.** No `node`/`npm:` tools in `mise.toml`; the two must
  not race for `npm` on PATH.
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
bootstrap.sh      source scripts/uv-bootstrap.sh, exec scripts/bootstrap.py
Justfile          `just` recipes for the day-to-day commands
home/
  .chezmoi.toml.tmpl      the per-machine questions (env, stateRoot, network, agents, system)
  .chezmoidata/           mise.toml, node.toml, packages.toml, envlinks.toml, rime.toml — inventories
  .chezmoiscripts/        run_before tools/env links; run_onchange mise, node, packages, fonts, setup; final run_after stamp
  .chezmoiexternal.toml   the zsh plugins
  dot_zshenv/.zprofile/.zshrc.tmpl, private_dot_config/{zsh,git,starship.toml,mise/conf.d,worktrunk,direnv}/,
  dot_tmux.conf, dot_local/bin/
scripts/
  bootstrap.py    plan + clearance, chezmoi init/backup/apply
  tools.py        shared prereqs, brew (macOS), chezmoi/mise, first-apply backup transaction
  uv-bootstrap.sh the only shell helper: uv + brew PATH
  env_links.py    the persistent $HOME links      runtimes.py   mise: reconcile + install
  node.py         nvm: Node, pnpm, npm globals    packages.py   OS packages (brew/apt/dnf/yum)
  setup.py        login shell, runtimes, agents, system components
  agents.py       the ADR-0011 manifest           components.py / managers.py / context.py
  check.py        `just check`
  docker-rootless-pod/, export-mnemopi-banks.py, brew_cask_install.py   standalone helpers
docs/plans/       ADRs (0013 governs)      docs/rfc/   RFCs (0006 = this migration)
```

## Notes

- **Runtimes:** rust/go and the CLI toolset via mise, Node via nvm, Python via uv (no system Python is needed).
- Run the bootstrap from inside the cloned repo; the clone is the chezmoi source.
