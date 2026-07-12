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

## What the bootstrap does

Split around the Home Manager switch:

1. **Pre-HM (shell):** detect privilege (root / sudo / none) → install
   prerequisites → **install Lix** → configure Nix (+ optional CERNET mirror) →
   **build & activate Home Manager** with `-b backup`.
2. **Post-HM (Python via `uv`):** set the login shell to the Nix zsh (`chsh`) →
   deploy SSH keys → write the deferred Claude setup → install any opt-in Linux
   system components.

When it finishes, the shell that launched it keeps its **old** PATH, so a bare
`zsh` won't be found yet. Start the new environment with the absolute path it
prints, or just re-login (your login shell is already zsh):

```bash
exec ~/.nix-profile/bin/zsh -l
```

## Flags & environment variables

| Flag | Effect |
| --- | --- |
| `--dry-run` | Print every command without executing it. |
| `--verbose` | Echo each command as it runs. |
| `--network CN` | Enable China (CERNET) mirrors for Nix, pypi/uv, and rustup. |
| `--system <list>` | Install opt-in Linux system components (`all` = every one). |
| `--host NAME` | Force a named flake host instead of auto-detecting. |
| `--no-claude` | Skip writing the Claude/Lark/MCP post-setup. |

| Env var | Effect |
| --- | --- |
| `DOTFILE_NETWORK_ENV=CN` | Same as `--network CN` (also read by the zsh env for pypi/rustup). |
| `DOTFILE_SYSTEM_COMPONENTS` | Fallback for `--system` (e.g. `all`); the flag wins. |
| `DOTFILE_FLAKE_CACHE` | Dir with `seed-paths.txt` to seed flake inputs from (CN/offline/CI). |
| `DOTFILE_SSH_SRC` | Override the SSH key source dir (default `sources/root/.ssh`). |

## Trying it on a new machine (and how to recover)

**Safety model — nothing is destroyed:**

- **Preview first:** `./bootstrap.sh --dry-run --verbose` runs nothing.
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

## Optional system components

User-level tools are always installed declaratively (see
[home/packages.nix](home/packages.nix)). *System-level* software is selected with
`--system` or `DOTFILE_SYSTEM_COMPONENTS` (the flag wins). Special specs: `all`
(every component; if both Docker variants match, **rootless wins**), `default`,
and `none`.

**When you pass nothing, the `default` group installs** — `brew` on macOS,
`software-properties` on Linux. Everything else is opt-in;
`cuda`/`nvidia`/`llvm`/`docker` you request explicitly. Each component is gated by
its OS, so a spec only installs what applies to the host.

```bash
./bootstrap.sh                       # default group only (brew / software-properties)
./bootstrap.sh --system docker,llvm  # exactly these (overrides the default group)
./bootstrap.sh --system all          # everything applicable to this OS
./bootstrap.sh --system none         # no system components at all
DOTFILE_SYSTEM_COMPONENTS=cuda,nvidia ./bootstrap.sh
```

To add components **after** the bootstrap, there's a manual interactive picker
(not auto-run) — it lists the components that apply to this OS as a checklist
(the default group pre-checked), lets you toggle the network for the run, then
installs via the same machinery:

```bash
./nix-system-interactive-install.sh            # pick + install
./nix-system-interactive-install.sh --dry-run  # preview only
```

| Name | Description | OS |
| --- | --- | --- |
| `software-properties` | `add-apt-repository` support **(default on Linux)** | debian, ubuntu |
| `docker` | Docker Engine (rootful) | debian, ubuntu |
| `docker-rootless` | Docker (rootless) | debian, ubuntu |
| `cuda` | CUDA Toolkit 12.6 | debian, ubuntu |
| `nvidia` | NVIDIA driver + container toolkit | debian, ubuntu |
| `llvm` | LLVM 18 (+ `update-alternatives`) | debian, ubuntu |
| `brew` | Homebrew — the package manager only (no formulae/casks) **(default on macOS)** | darwin |

On macOS the bootstrap does **not** install Homebrew by default (CLI tools come
from nixpkgs). Add it with `--system brew` (or `--system all`); on CN it uses the
BFSU mirror. It installs Homebrew *itself* only — add GUI apps yourself with
`brew install --cask <app>`.

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

## Post-login interactive setup

The Claude/Smithery/Lark setup (plugins, MCP servers, Lark CLI auth) is
*interactive*, so it is **not** auto-run. `setup.py` writes it to
`~/.local/share/dotfiles/post-login-setup.sh`; the zsh prints a reminder while
it's pending. Run it once when you're ready to authorize:

```bash
dotfiles-postsetup    # needs a TTY; self-removes on success
```

**Smithery MCP.** The [Smithery](https://smithery.ai/) CLI is expected to be
already installed, so the script calls `smithery` directly (no `npx`). It:

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
