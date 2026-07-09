{
  description = "lz's dotfiles — standalone Home Manager on Lix (see docs/plans/adr-0007)";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self, nixpkgs, home-manager, ... }@inputs:
    let
      # One entry per machine. `system` selects the platform; `username` and the
      # derived home directory are set in home/default.nix. Add hosts here.
      hosts = {
        "LiuzhendeMacBook-Pro" = {
          system = "aarch64-darwin";
          username = "lz";
        };
        # Generic x86_64 Linux host (real servers / x86 boxes / amd64 containers).
        "dotfiles-debian" = {
          system = "x86_64-linux";
          username = "lz";
        };
        # aarch64 Linux host — Apple-silicon OrbStack containers and ARM servers.
        "dotfiles-linux-arm" = {
          system = "aarch64-linux";
          username = "lz";
        };
      };

      mkHome =
        hostName:
        { system, username, extraModules ? [ ] }:
        home-manager.lib.homeManagerConfiguration {
          # Instantiate here (not legacyPackages) so allowUnfree applies — the
          # 1Password CLI is unfree. HM's own nixpkgs.config is ignored when a
          # pre-built pkgs is passed in.
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          extraSpecialArgs = { inherit inputs hostName username system; };
          modules = [ ./home ] ++ extraModules;
        };
    in
    {
      homeConfigurations = builtins.mapAttrs mkHome hosts;
    };
}
