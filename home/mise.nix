{ ... }:
{
  # Runtimes: mise manages node + rust (uv still handles Python, out of band).
  # Tools are declared globally; with the zsh `mise activate` integration, a
  # tool's bin only lands on PATH once it is actually installed, and the lazy
  # "auto-install on first use" only fires for interactive commands. So the whole
  # global config (node, rust, the npm-backed smithery CLI) is materialized
  # eagerly by platform/setup.py (`mise install`).
  programs.mise = {
    enable = true;
    enableZshIntegration = true;
    globalConfig = {
      settings = {
        experimental = true;
        # Install npm-backed tools with pnpm instead of npm. mise does NOT
        # auto-install the chosen package manager — it must already be on PATH —
        # so pnpm is provided from nixpkgs (see home/packages.nix), which lands
        # before setup.py runs `mise install`. pnpm's per-package build-script
        # approval (allow_builds, below) lets us permit only smithery's
        # postinstall instead of blanket-running every dependency's scripts.
        npm.package_manager = "pnpm";
      };
      tools = {
        node = "lts";
        rust = "stable";
        # Smithery MCP CLI — called directly by the post-login setup (no npx).
        # pnpm blocks dependency lifecycle scripts by default; smithery ships a
        # `postinstall`, so approve exactly that package. mise passes each entry
        # to `pnpm add --global` as `--allow-build=<pkg>` (needs pnpm >= 10.4.0;
        # the nixpkgs pnpm is 11.x). No other package's install scripts run.
        "npm:@smithery/cli" = {
          version = "latest";
          allow_builds = [ "@smithery/cli" ];
        };
      };
    };
  };
}
