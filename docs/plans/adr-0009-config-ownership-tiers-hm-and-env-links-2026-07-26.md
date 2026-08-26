# ADR-0009: Config ownership tiers — env-specific HM module owns mutable links; declarative nixification deferred

| Field  | Value                                     |
| ------ | ----------------------------------------- |
| Status | accepted                                  |
| Date   | 2026-07-26 (decisions settled 2026-07-27) |

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
  there. _No Claude config joins it yet_ — see Deferral below.
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
reviewed like any other change. Module comments state per entry _why_ it is
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
- Links appear at HM-switch time — _earlier_ in bootstrap than today's
  first-post-setup step — and bootstrap loses an env var
  (`DOTFILE_LINK_MAP_JSON`).
- Claude ergonomics are untouched: `/model`, `/config`, plugin installs all
  behave exactly as today. The cost is that Claude config stays
  non-declarative and its drift is only contained by living on the persistent
  volume, not by review.
- Env branches must be rebased over `main`; conflicts are confined to
  `home/env-links.nix` by construction.
- A _new top-level_ `$HOME` state file still needs a module commit before it
  persists — same exposure as ADR-0008, but the fix is now an in-repo diff
  rather than an out-of-repo file edit. (Whole-dir `.claude` linking means
  new _Claude-internal_ state dirs persist automatically.)
- Migration one-off: existing correct symlinks are "unmanaged files" to HM's
  collision check; the first switch shuffles them through the `-b backup`
  path — run bootstrap `--dry-run` first.
- The tier principle stands ready for future Tier A adoptions (Claude or
  otherwise) without re-deciding the mechanism split.

## Update log

- **2026-08-05 — two seeding hazards found by a clean-machine bootstrap** (a
  fresh jcc devpod with an empty `stateRoot`, during the ADR-0011
  implementation). Both are properties of this ADR's seeding, invisible on any
  host whose `stateRoot` was already populated:
  - **An empty seeded file is not always a valid empty state.** `.claude.json`
    is parsed by Claude Code at startup, so a zero-byte file reads as _corrupt_,
    not as "nothing yet": it backs the file up and exits non-zero, which on a
    fresh machine also fails its own installer. Entries therefore gained an
    optional `seed` (content applied on creation only, exactly like `mode`), and
    `.claude.json` seeds `{}`. Seeding switched from `touch` + `chmod` to
    `install -m` so content and mode arrive in one dry-run-safe command — a shell
    redirection would have written even under `$DRY_RUN_CMD`, since the redirect
    belongs to the shell rather than to the command.
  - **A file entry does not stay a link.** Writers that replace rather than
    update — temp file beside the path, `rename` over the top — turn the symlink
    into a regular file. Claude Code does this to `~/.claude.json`. The path then
    stops persisting to `stateRoot`, and the _next_ activation aborts the whole
    bootstrap: it finds an unmanaged file in the way, tries to back it up, and
    collides with the `.backup` from the previous cycle (reproduced twice).
    `seedEnvLinkTargets` now folds such a file back into its target and leaves the
    path free for Home Manager to relink, newer copy winning and saying so.
    **Residual behaviour, accepted knowingly:** for such a file, persistence is
    now _switch-time_ rather than continuous — the writer keeps replacing the link
    within a session, and each activation folds the result back. Two ways out if
    that ever matters: drop the entry (ADR-0005 called `.claude.json` opaque
    machine state anyway), or create the `$HOME` link directly instead of through
    HM's `home-files` dir, since a one-hop link _does_ survive the rename — which
    is why the pre-HM hand-made links on the reference host never showed this.

  - **`~/.ssh` can lock you out of the machine you are provisioning.** With an
    empty `stateRoot`, the switch moves the host's real `~/.ssh` to
    `.ssh.backup` and points `~/.ssh` at a freshly created empty directory — so
    `authorized_keys` disappears and the next inbound SSH fails. The activation
    now preserves every entry that exists only in the real `~/.ssh` before Home
    Manager places the link; existing entries in `stateRoot/.ssh` win and are
    never overwritten. The first bootstrap therefore retains `authorized_keys`,
    `known_hosts`, and key material without a separate manual seed step.

- **2026-08-05 — supersession executed.** `apply_link_map`, `_link_map_plan`,
  the hand-rolled JSONC parser and `platform/link-map.jsonc` are deleted;
  `DOTFILE_LINK_MAP_JSON` is no longer read anywhere, and the
  `.pre-dotfiles.bak` convention is gone with it (HM's `.backup` is now the
  only backup suffix, as decided). Refinement to the branch split: the
  _default_ entry set — the agent config/state and shell state any environment
  of this repo wants — now lives in `home/env-links.nix` on the shared
  branches, with `state` (the persistent root) as the single line an env branch
  overrides plus its env-only entries appended. The original "placeholder on
  shared branches" shape re-derived the same list per branch, which is the
  drift this ADR exists to prevent. Codex (`~/.codex`) and pi (`~/.pi`) joined
  the set as whole-dir links, on ADR-0011's finding that both rewrite their own
  config at runtime. The out-of-repo copy of the map on the reference host is
  left in place (inert, unread) — cleanup there is an environment step.
