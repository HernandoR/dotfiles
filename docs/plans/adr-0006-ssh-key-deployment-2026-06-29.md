# ADR-0006: SSH keys deployed by copy, git-ignored in staging

| Field | Value |
|---|---|
| Status | superseded |
| Date | 2026-06-29 |
| Superseded by | [ADR-0008](adr-0008-external-home-dir-symlinking-2026-07-20.md) |

> **Superseded (2026-07-20).** The copy-based SSH-key deployment
> (`deploy_ssh_keys` + `DOTFILE_SSH_SRC`) has been removed. SSH material is now
> symlinked into `$HOME` by the JSON(C) link map (ADR-0008), like any other
> external dir. This reverses the original decision below to *avoid* symlinking
> `~/.ssh`; that reasoning (SSH's strict-permission checks) still applies — the
> link map is safe only while the external `.ssh` is `700` and its keys `600`,
> because SSH enforces perms on the symlink target. The defensive
> `.gitignore` for `sources/root/.ssh/id_*` is retained.

## Context

The SSH key pair (`~/.ssh/id_ed25519`[`.pub`]) should be the *same identity*
across machines — registered once with GitHub/servers, then present on every
box. The persistent staging dir (`/fsx/…/dotfiles/.ssh`) is the natural store.

But the generic migration (ADR-0001) **symlinks** staging entries into `$HOME`,
and that is wrong for SSH keys two ways:

1. **Symlink vs real file.** SSH wants real files it owns with strict perms
   (`700` on `~/.ssh`, `600` on the private key). A symlink pointing out to the
   staging filesystem is fragile and surprising for key material.
2. **Secret in git.** Staging is a git repo (currently no remote, but that can
   change). `.ssh/id_ed25519` was tracked — a private key committed to history.

## Decision

### 1. Copy, don't symlink

`.ssh` is added to the migration phase's link-exclude set (alongside
`CLAUDE_MANAGED_PATHS`), so the symlink walk never touches it. A dedicated
`DotfilesManager.deploy_ssh_keys` then **copies** key material from
`<staging>/.ssh` into `~/.ssh`:

- Ensures `~/.ssh` exists at mode `700`.
- For each `id_*` private key → copy, `chmod 600`; each `*.pub` → copy,
  `chmod 644`.
- Skips everything else: `authorized_keys` is owned by `edit_home.sh`'s merge,
  `known_hosts` is machine-local.
- Staging is authoritative; a *differing* pre-existing home key is moved to a
  `<name>.pre-dotfiles.bak` backup (never silently overwritten). An identical
  copy is left in place (perms re-asserted); a stray symlink is replaced.

### 2. Git-ignore the private material

Staging gains a `.gitignore` (`.ssh/id_*`, un-ignoring `*.pub`) and the already
-tracked `.ssh/id_ed25519` is `git rm --cached`'d (working file kept). The repo
mirrors the ignore for `sources/root/.ssh/id_*` defensively.

## Consequences

- `~/.ssh/id_ed25519` becomes a real, `600` file copied from staging — the same
  key on every machine, with SSH-correct permissions.
- The private key is no longer tracked going forward. NOTE: it remains in the
  staging repo's **past history**; purging that needs a history rewrite, judged
  not worth it for a no-remote local repo. Do not add a remote without
  scrubbing history first.
- Public keys stay trackable.
- A machine that generated its own key before bootstrap keeps it at
  `~/.ssh/id_ed25519.pre-dotfiles.bak`.
