# ADR-0011: Multi-agent toolchain — one manifest, projected by CLI; instructions single-sourced

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-08-04 |

## Context

Claude Code is joined by two more agents the owner wants provisioned: **Codex
CLI** and **pi** (plus pi's memory / web-search / marketplace-bridge /
sub-agent / MCP-adapter extensions). ADR-0005 owns Claude's setup today via an
imperative post-setup; naively extending that pattern per agent yields three
places to maintain one intent.

Two findings from RFC-0004 shape everything below.

**All three agents rewrite their own config at runtime.** Claude via `/model`
and `/config` (already recorded in ADR-0009); Codex via `/model`
(openai/codex#14979), `/experimental`, `/statusline`; pi via `/settings` and
`pi install`. ADR-0009 deferred Tier-A nixification of Claude config precisely
because Home Manager only emits read-only store links — that reasoning now
generalises to all three. Declarative HM ownership of agent config files is
excluded by construction, not by preference.

**The drift ADR-0009 fixed for `$HOME` links has reappeared one layer up.** The
live `~/.claude/settings.json` declares four marketplaces (`agent-skillset`,
`astral-sh`, `worktrunk`, `composio`); `setup_claude` knows two. `worktrunk`
and `composio` were installed by hand and exist nowhere in the repo.

Meanwhile the standards moved: Agent Skills is an open `SKILL.md` standard
(agentskills.io, 2025-12) read by Claude Code and Codex alike, `~/.agents` is
already an ADR-0009 Tier-B link, and most of `~/.claude/skills/*` already
symlink into `~/.agents/skills/*` — a working pattern with no owner.

## Decision

> In the context of provisioning three coding agents whose configuration
> overlaps heavily,
> facing marketplace drift under ADR-0005 and the fact that all three agents
> rewrite their own config at runtime,
> we decided for a single in-repo capability manifest projected onto each agent
> by that agent's own CLI, plus one shared instruction source under
> `~/.agents/`,
> and against declarative HM ownership of agent config, against merge-patching
> the agents' config files, and against unifying per-agent preferences,
> to achieve one reviewed source for what the agents *have* while each agent
> keeps authority over what it *is*,
> accepting add-only projection semantics and a deliberately uneven capability
> surface across the three agents.

### The three planes

- **① Instruction — single-sourced.** `~/.agents/AGENTS.md` is the sole source.
  `~/.codex/AGENTS.md` symlinks to it (Codex reads `AGENTS.md` natively).
  Claude Code **does not read `AGENTS.md`** (Anthropic docs, 2026-05), so
  `~/.claude/CLAUDE.md` is a thin shell containing `@AGENTS.md` plus
  Claude-only lines. **Standing rule: nothing cross-agent may be written into
  the shell** — that discipline, not a mechanism, is what preserves the single
  point. pi has no instruction file (its system prompt is deliberately ~1k
  tokens) and abstains from this plane.

- **② Capability — one manifest, projected by CLI.** MCP servers, marketplaces,
  skills locations and pi extensions are declared once in `platform/` and
  applied with each agent's own commands (`claude plugin install`,
  `claude mcp add`, `pi install`, `codex mcp add`). Letting each tool write its
  own file is what keeps the projection from fighting the runtime writes above.
  This extends ADR-0005's mechanism rather than adding a second one.

- **③ Preference — explicitly not unified.** Model, theme, approval policy and
  sandbox stay per-agent. The value spaces are not isomorphic, and unifying
  them would reopen the settled read-only/runtime-writable question.

### Skills: dual-track

Marketplaces stay marketplace-managed (Claude natively; pi through
`pi-claude-marketplace`). Loose skills live in `~/.agents/skills/`, to which
both `~/.codex/skills` and pi's configurable `skills` setting point. The
single-shared-root alternative — projecting marketplace skills into
`~/.agents/skills/` too — was declined: marketplace cache paths embed version
numbers (`agent-skillset/discuss/0.1.0/skills`), so those links would break on
every plugin upgrade and need rebuilding each run. **Codex therefore cannot see
`agent-skillset`**; this is an accepted gap, not an oversight.

