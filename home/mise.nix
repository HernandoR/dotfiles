{ ... }:
{
  # Runtimes: mise manages node + rust (uv still handles Python, out of band).
  # Tools are declared globally and auto-installed on first use, so switching
  # does not block on a network download.
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
      };
    };
  };
}
