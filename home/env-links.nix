# Tier B of ADR-0009 (docs/plans/adr-0009): mutable, out-of-store $HOME links —
# the MECHANISM plus the default entry set. Shared on every branch.
#
# Each entry links a $HOME name to a *writable* target under `envLinks.stateRoot`
# — a persistent volume that outlives the machine ($HOME does not survive
# container recreation). This list is the inventory that replaced the ADR-0008
# JSON(C) link map: a new persistent top-level $HOME file/dir needs an entry
# before it survives recreation, and adding one is a reviewable commit.
#
# WHERE TO ADD AN ENTRY decides which file you edit:
#
#   every environment wants it       -> here, in `envLinks.entries` below
#   only this environment wants it,
#   or the volume path differs       -> home/env-branch.nix, on the env branch
#
# home/env-branch.nix is empty on shared branches and is the only file an env
# branch touches, so rebasing an env branch over `main` never conflicts (see its
# header). Keeping the mechanism and the shared list here means neither branch
# re-derives the other's work.
#
# Two rules when adding an entry:
#
#   1. Paths reach mkOutOfStoreSymlink as ABSOLUTE PATH STRINGS. A Nix path
#      literal (/fsx/foo unquoted) is copied into the read-only store at flake
#      eval, silently defeating the purpose. Strings are never copied.
#   2. Say WHY the entry is mutable — the "why" is what keeps the inventory
#      auditable. `kind`/`mode`/`seed` are how a missing target gets created
#      (below) — applied on creation only, never to a target that exists.
{ config, lib, pkgs, ... }:
let
  cfg = config.envLinks;
  target = name: "${cfg.stateRoot}/${name}";

  seedTarget = name: e:
    if e.kind == "dir" then
      # -m applies to directories this run creates; existing ones are a no-op.
      ''$DRY_RUN_CMD mkdir -p -m ${e.mode} ${lib.escapeShellArg (target name)}''
    else
      # Guarded so an existing file keeps its own mode AND its content. `install`
      # rather than `touch` + `chmod` so the initial content comes from `seed` in
      # one dry-run-safe command (a shell redirection would write even under
      # $DRY_RUN_CMD, since the redirect is the shell's, not the command's). An
      # empty seed reproduces the old `touch` exactly.
      ''[ -e ${lib.escapeShellArg (target name)} ] || $DRY_RUN_CMD install -m ${e.mode} ${seedFile name e} ${lib.escapeShellArg (target name)}'';

  # Store file holding an entry's initial content. Store path names may not start
  # with a period, and the entry names all do.
  seedFile = name: e:
    pkgs.writeText "env-link-seed-${lib.replaceStrings [ "." "/" ] [ "_" "_" ] name}" e.seed;

  # Repair a $HOME path that is a REGULAR FILE where a link belongs.
  #
  # Some writers replace rather than update: they write a temp file next to the
  # path and rename it over the top, which silently turns our symlink into a
  # regular file. Claude Code does this to ~/.claude.json (measured on a clean
  # devpod). Two things then go wrong, and both are silent until much later:
  #
  #   1. the file stops being the link — so it stops persisting to stateRoot,
  #      which is the entire point of the entry;
  #   2. the next activation finds an unmanaged file in the way, tries to back it
  #      up, collides with the `.backup` left by the previous cycle, and ABORTS —
  #      taking the whole bootstrap with it (reproduced twice).
  #
  # So fold the file back into its target and leave the path free; Home Manager
  # then places the link itself, as it would on a first run. The newer copy wins,
  # because the $HOME file is what the tool just wrote and the target is the stale
  # side — but say which way it went rather than deciding quietly.
  #
  # Files only. A real *directory* in the way is not this failure mode (writers
  # create files inside a dir, they never rename over it), and merging two trees
  # is a judgement call, so those keep going through HM's own `.backup` path.
  repairLink = name: e:
    let
      # Double-quoted, NOT escapeShellArg'd: that helper single-quotes, which
      # would stop $HOME from expanding. Entry names are plain dotfile names.
      link = "\"$HOME/${name}\"";
      tgt = lib.escapeShellArg (target name);
    in
    if e.kind != "file" then "" else ''
      if [ -e ${link} ] && [ ! -L ${link} ]; then
        if [ ${link} -nt ${tgt} ]; then
          warnEcho "env-links: ~/${name} was replaced by a regular file (newer than its target) — folding it back into ${target name}"
          $DRY_RUN_CMD mv -f ${link} ${tgt}
          $DRY_RUN_CMD chmod ${e.mode} ${tgt}
        else
          warnEcho "env-links: ~/${name} is a regular file older than its target — discarding it, the target wins"
          $DRY_RUN_CMD rm -f ${link}
        fi
      fi
    '';