### Memory

**agentmemory** (local SQLite; MCP server + native pi plugin; resident daemon)
is wired to **pi and Codex only**. Claude keeps its built-in file memory
(`~/.claude/projects/<proj>/memory/`), which is in active use. Revisit trigger:
the backend proving itself across a period of real use. The daemon is declared
as an HM `systemd.user.services` / `launchd.agents` unit — a service unit is
never rewritten at runtime, making it the one part of this work that is a
legitimate **Tier A** citizen under ADR-0009.

### pi extension set

`pi-claude-marketplace` (skills bridge), the agentmemory plugin,
`pi-tinyfish` (web search — chosen over `pi-websearch` to avoid a provider
credential on intranet hosts), `pi-subagents`, and `pi-mcp-adapter`. The
adapter is what makes the MCP list a genuine three-way single point; without it
pi would be the one agent unable to reach any declared MCP server.

Note, from reading `~/.claude/plugins/cache/`: `agent-skillset` and
`astral-sh/astral` are **pure skills** (hooks only in `dev_loop`; no agents, no
`.mcp.json`). So the marketplace bridge needs neither `pi-subagents` nor
`pi-mcp-adapter` as a dependency — both are included for their own sake.
`dev_loop`'s hooks fall under `pi-claude-marketplace`'s documented partial hook
support and are expected to degrade under pi.

### Install channels and the selection flag

All three new CLIs use their **official installers** — Codex via
`chatgpt.com/codex/install.sh`, pi and agentmemory via `npm install -g`
(Node from the existing mise runtime). `home/mise.nix` is untouched. Versions
stay outside git so each tool's self-update keeps working; at npm's default
prefix, pi's `pi update --self` breakage under custom prefixes
(earendil-works/pi#3942) does not apply.

`--no-claude` generalises to **`--agents=<spec>`**, reusing the comma-separated
spec-parsing shape `--system` already uses.

### Supersession

**ADR-0005 is superseded by this ADR.** It covered the same territory —
ownership of Claude's post-install setup — and its hard-coded lists have
demonstrably drifted from the live machine. The manifest introduced here
subsumes them, and closing that drift (all four marketplaces recorded in-repo)
is part of the first implementation phase. ADR-0009's tier principle is
**unchanged and reinforced**: nothing here moves agent config into Tier A, and
the one genuine Tier A addition is the agentmemory service unit.

## Consequences

- What the agents *have* — MCP servers, marketplaces, skills, extensions — has
  exactly one reviewed source, and adding one is a commit rather than a
  per-machine command. The `worktrunk`/`composio` drift is closed by
  construction.
- **Projection is add-only.** Deleting a manifest entry does not uninstall it;
  the manifest and the machine drift in one direction. Converging would require
  recording the previously applied set plus correct uninstall paths — declined
  for now, so this is a standing gap to reopen if it bites.
- The capability surface is **deliberately uneven**: Codex gets no marketplace
  skills, Claude gets no agentmemory, pi gets degraded `dev_loop` hooks. Each
  is a recorded trade, and each has a named cause rather than being an accident
  of implementation order.
- Claude's ergonomics are untouched — `/model`, `/config`, plugin installs and
  built-in memory behave exactly as before, consistent with ADR-0009.
- Bootstrap gains a resident daemon for the first time, and with it a small
  supervisor surface (systemd user unit / launchd agent) that must behave
  symmetrically on Linux and macOS.
- Three more CLI versions live outside git. This is the price of keeping
  self-update functional, and it is the direct inverse of the mise-managed
  choice made for `larksuite`/`smithery` — the asymmetry is intentional and
  worth revisiting if these tools' release cadence becomes disruptive.
- The `CLAUDE.md` shell is protected by discipline alone. If cross-agent content
  starts accumulating there, the single point is lost silently — worth a cheap
  periodic check (shell size / content review) rather than trust.
- The plane partition generalises: a fourth agent joins by adding manifest
  targets and one instruction link, without re-deciding the mechanism.
</content>
