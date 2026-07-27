# Tier B of ADR-0009 (docs/plans/adr-0009): env-specific mutable links.
#
# This module is the ONLY env-specific file in the flake. On the shared
# branches it is deliberately a no-op placeholder; each environment carries
# its real entries on its own branch (e.g. prod/mewtant), so the env delta —
# machine paths, secrets locations, intranet-only tools — never lands on the
# shared history and is always reviewable as a plain git diff.
#
# Entries link $HOME names to *writable* out-of-store targets on persistent
# storage. Two rules for every entry:
#
#   1. Use config.lib.file.mkOutOfStoreSymlink with an ABSOLUTE PATH STRING.
#      A Nix path literal (./foo or /fsx/foo without quotes) is copied into
#      the read-only store when the flake is evaluated, silently defeating
#      the purpose. Strings are never copied.
#   2. Say WHY the entry is env-specific/mutable in a comment — the entry
#      list is the inventory that replaced the ADR-0008 link map, and the
#      "why" is what keeps it auditable.
#
# Shape of a real entry (see the env branch for live ones):
#
#   home.file.".zsh_history".source =
#     config.lib.file.mkOutOfStoreSymlink "/persist/home-state/.zsh_history";
#
{ ... }:
{
  # Intentionally empty on this branch.
}
