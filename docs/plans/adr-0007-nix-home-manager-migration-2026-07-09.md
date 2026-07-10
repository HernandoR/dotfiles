# ADR-0007: Migrate to Nix flake + standalone Home Manager for user-level tooling and dotfiles

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-07-09 |
| Supersedes (at cutover) | ADR-0001 |
| Revises (at cutover) | ADR-0002, ADR-0004 |
| Retains | ADR-0005, ADR-0006 |
| Discussion | RFC-0001 |

## Context

The bootstrap today is `bootstrap.sh` → `uv` → `main.py` + `installers/`: it
detects the OS, installs core packages, runs an ordered set of "necessary"
components (oh-my-zsh + antigen, fzf, starship, Node via nvm, mergiraf), stages
`sources/root` into `~/dotfiles` by rsync and symlinks it into `$HOME`
(ADR-0001), then runs user-selected optional components. It works, but it is
imperative and does not reproduce across machines: tool versions are a mix of
pinned tags and unpinned upstreams with no lockfile, zsh plugins are fetched by
antigen at shell startup, and the whole-machine state is only legible by reading
Python. The bespoke stage/symlink/backup machinery re-implements what Home
Manager does natively.

The owner wants the user-level environment managed declaratively and
reproducibly "the Nix way," while keeping the current shell/prompt experience
(starship theme intact, fzf-tab completion) and continuing to run on existing
macOS and Debian/Ubuntu machines without reinstalling the OS. The full reasoning
trail, alternatives, and open-question resolutions are in RFC-0001.

## Decision

Adopt a **Nix flake + standalone Home Manager** configuration as the source of
truth for user-level tooling and dotfiles, on **Lix**, symmetric across macOS
and Linux, with a thin imperative layer for the system-level work Home Manager
cannot own on a non-NixOS host.

> In the context of a non-reproducible, imperative Python bootstrap that we run
> across several macOS and Debian/Ubuntu machines,
> facing version drift, runtime-assembled shell state, and bespoke linking
> machinery,
> we decided for **standalone Home Manager via a Nix flake on Lix**, rebuilt
> with native modules,
> and against nix-darwin, full NixOS, `nix-shell`-only, and verbatim config
> carry-over,
> to achieve declarative, lockfile-pinned, cross-machine reproducibility with
> the starship/zsh experience preserved,
> accepting that system-level provisioning and secrets stay imperative and that
> mise-managed runtimes are not lockfile-reproducible.

### 1. Standalone Home Manager, user-level, symmetric

Top-level flake outputs are `homeConfigurations` built with
`home-manager.lib.homeManagerConfiguration`. **No nix-darwin, no NixOS.** The
same modules serve macOS and Linux. This machine is **aarch64-darwin**
(Apple M3 Max); the fleet also includes x86_64-linux, aarch64-linux, and
possibly WSL.

### 2. Lix as the Nix implementation

