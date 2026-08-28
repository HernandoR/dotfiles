# RFC-0005: The third slot returns to upstream pi — ecosystem interoperability over a fork's feature surface

- Status: Open
- Date: 2026-08-28
- Owners: HernandoR

## Summary

ADR-0011 gave the toolchain's third slot to **oh-my-pi** (`omp`,
can1357/oh-my-pi) on 2026-08-06, on the grounds that the fork shipped natively
everything the four pi extensions existed for. This RFC proposes reversing that
slot back to **upstream bare pi** (`@earendil-works/pi-coding-agent`) — not
because omp's feature surface got worse, but because the slot's *value* was
mis-modelled: what the owner needs from it is **being the agent that other
tools can drive**, and third-party integrations (IDE plugins, agent-connection
protocols) treat `pi` as the first-class citizen, not its fork.

The switch is therefore a deliberate trade of capability for
interoperability. This RFC exists to make that trade explicit, enumerate what
is actually lost, and decide which losses get bought back with pi extensions,
which get bought back with configuration, and which are simply accepted.

## Motivation

**The owner's stated reason:** "3rd party support like IDE plugin and agent
connection usually have pi as first class support."

That is a different axis from the one ADR-0011's 2026-08-06 entry optimised.
That entry compared the two binaries **feature by feature** (MCP client,
sub-agents, browser, skills discovery) and correctly concluded omp dominated.
It never asked whether the binary needed to be *addressable by other software*.
An agent that is only ever launched by its owner in a terminal has no such
requirement; an agent that an editor extension or an ACP client launches does.

**One constraint verified on the reference host makes this concrete and is on
its own a defect in the current wiring.** omp's binary reaches `PATH` only
through mise's **interactive-zsh** `mise activate` integration:

- `home/mise.nix:17` declares `github:can1357/oh-my-pi`, materialised at
  `~/.local/share/mise/installs/github-can1357-oh-my-pi/latest/omp`.
- `home/shell.nix:156-164` puts `~/bin`, `~/.local/bin`, the Nix profiles,
  pixi, conda and CUDA on `home.sessionPath`. **mise's shims dir is not there** —
  by design, since `mise activate` is the mechanism.
- `platform/installers/agents.py` therefore needs `_mise_which` and
  `OmpAgent._bin` to find the binary at all during bootstrap, which is the same
  problem seen from inside the repo.

So any process that is *not* an interactive zsh — a VS Code extension host, a
JetBrains plugin, an editor spawning an ACP server, a `just` recipe, a systemd
unit — cannot resolve `omp` by name today. Claude and Codex do not have this
problem: their official installers land in `~/.local/bin`, which *is* on
`home.sessionPath`.

That finding does two things. It supports the switch, and it constrains it:
whatever install channel pi gets, **pi must be resolvable at a stable path
outside the shell**, or the switch buys nothing.

## What is actually in use today (measured, not assumed)

Read from the reference host on 2026-08-28, `~/.omp/agent/config.yml` and the
surrounding state. This is the baseline any replacement is judged against —
the "usable like omp" bar from the owner's step 3.

| Capability | Live evidence | Plane (ADR-0011) |
|---|---|---|
| Local long-term memory | `memory.backend: mnemopi`, `mnemopi.scoping: per-project-tagged`, `mnemopi.llmMode: smol`; **14 populated memory banks** under `~/.omp/agent/memories/mnemopi/banks/` (dotfiles, mldatakit, pcl-rustic, metrics-run-ops, dagster-ml-pipeline, several worktrees, `shared`) + `mnemopi.db` | ② capability (projected by `omp config set`) |
| Sub-agent model roles | `modelRoles`: `default`/`plan`/`vision`/`commit`/`tiny`/`smol`/`task`/`designer` each pinned to a specific Anthropic model | ③ preference |
| Autolearn | `autolearn.enabled: true` | ③ preference |
| Web search chain | `providers.webSearchOrder`: 23 providers, `anthropic` first, `tinyfish` mid-chain | ③ preference |
| Provider catalog control | 80+ entries in `disabledProviders` | ③ preference |
| MCP | `~/.omp/agent/mcp.json` holding `codegraph`, projected by `write_omp_mcp` | ② capability |
| Skills + instructions | `~/.omp/agent/AGENTS.md` → `~/.agents/AGENTS.md`, `~/.omp/agent/skills` → `~/.agents/skills` (both live symlinks) | ① instruction / ② capability |
| Claude marketplace discovery | omp's `claude` / `claude-plugins` discovery providers (no extension installed — `~/.omp/agent/extensions` does not exist) | ② capability |
| Editing / UX | `edit.mode: hashline`, `symbolPreset: nerd`, `theme.dark: titanium`, `composer.shape: box`, `defaultThinkingLevel: auto`, `compaction`/`retry` enabled, `github.enabled: true` | ③ preference |
| Session corpus | 23 session dirs, `agent.db` (300 KB), `history.db`, `models.db` | state |

Two things follow immediately:

1. **Most of the "usable like omp" surface is preference plane, which ADR-0011
   says this repo never projects.** Model roles, theme, search order, edit mode
   and the provider blocklist are per-machine by standing decision. Reproducing
   them is a *documentation* problem, not a manifest problem — unless this RFC
   decides to reopen plane ③, which it should not.
2. **The one genuinely projected capability with accumulated state is memory.**
   The 14 mnemopi banks are the only thing in the list that cannot be
   re-derived from a config file. Whatever pi's memory story turns out to be,
   the disposition of those banks is a decision, not an implementation detail.

## Blast radius

Verified by grep over the working tree:

| Site | Current content | Change |
|---|---|---|
| `platform/installers/agents.py` | `OmpAgent` (~130 lines), `OMP_MCP`, `OMP_MCP_SCHEMA`, `OMP_MEMORY_BACKEND`/`_KEY`, `write_omp_mcp`, `_omp_mcp_is_usable`, `_mise_which`, the retired-pi-extension comment block, `"omp"` in `MCP_SERVERS[codegraph].agents` | replace with `PiAgent`; decide the extension table |
| `home/mise.nix:17` | `"github:can1357/oh-my-pi" = "latest";` | remove (or replace, per Q3) |
| `home/env-links.nix:198-204` | `.omp` whole-dir Tier-B link, mode 700, with a 6-line rationale comment | becomes `.pi` (mode/kind decision in Q6) |
| `platform/setup.py:142` | deferred-script comment naming omp's MCP config and memory backend | reword |
| `AGENTS.md` | §4 agent toolchain (Projection / Instruction / Skills / Selection / Memory bullets), "A marketplace / plugin / MCP server / agent extension" bullet, "Agent config files" warning | reword every omp mention |
| `home/zsh/functions.zsh:174` | comment mentioning omp's native MCP config | reword |
| `docs/plans/adr-0011-*.md` | third-slot identity set by the 2026-08-06 update entry | see Q1 |

Not in the blast radius: the three-plane partition, the add-only projection
rule, the dual-track skills decision, `--agents=<spec>`, and ADR-0009's tier
rules. This RFC changes *who occupies the third slot*, not the mechanism —
which is the strongest evidence that ADR-0011's structure was right.

## Open questions

All eight are resolved; the resolutions are recorded in
[ADR-0012](../plans/adr-0012-third-slot-upstream-pi-2026-08-28.md), which is
`proposed` pending the owner's sign-off. Kept here with their answers so the
question set is not re-derived.

