# platform/ — the imperative layer

Home Manager (the `flake.nix` + `home/`) owns the **user** environment
declaratively. This directory is the thin **imperative** layer for what Home
Manager cannot do on a non-NixOS host (ADR-0007): install nix, configure
mirrors, invoke Home Manager, set the login shell, deploy secrets, and install
Linux system-level software.

## Entry point

```bash
./bootstrap.sh                     # auto-detect host; full bootstrap
./platform/bootstrap.sh --dry-run  # print every action without executing
./platform/bootstrap.sh --network CN            # enable China mirrors
./platform/bootstrap.sh --host dotfiles-debian  # pick a flake host explicitly
./platform/bootstrap.sh --system docker,cuda    # + Linux system components
```

`bootstrap.sh` runs, in order: prerequisites → install Lix → configure nix
(flakes; CERNET mirror only when `DOTFILE_NETWORK_ENV=CN`) → `home-manager
switch -b backup` → login shell → SSH keys → Claude post-setup → optional
system components.

## Files

| File | Role |
|---|---|
| `bootstrap.sh` | orchestrator / entry point |
| `lib.sh` | shared helpers (OS/host detection, Lix install, chsh) |
| `nix-cn.sh` | flakes + CN mirror gating (system nix.conf, sudo) + persist `~/.config/dotfiles/network-env` |
| `ssh-keys.sh` | deploy SSH keys by copy, strict perms (ADR-0006) |
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