in
{
  options.envLinks = {
    stateRoot = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/dotfile_home";
      description = ''
        Persistent per-user state root holding every link target, rooted under
        the user's home directory by default. An env branch overrides this in
        home/env-branch.nix; it is the only path in the default set, so
        overriding it moves the whole inventory at once.
      '';
    };

    entries = lib.mkOption {
      default = { };
      description = ''
        $HOME-relative name -> how to seed its target under stateRoot when it
        does not exist yet. Merged across files, so an env branch adds entries
        without restating these.
      '';
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          kind = lib.mkOption {
            type = lib.types.enum [ "dir" "file" ];
            description = "Seed a missing target as a directory or as a file.";
          };
          mode = lib.mkOption {
            type = lib.types.str;
            description = "chmod arg, applied ONLY when this run creates the target.";
          };

          seed = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = ''
              Initial content for a `file` entry, written ONLY when this run
              creates the target. Empty (the default) means an empty file, which
              is what most state files want. Set it for a file whose consumer
              treats empty as corrupt rather than as "nothing yet".
            '';
          };
        };
      });
    };
  };

  config = {
    envLinks.entries = {
      # --- agents (ADR-0011: all three rewrite their own config at runtime, so
      # none of these can be an HM store link) ---

      # Cross-agent instruction + loose-skills root (ADR-0011 plane ①):
      # ~/.agents/AGENTS.md is the single instruction source both Codex and pi
      # read, and ~/.agents/skills the shared loose-skills dir. Mutable: skills
      # are added and edited in place.
      ".agents" = { kind = "dir"; mode = "755"; };

      # Claude Code: ONE whole-dir link (ADR-0009 grilling Q2) so config and
      # state travel together and /model + /config persistence keeps working;
      # new Claude-internal state dirs then persist automatically.
      ".claude" = { kind = "dir"; mode = "755"; };
      # Claude Code runtime state (onboarding, MCP auth cache) — mutable JSON,
      # and it holds OAuth material, hence 600. Seeded with `{}` rather than
      # empty: Claude Code reads this file at startup and an empty one is not
      # "nothing yet" to it but a parse error — it reports the file as corrupted,
      # backs it up and exits non-zero, which on a fresh machine takes its own
      # installer down with it (found on a clean devpod bootstrap, 2026-08-05).
      ".claude.json" = { kind = "file"; mode = "600"; seed = "{}"; };

      # Codex CLI: whole-dir for the same reason as .claude — config.toml is
      # rewritten by /model (openai/codex#14979), /experimental and /statusline,
      # and the dir also holds auth.json, history and sessions. The AGENTS.md
      # and skills links into ~/.agents (ADR-0011) live *inside* this dir, so
      # they are part of the persistent volume rather than HM-managed.
      ".codex" = { kind = "dir"; mode = "700"; };

      # pi: whole-dir. ~/.pi/agent/settings.json is rewritten by /settings and
      # by `pi install` (which records the installed extension set into it).
      ".pi" = { kind = "dir"; mode = "700"; };

      # agentmemory's local SQLite store + its pinned engine binary (ADR-0011).
      # The whole value of a memory backend is that it accumulates, so this is
      # the one agent path where losing the state would matter most; 700 because
      # it holds verbatim conversation content.
      ".agentmemory" = { kind = "dir"; mode = "700"; };

      # --- shell / machine state ---

      # SSH material is per-host secret data. SSH checks permissions on the link
      # TARGET, so this is safe only while the target stays 700 and its keys 600
      # (ADR-0006 rationale, carried forward through ADR-0008).
      ".ssh" = { kind = "dir"; mode = "700"; };

      # Regenerable completion cache; persisted purely for zsh startup speed.
      ".zcompdump" = { kind = "file"; mode = "644"; };

      # Shell history must accumulate across container recreations.
      ".zsh_history" = { kind = "file"; mode = "600"; };
    };

    home.file = lib.mapAttrs (name: _: {
      source = config.lib.file.mkOutOfStoreSymlink (target name);
    }) cfg.entries;

    # Seed any missing link target BEFORE Home Manager places the links.
    #
    # A dangling out-of-store link is a trap rather than a harmless no-op: the
    # tool that owns the path cannot repair it, because mkdir/create_dir_all on
    # a dangling symlink fails with EEXIST instead of following it. And the
    # tools cannot win the race anyway — the HM switch runs before
    # platform/setup.py installs codex/pi, so the link is always there first.
    #
    # This is the `home.activation` escape hatch ADR-0009 reserved: the entries
    # stay the single declarative inventory, and this only makes what they
    # already declare TRUE — first by creating a missing target (below), then by
    # repairing a $HOME file that a rename-happy writer left where a link belongs
    # (see repairLink). Neither invents anything the entries do not already say. It creates stateRoot but NOT stateRoot's parent: if
    # the persistent volume is not mounted, mkdir -p would happily build the
    # whole tree on the container's ephemeral disk, and every link would then
    # "work" while silently persisting nothing — the exact failure this module
    # exists to prevent. So a missing parent warns and skips instead.
    home.activation.seedEnvLinkTargets =
      let parent = builtins.dirOf cfg.stateRoot; in
      lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
        if [ ! -d ${lib.escapeShellArg parent} ]; then
          warnEcho "env-links: ${parent} does not exist — not seeding link targets."
          warnEcho "env-links: mount the persistent volume, then re-run; until then the \$HOME links dangle."
        else
          $DRY_RUN_CMD mkdir -p ${lib.escapeShellArg cfg.stateRoot}
          ${lib.concatStringsSep "\n  " (lib.mapAttrsToList seedTarget cfg.entries)}
          ${lib.concatStringsSep "\n  " (lib.filter (s: s != "") (lib.mapAttrsToList repairLink cfg.entries))}
        fi
      '';
  };
}
