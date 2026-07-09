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

      # Fonts
      nerd-fonts.fira-code
    ]
    ++ lib.optionals stdenv.isLinux [
      xclip # tmux copy/paste bindings on Linux
    ];
}