- **2026-08-05 — the `home.activation` escape hatch is taken, narrowly.** The
  alternatives table reserved activation scripts for emergencies; seeding
  missing _link targets_ is that case. A dangling out-of-store link is not a
  benign no-op: `mkdir`/`create_dir_all` on one fails with `EEXIST` rather than
  following it (verified), so the tool that owns the path cannot repair it — and
  it never gets the chance, since the HM switch precedes `platform/setup.py`'s
  installs. `home.activation.seedEnvLinkTargets` therefore runs
  `entryBefore [ "checkLinkTargets" ]` and creates only what the entries already
  declare, with a per-entry `kind`/`mode` that is applied on creation only, so
  an existing target's permissions and content are never touched. Scope limit
  that keeps this honest: it creates `state` but **not** `state`'s parent — an
  unmounted volume warns and skips, because `mkdir -p` would otherwise rebuild
  the tree on ephemeral disk and every link would "work" while persisting
  nothing. The entries stay the single declarative inventory; the script only
  makes them true.
- **2026-08-05 — the rebase conflict is removed by splitting the file, not by
  git config.** "Env branches must be rebased over `main`; conflicts are
  confined to `home/env-links.nix`" (above) was accepted as a cost; with the
  shared branch now owning a default entry set _in that same file_, the conflict
  would fire on every rebase. Two git-level fixes were rejected on inspection.
  `.gitignore` cannot work at all: the repo is consumed through a git flakeref
  (`nix build "$REPO_DIR#…"`, which warns "Git tree is dirty"), and under the
  git fetcher an untracked file is invisible to eval — verified: `readFile` on
  an untracked probe fails while a tracked-but-modified file reads fine, so the
  `import` would break. A `.gitattributes` `merge=ours` driver resolves
  _backwards_ under rebase — "ours" is the upstream being replayed onto, so it
  would silently drop the env branch's entries — and the driver itself must be
  configured per clone, failing open to a normal conflict when it is not. So
  the mechanism plus the shared entries stay in `home/env-links.nix`, and
  `home/env-branch.nix` — empty on shared branches, the only file an env branch
  edits — carries the delta via two options (`envLinks.stateRoot`,
  `envLinks.entries`, merged by the module system). Verified with real git: the
  split rebases clean with both changes present, where the single-file shape
  conflicts on the same history. A target outside `stateRoot` (a distributed
  binary) stays a plain `home.file` line there, deliberately outside the
  auto-seeded inventory.
- **2026-08-07 — mise's global config is split across the tiers: settings stay
  Tier A, the tool list becomes Tier B.** "What already lives there (shell, git,
  tmux, starship, mise, packages) stays there" (Tier A, above) is hereby
  **amended for mise only**: a read-only `config.toml` store link makes
  `mise use -g`, `mise up --bump` and `mise unuse` all unusable — the same
  runtime-writes-vs-store-link tension this ADR already recognised for Claude,
  and the owner asked for the mise half to be resolved the other way. The
  deferral for Claude is untouched.

  mise happens to have exactly the seam this needs, and the split follows it
  (all four facts measured against mise 2026.7.0, not read off the docs):
  - mise reads **both** `~/.config/mise/config.toml` and
    `~/.config/mise/conf.d/*.toml` as global config, and `mise use -g` writes
    **only** `config.toml`. So `conf.d` is a place Home Manager can own without
    taking the file mise wants to rewrite.
  - within the global config, a `conf.d` file **always overrides**
    `config.toml`, whatever it is named (`00-` and `zz-` behave identically);
    mise even says so — `X is defined in conf.d/… which overrides the global
config`. That is right for settings and disqualifying for tools, which is
    what forces the split rather than merely permitting it: policy
    (`experimental`, `npm.package_manager`) goes to `conf.d` and keeps flowing
    on every switch; the tool list goes to `config.toml` and is seeded once.
  - _within_ `conf.d`, the lexically **first** filename wins. The HM-owned file
    is therefore named `zz-dotfiles.toml`, so the host-local `conf.d` escape
    hatch the READMEs document still beats it.
  - the HM module writes `config.toml` only when `programs.mise.globalConfig` is
    non-empty (home-manager `modules/programs/mise.nix`), so leaving that option
    unset — rather than any override or force — is what hands the file over.

  Mechanically this needed no new escape hatch: the tool list is a Tier B entry
  (`.config/mise/config.toml`) reusing `seedEnvLinkTargets`, so runtime pins also
  persist to `stateRoot`. Note this entry does **not** hit the residual behaviour
  recorded above for `.claude.json`: mise rewrites the file **in place**, so both
  link hops and the inode survive `mise use -g` and `mise unuse` (measured), and
  persistence stays continuous rather than switch-time — the regular-file repair
  is there for it but should never fire. Two small extensions to the mechanism:
  `install -D`, because this is the first entry whose name is _nested_ rather
  than a top-level dotfile; and a `seedSource` option taking the seed from a
  generated file instead of a string, so `home/mise.nix` keeps its tools as a
  reviewed Nix attrset (`pkgs.formats.toml` generates the seed) —
  `builtins.readFile` on that derivation would have worked but pulls
  import-from-derivation into flake eval. The entry is declared in
  `home/mise.nix` beside the content it seeds, the third "where to add an entry"
  case now documented in `home/env-links.nix`.

  **Accepted cost, stated plainly:** a tool added to `home/mise.nix` no longer
  reaches a host that has already bootstrapped — seeding is creation-only, so the
  repo is that host's _initial_ tool list, not its live one. Both READMEs, the
  `just runtimes` recipe comment and the `setup.py` plan wording say so rather
  than implying the old "every host, after `mise install`". **Future work if that
  stops being acceptable:** have `setup_runtimes` reconcile _additions_ only —
  `mise use -g` for a declared tool absent from `config.toml`, never touching a
  version already there — which would restore propagation without taking back
  ownership. Not built now; it needs the declared versions, and `_mise_tools()`
  deliberately extracts only names.
