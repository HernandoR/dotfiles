# CLAUDE.md

## Project

Cross-platform **dotfiles installer** written in **Python ≥ 3.9** (`pyproject.toml:6`). A thin POSIX shell entrypoint (`bootstrap.sh`) installs [`uv`](https://docs.astral.sh/uv/) if missing, then hands off to `main.py` (`bootstrap.sh:23`). `main.py` runs four ordered phases: OS bootstrap (core packages), necessary shell tooling (Oh My Zsh → fzf → Starship → Node), dotfiles migration (rsync to a staging dir, then symlink into `$HOME`), and user-selected optional components. The actual shell config files being deployed live under `sources/root/`. Targets macOS and Debian/Ubuntu; several downloads default to Chinese mirrors (BFSU/Gitee) for CN-network speed.

The installer architecture is recorded in ADRs under `docs/plans/`: staging/linking (ADR-0001), the `PackageManager` install abstraction (ADR-0003), necessary-components + phase separation (ADR-0004), the install-driven Claude post-setup that rebuilds `~/.claude` (ADR-0005), and SSH keys deployed by copy (ADR-0006). Read those before reshaping the installer model.

## Layout

```
bootstrap.sh      POSIX entrypoint: ensures uv, runs `uv run main.py "$@"`
main.py           DotfilesManager — OS detection, bootstrap, phase orchestration, sub-commands
pyproject.toml    Project metadata; dependencies = [] (no third-party deps)
installers/
  __init__.py     Empty — marks the package
  managers.py     PackageManager install backends (apt/brew/scripts) + Script/Deb specs (ADR-0003)
  components.py   Component catalog: NecessaryComponent (ordered) + OptionalComponent (registry)
sources/
  root/           The real dotfiles, staged into $HOME (.zshrc, .vimrc, .p10k.zsh, …)
  .ex_list        rsync --exclude-from pattern list (cache/lock/swap noise)
  zsh_plugins/    zsh plugin configs copied into ~/.oh-my-zsh/custom/plugins
  install/        standalone helper shell scripts (app installers)
  unusing/        retired/unused config
docs/plans/       ADRs (decision records for the installer architecture)
init/             Editor/terminal preferences (Sublime, iTerm colors, spectacle)
agc/              Notes (e.g. bash-circular-reference-fix.md)
```

There are **no** `installers/debian.py` / `installers/macos.py` modules — ADR-0003 deleted the per-OS helpers; every component's install logic lives on the component itself in `components.py`.

## Commands

There is **no Makefile, justfile, or npm scripts**, and **no test framework** (no tests directory, no pytest config). All entry is via `uv`:

```bash
./bootstrap.sh                              # full bootstrap (installs uv, runs main.py)
./bootstrap.sh --dry-run --verbose          # args pass straight through to main.py
uv run main.py                              # full bootstrap directly
uv run main.py --interactive                # allow interactive prompts (OMZ, Starship)
uv run main.py --optional-components docker,claude
DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS=all uv run main.py   # env var (CLI flag wins, main.py:378-380)

uv run main.py set-proxy     # git proxy from $http_proxy / $https_proxy
uv run main.py unset-proxy   # clear git proxy

uv run -m installers.components             # list all optional components (components.py:668)
```

Lint: no project-level lint config exists. `sources/root/ruff.toml` is a _deployed dotfile_, not this repo's config — do not treat it as the project linter.

## Architecture: install model (ADR-0003 / ADR-0004)

- **`DotfilesManager` (`main.py`) is the orchestrator and the context object** passed into every install as `ctx`. Components call `ctx.run_command(...)`, `ctx.package_manager(id)` (`main.py:273`), and `ctx.select_manager(installs)` (`main.py:277`). They do **not** receive a bare `run_cmd` callable, and they never import a runner.
- **`PackageManager` backends** (`managers.py:51`) self-register by `id` (`apt` `managers.py:83`, `brew` `managers.py:103`, `scripts` `managers.py:112`), declare `supported_os` and a `priority` (native managers outrank `scripts`, `managers.py:86,106,115`). The orchestrator — not the component — picks the highest-priority applicable backend via `select_manager` (`main.py:277`).
- **A component is declarative-first.** It lists `installs = {manager_id: spec}` and the base `Component.install` (`components.py:73`) resolves it through the chosen backend. Specs: a bare string = package name; `Deb(url)` (`managers.py:37`) for an apt `.deb`; `Script(url, interpreter, args)` (`managers.py:24`) for the `scripts` backend.
- **Multi-step installs override `install(self, ctx)`** and may reuse a backend via `ctx.package_manager("scripts").install(ctx, Script(...))` rather than re-rolling the download-run-cleanup dance.
- **`supported_os` is derived** for declarative components (`effective_supported_os` `components.py:50`, from the managers listed in `installs`); imperative-override components set an explicit `supported_os`.
- **Core OS bootstrap is not a component.** `bootstrap_debian` (`main.py:97`), `bootstrap_macos` (`main.py:144`), `install_homebrew` (`main.py:115`) are prerequisites and stay as `DotfilesManager` methods, outside the component system.

### The two component kinds (`components.py`)

Both subclass a shared `Component` base (`components.py:34`) that carries the install machinery; they differ only in lifecycle:

- **`NecessaryComponent` (`components.py:92`)** — always-run shell tooling. **Not** self-registering: install order is correctness-critical, so the catalog is the explicit ordered tuple `NECESSARY = (OhMyZsh, Fzf, Starship, Node)`, iterated by `run_necessary_components` (`main.py:298`). Per ADR-0004, these install binaries/frameworks only — shell rc files belong to the migration phase, so the repo's `.zshrc` stays canonical. `OhMyZsh` installs with `KEEP_ZSHRC=yes`; `Fzf` uses `--no-update-rc`; `Node` (nvm) runs with `PROFILE=/dev/null` so nvm never edits rc files (the repo `.zshrc` already wires `NVM_DIR`). `Node` is necessary because the Claude post-setup and several optional components assume it.
- **`OptionalComponent` (`components.py:108`)** — user-selected via `--optional-components` / `DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS`. Self-registers by `name` through `__init_subclass__` (`components.py:120`) into `_registry` (`components.py:116`); `resolve()` (`components.py:142`) maps a comma list (names + alias groups like `all`) to an ordered name list.

### The four phases (`main.py:315` `run()`)

1. `bootstrap_macos()` / `bootstrap_debian()` — OS prerequisites.
2. `run_necessary_components()` (`main.py:298`) — the `NECESSARY` tuple, in order.
3. `migrate_dotfiles()` (`main.py:303`) — `stage_dotfiles` then `link_dotfiles` (ADR-0001). Runs **after** the tools so the repo's rc files win. Both calls exclude `CLAUDE_MANAGED_PATHS` (`.claude`, `.claude.json`) — not deployed from staging; the `claude` component rebuilds `~/.claude` fresh via an install-driven post-setup (ADR-0005) — and `.ssh`, whose keys are *copied* (not symlinked) by `deploy_ssh_keys` (ADR-0006).
4. `set_default_shell()` — make zsh the login shell (idempotent, non-fatal: `chsh` → `usermod` fallback, warns on failure).
5. `run_optional_installers()` (`main.py:294`) — user-selected components.

`run()` ends with an advisory notice to open a new shell — purely informational; no later phase depends on an activated shell.

## Conventions

- **Language:** Python ≥ 3.9 (`pyproject.toml:6`).
- **No third-party dependencies** — `dependencies = []` (`pyproject.toml:7`); standard library only (`subprocess`, `pathlib`, `argparse`, `logging`, `shutil`, `tempfile`, `os`, `sys`).
- **Command execution goes through `DotfilesManager.run_command`** (`main.py:57`): it strips a leading `sudo` when running as root (`main.py:59-65`), logs every command, overlays an optional `env` dict onto the inherited environment (`main.py:67`), honors `--dry-run` by returning a fake `CompletedProcess` (`main.py:68-72`), and `sys.exit(1)` on failure when `check=True` (`main.py:83-84`). Components reach it as `ctx.run_command`.
- **Prefer argument-list commands over `shell=True`.** Lists are the norm; use `shell=True` only for genuine pipelines/redirects/globs (`components.py` `Cuda.install`). To set an env var, pass `env={...}` to `run_command` (`main.py:57`) rather than embedding `VAR=val` in a shell string.
- **Download-then-execute, never `curl | bash`.** The `scripts` backend (`managers.py:117`) downloads a URL to a temp file then runs `<interpreter> <file> <args>`, so a download failure actually stops the install. Reuse it; do not reintroduce a piped `curl ... | bash`.
- **Logging, not print, in installer code:** module logger `logging.getLogger("dotfiles")` (`main.py:21`, `components.py:31`, `managers.py:18`). (`components.py:668` `main()` prints the component catalog — that's a CLI listing, not install code.)
- **Paths:** use `pathlib.Path`; `Path.home()` for `$HOME`.
- **Naming:** modules/functions `snake_case`; component classes `PascalCase`. Optional components carry a lowercase `name` (the CLI id); necessary components leave `name` empty and rely on `description`.
- **OS identifiers** are the strings `"darwin"`, `"debian"`, `"ubuntu"` (`main.py:_detect_os`), used in `supported_os` tuples and manager `supported_os`.
- **Commit messages:** repo convention is Conventional-Commits `type(scope): subject` (see git log, e.g. `feat(installers): …`). `.copilot-commit-message-instructions.md` asks Copilot for _Chinese_ commit messages with ≤72-char lines — that instruction is for the Copilot integration; existing git history is English. Match recent history unless told otherwise.

## Canonical examples per layer

| If you're adding…                       | Read first → mirror                                   | Why                                                                       |
| --------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------- |
| A simple optional component             | `components.py:419` (`FdFind`) / `:404` (`Bottom`)    | Pure declarative `installs = {manager_id: spec}`; no per-component code.   |
| A multi-step optional component         | `components.py:180` (`Docker`) / `:426` (`Node`)      | Imperative `install(ctx)` reusing `ctx.package_manager(...)` + extra steps. |
| A necessary (always-run) component      | `components.py:645` (`Starship`)                      | `NecessaryComponent` reusing the `scripts` backend; add it to `NECESSARY`. |
| A new install backend                   | `managers.py:83` (`AptManager`)                       | Self-registering `PackageManager`: `id`, `supported_os`, `priority`, `install`. |
| A `main.py` manager method              | `main.py:166` (`stage_dotfiles`)                      | dry-run-safe via `run_command`; filesystem op, not a component.            |
| A new CLI sub-command                   | `main.py:370-373` + `main.py:391` dispatch            | Subparser registration + `args.command` dispatch block.                    |
| A new dotfile to deploy                 | add to `sources/root/` only                           | `stage_dotfiles` rsyncs everything in `sources/root/` (minus `.ex_list`).  |

## Don't touch / be careful with

- **`/output`** — generated at runtime, git-ignored (`.gitignore:1`). Holds downloaded installer scripts.
- **`.venv/`, `__pycache__/`, `*.egg-info/`** — git-ignored build/runtime artifacts (`.gitignore`).
- **`uv.lock`** — listed under `.gitignore` (last line); don't hand-edit.
- **`sources/root/**`** — these are *deployed verbatim* into the user's `$HOME` via symlink (`link_dotfiles` `main.py:201`). Editing them changes the user's live shell config. `sources/root/ruff.toml` is a deployed dotfile, **not** this repo's linter.
- **rc-file ownership (ADR-0004)** — necessary components must not write `~/.zshrc` (or other rc files); the repo's linked `.zshrc` is canonical. Keep `KEEP_ZSHRC=yes` / `--no-update-rc` on omz/fzf.
- **`sources/unusing/`** — retired config; don't wire it back in without intent.
- **Mirror URLs** — Homebrew via BFSU (`install_homebrew` `main.py:115`) and Oh My Zsh / fzf Gitee fallbacks (`components.py` `OhMyZsh`/`Fzf`) are deliberate for CN networks; don't "fix" them to upstream blindly.
- **`run_command` exits the process on failure** (`main.py:83-84`). Don't rely on a return value after a `check=True` call that may fail — control won't return.

## Adding a new X — recipes

### 1. New optional component

1. In `installers/components.py`, add a subclass of `OptionalComponent`. Set `name` (CLI id), `description`, and `groups` (e.g. `frozenset({"all"})`). Defining the class auto-registers it via `__init_subclass__` (`components.py:120`).
2. **Declarative (preferred):** set `installs = {"apt": "pkg", "brew": "pkg"}` (or `Deb(url)` / `Script(...)`). `supported_os` is derived; no `install()` needed.
3. **Multi-step:** override `install(self, ctx)`, set an explicit `supported_os`, and reuse a backend via `ctx.package_manager("scripts").install(ctx, Script(...))`. Mirror `Docker` (`components.py:186`) or `Node` (`components.py:435`).
4. CLI choices and `--optional-components` help update automatically from the registry (`main.py:357`). Verify with `uv run -m installers.components`.

### 2. New necessary component

1. Add an `NecessaryComponent` subclass with a `description` and an `install(self, ctx)` (or declarative `installs`).
2. Append it to the `NECESSARY` tuple (`components.py:665`) at the correct position — order is correctness-critical and this tuple is the single source of truth.
3. It must not write shell rc files (ADR-0004). Pass the installer's keep-rc flag (e.g. `KEEP_ZSHRC=yes` via `run_command(env=...)`, `--no-update-rc`).

### 3. New install backend

1. Add a `PackageManager` subclass to `installers/managers.py`: set `id`, `supported_os` (or `None`), `priority`, and implement `install(self, ctx, spec)`. Defining the class registers it.
2. Define/validate its own spec type if a bare string isn't enough (cf. `Deb`, `Script`).

### 4. New dotfile delivered to `$HOME`

1. Put the file under `sources/root/` preserving its `$HOME`-relative path.
2. Optionally add ignore patterns to `sources/.ex_list` if the file/dir produces runtime noise (cache, lock, swap).
3. On the next bootstrap, `stage_dotfiles` rsyncs it into the staging dir and `link_dotfiles` symlinks it into `$HOME` (skipping pre-existing real files).

## Hard rules

- Cite `file:line` for any claim about conventions or structure (done above).
- **No test framework is configured** — there are no tests in this repo. Verify changes with `uv run main.py --dry-run --verbose`, which prints every command without executing.
- Components are runner-agnostic: take `ctx`, route every command through `ctx.run_command`, honor dry-run.
- Don't reintroduce `curl | bash`; reuse the `scripts` backend (download then execute).
- The orchestrator picks the backend; a component never chooses its own (ADR-0003).
