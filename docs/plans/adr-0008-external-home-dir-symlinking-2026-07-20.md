# ADR-0008: JSON(C)-driven symlink map for external files/dirs into `$HOME`

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-07-20 |

## Context

Home Manager (ADR-0007) owns linking of the tracked dotfiles under
`sources/root`. But some files and directories a user wants in `$HOME` live
*outside* the repo — a persistent or synced folder (`/fsx/...`, a cloud-drive
mount) carrying per-machine/per-user state that does not belong in the flake
(shell history, `.claude`/`.agents` state, machine SSH material, …). There was
no first-class, idempotent, non-destructive way to fold such external content
into `$HOME`.

An earlier revision of this ADR gated the behavior on a single directory env
var (`DOTFILE_HOME_LINK_SRC`) whose direct sub-folders were linked. That was
too rigid: it couldn't rename between source and target, couldn't link
individual files, and couldn't express per-entry intent. The design was
reworked (see RFC-0002's update log) into an explicit, declarative link map.

`platform/setup.py` is the imperative post-Home-Manager layer, run via `uv run`
— and uv only exists *after* the Home Manager switch (`bootstrap.sh` puts the
HM profile on PATH so the Python steps find it). So the earliest point at which
this step can run is the very start of `setup.py`.

## Decision

Add an opt-in env var **`DOTFILE_LINK_MAP_JSON`** pointing at a JSON/JSONC file,
and an `apply_link_map(ctx)` step in `platform/setup.py` run **first** in
`main()` — before `set_login_shell`/`deploy_ssh_keys`/everything else, but
necessarily after uv (hence the whole script) is available.

> In the context of folding out-of-repo files and directories into `$HOME`,
> facing the absence of a safe, declarative, repeatable mechanism,
> we decided for a JSON(C) link map applied as the first post-HM step
> and against a single source-dir env var, a Home Manager source, or a copy,
> to achieve idempotent, non-destructive, per-entry-explicit linking,
> accepting a hand-rolled stdlib JSONC parser and manual cleanup of `.bak.N`.

### Config

`DOTFILE_LINK_MAP_JSON` points at a JSON **or JSONC** file (comments and
trailing commas allowed — parsed by a small, string-literal-aware stdlib
stripper, so the platform scripts stay dependency-free):

```jsonc
{
  "links": {
    "<label>": { "source": "/abs/src", "target": "/abs/dst", "type": "dir" | "file" }
  }
}
```

`links` is a **dict** keyed by a human-readable label (used only in log/warning
messages). Each entry carries an absolute `source`, absolute `target`, and a
declared `type`. The first-version map ships as `platform/link-map.jsonc`,
capturing this host's live `/root` ↔ `/fsx/hernando/dotfile_home_link_src`
relationship (`.agents`, `.claude`, `.ssh` as dirs; `.claude.json`,
`.zsh_history`, `.zcompdump` as files).

### Behavior

1. `DOTFILE_LINK_MAP_JSON` unset/empty → the feature is ignored.
2. Set but the file does not exist → **raise** (aborts the run; a misconfigured
   map fails loudly).
3. Set and present → each entry is validated and linked.

Per entry, a **source-side mismatch** logs a warning and skips the entry:
unknown `type`, missing `source`, or `type` disagreeing with what `source`
actually is (declared `dir` but a file, or vice-versa).

Target handling is non-destructive and idempotent:

| Target state | Action |
|---|---|
| Does not exist | Create the symlink |
| Already the correct symlink | Skip (idempotent) |
| Wrong-target / broken symlink | Replace with the correct symlink |
| Real file or real directory | Back up to a free `.pre-dotfiles.bak`, then link (also warned) |

Backup naming never clobbers: `~/x.pre-dotfiles.bak`, then `.bak.1`, `.bak.2`,
… — first free name. The suffix is the same one `deploy_ssh_keys` uses, so all
imperative post-HM steps share one backup convention, distinct from Home
Manager's own `.backup`.

Every warning is logged when hit **and** re-emitted in a summary once the whole
map has been processed. All mutations respect `ctx.dry_run`.

## Consequences

- A user declares exactly which external files/dirs land where in `$HOME`, with
  per-entry rename and type intent — more expressive than the source-dir sweep
  it replaced.
- Runs first, so links are in place before login-shell / SSH / Claude / system
  steps observe `$HOME`.
- Reruns are idempotent: correct symlinks are skipped, so no backup churn on
  container restart / re-bootstrap.
- No data loss: real content and prior backups are always preserved; the
  numeric-suffix `.pre-dotfiles.bak.N` scheme keeps the run automatic.
- A misconfiguration (env set, file missing) stops the bootstrap early rather
  than silently proceeding.
- Cost: a hand-rolled stdlib JSONC stripper to keep the platform scripts
  dependency-free (bootstrap prefers system Python for CN/offline reliability);
  and stale `.pre-dotfiles.bak.N` backups can accumulate (each logged, cleanup
  manual).
- Backup suffixes stay at **two**, split by ownership: Home Manager's `.backup`
  vs. the imperative steps' shared `.pre-dotfiles.bak`.
- `.ssh` appears in both the link map and `deploy_ssh_keys` (which copies keys
  into `~/.ssh`). Because the map runs first and makes `~/.ssh` a symlink to the
  external dir, `deploy_ssh_keys` then operates on that dir; it is a no-op when
  its own source (`DOTFILE_SSH_SRC`, default `sources/root/.ssh`) has no keys.
- The feature is inert until `DOTFILE_LINK_MAP_JSON` is set.
