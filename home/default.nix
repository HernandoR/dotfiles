{ pkgs, lib, username, homeDirectory ? null, ... }:
{
  imports = [
    ./packages.nix
    ./shell.nix
    ./starship.nix
    ./git.nix
    ./tmux.nix
    ./mise.nix
    ./direnv.nix
    # Mutable out-of-store $HOME links (ADR-0009 Tier B): mechanism + the set
    # every environment wants…
    ./env-links.nix
    # …and the per-environment delta. Empty on shared branches; the only file an
    # env branch (e.g. prod/mewtant) edits, so its rebases never conflict.
    ./env-branch.nix
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
