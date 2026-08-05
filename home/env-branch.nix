# The env branch's file — and the ONLY file an env branch is allowed to edit.
#
# Why it exists: `home/env-links.nix` carries the mechanism plus the entries
# every environment wants, so it keeps changing on the shared branches. If an
# env branch also edited it, every rebase over `main` would conflict there. This
# file stays EMPTY on the shared branches, so the env branch's commit to it
# always replays cleanly — no conflict by construction, which is what
# .gitattributes cannot give us (a `merge=ours` driver resolves backwards under
# rebase: "ours" is the upstream being replayed onto, so it would silently
# discard the env branch's entries).
#
# What goes here:
#
#   - `envLinks.stateRoot`, when this environment's persistent volume differs.
#   - `envLinks.entries`, for links only this environment wants. Merged with the
#     shared set, so never restate a shared entry — that is the drift ADR-0009
#     exists to catch.
#   - A plain `home.file` + `mkOutOfStoreSymlink` line for anything whose target
#     is NOT under `stateRoot` and must not be auto-seeded (a distributed binary,
#     say: seeding it as an empty file would be worse than a dangling link,
#     which at least fails loudly).
#
# Live example, from the prod/mewtant branch:
#
#   {
#     envLinks.entries = {
#       # jcc: intranet-only. Config holds a bearer token + internal endpoint.
#       ".jcc.yaml" = { kind = "file"; mode = "600"; };
#       # lark-cli: intranet Lark tooling — auth tokens, cache, logs.
#       ".lark-cli" = { kind = "dir"; mode = "700"; };
#     };
#     # The jcc binary is distributed on /fsx, not via nixpkgs, and lives outside
#     # stateRoot — deliberately not seeded, so a missing build is visible.
#     home.file.".local/bin/jcc".source =
#       config.lib.file.mkOutOfStoreSymlink "/fsx/hernando/local/bin/jcc";
#   }
#
{ ... }:
{
  # Intentionally empty on the shared branches.
}
