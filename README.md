# lz's dotfiles

Cross-platform dotfiles built on a **Nix flake + standalone
[Home Manager](https://nix-community.github.io/home-manager/)** running on
[**Lix**](https://lix.systems/), with a thin **imperative layer**
([`platform/`](platform/)) for the few things Home Manager can't do on a
non-NixOS host. Targets macOS (aarch64) and Debian/Ubuntu (x86_64 + aarch64).
The zsh + Starship (catppuccin_mocha) + fzf-tab experience is preserved.

Design is recorded in [ADR-0007](docs/plans/adr-0007-nix-home-manager-migration-2026-07-09.md)
(intent) and [RFC-0001](docs/rfc/rfc-0001-nix-home-manager-migration-2026-07-09.md)
(discussion trail); [AGENT.md](AGENT.md) is the contributor/agent guide.

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

  will install
    - prerequisites via apt-get: curl git xz-utils ca-certificates   [privileged]
    - Lix (multi-user) — fetch install.lix.systems/lix, create /nix, …   [privileged]
    - Home Manager generation for 'dotfiles-debian' — the whole user environment …
    - mise runtimes: aws-cli, docker-cli, go, just, node, …

  will write / link
    - /etc/nix/nix.conf <- experimental-features = nix-command flakes   [privileged]
    - Home Manager symlinks into /home/lz from the nix store (~/.zshrc, ~/.config/git, …)
    - link map ~/link-map.jsonc: 7 entries, 1 of them displacing a real file/dir
    - login shell /bin/bash -> ~/.nix-profile/bin/zsh (chsh; adds it to /etc/shells)   [privileged]

  will move your existing files aside (renamed, never deleted)
    - any $HOME file Home Manager wants to own -> the same name with a .backup suffix
    - /home/lz/.zsh_history (file) -> .zsh_history.pre-dotfiles.bak, then linked to …

? Proceed with this plan? [Y/n]
```

The last section is separate on purpose: displacing files you already have is
the only part of a bootstrap that touches your data, so it is listed
file-by-file, last, right where you answer.

Answering anything but yes exits without changing a thing. There is exactly one
prompt — no step-by-step nagging. A run with **no terminal** (CI, container
build, cron, `bash -c`) never asks and behaves as it always has; `--yes` skips
the prompt on a terminal too (the plan is still printed). Design record:
[ADR-0010](docs/plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md).

## What the bootstrap does

Split around the Home Manager switch:

1. **Pre-HM (shell):** detect privilege (root / sudo / none) → install
   prerequisites → **install Lix** → configure Nix (+ optional CERNET mirror) →
   **build & activate Home Manager** with `-b backup`.
2. **Post-HM (Python via `uv`):** apply the JSON(C) link map
   (`DOTFILE_LINK_MAP_JSON`, if set) → set the login shell to the Nix zsh
   (`chsh`) → write the deferred Claude setup → install any opt-in Linux system
   components.

When it finishes, the shell that launched it keeps its **old** PATH, so a bare
`zsh` won't be found yet. Start the new environment with the absolute path it
prints, or just re-login (your login shell is already zsh):

```bash
exec ~/.nix-profile/bin/zsh -l
```

## Flags & environment variables

| Flag              | Effect                                                      |
| ----------------- | ----------------------------------------------------------- |
| `--dry-run`       | Print every command without executing it (no clearance prompt — nothing to clear). |
| `--verbose`       | Echo each command as it runs.                               |
| `--yes` / `-y`    | Skip the clearance prompt (the plan is still printed). Same as `DF_ASSUME_YES=1`. |
| `--network CN`    | Enable China (CERNET) mirrors for Nix, pypi/uv, and rustup. |
| `--system <list>` | Install opt-in Linux system components (`all` = every one). |
| `--host NAME`     | Force a named flake host instead of auto-detecting.         |
| `--no-claude`     | Skip writing the Claude/Lark/MCP post-setup.                |

| Env var                     | Effect                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DF_ASSUME_YES=1`           | Skip the interactive clearance (same as `--yes`); exported automatically once you have cleared the plan, so the nested steps never re-ask.                                                                                                                                                                                                                             |
| `DOTFILE_NETWORK_ENV=CN`    | Same as `--network CN` (also read by the zsh env for pypi/rustup).                                                                                                                                                                                                                                                                                                   |
| `DOTFILE_SYSTEM_COMPONENTS` | Fallback for `--system` (e.g. `all`); the flag wins.                                                                                                                                                                                                                                                                                                                 |
| `DOTFILE_FLAKE_CACHE`       | Dir with `seed-paths.txt` to seed flake inputs from (CN/offline/CI).                                                                                                                                                                                                                                                                                                 |
| `DOTFILE_LINK_MAP_JSON`     | Opt-in: path to a JSON/JSONC link map (`{"links":{"<label>":{"source","target","type":"dir"\|"file"}}}`), applied as the **first** post-HM step. Unset = skip; set-but-missing file = error. Real targets are backed up to `.pre-dotfiles.bak` before linking; source type/existence mismatches warn (re-summarized at the end). Example: `platform/link-map.jsonc`. |

## Trying it on a new machine (and how to recover)

**Safety model — nothing is destroyed:**

- **Preview first:** `./bootstrap.sh --dry-run --verbose` runs nothing. An
  ordinary interactive run also prints its full plan and waits for clearance
  before the first change.
- **Existing dotfiles are backed up, not deleted.** Activation uses `-b backup`
  (`HOME_MANAGER_BACKUP_EXT=backup`), so a pre-existing `~/.zshrc` /
  `~/.gitconfig` / etc. is renamed to `~/.zshrc.backup` before the Home Manager
  symlink is placed.
- **The old setup stays intact.** This lives on the `feat/lix-based` branch; the
  previous config remains on `main`, and previous Home Manager generations are
  kept until you expire them.

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

## Component classification

Components in this repo are split into two broad categories:

- **User components** — declarative, managed by Home Manager in
  `home/packages.nix`.
- **System components** — imperative, installed by `platform/setup.py` via the
  `OptionalComponent` registry in `platform/installers/components.py`.

### User components

User components are the packages that Home Manager installs on every switch.
They are the default user environment and include the core CLI toolset, runtime
support, and the tools you use interactively.

- **Default user components** are the main `home/packages.nix` list that applies
  on all supported hosts. This includes tools such as `ripgrep`, `jq`, `fd`,
  `tree`, `wget`, `uv`, and the rest of the core CLI toolset.
- **Conditional user components** are still declarative, but gated by OS or
  other build-time conditions in `home/packages.nix` (for example, `xclip` is
  included only on Linux).

These user components are not selected with `--system`; they are always applied
by Home Manager as part of the bootstrap.

### System components

System components are the things Home Manager cannot own on a non-NixOS host.
They are selected with `--system <list>` or `DOTFILE_SYSTEM_COMPONENTS` and
installed after the Home Manager switch.

- **Required system components**
  - `software-properties` on Debian/Ubuntu. It provides `add-apt-repository`
    and is installed whenever `run_system` runs. Only `--system none` skips it.
- **Optional system components**
  - `docker` — Docker Engine (rootful)
  - `docker-rootless` — Docker (rootless)
  - `cuda` — CUDA Toolkit 12.6
  - `nvidia` — NVIDIA driver + container toolkit
  - `llvm` — LLVM 18 (+ `update-alternatives`)
  - `brew` — Homebrew itself on macOS only (no formulae/casks)

The `--system` selector accepts comma-separated component names, alias groups,
and `all`; if both `docker` and `docker-rootless` are selected, rootless wins.
When unset, the default system spec is used: on macOS that means `brew`, while on
Linux it means no optional system component, but required Linux prerequisites
like `software-properties` still run unless `--system none` is specified.

```bash
./bootstrap.sh                       # user components + default system components
./bootstrap.sh --system docker,llvm  # system components + required Linux prerequisites
./bootstrap.sh --system all          # every applicable system component
./bootstrap.sh --system none         # no system components at all (skips required too)
DOTFILE_SYSTEM_COMPONENTS=cuda,nvidia ./bootstrap.sh
```

To add components after bootstrap, run the manual interactive picker:

```bash
./nix-system-interactive-install.sh            # pick + install
./nix-system-interactive-install.sh --dry-run  # preview only
```

| Name                  | Description                                                                    | OS             |
| --------------------- | ------------------------------------------------------------------------------ | -------------- |
| `software-properties` | `add-apt-repository` support **(required on Linux — always installed)**        | debian, ubuntu |
| `docker`              | Docker Engine (rootful)                                                        | debian, ubuntu |
| `docker-rootless`     | Docker (rootless)                                                              | debian, ubuntu |
| `cuda`                | CUDA Toolkit 12.6                                                              | debian, ubuntu |
| `nvidia`              | NVIDIA driver + container toolkit                                              | debian, ubuntu |
| `llvm`                | LLVM 18 (+ `update-alternatives`)                                              | debian, ubuntu |
| `brew`                | Homebrew — the package manager only (no formulae/casks) **(default on macOS)** | darwin         |

On macOS the bootstrap does **not** install Homebrew by default (CLI tools
come from nixpkgs). Add it with `--system brew` (or `--system all`); on CN it
uses the BFSU mirror. It installs Homebrew _itself_ only — add GUI apps
yourself with `brew install --cask <app>`.

For the GUI apps, there's a manual **interactive cask picker** (not auto-run):

```bash
./brew-cask-interactive-install.sh
```

It runs a small `uv` script ([platform/brew_cask_install.py](platform/brew_cask_install.py),
deps declared inline via uv script mode) that shows the recommended casks as a
checklist (Edge + Alacritty pre-checked — edit the list in the file), lets you
pick a Homebrew mirror for the run (default follows `DOTFILE_NETWORK_ENV`), then
installs your selection.

List them anytime: `uv run platform/installers/components.py`.

## Adding software (tutorial)

Where a new tool is written down depends on which layer owns it:

| What you want                                                   | Write it in                                                              | Scope                                     |
| --------------------------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------- |
| A CLI tool that exists in nixpkgs                               | `home/packages.nix`                                                      | every host, on every switch               |
| A runtime, or a tool that only ships via npm/cargo/go/gh-release | `home/mise.nix` (`programs.mise.globalConfig.tools`)                     | every host, after `mise install`          |
| Something only one project needs                                | that project's `mise.toml`, **or** its own `flake.nix` devShell          | that directory tree                       |
| A daemon/driver/apt-level thing (docker, cuda, llvm, …)          | `platform/installers/components.py` + `--system`                         | see [Component classification](#component-classification) |
| A one-off experiment                                            | nothing — `nix shell nixpkgs#<pkg>`                                      | the current shell only                    |

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
[sync it into your home](#syncing-a-change-into-the-running-home).

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

To have the shell load on `cd`, add direnv to *this* config
(`programs.direnv.enable = true;` + `nix-direnv.enable = true;` in a
`home/*.nix` module — it is not part of the config today) and a one-line
`.envrc` (`use flake`) in the project.

### mise — find a tool

```bash
mise registry | grep -i terraform   # tool name -> the backend(s) mise would use
mise ls-remote node                 # versions available for a tool
```

Short names resolve through mise's registry (core/aqua/ubi); other backends are
named explicitly: `npm:<pkg>`, `cargo:<crate>`, `go:<module>`, `pipx:<pkg>`,
`ubi:<owner>/<repo>`.

### mise — global (persist in `home/mise.nix`)

`~/.config/mise/config.toml` is **generated**: Home Manager symlinks it into the
nix store, so `mise use --global …` cannot persist there (the write hits a
read-only store path; as root it edits the store copy and the next switch
reverts it). The global tool list lives in
[`home/mise.nix`](home/mise.nix):

```nix
        just = "latest";
        node = "lts";
+       terraform = "latest";
+       "npm:@openai/codex" = "latest";
```

npm-backed tools are installed with **pnpm** (`npm.package_manager = "pnpm"`,
`home/mise.nix:21`), and pnpm blocks dependency lifecycle scripts by default. If
a package genuinely needs its `postinstall`, approve exactly that package the way
`@smithery/cli` does (`home/mise.nix:38`):

```nix
        "npm:@smithery/cli" = {
          version = "latest";
          allow_builds = [ "@smithery/cli" ];
        };
```

Then switch and materialize — a declared-but-not-installed tool is not on `PATH`
until `mise install` has run (`home/mise.nix:3-8`):

```bash
home-manager switch --flake .#dotfiles-debian -b backup
mise install                     # install everything the global config declares
mise ls                          # what is installed / active
```

**Escape hatch for one machine only:** mise also reads
`~/.config/mise/conf.d/*.toml`, which Home Manager does not own — a file there
survives switches and is a legitimate place for host-local tools. The trade-off
is the usual one: it is outside git, so no other machine gets it.

### mise — per project

```bash
cd <project>
mise use node@22 python@3.12   # writes ./mise.toml (creating it) and installs
mise trust                     # needed for a mise.toml that came from git, not from you
mise current                   # active versions here
mise which node                # which shim/binary resolves
```

Commit `mise.toml` in that project; project config is independent of Home
Manager. `mise up` upgrades within the declared range (global config included,
since it rewrites nothing); `mise up --bump` *would* rewrite the config file, so
for global tools make that version change in `home/mise.nix` instead.

### Editing the Home Manager config

| Want to change                                  | File                                                                       |
| ----------------------------------------------- | -------------------------------------------------------------------------- |
| zsh options/plugins, `PATH`, session variables  | `home/shell.nix`                                                           |
| zsh functions, aliases, fzf-tab tweaks          | `home/zsh/functions.zsh`, `home/zsh/fzf-tab.zsh` (sourced verbatim)        |
| the prompt                                      | `home/starship.toml` (read by `home/starship.nix`)                          |
| git settings                                    | `home/git.nix`; aliases in `home/git-aliases.conf`                          |
| tmux                                            | `home/tmux.conf` (+ `home/tmux.nix`)                                       |
| mise tools/settings                             | `home/mise.nix`                                                            |
| links to env-specific mutable paths             | `home/env-links.nix` (ADR-0009 Tier B — real entries live on env branches)  |
| a new machine                                   | the `hosts` attrset in `flake.nix:17`                                       |

Two conventions worth keeping (see [AGENT.md](AGENT.md)): prefer an upstream
`programs.*` option over hand-rolled config, and embed verbatim files
(`builtins.readFile` / `source ${./file}`) instead of escaping large blobs into
nix strings. Don't reorder the zsh plugin list in `home/shell.nix` — completions
→ fzf-tab → autosuggestions → syntax-highlighting-last is correctness-critical.

### Syncing a change into the running home

Everything above is inert until Home Manager switches. From the repo:

```bash
# 1) preview: build the new generation, activate nothing, leave no ./result symlink
nix build --no-link --print-out-paths .#homeConfigurations.dotfiles-debian.activationPackage
nix store diff-closures /nix/var/nix/profiles/per-user/"$USER"/home-manager <the printed path>

# 2) activate
home-manager switch --flake .#dotfiles-debian -b backup
```

**Which host?** Your hostname if `flake.nix` defines it, else the OS/arch default
(`platform/lib.sh:211`). Any other user — including root — uses the impure
`generic` fallback, which needs `--impure`:

```bash
home-manager switch --flake .#generic -b backup --impure
```

`-b backup` is what the bootstrap does (`HOME_MANAGER_BACKUP_EXT=backup`);
without it, a switch aborts as soon as it finds a real file where a symlink
should go. Or let the bootstrap drive it — it detects the host and re-runs the
post-HM steps too:

```bash
./bootstrap.sh --dry-run --verbose   # preview the whole thing
./bootstrap.sh --yes                 # apply without the clearance prompt
```

Afterwards, in your shell:

```bash
exec zsh -l                          # pick up the new PATH / env / completions
mise install                         # materialize newly declared mise tools
home-manager packages | grep hyperfine   # verify the generation contains it
```

If the result is wrong, `home-manager switch --rollback` — see
[Trying it on a new machine](#trying-it-on-a-new-machine-and-how-to-recover).

**Updating versions** (as opposed to adding packages):

```bash
nix flake update                     # all inputs
nix flake update nixpkgs             # just nixpkgs
home-manager switch --flake .#dotfiles-debian -b backup
mise up                              # mise tools, within their declared ranges
```

Commit the changed `flake.lock` together with the change that needed it.

## Post-login interactive setup

The Claude/Smithery/Lark setup (plugins, MCP servers, Lark CLI auth) is
_interactive_, so it is **not** auto-run. `setup.py` writes it to
`~/.local/share/dotfiles/post-login-setup.sh`; the zsh prints a reminder while
it's pending. Run it once when you're ready to authorize:

```bash
dotfiles-postsetup    # needs a TTY; self-removes on success
```

**Smithery MCP.** The [Smithery](https://smithery.ai/) CLI is declared as an
mise npm tool (`npm:@smithery/cli`) and materialized eagerly by `setup.py`
alongside node, so the script calls `smithery` directly (no `npx`). It:

1. **API-key auth** — if `SMITHERY_API_KEY` is set in the environment, it asks
   whether to authenticate with that key. The CLI reads the variable itself, so
   choosing yes just verifies it via `smithery auth whoami`; with no key set it
   offers an interactive `smithery auth login` instead.
2. **Namespace form** — it then offers to add your namespace's aggregated MCP
   endpoint (`https://mcp.smithery.run/<namespace>`) to Claude via
   `smithery mcp add … --client claude`, falling back to
   `claude mcp add --transport http <namespace> https://mcp.smithery.run/<namespace>`.
3. Leaves a **commented-out** `smithery mcp add <server> --client claude` line
   (e.g. `upstash/context7-mcp`, which the namespace already covers) as a
   template for adding a separate server later.

## China mirrors

Everything mirror-related is gated on one switch. With `--network CN` (or
`DOTFILE_NETWORK_ENV=CN`) the bootstrap wires the CERNET substituter into the
system `nix.conf` and the zsh exports pypi/uv + rustup mirrors. Unset = upstream
defaults.

## Repository layout

```text
bootstrap.sh      Thin entry → platform/bootstrap.sh
flake.nix         Inputs (nixpkgs + home-manager), hosts, homeConfigurations
home/             Home Manager modules — the declarative user environment
  packages.nix    All user-level CLI tools
  shell.nix       zsh (fzf-tab order), fzf, zoxide, sessionPath/Variables
  starship.nix    + starship.toml (catppuccin_mocha theme)
  git.nix, tmux.nix, mise.nix, zsh/
platform/         Imperative layer (see platform/README.md)
  bootstrap.sh    Orchestrator; lib.sh; nix-cn.sh; setup.py; installers/
docs/plans/       ADRs (0007 governs)
docs/rfc/         RFCs (0001 = migration log)
sources/          Legacy assets (not deployed by Home Manager)
```

## Notes

- **Runtimes:** node/rust via [mise](https://mise.jdx.dev/), Python via
  [uv](https://docs.astral.sh/uv/). Nix does **not** provide a system Python.
- Run the bootstrap from inside the cloned repo.
