# lzhen's dotfiles

Cross-platform dotfiles with a Python-based bootstrap. A thin POSIX shell
entrypoint hands off to [`uv`](https://docs.astral.sh/uv/), which runs the
real installer (`main.py`). The installer detects your OS, installs core
packages, sets up Oh My Zsh + Starship, links the dotfiles into `$HOME`, and
optionally installs extra components from a registry.

> **Warning:** These are my personal settings. Fork the repo and review the
> code before running it — don't blindly apply someone else's configuration.

## Quick start

```bash
git clone git@github.com:HernandoR/dotfiles.git
cd dotfiles
./bootstrap.sh
```

`bootstrap.sh` requires `curl`. It installs `uv` if it isn't already present,
then runs `uv run main.py` and forwards any extra arguments to it. So anything
documented below for `main.py` can be passed straight through:

```bash
./bootstrap.sh --dry-run --verbose
```

## What the bootstrap does

Running with no sub-command (`./bootstrap.sh` or `uv run main.py`) performs a
full bootstrap:

1. **Detect OS** — `darwin`, `debian`/`ubuntu`, or `unknown` (read from
   `platform.system()` and `/etc/os-release`).
2. **Install core packages**
   - **macOS:** installs Homebrew (from the BFSU mirror) and `git`, `zsh`,
     `rsync`, `rclone`.
   - **Debian/Ubuntu:** `apt update`, ensures `curl` is present, then installs
     `git`, `zsh`, `rsync`, `aptitude`, `wget`.
3. **Configure the shell** — installs Oh My Zsh (falling back to a Gitee
   mirror when GitHub is unreachable), Antigen, the `zsh-autosuggestions` and
   `zsh-syntax-highlighting` plugins, and the Starship prompt.
4. **Restore + link dotfiles** — rsyncs the tracked files from `sources/root`
   into `~/dotfiles`, then symlinks them into `$HOME`.
5. **Run optional components** — anything you requested via
   `--optional-components` (see below).

### Flags

| Flag                           | Effect                                                          |
| ------------------------------ | --------------------------------------------------------------- |
| `--dry-run`                    | Print every command without executing it.                       |
| `--verbose`                    | Enable debug logging (and `rsync -P` progress).                 |
| `--interactive`                | Allow interactive prompts during install (Oh My Zsh, Starship). |
| `--optional-components <list>` | Comma-separated optional components / alias groups.             |

## Sub-commands

`main.py` also exposes targeted commands for managing dotfiles without a full
bootstrap:

```bash
./bootstrap.sh backup        # rsync $HOME/dotfiles back into sources/root
./bootstrap.sh restore       # restore sources/root into $HOME/dotfiles and re-link
./bootstrap.sh set-proxy     # set git http/https proxy from $http_proxy / $https_proxy
./bootstrap.sh unset-proxy   # clear the git proxy config
```

If you want to repoint the current user's home directory on Linux, use `edit_home.sh`:

```bash
sudo ./edit_home.sh /path/to/new/home
sudo DOTFILE_EDIT_HOME_TARGET=/path/to/new/home ./edit_home.sh
```

## Optional components

Optional components live in a self-registering registry
(`installers/components.py`). Each is selected by name, or by an **alias
group** (currently `all`). Select them in two ways — the CLI flag wins over the
environment variable:

```bash
# via flag
./bootstrap.sh --optional-components docker,claude

# via env var
DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS=all ./bootstrap.sh
```

Unknown names are logged and skipped. Components only run on their supported
OS; non-applicable ones are skipped automatically.

| Name              | Description                               | OS             |
| ----------------- | ----------------------------------------- | -------------- |
| `1password`       | 1Password                                 | debian, ubuntu |
| `docker`          | Docker                                    | debian, ubuntu |
| `docker-rootless` | Docker (rootless)                         | all            |
| `cmdl-tools`      | command-line tools (deadsnakes PPA, etc.) | debian, ubuntu |
| `cuda`            | CUDA Toolkit 12.6                         | debian, ubuntu |
| `llvm`            | LLVM 18 (+ `update-alternatives`)         | debian, ubuntu |
| `mac-brew`        | Homebrew formulae & casks                 | darwin         |
| `claude`          | Claude Code CLI                           | all            |

To list everything available at any time:

```bash
uv run -m installers.components
```

## Repository layout

```
bootstrap.sh             POSIX entrypoint — installs uv, runs main.py
main.py                  DotfilesManager: OS detection, core install, dotfile linking, sub-commands
installers/
  components.py          OptionalComponent registry (--optional-components)
  debian.py              Debian/Ubuntu installers (1Password, Docker, CUDA, LLVM, …)
  macos.py               macOS bootstrap (Homebrew + formulae/casks)
sources/
  root/                  the actual dotfiles, rsynced into $HOME
  .file_list             files rsync includes
  .ex_list               patterns rsync excludes
  zsh_plugins/           zsh plugin configs copied into Oh My Zsh custom/
  install/, templates/   supporting assets
init/                    editor/terminal preferences (Sublime, iTerm, etc.)
```

## Notes

- Requires Python ≥ 3.9; `uv` manages the interpreter and (currently empty)
  dependency set, so no manual `pip install` is needed.
- Several downloads default to Chinese mirrors (BFSU for Homebrew, Gitee for
  Oh My Zsh when GitHub is unreachable) for faster installs in CN networks.
- Run the installer from inside the cloned `dotfiles` directory — it expects
  the `sources/` directory to be present.
