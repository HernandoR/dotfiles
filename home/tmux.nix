{ ... }:
{
  # Carry the existing k-tmux config verbatim (custom prefix C-a, vi copy mode,
  # vim-aware pane navigation, status line). Edit home/tmux.conf to change it.
  # Note: the copy/paste bindings use xclip on Linux (see packages.nix) and
  # reattach-to-user-namespace on macOS, matching the old behavior.
  programs.tmux = {
    enable = true;
    extraConfig = builtins.readFile ./tmux.conf;
  };
}
