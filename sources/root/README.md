# Dotfiles

Shell configuration managed as a set of single-purpose files sourced in a specific order.

## Sourcing chains

### Bash

```
Login shell:
  .bash_profile
    ├── shopt settings (nocaseglob, histappend, cdspell, autocd, globstar)
    ├── bash completion (Homebrew or /etc/bash_completion)
    ├── tab completions (git, ssh, defaults, killall)
    └── sources .bashrc

Non-login interactive:
  .bashrc (directly)

  .bashrc
    ├── .tools        tool env (cargo, x-cmd, nix)
    ├── .exports      env vars + terminal colors
    ├── .path         all PATH additions
    ├── .bash_prompt  PS1/PS2 prompt rendering
    ├── .aliases      shell aliases
    ├── .functions    shell functions
    ├── .proxy        proxy + Homebrew mirrors
    └── .extra        machine-specific overrides (last)
```

### Zsh

```
All shells:
  .zshenv
    ├── .tools        tool env (cargo, x-cmd, nix)
    ├── .exports      env vars + terminal colors
    └── .path         all PATH additions
    │
    └── [non-interactive? stop here]

Interactive adds:
    ├── .bash_prompt  PS1/PS2 prompt rendering
    ├── .aliases      shell aliases
    ├── .functions    shell functions
    ├── .proxy        proxy + Homebrew mirrors
    └── .extra        machine-specific overrides (last)

  .zshrc
    ├── antigen       plugin manager
    ├── starship      prompt
    ├── iterm2        shell integration
    └── nvm           Node version manager (defines functions)
```

### POSIX sh

```
Login shell:
  .profile
    └── minimal PATH: $HOME/bin, $HOME/.local/bin
```

## File responsibilities

| File | Purpose | Sourced by |
|---|---|---|
| `.tools` | Tool environment (cargo, x-cmd, nix) | `.bashrc`, `.zshenv` |
| `.exports` | Environment variables + terminal colors | `.bashrc`, `.zshenv` |
| `.path` | All PATH additions (single source of truth) | `.bashrc`, `.zshenv` |
| `.bash_prompt` | PS1/PS2 + git prompt function | `.bashrc`, `.zshenv` |
| `.aliases` | Shell aliases | `.bashrc`, `.zshenv` |
| `.functions` | Shell functions | `.bashrc`, `.zshenv` |
| `.proxy` | Proxy + Homebrew mirror config | `.bashrc`, `.zshenv` |
| `.extra` | Machine-specific overrides | `.bashrc`, `.zshenv` |
| `.bash_profile` | Bash login: shopt, completion, tab completions | bash (login) |
| `.bashrc` | Bash: orchestrates sourcing order | `.bash_profile`, bash (non-login) |
| `.zshenv` | Zsh: orchestrates sourcing order | zsh (all invocations) |
| `.zshrc` | Zsh: plugins, theme, NVM | zsh (interactive) |
| `.profile` | POSIX sh: minimal PATH | sh (login) |

## Sourcing order rationale

`.tools` before `.exports`/`.path` — tool env vars must be set before PATH additions that depend on them.

`.exports` before `.path` — terminal colors defined before anything references them.

`.exports` before `.bash_prompt` — `${yellow}`, `${red}`, `${bold}` etc. must be defined before prompt rendering.

`.bash_prompt` before `.aliases`/`.functions` — prompt should be ready before user starts typing.

`.proxy` before `.extra` — proxy config runs before machine-specific overrides.

`.extra` last — allows overriding anything set by previous files.
