# The env branch's file — mewtant intranet hosts (branch prod/mewtant).
#
# This is the ONLY file this branch is allowed to edit. `home/env-links.nix`
# carries the mechanism plus the entries every environment wants and keeps
# changing on the shared branches; keeping this branch's delta in a file the
# shared branches never touch is what makes rebasing over them conflict-free.
# Restating a shared entry here would reintroduce exactly the two-inventories
# drift ADR-0009 exists to catch — so don't.
#
# `envLinks.stateRoot` IS overridden. The shared default now roots the inventory
# under $HOME, which on these hosts is container-local and does not survive a
# restart; the persistent volume is /fsx. Overriding the root moves the whole
# inventory at once, so this one line is all it takes.
{ config, ... }:
{
  envLinks.stateRoot = "/home/ec2-user/dotfile_home";

  envLinks.entries = {
    # jcc: intranet-only tool. Its config holds a bearer token and an internal
    # endpoint, so it can neither live in the store nor on shared history.
    ".jcc.yaml" = { kind = "file"; mode = "600"; };

    # lark-cli: intranet Lark tooling — auth tokens, cache and logs, all mutable.
    ".lark-cli" = { kind = "dir"; mode = "700"; };

    # Remote-IDE server trees. These hosts are only ever reached over SSH from a
    # local editor, so every container recreation re-downloads and re-installs
    # the server over the intranet. Both are entirely tool-owned and replaced
    # wholesale on each version bump, so neither can be a store link.

    # VS Code Remote: ~760MB of server, extensions and user-data. 700 because
    # `data/` holds the connection token and per-extension credential caches
    # next to the binaries (the tool itself creates this dir 750).
    ".vscode-server" = { kind = "dir"; mode = "700"; };

    # Zed Remote — note the UNDERSCORE: Zed's own path is ~/.zed_server, and a
    # ".zed-server" entry would persist a directory nothing ever reads. Holds
    # only the ~110MB remote-server binary, no credentials, hence 755 as Zed
    # creates it. Zed's *state* (LSP servers, logs — 1.4GB) lives in
    # ~/.local/share/zed and is deliberately not covered here: it is not a
    # top-level $HOME path, so persisting it is a separate decision.
    ".zed_server" = { kind = "dir"; mode = "755"; };
  };

  # The jcc binary is distributed on /fsx rather than through nixpkgs, so its
  # target sits outside stateRoot and is deliberately left out of the seeded
  # inventory: creating it as an empty file would be worse than a dangling link,
  # which at least fails loudly when the binary is missing.
  home.file.".local/bin/jcc".source =
    config.lib.file.mkOutOfStoreSymlink "/fsx/hernando/local/bin/jcc";
}
