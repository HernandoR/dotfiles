{ pkgs, ... }:
let
  toml = pkgs.formats.toml { };
in
{
  # Worktrunk (`wt`) user config. The CLI itself is a mise tool (home/mise.nix)
  # and its Claude plugin a manifest entry (platform/installers/agents.py); this
  # is the one file neither of them covers.
  #
  # Tier A, a read-only store link (ADR-0009): wt only READS this file — its
  # runtime state (hook approvals, markers, per-branch vars) goes to
  # ~/.config/worktrunk/approvals.toml and .git/wt/, never here — and the only
  # writer, `wt config create`, is the one-time scaffold this file replaces. So
  # unlike mise's tool list there is nothing to seed and hand over.
  xdg.configFile."worktrunk/config.toml".source = toml.generate "worktrunk-config" {
    # Where `wt switch --create` puts a worktree. Claude Code hard-codes
    # `<repo>/.claude/worktrees/<name>` for the worktrees it creates itself (a
    # session started from the desktop app's Code tab, `claude --worktree`, the
    # Agent tool's worktree isolation) and exposes no setting for the path —
    # measured against the docs on 2026-09-03; the only knob is a WorktreeCreate
    # hook, which the worktrunk plugin already installs to route creation through
    # `wt switch --create`. So the two tools meet on wt's side: this template
    # lands wt-created worktrees exactly where Claude-created ones are, and the
    # worktrees Claude creates through the plugin's hook come out under the same
    # path either way. One directory to look in, one `wt list`.
    #
    # `split("/") | last` drops a `<user>/` or `feat/` prefix, because that is what
    # Claude does — its worktree for branch `hernando/<name>` is at
    # `.claude/worktrees/<name>`. Two branches differing only in prefix would
    # collide on a path; wt refuses the second rather than overwriting.
    # Verified with `wt step eval` against this repo's own branch.
    worktree-path = "{{ repo_path }}/.claude/worktrees/{{ branch | split(\"/\") | last | sanitize }}";
  };
}
