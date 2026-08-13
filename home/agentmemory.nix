# The agentmemory daemon as a user service — ADR-0011's ONE Tier A addition.
#
# ADR-0009's tier rule keeps agent *config* out of Home Manager because all three
# agents rewrite it at runtime and HM can only emit read-only store links. A
# service unit is the opposite case: nothing ever rewrites it, so it is a
# legitimate declarative citizen and belongs here rather than in a hand-rolled
# systemd file or a launchd plist written by platform/setup.py.
#
# The split with the imperative layer, and why it is not a smell:
#
#   HM (here)                     declares the unit — same shape on both OSes
#   platform/setup.py             installs the binary (npm -g) and starts the unit
#
# The HM switch runs BEFORE platform/setup.py, so on a first bootstrap this unit
# exists while `agentmemory` does not yet. That is why the ExecStart is a wrapper
# that exits 0 (rather than failing) when the binary is missing: an absent tool is
# "nothing to do", not a fault to restart-loop over. `agents.start_agentmemory`
# kicks the unit once the install has happened.
#
# This unit is the supervised path and stays the only one wherever a supervisor
# exists. Hosts with NO init system at all (the jcc devpods: no
# /run/systemd/system, no session bus) can never run it, so there
# `agents.start_agentmemory` starts the daemon as a detached process once per
# bootstrap instead — unsupervised by design, since $HOME is container-local and
# the next bootstrap is the restart. See its docstring and ADR-0011's update log
# for 2026-08-13.
#
# Memory lives in a local SQLite DB under ~/.agentmemory, which is an ADR-0009
# Tier-B link (home/env-links.nix) so it survives container recreation. The daemon
# serves REST on :3111 (the viewer on :3113); the MCP shim each agent runs talks to
# that port — see MCP_SERVERS in platform/installers/agents.py.
{ pkgs, lib, config, ... }:
let
  # Resolve the binary at *run* time, not eval time: agentmemory is installed by
  # npm under the mise-managed node (ADR-0011 keeps its version outside git so its
  # own self-update works), so there is no store path to point at.
  #
  # PATH order matters, and none of it can be assumed: a user service starts with
  # a near-empty environment. The HM profile provides mise; mise — not PATH — is
  # what knows where its node lives (its install dir reaches PATH only through
  # shell integration, and the shims dir may not exist at all); and `npm prefix
  # -g` then locates the dir `npm install -g` actually wrote the CLI into.
  serve = pkgs.writeShellScript "agentmemory-serve" ''
    set -eu
    export PATH="$HOME/.nix-profile/bin:$HOME/.local/bin:$PATH"
    if command -v mise >/dev/null 2>&1; then
      npm="$(mise which npm 2>/dev/null || true)"
      # Note the explicit `if`s: `[ … ] && PATH=…` as a bare statement would be
      # the script's failing last command under `set -e` whenever the test fails,
      # killing the unit before it ever looked for the binary.
      if [ -n "$npm" ] && [ -x "$npm" ]; then
        PATH="$(dirname "$npm"):$PATH"
        npm_prefix="$("$npm" prefix -g 2>/dev/null || true)"
        if [ -n "$npm_prefix" ] && [ -d "$npm_prefix/bin" ]; then
          PATH="$npm_prefix/bin:$PATH"
        fi
      fi
    fi
    if ! command -v agentmemory >/dev/null 2>&1; then
      echo "agentmemory is not installed yet — nothing to serve." >&2
      echo "It is installed by platform/setup.py (npm -g @agentmemory/agentmemory)." >&2
      exit 0
    fi
    # Foreground server on :3111; systemd/launchd owns the lifecycle.
    exec agentmemory
  '';
in
{
  systemd.user.services.agentmemory = lib.mkIf pkgs.stdenv.isLinux {
    Unit = {
      Description = "agentmemory — local memory backend for Claude, Codex and omp (ADR-0011)";
      Documentation = "https://github.com/rohitg00/agentmemory";
    };
    Service = {
      Type = "simple";
      ExecStart = "${serve}";
      WorkingDirectory = config.home.homeDirectory;
      # Restart real crashes, but not the "not installed yet" exit 0 above.
      Restart = "on-failure";
      RestartSec = 10;
    };
    Install.WantedBy = [ "default.target" ];
  };

  # launchd is the symmetric half (ADR-0011 asks the supervisor surface to behave
  # the same on both OSes). KeepAlive.SuccessfulExit = false is launchd's
  # `Restart=on-failure`: relaunch on a crash, stay down after a clean exit.
  launchd.agents.agentmemory = lib.mkIf pkgs.stdenv.isDarwin {
    enable = true;
    config = {
      Label = "agentmemory";
      ProgramArguments = [ "${serve}" ];
      RunAtLoad = true;
      KeepAlive.SuccessfulExit = false;
      WorkingDirectory = config.home.homeDirectory;
      StandardOutPath = "${config.home.homeDirectory}/.agentmemory/launchd.out.log";
      StandardErrorPath = "${config.home.homeDirectory}/.agentmemory/launchd.err.log";
    };
  };
}
