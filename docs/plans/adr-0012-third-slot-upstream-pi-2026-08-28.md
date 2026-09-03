# ADR-0012: The third agent slot is upstream pi, chosen for interoperability and paid for in extensions

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-08-28 |

## Context

ADR-0011 partitioned agent configuration into three planes and gave the
toolchain's third slot to **oh-my-pi** (`omp`) in its 2026-08-06 update entry,
on a feature-by-feature comparison the fork won outright. RFC-0005 reopens that
slot for one reason the comparison never weighed: **what the owner needs from
the third slot is an agent other software can drive.** IDE plugins and
agent-connection clients treat upstream `pi` as the first-class citizen; omp is
absent from every such list.

Four findings from RFC-0005 shape this decision.

**The slot's binary is currently unreachable by anything but an interactive
shell.** omp comes from mise (`home/mise.nix`), and mise's tools reach `PATH`
only through the zsh `mise activate` integration — `home/shell.nix:156-164` puts
`~/.local/bin` and the Nix profiles on `home.sessionPath`, but not mise's shims.
So a VS Code extension host, an editor spawning an ACP server, a `just` recipe
or a systemd unit cannot resolve `omp` by name at all. Claude and Codex do not
have this problem; their installers land in `~/.local/bin`. This is a defect in
the present wiring independent of which agent occupies the slot, and it
constrains the fix: **the third slot's binary must be resolvable outside an
interactive shell, or the switch buys nothing.**

**Upstream pi refuses, by design, four of the capabilities the slot is used
for.** Its README and `docs/usage.md` state that it has no MCP, no sub-agents,
no permission popups, no plan mode, no to-dos and no background bash; it has no
memory backend of any kind and no Claude-Code-style hook engine. Each of those
is a community npm extension. The switch is therefore a **supply-chain trade**,
not a feature trade: one single-maintainer fork for six-or-seven
single-maintainer extensions. The owner chose this knowingly, in the full-parity
form.

**The interoperability premise is half false, and the decision was reaffirmed
after being shown so.** Upstream pi does *not* speak ACP — `--mode` accepts
`text`/`json`/`rpc` only, and native ACP is an open undecided proposal
(earendil-works/pi#4444); ACP is delivered by `pi-acp` v0.0.33, a
single-maintainer adapter. **omp has `omp acp` natively.** What pi wins is
presence and breadth, which no shim can buy: the ACP registry, Zed's docs,
JetBrains Air, agentic.nvim, a Homebrew formula, a nixpkgs attr, a devcontainer
Feature, a GitHub Action, 3+ VS Code extensions, 7 Neovim plugins, 2 Emacs
packages — against omp's zero listings and two registry requests open since May
and June.

**pi has no scriptable config setter.** `pi config` is an interactive TUI
picker; there is no `pi config get`/`set`. `OmpAgent.set_memory_backend`'s
mechanism — project one setting through the agent's own CLI — has no pi
counterpart, and writing `~/.pi/agent/settings.json` is exactly the
agent-config patching ADR-0011 declined. This hard-limits what the third slot
can be given declaratively.

## Decision

> In the context of the third agent slot, whose binary is currently reachable
> only from an interactive zsh and whose occupant is absent from every IDE and
> agent-connection integration list,
> we decided for **upstream pi, installed at a stable path outside the shell,
> with full feature parity bought through its extension ecosystem**,
> and against keeping omp, against a `pi`→`omp` compatibility shim, and against
> projecting any pi *setting*,
> to achieve a third slot that other software can discover and drive,
> accepting a six-to-seven-package third-party dependency surface, the permanent
> loss of the mnemopi memory store, and a preference plane that cannot be
> projected at all.

### The occupant

`PiAgent` replaces `OmpAgent`: `id = "pi"`, `binary = "pi"`,
`config_dir = "~/.pi"`. The `--agents=<spec>` vocabulary becomes
`claude,codex,pi`, with **no alias for the retired `omp` id** — an unknown agent
warns and is skipped. An alias was written and then removed on the owner's call:
`--no-claude` earned its alias by being a *renamed flag* for an unchanged
concept, whereas `omp` names an agent that no longer exists here, and silently
resolving it to a different one would hide the change rather than surface it.

### Install channel — the constraint, not a preference

`npm install -g --prefix ~/.local --ignore-scripts @earendil-works/pi-coding-agent`,
with node resolved through `mise which npm`.

- `~/.local/bin/pi` **is** on `home.sessionPath`, which is the entire point.
- `pi update --self` keeps working: the `--prefix` breakage of
  earendil-works/pi#3942 was fixed in 0.72.0, and
  `dist/config.js:getInferredNpmInstall()` infers the prefix from exactly the
  `<prefix>/lib/node_modules/...` layout `~/.local` produces.
- **The `npmCommand` setting must be left unset** — pi skips prefix inference
  entirely when it is present, which would silently re-break self-update.
- `--ignore-scripts` is pi's own documented recommendation and independently
  avoids the native-postinstall failures of the 2026-08-05 clean-pod run.

Rejected: mise (any backend — reproduces the `PATH` gap being escaped),
`npm -g` under mise's node prefix (same gap; the retired `PiAgent` had this
defect and it was never noticed), the nixpkgs attr (pins the version into the
flake, inverting the standing "versions stay outside git" rule), GitHub-release
Bun binaries (pi returns no self-update path for the `bun-binary` method), and
`pi.dev/install.sh` (picks a prefix of its own choosing).

