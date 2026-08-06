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

## Update log

- **2026-08-05 — implemented.** The manifest is
  `platform/installers/agents.py`: the `MARKETPLACES` / `PLUGINS` /
  `MCP_SERVERS` / `PI_PACKAGES` tables, each entry carrying the agents it targets
  and why, plus one `Agent` subclass per agent holding *that agent's* install
  channel and projection commands. `setup.py`'s `setup_claude` became
  `setup_agents` + `write_deferred_setup`, `--no-claude` became `--agents=<spec>`
  (with the old flag kept as a deprecated alias), and the daemon is
  `home/agentmemory.nix` (`systemd.user.services` on Linux, `launchd.agents` on
  Darwin, one shared `writeShellScript`). `~/.agentmemory` joined
  `home/env-links.nix`, since a memory backend whose SQLite store does not
  survive container recreation is pointless.

  Four implementation choices departed from the letter of this ADR:

  - **Claude's marketplaces, plugins and MCP adds moved out of the deferred
    interactive script and now run unattended during bootstrap.** The `worktrunk`
    / `composio` drift is only "closed by construction" if applying the manifest
    needs no human; leaving it behind `dotfiles-postsetup` would have kept the
    fix optional. Verified against the CLI surface first: `claude plugin
    marketplace add` / `plugin install` / `mcp add` take flags for everything and
    prompt for nothing. The deferred script keeps exactly what genuinely blocks on
    a human — Smithery auth and the Lark CLI's own installer — and projection
    commands now run with stdin on `/dev/null` (`Ctx.run_command
    stdin_devnull=True`), so an unexpected prompt fails loudly instead of hanging
    a bootstrap.
  - **pi reaches agentmemory through the MCP adapter, not through a native pi
    plugin.** agentmemory's pi integration ships as a directory in its repo to be
    copied into `~/.pi/agent/extensions/agentmemory` and re-copied on every
    upgrade — the same version-pinned derived artifact that got the
    single-shared-skills-root option declined above. Since `pi-mcp-adapter` is in
    the extension set anyway, pi gets the memory tools with nothing to re-sync.
  - **pi's half of `MCP_SERVERS` is written to `~/.agents/mcp.json`** rather than
    projected by a command, because pi has no MCP CLI. That file is
    `pi-mcp-adapter`'s documented tool-agnostic source (precedence 2 of 6), no
    agent ever rewrites it (the adapter persists its own overrides in
    `~/.pi/agent/mcp.json` and never writes back), and only declared server names
    are touched — so this is not the agent-config merge-patching this ADR
    declined. The alternative, `pi-mcp-adapter init --discover-host-configs`,
    would import whatever Claude and Codex happen to have, i.e. re-import drift
    instead of projecting the manifest.
  - **The `~/.codex/skills` link is a compatibility belt, not the mechanism.**
    Codex reads `$HOME/.agents/skills` natively at user scope, which this ADR did
    not assume. The link costs one idempotent line and is kept in case an older
    Codex only knows the per-agent path.

  Two findings recorded but deliberately **not** acted on, because each reverses a
  premise this ADR decided on and that is an ADR-level call, not an
  implementation one:

  - **Codex has had a plugin marketplace since 2026-03-26** (`codex plugin
    marketplace add`), so "Codex therefore cannot see `agent-skillset`" is no
    longer a fact about the tool — it is now only a consequence of every
    marketplace entry targeting `claude`. Closing the gap is adding `"codex"` to
    those entries' `agents` plus a Codex marketplace projection.
  - **pi does read a global `AGENTS.md`** under its agent dir, where this ADR has
    it abstaining from plane ①. One more link in `PiAgent.project` would make the
    instruction plane a genuine three-way single point.

  Verified statically: `nix flake check --no-build`, a Linux `activationPackage`
  build (unit + wrapper inspected in the store), a Darwin eval of the `launchd`
  branch, and `setup.py --plan` / `--dry-run` for `--agents` = default / `none` /
  `claude,pi`.