| # | Question | Resolution | Decided by |
|---|---|---|---|
| Q1 | Record shape — new ADR or a 7th ADR-0011 update entry? | **New ADR-0012**, narrowly scoped to the slot's occupant and capability set, superseding only ADR-0011's 2026-08-06 and 2026-08-20 entries; ADR-0011 stays accepted for its structure and is atomically edited to point here. ADR-0011's body was already stale against its own 6-entry update log — the half-current-record antipattern | agent, by the ADR-driven-development rule |
| Q2 | Install channel, given pi must resolve outside an interactive shell | **`npm install -g --prefix ~/.local --ignore-scripts`**, node via `mise which npm`; `npmCommand` left unset. Dry-run validated; `~/.local/lib` must be created first | agent, on converging evidence |
| Q3 | Does omp stay installed during the transition? | **Yes, on the reference host.** mise seed and `.omp` env link are removed so no *new* machine gets omp; the existing binary and `/fsx/hernando/dotfile_home_link_src/.omp` are left alone, consistent with add-only retirement — which also keeps the archive recoverable and `PI_ACP_PI_COMMAND=omp` available | agent, per ADR-0011's standing rule |
| Q4 | Memory replacement, and the banks | **Two layers.** Shared: `@modelcontextprotocol/server-memory` at `~/.agents/memory/memory.jsonl` — cross-machine via the existing Lustre env link, no credential, no daemon, no egress; one `McpServer` entry for all three agents. Local: `pi-memory` 0.4.2 for pi. Claude's built-in stays off. mem0 declined on data governance. Banks **exported** to `~/.agents/memory-archive/<project>.md` | owner, with the package/mechanism from research |
| Q9 | Is pi configured interactively or by a written preset? | **Written preset**, host owns it afterwards. Contract is **seed, not own** — per-key, split by plane: `packages` repo-reconciled (and *acted upon* by pi at startup, so it replaces `pi install`), everything else add-only leaf-level seed | owner |
| Q10 | Where does shared memory live? | **Under `~/.agents`** — the root that already single-sources instructions and loose skills, and whose env-link target is on Lustre, making the store cross-machine by construction | owner |
| Q5 | Extension set | **Full parity**: 9 packages. Composition largely forced — see ADR-0012's table; `@gotgenes/pi-permission-system` excluded on a hard conflict, `pi-tinyfish`/`pi-brave-search` dropped as stale | owner (posture), agent (composition) |
| Q6 | `~/.pi` env link shape | **Whole dir, mode 700** — it holds `auth.json`, `trust.json`, sessions and the `npm/`/`git/` extension installs, plus `pi-acp`'s hard-coded `~/.pi/pi-acp/`; same reasoning as `.codex` and `.omp` | agent, by ADR-0009 precedent |
| Q7 | Preference-plane transfer | **Recorded in this RFC's inventory table as a reference recipe; never projected.** pi has no `pi config set`, so this is now structural rather than policy | agent |
| Q8 | The `pi` → `omp` shim alternative | **Declined, with source-level evidence** — see the 2026-08-28 interoperability entry. Covers only ACP, breaks on RPC command drift, and cannot be expressed through registry-driven install | agent, reaffirmed by owner |

## Discussion log

### 2026-08-28 — opened

Local facts established (all verified on the reference host, cited above): the
mise-shim `PATH` gap, the live `config.yml` inventory, the 14 mnemopi banks, the
blast radius, and the recoverability of the retired implementation —
`git show e6eb1f8^:platform/installers/agents.py` still holds the whole
`PiAgent` class, the `PI_PACKAGES` table and the deleted npm helper layer
(`_npm`, `_npm_global_bin`, `ensure_node_on_path`, `_resolve_bin`,
`_npm_install_global`), which the 2026-08-20 entry removed along with
agentmemory. So the reversal is a restore-plus-update, not a rewrite.

Upstream pi's *current* capability surface — native MCP? native sub-agents?
native memory? skills discovery? which of `pi-claude-marketplace`,
`pi-mcp-adapter`, `pi-subagents`, `pi-tinyfish` still exist? — is being
verified against upstream rather than taken from ADR-0011's 2026-08-04 research,
which is three weeks stale and describes a pre-fork pi. That section is
appended below when it lands.

### 2026-08-28 — upstream pi's capability surface, verified against upstream

Verified against pi 0.84.3 (published 2026-08-24), its shipped docs
(`package/docs/*.md` in the npm tarball) and `dist/` source. This supersedes
ADR-0011's 2026-08-04 research, which described a pre-fork pi.

**The finding that reshapes the whole question: pi refuses, by design, four of
the capabilities the third slot is used for.** From pi's own README
(§Philosophy) and `docs/usage.md`, verbatim:

> **No MCP.** Build CLI tools with READMEs (see Skills), or build an extension
> that adds MCP support.
> **No sub-agents.** There's many ways to do this. Spawn pi instances via tmux,
> or build your own with extensions, or install a package that does it your way.
> It intentionally does not include built-in MCP, sub-agents, permission popups,
> plan mode, to-dos, or background bash.

And there is **no memory backend of any kind** — zero memory keys in
`docs/settings.md`, persistence is JSONL sessions plus `AGENTS.md` context files
— and **no Claude-Code-style hook engine** (only in-process extension lifecycle
events and a `spawnHook` on the bash tool).

So the 2026-08-06 entry's comparison was not wrong, it was *understated*: omp
does not merely ship those features natively, upstream declines to have them at
all. Every one becomes a community npm extension. **This is the real price of
the switch, and it is a supply-chain trade, not a feature trade:** one
single-maintainer fork is exchanged for six-to-seven single-maintainer
extensions drawn from an 8,521-package `keywords:pi-package` ecosystem.

What pi *does* have, and what it means for each plane:

| Plane | Mechanism | Verdict |
|---|---|---|
| ① Instruction | `~/.pi/agent/AGENTS.md` is pi's global context file, loaded at startup, concatenated with ancestor `AGENTS.md`/`CLAUDE.md`. `AGENTS.override.md` replaces per directory; `--no-context-files` disables | **Works unchanged** — one symlink, exactly as `~/.omp/agent/AGENTS.md` does today |
| ② Skills | pi implements the Agent Skills standard and **reads `~/.agents/skills/` natively** as a global discovery location, alongside `~/.pi/agent/skills/`. Deliberate deviation: skill `name` need not match its directory, "so shared dirs work across harnesses" | **Better than expected** — the shared loose-skills root needs no setting at all. Caveat: root-level `.md` files in `~/.agents/skills/` are ignored (only `SKILL.md` dirs and nested `.md` count) |
| ② Capability install | `pi install npm:<pkg>` / `git:<host>/<repo>` / local path, appending to the `packages` array in `~/.pi/agent/settings.json`, installing under `~/.pi/agent/npm/`. Versioned specs are pinned and skipped by `pi update --extensions` | **Projectable through the agent's own CLI**, satisfying ADR-0011's rule |
| ③ Preference | `~/.pi/agent/settings.json`, deep-merged with project `.pi/settings.json` | Rewritten at runtime by `/settings`, `/theme`, `pi install`/`remove`, and startup housekeeping — so ADR-0009's Tier-A exclusion holds unchanged |

**A new constraint with no omp equivalent: pi has no scriptable config setter.**
`pi config` is an *interactive TUI* resource enable/disable picker; there is no
`pi config get` / `pi config set` in the argument parser. `OmpAgent.set_memory_backend`'s
mechanism — project one setting through the agent's own CLI — therefore has no
counterpart. Any pi *setting* could only be projected by writing
`settings.json`, which is precisely the agent-config merge-patching ADR-0011
declined. **Consequence: pi's projected surface is exactly `pi install` plus
symlinks, and nothing else.** Everything in the measured `config.yml` inventory
above that is not a package stays manual, per machine, forever. This is the
honest answer to "make it usable like omp": the *capabilities* can be projected,
the *tuning* cannot.

**Install channel — decided, on evidence:**
`npm install -g --prefix ~/.local --ignore-scripts @earendil-works/pi-coding-agent`.
Three facts converge on it:

1. It lands the binary at `~/.local/bin/pi`, which **is** on `home.sessionPath`
   (home/shell.nix:158) — the whole point of the switch. Every alternative
   channel fails this: mise's registry `pi` tool (aqua/github/npm backends) is a
   shim reachable only from an activated zsh, reproducing the exact gap being
   escaped; `npm -g` under mise's node lands in
   `~/.local/share/mise/installs/node/lts/bin/`, which has the same problem —
   note this means the *original* PiAgent (`_npm_install_global`, retired
   2026-08-06) had this defect too and it was never noticed.
2. `pi update --self` keeps working. Issue earendil-works/pi#3942 ("not managed
   by a global npm install" under `--prefix`) was **fixed in 0.72.0**;
   `dist/config.js:getInferredNpmInstall()` walks up from the package dir and,
   for a `<prefix>/lib/node_modules/...` layout, injects `--prefix <prefix>`
   into the self-update argv. `~/.local` produces exactly that layout.
   **Corollary: the `npmCommand` setting must be left unset** — pi skips prefix
   inference entirely when it is set (`const inferred = npmCommand?.length ? undefined : getInferredNpmInstall()`).
3. `--ignore-scripts` is pi's own documented recommendation (`docs/quickstart.md`)
   and independently sidesteps the native-postinstall failures the 2026-08-05
   clean-pod run hit with `protobufjs`/`sharp`.

Rejected: Homebrew (not used on these Linux hosts), the nixpkgs attr
(`pi-coding-agent`, indexed at 0.79.1 — pins the version into the flake, the
inverse of the standing "versions stay outside git" rule), GitHub-release Bun
binaries (`dist/config.js` returns `undefined` for the `bun-binary` method, so
self-update dies), and `curl https://pi.dev/install.sh | sh` (npm-based but
picks/creates a prefix of its own choosing — uncontrolled).

