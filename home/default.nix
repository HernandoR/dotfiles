{ pkgs, lib, username, homeDirectory ? null, ... }:
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
  # Honor an explicit homeDirectory (the impure `generic` host passes $HOME so it
  # works for root or any user); otherwise derive it from the platform.
  home.homeDirectory =
    if homeDirectory != null && homeDirectory != "" then
      homeDirectory
    else if pkgs.stdenv.isDarwin then
      "/Users/${username}"
    else
      "/home/${username}";

  # Pin to the release this config was first built against; do not bump casually.
  home.stateVersion = "25.05";

  programs.home-manager.enable = true;
}
