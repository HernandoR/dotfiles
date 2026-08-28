{
  pkgs,
  lib,
  ...
}:
let
  toml = pkgs.formats.toml { };

  # Global tool list. This is the SEED for ~/.config/mise/config.toml (see the
  # envLinks entry below), not a live store link — mise owns that file at
  # runtime, so `mise use -g`, `mise up --bump` and `mise unuse` all work and
  # persist. The cost, accepted knowingly (ADR-0009 update log 2026-08-07): a
  # tool added here reaches a host that has already bootstrapped only when
  # someone runs `mise use -g <tool>@<version>` there.
  tools = {
    aws-cli = "latest";
    go = "latest";
    just = "latest";
    node = "lts";
    # Lark CLI — installed via `npx @larksuite/cli@latest install` in the
    # post-login Claude setup, but kept available as a global npm tool here
    # so the runtime is present once mise has materialized node.
    "npm:@larksuite/cli" = "latest";
    # Smithery MCP CLI — called directly by the post-login setup (no npx).
    # pnpm blocks dependency lifecycle scripts by default; smithery ships a
    # `postinstall`, so approve exactly that package. mise passes each entry
    # to `pnpm add --global` as `--allow-build=<pkg>` (needs pnpm >= 10.4.0;
    # the nixpkgs pnpm is 11.x). No other package's install scripts run.
    "npm:@smithery/cli" = {
      version = "latest";
      allow_builds = [ "@smithery/cli" ];
    };
    pre-commit = "latest";
    rust = "stable";
    worktrunk = "latest";
  }
  # The docker CLI is only the client half; the daemon is a Linux-only
  # opt-in system component (`--system docker`, see
  # platform/installers/components.py). On macOS this repo never installs a
  # daemon, so shipping the client would be dead weight.
  // lib.optionalAttrs pkgs.stdenv.isLinux {
    docker-cli = "latest";
  };
in
{
  # Runtimes: mise manages node + rust (uv still handles Python, out of band).
  #
  # The global config is SPLIT across mise's two global files, because the two
  # halves want opposite ownership (ADR-0009 tiers):
  #
  #   ~/.config/mise/conf.d/zz-dotfiles.toml  settings  — Tier A, read-only store
  #                                                       link, flows on every switch
  #   ~/.config/mise/config.toml              tools     — Tier B, seeded once, then
  #                                                       mise's own file
  #
  # `programs.mise.globalConfig` is deliberately NOT set: the HM module writes
  # config.toml only when that option is non-empty (home-manager
  # modules/programs/mise.nix), so leaving it unset hands the file to mise.
  #
  # Tools are declared globally; with the zsh `mise activate` integration, a
  # tool's bin only lands on PATH once it is actually installed, and the lazy
  # "auto-install on first use" only fires for interactive commands. So the whole
  # global config (node, rust, the npm-backed smithery CLI) is materialized
  # eagerly by platform/setup.py (`mise install`).
  programs.mise = {
    enable = true;
    enableZshIntegration = true;
  };

  # Settings, not tools: policy about HOW mise installs, which no one wants to
  # change per-machine with a `mise` subcommand — so this half stays declarative.
  #
  # It lives in conf.d rather than config.toml because conf.d always OVERRIDES
  # config.toml (mise says so itself: "X is defined in conf.d/… which overrides
  # the global config"), which is what we want for settings and exactly what we
  # do not want for tools. Named `zz-` on purpose: within conf.d the
  # lexically FIRST file wins (measured), so any host-local conf.d file a user
  # drops in still beats this one.
  xdg.configFile."mise/conf.d/zz-dotfiles.toml".source = toml.generate "mise-dotfiles-conf" {
    settings = {
      experimental = true;
      # Install npm-backed tools with pnpm instead of npm. mise does NOT
      # auto-install the chosen package manager — it must already be on PATH —
      # so pnpm is provided from nixpkgs (see home/packages.nix), which lands
      # before setup.py runs `mise install`. pnpm's per-package build-script
      # approval (allow_builds, above) lets us permit only smithery's
      # postinstall instead of blanket-running every dependency's scripts.
      npm.package_manager = "pnpm";
    };
  };

  # The mutable half. A Tier B entry (home/env-links.nix) rather than a store
  # link, so that:
  #   - mise can rewrite it (`mise use -g`) — the whole point of this split;
  #   - the versions it then holds survive container recreation, since the real
  #     file lives under envLinks.stateRoot;
  #   - a fresh machine still starts from the reviewed tool list above, because
  #     `seedSource` is applied on creation only.
  # Unlike Claude Code, mise rewrites this file IN PLACE rather than renaming a
  # temp file over it — measured: `mise use -g` and `mise unuse` both leave the
  # inode and both link hops intact and land in stateRoot. So persistence here is
  # continuous, and env-links' regular-file repair never has to fire for it.
  envLinks.entries.".config/mise/config.toml" = {
    kind = "file";
    mode = "644";
    seedSource = toml.generate "mise-tools-seed" { inherit tools; };
  };
}