- **2026-08-05 — verified end to end on a clean machine**, a 4 CPU / 8 GiB jcc
  devpod with a pod-local `stateRoot`, so the reference host's live agent state was
  never touched. Nine runs; the last full one goes from bare Ubuntu 24.04 to
  everything provisioned in **2m55s**, and a repeat run is idempotent. Confirmed on
  the machine: claude 2.1.222 · codex 0.146.0 · pi 0.83.0 · agentmemory 0.9.28;
  4 marketplaces + 7 plugins into a fresh Claude config; `codex mcp list` showing
  **both** `agentmemory` and `codegraph` enabled (the three-way MCP single point is
  real, not just declared); all four pi packages recorded in pi's own
  settings.json; and every instruction/skills link resolving to `~/.agents`.

  Five defects that only a clean machine could surface, four of them introduced by
  this implementation:

  - **A failing vendor installer aborted the whole run.** Routing the installers
    through the `scripts` backend inherited its `check=True`, so Claude's installer
    exiting 1 took the rest of the post-HM phase with it. `Script` now carries
    `check`.
  - **`.claude.json` seeded empty reads as corrupt** to Claude Code — an ADR-0009
    defect, fixed there with the new `seed` option.
  - **npm was never found.** `shutil.which("npm")` cannot work on a fresh machine:
    mise's node reaches PATH only through shell integration. It looked fine on the
    reference host purely because that shell has mise activated. Resolved via
    `mise which npm`.
  - **node was not on the *children's* PATH**, so npm's dependency postinstalls
    and the node-shebang CLIs failed with `node: not found`. `ensure_node_on_path`
    now prepends the mise node bin dir, as `Ctx._extend_path` already does for
    `~/.local/bin`.
  - **codegraph silently un-did plane ①.** It reads `~/.codex/AGENTS.md`, appends
    its usage block and writes the result back over the path, replacing the symlink
    with a regular file (measured: shared content + 803 bytes). Ordering alone
    cannot fix it, so links are re-asserted after every delegated installer
    (`Agent.relink`) and an appended-to copy is folded back into the shared source
    (`_link(absorb=True)`).

  Two things remain unexercised, and neither can be tested from here: the
  agentmemory **service** (no jcc devpod has an init system, so the unit is only
  ever written, never started), and Claude's `/model` / `/config` runtime writes,
  which need an interactive session. npm's `allow-scripts` default also skips
  `protobufjs` / `sharp` postinstalls, so pi and agentmemory are installed with
  their native pieces unbuilt.

