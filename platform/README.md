# platform/ — the imperative layer

Home Manager (the `flake.nix` + `home/`) owns the **user** environment
declaratively. This directory is the thin **imperative** layer for what Home
Manager cannot do on a non-NixOS host (ADR-0007): install nix, configure
mirrors, invoke Home Manager, apply an external symlink map, set the login
shell, and install Linux system-level software.

## Entry point

```bash
./bootstrap.sh                     # auto-detect host; full bootstrap
./platform/bootstrap.sh --dry-run  # print every action without executing
./platform/bootstrap.sh --yes      # skip the clearance prompt (CI-style run)
./platform/bootstrap.sh --network CN            # enable China mirrors
./platform/bootstrap.sh --host dotfiles-debian  # pick a flake host explicitly
./platform/bootstrap.sh --system docker,cuda    # + Linux system components
```

## Plan + clearance (ADR-0010)

On an interactive terminal nothing is touched until the whole plan has been
printed and cleared **once** — installs, the network/mirrors in use, the config
files written and the symlinks placed, with `[privileged]` on the steps that use
root/sudo, and a final highlighted section listing every existing file that gets
moved aside (`*.backup`, `*.pre-dotfiles.bak`). There are deliberately no
per-step prompts.

Each script describes its own steps so the plan cannot drift from the run:

| Producer | Emits |
|---|---|
| `lib.sh` `plan_fact`/`plan_install`/`plan_config`/`plan_backup` | facts + the pre-HM shell steps (`plan_prereqs`, `plan_nix`) |
| `nix-cn.sh --plan` | `section<TAB>text<TAB>priv` for the network marker + system `nix.conf` |
| `setup.py --plan-items` | the same TSV for the post-HM half (link map incl. its backups, login shell, mise, Claude, system components) |

`bootstrap.sh` merges them with `plan_import_tsv`, prints with `print_plan`, and
calls `require_clearance`. No terminal (CI, container, cron) or `--yes` /
`DF_ASSUME_YES=1` or `--dry-run` → no prompt. A yes exports `DF_ASSUME_YES=1`, so
`setup.py` (which asks for its own clearance when run standalone) does not ask
twice. `setup.py --plan` prints the post-HM half on its own.

`bootstrap.sh` runs, in order: prerequisites → install Lix → configure nix
(flakes; CERNET mirror only when `DOTFILE_NETWORK_ENV=CN`) → `home-manager
switch -b backup` → JSON(C) link map → login shell → Claude post-setup →
optional system components.

## Files

| File | Role |
|---|---|
| `bootstrap.sh` | orchestrator / entry point |
| `lib.sh` | shared helpers (OS/host detection, Lix install, chsh) |
| `nix-cn.sh` | flakes + CN mirror gating (system nix.conf, sudo) + persist `~/.config/dotfiles/network-env` |
| `claude-setup.sh` | Claude Code CLI + deferred OAuth post-login setup (ADR-0005) |
| `system/cuda.sh` | CUDA Toolkit (Debian/Ubuntu, x86_64) |
| `system/docker.sh` | Docker Engine + GPU toolchain |
| `system/nvidia.sh` | NVIDIA driver + container toolkit |
| `system/llvm.sh` | LLVM/Clang + update-alternatives |

## What is NOT here (owned by Home Manager)

Shell (zsh + starship + fzf + fzf-tab), git, tmux, the CLI toolset
(fd/ripgrep/gh/jj/bottom/mergiraf/difftastic/…), language runtimes (mise:
node/rust; uv: python), and all dotfiles. Edit `home/` for those.

## CN mirrors

A single switch — `DOTFILE_NETWORK_ENV=CN` — gates every China mirror. When set:
the CERNET nix substituter is written to the system nix.conf (so the daemon
serves it to all users), and the pypi/uv + rustup mirror vars are exported by the
Home Manager `.zshenv`. When unset, upstream defaults are used everywhere.