**Validated on the reference host** (dry-run only, nothing installed):
`npm --prefix ~/.local config get prefix` returns `/root/.local`, and
`npm install -g --prefix ~/.local --ignore-scripts --dry-run
@earendil-works/pi-coding-agent` resolves **0.84.3 as a single package** and
writes nothing. One prerequisite surfaced that would otherwise fail a clean
bootstrap: **`~/.local/lib` must exist first** — without it npm aborts with
`ENOENT … lstat '/root/.local/lib'` before it does anything else. The installer
must `mkdir -p ~/.local/lib`.

The npm helper layer deleted on 2026-08-20 comes back for this —
`ensure_node_on_path` in particular, since pi is a node-shebang CLI and
`shutil.which("npm")` provably fails on a fresh machine.

### The three planes under pi

- **① Instruction.** `~/.pi/agent/AGENTS.md` symlinks to `~/.agents/AGENTS.md`.
  pi loads it as its global context file and concatenates ancestor
  `AGENTS.md`/`CLAUDE.md` below it. The plane stays a genuine three-way single
  point.
- **② Skills.** **No setting is required**: pi implements the Agent Skills
  standard and reads `~/.agents/skills/` natively as a global discovery
  location. `~/.pi/agent/skills` → `~/.agents/skills` is kept as a belt, as it
  was for omp and Codex. One caveat to record: pi ignores root-level `.md` files
  under `~/.agents/skills/` — only `SKILL.md` directories and nested `.md` in
  grouping folders are discovered.
- **② Capability.** Extensions are projected with **`pi install <source>`**,
  which appends to the `packages` array in `~/.pi/agent/settings.json` and
  installs under `~/.pi/agent/npm/`. This is projection through the agent's own
  CLI, exactly as ADR-0011 requires — pi writes its own settings file, we never
  do.
- **② MCP.** `pi-mcp-adapter` reads **`~/.agents/mcp.json` at precedence layer
  2** of six, and never writes back to it — verified against the adapter's own
  README. So `MCP_SERVERS` is projected there by the restored
  `write_shared_mcp`, the file stays repo-owned, and the MCP plane is a genuine
  three-way single point again with no new ownership. Two conditions:
  `hostConfigDiscovery` stays at its default `off` (turning it on re-imports
  whatever Claude and Codex happen to have — the drift-import this repo already
  declined once), and the adapter's `settings` block belongs *inside* the
  `mcp.json` files, not in `settings.json`.

  Two entries live here after this change: `codegraph` (delegated to its own
  installer) and the shared **`memory`** server above, which is the first
  env-carrying entry Claude's projection has ever had — the argument-order fix
  from 2026-08-13 was written for exactly this.

  **This file is already drifted and must be reconciled.**
  `~/.agents/mcp.json` still declares `agentmemory` at
  `http://localhost:3111`, retired on 2026-08-20 but never removed because
  projection is add-only. Nothing serves that port. Left alone, pi inherits a
  dead MCP server on its first session. Reconciling the file to the manifest is
  part of this change — the first time ADR-0011's acknowledged add-only gap has
  actually cost something.