- **2026-08-05 — two of this ADR's premises are retired, on the owner's call.**
  Both were falsified by tooling that shipped after the ADR was written, and both
  reversals were verified on the test pod rather than taken from release notes:

  - **"Codex therefore cannot see `agent-skillset`" no longer holds.** Codex has
    had a plugin marketplace since 2026-03-26, and its CLI accepts the same source
    shapes Claude's does (`codex plugin marketplace add <SOURCE>`,
    `codex plugin add PLUGIN@MARKETPLACE`). All four marketplaces and all seven
    plugins now target Codex as well; `codex plugin list` shows every one
    *installed, enabled*, `agent-skillset` included. The dual-track skills decision
    stands unchanged — marketplaces stay marketplace-managed, loose skills stay in
    `~/.agents/skills` — what changed is only the reach of the marketplace track,
    so the "deliberately uneven capability surface" consequence loses one of its
    three examples.
  - **pi does not abstain from plane ①.** It loads `AGENTS.md` from its agent dir
    at startup (pi's own README), so `~/.pi/agent/AGENTS.md` links to the shared
    source like Codex's, and the instruction plane is a genuine three-way single
    point instead of a two-party one.

  One finding upgraded from "recorded" to "confirmed, still not acted on": the
  Codex plugin CLI exists and takes the same shapes as Claude's —
  `codex plugin marketplace add <SOURCE>` (local path, `owner/repo[@ref]`, HTTPS or
  SSH git URL) and `codex plugin add PLUGIN@MARKETPLACE`. So closing the
  `agent-skillset` gap is now a verified one-line-per-entry change rather than a
  guess, and remains an ADR-level decision.

- **2026-08-06 — pi is replaced by oh-my-pi (`omp`, can1357/oh-my-pi) in the
  third slot, on the owner's call; the pi extension set retires.** omp is pi's
  fork and ships everything the four pi packages existed for as native features,
  so the replacement is mostly a deletion plus a re-point:

  - **Install channel changes from npm to the `omp` Nix package.** The binary
    comes from the `llm-agents-nix` flake input (numtide/llm-agents.nix,
    `packages/omp` — package-only, no HM module) as `home/packages.nix`'s
    `inputs.llm-agents-nix.packages.${pkgs.system}.omp`, and the HM switch
    places it in `~/.nix-profile/bin`. numtide's daily CI builds are pulled from
    `cache.numtide.com` (declared in flake.nix's `nixConfig`), so a switch does
    not compile the bun+rust source tree. This is the deliberate exception to
    "agent CLI versions stay outside git" — the version is pinned via the flake
    input instead, because the owner asked for a Nix install. pi's npm install
    (`@earendil-works/pi-coding-agent`) and the pi half of the npm machinery are
    gone; the remaining npm path serves agentmemory only.
  - **Config stays out of Home Manager, by construction.** The standing rule
    for all three agents holds for omp unchanged: HM owns only the *binary*.
    `~/.omp` remains an ADR-0009 Tier-B out-of-store staging link
    (home/env-links.nix), the shared-source links and the MCP merge are
    projected by `OmpAgent` at bootstrap, and plugins are installed through
    omp's own interface (`omp install <npm-spec>`) — never by an HM-generated
    config file. `llm-agents.nix` exposes packages only, which is what keeps
    this clean: there is no `programs.omp` module to accidentally adopt.
  - **The four-package extension set is deleted, not migrated.** The mapping:
    `pi-claude-marketplace` → omp's `claude` / `claude-plugins` discovery
    providers read installed Claude marketplaces and plugins for skills, slash
    commands and MCP servers; `pi-mcp-adapter` → omp is a first-class MCP client
    that reads `~/.omp/agent/mcp.json` (the manifest merges its `omp`-targeting
    servers there, add-only — omp's `/mcp` commands rewrite the file itself, so
    this is the same merge contract the adapter had, minus the adapter);
    `pi-tinyfish` → omp ships a native browser tool (no provider credential,
    which was tinyfish's original rationale); `pi-subagents` → omp has native
    sub-agents/custom agents. If a real gap shows up, the manifest grows an
    `omp install <npm-spec>` extension entry (omp preserves pi's extension API) —
    never a per-machine command.
  - **Plane ① moves with the agent dir.** `~/.pi/agent/AGENTS.md` becomes
    `~/.omp/agent/AGENTS.md` (omp's native user-level context file, discovery
    priority 100), still a symlink to `~/.agents/AGENTS.md`; `~/.pi/agent/skills`
    becomes `~/.omp/agent/skills`, and omp also reads `~/.agents/skills` directly
    through its `agents` discovery provider, so that link is a belt, not the
    mechanism. The `~/.pi` env link (home/env-links.nix) becomes `~/.omp`
    (whole-dir, 700 — sessions and the auth store live there too).
  - **agentmemory is unchanged**, still wired to the third slot + Codex via MCP
    (`~/.omp/agent/mcp.json` for omp). omp's own memory backends
    (off/local/hindsight) are recorded as a possible future replacement, not the
    current wiring.
  - **Retirement on already-provisioned machines is manual** — projection is
    add-only, so a machine that got pi keeps it until the owner uninstalls it
    (`npm uninstall -g @earendil-works/pi-coding-agent`). Verified statically on
    the reference host: `python3 platform/installers/agents.py` prints the
    three-agent manifest with omp; `setup.py --plan --agents omp` /
    `--plan-items --agents all` and `./bootstrap.sh --dry-run --verbose` describe
    the nix package, the two shared-source links and the MCP merge;
    `nix flake check --no-build` passes and a targeted eval confirms the `omp`
    derivation from `llm-agents-nix` in `home.packages` (and its absence from
    the mise tools), plus the `.omp` (700) env link. Not yet exercised: a real
    build/substitution of the omp derivation and an omp session (needs network +
    the owner's machine switch), so the runtime claims about omp's native
    surface are taken from its docs, not from a clean-pod run.
