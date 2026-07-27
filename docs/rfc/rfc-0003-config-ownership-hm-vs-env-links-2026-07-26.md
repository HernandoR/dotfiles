# RFC-0003: Config ownership split — Home Manager declarative config vs. env-specific mutable links

- Status: Resolved
- Date: 2026-07-26
- Owners: HernandoR

## Summary

Re-partition ownership of everything currently folded into `$HOME` by the
ADR-0008 link map. Portable, declarative configuration (notably most of Claude
Code's config) moves into Nix / Home Manager modules; mutable state and
secrets that must stay on persistent storage remain symlinks, but declared in
a dedicated **env-specific Home Manager module** (via
`config.lib.file.mkOutOfStoreSymlink`) instead of the imperative Python link
map. Environment differences (e.g. corp-intranet hosts) are carried as git
branches of that module, not as out-of-repo config files.

## Motivation

Three problems have surfaced since ADR-0008 landed (2026-07-20):

1. **The link map drifts from reality.** On the reference host, `/root` has
   two symlinks (`.jcc.yaml`, `.lark-cli`) that exist in *neither* copy of the
   map — they were created by hand on 2026-07-21 and never recorded. Worse,
   the two copies of the map have themselves diverged: the live map
   (`/fsx/hernando/local/dotfile_link_map.jsonc`) carries a `jcc` binary entry
   (`~/.local/bin/jcc`) that the repo's `platform/link-map.jsonc` lacks. An
   out-of-repo, hand-edited config file has no review loop and no single
   source of truth — the drift is structural, not accidental.

2. **Declarative config is managed imperatively.** Claude Code's
   `settings.json` (enabled plugins, marketplaces, theme, permissions, model)
   is plain declarative data, yet it lives inside the whole-dir `.claude`
   symlink, *and* `setup_claude` in `platform/setup.py` re-installs the same
   plugins/marketplaces with imperative `claude plugin install …` calls
   (ADR-0005). Two mechanisms express one intent; Home Manager can express it
   once.

3. **Genuinely mutable state is mixed in with config.** Shell history, Claude
   memory/sessions/credentials, `~/.jcc.yaml` (contains a bearer token),
   `.lark-cli` (auth + cache) must stay writable and must survive container
   recreation — they can never be read-only Nix store links. Today the
   whole-dir symlinks conflate this state with the config sitting next to it.

## Current state inventory

Every link on the reference host (`/root` ↔ `/fsx/hernando/…`), classified:

| Target | In map? | Nature | Proposed owner |
|---|---|---|---|
| `~/.claude` (dir) | yes | **mixed**: config (`settings.json`, `CLAUDE.md`) + state (`projects/…/memory`, `sessions`, `history.jsonl`, `.credentials.json`, `plugins`, …) | split — see below |
| `~/.claude.json` | yes | runtime state (onboarding, MCP auth cache) | env-links module |
| `~/.agents` (dir) | yes | mutable skills/state | env-links module |
| `~/.ssh` (dir) | yes | secrets, per-host | env-links module |
| `~/.zsh_history` | yes | mutable state | env-links module |
| `~/.zcompdump` | yes | regenerable cache (kept for startup speed) | env-links module |
| `~/.jcc.yaml` | **no — drift** | secret (token) + env-specific endpoint | env-links module |
| `~/.lark-cli` (dir) | **no — drift** | auth + cache, env-specific | env-links module |
| `~/.local/bin/jcc` | live map only — **drift** | env-specific binary | env-links module |

## Research: what Home Manager actually provides

Verified against Context7 (`/nix-community/home-manager`) and the HM source
(master, which `flake.nix` tracks), 2026-07-26:

- **`home.file.<name>` / `xdg.configFile.<name>`** link files into `$HOME`
  *through the Nix store* — targets become read-only store symlinks. Options:
  `source`, `text`, `recursive`, `executable`, `force`, `onChange`.
- **`config.lib.file.mkOutOfStoreSymlink "/abs/path"`** is the sanctioned
  escape hatch for mutable targets: the `$HOME` link resolves (via one store
  indirection) to the out-of-store path, which stays writable. Gotchas:
  - The argument must be an **absolute path as a string**. A Nix *path
    literal* (`./foo`) is copied into the store when the flake is fetched, so
    the link silently points back into the immutable store. No `--impure`
    needed for plain strings.
  - The destination need not exist at build time (dangling links are allowed);
    content changes never trigger rebuilds. Works for directories.
- **`home.activation`** DAG entries after `writeBoundary` may run arbitrary
  idempotent shell (with `run`/`$DRY_RUN` dry-run support) — a fallback if
  declarative linking ever falls short.
- **`programs.claude-code`** exists: shipped in release-25.11, substantially
  extended on master (which we track). It manages `settings.json` (free-form
  attrs → `pkgs.formats.json`), `plugins` + `marketplaces`, `context`
  (→ `~/.claude/CLAUDE.md`), `rules`, `agents`/`commands`/`skills`,
  `mcpServers`, and a `configDir` option. Everything it writes is a
  **read-only store link**.

Conclusion: HM natively covers both halves — declarative config via modules
(`programs.claude-code` etc.) and mutable links via
`home.file` + `mkOutOfStoreSymlink`. The Python link map duplicates the
latter with a weaker feedback loop.

## Proposal

### 1. Ownership rule (two tiers)

- **Tier A — portable declarative config** → Home Manager modules in-repo,
  shared across environments (main branch). Examples: Claude Code settings,
  plugin/marketplace list, `CLAUDE.md`, and anything else currently reachable
  only through a symlinked dir but semantically config.
- **Tier B — env-specific mutable state & secrets** → symlinks to persistent
  storage, declared in **one dedicated HM module** (working name
  `home/env-links.nix`) using `mkOutOfStoreSymlink` with absolute string
  paths. Everything in the inventory table above marked "env-links module"
  lands here.

### 2. Env-specific module, branch-managed

`home/env-links.nix` is deliberately the *only* env-specific file. On `main`
it holds an empty/no-op default (or a documented example). Environment
branches (e.g. the corp-intranet branch) override it with their real
`/fsx/...` paths and any extra env-only entries (`jcc` binary, `.lark-cli`,
`.jcc.yaml`). Rebase/merge conflicts are confined to this one module, which is
the point: the env delta is *visible as a diff* instead of hidden in an
out-of-repo JSONC file.

### 3. Invert the `.claude` link

`programs.claude-code` wants to own individual files *inside* `~/.claude` as
store links. That is incompatible with `~/.claude` being one whole-dir symlink
onto `/fsx`: HM would write host-specific store links *through* the symlink
into the shared persistent dir (dangling after container recreation until the
next switch, and fought over if two hosts ever share the dir). So invert:

- `~/.claude` becomes a **real local directory**; HM materializes the config
  files in it (`settings.json`, `CLAUDE.md`, plugins/marketplaces wiring).
- The **state subpaths** are individually linked out to
  `/fsx/…/dotfile_home_link_src/.claude/…` via the env-links module. Candidate
  list (exact set is an open question): `projects/` (holds per-project
  memory), `sessions/`, `session-env/`, `history.jsonl`, `.credentials.json`,
  `file-history/`, `tasks/`, `jobs/`, `todos/`, `shell-snapshots/`,
  `skills/`, `plugins/`.

### 4. Seed the Nix config from the live config

Initial `programs.claude-code.settings` values are extracted from the current
live `settings.json` (enabledPlugins, extraKnownMarketplaces, theme,
permissions, model), split into the shareable part (plugins, marketplaces,
permission mode → Tier A, main branch) and anything env/personal (goes to the
env branch or stays out). The same extraction pass reviews the rest of the
inventory for further Tier-A candidates.

### 5. Retire the Python link map

Once the env-links module covers the inventory, `apply_link_map` /
`DOTFILE_LINK_MAP_JSON` / both copies of the JSONC map are removed
(superseding ADR-0008). Ordering even improves: the HM switch runs *before*
`setup.py`, so links exist earlier in bootstrap than they do today.

## Alternatives Considered

| Alternative | Why not |
|---|---|
| Keep the Python link map, just re-sync it | Fixes today's drift, not the mechanism that produced it; still two link systems (HM + Python), still an out-of-repo config file with no review loop. |
| Env differences via flake host attrs / specialArgs instead of branches | Every env's paths (incl. corp-internal hostnames/mount points) become visible on `main`; branches keep corp details off the public history. Cost: rebase discipline — accepted. |
| Env differences via a gitignored local `.nix` file imported when present | Reintroduces exactly the out-of-repo-drift problem this RFC is fixing; also impure imports are awkward in flakes. |
| Manage *all* of `.claude` declaratively (no state links) | Memory/sessions/credentials must survive container recreation and be writable; store links are read-only and `/nix` may be ephemeral. Impossible by construction. |
| Keep whole-dir `.claude` symlink; skip `programs.claude-code` | Loses the declarative settings/plugin management that motivates Tier A; `setup_claude`'s imperative plugin installs stay. Viable fallback if the module proves immature — recorded as a risk. |
| `home.activation` script instead of `mkOutOfStoreSymlink` for Tier B | Imperative inside the declarative layer; bypasses HM's collision checks and generation cleanup. Reserve as escape hatch only. |

## Risks

- **`settings.json` becomes read-only.** In-app `/config` changes (theme,
  model) will no longer persist — they must be edited in Nix and re-switched.
  Acceptable for a declared-config workflow, but a real ergonomic change.
  (Claude Code's *runtime* state writes go to `~/.claude.json` and state
  subdirs, which stay writable.)
- **State-subpath list is a moving target.** Claude Code adds new state dirs
  over versions; a new unlisted one silently becomes ephemeral (lost on
  container recreation) until added to the env-links module. Mitigation: a
  periodic drift check (compare `ls ~/.claude` against the declared set) —
  cheap to script.
- **`programs.claude-code` on master is unstable.** Options were restructured
  between 25.11 and master and may drift again; the flake follows master, so a
  `flake.lock` bump can break the module surface. Mitigation: pin/bump
  deliberately, and the fallback alternative above.
- **Migration collisions.** Existing correct symlinks at `~/.ssh` etc. are
  "unmanaged files" to HM's `checkLinkTargets`; the bootstrap's `-b backup`
  equivalent handles them, but the first switch will shuffle links — needs a
  dry-run first (`home-manager switch -n` / bootstrap `--dry-run`).
- **`.ssh` via a store indirection**: unchanged from ADR-0008 in substance —
  SSH checks perms on the final target (`700`/`600` on `/fsx`), and the extra
  store hop is a world-readable *symlink*, not key material.

## Open Questions

- Exact state-subpath set for `.claude` (see candidate list above) — decide at
  implementation time by auditing a live `~/.claude`.
- Should `.zcompdump` stay persisted at all, or be dropped (regenerable) to
  shrink the env module?
- Does `programs.claude-code`'s `plugins`/`marketplaces` management fully
  replace `setup_claude`'s imperative installs, or only the marketplace/enable
  part (leaving first-fetch to the CLI)? Determines how much of ADR-0005
  survives.
- Naming/placement of the env module (`home/env-links.nix` vs `home/env/`
  scope) and whether the `generic` impure host wires it automatically.

## Acceptance Criteria

- [ ] A fresh bootstrap on the reference host produces every link in the
  inventory table with **no** `DOTFILE_LINK_MAP_JSON` set.
- [ ] `~/.claude/settings.json` and `~/.claude/CLAUDE.md` are HM-managed;
  plugins/marketplaces come from Nix, and `setup_claude` no longer runs
  `claude plugin install` for them.
- [ ] Claude memory, sessions, credentials, and shell history survive a
  container recreation + re-bootstrap.
- [ ] `main` contains no corp-specific absolute paths; the corp branch's env
  delta is confined to the env-links module.
- [ ] `apply_link_map` and both JSONC maps are deleted; ADR-0008 is marked
  superseded.

## Rollout

Phased, each phase leaving the system bootable:

1. Add the env-links module carrying exactly today's live links (including the
   drift entries `.jcc.yaml`, `.lark-cli`, `jcc`) — link map still active but
   redundant.
