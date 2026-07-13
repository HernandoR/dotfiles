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
      };
      tools = {
        node = "lts";
        rust = "stable";
        # Smithery MCP CLI — called directly by the post-login setup (no npx).
        "npm:@smithery/cli" = "latest";
      };
    };
  };
}