Install via the Determinate installer (or Lix's installer), flakes enabled. Lix
is a drop-in for the flakes/Home-Manager workflow; only its internal C++ API
diverges from CppNix, which does not affect this usage. Matches the
`feat/lix-based` branch.

### 3. Full native rewrite; zsh-only

Rebuild the environment with Home Manager modules rather than carrying the old
rc files forward. **Drop oh-my-zsh, antigen, powerlevel10k (`.p10k.zsh`), the
bash framework (`.bashrc`/`.bash_prompt`/`.bash_profile`/`.bash_logout`), and
`.screenrc`.** The shell is zsh-only; tmux is the multiplexer.

### 4. Runtimes: mise + uv

`programs.mise` manages node (LTS) and rust (stable) with an activation script;
project-level `.tool-versions` still switches versions. Python continues to use
**uv** (already in the repo). Accepted trade-off: mise downloads runtimes
imperatively, so that slice is not `flake.lock`-reproducible.

### 5. Multi-host / multi-system helper

Because the fleet spans multiple `system` strings, the flake uses a generic
helper (a `mkHome`-style function, or flake-utils / flake-parts) to enumerate
`homeConfigurations` per host — not the single hard-coded output of a typical
single-machine starter. Each machine gets `hosts/<host>/home.nix` for its
username, `system`, and per-machine extras.

### 6. Repository structure

```
flake.nix              # inputs: nixpkgs + home-manager (on Lix); mkHome helper; outputs: homeConfigurations.<host>
flake.lock
home/
  default.nix          # imports + username/homeDirectory/stateVersion (per-host via specialArgs)
  packages.nix         # home.packages: CLI toolset + _1password-cli + nerd-fonts
  shell.nix            # programs.zsh (completion + fzf-tab + zsh-completions, ordered), programs.fzf, sessionVariables/sessionPath, initContent
  starship.nix         # programs.starship.settings (ported from .config/starship.toml)
  git.nix              # programs.git (mergiraf merge-driver + aliases, ported from .gitconfig)
  tmux.nix             # programs.tmux (ported from .tmux.conf)
  mise.nix             # programs.mise + activation (node LTS + rust stable)
  misc.nix             # xdg.configFile.source: helix/lvim/zellij/alacritty/condarc/ruff verbatim
hosts/
  <host>/home.nix      # per-machine: username, system, extras
platform/              # imperative layer, split around the Home Manager switch
  bootstrap.sh         # PRE-HM (shell): privilege → prereqs → install Lix → nix config (+CN mirror) → home-manager switch
  lib.sh               # shared shell helpers (privilege, OS/host detect, Lix install)
  nix-cn.sh            # flakes + CN mirror gating (system nix.conf) + persist network-env
  setup.py             # POST-HM (python via `uv run`): login shell, SSH keys, Claude, system components
  installers/          # PackageManager backends + system components (docker/cuda/nvidia/llvm), reused by setup.py
```

The imperative layer is split around the switch: **pre-HM is shell** (nix/uv do
not exist yet), **post-HM is Python run via `uv run`** (uv + a Python are on the
HM profile by then, and Python is more maintainable for the multi-step system
installs — it reuses the ADR-0003 `PackageManager`/`Component` machinery). `uv`
owns the Python interpreter; no nix-provided `python3`.

**Privilege model.** `bootstrap.sh` detects `root` / `sudo` / `none`: `root`
runs privileged steps directly (sudo stripped), `sudo` uses sudo, `none` skips
every privileged step and — if nix is not installed (and cannot be, without
privilege) — exits cleanly. The user-level steps (HM switch, SSH keys, Claude)
always run.

**Any user / root.** Named hosts assume the owner (`lz`). An impure `generic`
host reads `$USER`/`$HOME` via `builtins.getEnv` (so it works for root or any
other user under `--impure`); it is gated behind `optionalAttrs`, so it stays
invisible to a pure `nix flake check`.

### 7. Disposition of current assets

**Into the flake (Home Manager native):** zsh (rebuilt) with `zsh-fzf-tab` +
`zsh-completions`; `programs.fzf`; `programs.starship.settings`;
`programs.git` (with the mergiraf merge driver in `extraConfig`);
`programs.tmux`; `programs.mise` (node/rust); the CLI toolset
(`fd`, `bottom`, `gh`, `jujutsu`, `mergiraf`, `ripgrep`, `tree`, `vim`, `wget`,
`rsync`, coreutils, `git-lfs`, `_1password-cli`, nerd-fonts) via
`home.packages`; `.aliases`/`.exports`/`.path`/`.functions` as
`shellAliases`/`sessionVariables`/`sessionPath`/`initContent`; leaf rc files
(`.inputrc`, `.curlrc`, `.wgetrc`, `.condarc`, `.lscolors`, `ruff.toml`,
helix/lvim/zellij/alacritty) via `home.file.source` / `xdg.configFile.source`.

**Kept in the imperative layer (`platform/`):** docker / docker-rootless, CUDA,
NVIDIA drivers, LLVM + `update-alternatives`, apt/brew **system** packages and
GUI casks, Claude deferred OAuth (ADR-0005), SSH-key copy (ADR-0006), codegraph
(not in nixpkgs), and `chsh` to the Nix-provided zsh.

System components are selected with `--system <list>` or the
`DOTFILE_SYSTEM_COMPONENTS` env var (flag wins). Special specs: `all` (every
component; rootless docker wins over rootful), `default` (the default group),
`none` (skip). **When nothing is specified, the `default` group installs** —
currently `brew` on macOS + `software-properties` on Linux. Everything else
(docker/docker-rootless/cuda/nvidia/llvm) stays opt-in; `cuda`/`nvidia` are
deliberately not defaulted (hardware-specific). The macOS `brew` component
installs **Homebrew itself only** (no formulae/casks — CLI tools come from
nixpkgs; GUI apps are added later via `brew install --cask`, or the interactive
picker). Each component declares `supported_os`, so a spec installs only what
applies to the host (Linux components skip on macOS and vice versa). The Claude/Lark/MCP setup is
**interactive** so it is not auto-run: `setup.py` writes
`~/.local/share/dotfiles/post-login-setup.sh`, the HM zsh prints a reminder while
it is pending, and the user runs it once via the `dotfiles-postsetup` function
(self-removes on success). Platform-injected env files are never clobbered (HM
only manages declared files, and collisions are backed up) but are not
auto-sourced — use `~/.proxy` / `~/.extra`.

**Dropped:** oh-my-zsh, antigen, `antigen.zsh`, `.p10k.zsh`, the bash framework,
`.screenrc`, the rsync→stage→symlink pipeline (ADR-0001), and the `init/` plists
and terminal themes (macOS defaults / GUI are out of scope).

**To confirm during implementation:** whether `mergiraf` is packaged in nixpkgs
on the pinned channel; if not, it stays a musl-binary install in `platform/`.

### 8. Constraints retained

- **Secrets never enter the Nix store.** SSH private keys are copied with strict
  perms by the imperative layer (ADR-0006 unchanged).
- **No GUI casks or macOS system defaults in Nix.** Out of scope by choice.
- **CN mirrors are gated on a single switch: `DOTFILE_NETWORK_ENV=CN`.** When
  unset, upstream defaults are used. Split by layer:
  - *Imperative (`platform/bootstrap.sh`), when `CN`:* write the CERNET nix
    substituter (`https://mirrors.cernet.edu.cn/nix-channels/store`; it proxies
    cache.nixos.org and serves the official signing key, so no extra trusted key
    is needed) into the **system** `/etc/nix/nix.custom.conf` (Lix's `!include`
    target) so the daemon serves it to every user — a substituter set in a
    *user-level* `~/.config/nix/nix.conf` is ignored for non-trusted users.
    Likewise configure the Homebrew and pip/uv mirrors, and persist the flag to
    `~/.config/dotfiles/network-env`.
  - *Declarative (Home Manager):* the config is network-neutral. The shell reads
    `DOTFILE_NETWORK_ENV` at startup (`.zshenv`) and exports the pypi/uv and
    rustup mirror variables only when it is `CN`.

### 9. Transition and verification

Parallel until verified. The old Python path stays on `main`; the flake is
developed on `feat/lix-based`. Verification order:

1. `nix flake check` green.
2. **OrbStack Debian container** (the safe sandbox for the destructive first
   switch): install Lix → configure the CN substituter →
   `home-manager switch --flake .#<linux-host>` from a clean home → verify
   starship theme, fzf-tab ordering, git+mergiraf, tmux, the toolset, mise, and
   that a `#!/usr/bin/env bash` project script runs unchanged.
3. Real macOS machine with `home-manager switch -b backup`.

Only after the flake is verified on real hardware do we cut over, port the
retained imperative bits into `platform/`, retire the old pipeline, and flip the
superseded ADRs.

## Consequences

- **Reproducible, legible user environment.** `flake.lock` pins the toolset and
  configs; a new machine converges to the same state with one `home-manager
  switch`. Whole-machine intent is readable as data.
- **Home Manager owns linking and backups**, replacing ADR-0001's bespoke
  stage/symlink/backup machinery and its `_staging_has_unlinked_items` guard.
- **The starship theme and zsh UX are preserved** — starship via
  `programs.starship.settings`, fzf-tab via ordered `programs.zsh.plugins`.
- **Project shell scripts keep working**: standalone HM only *adds* to `PATH`;
  the system still provides `/bin/bash` and `/usr/bin/env`, so purity breakage
  does not reach the login shell (it would only bite under NixOS or a
  `nix develop` pure shell, neither of which we adopt). Note HM does **not** put
  the nix profile bin on `PATH` on its own — it assumes Nix's shell hook does,
  which is absent on single-user/container installs — so `home.sessionPath`
  names `~/.nix-profile/bin` and `/nix/var/nix/profiles/default/bin` explicitly,
  making the HM tools and `nix` reachable by name on every host.
- **System-level work stays imperative.** docker/cuda/nvidia/llvm, GUI apps, and
  the login-shell change are not declarative on non-NixOS hosts; the `platform/`
  layer carries them, so the design is a hybrid, not "everything in Nix."
- **Two prompt/runtime managers coexist by design during transition** — the old
  Python path on `main`, the flake on `feat/lix-based` — until real-hardware
  verification. ADR-0001 (and the linking parts of ADR-0004) remain in effect
  for the legacy path until cutover, then flip to `superseded`. ADR-0002's nvm
  toolchain is replaced by mise. ADR-0005 (Claude post-setup) and ADR-0006
  (SSH-by-copy) are ported unchanged into `platform/`.
- **Costs:** a Nix/Home-Manager/Lix learning and maintenance surface; CN
  first-install latency (mitigated by the mirror); mise runtimes are not
  lockfile-reproducible; the fzf-tab load order must be re-established in the
  native zsh module and verified.