2. Land `programs.claude-code` with settings extracted from the live config;
   invert the `.claude` whole-dir link into per-subpath state links; trim
   `setup_claude`.
3. Remove `apply_link_map` + maps; supersede ADR-0008; update ADR-0005.

Code-comment discipline applies throughout (module headers state *why* an
entry is env-specific / what breaks if it's removed), matching the existing
`platform/` and `home/` comment style.

## Update log

- **2026-07-26 — initial draft**, from the six-point direction discussed in
  session (link-map drift, nixify declarative config, HM-managed mutable
  links via `mkOutOfStoreSymlink`, env-specific module on branches, review of
  nix-manageable links, seed from live config). Context7 research findings
  folded into the Research section. Outcome recorded as ADR-0009 (proposed).

- **2026-07-27 — decision grilling; resolved.** Three questions settled with
  the owner, narrowing the proposal:
  - **Q1 — `settings.json` stays a mutable link; Tier A for Claude config is
    deferred.** The decisive fact: everything `programs.claude-code` writes is
    a read-only store link, and the owner actively relies on `/model`/`/config`
    persistence (observed in-session), which such a link breaks. The
    seed+writable-copy middle ground (nix renders, activation installs a real
    writable file, switch re-asserts) was offered and declined — no declarative
    Claude config for now; `setup_claude`'s imperative plugin installs remain;
    ADR-0005 is untouched.
  - **Q2 — `~/.claude` keeps the whole-dir symlink.** With Q1 deferring all
    HM-managed files inside `.claude`, the inversion (real dir + ~12
    per-subpath state links) buys nothing today and costs a migration plus a
    moving-target subpath list. Inversion moves from proposal to future work;
    a side benefit of whole-dir linking is that new Claude-internal state dirs
    persist automatically.
  - **Q3 — the Python link map is deleted; ADR-0008 superseded.** One linking
    mechanism only: after one successful bootstrap on the env branch proves the
    env-links module, `apply_link_map`, `DOTFILE_LINK_MAP_JSON`, the JSONC
    parser, and both map files go; the escape-hatch option (keep deprecated)
    was declined.
  Minor open questions closed without asking: `.zcompdump` stays linked as
  today (zero-risk, revisit later); module is `home/env-links.nix`, imported
  unconditionally, no-op with placeholder example on `main`. Seeding a fresh
  environment's persistent config skeleton (original point 6) reduces, under
  Q1/Q2, to env provisioning — out of scope.

  **Acceptance criteria as resolved** (replacing the draft list above — the
  Claude/HM items no longer apply):
  - Fresh bootstrap on the env branch produces every link in the inventory
    table (incl. `.jcc.yaml`, `.lark-cli`, `~/.local/bin/jcc`) with no
    `DOTFILE_LINK_MAP_JSON` set.
  - Claude memory, sessions, credentials, and shell history survive container
    recreation + re-bootstrap; `/model` and `/config` persistence unchanged.
  - `main` contains no corp-specific absolute paths.
  - `apply_link_map` and both JSONC maps deleted; ADR-0008 marked superseded.
  Outcome: ADR-0009 rewritten atomically to the settled scope and accepted.
