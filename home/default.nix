{ pkgs, lib, username, ... }:
{
  imports = [
    ./packages.nix
    ./shell.nix
    ./starship.nix
    ./git.nix
    ./tmux.nix
    ./mise.nix
  ];

  home.username = username;
  home.homeDirectory =
    if pkgs.stdenv.isDarwin then "/Users/${username}" else "/home/${username}";

  # Pin to the release this config was first built against; do not bump casually.
  home.stateVersion = "25.05";

  programs.home-manager.enable = true;
}