- **② Marketplaces and plugins — projected, and now genuinely three-way.**
  `pi-claude-marketplace`'s `~/.pi/agent/claude-plugins.json` is documented in
  its own source as "the USER-AUTHORED desired state" against a deliberately
  lenient schema:
  `{schemaVersion: 1, marketplaces: {<name>: {source, autoupdate?}}, plugins:
  {"<plugin>@<marketplace>": {enabled?}}}`. The plugin key is **exactly**
  `Plugin.qualified()` in `agents.py` and **exactly** Claude's own
  `enabledPlugins` key format, so `MARKETPLACES` + `PLUGINS` are isomorphic to
  this file and it is generated from them.

  This is what finally makes marketplaces and plugins a **three-way** single
  point — Claude via `claude plugin install`, Codex via `codex plugin add`, pi
  via one generated declarative file. omp could never have this.

  **Ownership split:** the repo owns the base `claude-plugins.json`; the machine
  owns `claude-plugins.local.json`, whose entries *replace* same-keyed base
  entries wholesale. The extension patches the base only on explicit mutating
  commands, at entry level, preserving unknown keys, and carries an explicit
  architectural guard against ever serializing a merged view back over the base
  — so re-projection cannot stomp a deliberate per-machine deviation, and the
  extension cannot absorb the override layer.

  Pinning: plugin versions are deliberately absent from this file (a machine
  fact in the extension's `state.json`); marketplace pinning is a git ref inside
  `source`. The repo's bare `owner/repo` entries therefore float the default
  branch — the same trade the Claude and Codex projections already make.

- **Extension config — a fourth category, with a rule.** ADR-0011 knows agent
  config (never touched) and the manifest (projected by CLI). pi's extensions
  introduce files owned by neither, and they are not one thing:
  `~/.agents/mcp.json` and `claude-plugins.json` are declarative desired state
  the repo can author → **projected**; everything else
  (`~/.pi/web-search.json`, plannotator's json, per-extension `config.json`) is
  per-extension tuning → **left manual and documented**. The line is drawn at
  "is this file isomorphic to something the manifest already declares?", not at
  "does the extension ever write it" — because with `--local` and entry-level
  patching, co-ownership is expressible here in a way it is not for agent
  config.

- **③ Preference — seeded, not owned.** On the owner's call, pi is configured by
  a **written preset** rather than interactively: the repo supplies initial
  values in `~/.pi/agent/settings.json` and the host owns them from then on.

  This deliberately relaxes ADR-0011's "never write an agent's config file" for
  pi, and it keeps that rule's actual protection. The danger was a projection
  that *re-asserts* every bootstrap and destroys `/model`, `/theme` and
  `pi install` changes. The contract here is **seed**, not own — and seed
  semantics already exist in this repo: `home/mise.nix` seeds
  `~/.config/mise/config.toml` for exactly this reason, and `home/env-links.nix`
  has a `seed`/`seedSource` option, used for `.claude.json`.

  **The contract is per-key, split by plane.** One uniform merge rule was tried
  and falsified on this host (RFC-0005, the stale-`~/.pi` entry):

  - **`packages` is plane ② capability, not preference.** It is the manifest's
    own content expressed in pi's file, so it is **repo-owned and reconciled** to
    the manifest list. This is also the only way a *dropped* package can ever
    leave, since add-only projection cannot remove one.
  - **Every other key is plane ③** — `modelRoles`, `theme`, thinking level, edit
    mode, provider blocklist — and gets an **add-only leaf-level seed**: written
    when the file does not already carry that leaf, never overwritten. Nested
    objects merge per leaf, so adding one `modelRoles` entry cannot wipe the
    others. This is the same add-only contract `write_omp_mcp` already used
    against a file omp itself rewrites.

  With no `pi config set`, this is the only mechanism available — but it is now
  sufficient, which is why RFC-0005's earlier conclusion ("the capabilities can
  be projected, the tuning cannot") is **withdrawn**. The measured omp
  `config.yml` inventory becomes the preset's content, so a new machine comes up
  already tuned. The rule extends to per-extension config files
  (`~/.pi/web-search.json`, plannotator's json) for the same reason: the owner's
  decision is about *how* pi is configured, not about which file.

  Accepted cost, already on record for seeds in ADR-0009's update log
  (2026-08-07): a preset value **changed** later reaches an
  already-bootstrapped host only when someone re-applies it. Leaf-level merging
  narrows this — newly *added* keys do propagate; only changed values do not.

  **pi's own write path makes this safe, verified in `dist/`.**
  `persistScopedSettings` takes a file lock, **re-reads the file from disk**,
  and copies in only the fields modified in that session; unknown keys ride
  through untouched and nested objects merge key-by-key. There is no schema, no
  `$schema`, no `schemaVersion`, and a partial file is fully valid. A malformed
  file is never clobbered but is *entirely ignored*, so the seed must emit strict
  JSON — no comments, no trailing commas. Formatting normalises to 2-space indent
  on pi's first write, which is fine for a generated file. Legacy key spellings
  (`queueMode`, `websockets`, `retry.maxDelayMs`) are silently migrated on every
  load and must not be seeded.

  **`packages` is acted upon, not merely recorded — which removes work.** At
  startup pi resolves the array with no `onMissing` callback and installs any
  missing or version-mismatched npm package unconditionally, guarded only by
  `PI_OFFLINE`. So seeding `packages` **replaces the `pi install` projection
  entirely**: pi installs the nine extensions itself on first launch. That takes
  nine subprocess calls out of the bootstrap and removes a failure mode — a
  `pi install` dying mid-run and leaving a partial set. `pi install` stays the
  right tool for a human adding one later, since it also mutates the array.

  **The `npm:` prefix is mandatory and omitting it fails silently.** Anything not
  prefixed `npm:`/`git:`/`github:`/`http:`/`https:`/`ssh:` is parsed as a local
  path, and an absent local path is skipped **without warning** — so
  `["pi-mcp-adapter"]` installs nothing and reports nothing. `docs/settings.md`'s
  own example is wrong on this point. Every emitted entry is `npm:<name>`.

  **Three corrections to what the omp inventory can carry over**, because the
  seed's value depends on them:

  - **`modelRoles` has no upstream equivalent.** omp's `--smol`/`--slow`/`--plan`
    flags and `PI_SMOL_MODEL`/`PI_SLOW_MODEL`/`PI_PLAN_MODEL` env vars are fork
    additions — grepping pi 0.84.3's whole tarball for them returns zero hits. pi
    has one model, as **two keys** with a **bare id**: `defaultProvider:
    "anthropic"` + `defaultModel: "claude-opus-5"`. The eight roles are remapped
    onto `pi-subagents`' `subagents.agentOverrides.<agent>` block — which pi
    preserves as an unknown key — against a *different vocabulary* (`oracle`,
    `reviewer`, `worker`, `delegate`, `researcher`, `scout`, …). The capability
    survives; it is a remap the owner should review, not a rename.
  - **`defaultThinkingLevel: auto` is invalid** in pi (`off|minimal|low|medium|
    high|xhigh|max`). The seed uses `medium`.
  - **`theme` is one string**, `"<light>/<dark>"`, and **`titanium` is not a
    built-in** — it needs `~/.pi/agent/themes/titanium.json` or the value changes.

  Accepted losses with no equivalent anywhere in pi or the nine extensions:
  `symbolPreset`, `autolearn`, `github`, `composer`, `setupVersion`, and the
  `mnemopi` block. `disabledProviders` (~80 ids) also has no equivalent and is
  mostly moot — pi only offers providers with saved credentials.

### Memory — two layers, and the shared one lives in `~/.agents`

pi has no native memory backend, so memory is entirely extension and MCP
territory. It is built as two layers.

**Shared layer — `@modelcontextprotocol/server-memory` 2026.7.4, store at
`~/.agents/memory/memory.jsonl`.** One `McpServer` manifest entry reaching all
three agents: `claude mcp add`, `codex mcp add`, and `~/.agents/mcp.json` for pi
through `pi-mcp-adapter`. Nine tools over a knowledge graph of entities,
relations and observations.

`~/.agents` is the right home for it, not merely a tidy one. That root is already
an ADR-0009 Tier-B env link whose target is on **Lustre**
(`/fsx/hernando/dotfile_home_link_src/.agents`), so the store is **cross-machine
by construction — no service, no credential, no egress.** The mechanism that
already single-sources instructions and loose skills now single-sources memory,
and the cross-machine property comes from this repo's own env-link inventory
rather than from a vendor.

`MEMORY_FILE_PATH` **must be absolute** — a relative value resolves against the
package directory, and the default store sits inside that directory where an
`npx` reinstall would discard it. The manifest computes the path from `HOME`.

**Local layer — `pi-memory` 0.4.2** for pi only: markdown and JSON under
`~/.pi/agent/memory/`, zero config, no daemon, no native build, no extra
credential. Note that this is "local" in the sense of *one agent*, not *one
machine*: `~/.pi` is also an env link, so it is on Lustre too.

**Claude's built-in memory stays off** (`autoMemoryEnabled: false`) by the
owner's decision. It is preference plane, so this repo does not project it; the
shared graph is what replaces it.

**mem0 was investigated and declined** (RFC-0005). Its mechanism was the best
found — cloud-only credential, hosted HTTP MCP needing no local process, and
first-party plugins for all three agents including lifecycle hooks. It was
declined on data governance: `add()` transmits raw conversation turns, OpenAI and
Anthropic are named subprocessors, there is no EU region, and the free tier's
content is training corpus. Hosts holding intranet content disqualify it
regardless of mechanism. Connectivity was checked first and was *not* the reason —
both endpoints answer 401 from the reference host.

**Accepted risk, stated precisely: the shared store has no write locking.**
`dist/index.js` reads the whole file and writes it back whole, inside the server
process. So:

- The failure mode is **silent loss of a concurrent writer's recent additions**,
  not a corrupt file — each write emits a complete buffer.
- **The likely collision is same-host, not cross-host**: Claude, Codex and pi each
  spawn their own server process, so three writers to one file on one machine is
  the normal case.
- **No external wrapper can fix it.** A `flock` around the command would hold the
  lock for a whole session and block the other agents; the race is inside a single
  function. Making it safe means a small fork patching that function.
- The mitigation taken is to accept it and rely on the same one-writer-at-a-time
  reality the Lustre stateRoot already depends on for `agent.db`, `mnemopi.db` and
  Claude's state. Memory-tool calls are infrequent, so the window is narrow.

**What is given up against mem0:** no embeddings and no semantic search
(`search_nodes` is substring matching, not vector similarity), and no automatic
capture — nothing is written unless a model calls a tool.

**The mnemopi banks are exported, not migrated.** mnemopi exists only as the
fork's `@oh-my-pi/pi-mnemopi` and nothing upstream can read its store. Measured
scope (RFC-0005, after correcting a first undercount): **430 content rows across 8
non-empty banks**, 5 empty — including `dotfiles` and `shared`, the two that
sounded most valuable. The durable content is the `memoria_facts` /
`memoria_instructions` / `memoria_kg` extractions; `working_memory` is largely raw
transcript and `facts` duplicates `memoria_facts`. mnemopi ships an undocumented
`mnemopi export <file.json>` in its CLI, so the export is a JSON transform rather
than SQL against an undocumented schema. Output goes to
`~/.agents/memory-archive/<project>.md` — greppable by all three agents,
deliberately **not** auto-loaded as context, and portable across the next backend
change.

**Sequencing:** the `.omp` env link points at
`/fsx/hernando/dotfile_home_link_src/.omp` (1.1 GB, outside `$HOME`), so dropping
the entry unlinks but does not delete — the banks are not at risk from the switch
itself. The export must precede **deletion of that stateRoot directory**, a
separate manual cleanup. It is called out here so the cleanup is not done first by
someone assuming the data was already gone.

### The parity extension set

Projected with `pi install npm:<pkg>`, one manifest entry each. The full-parity
posture is the owner's decision; the *composition* below is forced by peer
dependencies and tool-name collisions more than by preference.

| Package | Version | Replaces (omp native) | Note |
|---|---|---|---|
| `pi-mcp-adapter` | 2.29.0 | native MCP client | reads `~/.agents/mcp.json`, layer 2 of 6 |
| `pi-subagents` (unscoped) | 0.58.0 | native sub-agents | **forced** — the only package satisfying the marketplace's `pi-subagents >= 0.35.0` peer |
| `pi-memory` | 0.4.2 | `memory.backend = mnemopi` (local layer) | one agent, not one machine; the shared layer is the `memory` MCP entry |
| `pi-claude-marketplace` | 0.17.0 | `claude` / `claude-plugins` discovery | config **is** projected — `claude-plugins.json` from the manifest |
| `pi-web-access` | 0.25.0 | native browser / web search + intranet fetch | all web access; keyless and model-independent (see the update log for why `pi-web-search` went) |
| `pi-hide-providers` | 0.1.15 | `disabledProviders` | the provider fence pi has none of; monkey-patches `ModelRuntime` — risk named in the update log |
| `pi-lens` | 4.1.2 | native LSP + diagnostics | no CI; pins `pi-tui ^0.84.1`; rewrites source |
| `@plannotator/pi-extension` | 0.27.9 | plan mode | set `model: null`; needs a browser |
| ~~`pi-background-tasks`~~ | 2.4.2 | background bash | **retired 2026-09-03** — dropped by hand on the reference host; see the update log |
| `pi-token-usage-statistics` | 0.2.0 | — (omp had a `/usage` view) | per-session token/cost ledger, no egress, no config; adopted 2026-09-03 |

Three constraints that are decisions, not details:

- **Loose sub-agent definitions cannot be single-sourced — but there are none.**
  No sub-agent package reads `~/.claude/agents/`; the advertised "Claude Code
  compatibility" is format-level only, so loose user-level agents would have to
  be copied and translated into `~/.pi/agent/agents/*.md`. Measured on this host:
  **`~/.claude/agents/` does not exist**, and *plugin-provided* agents are
  installed there automatically by `pi-claude-marketplace`. So the burden is
  currently nil and the gap is latent, not active.
- **Web access is one package, not two.** `pi-web-search` and `pi-web-access`
  collide on the `web_search` tool name — fatally, as it turned out — and the
  collision was resolved by dropping the former; see the update log.
  `pi-tinyfish` and `pi-brave-search` are **dropped**, not restored: both need a
  third-party key, both are ~3.5 months stale at 29–60 downloads/week, and both
  are already providers inside `pi-web-access`.
- **`@gotgenes/pi-permission-system` is excluded** — not as a scope reduction.
  It integrates with `@gotgenes/pi-subagents`, which the forced sub-agent choice
  rules out; and it would be a **second approval broker over the same MCP calls**
  as `pi-mcp-adapter` ("first synchronous claim wins"), with no documented
  coordination protocol. Untested concurrency at a security boundary is not a
  parity feature.

**Resolved by reading the extension's shipped source, not its README:**
`pi-claude-marketplace` **never reads `~/.claude/plugins/cache`**. It is an
independent marketplace client that clones from git into its own
`sources/`/`plugin-clones/` tree and parses only the `.claude-plugin/*.json`
*format*. Claude's version-bearing cache layout is therefore irrelevant to it,
and the concern that made ADR-0011 decline a single shared skills root **does not
transfer**. Its one read of Claude's own config is `/claude:plugin import`, which
reads `~/.claude/settings.json` and `settings.local.json` read-only (honoring
`CLAUDE_CONFIG_DIR`) — useful for one-shot seeding, not the mechanism.

**Prerequisite this exposes, and it is not optional.** The manifest has drifted
behind the machine again: the live `~/.claude/settings.json` declares **5**
marketplaces and **13** plugins where the repo declares 4 and 7 —
`mewtant-plugins` plus `reclaim-code-entropy`, four `mewtant-plugins` plugins and
`pyright-lsp@claude-plugins-official` exist only on the machine. Generating
`claude-plugins.json` from a stale manifest would hand pi *seven* plugins where
Claude has *thirteen*, i.e. ship a smaller skill set than Claude's — the opposite
of the skill-sync this switch is for. **Reconciling the manifest to the live set
comes first.** `pyright-lsp` needs its own call, since its marketplace is a
Claude builtin that may have no Codex or pi equivalent.

Two feared costs measure **zero on this host today, and stay latent**: there is
no `~/.claude/agents/` directory, and no cached plugin ships an `agents/` dir or
a `.mcp.json` — so the agent-translation burden is currently empty
(plugin-provided agents are installed automatically into `~/.pi/agent/agents/`)
and the unnamespaced MCP-name collision that aborts an import has nothing to
collide with. One precedence note for later: the bridge writes
`~/.pi/agent/mcp.json`, **layer 4**, which outranks the manifest's
`~/.agents/mcp.json` at layer 2.

### omp's retirement

- `home/mise.nix` loses the `github:can1357/oh-my-pi` seed, so no new machine
  gets omp.
- `home/env-links.nix` loses `.omp` and gains `.pi` (whole dir, mode 700 — it
  holds `auth.json`, `trust.json`, sessions, and the `npm/` and `git/` extension
  installs, so it must persist as a unit; `pi-acp` also writes a hard-coded
  `~/.pi/pi-acp/`, and `pi-web-access` writes `~/.pi/web-search.json` — note *not*
  under `~/.pi/agent/` — both of which land inside the same link).
- **`~/.pi-lens` needs its own entry.** `pi-lens` keeps its global config at
  `~/.pi-lens/config.json`, outside `~/.pi`, so without an entry it dies with
  every container recreation.
- **The stale pre-omp `~/.pi` is reset, not reused.** stateRoot still holds a
  complete pi tree from 2026-08-06 03:54 — 171 MB, whose `settings.json` declares
  the old four packages *including `pi-tinyfish`*, and whose `node_modules` holds
  `pi-mcp-adapter` 2.20.1, `pi-subagents` 0.41.0 and `pi-claude-marketplace`
  0.13.0. It carries no `auth.json`, no sessions and no memory, so nothing is
  lost by renaming it to `.pi.pre-omp-2026-08-06.bak` (an instant, reversible
  rename on Lustre) and letting the bootstrap build fresh. Leaving it in place
  would defeat the plane-③ seed on its first and most important run — the
  `packages` key would already exist. Its only valuable contents, the `AGENTS.md`
  and `skills` symlinks into `~/.agents`, are still intact and are re-created by
  `PiAgent.project` anyway.
- Consistent with ADR-0011's standing rule, **retirement on an
  already-provisioned machine stays manual**: projection is add-only, so the
  reference host keeps its omp binary, its `~/.omp` directory and its mise entry
  until the owner removes them. This is deliberate — it is also what keeps the
  memory archive recoverable and the `PI_ACP_PI_COMMAND=omp` fallback available
  during the transition.

### Supersession

ADR-0011 **remains accepted**: its three-plane partition, add-only projection
rule, dual-track skills decision and `--agents` selection all survive this
change untouched, which is the strongest available evidence that the structure
was right. What this ADR supersedes is narrower and named precisely:

- the **2026-08-06 update entry** (third slot = omp; the pi extension set
  retires), and
- the **2026-08-20 update entry** (memory = omp-native mnemopi).

ADR-0011 is atomically edited to remove those two entries' now-stale claims from
its body and point here instead, rather than being left half-current.

## Consequences

- **The third slot becomes discoverable and drivable by other software** — the
  one thing it could not do before. Registry-driven ACP install, the editor
  plugins, the devcontainer Feature and the GitHub Action all become available
  without per-machine glue.
- **The dependency surface grows from one fork to a fork's worth of
  extensions.** Every parity feature now has its own maintainer, release cadence
  and failure mode, and a pi minor bump can break any of them independently.
  This is the accepted price of the switch and the thing most likely to generate
  future work.
- **Single-maintainer risk is redistributed, not escaped.** All sixteen
  candidate packages are bus-factor 1, and `pi-mcp-adapter`, `pi-subagents` and
  `pi-web-access` — three of the highest-traffic dependencies — share one
  maintainer, one release cadence and one bus factor. `pi-lens` and
  `@plannotator` have no CI signal at all, and the first rewrites source files.
- **The preference plane is now unprojectable, not merely unprojected.** Anyone
  provisioning a new machine gets a working pi with the right capabilities and
  none of the owner's tuning. The RFC's recorded `config.yml` inventory is the
  only mitigation, and it is documentation, not mechanism.
- **Memory is discontinuous.** Whatever extension is chosen starts empty, and
  the archive is a read-only artifact no agent consults automatically. The honest
  read from the measurement is that little of value is lost.
- **Memory is cross-agent again, with zero egress and no service.** One
  `MCP_SERVERS` entry gives Claude, Codex and pi a shared knowledge graph at
  `~/.agents/memory/memory.jsonl`, cross-machine because `~/.agents` is already a
  Tier-B env link onto Lustre. No credential, no vendor, no daemon — the
  cross-machine property is supplied by this repo's own inventory. That is a
  better position than the agentmemory era, which needed a supervised process
  these hosts cannot run, and better than mem0, which needed a US cloud account
  and shipped raw transcripts to it.
- **The shared store trades away semantic search and safe concurrency.** No
  embeddings — `search_nodes` is substring matching. No automatic capture: nothing
  is written unless a model calls a tool. And the server read-modify-writes the
  whole file with no lock, so two concurrent writers silently lose one side's
  recent additions; the likely case is three agents on one host, not two hosts.
  Accepted on the same one-writer-at-a-time basis the Lustre stateRoot already
  relies on, with a single-function fork as the escape hatch if it bites.
- **pi carries two memory tool surfaces**, `pi-memory`'s seven and the graph's
  nine, with nothing telling the model which to prefer. If that causes confusion,
  the resolution is to drop `pi-memory` and let the shared graph be the whole
  plane.
- **The add-only projection gap is no longer theoretical.** It has now cost
  something twice in one sitting: a retired `agentmemory` server still declared
  in `~/.agents/mcp.json`, and a manifest six plugins and one marketplace behind
  the machine. ADR-0011 filed this as "a standing gap to reopen if it bites";
  this ADR is the evidence that it bit. Closing it properly — reading the machine
  back and reporting divergence — is out of scope here, and is the strongest
  candidate for the next ADR.
- **ACP arrives through a v0.0.33 single-maintainer adapter**, so the
  interoperability win is real but thinner than "pi supports ACP" would suggest.
  If `pi-acp` stalls, the slot's headline benefit degrades to editor-plugin
  breadth alone.
- **The `PATH` defect is fixed for the slot but remains for every other mise
  tool.** Nothing else in `home/mise.nix` needs to be reachable by a non-shell
  process today; if something does, this ADR's reasoning applies to it too.
- **A fourth agent still joins by the ADR-0011 recipe.** This change is an
  occupant swap, not a mechanism change.

## Update log

- **2026-08-28 — first-start defects, and one decision reversed.** pi had never
  actually started on a host this ADR provisioned. Three findings, in ascending
  order of how wrong this ADR was.

  - **The `web_search` collision was fatal, not a warning.** This ADR recorded
    that `pi-web-access` "gives the tool up", but nothing was ever written to make
    it do so — the knob lives in `~/.pi/web-search.json`, which no projection
    touched. pi does not warn and continue on a duplicate tool name; it fails the
    second extension load outright, taking `fetch_content`, `source_check` and
    `get_search_content` with it. Every host provisioned under this ADR was in
    that state.

  - **`pi-web-search` is retired, reversing this ADR's choice of it.** The
    original rationale — the only candidate reaching Anthropic's native
    Messages-API search with no extra credential — held only while Anthropic was
    the whole provider set. With the set pinned to Anthropic now, Codex and
    DeepSeek later, both of its tools fail: `url_context` is Gemini-only and can
    never fire, and its `web_search` dispatches on the *current model's* provider
    and hard-errors rather than falling back, with DeepSeek absent from its list.
    Its remaining advantage, grounded search inside the same inference call, is
    billed per search and lands in Anthropic extra usage under subscription OAuth
    — the exact thing `warnings.anthropicExtraUsage` is enabled to surface.
    Dropping it dissolves the collision at the root instead of renaming around it,
    and leaves `pi-web-access` — keyless via Exa MCP, and dispatching
    independently of the session model — as the sole owner of `web_search`.
    `fetch_content` had no substitute either way: pi's four built-in tools
    (`read` / `write` / `edit` / `bash`) include no fetch and no search.

  - **ADR-0009's `~/.pi` symlink silently corrupts npm's lockfile.** pi derives
    its extension root as `<agentDir>/npm` and hands that **symlinked** path to
    `npm install --prefix` from an arbitrary cwd. npm resolves `node_modules`
    through the symlink but keeps the symlinked prefix, so every package is
    recorded as a path escaping the prefix; the next install re-resolves those
    keys against the real root and writes a second copy alongside the first.
    Measured: +311 entries per install, unbounded. The reference host had reached
    3082 entries in a 1.9 MB lockfile — 330 real, 13 stacked stateRoot segments —
    which inflated `npm audit` from 302 packages to 2433 and made npm report
    install scripts as unreviewed no matter what `allowScripts` said. That report
    was the `npm warn install-scripts` line the owner saw. Deleting the lockfile
    is the whole repair and is now a projection step; the root-cause fix
    (`PI_CODING_AGENT_DIR=<stateRoot>/.pi/agent`, so pi never hands npm a
    symlink) also relocates `pi-web-access`'s config and is deliberately left to
    a separate change.

  Two smaller corrections fell out of the same pass. `enabledModels` is **not**
  an equivalent of omp's `disabledProviders`, as the implementation notes
  claimed: pi counts a provider credentialed from its *environment variable*
  alone, and a pattern matching nothing yields an empty scope that pi then falls
  through — on a host with an AWS role and no Anthropic login it silently chose a
  Bedrock model. pi 0.84.3 has no provider allowlist at all; verified against the
  settings schema, `models.json` (its `models` array merges, and its `apiKey` is
  the lowest-precedence credential source), `auth.json`'s provider-scoped `env`
  (`||`-chained, so a blank value falls through to `process.env`) and the
  extension API (`unregisterProvider` only removes extension-registered
  providers). And npm 11.19 blocks dependency install scripts by default, which on
  Linux leaves `node-pty` — plan mode's web TUI, whose tarball ships darwin and
  win32 prebuilds only — with no native module; `allowScripts` in
  `~/.pi/agent/npm/package.json` is now seeded before `packages` is declared so
  the first extension install can build it.

- **2026-08-28 (later) — `disabledProviders` has an answer after all.**
  `pi-hide-providers` 0.1.15 is added to the set, on the owner's find. It supplies
  the provider fence the entry above concluded pi does not have, and it does not
  contradict that conclusion: its own README documents the same dead ends this repo
  measured — `registerProvider({ models: [] })` is override-only, and
  `unregisterProvider()` reaches only extension-registered providers — and it
  therefore works by **monkey-patching** `ModelRuntime`'s `getModels`,
  `getAvailableSnapshot`, `getAvailable` and `getModel` on `session_start`. The
  author labels that as not an official SDK mechanism. Accepted with the risk named,
  on the same basis as `pi-lens`: MIT, no runtime dependencies, `@earendil-works/
  pi-coding-agent` 0.84.3 pinned as a devDependency, and vitest + typecheck + knip
  in the repo. The counterweight is that it is 0.1.x, four days old at adoption,
  16 versions in that span, single-maintainer, and reaches into pi internals that
  carry no compatibility promise — so a pi upgrade is the thing to watch.

  Its scope is narrower than its README claims, and the manifest note records the
  two measured gaps rather than the advertised behaviour:

  - **`pi --list-models` is not filtered.** Verified with `amazon-bedrock` and
    `huggingface` hidden: all 118 Bedrock models still listed. That path opens no
    session, so the `session_start` patch never runs.
  - **The cold-start model pick is not filtered.** `main.js` resolves
    `enabledModels` and chooses the initial model in `buildSessionOptions` *before*
    `createAgentSession`, so before any `session_start` handler exists. The
    empty-scope fallback this ADR's earlier entry describes is therefore still
    reachable. The extension's `model_select` handler is described in its source as
    a safety net that blocks hidden models, but it only calls `ctx.ui.notify()`.

  What it does close is the whole remaining exposure once the chosen provider is
  authenticated: the `/model` picker, `Ctrl+P` cycling and session-restore lookups,
  which read exactly the four accessors it patches. The blocklist is seeded with the
  providers pi turns on from **ambient environment** rather than from a login —
  `amazon-bedrock` (the pod's IAM role) and `huggingface` (`HF_TOKEN`) — because
  neither variable can be unset for pi alone without also breaking `aws` and `hf`
  inside pi's own bash tool. `isHidden()` requires an exact provider match and has
  no wildcard, so "hide everything except Anthropic" is not expressible; the list
  names what to hide and is reconciled, keeping rules added by `/hide-models add`.

  Installing it also re-demonstrated the lockfile defect above: `pi install` took
  the tree from 0 escaping entries back to 330 in a single call.

- **2026-08-28 (later still) — the lockfile escape is fixed at the cause.**
  `home/env-links.nix` now sets `home.sessionVariables.PI_CODING_AGENT_DIR` to
  `${cfg.stateRoot}/.pi/agent`, so pi never hands npm the `~/.pi` symlink. The
  projection-time lockfile repair stays as the belt: it heals hosts provisioned
  before this, and any context the session variable does not reach.

  Nothing moves. `~/.pi/agent` *is* `${stateRoot}/.pi/agent` — one is the ADR-0009
  link, the other its target — so `settings.json`, `auth.json`, `sessions/`,
  `npm/`, the memory store and `hide-providers.json` are the same files under
  either spelling. What changes is the string pi passes to `npm --prefix`, and that
  is the whole defect. Measured through pi's own installer, one `pi install`,
  everything else held equal:

  | `PI_CODING_AGENT_DIR` | lockfile after |
  |---|---|
  | unset | 331 entries, **330 escaped** |
  | `${stateRoot}/.pi/agent` | 331 entries, **0 escaped** |

  Three consequences worth having on the record:

  - **`home.sessionVariables`, not `programs.zsh.sessionVariables`.** The existing
    `sessionVariables` block in `home/shell.nix` is the zsh one, which would have
    reproduced exactly the reach failure this ADR fixed for pi's binary by using
    `home.sessionPath`: an editor extension host or an ACP server is not an
    interactive zsh. Verified in the built generation — the export lands in
    `hm-session-vars.sh`, beside the `home.sessionPath` PATH line.
  - **One file genuinely relocates.** `pi-web-access` resolves its config through
    the same variable, so `web-search.json` moves from `~/.pi/` down to
    `~/.pi/agent/`. Harmless — this repo stopped writing that file when
    `pi-web-search` was retired — but `RETIRED_PI_WEB_SEARCH` now sweeps both
    spellings (`PI_WEB_SEARCH_PATHS`), since retirement has to reach hosts
    provisioned before the variable existed.
  - **Graceful degradation.** Where the variable does not reach, pi falls back to
    `~/.pi/agent`, the same directory, so the only regression is the escape itself
    — which the repair step already handles. Also, setting the variable makes pi
    skip its first-run startup selector; moot, since that path additionally needs
    experimental features and a missing `settings.json`, and the projection always
    seeds one.

  Verified with `just build` (changes nothing in `$HOME`); activation is `just
  switch`, which is the owner's to run.

- **2026-09-03 — the manifest catches up with the reference host.** Three
  differences between `PI_SETTINGS_SEED` and the live `~/.pi/agent`, all
  resolved in the host's favour because every one was a deliberate hand edit
  under plane ③ or a plane-② choice ADR-0011 exists to absorb.

  - **`pi-background-tasks` is retired, `pi-token-usage-statistics` declared.**
    The host's `settings.json.bak-20260902` still lists the former and the live
    file does not; the latter was installed by hand. The manifest follows: the
    package moves to `RETIRED_PI_PACKAGES` so it leaves every host, and the
    ledger extension joins `PI_PACKAGES`. The background-bash slot stays empty
    on purpose — its occupant carried a request-metadata-rewriting provider and
    the tightest peer range in the set, and nothing is refilled into the slot
    until something earns it.
  - **The model preset is re-pinned**: `defaultModel` Fable 5.1, sub-agent
    default Opus 5, oracle Fable / reviewer Opus (both `high`). Still seeded
    leaf-by-leaf, so no host that chose otherwise with `/model` is touched.
  - **`models.json` joins the projected set**, as `PI_MODELS_SEED`. The host had
    found the answer to the cold-start gap the 2026-08-28 entry left open: a
    provider-level `apiKey` naming an environment variable nothing sets
    (`$PI_DISABLE_HUGGINGFACE`, `$PI_DISABLE_AMAZON_BEDROCK`). pi's value
    resolution marks that "unresolved", `configuredRequestAuthStatus()` returns
    `{ configured: false }`, and `getProviderAuthStatus()` returns *that* before
    it reaches the ambient-environment check — so `HF_TOKEN` and the AWS role
    stop being credentials for pi without being unset for `hf` and `aws` inside
    its bash tool. Per-provider add-only: a `providers.<id>` block the host wrote
    is never overwritten. This closes the "not by this package" caveat under
    `PI_HIDE_PROVIDERS_SEED`; the hide rules stay for the picker, this fences
    the initial pick.

  Also found, not fixed here: a stray `~/.pi/.pi/tasks/session-*/` tree on the
  reference host — the `~/.pi/<agentdir>` spelling doubled by some extension
  resolving its task dir relative to the symlink. Left in place; it is state,
  not config, and the writer has not been identified.
