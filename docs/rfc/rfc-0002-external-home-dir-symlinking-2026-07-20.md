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

- **2026-07-20 — reworked from a source-dir env var to a JSON(C) link map.**
  The original proposal (a single `DOTFILE_HOME_LINK_SRC` directory whose direct
  sub-folders were swept into `$HOME`) was replaced. It could not rename between
  source and target, could not link individual files, and buried per-entry
  intent in a directory listing. New design:
  - **Env var:** `DOTFILE_LINK_MAP_JSON` (name carries `JSON`) → a config file,
    not a directory.
  - **Schema:** a **dict** (not a list) — `{"links": {"<label>": {"source",
    "target", "type": "dir"|"file"}}}`. The label is a log-only handle; each
    entry is fully explicit. `type` is declared so a source/type mismatch is
    detectable.
  - **Format:** JSONC by default, plain JSON compatible. Parsed with a
    string-literal-aware stdlib stripper (comments + trailing commas) rather
    than a dependency, to keep the platform scripts dependency-free
    (`bootstrap.sh` prefers system Python for CN/offline reliability).
  - **Conditions:** unset → ignore; set-but-file-missing → **raise/abort**;
    both present → link.
  - **Timing:** the **first** step in `setup.py`'s `main()` (before every other
    imperative step), but necessarily after uv — hence the script itself — is
    available, which is only *after* the Home Manager switch.
  - **Mismatch handling:** a source-side mismatch (wrong/unknown `type`, missing
    `source`) warns and skips; every warning is logged when hit **and**
    re-emitted in an end-of-run summary.
  - **Target handling:** unchanged from the prior revision — correct symlink →
    skip; wrong/broken symlink → replace; real content → back up to
    `.pre-dotfiles.bak` then link (also warned).
  - **First version:** `platform/link-map.jsonc`, capturing this host's live
    `/root` ↔ `/fsx/hernando/dotfile_home_link_src` links.
  ADR-0008 rewritten atomically (incl. title) to state this design.
