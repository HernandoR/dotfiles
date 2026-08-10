# RFC-0004: Multi-agent toolchain — add Codex and pi, single-source what can be shared

- Status: Resolved
- Date: 2026-08-04
- Owners: HernandoR

## Summary

Add two more coding agents (OpenAI **Codex CLI** and **pi**) alongside Claude
Code, plus the pi extensions the owner wants (memory, web search, Claude
plugin-marketplace bridge, sub-agents, MCP adapter). Rather than growing a
third and fourth place to maintain the same intent, partition the agents'
configuration into planes and single-source only the planes that are
genuinely shareable: the **instruction text** and the **capability manifest**.
Per-agent runtime preferences stay per-agent, deliberately.

## Motivation

1. **The single-point problem is already real, not hypothetical.** The live
   `~/.claude/settings.json` declares **four** marketplaces
   (`agent-skillset`, `astral-sh`, `worktrunk`, `composio`) and seven enabled
   plugins. `platform/setup.py`'s `setup_claude` knows about **two** of them.
   `worktrunk` and `composio` were installed by hand and exist nowhere in the
   repo — exactly the drift ADR-0009 eliminated for `$HOME` links, reappearing
   one layer up in agent tooling. Adding two more agents without fixing the
   mechanism triples it.

2. **Cross-agent standards have arrived and change what is possible.** Agent
   Skills became an open standard (agentskills.io, December 2025) and is now
   read by Claude Code, Codex CLI, Cursor, Gemini CLI and others from a
   `SKILL.md` + frontmatter directory. `AGENTS.md` is likewise converging as
   the shared instruction file. A year ago "one config for three agents" was
   not expressible; now most of it is.

3. **The machine is already half-way there by accident.** `~/.agents` is an
   ADR-0009 Tier-B link, and most of `~/.claude/skills/*` are symlinks into
   `~/.agents/skills/*` — created by the lark-cli installer, not by design.
   The pattern works; it just has no owner and no record.

## Research: what each agent actually does

Verified 2026-08-04 against upstream docs, the openai/codex and
earendil-works/pi issue trackers, and the live machine.

### Runtime mutability — the decisive constraint

