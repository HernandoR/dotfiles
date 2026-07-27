# ADR-0009: Config ownership tiers — env-specific HM module owns mutable links; declarative nixification deferred

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-07-26 (decisions settled 2026-07-27) |

## Context

ADR-0008 introduced a JSON(C) link map, applied by `platform/setup.py`, to
fold out-of-repo files/dirs into `$HOME`. Within a week it drifted: two
symlinks on the reference host (`~/.jcc.yaml`, `~/.lark-cli`) exist in neither
copy of the map, and the live map (`/fsx/hernando/local/…`) diverged from the
repo copy (`platform/link-map.jsonc`) — the out-of-repo, hand-edited file has
no review loop.

Home Manager (tracked at master by `flake.nix`) natively provides writable
out-of-store symlinks via `config.lib.file.mkOutOfStoreSymlink
"/abs/path/as/string"` (RFC-0003, Research), so the Python link map duplicates
an HM facility with a weaker feedback loop.

RFC-0003 also proposed moving Claude Code's declarative config
(`settings.json`, plugins, marketplaces) into `programs.claude-code`. During
decision grilling (2026-07-27) this was **deferred**: everything the module
writes is a read-only store link, which breaks `/model` and `/config`
persistence — runtime writes the owner actually relies on. The seed+writable-
copy workaround was considered and declined in favor of keeping the current
mutable link unchanged (RFC-0003, update log).

## Decision

> In the context of managing what lands in `$HOME`,
> facing link-map drift under ADR-0008 and read-only-vs-runtime-writable
> tension in Claude config,
> we decided for a single env-specific, branch-managed Home Manager module of
> `mkOutOfStoreSymlink` entries as the sole owner of mutable `$HOME` links,
> deferring declarative (Tier A) nixification of Claude config,
> and against keeping the imperative Python link map or flattening env
> differences into flake host attrs,
> to achieve one reviewed source of truth with env deltas visible as git
> diffs,
> accepting rebase discipline on env branches and postponed declarative
> Claude management.

### Ownership rule (the tiers, as a standing principle)

- **Tier A — portable declarative config** → shared HM modules on `main`.
  What already lives there (shell, git, tmux, starship, mise, packages) stays
  there. *No Claude config joins it yet* — see Deferral below.
- **Tier B — env-specific mutable state & secrets** → symlinks to persistent
  storage, declared in **one HM module** (`home/env-links.nix`) using
  `mkOutOfStoreSymlink` with absolute **string** paths (never Nix path
  literals — those are copied into the store and the link silently points at
  the immutable copy).

### The env-links module

Covers the full current inventory, including the entries the JSONC maps lost
track of:

`~/.claude` (whole dir), `~/.claude.json`, `~/.agents`, `~/.ssh`,
`~/.zsh_history`, `~/.zcompdump`, `~/.jcc.yaml`, `~/.lark-cli`,
`~/.local/bin/jcc`.

`~/.claude` deliberately stays a **whole-dir link** (grilling Q2): with no HM-
managed files inside it, per-subpath inversion buys nothing and costs a
migration plus a moving-target subpath list. The module is imported
unconditionally from `home/default.nix`; on the shared branches
(`main`/`feat/lix-based`) it is a no-op carrying only a commented placeholder
example (no corp paths on shared history). Each environment carries its real
absolute paths on its own branch — the first being **`prod/mewtant`** for the
mewtant intranet hosts — so the env delta is confined to this one file and
reviewed like any other change. Module comments state per entry *why* it is
env-specific/mutable.

### Deferral: declarative Claude config (Tier A candidate)

`programs.claude-code` adoption, the settings extraction, and the `.claude`
inversion are recorded as **future work**, not intent. Revisit triggers:
`programs.claude-code` (or Claude Code itself) gains a sane story for
runtime-mutable settings, or the owner stops relying on `/model`/`/config`
persistence. Until then `setup_claude` (ADR-0005) continues to own plugin and
marketplace installs imperatively — ADR-0005 is **unchanged** by this ADR.
For a brand-new environment, seeding a fresh persistent `.claude`/config
skeleton is env provisioning, out of scope here.

### Supersession

**ADR-0008 is superseded by this ADR.** After one successful bootstrap on an
env branch proves the module, `apply_link_map`, `DOTFILE_LINK_MAP_JSON`, the
hand-rolled JSONC parser, and both map files are deleted. Non-destructive
collision handling transfers to HM (`checkLinkTargets` + the bootstrap's
`-b backup`-equivalent activation); HM's `.backup` becomes the single backup
suffix, retiring `.pre-dotfiles.bak`.

## Consequences

- Every `$HOME` link has exactly one reviewed owner; "what links exist" is
  answerable from the checked-out branch, and drift like
  `.jcc.yaml`/`.lark-cli` cannot silently accumulate — a new link requires a
  commit.
- Links appear at HM-switch time — *earlier* in bootstrap than today's
  first-post-setup step — and bootstrap loses an env var
  (`DOTFILE_LINK_MAP_JSON`).
- Claude ergonomics are untouched: `/model`, `/config`, plugin installs all
  behave exactly as today. The cost is that Claude config stays
  non-declarative and its drift is only contained by living on the persistent
  volume, not by review.
- Env branches must be rebased over `main`; conflicts are confined to
  `home/env-links.nix` by construction.
- A *new top-level* `$HOME` state file still needs a module commit before it
  persists — same exposure as ADR-0008, but the fix is now an in-repo diff
  rather than an out-of-repo file edit. (Whole-dir `.claude` linking means
  new *Claude-internal* state dirs persist automatically.)
- Migration one-off: existing correct symlinks are "unmanaged files" to HM's
  collision check; the first switch shuffles them through the `-b backup`
  path — run bootstrap `--dry-run` first.
- The tier principle stands ready for future Tier A adoptions (Claude or
  otherwise) without re-deciding the mechanism split.
