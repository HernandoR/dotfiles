# ADR-0001: Dotfiles Staging-and-Linking Strategy

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-06-23 |

## Context

Bootstrap flow: `bootstrap.sh` → `main.py` (`DotfilesManager`). The tracked
configs live in `sources/root/`. A *staging directory* (`$DOTFILE_EDIT_HOME_TARGET/dotfiles`,
default `~/dotfiles`) acts as a writable copy of those configs on the target
machine. `link_dotfiles` then symlinks entries from staging into `$HOME`.

The previous implementation had two problems:

1. **Selective staging via `.file_list`**: `restore_dotfiles` used
   `rsync --files-from=sources/.file_list`, requiring every new dotfile to be
   registered in two places (`sources/root/` *and* `.file_list`). This was
   error-prone and the backup workflow that motivated it is no longer used.

2. **Directories became real dirs, not symlinks**: `link_dotfiles` created real
   directories at the destination and only symlinked individual files. This
   meant `~/.agents` and `~/.claude` (and any future directory-shaped config)
   were real directories rather than symlinks into staging, making it harder to
   see at a glance what is dotfiles-managed.

A third constraint: some files in `$HOME` (e.g. `~/.agents/`, `~/.claude/`)
may be created by other tools *before* bootstrap runs. Whether those files
should be brought under dotfiles management is not always clear, so the
bootstrap must be non-destructive toward pre-existing content.

## Decision

### 1. Staging: copy everything, keep noise exclusions

Replace `restore_dotfiles` (and its `--files-from=.file_list` filter) with a
simpler `stage_dotfiles` that rsyncs all of `sources/root/` to staging:

```
rsync -a -v -h -C --recursive \
      --exclude-from=./sources/.ex_list \
      sources/root/  <staging>/
```

`sources/.ex_list` is kept — it filters out runtime noise
(`**cache**`, `**lock.json`, `**swap/*`). `sources/.file_list` is deleted.

`backup_dotfiles`, `restore_dotfiles`, and the `backup`/`restore` CLI
subcommands are removed. Backup is deprecated; staging is now the canonical
representation of the managed configs.

### 2. Staging skip on populated staging + fresh home

Before running rsync, check whether staging is already populated AND at least
one direct child of staging is not yet correctly symlinked in `$HOME`. If so:

- Log a `WARNING` ("staging exists but symlinks missing — skipping rsync,
  running link step only")
- Skip the rsync entirely — preserving any customisations made directly in
  staging since the last full bootstrap
- Proceed straight to `link_dotfiles`

This handles the **container-restart** case: staging lives on a persistent
filesystem (`/fsx/…`), but `$HOME` is recreated fresh. Re-rsyncing from
`sources/root` would clobber staging edits; the right action is to
re-establish the symlinks only.

When staging does not exist, or every direct child of staging is already
correctly symlinked in `$HOME`, the rsync runs as normal.

### 3. Linking: non-destructive, prefer directory symlinks

`link_dotfiles` applies these rules at every node of the staging tree:

`link_dotfiles` applies these rules at every node of the staging tree:

| Destination state | Action |
|---|---|
| Does not exist | Create symlink (file or directory) pointing to staging node |
| Correct symlink (→ staging) | Skip |
| Wrong-target or broken symlink | Replace with correct symlink |
| Real file | Skip — may predate bootstrap; do not clobber |
| Real directory | Recurse — apply same rules to its contents |

Key consequence: on a *fresh* machine where `~/.agents` does not yet exist,
bootstrap creates `~/.agents → <staging>/.agents` (a directory symlink). On a
machine where `~/.agents` was already created by Claude Code or another tool,
bootstrap recurses into it and only symlinks the items that are missing —
leaving pre-existing content untouched.

## Consequences

- When staging already exists and `$HOME` is missing symlinks (container
  restart), bootstrap skips rsync and only re-establishes symlinks — staging
  customisations are preserved.


- `sources/.file_list` is deleted; adding a new dotfile only requires placing
  it under `sources/root/`.
- `AGENT.md` instructions for adding new dotfiles no longer reference
  `.file_list`.
- `backup_dotfiles`, `restore_dotfiles`, and the `backup`/`restore` argparse
  subcommands are removed from `main.py`.
- Directory-shaped configs (`.agents`, `.claude`, `.config/helix`, etc.) become
  directory symlinks into staging on fresh machines, making dotfiles membership
  visually obvious from `ls -la ~`.
- Pre-existing real files and directories in `$HOME` are never overwritten by
  bootstrap — mismatches are logged but left alone.
