# RFC-0002: Symlink an external directory's sub-folders into `$HOME`

- Status: Resolved
- Date: 2026-07-20
- Owners: HernandoR

## Summary

Add an opt-in env var, `DOTFILE_HOME_LINK_SRC`, pointing at a directory whose
*direct sub-folders* are each symlinked into the current user's `$HOME` during
the imperative post-Home-Manager setup. Pre-existing real content at a target
name is backed up (renamed with a `.nkp` suffix) before the symlink is made.

## Motivation

Home Manager (ADR-0007) owns the linking of the *tracked* dotfiles under
`sources/root`. But some directories a user wants in `$HOME` live *outside* the
repo — e.g. a persistent/synced folder (`/fsx/...`, a cloud-drive mount) that
carries per-machine or per-user state not suitable for the flake. There is
currently no first-class way to fold such an external directory's children into
`$HOME` as symlinks; users do it by hand and it is neither idempotent nor
non-destructive. This gives that workflow one env var and one safe, repeatable
step.

## Goals

- One env var names an external source directory; each of its **direct child
  directories** becomes a symlink in `$HOME`.
- Safe on repeated runs (container restart, re-bootstrap) — no backup churn.
- Never destroy pre-existing real content or an earlier backup.

## Non-Goals

- Linking loose files at the top level of the source (directories only).
- Replacing or extending Home Manager's own linking of `sources/root`.
- Providing an in-repo default source path (this is user-specific).
- A dedicated CLI flag (env-only, like `DOTFILE_SSH_SRC`).

## Proposal

Add `link_home_dirs(ctx)` to `platform/setup.py`, called from `main()`
immediately after `deploy_ssh_keys`. It reads `DOTFILE_HOME_LINK_SRC`; if unset
or empty it returns silently, and if set-but-missing it warns and returns
(mirroring `deploy_ssh_keys`'s missing-source handling).

For each direct child *directory* `foo` of the source, resolve `~/foo` and act
per its current state:

| State of `~/foo` | Action |
|---|---|
| Does not exist | Create symlink `~/foo → <src>/foo` |
| Already the correct symlink | Skip (idempotent) |
| Wrong-target / broken symlink | Replace with the correct symlink (no backup) |
| Real file or real directory | Rename to a free `.nkp` backup, then symlink |

Backup naming: try `~/foo.nkp`; if taken, `~/foo.nkp.1`, `~/foo.nkp.2`, … —
first free name wins, so an earlier backup is never clobbered. All mutations
respect `ctx.dry_run`.

## Alternatives Considered

| Alternative | Why Not |
|---|---|
| Keep the user's name `DOTFILE_HOME_DESTINATION` | Reads backwards — the var is the *source*, `$HOME` is the destination. Renamed to `DOTFILE_HOME_LINK_SRC` to match `DOTFILE_SSH_SRC`. |
| Always back up anything present (even a symlink) | Churns a new backup every run; not idempotent. |
| Skip-and-warn on `.nkp` collision | Simpler but fails to link the folder; numeric suffix keeps the run fully automatic without data loss. |
| Fold into Home Manager | HM's source must be in the flake/repo; this is deliberately for out-of-repo, per-machine directories. |
| Copy instead of symlink | Source is meant to stay authoritative (often on persistent storage); symlink keeps a single source of truth. |

## Risks

- A stale broken symlink in `$HOME` is replaced silently — acceptable, it held
  no real data.
- Accumulating `.nkp.N` backups if real content keeps reappearing — logged each
  time so the churn is visible; user cleans up manually.

## Open Questions

- (Resolved during grilling — see ADR-0008.)

## Acceptance Criteria

- [ ] `DOTFILE_HOME_LINK_SRC=<dir> ./bootstrap.sh --dry-run` logs intended
  symlinks/backups and changes nothing.
- [ ] Unset var → step is a no-op.
- [ ] Re-running with the var set produces no new backups when targets are
  already correct symlinks.
- [ ] A pre-existing real `~/foo` is renamed to `~/foo.nkp` (or next free
  suffix) and replaced by a symlink.

## Rollout

Additive: new function + `main()` call in `platform/setup.py`, a README env-table
row, and ADR-0008. No migration; the feature is inert until the var is set.

## Update log

- **2026-07-20 — backup suffix unified.** The draft above proposed a dedicated
  `.nkp` backup suffix. On review this was dropped: a third suffix added noise
  for no benefit. The step now reuses `deploy_ssh_keys`'s existing
  `.pre-dotfiles.bak` (collision scheme unchanged: `.pre-dotfiles.bak`,
  `.pre-dotfiles.bak.1`, …). Backup conventions therefore stay at two, split by
  ownership: Home Manager's `.backup` vs. the imperative steps'
  `.pre-dotfiles.bak`. ADR-0008 updated to match.
