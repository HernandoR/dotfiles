# lz's dotfiles

Cross-platform dotfiles built on a **Nix flake + standalone
[Home Manager](https://nix-community.github.io/home-manager/)** running on
[**Lix**](https://lix.systems/), with a thin **imperative layer**
([`platform/`](platform/)) for the few things Home Manager can't do on a
non-NixOS host. Targets macOS (aarch64) and Debian/Ubuntu (x86_64 + aarch64).
The zsh + Starship (catppuccin_mocha) + fzf-tab experience is preserved.

Design is recorded in [ADR-0007](docs/plans/adr-0007-nix-home-manager-migration-2026-07-09.md)
(intent) and [RFC-0001](docs/rfc/rfc-0001-nix-home-manager-migration-2026-07-09.md)
(discussion trail); [AGENTS.md](AGENTS.md) holds the short must-follow rules for
coding agents — everything else (layout, conventions, guardrails, how to add
anything) is in this file.

> **Warning:** These are my personal settings. Fork the repo and review the code
> before running it — don't blindly apply someone else's configuration. The
> bootstrap can install Nix, change your login shell, and install system
> software. See **[Trying it on a new machine](#trying-it-on-a-new-machine-and-how-to-recover)**
> for the (fully recoverable) safety model first.

## Quick start

```bash
git clone git@github.com:HernandoR/dotfiles.git
cd dotfiles
./bootstrap.sh --dry-run --verbose   # preview every step, run nothing (recommended first)
./bootstrap.sh                       # then run for real
```

`bootstrap.sh` needs `curl` and `git`. No privilege is required if Nix is
already installed; otherwise it needs root/sudo to install Lix (with no
init system — bare container/CI — it falls back to a single-user install).

**On a terminal it asks before it touches anything.** It prints the whole plan
first — what will be installed, from which network/mirrors, which config files
are written, and every symlink it will place — then asks for clearance **once**:

```text
==> Plan — nothing has run yet
  os          ubuntu (x86_64)
  host        dotfiles-debian
  privilege   sudo — privileged steps run via sudo (may ask for your password)
  network     upstream defaults (pass --network CN for the China mirrors)

  will install                 # prerequisites, Lix, the HM generation, mise runtimes …
  will write / link            # system nix.conf, every HM symlink, the login shell
  will move your existing files aside (renamed, never deleted)
    - any $HOME file Home Manager wants to own -> the same name with a .backup suffix

? Proceed with this plan? [Y/n]
```

(Each section really lists every item, one per line, with `[privileged]` on the
steps that use root/sudo.) The last section is separate on purpose: displacing
files you already have is the only part of a bootstrap that touches your data, so
it is listed file-by-file, last, right where you answer.

Answering anything but yes exits without changing a thing. There is exactly one
prompt — no step-by-step nagging. A run with **no terminal** (CI, container
build, cron, `bash -c`) never asks and behaves as it always has; `--yes` skips
the prompt on a terminal too (the plan is still printed). Design record:
[ADR-0010](docs/plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md).

## What the bootstrap does

Split around the Home Manager switch:

The whole run is one Python process (`platform/bootstrap.py`; the root
`bootstrap.sh` only guarantees a `python3` and execs it):

1. **Pre-HM:** detect privilege (root / sudo / none) → install
   prerequisites → **install Lix** → configure Nix (+ optional CERNET mirror) →
   **build & activate Home Manager** with `-b backup` (this is also where the
   out-of-store `$HOME` links from `home/env-links.nix` are placed).
2. **Post-HM (`platform/setup.py`, same process):** set the login shell to the Nix zsh (`chsh`) →
   install the coding agents and project the capability manifest onto each
   ([ADR-0011](docs/plans/adr-0011-multi-agent-toolchain-single-source-2026-08-04.md))
   → write the interactive remainder → install any opt-in Linux system
   components.

When it finishes, the shell that launched it keeps its **old** PATH, so a bare
`zsh` won't be found yet. Start the new environment with the absolute path it
prints, or just re-login (your login shell is already zsh):

```bash
exec ~/.nix-profile/bin/zsh -l
```

## Flags & environment variables

| Flag | Effect |
| ----------------- | ----------------------------------------------------------- |
| `--dry-run` | Print every command without executing it (no clearance prompt — nothing to clear). |
| `--verbose` | Echo each command as it runs. |
| `--yes` / `-y` | Skip the clearance prompt (the plan is still printed). Same as `DF_ASSUME_YES=1`. |
| `--network CN` | Enable China (CERNET) mirrors for Nix, pypi/uv, and rustup. |
| `--system <list>` | Install opt-in Linux system components (`all` = every one). |
| `--host NAME` | Force a named flake host instead of auto-detecting. |
| `--agents <list>` | Which coding agents to provision: `claude,codex,pi` / `all` (default) / `none`. |
| `--no-claude` | Deprecated alias for `--agents none`. |

| Env var | Effect |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DF_ASSUME_YES=1` | Skip the interactive clearance (same as `--yes`); exported automatically once you have cleared the plan, so the nested steps never re-ask. |
| `DOTFILE_NETWORK_ENV=CN` | Same as `--network CN` (also read by the zsh env for pypi/rustup). |
| `DOTFILE_SYSTEM_COMPONENTS` | Fallback for `--system` (e.g. `all`); the flag wins. |
| `DOTFILE_AGENTS` | Fallback for `--agents` (e.g. `claude` or `none`); the flag wins. |
| `DOTFILE_FLAKE_CACHE` | Dir with `seed-paths.txt` to seed flake inputs from (CN/offline/CI). |

## Trying it on a new machine (and how to recover)

**Safety model — nothing is destroyed:**

- **Preview first:** `./bootstrap.sh --dry-run --verbose` runs nothing. An
  ordinary interactive run also prints its full plan and waits for clearance
  before the first change.
- **Existing dotfiles are backed up, not deleted.** Activation uses `-b backup`
  (`HOME_MANAGER_BACKUP_EXT=backup`), so a pre-existing `~/.zshrc` /
  `~/.gitconfig` / etc. is renamed to `~/.zshrc.backup` before the Home Manager
  symlink is placed.
- **The old setup stays intact.** The previous (pre-Nix) config remains on the
  `archive` branch, and previous Home Manager generations are kept until you
  expire them.

**Roll back (after the `home-manager` CLI is on PATH):**

```bash
# 1) step back exactly one generation (no rebuild, no flake needed)
home-manager switch --rollback

# 2) or activate a specific earlier generation
home-manager generations                                   # list them (newest first)
PROFILE=~/.local/state/nix/profiles/home-manager           # or /nix/var/nix/profiles/per-user/$USER/home-manager
nix-env --profile "$PROFILE" --switch-generation <id>
"$PROFILE"/activate

# 3) restore a file that was backed up
mv ~/.zshrc.backup ~/.zshrc                                # repeat for any *.backup

# 4) restore your previous login shell
chsh -s "$(command -v bash)"                               # or your prior shell
```

**Fully uninstall Home Manager:**

```bash
home-manager uninstall        # prompts; removes the HM symlinks + generations
```

`uninstall` removes the symlinks Home Manager created but **does not restore your
`*.backup` files** — move those back manually (`mv ~/.zshrc.backup ~/.zshrc`) and
`chsh` back to your old shell. Reclaim store space with `nix-collect-garbage -d`.
To remove Nix/Lix entirely, follow the Lix uninstall docs.

**Prune old generations** later:

```bash
home-manager expire-generations "-30 days"   # keep the last 30 days (current is always kept)
home-manager remove-generations <id> [<id>…] # remove specific ones
nix-collect-garbage -d                        # then reclaim disk
```

## Staying in sync

`git pull` on its own changes nothing in `$HOME`: every dotfile is a symlink into
`/nix/store`, so the repo is only a build input. One switch applies whatever came
in — from upstream or from your own edit:

```bash
git pull                     # on an env branch (prod/mewtant): rebase onto the shared branch, never merge
just switch                  # == home-manager switch --flake .#<host> -b backup
exec zsh -l                  # pick up the new PATH / env / completions
mise use -g <tool>@<ver>     # only if home/mise.nix gained a tool — see below, a
                             # switch does not push it to a machine you already set up
```

**The `just` recipes.** `Justfile` names the commands in this section, so the
host, `--impure`, and `-b backup` are not yours to remember. `just` on its own
lists them; the ones you will actually use are `build`, `diff`, `switch`,
`reset-hard`, `check`, `update`, `news`, `packages`, `generations`, `rollback`,
`expire`, `gc`, and `plan`. Everything below spells out what a recipe runs —
reach for the raw command when you want a variation, or before the first switch
has put `just` on PATH (it comes from mise).

**Which host?** Your hostname if `flake.nix` defines it, else the OS/arch default
(`platform/bootstrap.py` `detect_named_host`). Any other user — including root — uses the impure
`generic` fallback: `home-manager switch --flake .#generic -b backup --impure`.
`just show-host` prints what resolves for you; `just host=<name> switch` (or
`DF_HOST=<name>`) overrides it.

`-b backup` is what the bootstrap does (`HOME_MANAGER_BACKUP_EXT=backup`);
without it a switch aborts as soon as it finds a real file where a symlink should
go. To see the delta before activating:

```bash
nix build --no-link --print-out-paths .#homeConfigurations."<host>".activationPackage
nix store diff-closures /nix/var/nix/profiles/per-user/"$USER"/home-manager <the printed path>
```

If the result is wrong, `home-manager switch --rollback` — see
[Trying it on a new machine](#trying-it-on-a-new-machine-and-how-to-recover).

**Starting over from the repo** — when `$HOME` has drifted, or a switch keeps
aborting on `.backup` files left by an earlier cycle:

```bash
just reset-hard              # move every managed path aside, then activate
```

It collects every `$HOME` path the generation would own into a single
`~/dotfiles_backup/YYYY_MM_DD_HHMMSS/`, keeping each file's `$HOME`-relative
name, and only then activates. Because nothing is left in the way, Home Manager
renames nothing and the `.backup` collision that aborts a plain `switch`
(ADR-0009) cannot happen.

Everything is **moved, never deleted** — recover any file by copying it back out
of the timestamped directory. It prints the full list and asks once before
touching anything (`DF_ASSUME_YES=1` to skip, which a non-interactive run must
pass explicitly — silence is refusal, not consent). It does not sweep
pre-existing `*.backup` files.

An env-linked path (`~/.claude`, `~/.ssh`, …) is a symlink, so what moves is the
link; the data in `envLinks.stateRoot` is untouched and the activation relinks
it. One guard: if `~/.ssh` is still a **real** directory holding
`authorized_keys` while the persistent target has none, the recipe refuses
rather than severing inbound SSH to the machine.

**Updating versions** (as opposed to applying config):

```bash
nix flake update                     # all inputs; or `nix flake update nixpkgs`
home-manager switch --flake .#<host> -b backup
mise up                              # mise tools, within their declared ranges
```

Commit the changed `flake.lock` together with the change that needed it.

### Re-running the bootstrap

Only needed when the change is in the **imperative half**: `platform/` itself, a
login shell that never got set, or a new `--system` component. Re-runs are
idempotent — Lix is skipped when nix exists
(`platform/bootstrap.py` `install_lix`), `nix.conf` lines are deduplicated before
appending (`_missing_conf_lines`), an unchanged generation is reused rather than created
("No change so reusing latest profile generation"), and `chsh`, `mise install`
and brew all no-op when already done. Four things to know:

- **Pass the same flags as the first run.** Without `--network CN` the run
  *deletes* `~/.config/dotfiles/network-env` (`configure_nix`), silently
  dropping the pypi/uv + rustup mirrors from your shell.
- **A leftover `.backup` aborts activation.** If a file Home Manager newly wants
  to own already exists for real and `<name>.backup` is still there from last
  time, activation fails with _"would be clobbered by backing up"_. Delete the
  stale `.backup`, or re-run with `HOME_MANAGER_BACKUP_OVERWRITE=1`.
- **The post-login script comes back.** `setup.py` rewrites
  `post-login-setup.sh` unconditionally, so `dotfiles-postsetup` is offered again
  even after you ran it; `codegraph upgrade` also runs every time. `--agents none`
  skips both.
- **Removing a manifest entry does not uninstall it.** Agent projection is
  add-only: drop a marketplace, plugin, MCP server or agent extension from
  `platform/installers/agents.py` and the machines that already applied it keep
  it. Uninstall there by hand, once.
- **Disk is what accumulates, not installs.** Each changed `flake.lock` leaves a
  generation behind, and `*.backup` files are never
  removed — prune with `expire-generations` + `nix-collect-garbage` (above).

## Component classification

Components in this repo are split into two broad categories:

- **User components** — declarative, managed by Home Manager in
  `home/packages.nix`.
- **System components** — imperative, installed by `platform/setup.py` via the
  `OptionalComponent` registry in `platform/installers/components.py`.

### User components

The `home/packages.nix` list Home Manager installs on every switch — the core CLI
toolset (`ripgrep`, `jq`, `fd`, `tree`, `wget`, `uv`, …), some of it gated by OS
in the same file (`xclip` on Linux only). Never selected with `--system`: always
applied.

### System components

What Home Manager cannot own on a non-NixOS host, installed after the switch and
selected with `--system <list>` / `DOTFILE_SYSTEM_COMPONENTS`:

| Name | Description | OS |
| --------------------- | ------------------------------------------------------------------------------ | -------------- |
| `software-properties` | `add-apt-repository` support **(required on Linux — always installed)** | debian, ubuntu |
| `docker` | Docker Engine (rootful) | debian, ubuntu |
| `docker-rootless` | Docker (rootless) | debian, ubuntu |
| `cuda` | CUDA Toolkit 12.6 | debian, ubuntu |
| `nvidia` | NVIDIA driver + container toolkit | debian, ubuntu |
| `llvm` | LLVM 18 (+ `update-alternatives`) | debian, ubuntu |
| `brew` | Homebrew — the package manager only (no formulae/casks) **(default on macOS)** | darwin |

The selector takes names, alias groups and `all`; `docker` + `docker-rootless`
together resolve to rootless. Unset means the `default` group — `brew` on macOS,
nothing optional on Linux — and `software-properties` still runs on Debian/Ubuntu
unless you pass `--system none`, which opts out of everything.

```bash
./bootstrap.sh --system docker,llvm   # + the required Linux prerequisites
DOTFILE_SYSTEM_COMPONENTS=cuda,nvidia ./bootstrap.sh
./nix-system-interactive-install.sh   # add components later (--dry-run to preview)
uv run platform/installers/components.py   # list what exists
```

**macOS:** `brew` installs Homebrew _itself_ only (CLI tools come from nixpkgs; on
CN via the BFSU mirror). GUI apps are a separate, manual, never-auto-run picker —
`./brew-cask-interactive-install.sh`, a uv script
([platform/brew_cask_install.py](platform/brew_cask_install.py)) that offers the
recommended casks as a checklist (Edge + Alacritty pre-checked; edit the list in
the file) and a mirror choice defaulting to `DOTFILE_NETWORK_ENV`.

## Adding software (tutorial)

Where a new tool is written down depends on which layer owns it:

| What you want | Write it in | Scope |
| --------------------------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------- |
| A CLI tool that exists in nixpkgs | `home/packages.nix` | every host, on every switch |
| A runtime, or a tool that only ships via npm/cargo/go/gh-release | `home/mise.nix` (the `tools` attrset) | new hosts on bootstrap; existing ones need `mise use -g` |
| Something only one project needs | that project's `mise.toml`, **or** its own `flake.nix` devShell | that directory tree |
| A daemon/driver/apt-level thing (docker, cuda, llvm, …) | `platform/installers/components.py` + `--system` | see [Component classification](#component-classification) |
| A one-off experiment | nothing — `nix shell nixpkgs#<pkg>` | the current shell only |

**Nothing user-level is installed imperatively.** Home Manager installs its
`home-manager-path` into the same profile `~/.nix-profile` points at, so a
`nix profile install` / `nix-env -i` on the side competes with it for the same
file names, never reaches another machine, and does not show up in
`home-manager packages`. If you want the tool tomorrow, it goes into a file in
this repo.

### Nix — find a package

```bash
nix search nixpkgs hyperfine     # regex match over nixpkgs attributes + descriptions
nix search nixpkgs '^ripgrep$'   # anchored: the exact attribute name
```

or [search.nixos.org/packages](https://search.nixos.org/packages) — same data,
with the attribute name and the binaries a package provides.

`nix search nixpkgs` resolves the *registry* nixpkgs (current unstable), while
this repo builds from the revision pinned in `flake.lock`. Confirm the attribute
exists there and see the version you'd actually get:

```bash
nix eval --raw .#homeConfigurations.dotfiles-debian.pkgs.ripgrep.version   # -> 15.1.0
```

Try it before committing to it — this puts it on `PATH` for one shell and
persists nothing:

```bash
nix shell nixpkgs#hyperfine      # then: hyperfine --version
```

### Nix — global (persist in `home/packages.nix`)

Add the attribute to the list in [`home/packages.nix`](home/packages.nix), in
the group it belongs to; wrap it in `lib.optionals stdenv.isLinux` /
`isDarwin` if it is OS-specific (`home/packages.nix:47`):

```nix
      ripgrep
      jq
+     hyperfine # benchmarking
```

Unfree packages need no extra step — `mkHome` instantiates nixpkgs with
`config.allowUnfree = true` (`flake.nix:41`). Then
[sync it into your home](#staying-in-sync).

### Nix — per project

Project dependencies never go into `home/packages.nix`. Ad hoc, in the project
directory:

```bash
nix shell nixpkgs#ffmpeg nixpkgs#imagemagick   # this shell only, nothing persisted
```

Reproducible: give *that* project its own flake with a devShell and enter it
with `nix develop` (commit its `flake.nix` + `flake.lock`):

```nix
# <project>/flake.nix
{
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
  outputs =
    { nixpkgs, ... }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = [ pkgs.ffmpeg pkgs.imagemagick ];
      };
    };
}
```

To have that shell load on `cd` instead, drop a one-line `.envrc` next to the
flake — direnv + nix-direnv are already part of this config
([`home/direnv.nix`](home/direnv.nix)):

```bash
echo 'use flake' > .envrc
direnv allow          # required once per .envrc, and again after every edit
echo '.direnv/' >> .gitignore
```

`cd` in and the devShell is active; `cd` out and it's gone. The first entry
builds the closure (slow); nix-direnv caches the result in `.direnv/` and pins
it with a GC root, so later entries are instant and `nix-collect-garbage` leaves
it alone.

direnv and the global `mise activate` coexist, and the devShell wins: if the
devShell lists a tool mise also manages (`node`, `just`, …), the devShell's copy
is the one on PATH inside that project — even if a project `mise.toml` pins a
different version. Leave such a tool out of the devShell to keep mise's.

### mise — find a tool

```bash
mise registry | grep -i terraform   # tool name -> the backend(s) mise would use
mise ls-remote node                 # versions available for a tool
```

Short names resolve through mise's registry (core/aqua/ubi); other backends are
named explicitly: `npm:<pkg>`, `cargo:<crate>`, `go:<module>`, `pipx:<pkg>`,
`ubi:<owner>/<repo>`.

### mise — global (two files, two owners)

mise's global config is **split**, because its two halves want opposite
ownership ([ADR-0009](docs/plans/adr-0009-config-ownership-tiers-hm-and-env-links-2026-07-26.md)
tiers):

| File | Holds | Owner |
| --- | --- | --- |
| `~/.config/mise/config.toml` | the tool list | **mise.** Seeded from `home/mise.nix` the first time the target does not exist, then yours to rewrite |
| `~/.config/mise/conf.d/zz-dotfiles.toml` | `[settings]` | Home Manager. Read-only store link, re-applied on every switch |

So `mise use -g`, `mise up --bump` and `mise unuse` all work and persist — the
real `config.toml` lives under `envLinks.stateRoot`, so those versions also
survive container recreation.

The split is what makes both true at once: within the global config, a `conf.d`
file always **overrides** `config.toml` (mise will tell you so: `X is defined in
conf.d/… which overrides the global config`). That is what settings want and
exactly what tools must not have, so only `[settings]` goes there.

**A tool added to `home/mise.nix` does not reach a machine that already
bootstrapped** — the seed applies on creation only, and a switch will not touch
your `config.toml`. Add it there with `mise use -g <tool>@<version>`; the repo
list stays the source of truth for the *next* fresh machine, which is why new
tools still belong in [`home/mise.nix`](home/mise.nix):

```nix
        just = "latest";
        node = "lts";
+       terraform = "latest";
+       "npm:@openai/codex" = "latest";
```

npm-backed tools are installed with **pnpm** (`npm.package_manager = "pnpm"`,
`home/mise.nix:88` — a setting, hence the `conf.d` half), and pnpm blocks
dependency lifecycle scripts by default. If a package genuinely needs its
`postinstall`, approve exactly that package the way `@smithery/cli` does
(`home/mise.nix:29`):

```nix
        "npm:@smithery/cli" = {
          version = "latest";
          allow_builds = [ "@smithery/cli" ];
        };
```

Then, **on this machine**, add it and materialize — a declared-but-not-installed
tool is not on `PATH` until it is installed (`home/mise.nix:60-64`):

```bash
mise use -g terraform@latest     # writes ~/.config/mise/config.toml and installs
mise ls                          # what is installed / active
just runtimes                    # == mise install: catch up anything still missing
```

To check the two halves are landing where they should:

```bash
mise config ls                   # both files, and which tools each contributes
mise settings                    # resolved settings (from the conf.d half)
```

**Host-local escape hatch:** a second `~/.config/mise/conf.d/*.toml` still
overrides everything, including the repo's settings — `conf.d` resolves
**lexically first-wins**, and the Home-Manager-owned file is named `zz-` precisely
so any name you pick beats it. Prefer plain `mise use -g` for host-local *tools*
now that `config.toml` is yours; keep `conf.d` for overriding a setting.

### mise — per project

```bash
cd <project>
mise use node@22 python@3.12   # writes ./mise.toml (creating it) and installs
mise trust                     # needed for a mise.toml that came from git, not from you
mise current                   # active versions here
mise which node                # which shim/binary resolves
```

Commit `mise.toml` in that project; project config is independent of Home
Manager. `mise up` upgrades within the declared range, and `mise up --bump` —
which rewrites the config file — now works on the global config too. Mirror a
bump you want to keep into `home/mise.nix`, or the next fresh machine seeds the
old version.

### Editing the Home Manager config

| Want to change | File |
| ----------------------------------------------- | -------------------------------------------------------------------------- |
| zsh options/plugins, `PATH`, session variables | `home/shell.nix` |
| zsh functions, aliases, fzf-tab tweaks | `home/zsh/functions.zsh`, `home/zsh/fzf-tab.zsh` (sourced verbatim) |
| the prompt | `home/starship.toml` (read by `home/starship.nix`) |
| git settings | `home/git.nix`; aliases in `home/git-aliases.conf` |
| tmux | `home/tmux.conf` (+ `home/tmux.nix`) |
| mise settings (live), mise tool seed | `home/mise.nix` |
| links to writable, out-of-store paths | `home/env-links.nix` (ADR-0009 Tier B — the set every environment wants) |
| the same, for one environment only | `home/env-branch.nix` (empty on shared branches; the only file an env branch edits, so its rebases never conflict) |
| a new machine | the `hosts` attrset in `flake.nix:17` |

Two conventions worth keeping (see
[Contributing](#contributing--conventions-and-guardrails)): prefer an upstream
`programs.*` option over hand-rolled config, and embed verbatim files
(`builtins.readFile` / `source ${./file}`) instead of escaping large blobs into
nix strings. Don't reorder the zsh plugin list in `home/shell.nix` — completions
→ fzf-tab → autosuggestions → syntax-highlighting-last is correctness-critical.

Everything above is inert until Home Manager switches: see
[Staying in sync](#staying-in-sync) for the switch, the preview, and the rollback.
Verify a package landed with `home-manager packages | grep hyperfine`. Or let the
bootstrap drive it — it detects the host and re-runs the post-HM steps too
(`./bootstrap.sh --dry-run --verbose`, then `./bootstrap.sh --yes`).

## Coding agents

Three agents — **Claude Code**, **Codex CLI** and **pi** — are provisioned from
one in-repo manifest (`platform/installers/agents.py`). What the agents *have*
(marketplaces, plugins, MCP servers, pi extensions) is a reviewed table there;
what each agent *is* (model, theme, approval policy) stays in its own config,
which the agents rewrite at runtime. Claude and Codex get their capabilities
through their own CLIs (`claude plugin …`, `claude mcp add`, `codex mcp add`);
pi has no MCP or marketplace CLI, so it gets declarative files this repo owns —
`~/.agents/mcp.json`, `~/.pi/agent/claude-plugins.json`, and the `packages`
array in its settings. pi's `settings.json` is **seeded, never owned**
(ADR-0012): `packages` is reconciled to the manifest, every other key is written
only when absent, so `/model`, `/theme` and hand edits survive re-projection.
Cross-agent instructions live once, in `~/.agents/AGENTS.md`, which Codex and pi
reach by symlink and Claude imports from its thin `~/.claude/CLAUDE.md` shell.
pi replaces omp in the third slot (ADR-0012, 2026-08-28), chosen for
interoperability; it is a mise npm tool (`home/mise.nix`) and `~/.pi/agent` is a
Tier-B out-of-store env link (ADR-0009). Shared memory is an MCP knowledge graph
at `~/.agents/memory/memory.jsonl`, reaching all three agents with no service and
no egress; pi additionally has the local `pi-memory` layer.
Design records:
[ADR-0011](docs/plans/adr-0011-multi-agent-toolchain-single-source-2026-08-04.md),
[ADR-0012](docs/plans/adr-0012-third-slot-upstream-pi-2026-08-28.md).

```bash
python3 platform/installers/agents.py    # what the agents have, and who gets what
./bootstrap.sh --agents claude,codex     # provision a subset (default: all three)
```

Adding a capability is an edit to that manifest plus a commit — never a per-machine
command, which is the drift the ADR exists to stop.

## Post-login interactive setup

Only the two steps that genuinely need you — Smithery auth and the Lark CLI's own
installer — are deferred. `setup.py` writes them to
`~/.local/share/dotfiles/post-login-setup.sh`; the zsh prints a reminder while it's
pending. Run it once when you're ready to authorize:

```bash
dotfiles-postsetup    # needs a TTY; self-removes on success
```

It offers to authenticate [Smithery](https://smithery.ai/) and add your namespace's
MCP endpoint to Claude, then installs the Lark CLI — each step skippable, nothing
fatal. Marketplaces, plugins, MCP servers, the shared memory store and pi's
declarative files are *not* here: they are applied unattended during the
bootstrap. Details:
[platform/README.md](platform/README.md#post-login-setup-smithery--lark).

## China mirrors

Everything mirror-related is gated on one switch. With `--network CN` (or
`DOTFILE_NETWORK_ENV=CN`) the bootstrap wires the CERNET substituter into the
system `nix.conf` and the zsh exports pypi/uv + rustup mirrors. Unset = upstream
defaults.

## Contributing — conventions and guardrails

Design changes start as an RFC in `docs/rfc/` and settle into an ADR in
`docs/plans/` (see the indexes there); read the governing ADR before reshaping
what it governs. ADR-0007 owns the two-layer model, 0009 config ownership, 0010
the plan/clearance, 0011 + 0012 the agent toolchain. ADRs 0001–0006 and 0008
describe the retired Python pipeline — don't cite them as current design.

### Conventions

- **Nix:** modules take `{ pkgs, lib, config, ... }`; prefer upstream
  `programs.*` options over hand-rolled config; embed verbatim files
  (`builtins.readFile` / `source ${./file}`) to dodge nix-string escaping (see
  `git-aliases.conf`, `zsh/*.zsh`, `starship.toml`).
- **Python (`platform/`):** stdlib only; commands via `ctx.run_command` (strips
  the sudo prefix when root, honors dry-run); argument lists over `shell=True`;
  download-then-execute, never `curl | bash`; module logger
  `logging.getLogger("dotfiles")`.
- **The plan is part of the step** (ADR-0010): anything that installs, needs
  privilege, or displaces a file must register itself in the plan next to the
  code that performs it (`plan_prereqs`/`plan_nix` sit beside
  `ensure_prereqs`/`install_lix`; `setup.build_plan` shares its read-only
  decision helpers with the apply path). A step that runs without appearing in
  the plan defeats the clearance.
- **OS identifiers:** `"darwin"`, `"debian"`, `"ubuntu"`, `"amzn"`, `"fedora"`,
  `"rhel"`, `"suse"`, `"arch"`, `"alpine"`, `"unknown"` — one *family* per id
  (`installers/context.py` `Ctx._detect_os`). Exact `/etc/os-release` `ID` wins
  over `ID_LIKE` (Amazon Linux claims `ID_LIKE=fedora` — true for dnf, false for
  the rest), and an unrecognised Linux stays `"unknown"`, **never** guessed as
  `debian`: a family with no backend must be skipped, and it can only be skipped
  if it is named honestly. Never hardcode a package manager — route through
  `_PKG_MANAGERS` (`platform/bootstrap.py`) pre-HM and
  `PackageManager.supported_os` (`installers/managers.py`) post-HM.
- **Markdown:** the rules live in `.markdownlint-cli2.jsonc`, so agents and
  editors stop inventing their own. Tables are **compact** — one space around
  every pipe, `| --- |` separators — never hand-aligned padding, which silently
  rots the moment a cell's content changes and which markdownlint cannot fix
  automatically. Run `npx markdownlint-cli2 --fix <file>` if a table drifts.
  `docs/` ADRs/RFCs are records: they are linted but deliberately not
  retro-formatted, so don't reflow one just to make the linter quiet.
- **Commits:** Conventional-Commits `type(scope): subject`; history is English.

### Don't touch / be careful with

- **`home.stateVersion`** — pinned to the first-built release; don't bump
  casually.
- **`DRY_RUN`** — never export this name around a Home Manager activation:
  `activate` treats it as set-or-unset and would silently dry-run the whole
  switch. The Python layer keeps dry-run in `ctx.dry_run`, not the environment.
- **fzf-tab ordering** (`home/shell.nix`) — completions → fzf-tab →
  autosuggestions → syntax-highlighting-last is correctness-critical;
  `autosuggestion.enable = false` is intentional (loaded as a plugin after
  fzf-tab). Don't "simplify" it.
- **CERNET / mirror wiring** — deliberate, gated on `DOTFILE_NETWORK_ENV=CN`;
  don't hardcode mirrors unconditionally.
- **The `~/.claude/CLAUDE.md` shell** — Claude-only lines plus the
  `@~/.agents/AGENTS.md` import; anything another agent would also want goes in
  `~/.agents/AGENTS.md`.
- **Agent config files** (`~/.claude/settings.json`, `~/.codex/config.toml`,
  `~/.pi/agent/settings.json`) — all rewritten by the agents at runtime, so none
  may ever be a Home Manager store link. Claude's and Codex's are never written
  from `platform/` at all; pi's is the single exception (ADR-0012) and only
  under seed semantics — `packages` reconciled, every other key written **only
  when absent**. If you find yourself overwriting a key pi already has, you have
  broken the contract that makes this safe.

### Adding a new X

User tools, runtimes and system components: see
[Adding software](#adding-software-tutorial). Beyond those:

- **A CLI tool nixpkgs doesn't have** → a derivation in `home/pkgs/<tool>.nix`,
  pulled in via `callPackage` from `home/packages.nix`. **`git add` the new
  file** — the flake copies only tracked files, so an untracked derivation fails
  eval with "path … does not exist".
- **A marketplace / plugin / MCP server / pi extension** → one entry in the
  matching table in `platform/installers/agents.py`, stating which agents it
  targets and why. A marketplace MUST target every agent its plugins do, or
  `pi-claude-marketplace` reports `<marketplace not declared>`; a `PI_PACKAGES`
  spec MUST carry the `npm:` prefix (anything unprefixed is parsed as a local
  path, and a missing local path is skipped silently). Verify with
  `python3 platform/installers/agents.py` and `python3 platform/setup.py
  --plan`. Never install one by hand on a machine — that is the drift ADR-0011
  exists to stop.
- **A fourth agent** → subclass `Agent` in `agents.py` (`id`, `binary`,
  `install`, `project`, `plan`) and add its id to the entries it should receive.
- **A system component** → subclass `OptionalComponent` in `components.py`;
  declarative `installs = {...}` or an imperative `install(self, ctx)`.
  Auto-registers; verify with `uv run platform/installers/components.py`.
- **A new install backend** → subclass `PackageManager` in `managers.py`
  (`id`, `supported_os`, `priority`, `install`).
- **A new machine** → a `hosts` entry in `flake.nix` (name = hostname for
  auto-detection), or rely on the impure `generic` fallback.

### Verification

There is no test framework. Verify with `./bootstrap.sh --dry-run --verbose`
(the whole plan, nothing executed), `nix flake check` (every named host), and
container runs (Debian/Ubuntu/NixOS — see RFC-0001). `python3 -m py_compile
platform/bootstrap.py platform/setup.py` catches syntax slips early.

## Repository layout

```text
Justfile          `just` recipes for the day-to-day Home Manager commands
bootstrap.sh      Shell launcher: ensure python3 → exec platform/bootstrap.py
flake.nix         Inputs (nixpkgs + home-manager), hosts, homeConfigurations
home/             Home Manager modules — the declarative user environment
  packages.nix    All user-level CLI tools
  shell.nix       zsh (fzf-tab order), fzf, zoxide, sessionPath/Variables
  starship.nix    + starship.toml (catppuccin_mocha theme)
  git.nix, tmux.nix, mise.nix, zsh/
platform/         Imperative layer (see platform/README.md)
  bootstrap.py    Orchestrator (plan, clearance, Lix, nix, HM switch); setup.py; installers/
docs/plans/       ADRs (0007 governs)
docs/rfc/         RFCs (0001 = migration log)
```

## Notes

- **Runtimes:** node/rust via [mise](https://mise.jdx.dev/), Python via
  [uv](https://docs.astral.sh/uv/). Nix does **not** provide a system Python.
- Run the bootstrap from inside the cloned repo.
