# ADR-0008: Symlink an external directory's sub-folders into `$HOME`

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-07-20 |

## Context

Home Manager (ADR-0007) owns the linking of the tracked dotfiles under
`sources/root`. Some directories a user wants present in `$HOME` live *outside*
the repo — a persistent or synced folder (`/fsx/...`, a cloud-drive mount)
carrying per-machine/per-user state that does not belong in the flake. There
was no first-class, idempotent, non-destructive way to fold such an external
directory's children into `$HOME`.

`platform/setup.py` is the imperative post-Home-Manager layer (ADR-0007), and
`deploy_ssh_keys` there already establishes the house pattern for this shape of
work: read a `DOTFILE_`-prefixed source env var, act non-destructively, back up
conflicts with a suffix. This decision reuses that pattern for directory
symlinking.

## Decision

Add an opt-in env var **`DOTFILE_HOME_LINK_SRC`** and a `link_home_dirs(ctx)`
step in `platform/setup.py`, called from `main()` immediately after
`deploy_ssh_keys`.

> In the context of folding an out-of-repo directory's contents into `$HOME`,
> facing the absence of a safe, repeatable mechanism,
> we decided for an env-var-gated symlink step in `platform/setup.py`
> and against a Home Manager source, a copy, or a CLI flag,
> to achieve idempotent, non-destructive linking of per-machine directories,
> accepting that stale backups (`.pre-dotfiles.bak.N`) can accumulate and must
> be cleaned up by hand.

Naming: the var is the **source** whose direct sub-folders are linked *into*
`$HOME` (which is the destination). It is named `DOTFILE_HOME_LINK_SRC` — not
the originally-proposed `DOTFILE_HOME_DESTINATION`, which read backwards — to
match `DOTFILE_SSH_SRC`.

Behavior:

1. If `DOTFILE_HOME_LINK_SRC` is unset/empty → no-op (pure opt-in, no CLI flag).
   If set but the directory does not exist → warn and return.
2. Only **direct child directories** of the source are linked; loose files at
   the top level are ignored.
3. Per-target state rules for `~/foo` (mirroring ADR-0001's linking table):

   | State of `~/foo` | Action |
   |---|---|
   | Does not exist | Create symlink `~/foo → <src>/foo` |
   | Already the correct symlink | Skip (idempotent) |
   | Wrong-target / broken symlink | Replace with the correct symlink (no backup) |
   | Real file or real directory | Rename to a free `.pre-dotfiles.bak`, then symlink |

4. Backup naming never clobbers: try `~/foo.pre-dotfiles.bak`, then
   `~/foo.pre-dotfiles.bak.1`, `~/foo.pre-dotfiles.bak.2`, … — first free name
   wins. The suffix is deliberately the **same** one `deploy_ssh_keys` uses, so
   all imperative post-HM steps share one backup convention.
5. All mutations respect `ctx.dry_run`.

Documented as a new row in the README env-var table.

## Consequences

- A user gets one env var to bring an external directory's sub-folders into
  `$HOME` as symlinks, safely and repeatably.
- Reruns are idempotent: correct symlinks are skipped, so no backup churn on
  container restart / re-bootstrap.
- No data loss: real content and prior backups are always preserved; the
  numeric-suffix scheme keeps the run automatic.
- Backup suffixes stay at **two**, split by ownership: Home Manager uses
  `.backup`; every imperative post-HM step (`deploy_ssh_keys` and now
  `link_home_dirs`) uses the shared `.pre-dotfiles.bak`.
- Stale `.pre-dotfiles.bak.N` backups can accumulate if real content repeatedly
  reappears at a target; each is logged, and cleanup is manual.
- The feature is inert until `DOTFILE_HOME_LINK_SRC` is set — zero impact on
  existing bootstraps.
