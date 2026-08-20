# AGENTS.md

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
  machinery is retired). Config a tool rewrites at runtime is the exception, and
  ADR-0009 says where it goes instead: `home/env-links.nix` entries link it to a
  writable target and seed it on creation (the agents' dirs, and mise's tool list
  — `home/mise.nix` keeps only mise's `[settings]` as a store link).
- **Imperative (`platform/`)** handles what HM can't: install Lix, configure nix
  (+ optional CERNET mirror), run the HM switch, set the login shell, deploy SSH
  keys, write the deferred Claude setup, and install opt-in Linux system
  software (docker/cuda/nvidia/llvm).

## Layout

```text
Justfile              Named recipes for the recurring HM operations (build/diff/switch/…)
bootstrap.sh          Thin entry → exec platform/bootstrap.sh "$@"
brew-cask-interactive-install.sh   Manual macOS cask picker (→ platform/brew_cask_install.py); NOT auto-run
nix-system-interactive-install.sh  Manual system-component picker (→ platform/nix_system_install.py); NOT auto-run
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
  tmux.nix / tmux.conf, mise.nix, direnv.nix
  env-links.nix       ADR-0009 Tier B: mkOutOfStoreSymlink mechanism + the $HOME links every env wants
  env-branch.nix      the per-env delta (empty on shared branches; the ONLY file an env branch edits)
  zsh/                functions.zsh, fzf-tab.zsh — sourced verbatim from initContent
  pkgs/               local derivations for tools nixpkgs lacks (getnf.nix — the Nerd Fonts installer CLI)
platform/             Imperative layer (see platform/README.md)
  bootstrap.sh        Orchestrator: privilege → prereqs → Lix → nix-cn → HM switch → setup.py
  lib.sh              Shared shell helpers (log/run, detect_priv, load_nix_path, install_lix, …)
  nix-cn.sh           Persist network-env; wire CERNET into system nix.conf when CN
  setup.py            PEP723 uv script: post-HM steps (login shell, coding agents, system SW)
  brew_cask_install.py   uv/questionary impl of the root cask picker
  nix_system_install.py  uv/questionary impl of the root system-component picker
  installers/
    managers.py       PackageManager backends (apt/brew/scripts) + Script/Deb specs (ADR-0003)
    components.py     System-level OptionalComponent registry (docker/cuda/nvidia/llvm/brew/…) + codegraph
    agents.py         ADR-0011: the multi-agent capability manifest + its per-agent CLI projection
    context.py        Shared Ctx + detect_priv (used by setup.py + the pickers)
hosts/                (reserved for per-host modules)
docs/plans/           ADRs (0007 governs the layers, 0009 config ownership, 0010 the plan,
                      0011 the agent toolchain; 0001–0006 + 0008 legacy/superseded)
docs/rfc/             RFCs (0001 = migration discussion log)
```

## Commands

No test framework. `Justfile` names the recurring Home Manager operations —
prefer a recipe over the raw command, it already carries the host resolution and
the `-b backup` policy:

```bash
just                     # list every recipe
just show-host           # which flake host resolves here (and pure vs impure)
just build               # build the activation package, change nothing
just diff                # build + diff-closures against the live generation
just switch              # build + activate (HOME_MANAGER_BACKUP_EXT=backup)
just reset-hard          # move managed $HOME paths to ~/dotfiles_backup/<stamp>/, then activate
just check               # nix flake check (named hosts; `generic` is invisible)
just update [input]      # nix flake update
just rollback            # step back one generation
just plan                # ./bootstrap.sh --dry-run --verbose
just host=<name> switch  # force a host (also DF_HOST=…)
```

The host is resolved by reusing `platform/lib.sh` the way `bootstrap.sh:91-102`
does — **keep the Justfile's `host :=` block in step with that logic.**

Underneath, or when `just` is not available yet:

```bash
./bootstrap.sh                         # full bootstrap (Lix → nix → HM → post-setup)
./bootstrap.sh --dry-run --verbose     # preview every step, run nothing
./bootstrap.sh --network CN            # enable CERNET mirrors (nix + pypi/uv + rustup)
./bootstrap.sh --system all            # + every opt-in Linux system component
./bootstrap.sh --agents claude         # provision only Claude Code (default: all three)
./bootstrap.sh --agents none           # no agent tooling at all (was --no-claude)
./bootstrap.sh --host dotfiles-debian  # force a named flake host

# Home Manager directly (owner on a named host):
nix run . -- switch -b backup                       # if you add a `homeManager` app; else:
nix build .#homeConfigurations.<host>.activationPackage && ./result/activate

# List / run system components:
uv run platform/installers/components.py            # list opt-in system components
python3 platform/installers/components.py           # same (stdlib only)
python3 platform/installers/agents.py               # print the agent capability manifest
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
- **Plan + one-shot clearance** (ADR-0010; `lib.sh:9-105`, `bootstrap.sh:102-155`):
  before the first mutation, every step registers what it *would* do
  (`plan_fact`/`plan_install`/`plan_config`/`plan_backup` — the last bucket,
  printed last and highlighted, is anything that displaces a file the user
  already has), the merged plan is printed
  (`print_plan`) and `require_clearance` takes a single yes/no. The nested
  scripts describe their own half — `nix-cn.sh --plan` and `setup.py
  --plan-items` emit `section<TAB>text<TAB>priv`, merged by `plan_import_tsv` —
  so the plan cannot drift from the run. **No per-step prompts.** A run with no
  terminal never asks (`is_interactive`: stdin tty, or stdout tty + readable
  `/dev/tty` for the `curl | bash` case), so CI/containers are unchanged;
  `--yes`/`DF_ASSUME_YES=1` and `--dry-run` skip the prompt. Clearance exports
  `DF_ASSUME_YES=1`, which is how `setup.py` knows not to ask again.
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
`~/.nix-profile/bin/zsh`) → `setup_runtimes` (`mise install` for node/rust/…) →
`setup_agents` (install the selected agents + project the manifest) →
`write_deferred_setup` (the interactive remainder) → `run_system` (opt-in
components). The last three run only when at least one agent is selected.

### 4. The agent toolchain (`platform/installers/agents.py`, ADR-0011)

One manifest, three agents, projected by each agent's own CLI:

- **Manifest** — `MARKETPLACES`, `PLUGINS`, `MCP_SERVERS`. Every
  entry names the agents it targets and why. This is the single reviewed source
  for what the agents *have*; adding one is a commit, not a per-machine command.
- **Projection** — one `Agent` subclass per agent (`claude`/`codex`/`omp`) owning
  that agent's install channel and its own commands (`claude plugin install`,
  `claude mcp add`, `codex mcp add`, omp's native `~/.omp/agent/mcp.json`).
  Nothing here writes an agent's config file: all three rewrite their own config
  at runtime, which is also why none of it is Home-Manager-managed (ADR-0009
  Tier A is excluded by construction). **Projection is add-only** — removing a
  manifest entry does not uninstall it.
- **Instruction plane** — `~/.agents/AGENTS.md` is the only source, and all three
  agents reach it: `~/.codex/AGENTS.md` and `~/.omp/agent/AGENTS.md` symlink to
  it, and `~/.claude/CLAUDE.md` is a thin shell that `@~/.agents/AGENTS.md`-imports
  it and holds Claude-only lines. Nothing cross-agent may go in the shell
  (`setup.py` warns when it grows past 40 lines). Delegated installers that append
  to a linked file and write it back (codegraph does) are handled by re-asserting
  the links afterwards and folding the addition into the shared source.
- **Skills** — dual track. Marketplaces stay marketplace-managed and now reach
  **both** Claude and Codex (Codex grew a plugin marketplace after ADR-0011 was
  written; the ADR's "Codex cannot see agent-skillset" gap is closed and its
  closure is verified). Loose skills live in `~/.agents/skills`, which Codex and
  omp read natively and to which `~/.codex/skills` and `~/.omp/agent/skills` are
  linked.
- **Selection** — `--agents=<spec>` (`claude,codex,omp` / `all` / `none`; unset =
  all). `--no-claude` is a deprecated alias for `none`.
- **Memory** — **omp-native, via mnemopi**. `memory.backend = mnemopi` is
  projected with `omp config set` (`OmpAgent.set_memory_backend`), which turns on
  omp's bundled local memory store: SQLite under omp's agent memories dir inside
  `~/.omp`, with **no daemon and no port**. The agentmemory daemon, its MCP shim,
  its Home Manager unit (`home/agentmemory.nix`), its `~/.agentmemory` env link
  and the no-service-manager fallback start are all gone (ADR-0011 update log,
  2026-08-20) — nothing in the bootstrap keeps a resident process alive any more.
  Claude and Codex are back to whatever their own settings say: memory is
  **preference plane** for them, so it stays per machine and the manifest never
  writes it.

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
  docker wins over rootful). **`software-properties` is `required = True`**, so
  `run_system` always installs it first on its applicable OS (debian/ubuntu) —
  whatever the spec — because `add-apt-repository` is a prerequisite for the
  docker/nvidia/llvm repo setup; `--system none` is the only opt-out (it never
  calls `run_system`). **With nothing specified, `setup.py` installs the
  `default` group** (`groups = {"default"}` → `brew` on macOS) plus the required
  `software-properties` on Linux. Each declares `supported_os`, so a spec
  installs only what applies to the host; they need privilege and run last. The ADR-0003 install machinery
  (declarative `installs = {manager_id: spec}` resolved through a
  `PackageManager` backend, with an imperative `install(ctx)` override for
  multi-step installs) is unchanged.

## Environment variables (the full set)

| Var | Where | Effect |
| --- | --- | --- |
| `DF_ASSUME_YES=1` | bootstrap / `lib.sh` / `setup.py` (`Ctx.assume_yes`) | Skip the one-shot clearance (same as `--yes`/`-y`). Exported by `require_clearance` after a yes, so nested steps don't re-ask. |
| `DOTFILE_NETWORK_ENV=CN` | bootstrap / `nix-cn.sh` / HM `envExtra` | Enable CERNET (nix system.conf) + pypi/uv + rustup mirrors. Unset = upstream. |
| `DOTFILE_SYSTEM_COMPONENTS` | bootstrap / `setup.py` | Fallback for `--system` (e.g. `all`). |
| `DOTFILE_AGENTS` | bootstrap / `setup.py` | Fallback for `--agents` (e.g. `claude` or `none`); unset = all agents. |
| `DOTFILE_FLAKE_CACHE` | bootstrap | Dir with `seed-paths.txt` to `nix copy` flake inputs from (CN/offline/CI). |

Only what genuinely blocks on a human — Smithery auth and the Lark CLI installer
— is deferred to `~/.local/share/dotfiles/post-login-setup.sh`; the HM zsh prints
a reminder and the user runs it once via the `dotfiles-postsetup` shell function
(self-removes on success). Marketplaces, plugins, MCP servers and omp's native
MCP config are **not** deferred: the manifest is only a single source if applying
it needs no human, so they run unattended with stdin on `/dev/null`.

## Conventions

- **Nix:** modules take `{ pkgs, lib, config, ... }`; prefer upstream `programs.*`
  options over hand-rolled config; embed verbatim files
  (`builtins.readFile`/`source ${./file}`) to dodge nix-string escaping (see
  `git-aliases.conf`, `zsh/*.zsh`, `starship.toml`).
- **Adding a step that installs, needs privilege, or displaces a file:** register
  it in the plan too, next to the code that performs it (`plan_prereqs`/`plan_nix`
  sit beside `ensure_prereqs`/`install_lix`; `nix-cn.sh --plan` and `setup.py`'s
  `build_plan` share their read-only decision helpers with the apply path). A
  step that runs without appearing in the plan defeats the clearance — ADR-0010
  makes this a standing rule, not a nicety.
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
- **A user CLI tool nixpkgs doesn't have** → a derivation in `home/pkgs/<tool>.nix`,
  pulled in as `(callPackage ./pkgs/<tool>.nix { })` from the `with pkgs` list in
  `packages.nix` (`home/packages.nix:52`). `git add` the new file — the flake
  copies only tracked files, so an untracked derivation fails eval with "path …
  does not exist".
- **Shell config** → the relevant `home/*.nix` `programs.*` option, or a verbatim
  file sourced from `initContent`.
- **A new machine** → add a `hosts` entry in `flake.nix` (name = hostname for
  auto-detection), or rely on the `generic` impure fallback.
- **A marketplace / plugin / MCP server / agent extension** → one entry in the
  matching table in `platform/installers/agents.py`, stating which agents it
  targets and why (omp's extension set is deliberately empty — its native MCP
  client, sub-agents, browser and Claude-plugin skills discovery cover the
  retired pi packages). Verify with `python3 platform/installers/agents.py` and
  `platform/setup.py --plan`. Never install it by hand on a machine — that is the
  drift ADR-0011 exists to stop.
- **A cross-agent instruction/rule** → `~/.agents/AGENTS.md` (the machine's
  shared source), never `~/.claude/CLAUDE.md`.
- **A fourth agent** → subclass `Agent` in `agents.py` (`id`, `binary`,
  `install`, `project`, `plan`) and add its id to the entries it should receive.
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
- **The `~/.claude/CLAUDE.md` shell** — Claude-only lines plus the
  `@~/.agents/AGENTS.md` import. Anything another agent would also want goes in
  `~/.agents/AGENTS.md`; nothing mechanically enforces this, which is why
  ADR-0011 makes it a standing rule.
- **Agent config files** (`~/.claude/settings.json`, `~/.codex/config.toml`,
  `~/.omp/agent/config.yml` + `~/.omp/agent/mcp.json`) — all three are rewritten
  by the agents at runtime. Never manage them with Home Manager and never patch
  them from `platform/`; project capabilities through the agents' own CLIs (or
  omp's native MCP file) instead.
- **Legacy ADRs 0001–0006** — describe the retired Python pipeline; ADR-0007
  governs. Don't cite them as current design.

## Hard rules

- Cite `file:line` for claims about structure/conventions.
- No test framework: verify with `./bootstrap.sh --dry-run --verbose`, `nix
  flake check`, and container runs (Debian/Ubuntu/NixOS — see RFC-0001).
- Keep the two layers separate: declarative intent in `home/`, imperative
  remainder in `platform/`.