The deleted npm helper layer must come back for this: `ensure_node_on_path`
specifically, since pi is a node-shebang CLI and the 2026-08-05 run proved
`shutil.which("npm")` cannot work on a fresh machine (mise's node reaches PATH
only through shell integration — `mise which npm` is the resolution that works).

### 2026-08-28 — the interoperability premise, tested rather than assumed

The switch's whole justification is third-party support, so it was verified
directly rather than taken on trust. **The premise is half false, and the owner
reaffirmed the switch after seeing the falsification.**

**False half — protocol capability.** Upstream pi does **not** speak ACP.
`docs/usage.md` lists exactly four modes (interactive, `-p/--print`,
`--mode json`, `--mode rpc`); `acp` is not an accepted value, there is no
`acp.md` in its 31 doc files, and the CHANGELOG has zero ACP hits. Native ACP is
an **open, undecided proposal** (earendil-works/pi discussion #4444, opened
2026-05-12, implementation plan posted 2026-07-09, no maintainer decision). ACP
is delivered by **`pi-acp` v0.0.33**, a single-maintainer MIT adapter
(svkozak/pi-acp) that shells out to `pi --mode rpc --no-themes` and requires
pi ≥ 0.80.4. **omp, by contrast, has `omp acp` natively.** Note also that pi's
`--mode rpc` is JSON Lines over stdio, **not** JSON-RPC.