| Agent | Config file | Written by the agent at runtime? |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | **Yes** — `/model`, `/config` (already recorded in ADR-0009) |
| Codex CLI | `~/.codex/config.toml` | **Yes** — `/model` mutates it (openai/codex#14979); `/experimental` and `/statusline` persist by documented design |
| pi | `~/.pi/agent/settings.json` | **Yes** — `/settings`, and `pi install` records packages into it |

This is the single most important finding: **all three agents write their own
config**. ADR-0009 deferred declarative (Tier A) nixification of Claude config
because Home Manager can only produce read-only store links, which breaks
runtime writes. That reasoning generalises unchanged to Codex and pi. Managing
any of the three agents' config files as HM store links is off the table by
construction — not a preference.

### Instruction plane

- **Claude Code does not read `AGENTS.md`** (Anthropic docs, May 2026). The two
  sanctioned bridges are a `@AGENTS.md` import inside `CLAUDE.md`, or
  `ln -s AGENTS.md CLAUDE.md`.
- **Codex** reads `AGENTS.override.md` then `AGENTS.md` at each directory level,
  concatenated root-down, plus a global `~/.codex/AGENTS.md`.
- **pi** has no instruction file at all — its system prompt is deliberately
  ~1,000 tokens. It has `prompts` (templates) and `skills`, not rules.

So the instruction plane is a two-party problem (Claude + Codex); pi abstains.

### Capability plane

| | Claude Code | Codex CLI | pi |
|---|---|---|---|
| Plugin marketplaces | native | **none** | via `pi-claude-marketplace` |
| Skills (`SKILL.md`) | `~/.claude/skills/`, plugins | `~/.codex/skills/`, `.agents/skills/` | configurable `skills` paths; honours `.agents/skills` |
| MCP | native | native (`[mcp_servers]`) | **not built in** — needs `pi-mcp-adapter` |
| Sub-agents | native | — | `pi-subagents` |

Local inventory of the four installed marketplaces (read from
`~/.claude/plugins/cache/`): `agent-skillset` (discuss / implement / dev-loop /
fetch-external-knowledge) and `astral-sh/astral` are **pure skills**, with
hooks only in `dev-loop`; **no agents, no `.mcp.json`, no commands**.
`worktrunk` and `composio` carry hooks/commands. Consequence: bridging
marketplaces into pi needs neither `pi-subagents` (nothing to run) nor
`pi-mcp-adapter` (no MCP declared); only `dev-loop`'s hooks land in
`pi-claude-marketplace`'s documented "partial support".

### Install channels

- **Codex**: `curl -fsSL https://chatgpt.com/codex/install.sh | sh` yields a
  Rust binary with no Node dependency; `npm install -g @openai/codex` needs
  Node 22+. The widely-cited "npm trap" is only the **unscoped** `codex`
  package name (an unrelated 2012 doc generator) — the scoped package is
  legitimate.
- **pi**: `@earendil-works/pi-coding-agent` on npm. `pi update --self` **fails
  when pi is installed under a custom npm prefix** (earendil-works/pi#3942) —
  which is precisely what mise's npm backend (pnpm global) produces.
- **agentmemory**: `npm install -g @agentmemory/agentmemory`. Exposes an MCP
  server, a CLI, native per-agent plugins (including pi), and a REST API on
  :3111 over local SQLite. No external database, no mandatory API key; runs a
  **background daemon**. Apache-2.0. Maturity figures are self-reported by the
  project's README and were not independently verified.

## Proposal

Partition into three planes and treat them differently:

| Plane | Contents | Treatment |
|---|---|---|
| ① Instruction | `AGENTS.md` / `CLAUDE.md` text | single-sourced |
| ② Capability | MCP servers, marketplaces, skills, pi extensions | single manifest, projected |
| ③ Preference | model, theme, approval policy, sandbox | **not** unified |

③ is excluded because the three agents' value spaces are not isomorphic and
because unifying it would collide head-on with the runtime-mutability finding
above.

For ②, projection is by **CLI command** (`claude plugin install`,
`claude mcp add`, `pi install`, `codex mcp add`) rather than by editing the
agents' config files: let each tool write its own file, and nothing fights its
runtime writes. This extends ADR-0005's existing mechanism instead of inventing
a second one.

## Alternatives Considered

| Alternative | Why not |
|---|---|
| Nixify the three agents' configs as HM store links | Impossible by construction — all three write their config at runtime (see Research). Same reason ADR-0009 deferred it for Claude. |
| Merge-patch the agents' config files from one manifest | Converges (can remove, not just add) but requires a JSON and a TOML merger, comment/order preservation, and a "which keys are ours" ownership notion — three long-lived liabilities. |
| Unify plane ③ too | Needs a cross-agent semantic mapping layer whose lowest common denominator drops each agent's distinctive controls, and reopens the settled read-only/runtime-writable question. |
| One shared skills root for all three (`~/.agents/skills/`), marketplaces projected into it by symlink | Would have closed the Codex skills gap, but marketplace cache paths carry version numbers (`agent-skillset/discuss/0.1.0/skills`), so the projected links break on every plugin upgrade and must be rebuilt each postsetup. Declined in favour of no derived artifacts. |
| pi runs entirely on its own package ecosystem, ignoring Claude marketplaces | Clean isolation, but the skills list becomes two lists — directly against the goal. |
| Everything through MCP (memory and web search too) for one uniform form | Gives up pi's native TUI integration for its own extensions with no single-point gain, since the manifest already spans both forms. |
| Install the three new CLIs via mise npm tools | Consistent with `npm:@larksuite/cli` / `npm:@smithery/cli` and puts versions in git, but breaks `pi update --self` (#3942) and forces Codex through a Node dependency it does not otherwise need. Declined; see Q8. |
| Connect Claude to agentmemory in the same step | Claude already has built-in file memory in active use; adding a competing store to the primary tool before the backend is proven is the wrong order. Deferred with an explicit revisit trigger. |

## Risks

- **CLI projection is add-only.** Removing an entry from the manifest does not
  uninstall it; manifest and machine drift in one direction. Converging would
  need a recorded previous-state file and correct uninstall paths — declined
  as extra machinery for now, so this is an accepted standing gap.
- **agentmemory introduces a resident daemon** into a bootstrap that currently
  has none, and its maturity rests on self-reported numbers. Mitigated by
  scoping it to pi + Codex first, keeping Claude on built-in memory.
- **The `CLAUDE.md` thin shell can silently defeat the single point.** Nothing
  mechanically prevents cross-agent content being written into it instead of
  `AGENTS.md`; only the ADR's discipline does.
- **Codex has no marketplace**, so `agent-skillset` skills never reach it. The
  capability surface is intentionally uneven across the three agents.
- **`dev-loop`'s hooks degrade under pi** (`pi-claude-marketplace` documents
  partial hook support). Expected behaviour, not a defect to chase.
- **Three new imperative drift surfaces** — the new CLIs' versions live outside
  git, by the same choice that keeps their self-update working.

## Open Questions

Resolved in the 2026-08-04 grilling; see the update log. None outstanding.

## Acceptance Criteria

- [x] A fresh bootstrap installs `codex`, `pi`, and `agentmemory`, and wires
  the pi extension set, with no manual per-machine step. (Clean jcc devpod,
  bare Ubuntu → provisioned in 2m55s, unattended.)
- [x] The four live marketplaces (`agent-skillset`, `astral-sh`, `worktrunk`,
  `composio`) all appear in the in-repo manifest — the current drift is closed.
  (`MARKETPLACES` in `platform/installers/agents.py`.)
- [x] `~/.codex/AGENTS.md` resolves to `~/.agents/AGENTS.md`, and
  `~/.claude/CLAUDE.md` imports it. Caveat on the second half: `codegraph`
  appends its own delimited usage block to the Claude shell, so the shell is not
  literally free of cross-agent text — that block is vendor-written and
  vendor-refreshed, not ours to host elsewhere.
- [x] `~/.codex/skills` and pi's skills dir both resolve to `~/.agents/skills/`
  (via a link on pi's side rather than its `skills` setting, since that setting
  lives in the file pi rewrites at runtime).
- [x] MCP servers declared once reach Claude and Codex — `codex mcp list` shows
  both `agentmemory` and `codegraph` enabled. For pi they are declared in
  `~/.agents/mcp.json` with `pi-mcp-adapter` installed; that the adapter *reads*
  them has not been exercised in a live pi session.
- [x] `--agents=<spec>` selects which agents to provision; `--no-claude` no
  longer exists as the only lever (it survives as a deprecated alias for
  `--agents=none`).
- [~] Claude's plugin installs behave exactly as before (4 marketplaces + 7
  plugins into a fresh config, then idempotent on re-run). `/model` and `/config`
  need an interactive session and are not verified; built-in memory is untouched
  by construction.

## Rollout

1. Manifest + projection layer in `platform/`, driving the *existing* Claude
   steps only — behaviour-neutral, closes the marketplace drift.
2. Add Codex: install, instruction symlink, skills link, MCP projection.
3. Add pi: install, extension set, skills path, marketplace bridge.
4. agentmemory: install, HM-declared user service, wire pi + Codex.
5. Generalise `--no-claude` → `--agents=<spec>`; mark ADR-0005 superseded.

Each phase leaves the system bootable and is separately revertible. Code-comment
discipline as in `platform/` and `home/`: every manifest entry states which
agents it targets and why it is where it is.

## Update log

- **2026-08-04 — drafted and resolved in one decision-grilling session.** Nine
  questions; the owner overrode the recommendation on three (Q4, Q8, Q9-scope
  aside), and the answers to Q7 improved the design over what was proposed.

  - **Q1 — unify planes ① and ②; leave ③ alone.** As proposed.
  - **Q2 — CLI-command projection**, accepting add-only semantics. The
    state-file variant that would make the manifest converge was offered and
    declined as premature machinery.
  - **Q3 — pi gets skills by bridging Claude marketplaces, and runtime
    capability from native pi extensions.** The mixed answer follows from the
    forms not being interchangeable: memory/web search are MCP servers on the
    Claude side and native TS extensions on the pi side.
  - **Q4 — dual-track skills, overriding the recommendation.** The proposed
    single shared root (`~/.agents/skills/` for everything, marketplaces
    projected in) was declined; marketplaces stay marketplaces, loose skills
    stay in `~/.agents/skills/`. Accepted cost: **Codex cannot see
    `agent-skillset`**, since Codex has no marketplace mechanism. Benefit: no
    version-pinned derived symlinks to rebuild.
  - **Q5 — agentmemory, wired to pi and Codex only.** Claude keeps its built-in
    file memory; connecting it is a future decision with an explicit trigger
    (the backend proving itself in use). Narrower than recommended.
  - **Q6 — `~/.agents/AGENTS.md` is the source**; Codex symlinks to it, Claude
    gets a thin `CLAUDE.md` that `@AGENTS.md`-imports it plus Claude-only lines.
    Chosen over a bare symlink so Claude-specific rules have a legal home
    instead of leaking into the shared file.
  - **Q7 — pi extensions: `pi-tinyfish`, `pi-subagents`, `pi-mcp-adapter`**
    (plus `pi-claude-marketplace` and the agentmemory plugin from Q3/Q5).
    `pi-mcp-adapter` was recommended *against* as a dependency-free addition;
    including it turned out to be the better call — it makes the MCP list a
    genuine three-way single point and removes a predicted capability gap.
    `pi-tinyfish` over `pi-websearch` to avoid a provider credential on
    intranet hosts.
  - **Q8 — official installers for all three, overriding the recommendation.**
    The per-form split (Codex via `install.sh`, pi/agentmemory via mise) was
    declined in favour of one uniform channel. Consequence: `home/mise.nix` is
    untouched, self-update keeps working everywhere (#3942 does not apply at
    npm's default prefix), and three CLI versions stay outside git.
  - **Q9 — record first, implement separately.** This RFC plus ADR-0011 land
    now; implementation follows as its own round.

  Decided without asking, following existing repo convention: ADR-0011
  **supersedes ADR-0005** (same territory rewritten, and ADR-0005's list has
  demonstrably drifted); the `--no-claude` flag generalises to `--agents=<spec>`
  reusing the spec-parsing shape `--system` already uses; the agentmemory daemon
  is declared as an HM `systemd.user.services` / `launchd.agents` unit — a
  service unit is never rewritten at runtime, making it the one part of this
  work that is a legitimate Tier A citizen.

  Outcome: [ADR-0011](../plans/adr-0011-multi-agent-toolchain-single-source-2026-08-04.md).

- **2026-08-05 — implemented** on `feat/adr-0011-multi-agent-toolchain`. The two
  criteria above that are properties of the repo are met; the remaining ones
  describe machine state after a real bootstrap and are verified there, not here.
  Implementation notes, four deviations, and two findings that reverse premises of
  this RFC (Codex *does* have a plugin marketplace; pi *does* read a global
  `AGENTS.md`) are recorded in the ADR-0011 update log.
