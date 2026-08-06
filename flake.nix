{
  description = "lz's dotfiles — standalone Home Manager on Lix (see docs/plans/adr-0007)";

  # omp (oh-my-pi) comes from numtide/llm-agents.nix as a *binary package*
  # (home/packages.nix). Its flake exposes packages only — no HM module — which
  # is exactly the constraint ADR-0011 wants: the agent's config is never
  # Home-Manager-managed, only its binary is. Their cache carries the daily CI
  # builds, so a switch pulls omp instead of compiling the bun+rust source tree.
  nixConfig = {
    extra-substituters = [ "https://cache.numtide.com" ];
    extra-trusted-public-keys = [ "niks3.numtide.com-1:DTx8wZduET09hRmMtKdQDxNNthLQETkc/yaX7M4qK0g=" ];
  };

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    llm-agents-nix = {
      url = "github:numtide/llm-agents.nix";
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
        { system, username, homeDirectory ? null, extraModules ? [ ] }:
        home-manager.lib.homeManagerConfiguration {
          # Instantiate here (not legacyPackages) so allowUnfree applies — the
          # 1Password CLI is unfree. HM's own nixpkgs.config is ignored when a
          # pre-built pkgs is passed in.
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          extraSpecialArgs = { inherit inputs hostName username system homeDirectory; };
          modules = [ ./home ] ++ extraModules;
        };
    in
    {
      # Named hosts are pure and reproducible. `generic` is an impure fallback
      # for arbitrary users (including root): it reads $USER/$HOME at eval time,
      # so it only materializes under `--impure` and stays invisible to a pure
      # `nix flake check`. platform/bootstrap.sh falls back to it when no named
      # host matches the current machine/user.
      homeConfigurations =
        (builtins.mapAttrs mkHome hosts)
        // (
          let
            u = builtins.getEnv "USER";
            h = builtins.getEnv "HOME";
          in
          nixpkgs.lib.optionalAttrs (u != "" && h != "") {
            generic = mkHome "generic" {
              system = builtins.currentSystem;
              username = u;
              homeDirectory = h;
            };
          }
        );
    };
}
