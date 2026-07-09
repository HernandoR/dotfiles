{ ... }:
{
  # Faithfully carry the existing theme: read the hand-written starship.toml and
  # let Home Manager write it back. Edit home/starship.toml to change the prompt.
  programs.starship = {
    enable = true;
    enableZshIntegration = true;
    settings = builtins.fromTOML (builtins.readFile ./starship.toml);
  };
}
