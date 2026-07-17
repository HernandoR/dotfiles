{ pkgs, lib, ... }:
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

      # pnpm: mise installs npm-backed tools (home/mise.nix) with pnpm rather
      # than npm, and mise requires the chosen package manager to already be on
      # PATH — so provide it here (present before setup.py runs `mise install`).
      # nixpkgs pnpm is 11.x (>= 10.4.0, needed for pnpm's --allow-build).
      pnpm

      # Python: uv manages Python distributions and runs the platform/ post-HM
      # setup scripts via `uv run`. No nix-provided python3 — uv owns the
      # interpreter (ADR-0007).
      uv

      # Fonts
      nerd-fonts.fira-code
    ]
    ++ lib.optionals stdenv.isLinux [
      xclip # tmux copy/paste bindings on Linux
    ];
}
