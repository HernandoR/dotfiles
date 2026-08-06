{ pkgs, lib, inputs, ... }:
{
  home.packages =
    with pkgs;
    [
      # GNU userland first so `ls --color=auto` / `sed` / `grep` behave the same
      # on macOS as on Linux.
      coreutils
      findutils
      gnused
      gnugrep

      # CLI toolset (replaces the old optional components + brew formulae).
      ripgrep
      jq
      fd
      tree
      wget
      rsync
      bottom
      gh
      jujutsu
      difftastic # provides `difft`, the git external differ
      fzf
      tmux
      vim
      git-lfs
      mergiraf # syntax-aware git merge driver (see git.nix)
      zellij
      _1password-cli # `op`
      skopeo # inspect/copy container images without a daemon

      # omp (oh-my-pi) — the ADR-0011 third agent (see platform/installers/agents.py).
      # The *binary* is declarative, from the llm-agents-nix flake input
      # (flake.nix); its *config* deliberately is not: ~/.omp is an ADR-0009
      # Tier-B out-of-store staging link (home/env-links.nix), the shared-source
      # links and MCP merge are projected by OmpAgent at bootstrap, and any
      # future plugins go through `omp install` — never through a generated
      # config file. Available on every host this repo targets
      # (aarch64-darwin, x86_64-linux, aarch64-linux).
      inputs.llm-agents-nix.packages.${pkgs.system}.omp

      # pnpm: mise installs npm-backed tools (home/mise.nix) with pnpm rather
      # than npm, and mise requires the chosen package manager to already be on
      # PATH — so provide it here (present before setup.py runs `mise install`).
      # nixpkgs pnpm is 11.x (>= 10.4.0, needed for pnpm's --allow-build).
      pnpm

      # Python: uv manages Python distributions and runs the platform/ post-HM
      # setup scripts via `uv run`. No nix-provided python3 — uv owns the
      # interpreter (ADR-0007).
      uv

      # Fonts. `nerd-fonts.fira-code` ships all three FiraCode families
      # (FiraCodeNerdFont / …NerdFontMono / …NerdFontPropo); `fira-mono` is the
      # separate ligature-free Fira Mono typeface, patched the same way.
      nerd-fonts.fira-code
      nerd-fonts.fira-mono

      # getnf — Nerd Fonts installer CLI, for pulling an extra font ad hoc
      # without a rebuild. Packaged locally (not in nixpkgs); see pkgs/getnf.nix.
      (callPackage ./pkgs/getnf.nix { })
    ]
    ++ lib.optionals stdenv.isLinux [
      xclip # tmux copy/paste bindings on Linux
    ];

  # Standalone HM defaults this to false, which means fonts installed above are
  # in the profile but invisible to fontconfig — `fc-list` and every Linux
  # terminal would miss FiraCode Nerd Font. Enabling it generates the
  # fontconfig.d snippets that point at the profile's share/fonts and refreshes
  # the cache on activation. (Darwin needs no flag: HM's darwin fonts module
  # rsyncs profile fonts into ~/Library/Fonts/HomeManager, since macOS ignores
  # symlinked fonts.)
  fonts.fontconfig.enable = true;
}