**True half — presence and breadth, which no shim can buy.** `pi-acp` is in the
official ACP registry (`cdn.agentclientprotocol.com/registry/v1/latest/registry.json`,
39 agents) and pi is named in Zed's `external-agents.md`, Zed's ACP directory
(46 agents), JetBrains Air's supported-agent list and agentic.nvim's provider
list. Beyond ACP: a Homebrew formula (`pi-coding-agent`, 30,707 installs/365d),
a nixpkgs attr, a Dev Container Feature (marcfargas/pi-devcontainers), a GitHub
Action (shaftoe/pi-coding-agent-action), 3+ VS Code extensions, **7 independent
Neovim plugins**, and 2 Emacs packages. **omp appears in none of those lists** —
its ACP-registry request has been open since 2026-05-16 (can1357/oh-my-pi#1122)
and its Zed-docs request since 2026-06-04 with no maintainer response.

**The rejected alternative, recorded with its evidence (RFC Q8).** A `pi` → `omp`
shim was examined at source level and is *partially* viable: `pi-acp` resolves
its binary as `getPiCommand(process.env.PI_ACP_PI_COMMAND)`, and omp mirrors
every `OMP_*` env var to its `PI_*` alias including `PI_CODING_AGENT_DIR` — so
`PI_ACP_PI_COMMAND=omp PI_CODING_AGENT_DIR=$HOME/.omp/agent` needs no symlink at
all. It was declined for three reasons:

1. **It covers only the ACP half of the owner's stated need.** The IDE-plugin
   half is unreachable: Zetaphor's VS Code extension embeds the pi SDK as an npm
   dependency (`createAgentSession`) and never spawns a binary, and
   `carderne/pi-nvim` requires a *pi-side extension* writing sockets to
   `/tmp/pi-nvim-sockets/`. Neither sees a PATH shim.
2. **RPC command drift is a live risk.** pi-acp sends `get_commands`; omp's
   `docs/rpc.md` documents `get_available_commands` in a documented superset, and
   omp makes no upstream-compatibility claim. omp's acceptance of `--no-themes`
   and `--session <path>` is unverified.
3. **Registry-driven install cannot express it.** Zed/JetBrains "install from
   registry" runs `npx pi-acp@0.0.33`; there is nowhere to inject
   `PI_ACP_PI_COMMAND`, so the one-click path — the actual prize — would have to
   be abandoned for a hand-written `agent_servers` `"type": "custom"` entry with
   an `env` block, which is where omp already is today.

Recorded so the next person does not re-derive it: if the owner ever wants omp
back for terminal work, `PI_ACP_PI_COMMAND=omp` is the 30-minute spike, and
`pi.dev/packages/pi-omp-session-sync` exists as a bridge.

### 2026-08-28 — owner's decisions

Grilled one question at a time; answers are the input to ADR-0012.

1. **Motive** — "3rd party support like IDE plugin and agent connection usually
   have pi as first class support." The slot is valued for being *drivable by
   other software*, an axis ADR-0011 never considered.
2. **Posture — full parity.** Presented with the fact that pi refuses MCP,
   sub-agents, memory and hooks by design, and that parity therefore costs six
   or seven community extensions, the owner chose the **full parity chase** over
   an interop-core subset, a minimal bridge, or keeping omp alongside.
3. **Memory banks — export to a markdown archive.** The 14 mnemopi banks cannot
   be migrated (mnemopi exists only as `@oh-my-pi/pi-mnemopi`; no pi memory
   extension can read its store, and there is no importer). A one-off script
   dumps each bank to `~/.agents/memory-archive/<project>.md` — greppable by all
   three agents, **not** auto-loaded as context, and portable across the next
   backend change too. The new pi memory extension starts empty.
4. **Reaffirmed after falsification.** Shown that pi's ACP is itself a
   third-party v0.0.33 adapter while omp's is native, the owner reaffirmed the
   switch on breadth: registry install, Homebrew, nixpkgs, the devcontainer
   Feature, the GitHub Action and the editor-plugin surface are not obtainable
   by any shim.

**Ordering constraint — stated too strongly at first, corrected here.** The
initial reading was that the export must precede removal of the `.omp` env link.
Checking the mechanism shows that is wrong, and the correction matters because it
lowers the plan's risk. `envLinks` entries link `$HOME/<name>` to
`stateRoot/<name>`; on this host `stateRoot` is
`/fsx/hernando/dotfile_home_link_src` (home/env-branch.nix:16), so the live data
sits at `/fsx/hernando/dotfile_home_link_src/.omp` — **1.1 GB, on the shared
filesystem, outside `$HOME` entirely.** Dropping the entry removes only the
`$HOME` symlink; nothing deletes the target, and a recreated container simply
does not get `~/.omp` re-linked.

So the real dependency is narrower: **the export must precede deletion of
`/fsx/hernando/dotfile_home_link_src/.omp`**, which is a manual act nobody has
scheduled. The banks are not at risk from the switch itself, only from a later
cleanup — recorded so that cleanup is not done first by someone assuming the
data was already gone. (For that cleanup's sake: most of the 1.1 GB is
`puppeteer/`, `natives/`, `logs/` and 23 session dirs; the mnemopi store is
18 MB of it.)

### 2026-08-28 — the memory banks, measured before the export is scoped

The decision to export was taken on the assumption that 14 banks held durable
project knowledge. Opening them changes the scope, so it is recorded here rather
than discovered mid-implementation.

`~/.omp/agent/memories/mnemopi/mnemopi.db` — the *root* store — is **empty**:
33 tables, every one zero rows. The real data is per-bank, in
`banks/<project>-<hash>/mnemopi.db`. Measured across all 13 banks:

| Bank | Rows | Breakdown |
|---|---|---|
| `mldatakit-hernando-feat-behance-crawler` | 60 | wm 10 · memoria_facts 25 · facts 25 |
| `mldatakit-uuid-bucket-abtest` | 44 | wm 6 · memoria_facts 19 · facts 19 |
| `dagster-ml-pipeline` | 36 | wm 2 · memoria_facts 11 · instructions 5 · kg 7 · facts 11 |
| `mldatakit-fix-brass-sorted-writes` | 35 | wm 1 · memoria_facts 12 · instructions 5 · kg 5 · facts 12 |
| `metrics-run-ops` | 22 | wm 2 · memoria_facts 10 · facts 10 |
| `mldatakit-hernando-refactor-remove-uuid-buckets` | 21 | wm 3 · memoria_facts 9 · facts 9 |
| `pcl-rustic` | 20 | wm 4 · memoria_facts 8 · facts 8 |
| `mldatakit` | 18 | wm 2 · memoria_facts 8 · facts 8 |
| `dotfiles`, `shared`, `lz-playground`, `mldatakit-hernando-feat-viztrace-runner`, `tmp` | **0** | empty |
| **Total** | **256** | 18 MB on disk, almost all SQLite/FTS page overhead |

Three observations that narrow the export:

1. **`memoria_facts` and `facts` carry identical counts in every bank** — two
   representations of the same extraction, so the export must pick one, not
   concatenate both, or every archive doubles.
2. **`working_memory` is mostly raw transcript, not knowledge.** Sampled rows are
   verbatim `[role: user] … [role: assistant] …` chunks, one still carrying a
   `--- pi-extension-context:start ---` marker. Low durable value.
3. **The genuinely valuable rows are the extracted facts, instructions and KG
   triples**, and they are real engineering findings — e.g. "crawlers poison
   branch uses XACK+XDEL after poison_threshold deliveries", "poison branch drops
   work ids with no marker permanently without logging", "cursor moves past
   unmarked ids making them invisible". That is a defect chain worth keeping.
4. **The two banks whose names sounded most valuable — `dotfiles` and `shared` —
   are empty.** Nothing cross-project accumulated at all.

**Revised export scope:** eight non-empty banks, prioritising
`memoria_facts` (or `facts`, not both), `memoria_instructions` and `memoria_kg`;
`working_memory` included only as a clearly-separated appendix, or dropped. That
is roughly 150 useful rows and a ~40-line one-shot script — cheaper than the
decision assumed, and the honest read is that **the memory plane was carrying far
less than `config.yml` implied**, which lowers the stakes of losing mnemopi
considerably.

### 2026-08-28 — correction to the bank measurement above

The "256 rows" figure in the previous entry is **wrong and is corrected here**,
because a later independent count disagreed and the disagreement was resolved
rather than averaged. The first pass counted a hand-picked subset of tables and
missed `triples`, `annotations`, `graph_edges`, `gists` and `memory_embeddings`.
Recounting every non-FTS table:

**430 core content rows** across **8 non-empty banks** (1,366 including FTS
shadow tables, which are derived and must not be counted). Per bank:
`mldatakit` 99 · `mldatakit-uuid-bucket-abtest` 81 ·
`mldatakit-…-behance-crawler` 80 · `dagster-ml-pipeline` 47 ·
`mldatakit-fix-brass-sorted-writes` 42 · `pcl-rustic` 28 ·
`mldatakit-…-remove-uuid-buckets` 27 · `metrics-run-ops` 26. Empty: `dotfiles`,
`shared`, `lz-playground`, `mldatakit-…-viztrace-runner`, `tmp`.

The qualitative conclusions of the previous entry stand — the root store is
empty, the empty banks are the ones whose names sounded most valuable,
`working_memory` is largely transcript — and 430 rows is still small enough that
the export is a script, not a project. What changes is only the scale: about 1.7×
the assumed volume.

**Export gets easier than assumed: mnemopi ships its own exporter.** Undocumented
in its README but present in `packages/mnemopi/src/cli.ts`:
`mnemopi export <file.json>` / `import <file.json>` / `bank list|create|delete`,
with paths from `MNEMOPI_DB_PATH` / `MNEMOPI_DATA_DIR`. So the export is
`mnemopi export` per bank, then a JSON→markdown transform — no SQL against an
undocumented schema.

### 2026-08-28 — live drift found in the shared MCP source

`~/.agents/mcp.json` **already exists** (330 bytes, last written 2026-08-06) and
declares **two** servers: `codegraph`, and a stale **`agentmemory`** pointing at
`npx -y @agentmemory/mcp` with `AGENTMEMORY_URL=http://localhost:3111`.

agentmemory was retired on 2026-08-20 — its Home Manager unit, env link, MCP
entry and the whole npm layer were deleted from the repo — but **projection is
add-only, so the file it had been written into was never cleaned**. Nothing has
served :3111 on this host since (the ADR-0011 entry for that date records the
daemon never successfully ran here at all).

This matters immediately rather than eventually: `pi-mcp-adapter` reads
`~/.agents/mcp.json` at **precedence layer 2**, so the moment pi is provisioned it
would inherit a dead MCP server and pay a failing-tool cost every session. **The
file must be reconciled to the manifest as part of this work** — which is also
the first concrete instance of the add-only gap ADR-0011 flagged as "a standing
gap to reopen if it bites". It has now bitten.

### 2026-08-28 — the parity extension set, verified package by package

All sixteen candidate packages are **single-maintainer, bus-factor 1** — that
criterion cannot discriminate between them, so adoption, tests and CI were used
instead. None carries an npm `deprecated` flag.

**MCP — `pi-mcp-adapter` 2.29.0** (2026-08-26, 180k dl/wk). Its six-layer
precedence list is confirmed verbatim, lowest to highest:
`~/.config/mcp/mcp.json` → **`~/.agents/mcp.json`** → `~/.agents/mcp/mcp.json` →
`~/.pi/agent/mcp.json` → `.mcp.json` → `.pi/mcp.json`. The tool-agnostic source at
layer 2 is **still supported and never written back to** — `/mcp disable|enable`
writes only a `disabled` field to `.pi/mcp.json`. So the retired
`write_shared_mcp` comes back unchanged and the MCP plane is a genuine three-way
single point again, with no new file to own. Two traps recorded: the adapter's own
`settings` block lives *inside* the `mcp.json` files (`{"settings": {...},
"mcpServers": {...}}`), not in `settings.json`; and `hostConfigDiscovery` must
stay at its default `off`, or it re-imports whatever Claude and Codex happen to
have — the drift-import ADR-0011 already declined once.

**Memory — `pi-memory` 0.4.2** (2026-08-11, 9k dl/wk, 4 CI workflows). Markdown +
JSON under `~/.pi/agent/memory/`, seven tools registered with **zero config**, no
daemon, no native build, and no credential beyond the Anthropic one already
present. Skip its optional `qmd` index — it is the package's only egress path, and
the cost is losing `memory_search` only.
Rejected: **`@remnic/plugin-pi`** — needs a resident daemon on `127.0.0.1:4318`,
an `OPENAI_API_KEY`-shaped extraction endpoint (Anthropic is not a documented
provider) and it rewrites three files into pi's extensions dir; a resident daemon
is also exactly what the 2026-08-20 entry removed and does not want back.
**`pi-hermes-memory` 0.9.6** is the recorded fallback, not the choice: it is the
only candidate with **per-project scoping**, which is what `mnemopi.scoping:
per-project-tagged` was doing, but it needs a `better-sqlite3` native build —
the exact class of failure the 2026-08-05 clean-pod run hit with
`protobufjs`/`sharp` — and it keys projects on the **git repo-root basename**, so
same-named repos collide. **Accepted regression, stated plainly: memory becomes
global-only.** Escalate to hermes only if that proves unusable in practice.

**Sub-agents — the choice is forced, not preferred.**
`pi-claude-marketplace` declares a peer dependency on **`pi-subagents >= 0.35.0`**,
and only the **unscoped `pi-subagents`** (0.58.0, 2026-08-27, 114k dl/wk, 196 unit
test files) can satisfy it — `@tintinweb/pi-subagents` is a different package name
at 0.19.0, and `@gotgenes/pi-subagents` is a hard fork of tintinweb's whose
`19.3.5` is a re-baseline, not maturity. Since the marketplace bridge is the
owner's named requirement ("skill sync with anthropic claude"), the sub-agent
package is decided by it. The three are also **mutually exclusive by tool-name
collision**: nicobailon and gotgenes both register `subagent`; tintinweb and
gotgenes both register `get_subagent_result` and `steer_subagent`. Install exactly
one.
Recorded so it is not assumed otherwise: **none of the three reads Claude Code's
`~/.claude/agents/`.** tintinweb's advertised "Claude Code compatibility" is
format-level only. Agent definitions will be **copied and translated** into
`~/.pi/agent/agents/*.md`, not symlinked — a genuine new maintenance surface with
no single-source story.

**Web — two packages, split by capability, and the split is deliberate.**
`pi-web-search` 1.3.1 is the **only** candidate that reaches Anthropic's native
Messages-API web search, needing **no credential beyond the existing Anthropic
one and no configuration at all**. That is precisely the rationale that originally
chose `pi-tinyfish` over `pi-websearch`, now satisfiable without a third-party
key. But it can never reach an intranet host — Anthropic's servers do the
fetching — so `pi-web-access` 0.25.0 is installed alongside **for its
`fetch_content` tool only** (keyless local HTTP, local PDF parsing, local
`git clone`), which is the only intranet-capable fetcher in the set. **They
collide:** both register `web_search`, and only `pi-web-access` has the rename /
disable knob, so it must be the one to give it up. `fetch_content` additionally
needs `ssrf.allowRanges` widened (private IPs are blocked by default) while
`fetchRouting.allowRemoteHostedProviders` stays `false`.
Dropped: **`pi-tinyfish`** (0.1.1, last published 2026-05-15, 29 dl/wk, peer range
`*` — no compatibility signal at all) and **`pi-brave-search`** (0.2.2,
2026-05-07, 60 dl/wk). Both need third-party keys and both are already providers
inside `pi-web-access`. The retired extension set's web-search entry is therefore
**not** restored as-is.

**Claude interop — `pi-claude-marketplace` 0.17.0** (2026-08-20, 1.9k dl/wk).
Imports slash commands and skills fully, agents (needs `pi-subagents`), MCP
servers (needs `pi-mcp-adapter`), hooks partially; LSP servers, themes and
unmappable hooks not at all, hence `--partial`. **MCP server names are not
namespaced, so an import fails outright on a name collision** — with `codegraph`
already declared in `~/.agents/mcp.json`, that is a live possibility worth
checking before first run.
Two hard limits on projecting it, and they change the plan's shape:
its authoritative config is `~/.pi/agent/claude-plugins.json` (+`.local.json`),
**the extension's own primary write surface**, and **its schema is not
documented** — the README names only an `enabled` key. So it cannot be
hand-authored from the manifest; it must be **bootstrapped interactively through
its slash commands**, which puts it in the deferred-setup script rather than in
unattended projection.
And the version-pinning question ADR-0011 declined the shared-skills-root over is
**still open**: the README never mentions `~/.claude/plugins/cache` at all, pins
only at *marketplace* granularity via a git ref, and **floats the default branch
without one**. Whether it copes with cache paths like
`agent-skillset/discuss/0.5.0/skills` is **UNVERIFIED and must be tested against
the live layout** before the skills-sync claim is believed.

**Parity extras — three accepted, one forced out.**
- `pi-lens` 4.1.2 (LSP/diagnostics; replaces omp's native LSP). **Accepted with a
  named risk:** no CI signal, it pins `pi-tui ^0.84.1` — the tightest coupling to
  pi's TUI internals in the set — and it **rewrites source files** (autofix,
  edit-autopatch). Mitigation: it degrades gracefully and exposes a
  `/lens-health` degradation ledger, and its background dependency/security scans
  are opt-in and stay off.
- `@plannotator/pi-extension` 0.27.9 (plan review; replaces omp's plan mode).
  Accepted; needs a browser and a loopback reverse proxy. Set `model: null` so it
  stops overriding the session model with its bundled
  `claude-sonnet-4-5` default.
- `pi-background-tasks` 2.4.2 (background bash, which pi also refuses).
  **Accepted conditionally — one blocker to check on these hosts:** its Fusion
  routes are admitted "only through Pi Anthropic or Codex subscription **OAuth**;
  metered frontier API credentials are **rejected before child creation**." With
  an `ANTHROPIC_API_KEY` rather than subscription OAuth, Fusion will not launch;
  `bg_run` and `bg_delegate` still work. It also installs a provider that
  **rewrites Anthropic request metadata** — worth auditing. Its
  `^0.81‖^0.82‖^0.83‖^0.84` enumerated peer range is the most honest compat
  declaration in the set: it will refuse to install on 0.85 rather than fail
  quietly.
- **`@gotgenes/pi-permission-system` 27.1.0 — excluded, and not as a scope
  reduction.** Two independent reasons: it advertises native integration with
  **`@gotgenes/pi-subagents`**, which the marketplace's peer dependency has
  already ruled out; and it would be a **second approval broker arbitrating the
  same MCP calls** as `pi-mcp-adapter`, whose own brokered approval is
  "first synchronous claim wins", with **no documented coordination protocol
  between them**. Untested-by-anyone concurrency at the security boundary is not
  a parity feature. Note also that `pi-background-tasks`' `bg_run` would bypass
  any bash policy it did enforce unless added to `shellTools`. Revisit if the
  authors ever address the pairing.

**Concentration risk worth stating once:** `pi-mcp-adapter`, `pi-subagents` and
`pi-web-access` — three of the highest-traffic dependencies here — share a single
maintainer (`nicopreme`) and therefore one release cadence and one bus factor.
Escaping a single-maintainer fork does not fully escape single-maintainer risk;
it redistributes it.

**A fourth config category this exposes, which ADR-0011 does not have a rule
for.** ADR-0011 knows agent config (never touched) and the manifest (projected by
CLI). These extensions introduce **extension config** — files owned by neither.
Three sub-cases, and they need different treatment:
`~/.agents/mcp.json` is *ours* and the adapter never writes it → projectable;
`~/.pi/agent/claude-plugins.json` is the extension's own write surface with an
undocumented schema → interactive, deferred, never projected;
the rest (`~/.pi/web-search.json`, plannotator's json, per-extension `config.json`)
are static tuning → projectable in principle, but each is one more file this repo
would own. **Recommendation: project only `~/.agents/mcp.json`, and leave every
other extension's tuning manual and documented**, so the switch does not quietly
grow a second config-ownership regime.

### 2026-08-28 — the two open blockers, closed by reading source and the live host

**Blocker 1 — auth shape: CLEARED.** The owner confirms these hosts use
subscription **OAuth**, not a metered `ANTHROPIC_API_KEY`. So
`pi-background-tasks`' Fusion routes admit, and the package is accepted
unconditionally rather than conditionally. Its provider that rewrites Anthropic
request metadata still deserves an audit on first use.

**Blocker 2 — `pi-claude-marketplace` and version-bearing cache paths: the
concern was aimed at the wrong thing, and it is retired.** Settled by reading
the shipped TypeScript (`npm pack pi-claude-marketplace@0.17.0`, 216 files, full
source, read locally — nothing installed).

*It never reads `~/.claude/plugins/cache` at all.* Grepping the whole tree for
`.claude` yields only: `<pluginRoot>/.claude-plugin/plugin.json` and
`<marketplaceRoot>/.claude-plugin/marketplace.json` (the *format* it parses),
documentation URLs, and one module — `orchestrators/import/settings.ts`. The
extension is an **independent marketplace client**: `persistence/locations.ts`
shows it clones marketplaces itself from git into
`<scopeRoot>/pi-claude-marketplace/sources/<mp>/`, with its own
`plugin-clones/`, `data/`, `resources/skills/`, `resources/prompts/`, `hooks/`,
`agents/` and `mcp.json`. So Claude's version-bearing cache layout
(`agent-skillset/discuss/0.5.0/skills`) is irrelevant to it — the problem that
made ADR-0011 decline a single shared skills root **does not transfer here**.

*What the real version exposure is, and it is much smaller.* Plugin versions are
deliberately **not** in the declarative config —
`PLUGIN_CONFIG_ENTRY_SCHEMA` has only `enabled`, with the comment "No `version`
field per D-06 -- versions are a machine fact owned by `state.json`". Pinning
happens at *marketplace* granularity, as a git ref inside the `source` string.
The repo's four `MARKETPLACES` entries are bare `owner/repo` shorthands and one
plain git URL, so they would **float the default branch**. That is a real but
ordinary trade — the same one the Claude and Codex projections already make —
not the link-rot-on-every-upgrade failure that was feared.

*The finding that changes the plan: the config is explicitly designed to be
written by hand, and its shape is already the repo's shape.*
`persistence/config-io.ts` documents `claude-plugins.json` as "the
USER-AUTHORED desired state" against a lenient schema:

```json
{
  "schemaVersion": 1,
  "marketplaces": { "<name>": { "source": "<raw string>", "autoupdate": true } },
  "plugins":      { "<plugin>@<marketplace>": { "enabled": true } }
}
```

`Type.Object` keeps `additionalProperties: true` at every level on purpose — "a
user-authored typo or a forward-compatible new key does NOT fail validation" —
`absent` is a legal state distinct from empty, and `schemaVersion` is an optional
literal `1`. The plugin key is `${plugin}@${marketplace}`
(`orchestrators/reconcile/plan.ts:69`), which is **exactly**
`Plugin.qualified()` in `platform/installers/agents.py:128` **and exactly**
Claude's own `enabledPlugins` key format. The repo's `MARKETPLACES` +
`PLUGINS` tables are isomorphic to this file.

*Write-back is bounded, and there is a clean ownership split.*
`persistence/config-write-back.ts` patches at entry level on **mutating commands
only**, preserving unknown keys and pinning `schemaVersion: 1`. It carries an
explicit architectural guard against ever serializing a merged view back to
base, so it cannot silently absorb the override layer, and `--local` routes a
write to `claude-plugins.local.json`, whose entries **replace** same-keyed base
entries wholesale. That yields the split this repo wants: **the repo owns the
base file; the machine owns `.local.json`.** Re-projection cannot stomp a
deliberate per-machine deviation.

**Revised recommendation, reversing the earlier one:** project
`claude-plugins.json` from the manifest. The interactive-and-deferred treatment
was based on the README's silence about the schema; the source settles it. This
makes marketplaces and plugins a genuine **three-way** single point — Claude via
`claude plugin install`, Codex via `codex plugin add`, pi via one generated
declarative file — which is what ADR-0011 wanted all along and could not have
for omp. `/claude:plugin import` (which reads only `~/.claude/settings.json` and
`settings.local.json`, read-only, honoring `CLAUDE_CONFIG_DIR`) remains useful as
a one-shot seeding convenience, not as the mechanism.

**Two feared costs are currently zero, and both stay latent.** The live host has
**no `~/.claude/agents/` directory at all**, and no plugin in
`~/.claude/plugins/cache/` ships an `agents/` dir or a `.mcp.json`. So the
"copy and translate agent definitions" burden is today empty — it applies only to
loose user-level agents, since plugin-provided agents are installed
automatically into `~/.pi/agent/agents/` by the bridge — and the unnamespaced
MCP-server collision that would abort an import has nothing to collide with.
Both remain true risks the moment either condition changes.

One precedence detail to keep in view: the bridge writes
`<scopeRoot>/mcp.json` = `~/.pi/agent/mcp.json`, which is **layer 4** and
therefore **outranks** the manifest's `~/.agents/mcp.json` at layer 2. A future
plugin-provided server named `codegraph` would shadow the manifest's.

### 2026-08-28 — manifest drift found again, larger than in ADR-0011

Reading `~/.claude/settings.json` on the reference host to see what
`/claude:plugin import` would find turned up the same defect ADR-0011 was
written to fix, recurred and grown. ADR-0011 claimed the
`worktrunk`/`composio` drift was "closed by construction". **It is not closed.**

Live `extraKnownMarketplaces` holds **five**; the repo's `MARKETPLACES` holds
four. Live `enabledPlugins` holds **thirteen**; the repo's `PLUGINS` holds seven.
Nothing in the repo is missing from the machine — the drift is entirely
machine-ahead-of-repo:

| Live but not in the repo | Kind |
|---|---|
| `mewtant-plugins` (`troph-team/mewtant-plugins`, `autoUpdate: true`) | marketplace |
| `reclaim-code-entropy@agent-skillset` | plugin |
| `feedback-mewtant-plugins@mewtant-plugins` | plugin |
| `hugging-face-buckets@mewtant-plugins` | plugin |
| `mldatakit@mewtant-plugins` | plugin |
| `spdl-pipeline@mewtant-plugins` | plugin |
| `pyright-lsp@claude-plugins-official` | plugin, from a **builtin** marketplace absent from `extraKnownMarketplaces` |

The cause is structural and worth naming rather than blaming: projection is
add-only, so the repo can only ever *add* to the machine, and nothing ever reads
the machine back to notice the machine has moved first. ADR-0011 recorded exactly
this as "a standing gap to reopen if it bites". Between this and the stale
`agentmemory` entry in `~/.agents/mcp.json`, **it has now bitten twice in one
sitting.**

This matters specifically for the switch rather than merely being tidy: if
`claude-plugins.json` is generated from the manifest, then pi gets *the repo's
seven*, not *the machine's thirteen* — and the third slot would silently ship a
smaller skill set than Claude has, which is the opposite of the "skill sync with
Claude" the switch is for. **Reconciling the manifest to the live set is a
prerequisite of the projection, not follow-up work.** The `pyright-lsp` entry
additionally needs a decision, since its marketplace is a Claude builtin and may
have no equivalent under Codex or pi.

**Unrelated but found in the same file, and it should not be lost again:**
`autoMemoryEnabled` is still `false`. It was turned off for agentmemory's sake,
and ADR-0011's 2026-08-20 entry said plainly that a machine in that state "should
be turned back on by hand; nothing in the bootstrap will do it." Nobody did. With
memory becoming pi-only under this ADR, **Claude currently has no memory at all
on this host** — built-in off, no MCP memory server. It is preference plane, so
this repo will not project it; it is called out here because the switch makes the
consequence worse, not better.

### 2026-08-28 — two further owner decisions, and what they reverse

**Decision 5 — memory becomes two layers, and mem0 is the shared one.**

- Claude's built-in memory **stays off** (`autoMemoryEnabled: false` remains).
- pi keeps the local backend recommended above (`pi-memory`).
- **Both Claude and pi additionally get mem0**, for long-term memory that
  survives across machines.

This resolves the gap the previous entry flagged — Claude was about to be left
with no memory at all — but not by turning the built-in store back on. It also
changes the shape of the memory plane from *one local store per agent* to
**local per agent, plus one shared cross-machine store for all of them**.

Consequences that follow immediately, before any mechanism is chosen:

- The memory plane returns to being **cross-agent**, which the 2026-08-20 entry
  had given up. The difference from the agentmemory era is that the shared layer
  is now the *second* layer rather than the only one, so a failure of the shared
  store degrades to local memory instead of to nothing.
- mem0 is reached over **MCP**, which makes it exactly one `McpServer` manifest
  entry — the single-point mechanism ADR-0011 already has, with no new machinery.
  It lands in Claude via `claude mcp add`, in Codex via `codex mcp add`, and in
  pi through `pi-mcp-adapter` reading `~/.agents/mcp.json`.
- **Codex is included, on my call, and is easy to veto.** The owner named Claude
  and pi. A memory server is agent-agnostic, the manifest entry reaches all three
  for free, and leaving Codex out would be an asymmetry with no stated cause.
- Two open risks to settle from research, not assumption: whether mem0 needs a
  **resident daemon** (the thing the 2026-08-20 entry deliberately removed and
  these init-less hosts cannot supervise), and whether it needs a **non-Anthropic
  credential plus outbound network egress** (the owner has Anthropic
  subscription OAuth only, and some hosts are intranet-restricted). "Cross-machine"
  implies shared state somewhere, so one of a hosted service, a reachable server,
  or the shared `/fsx` filesystem must carry it.

**Decision 6 — pi is configured by a written preset, not interactively. This
reverses ADR-0011's standing rule for pi, deliberately.**

The owner's instruction: write the preset config file directly, and let the host
change it afterwards.

ADR-0011 said nothing may write an agent's own config file, because all three
agents rewrite theirs at runtime. That rule was protecting against a real
failure — a projection that re-asserts on every bootstrap silently destroys
`/model`, `/theme` and `pi install` changes. **The owner's decision keeps the
protection and drops the prohibition**, by changing the contract from *own* to
*seed*: the repo supplies initial values, the host owns them from then on.

This is not a new idea in this repo, which matters — it means there is precedent,
vocabulary and a known cost rather than an invention:

- `home/mise.nix` already treats `~/.config/mise/config.toml` as a **seed**, not
  a live store link, precisely so `mise use -g` keeps working.
- `home/env-links.nix` already has a `seed` / `seedSource` option that writes a
  target only when it does not exist, used for `.claude.json` (`{}`).
- ADR-0009's update log (2026-08-07) already recorded the accepted cost of seed
  semantics: **a value added to a seed reaches a host that has already
  bootstrapped only when someone re-applies it by hand.**

What this unlocks, and it is the direct answer to "make it usable like omp": the
measured `config.yml` inventory stops being a *documentation* problem. Model
roles, theme, thinking level, edit mode and the provider blocklist become
**seedable**, so a new machine comes up already tuned. The previous entry's
conclusion — "the capabilities can be projected, the tuning cannot" — is
therefore **withdrawn**.

It also generalises past `settings.json`. The same contract now covers the
per-extension config files the previous entry chose to leave manual
(`~/.pi/web-search.json`, plannotator's json, per-extension `config.json`): they
are seeded too, because the owner's rule is about *how* pi is configured, not
about which file.

**The one design question this leaves, and my recommendation.** "Write the preset,
let the host change it" admits two mechanisms with materially different
behaviour:

- **whole-file if absent** — simplest, but a key added to the preset later never
  reaches an existing machine, which is exactly ADR-0009's recorded seed cost;
- **add-only merge at leaf-key level** — write a key only when the file does not
  already carry it; never overwrite a value the host has set.

I recommend the second. It satisfies both halves of the instruction more exactly
(preset values land, host changes survive, *and* new preset keys propagate), and
it is not a new contract: `write_omp_mcp` did add-only merging into
`~/.omp/agent/mcp.json` — a file omp itself rewrites — and ADR-0011's 2026-08-06
entry explicitly accepted that as "the same merge contract the adapter had". The
only new detail is merge depth: nested objects such as `modelRoles` and `theme`
must merge per leaf, or adding one role would wipe the others.

`claude-plugins.json` keeps its own distinct contract (repo owns the base file,
host owns `claude-plugins.local.json`) rather than being folded into this one,
because that extension ships a real override layer and using it is strictly
better than merging. Two contracts, each with a stated reason.

### 2026-08-28 — a stale `~/.pi` already exists, and it falsifies the seed mechanism I just recommended

The env-link stateRoot on this host is `/fsx/hernando/dotfile_home_link_src`,
and it is **Lustre** — `10.64.185.169@tcp:/5soidb4v[/hernando]`, mounted with
`flock`. That is worth stating plainly for the first time in this RFC: the
"persistent volume" is genuinely **network-shared across hosts**, not merely
container-external. Two consequences: a file-backed store placed there is
cross-machine *by construction*, and the existing SQLite stores
(`~/.omp/agent/agent.db`, `mnemopi.db`, Claude's state) have been living on a
network filesystem all along — which works because `flock` is enabled and, in
practice, one host writes at a time.

**`.pi` never left.** stateRoot still holds a complete pre-omp pi tree, **171 MB**,
frozen at 2026-08-06 03:54 — the hour omp replaced pi:

| Path | Content |
|---|---|
| `.pi/agent/settings.json` | `{"packages": ["npm:pi-claude-marketplace", "npm:pi-mcp-adapter", "npm:pi-tinyfish", "npm:pi-subagents"]}` |
| `.pi/agent/npm/node_modules` | `pi-mcp-adapter` **2.20.1** · `pi-subagents` **0.41.0** · `pi-claude-marketplace` **0.13.0** · `pi-tinyfish` **0.1.1** |
| `.pi/agent/AGENTS.md` | symlink → `/root/.agents/AGENTS.md`, **still intact** |
| `.pi/agent/skills` | symlink → `/root/.agents/skills`, **still intact** |

There is no `auth.json`, no `sessions/`, no memory store — so **nothing of value
is in there.** (Also still present and equally dead: `.agentmemory`, 33 MB,
retired on 2026-08-20.)

**This falsifies the add-only-merge recommendation from the previous entry, on
this host, concretely.** Re-adding the `.pi` env link resurrects that
`settings.json`. `packages` then already exists, so an add-only merge would
**decline to write the preset's nine-package array** and pi would come up with
the old four — including `pi-tinyfish`, the package this plan explicitly drops as
abandoned. The mechanism would silently deliver the opposite of the decision.

**The fix is a per-key contract split by plane, not a single merge rule.** The
previous entry treated `settings.json` as one thing; it is two:

- **`packages` is plane ② capability, not preference.** It is the manifest's own
  content expressed in pi's file, so it is **repo-owned and reconciled** — set to
  the manifest's list, not merged with whatever is there. This is also the only
  way a *dropped* package (tinyfish) can ever leave, since add-only projection
  cannot remove.
- **Everything else in `settings.json` is plane ③ preference** — `modelRoles`,
  `theme`, thinking level, edit mode, provider blocklist — and gets the add-only
  leaf-level seed: written when absent, never overwritten, so `/model`, `/theme`
  and a hand edit all survive.

That split keeps both halves of the owner's instruction intact and is a better
match to ADR-0011's planes than one uniform rule would have been.

**And it forces a decision the plan did not have: reuse the stale tree, or reset
it.** Recommendation: **reset** — rename it to `.pi.pre-omp-2026-08-06.bak` in
stateRoot (a rename on Lustre, instant, reversible) and let the bootstrap build
fresh. Four reasons: the three surviving extensions are 3–4 minor versions behind
and were installed against pi 0.83.x; `pi-tinyfish` must go regardless; 171 MB of
`node_modules` is cheap to rebuild and expensive to reason about; and the two
things actually worth keeping — the `AGENTS.md` and `skills` symlinks — are
re-created by `PiAgent.project` in one line each. Nothing in the tree is
irreplaceable, which is what makes this cheap rather than a judgement call.

The first write into a reset `.pi` is therefore a clean full preset, and the
add-only seed only starts protecting host changes from the second bootstrap
onward — which is the correct order for it.

### 2026-08-28 — mem0 investigated and declined; the shared store moves under `~/.agents`

**Decision 5 is revised by the owner after seeing the research: mem0 is dropped.
The shared cross-machine memory store is a file-backed MCP knowledge graph under
`~/.agents`.**

**Connectivity was not the blocker, and was checked first rather than assumed.**
`https://api.mem0.ai/v1/ping/` and `https://mcp.mem0.ai/mcp/` both answer **401**
from the reference host — reachable, merely unauthenticated. So mem0 was declined
on data governance, not on network reach.

**What mem0 would actually have given, recorded because it was genuinely good.**
Cloud mem0 needs **only** `MEM0_API_KEY` — extraction, embedding and dedup all
happen server-side, so no OpenAI key is required. Its MCP endpoint is
remote-hosted streamable HTTP, i.e. **no local process at all**, which is exactly
the daemonless shape this repo wants. And the integration surface is first-party
on all three agents: a Claude Code plugin (marketplace `mem0ai/mem0`, plugin
`mem0@mem0-plugins`) with **lifecycle hooks** that capture memory automatically at
session start, pre-compaction, task completion and session end; a Codex plugin;
and **`@mem0/pi-agent-plugin` 0.1.5** (Apache-2.0, published 2026-08-24 by the
mem0 npm org), which uses the SDK directly and therefore would not even have
needed `pi-mcp-adapter`. Cross-machine sharing is just "same `MEM0_API_KEY` +
same `user_id`". On mechanism, it was the best option found.

**Why it was declined anyway** — four facts from mem0's own docs and privacy
policy:

1. **Raw conversation turns leave the host.** `add()` posts the messages;
   extraction is server-side. Only extracted facts are *stored*, but the
   transcript transits.
2. **OpenAI and Anthropic are named subprocessors.** Content reaches third-party
   LLMs even though the client supplies no key for them.
3. **US-only, no EU region**, per the privacy policy's own transfer language.
4. **Free-tier content is training corpus** — "we do not train our AI models on
   data from Paid Plan users" carries the obvious negative implication.

For hosts that hold intranet content, that is disqualifying regardless of how
clean the mechanism is. Two further facts made it easy: there is **no
self-hostable MCP server** (`mem0ai/mem0-mcp` is archived as of 2026-03-24 and the
monorepo ships no MCP source, only JSON configs pointing at the hosted URL), and
self-hosting would reinstate a supervised FastAPI daemon plus Postgres/pgvector
on init-less hosts, hard-code OpenAI/Gemini for embeddings (Anthropic has no
embeddings API), and still require a hand-written MCP shim because
`MemoryClient.__init__` unconditionally pings `/v1/ping/`, which the self-hosted
server does not serve. Vendor track record reinforced it: OpenMemory launched and
was sunset inside about a year, the official local MCP server was archived after
roughly four months, and there have been two SDK majors in eleven months with the
Python and Node SDKs currently on different major versions.

Recorded so nobody re-derives it: if the policy position ever changes, the paid
cloud key plus the three first-party plugins is the shape to reach for, and the
entity-scoping gotcha to know is that default extraction splits facts by speaker,
so a query joining `user_id` **AND** `agent_id` returns nothing — share on
`user_id` and filter with `OR`.

**The replacement, and why `~/.agents` is exactly right.**
`@modelcontextprotocol/server-memory` **2026.7.4** (published 2026-07-04), run as
a stdio MCP server via `npx -y`, with its store at
**`~/.agents/memory/memory.jsonl`**.

This lands the memory plane in the same root as the instruction source and the
loose-skills dir, which is more than tidiness — `~/.agents` is already an
ADR-0009 Tier-B env link, so its target is
`/fsx/hernando/dotfile_home_link_src/.agents` on **Lustre**. The store is
therefore **cross-machine by construction, with no service, no credential and no
egress**. The mechanism that already single-sources instructions and skills now
single-sources memory too, and the cross-machine property comes from the env-link
inventory rather than from a vendor.

Verified by reading the shipped `dist/index.js`, not the README:

- **Nine tools**: `create_entities`, `create_relations`, `add_observations`,
  `delete_entities`, `delete_observations`, `delete_relations`, `read_graph`,
  `search_nodes`, `open_nodes`.
- **`MEMORY_FILE_PATH` must be absolute.** A relative value resolves against the
  *package directory* (`dist/index.js:15-17`), and the default path is inside the
  package dir itself — which an `npx` reinstall would discard. So the env var is
  mandatory in practice, and the manifest computes it from `HOME` rather than
  hard-coding `/root`.
- It is **one `McpServer` manifest entry** reaching all three agents through
  machinery that already exists: `claude mcp add` (whose argument-order fix from
  2026-08-13 was written for the next env-carrying entry — this is it),
  `codex mcp add`, and `~/.agents/mcp.json` for pi via `pi-mcp-adapter`.

**The concurrency risk, stated precisely, and one correction to what I told the
owner.** `dist/index.js:53` reads the whole file and `:96` writes it back with
`fs.writeFile(path, lines.join("\n"))` — a **read-modify-write of the entire
file, with no locking anywhere**. Consequences:

- The failure mode is **silent loss of the other writer's recent additions**, not
  a corrupted file: each write emits a complete buffer.
- **The likelier collision is same-host, not cross-host.** Claude, Codex and pi
  each spawn their own `npx server-memory` process, so three writers to one file
  on a single machine is the normal case, before any second machine is involved.
- **Correction:** when I offered this option I said concurrent writes "need
  locking I'd have to add". That was wrong. The read-modify-write happens *inside*
  the server process, so no external wrapper can serialize it per write — a
  `flock` wrapper around the command would hold the lock for the whole session
  and block the other agents instead. Making it safe means patching that one
  function in a fork.
- Mitigation actually available: accept it, and rely on the same
  one-writer-at-a-time reality the Lustre stateRoot already depends on for
  `agent.db`, `mnemopi.db` and Claude's state. Memory-tool calls are infrequent
  and small, so the exposure window is narrow. If loss shows up in practice, the
  fix is a small fork adding `flock` around the read-modify-write — a bounded
  change to a single function in a 500-line file.

**What is given up relative to mem0, plainly:** no embeddings and no semantic
search (`search_nodes` is substring matching over a knowledge graph, not vector
similarity), and no automatic capture — nothing writes memory unless a model calls
a tool, where mem0's Claude plugin had session-lifecycle hooks. The store is a
knowledge graph of entities, relations and observations, not prose notes.

**pi keeps `pi-memory` as a local second layer, and that needs a caveat.** Its
store is `~/.pi/agent/memory/` which, because `~/.pi` is also an env link, is
*also* on Lustre and therefore also cross-machine — the local/shared distinction
is about *scope of agents*, not about machines. The caveat is tool-surface
overlap: pi would carry `pi-memory`'s seven tools **and** the nine graph tools,
with nothing telling the model which to use. Worth watching; if it causes
confusion, drop `pi-memory` and let the shared graph be the whole memory plane.

### 2026-08-28 — pi's settings schema, and four corrections it forces

Read from pi 0.84.3's own tarball: `dist/core/settings-manager.d.ts` (the
`Settings` interface), `docs/settings.md`, and the `dist/` write paths. Nothing
installed.

**Seeding is safe, and safer than the seed decision assumed.** `persistScopedSettings`
(`dist/core/settings-manager.js:376-399`) takes a file lock, **re-reads the file
from disk**, spreads it, and copies in only the fields modified during that
session. Three consequences that matter:

- **Unknown keys are preserved.** There is no schema validation and no
  unknown-key stripping anywhere. This is what makes an extension-owned block
  inside pi's settings.json safe to seed.
- **Nested objects merge key-by-key** where a setter records a nested key, so
  seeding a nested object does not get flattened by the next runtime write.
- **A malformed file is never clobbered, but is entirely ignored** — a
  `JSON.parse` failure degrades settings to `{}` and then `save()` bails without
  writing. So the seed must emit strict JSON: no comments, no trailing commas.
  Formatting is normalised to 2-space indent on pi's first write; hand alignment
  is lost, which is fine for a generated file.

There is **no `$schema` and no `schemaVersion`**, every key is optional, and a
partial file is fully valid. Migrations run unconditionally on every load and
rename legacy spellings (`queueMode`→`steeringMode`,
`websockets`→`transport`, `retry.maxDelayMs`→`retry.provider.maxRetryDelayMs`), so
the seed must not use the old names.

**Correction 1 — `modelRoles` has no upstream equivalent, and I earlier implied
it did.** Reading `omp --help` showed `--smol`, `--slow`, `--plan` and
`PI_SMOL_MODEL`/`PI_SLOW_MODEL`/`PI_PLAN_MODEL`, and I took them for pi lineage.
Grepping the whole pi 0.84.3 tarball — `dist/` and `docs/` — for `smol`,
`PI_SMOL_MODEL`, `PI_SLOW_MODEL`, `PI_PLAN_MODEL` and `--slow` returns **zero
hits**. They are omp additions.

Upstream pi has exactly one model: `defaultProvider` + `defaultModel` as **two
keys**, with the model as a **bare id** (`"anthropic"` + `"claude-opus-5"`, not
`"anthropic/claude-opus-5"`). The combined `provider/model` form appears only in
`enabledModels` patterns, `modelThinkingLevels` keys, `--model`, and extension
config.

The nearest replacement for the eight omp roles is **`pi-subagents`**, which reads
`subagents.defaultModel`, `subagents.defaultProvider`, `subagents.defaultThinking`
and `subagents.agentOverrides.<agent>.{model,thinking,...}` out of pi's own
settings.json. Its roles are agent names, not omp's role names — `oracle`,
`reviewer`, `worker`, `delegate`, `researcher`, `scout`, `claude-code`,
`codex-exec`, `cursor-agent`. So the model-roles capability survives the switch,
but **re-expressed against a different vocabulary**, and only because the
sub-agent extension is installed. It is not a rename; it is a remap the owner
should review.

**Correction 2 — `defaultThinkingLevel: auto` is invalid.** omp's live value is
`auto`; pi accepts only `off|minimal|low|medium|high|xhigh|max`
(`dist/cli/args.js:6`). The seed uses `medium`, pi's own default.

**Correction 3 — the `npm:` prefix is mandatory, and omitting it fails
silently.** `parseSource` (`dist/core/package-manager.js:1148-1170`) treats
anything not prefixed `npm:`/`git:`/`github:`/`http:`/`https:`/`ssh:` as a
**local path**, and `resolveLocalExtensionSource` **returns silently** when that
path does not exist. So `"packages": ["pi-mcp-adapter"]` installs nothing, warns
nothing, and leaves pi with no extensions. `docs/settings.md:294`'s own example
(`["pi-skills", "@org/my-extension"]`) is wrong for npm packages. Every entry the
manifest emits must be `npm:<name>`.

**Correction 4, and this one improves the plan — a hand-written `packages` array
is acted upon, not merely recorded.** At startup `resource-loader.js:276` calls
`packageManager.resolve()` with no `onMissing` callback, and for a missing or
version-mismatched npm package `installMissing()` then calls
`installParsedSource()` **unconditionally** (`package-manager.js:981-1035`), the
only guard being `PI_OFFLINE`/`--offline`. So seeding `packages` **replaces the
`pi install` projection entirely**: pi installs the nine extensions itself on
first launch. That removes nine subprocess calls from the bootstrap and one class
of failure (a `pi install` that fails mid-run leaving a partial set). `pi install`
remains the right tool for a human adding one later, since it also mutates the
array.

**The omp inventory, mapped.** Of the eighteen keys measured in `config.yml`:

| omp key | upstream pi | disposition |
|---|---|---|
| `compaction.enabled` | `compaction.enabled` | identical, seeded |
| `retry.enabled` | `retry.enabled` | identical, seeded |
| `modelRoles.default` | `defaultProvider` + `defaultModel` | seeded, split into two keys |
| `modelRoles.*` (7 more) | — | remapped onto `subagents.agentOverrides.*` |
| `defaultThinkingLevel` | same key, **new value** | `auto` → `medium` |
| `theme.{dark,light}` | `theme` as one string `"<light>/<dark>"` | seeded; **`titanium` is not a built-in** — needs `~/.pi/agent/themes/titanium.json` or the value changes |
| `providers.webSearchOrder` | — | `pi-web-access`, key `searchRouting.providers`, in **`~/.pi/web-search.json`** (note: not under `~/.pi/agent/`); 9 of omp's 23 providers do not exist there |
| `disabledProviders` (~80) | — | no equivalent. Nearest is the `enabledModels` allowlist plus simply having no credentials — pi only offers providers with saved auth, so most of the list is moot |
| `edit.mode: hashline` | — | `pi-lens` provides hashline-anchored edit tools, configured in **`~/.pi-lens/config.json`** |
| `providers.memoryModel` | — | `pi-memory`, env-var only (`PI_MEMORY_EXIT_SUMMARY_MODEL`) |
| `symbolPreset`, `autolearn`, `github`, `composer`, `setupVersion`, `mnemopi.*` | — | **no equivalent anywhere**, in pi or in the nine extensions. Accepted losses |

**Two new top-level paths this exposes, which the env-link inventory does not yet
cover:** `~/.pi-lens/config.json` (pi-lens' global config) sits **outside**
`~/.pi`, so it needs its own entry or it dies with every container.
`~/.pi/web-search.json` is inside `~/.pi` and is already covered by that whole-dir
entry — but note it is *not* under `~/.pi/agent/`, which is easy to get wrong when
writing the seed.

**Privacy defaults worth seeding explicitly:** `enableInstallTelemetry` defaults
to **true**; the seed sets it `false`. `enableAnalytics` already defaults false
and is seeded false for clarity. `warnings.anthropicExtraUsage` is kept **on**
deliberately — with subscription OAuth, third-party-harness tokens can bill as
extra usage, and that warning is the only thing that says so.
