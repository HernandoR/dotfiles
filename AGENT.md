# CLAUDE.md

## Project

Cross-platform **dotfiles installer** written in **Python ≥ 3.9** (`pyproject.toml:6`). A thin POSIX shell entrypoint (`bootstrap.sh`) installs [`uv`](https://docs.astral.sh/uv/) if missing, then hands off to `main.py` (`bootstrap.sh:23`). `main.py` detects the OS, installs core packages, configures Oh My Zsh + Starship, rsyncs/symlinks tracked dotfiles into `$HOME`, and runs optional components selected from a self-registering registry. The actual shell config files being deployed live under `sources/root/`. Targets macOS and Debian/Ubuntu; several downloads default to Chinese mirrors (BFSU/Gitee) for CN-network speed.

## Layout

```

bootstrap.sh POSIX entrypoint: ensures uv, runs `uv run main.py "$@"`
main.py DotfilesManager — OS detection, core install, dotfile link, sub-commands
install_llvm.py Standalone PEP-723 script (uv run) wrapping installers.debian.install_llvm
pyproject.toml Project metadata; dependencies = [] (no third-party deps)
installers/
**init**.py Empty — marks the package
components.py OptionalComponent registry (--optional-components)
debian.py Debian/Ubuntu installers (1Password, Docker, CUDA, LLVM, …)
macos.py macOS bootstrap (Homebrew + formulae/casks)
sources/
root/ The real dotfiles, staged into $HOME (.zshrc, .vimrc, .p10k.zsh, …)
.ex_list rsync --exclude-from pattern list (cache/lock/swap noise)
zsh_plugins/ zsh plugin configs copied into ~/.oh-my-zsh/custom/plugins
install/ standalone helper shell scripts (app installers)
templates/ (empty at scan time)
unusing/ retired/unused config
init/ Editor/terminal preferences (Sublime, iTerm colors, spectacle)
agc/ Notes (e.g. bash-circular-reference-fix.md)

```

## Commands

There is **no Makefile, justfile, or npm scripts**, and **no test framework** (no tests directory, no pytest config). All entry is via `uv`:

```bash
./bootstrap.sh                              # full bootstrap (installs uv, runs main.py)
./bootstrap.sh --dry-run --verbose          # args pass straight through to main.py
uv run main.py                              # full bootstrap directly
uv run main.py --interactive                # allow interactive prompts (OMZ, Starship)
uv run main.py --optional-components docker,claude
DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS=all uv run main.py   # env var (CLI flag wins, main.py:388-390)

uv run main.py set-proxy     # git proxy from $http_proxy / $https_proxy
uv run main.py unset-proxy   # clear git proxy

uv run -m installers.components             # list all optional components (components.py:186)
uv run install_llvm.py --version 19         # standalone LLVM installer (PEP-723 script)
```

Lint: no project-level lint config exists. `sources/root/ruff.toml` is a _deployed dotfile_, not this repo's config — do not treat it as the project linter.

## Conventions

- **Language:** Python ≥ 3.9 (`pyproject.toml:6`); `install_llvm.py` declares its own `requires-python = ">=3.10"` in a PEP-723 inline block (`install_llvm.py:2-4`).
- **No third-party dependencies** — `dependencies = []` (`pyproject.toml:7`); standard library only (`subprocess`, `pathlib`, `argparse`, `logging`, `shutil`, `tempfile`, `urllib.request`).
- **Command execution goes through a `run_cmd` callable.** `DotfilesManager.run_command` (`main.py:52`) is the canonical runner; it strips a leading `sudo` when running as root (`main.py:53-60`), logs every command, honors `--dry-run` by returning a fake `CompletedProcess` (`main.py:63-67`), and `sys.exit(1)` on failure when `check=True` (`main.py:78-79`). Installer functions in `installers/` receive this as a `run_cmd` parameter rather than importing it (e.g. `debian.py:5`, `macos.py:1`), keeping them decoupled and dry-run-aware.
- **Prefer argument-list commands over `shell=True`.** Lists are the norm (`main.py:84`, `main.py:104`). Use `shell=True` only for genuine pipelines/redirects/globs (`debian.py:17`, `macos.py:113`).
- **Download-then-execute, never `curl | bash`.** Remote install scripts are downloaded to a temp/known file, then run as a separate command, so a download failure actually stops the install (`main.py:281-288` Starship; `components.py:187-194` Claude). A piped `curl ... | bash` masks curl's exit code — do not reintroduce it. (Note: `debian.py:17,28` and `macos.py:121` still use the piped form — follow the temp-file pattern for new code.)
- **Logging, not print, in `main.py`/`components.py`:** module logger `logging.getLogger("dotfiles")` (`main.py:21`, `components.py:22`). Installer modules in `installers/debian.py` / `macos.py` use `print()` for sub-step progress (`debian.py:53`, `macos.py:24`) — match the surrounding file.
- **Paths:** use `pathlib.Path` (`main.py:9`, `components.py` temp handling). `Path.home()` for `$HOME`.
- **Naming:** modules/functions `snake_case`; component classes `PascalCase` with lowercase string `name` attributes (`components.py:104-106`).
- **OS identifiers** are the strings `"darwin"`, `"debian"`, `"ubuntu"` (`main.py:37-50`, used in `supported_os` tuples).
- **Commit messages:** repo convention is Conventional-Commits `type(scope): subject` (see git log, e.g. `feat(installers): …`). `.copilot-commit-message-instructions.md` asks Copilot for _Chinese_ commit messages with ≤72-char lines — that instruction is for the Copilot integration; existing git history is English. Match recent history unless told otherwise.

## Canonical examples per layer

| If you're adding…               | Read first → mirror                                          | Why                                                                                                         |
| ------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| An optional install component   | `installers/components.py:114-122` (`Docker`)                | Smallest complete `OptionalComponent` subclass: `name`, `description`, `supported_os`, `groups`, `install`. |
| A Debian/Ubuntu install routine | `installers/debian.py:16-24` (`install_docker`)              | Takes `run_cmd`, mixes list + `shell=True` commands, cleans up temp files.                                  |
| A macOS install routine         | `installers/macos.py:65-138` (`install_mac_brew`)            | brew update/upgrade, formulae + casks loops, cleanup.                                                       |
| A `main.py` manager method      | `main.py:279-288` (`install_starship`)                       | Temp-file download-then-run + dry-run-safe via `run_command`.                                               |
| A new CLI sub-command           | `main.py` `subparsers.add_parser` + `args.command` dispatch  | Subparser registration + `args.command` dispatch block.                                                     |
| A standalone one-off script     | `install_llvm.py:1-11`                                       | PEP-723 header, local `run_cmd`, reuses an `installers/` function.                                          |
| A new dotfile to deploy         | add to `sources/root/` only                                  | `stage_dotfiles` rsyncs everything in `sources/root/` (minus `.ex_list`) on bootstrap.                     |

## Don't touch / be careful with

- **`/output`** — generated at runtime, git-ignored (`.gitignore:1`). Holds downloaded installer scripts.
- **`.venv/`, `__pycache__/`, `*.egg-info/`** — git-ignored build/runtime artifacts (`.gitignore`).
- **`uv.lock`** — listed under `.gitignore` (last line); don't hand-edit.
- **`sources/root/**`** — these are *deployed verbatim* into the user's `$HOME` via symlink (`main.py:248-277`). Editing them changes the user's live shell config. `sources/root/ruff.toml` is a deployed dotfile, **not** this repo's linter.
- **`sources/unusing/`** — retired config; don't wire it back in without intent.
- **Mirror URLs** — Homebrew via BFSU (`macos.py:17-21,38-44`) and Oh My Zsh Gitee fallback (`main.py:152`) are deliberate for CN networks; don't "fix" them to upstream blindly.
- **`run_command` exits the process on failure** (`main.py:78`). Don't rely on a return value after a `check=True` call that may fail — control won't return.

## Adding a new X — recipes

### 1. New optional component

1. In `installers/components.py`, add a subclass of `OptionalComponent` (`components.py:25`). Set `name` (CLI id), `description`, `supported_os` (tuple of OS strings or `None` for all — `components.py:35`), and `groups` (e.g. `frozenset({"all"})`). Defining the class auto-registers it via `__init_subclass__` (`components.py:38-41`).
2. Implement `install(self, manager)` and delegate to a function in `installers/debian.py` or `installers/macos.py`, passing `manager.run_command` (pattern: `components.py:120-121`).
3. The CLI choices and `--optional-components` help update automatically from the registry (`main.py:357-368`). Verify with `uv run -m installers.components`.

### 2. New install routine in an installer module

1. Add a function `def install_foo(run_cmd):` to `installers/debian.py` or `macos.py`. Accept `run_cmd` — never import a runner.
2. Prefer list commands; use `shell=True` only for pipes/redirects. For remote scripts, download to a temp/`Path` then execute separately (see `main.py:281-288`), not `curl | bash`.
3. Clean up any temp files you create (`debian.py:12-13`).
4. Wire it to a component (recipe 1) or a `main.py` method.

### 3. New dotfile delivered to `$HOME`

1. Put the file under `sources/root/` preserving its `$HOME`-relative path.
2. Optionally add ignore patterns to `sources/.ex_list` if the file/dir produces runtime noise (cache, lock, swap).
3. On the next bootstrap, `stage_dotfiles` rsyncs it into the staging dir and `link_dotfiles` symlinks it into `$HOME`.

## Hard rules

- Cite `file:line` for any claim about conventions or structure (done above).
- **No test framework is configured** — there are no tests in this repo. Verify changes with `uv run main.py --dry-run --verbose`, which prints every command without executing.
- Keep installer functions runner-agnostic: receive `run_cmd`, honor dry-run by routing through it.
- Don't reintroduce `curl | bash`; download then execute.
