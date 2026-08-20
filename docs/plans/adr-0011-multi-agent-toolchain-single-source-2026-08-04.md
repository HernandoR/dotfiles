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
`astral-sh/astral` are **pure skills** (hooks only in `dev-loop`; no agents, no
`.mcp.json`). So the marketplace bridge needs neither `pi-subagents` nor
`pi-mcp-adapter` as a dependency — both are included for their own sake.
`dev-loop`'s hooks fall under `pi-claude-marketplace`'s documented partial hook
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
  skills, Claude gets no agentmemory, pi gets degraded `dev-loop` hooks. Each
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

  - **Install channel changes from npm to mise's GitHub backend.** The binary is
    declared in `home/mise.nix` as `github:can1357/oh-my-pi` and materialized by
    `mise use -g`/`mise install`. This avoids the long compile time of the Nix
    source build. The version remains outside the flake and Home Manager, so
    mise can update it independently; pi's npm install
    (`@earendil-works/pi-coding-agent`) and the pi half of the npm machinery are
    gone; the remaining npm path serves agentmemory only.
  - **Config stays out of Home Manager, by construction.** The standing rule
    for all three agents holds for omp unchanged: HM owns only the *binary*.
    `~/.omp` remains an ADR-0009 Tier-B out-of-store staging link
    (home/env-links.nix), the shared-source links and the MCP merge are
    projected by `OmpAgent` at bootstrap, and plugins are installed through
    omp's own interface (`omp install <npm-spec>`) — never by an HM-generated
    config file. mise exposes the runtime tool without introducing a
    `programs.omp` module, so this remains clean.
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
    the mise tool, the two shared-source links and the MCP merge;
    `nix flake check --no-build` passes and a targeted eval confirms the `omp`
    mise tool seed and its absence from `home.packages`, plus the `.omp` (700)
    env link. Not yet exercised: a real mise install and an omp session (needs
    network + the owner's machine switch), so the runtime claims about omp's
    native surface are taken from its docs, not from a clean-pod run.

- **2026-08-10 — OMP moves from Nix to mise.** The owner reported that building
  OMP through the Nix source derivation took too long. The package was removed
  from `home/packages.nix` (and the now-unused `llm-agents-nix` flake input and
  cache configuration were removed); `home/mise.nix` now seeds
  `github:can1357/oh-my-pi` for `mise use -g`/`mise install`. OMP's mutable
  configuration and capability projection remain unchanged.

- **2026-08-13 — all memory goes through agentmemory; Claude's built-in memory
  is switched off.** The Memory section above scoped agentmemory to two agents
  and left Claude on `~/.claude/projects/<proj>/memory/`, with "the backend
  proving itself across a period of real use" as the revisit trigger. The owner
  fired that trigger and chose the opposite of the split: **one store for all
  three agents**, not two stores side by side.

  What changed in the repo, both in `platform/installers/agents.py`:

  - the `agentmemory` `McpServer` entry gains `claude`, so `claude mcp add`
    projects it the way `codex mcp add` and the `~/.omp/agent/mcp.json` merge
    already did — which took a fix, because Claude's `_mcp_add` built its
    argument order wrong: `claude mcp add`'s `-e/--env` is variadic, so a server
    name placed after it is swallowed as another `KEY=VALUE`. The bug was latent
    for exactly as long as it could be — agentmemory is the first env-carrying
    server projected to Claude, and codegraph, the only other entry, is
    delegated to its own installer and never took this path;
  - `_agentmemory_wanted` becomes "any agent selected" rather than "codex or
    omp", so a Claude-only run now installs the backend instead of nothing.

  What deliberately did **not** change: the switch that turns Claude's built-in
  memory off is `autoMemoryEnabled: false` in `~/.claude/settings.json`, and
  that file is the **preference plane** — the one plane this ADR states is never
  touched, because all three agents rewrite it at runtime. Projecting it would
  buy reproducibility at the cost of the invariant that keeps `/model`,
  `/config` and plugin installs working, which is a worse trade than applying
  one key per machine. So the capability half is projected and the preference
  half is manual, and this entry is where that split is recorded rather than
  being rediscovered as drift.

  Honest note on the trigger: it fired on the owner's judgement, not on
  evidence, because there is no evidence either way. Inspecting the reference
  host on this date found the binary installed and the MCP entry present in both
  `~/.codex/config.toml` and `~/.omp/agent/mcp.json`, but `~/.agentmemory`
  holding **no SQLite store at all** — only `.env`, the pinned `bin/iii` engine,
  `engine-state.json` and a stale `iii.pid` whose process is gone, all frozen at
  2026-08-10. The daemon has never successfully run here: these hosts have no
  init system (`/run/systemd/system` does not exist, no D-Bus), so
  `agents.start_agentmemory` takes its documented "no systemd user session"
  branch and returns. Nothing was listening on :3111, which meant the MCP shim
  exposed only its degraded surface to all three agents. With the built-in store
  now off, that would have left Claude with no working memory at all — so the
  same round closes it rather than filing it.

  **The init-less host starts the daemon from the bootstrap itself.** On the
  owner's call: start it once per bootstrap and let a machine that goes away take
  the process with it, since `$HOME` on these hosts is container-local and the
  next bootstrap is what brings it back anyway. `agents.start_agentmemory` now
  has three cases in descending order of supervision — launchd, systemd, and a
  detached `subprocess.Popen` (`start_new_session=True`, so it outlives the
  bootstrap shell) — and the third is reachable **only** when neither supervisor
  exists. Hosts with systemd or launchd keep the HM unit and are not touched by
  this path; it is a floor for hosts that cannot have a supervisor, not a
  replacement for one. Nothing restarts the process, which is the accepted trade:
  a crash mid-session stays down until the next bootstrap.

  Three details that keep it honest rather than merely started: the fallback
  probes :3111 first, so re-running a bootstrap cannot stack a second daemon on
  a port the first still holds (the `iii.pid` file is useless for this — it
  outlives the container that wrote it); it then polls the port for up to 15s and
  *reports* whether the daemon actually answered, because a process that exits on
  a bad config looks identical to a healthy one at `Popen` time, and reporting a
  start that did not happen is precisely how this plane stayed dead unnoticed;
  and `plan_items` branches on the same `_has_service_manager` predicate as the
  start path, so the ADR-0010 plan names which of the two ways *this* host will
  start it. Output goes to `~/.agentmemory/bootstrap.log`, truncated per run,
  next to the launchd log paths the unit already uses.

  The `~/.agentmemory` env link (`home/env-links.nix`) was already correct and
  was only ever waiting for a store to persist.

- **2026-08-20 — agentmemory is removed; memory becomes omp-native (mnemopi).**
  The 2026-08-13 entry above put every agent on one agentmemory store, on the
  premise that a shared daemon was the only way to get a real memory backend.
  omp has since grown its own: `memory.backend = mnemopi` is a built-in local
  long-term memory backend (SQLite under omp's agent memories dir, recall/retain/
  reflect + `memory_edit` tools, `/memory` commands) with **no daemon, no port and
  no npm package**. The owner's call is to use it and delete the daemon rather
  than run both.

  What was removed:

  - `home/agentmemory.nix` — the systemd-user / launchd unit. With it goes this
    ADR's *only* Tier A citizen, so the agent toolchain is now entirely
    imperative-plus-links again and `home/default.nix` imports one module less.
  - the `~/.agentmemory` env link (`home/env-links.nix`). The store that has to
    survive container recreation is now inside `~/.omp`, which is already a
    whole-dir Tier-B link at 700.
  - in `platform/installers/agents.py`: the `agentmemory` `McpServer` entry, the
    `AGENTMEMORY_*` constants, `_agentmemory_wanted`, `install_agentmemory`,
    `_has_service_manager`, `_agentmemory_is_up`, `start_agentmemory` and its
    unsupervised fallback — and, with the last npm-installed tool gone, the whole
    npm helper layer (`_npm`, `_npm_global_bin`, `ensure_node_on_path`,
    `_resolve_bin`, `_npm_install_global`). Nothing in a bootstrap starts or
    supervises a resident process any more, which retires the init-less-host
    problem the previous entry solved rather than working around it again.

  What replaced it: `OmpAgent.set_memory_backend` runs
  `omp config set memory.backend mnemopi`, guarded by `omp config get` so it is a
  no-op once set. This is the same projection rule as every other capability —
  through the agent's *own* CLI, never by writing `~/.omp/agent/config.yml`, which
  omp rewrites at runtime (ADR-0009 Tier A still excluded by construction). The
  ADR-0010 plan gains one line naming the setting, and `plan_items` lost its
  install/daemon lines.

  Consequences accepted:

  - **Memory is no longer cross-agent.** Only omp has a projected memory backend;
    Claude and Codex fall back to whatever their own settings say, which is
    preference plane and therefore per machine. The single-store property of the
    2026-08-13 entry is given up deliberately: it was never observed working (see
    that entry's honest note — the daemon had never persisted a store on these
    hosts), so what is lost is a declaration, not a working plane. The `claude
    mcp add` argument-order fix it produced stays; it is correct independently.
  - **Claude's `autoMemoryEnabled: false`** was, and remains, a per-machine
    preference-plane setting this repo never projects. A machine that had it
    turned off for agentmemory's sake should be turned back on by hand; nothing in
    the bootstrap will do it.
  - **Retirement is manual, as always.** Projection is add-only, so an already
    provisioned machine keeps its `agentmemory` MCP entry, its npm install and its
    `~/.agentmemory` directory until the owner removes them.

  Verified on the reference host: `python3 platform/installers/agents.py` prints
  the manifest with `codegraph` as the only MCP server and `memory.backend =
  mnemopi` under omp; `python3 platform/setup.py --plan` shows the single new
  `omp config set` line and no agentmemory install/daemon items; `nix flake check`
  passes with the module and the env link gone; and `omp config get
  memory.backend` reports `mnemopi` after the projection ran.
