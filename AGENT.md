# AGENT.md

## Project

Cross-platform **dotfiles**, migrated from a Python installer to a **Nix flake +
standalone Home Manager** setup on [**Lix**](https://lix.systems/), with a thin
**imperative layer** for the few things Home Manager cannot do on a non-NixOS
host. Targets macOS (aarch64) and Debian/Ubuntu (x86_64 + aarch64), symmetric,
**no nix-darwin**. The governing design record is
[`docs/plans/adr-0007-nix-home-manager-migration-2026-07-09.md`](docs/plans/adr-0007-nix-home-manager-migration-2026-07-09.md);
its discussion trail is
[`docs/rfc/rfc-0001-…`](docs/rfc/rfc-0001-nix-home-manager-migration-2026-07-09.md).
Read those before reshaping the model.

Two layers, split around the Home Manager switch:

- **Declarative (Home Manager)** owns the user environment: CLI tools, zsh +
  starship + fzf-tab, git, tmux, mise. Files are symlinked from the nix store —
  there is **no** rsync/staging/link pipeline anymore (the old ADR-0001..0006
  machinery is retired).
- **Imperative (`platform/`)** handles what HM can't: install Lix, configure nix
  (+ optional CERNET mirror), run the HM switch, set the login shell, deploy SSH
  keys, write the deferred Claude setup, and install opt-in Linux system
  software (docker/cuda/nvidia/llvm).

## Layout

```text
bootstrap.sh          Thin entry → exec platform/bootstrap.sh "$@"
flake.nix             Inputs (nixpkgs-unstable + home-manager); hosts; mkHome; homeConfigurations
flake.lock            Pinned inputs
home/                 Home Manager modules (the declarative user environment)
  default.nix         imports + home.username / homeDirectory / stateVersion
  packages.nix        home.packages — all user-level CLI tools (the "necessary" set)
  shell.nix           programs.zsh (fzf-tab order), fzf, zoxide, sessionVariables/sessionPath, initContent
  starship.nix        programs.starship.settings = fromTOML(readFile ./starship.toml)
  starship.toml       catppuccin_mocha theme (verbatim)
  git.nix             programs.git (settings/lfs/signing/attributes) + git-aliases.conf include
  git-aliases.conf    verbatim git aliases (avoids nix-string escaping)
  tmux.nix / tmux.conf, mise.nix
  zsh/                functions.zsh, fzf-tab.zsh — sourced verbatim from initContent
platform/             Imperative layer (see platform/README.md)
  bootstrap.sh        Orchestrator: privilege → prereqs → Lix → nix-cn → HM switch → setup.py
  lib.sh              Shared shell helpers (log/run, detect_priv, load_nix_path, install_lix, …)
  nix-cn.sh           Persist network-env; wire CERNET into system nix.conf when CN
  setup.py            PEP723 uv script: post-HM steps (login shell, SSH, Claude, system SW)
  installers/
    managers.py       PackageManager backends (apt/brew/scripts) + Script/Deb specs (ADR-0003)
    components.py     System-level OptionalComponent registry (docker/cuda/nvidia/llvm/…)
hosts/                (reserved for per-host modules)
docs/plans/           ADRs (0007 governs; 0001–0006 legacy/superseded)
docs/rfc/             RFCs (0001 = migration discussion log)
sources/              Legacy asset scripts (install/*.sh) — NOT deployed by HM
```

## Commands

No Makefile/justfile and no test framework. Entry is the bootstrap or nix
directly:

```bash
./bootstrap.sh                         # full bootstrap (Lix → nix → HM → post-setup)
./bootstrap.sh --dry-run --verbose     # preview every step, run nothing
./bootstrap.sh --network CN            # enable CERNET mirrors (nix + pypi/uv + rustup)
./bootstrap.sh --system all            # + every opt-in Linux system component
./bootstrap.sh --host dotfiles-debian  # force a named flake host

# Home Manager directly (owner on a named host):
nix run . -- switch -b backup                       # if you add a `homeManager` app; else:
nix build .#homeConfigurations.<host>.activationPackage && ./result/activate

# List / run system components:
uv run platform/installers/components.py            # list opt-in system components
python3 platform/installers/components.py           # same (stdlib only)
```

## Architecture

### 1. Flake + hosts (`flake.nix`)

- `hosts` is one attr per machine (`flake.nix:17`): `system` + `username`. Named
  hosts are **pure/reproducible**.
- `mkHome` (`flake.nix:34`) instantiates `nixpkgs` with `config.allowUnfree =
  true` (the 1Password CLI is unfree) and builds a `homeManagerConfiguration`.
- **`generic` host (`flake.nix:55`)** is an *impure* fallback: it reads
  `$USER`/`$HOME` via `builtins.getEnv` at eval time, so it materializes only
  under `--impure` and is invisible to a pure `nix flake check`. bootstrap falls
  back to it for any non-`lz` user (including root) — this is how root/arbitrary
  users and bare containers work.
- `home/default.nix` derives `home.homeDirectory` from an explicit
  `homeDirectory` (generic) or the platform default; `stateVersion = "25.05"`
  (do not bump casually).

### 2. Pre-HM imperative (`platform/bootstrap.sh` + `lib.sh` + `nix-cn.sh`)

Ordered: detect privilege → select host → gate → prereqs → **install Lix** →
configure nix (+CN) → seed flake inputs (optional) → **build + activate HM**.

- **Privilege model** (`lib.sh` `detect_priv`): `root` (run directly), `sudo`
  (via sudo), `none` (skip everything needing sudo; do only user-level nix/HM;
  if nix is absent and can't be installed → respectful exit).
- **Lix install** (`lib.sh` `install_lix`): multi-user (service-managed daemon)
  when an init system exists; otherwise a **single-user `--no-daemon`** install
  (bare docker/CI) with `build-users-group =` so root needs no `nixbld` pool.
- **HM activation**: builds `.#homeConfigurations.<host>.activationPackage` from
  the *locked* home-manager (no `home-manager/master` fetch) and runs
  `$out/activate` with `HOME_MANAGER_BACKUP_EXT=backup` (== `switch -b backup`).
  It then puts the generation's `home-path/bin` on PATH so post-HM `uv` resolves.
- **CN mirror** (`nix-cn.sh`): always persists `~/.config/dotfiles/network-env`;
  when CN + privileged, wires CERNET substituter + `trusted-users` into the
  *system* `nix.conf` (a user-level substituter is ignored for non-trusted users
  under the multi-user daemon).

### 3. Post-HM imperative (`platform/setup.py`, via `uv run`)

Runs after the switch, when `uv` exists on the HM profile. PEP723 script (stdlib
plus the `installers` package only). Steps: `set_login_shell` (chsh to
`~/.nix-profile/bin/zsh`) → `deploy_ssh_keys` (copy `id_*`, strict perms) →
`setup_claude` (write the deferred setup) → `run_system` (opt-in components).

## The component model

- **User-level tools = declarative.** Everything the user runs lives in
  `home/packages.nix` and is installed by HM on every switch. There is no
  "necessary component" phase and no per-tool selection — add a package to the
  list. Reachability is guaranteed because `home.sessionPath`
  (`home/shell.nix`) explicitly names `~/.nix-profile/bin` +
  `/nix/var/nix/profiles/default/bin` (standalone HM does **not** add the nix
  profile to PATH itself).
- **System-level = opt-in `OptionalComponent`** (`installers/components.py`):
  Linux — `docker`, `docker-rootless`, `cuda`, `nvidia`, `llvm`,
  `software-properties`; macOS — `brew` (installs Homebrew itself only, no
  formulae/casks). Selected via `--system <list>` **or** the
  `DOTFILE_SYSTEM_COMPONENTS` env var (flag wins). `OptionalComponent.resolve()`
  accepts names, alias groups, and the `all` keyword (every component; rootless
  docker wins over rootful). Each declares `supported_os`, so `--system all`
  installs only what applies to the host; they need privilege and run last. The ADR-0003 install machinery
  (declarative `installs = {manager_id: spec}` resolved through a
  `PackageManager` backend, with an imperative `install(ctx)` override for
  multi-step installs) is unchanged.

## Environment variables (the full set)

| Var | Where | Effect |
| --- | --- | --- |
| `DOTFILE_NETWORK_ENV=CN` | bootstrap / `nix-cn.sh` / HM `envExtra` | Enable CERNET (nix system.conf) + pypi/uv + rustup mirrors. Unset = upstream. |
| `DOTFILE_SYSTEM_COMPONENTS` | bootstrap / `setup.py` | Fallback for `--system` (e.g. `all`). |
| `DOTFILE_FLAKE_CACHE` | bootstrap | Dir with `seed-paths.txt` to `nix copy` flake inputs from (CN/offline/CI). |
| `DOTFILE_SSH_SRC` | `setup.py` | Override the SSH key source dir (default `sources/root/.ssh`). |

The deferred, **interactive** Claude/Lark/MCP setup is written to
`~/.local/share/dotfiles/post-login-setup.sh` and is **not** auto-run (it needs
a TTY); the HM zsh prints a reminder and the user runs it once via the
`dotfiles-postsetup` shell function (self-removes on success).

## Conventions

- **Nix:** modules take `{ pkgs, lib, config, ... }`; prefer upstream `programs.*`
  options over hand-rolled config; embed verbatim files
  (`builtins.readFile`/`source ${./file}`) to dodge nix-string escaping (see
  `git-aliases.conf`, `zsh/*.zsh`, `starship.toml`).
- **Shell (`platform/*.sh`):** `set -euo pipefail`; route side effects through
  `run` (dry-run aware); internal flags are `DF_DRY_RUN`/`DF_VERBOSE` — **never**
  bare `DRY_RUN` (home-manager's `activate` treats `-v DRY_RUN` as set-or-unset
  and would silently dry-run the whole activation).
- **Python (`setup.py`/`installers`):** stdlib only; commands via
  `ctx.run_command` (strips leading `sudo` when root, honors `--dry-run`);
  argument lists over `shell=True`; download-then-execute (the `scripts`
  backend), never `curl | bash`; module logger `logging.getLogger("dotfiles")`.
- **OS identifiers:** `"darwin"`, `"debian"`, `"ubuntu"`.
- **Commits:** Conventional-Commits `type(scope): subject`; history is English.

## Adding a new X

- **A user CLI tool** → add to `home/packages.nix`. Done (declarative, all hosts).
- **Shell config** → the relevant `home/*.nix` `programs.*` option, or a verbatim
  file sourced from `initContent`.
- **A new machine** → add a `hosts` entry in `flake.nix` (name = hostname for
  auto-detection), or rely on the `generic` impure fallback.
- **A system component** → subclass `OptionalComponent` in `components.py`
  (`name`, `description`, optional `groups`); declarative `installs = {...}` or an
  imperative `install(self, ctx)` for multi-step. Auto-registers; verify with
  `uv run platform/installers/components.py`.
- **A new install backend** → subclass `PackageManager` in `managers.py`
  (`id`, `supported_os`, `priority`, `install`).

## Don't touch / be careful with

- **`home.stateVersion`** — pinned to the first-built release; don't bump casually.
- **`DRY_RUN`** — do not use this name in bootstrap; it collides with HM activate.
- **fzf-tab ordering** (`home/shell.nix`) — completions → fzf-tab →
  autosuggestions → syntax-highlighting-last is correctness-critical;
  `autosuggestion.enable = false` is intentional (loaded as a plugin after
  fzf-tab). Don't "simplify" it.
- **CERNET / mirror wiring** — deliberate, gated on `DOTFILE_NETWORK_ENV=CN`;
  don't hardcode mirrors unconditionally.
- **`sources/`** — legacy assets; not deployed by HM. Don't wire back in blindly.
- **Legacy ADRs 0001–0006** — describe the retired Python pipeline; ADR-0007
  governs. Don't cite them as current design.

## Hard rules

- Cite `file:line` for claims about structure/conventions.
- No test framework: verify with `./bootstrap.sh --dry-run --verbose`, `nix
  flake check`, and container runs (Debian/Ubuntu/NixOS — see RFC-0001).
- Keep the two layers separate: declarative intent in `home/`, imperative
  remainder in `platform/`.
