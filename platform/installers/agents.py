"""The multi-agent capability manifest and its per-agent projection (ADR-0011,
ADR-0012).

Three coding agents are provisioned from this one file: **Claude Code**, **Codex
CLI** and **pi**. ADR-0011 partitions their configuration into three planes and
treats each differently — this module implements ① and ②, and touches ③ only for
pi, only as a seed, and only because ADR-0012 says so explicitly:

- **① instruction — single-sourced.** ``~/.agents/AGENTS.md`` is the only
  instruction source. ``~/.codex/AGENTS.md`` and ``~/.pi/agent/AGENTS.md`` symlink
  to it; ``~/.claude/CLAUDE.md`` is a thin shell that imports it (Claude Code does
  not read ``AGENTS.md``). Standing rule: nothing cross-agent may be written into
  the Claude shell.
- **② capability — one manifest, projected per agent.** The ``MARKETPLACES`` /
  ``PLUGINS`` / ``MCP_SERVERS`` / ``PI_PACKAGES`` tables below are the single
  reviewed source for what the agents *have*. Claude and Codex get theirs through
  their own CLIs (``claude plugin install``, ``claude mcp add``, ``codex mcp
  add``); pi, which has no MCP and no marketplace CLI, gets its through three
  declarative files this repo owns — ``~/.agents/mcp.json`` (read by
  ``pi-mcp-adapter`` at precedence layer 2, never written back to),
  ``~/.pi/agent/claude-plugins.json`` (``pi-claude-marketplace``'s documented
  user-authored desired state) and the ``packages`` array in pi's settings.
- **③ preference — not unified, and for pi seeded rather than owned.** Model,
  theme and approval policy stay per-agent. All three agents rewrite their own
  config at runtime (Claude ``/model``+``/config``, Codex ``/model``, pi
  ``/settings``+``/model``+``pi install``), which is why none of these files can
  be a Home Manager store link — ADR-0009 Tier A is excluded by construction, not
  by preference. pi is the one exception ADR-0012 grants, and it keeps that rule's
  protection by changing the contract from *own* to **seed**: values are written
  leaf by leaf when absent and never overwritten, so runtime writes survive.

**Projection is add-only** (ADR-0011, Consequences): deleting an entry here does
not uninstall it from a machine that already applied it. That gap cost something
twice on 2026-08-28 — a retired ``agentmemory`` server still declared in
``~/.agents/mcp.json``, and a manifest six plugins and one marketplace behind the
live machine — so the two files this repo *writes whole* now also remove names
they used to declare (``RETIRED_MCP_SERVERS``, ``RETIRED_PI_PACKAGES``). Anything
the manifest never knew about is still left alone.

The third slot has changed occupant twice, and the current reasons matter more
than the history:

- **Codex has a plugin marketplace** (``codex plugin marketplace add <SOURCE>`` /
  ``codex plugin add PLUGIN@MARKETPLACE``, verified on the machine), so ADR-0011's
  accepted "Codex cannot see ``agent-skillset``" gap is closed. The dual-track
  skills decision is unchanged — marketplaces stay marketplace-managed, loose
  skills stay in ``~/.agents/skills`` — only the *reach* of the marketplace track
  grew, and it now reaches pi as well.
- **pi replaced omp in the third slot (2026-08-28; ADR-0012), for
  interoperability rather than features.** omp is the richer binary: it ships MCP,
  sub-agents, memory and a browser natively, all of which upstream pi refuses by
  design. What it does not have is *presence* — it appears in no IDE plugin's or
  ACP client's supported-agent list, and its mise-installed binary cannot even be
  resolved by a process that is not an interactive zsh, because mise's shims reach
  PATH only through ``mise activate``. pi installs to ``~/.local/bin``, which is
  on ``home.sessionPath``. The price is that every capability omp had natively is
  now a third-party extension (``PI_PACKAGES``), and that price was accepted
  knowingly.

Memory is the one plane that is genuinely cross-agent: a single MCP
knowledge-graph store at ``~/.agents/memory/memory.jsonl``, declared once in
``MCP_SERVERS`` and reaching all three agents. It sits under ``~/.agents``
deliberately — that root is a Tier-B env link onto the Lustre state volume, so the
store is cross-machine with no service, no credential and no egress.
"""

import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys

if __package__ in (None, ""):  # run directly (`python3 platform/installers/agents.py`)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from installers.managers import Script  # noqa: E402

logger = logging.getLogger("dotfiles")

HOME = pathlib.Path.home()

# --- the shared root ---------------------------------------------------------
# ~/.agents is an ADR-0009 Tier-B link (home/env-links.nix) so everything below
# lives on the persistent volume and is writable — the instruction source is a
# file the owner edits, and the skills dir is written by installers (lark-cli
# already symlinks into it).
AGENTS_DIR = HOME / ".agents"
SHARED_INSTRUCTIONS = AGENTS_DIR / "AGENTS.md"
SHARED_SKILLS = AGENTS_DIR / "skills"
# The tool-agnostic MCP source (ADR-0012). `pi-mcp-adapter` reads this file at
# precedence layer 2 of 6 and NEVER writes back to it — `/mcp disable|enable`
# writes only a `disabled` field to `.pi/mcp.json` — so unlike omp's own
# ~/.omp/agent/mcp.json this is a file the repo genuinely owns. Claude and Codex
# still get their servers through their own CLIs; this is pi's half of the same
# single point.
SHARED_MCP = AGENTS_DIR / "mcp.json"

# The shared memory plane (ADR-0012). One MCP knowledge-graph store that all
# three agents reach, deliberately inside ~/.agents rather than under any one
# agent's dir: ~/.agents is a Tier-B env link whose target is on the Lustre
# stateRoot, so the store is cross-machine by construction — no service, no
# credential, no egress. MEMORY_FILE must be ABSOLUTE: a relative
# MEMORY_FILE_PATH resolves against the server's own package dir, and the
# default store lives there too, where an `npx` reinstall would discard it.
SHARED_MEMORY_DIR = AGENTS_DIR / "memory"
SHARED_MEMORY_FILE = SHARED_MEMORY_DIR / "memory.jsonl"
# Where the retired mnemopi banks are exported to (scripts/export-mnemopi-banks.py).
# Read by a human or grepped by an agent; deliberately NOT auto-loaded as context.
SHARED_MEMORY_ARCHIVE = AGENTS_DIR / "memory-archive"

SHARED_INSTRUCTIONS_SEED = """\
# AGENTS.md — shared agent instructions

The single instruction source for every coding agent on this machine (ADR-0011
plane ①). Codex reads it as `~/.codex/AGENTS.md`; Claude Code reads it through the
`@~/.agents/AGENTS.md` import at the top of `~/.claude/CLAUDE.md`.

Anything that applies to more than one agent belongs **here**. Claude-only rules
go in the `~/.claude/CLAUDE.md` shell — nothing else does.

<!-- your cross-agent rules below -->
"""

# --- ② the capability manifest ----------------------------------------------
# Every entry says which agents it targets and why it is where it is. Adding a
# capability is an edit here plus a commit — never a per-machine command.


class Marketplace:
    """A Claude-Code plugin marketplace (``claude plugin marketplace add``).

    ``source`` is whatever that command accepts: a ``owner/repo`` GitHub shorthand
    or a git URL.
    """

    def __init__(self, name, source, agents=("claude",), note=""):
        self.name = name
        self.source = source
        self.agents = tuple(agents)
        self.note = note


class Plugin:
    """A plugin from one of the marketplaces above, installed at user scope."""

    def __init__(self, name, marketplace, agents=("claude",), note=""):
        self.name = name
        self.marketplace = marketplace
        self.agents = tuple(agents)
        self.note = note

    @property
    def qualified(self):
        return "{}@{}".format(self.name, self.marketplace)


class McpServer:
    """An MCP server, declared once and projected to every agent that wants it.

    Either a stdio server (``command`` + ``args``) or a remote one (``url``).
    ``delegated=True`` means some other installer already writes this server into
    the agents' config and the projection must not add it a second time (codegraph
    installs itself into Claude *and* Codex, including Claude's auto-allow list,
    which we could not reproduce from here).
    """

    def __init__(self, name, agents, command=None, args=(), env=None, url=None,
                 delegated=False, note=""):
        self.name = name
        self.agents = tuple(agents)
        self.command = command
        self.args = list(args)
        self.env = dict(env or {})
        self.url = url
        self.delegated = delegated
        self.note = note

    def block(self):
        """The server as the standard ``mcpServers`` JSON block (what SHARED_MCP
        holds, and the shape every MCP host but Codex uses)."""
        if self.url:
            return {"url": self.url}
        block = {"command": self.command, "args": self.args}
        if self.env:
            block["env"] = self.env
        return block


class PiPackage:
    """One pi extension package, as `pi install` would record it in settings.json.

    ``spec`` is the verbatim source string, and it MUST carry an explicit scheme
    prefix — see the note above PI_PACKAGES for why a bare name silently installs
    nothing. ``note`` says why the package is in the set, since with pi almost every
    capability is a third-party choice that deserves a reason.
    """

    def __init__(self, spec, note=""):
        self.spec = spec
        self.note = note


# Marketplaces — all four that the reference host actually has, and both agents
# that have a marketplace mechanism. `worktrunk` and `composio` were installed by
# hand and existed nowhere in the repo; closing that drift is the whole reason
# ADR-0011 supersedes ADR-0005, so do not remove them because they look
# unfamiliar.
#
# Codex joined these after the ADR: it grew a plugin marketplace (2026-03-26) that
# takes the same source shapes Claude's does, which retires the ADR's accepted
# "Codex cannot see agent-skillset" gap. Projection is best-effort per entry, so a
# plugin Codex cannot use fails as one warning rather than as a broken run.
# Every agent with a marketplace mechanism. Claude and Codex have real CLIs; pi
# reads marketplaces through `pi-claude-marketplace`, whose declarative config
# (~/.pi/agent/claude-plugins.json) is generated from these same two tables
# (ADR-0012). An entry that genuinely cannot reach one of the three should name its
# agents explicitly rather than using this tuple, so the exception stays visible.
#
# A marketplace MUST target every agent its plugins do: pi-claude-marketplace
# resolves a plugin against the declared marketplaces and reports
# "<marketplace not declared>" otherwise.
ALL_MARKETS = ("claude", "codex", "pi")

MARKETPLACES = (
    Marketplace("agent-skillset", "hernandor/agent-skillset", agents=ALL_MARKETS,
                note="the owner's own skills: discuss / implement / dev-loop / fetch-external-knowledge"),
    Marketplace("astral-sh", "astral-sh/claude-code-plugins", agents=ALL_MARKETS,
                note="Astral's Python tooling skills (uv / ruff / ty)"),
    Marketplace("worktrunk", "max-sixty/worktrunk", agents=ALL_MARKETS,
                note="worktrunk (`wt`) worktree workflow — the CLI itself is a mise tool"),
    Marketplace("composio", "https://github.com/ComposioHQ/composio-plugin-cc.git",
                agents=ALL_MARKETS,
                note="Composio tool bridge; a git URL rather than a GitHub shorthand"),
    Marketplace("mewtant-plugins", "troph-team/mewtant-plugins", agents=ALL_MARKETS,
                note="the team's own plugins (mldatakit / spdl-pipeline / hugging-face-buckets "
                     "/ feedback). Was installed by hand and existed nowhere in the repo — the "
                     "same drift ADR-0011 was written to stop, found again on 2026-08-28"),
)

# Plugins, one per marketplace entry that has one. `agent-skillset` ships four
# separate plugins and there is still no bulk-install command.
PLUGINS = (
    Plugin("discuss", "agent-skillset", agents=ALL_MARKETS),
    Plugin("implement", "agent-skillset", agents=ALL_MARKETS),
    Plugin("dev-loop", "agent-skillset", agents=ALL_MARKETS,
           note="its hooks are the only non-skill content in agent-skillset; Codex has a "
                "hook engine, and pi-claude-marketplace supports hooks only partially — "
                "expected to degrade, not a defect to chase"),
    Plugin("fetch-external-knowledge", "agent-skillset", agents=ALL_MARKETS),
    Plugin("reclaim-code-entropy", "agent-skillset", agents=ALL_MARKETS,
           note="drift found 2026-08-28: enabled on the machine, absent from this table"),
    Plugin("astral", "astral-sh", agents=ALL_MARKETS),
    Plugin("worktrunk", "worktrunk", agents=ALL_MARKETS),
    Plugin("composio", "composio", agents=ALL_MARKETS),
    # The four mewtant-plugins entries, all drift found on 2026-08-28.
    Plugin("mldatakit", "mewtant-plugins", agents=ALL_MARKETS),
    Plugin("spdl-pipeline", "mewtant-plugins", agents=ALL_MARKETS),
    Plugin("hugging-face-buckets", "mewtant-plugins", agents=ALL_MARKETS),
    Plugin("feedback-mewtant-plugins", "mewtant-plugins", agents=ALL_MARKETS),
    # `pyright-lsp@claude-plugins-official` is enabled on the machine and is NOT
    # here on purpose: its marketplace is a Claude *builtin*, absent from
    # extraKnownMarketplaces, so there is nothing for the Codex or pi projections
    # to add it from. Recording the exception beats silently dropping it.
)

# MCP servers. `agents` is the single point ADR-0011 promises: one entry reaches
# Claude via `claude mcp add`, Codex via `codex mcp add`, and pi via SHARED_MCP
# (pi has no native MCP at all, so pi-mcp-adapter reads that file for it).
MCP_SERVERS = (
    McpServer(
        "codegraph", agents=("claude", "codex", "pi"),
        command="codegraph", args=["serve", "--mcp"], delegated=True,
        note="code-intelligence graph; `codegraph install` wires Claude + Codex itself "
             "(and writes Claude's auto-allow list), so only pi is projected from here",
    ),
    McpServer(
        "memory", agents=("claude", "codex", "pi"),
        command="npx", args=["-y", "@modelcontextprotocol/server-memory"],
        env={"MEMORY_FILE_PATH": str(SHARED_MEMORY_FILE)},
        note="the toolchain's shared memory plane (ADR-0012): one knowledge graph of "
             "entities/relations/observations at ~/.agents/memory/memory.jsonl. It lives in "
             "~/.agents on purpose — that root is a Tier-B env link onto the Lustre "
             "stateRoot, so the store is cross-machine with no service, no credential and "
             "no egress. This is the FIRST env-carrying server ever projected to Claude, "
             "which is what the `claude mcp add` argument-order fix (2026-08-13) was written "
             "for. Known trade: the server read-modify-writes the whole file with no lock, "
             "so concurrent writers lose each other's recent additions — most likely the "
             "three agents on ONE host, not two hosts. Accepted on the same "
             "one-writer-at-a-time basis the Lustre stateRoot already relies on",
    ),
    # The Smithery *namespace* endpoint (https://mcp.smithery.run/<namespace>) is
    # deliberately NOT here: its name comes from the logged-in Smithery account,
    # not from the repo, so it stays in the deferred interactive setup that can
    # ask `smithery namespace show`.
)

# Servers this repo used to declare and no longer does. Projection is otherwise
# add-only, which is why this list has to exist: without it a retired server stays
# in SHARED_MCP forever. `agentmemory` is the case that proved it — retired on
# 2026-08-20 with its unit, env link and npm install, but still declared in
# ~/.agents/mcp.json on 2026-08-28 pointing at a port nothing serves. A name here
# is removed only from files this repo writes, and only when the manifest no longer
# declares it; servers the manifest never knew about are still left alone.
RETIRED_MCP_SERVERS = ("agentmemory",)

# --- pi's extension set ------------------------------------------------------
# pi refuses MCP, sub-agents, memory, plan mode, permission prompts and background
# bash BY DESIGN (its own README: "Build CLI tools with READMEs, or build an
# extension"). So every capability omp had natively is an extension here. The owner
# chose full parity knowingly (ADR-0012); the *composition* below is mostly forced
# by peer dependencies and tool-name collisions, not preferred.
#
# These are NOT installed by a `pi install` subprocess from this module. They are
# seeded into `packages` in pi's settings.json, and pi installs any missing one
# itself at startup — verified in dist/: resolve() runs with no onMissing callback,
# so installMissing() installs unconditionally (only PI_OFFLINE stops it). That
# removes nine subprocess calls and the partial-install failure mode with them.
#
# The `npm:` prefix is MANDATORY. Anything not prefixed
# npm:/git:/github:/http:/https:/ssh: is parsed as a *local path*, and a missing
# local path is skipped SILENTLY — so a bare "pi-lens" yields no extension and no
# warning. pi's own docs/settings.md example gets this wrong.
PI_PACKAGES = (
    PiPackage("npm:pi-mcp-adapter",
              note="MCP for pi, which has none natively. Reads SHARED_MCP at precedence "
                   "layer 2 of 6 and never writes back to it. Keep hostConfigDiscovery at "
                   "its default `off` — turning it on re-imports whatever Claude and Codex "
                   "happen to have, i.e. re-imports drift"),
    PiPackage("npm:pi-subagents",
              note="sub-agents. FORCED choice: pi-claude-marketplace declares a peer on "
                   "`pi-subagents >= 0.35.0`, which only this unscoped package satisfies — "
                   "@tintinweb/ and @gotgenes/ are different package names. All three also "
                   "collide on tool names, so exactly one may be installed. Its `subagents.*` "
                   "keys in pi's settings.json are where omp's modelRoles land"),
    PiPackage("npm:pi-memory",
              note="pi's LOCAL memory layer (markdown+JSON under ~/.pi/agent/memory). "
                   "'Local' means one agent, not one machine — ~/.pi is an env link too. The "
                   "shared layer is the `memory` MCP server above. Leave its optional qmd "
                   "index off: it is the package's only egress path"),
    PiPackage("npm:pi-claude-marketplace",
              note="the skills/plugins bridge to Claude. Does NOT read "
                   "~/.claude/plugins/cache — it is an independent marketplace client that "
                   "clones from git itself, so Claude's version-bearing cache paths are "
                   "irrelevant to it. Its declarative config is generated from MARKETPLACES "
                   "+ PLUGINS (see write_pi_claude_plugins)"),
    PiPackage("npm:pi-web-search",
              note="web search. The ONLY candidate reaching Anthropic's native Messages-API "
                   "search, so no extra credential — exactly the rationale that once chose "
                   "pi-tinyfish over pi-websearch, now satisfiable without a third-party key"),
    PiPackage("npm:pi-web-access",
              note="installed for `fetch_content` ONLY — the one keyless intranet-capable "
                   "fetcher (local HTTP, local PDF, local git clone). It collides with "
                   "pi-web-search on `web_search` and is the only one of the two with a "
                   "rename/disable knob, so it gives that tool up. Needs ssrf.allowRanges "
                   "widened for intranet hosts while fetchRouting.allowRemoteHostedProviders "
                   "stays false. Config: ~/.pi/web-search.json (NOT under ~/.pi/agent/)"),
    PiPackage("npm:pi-lens",
              note="LSP + diagnostics, replacing omp's native LSP, and the nearest thing to "
                   "omp's `edit.mode: hashline` (it ships hashline-anchored edit tools). "
                   "Accepted with a named risk: no CI signal, it pins `pi-tui ^0.84.1` — the "
                   "tightest coupling to pi internals in the set — and it rewrites source "
                   "files. Config: ~/.pi-lens/config.json, OUTSIDE ~/.pi, hence its own env link"),
    PiPackage("npm:@plannotator/pi-extension",
              note="plan mode, which pi also refuses. Set `model: null` in its config or it "
                   "overrides the session model with its bundled claude-sonnet-4-5 default"),
    PiPackage("npm:pi-background-tasks",
              note="background bash. Its Fusion routes admit only subscription OAuth and "
                   "reject metered API keys before child creation — satisfied, these hosts "
                   "use OAuth. Also installs a provider that rewrites Anthropic request "
                   "metadata; audit that on first use"),
    # Deliberately NOT here, each for a stated reason:
    # - pi-tinyfish / pi-brave-search: both need a third-party key, both ~3.5 months
    #   stale at 29-60 downloads/week, and both are already providers inside
    #   pi-web-access. The retired set's web-search entry is not restored as-is.
    # - @gotgenes/pi-permission-system: pairs with @gotgenes/pi-subagents, which the
    #   forced sub-agent choice above rules out; and it would be a SECOND approval
    #   broker over the same MCP calls as pi-mcp-adapter ("first synchronous claim
    #   wins") with no documented coordination protocol between them.
)

# --- install channels --------------------------------------------------------
# claude and codex use their official installers (ADR-0011, "Install channels"):
# versions stay outside git so each tool's self-update keeps working.
CODEX_INSTALLER = "https://chatgpt.com/codex/install.sh"

# pi's install channel, and it is a constraint rather than a preference (ADR-0012).
# `npm install -g --prefix ~/.local` is the only channel satisfying all three of:
#
#   1. the binary lands at ~/.local/bin/pi, which IS on home.sessionPath — the
#      whole point of the switch, since mise's shims reach PATH only through the
#      interactive-zsh `mise activate` integration, so nothing that is not an
#      interactive shell (a VS Code extension host, an editor spawning an ACP
#      server, a just recipe) could ever resolve the mise-installed omp;
#   2. `pi update --self` keeps working: the --prefix breakage of
#      earendil-works/pi#3942 was fixed in 0.72.0, and pi infers the prefix from
#      exactly the <prefix>/lib/node_modules layout that ~/.local produces;
#   3. --ignore-scripts is pi's own documented recommendation and independently
#      avoids the native-postinstall failures of the 2026-08-05 clean-pod run.
#
# Rejected: mise (any backend — reproduces the PATH gap being escaped), npm -g at
# mise's own node prefix (same gap; the pre-omp PiAgent had this defect and nobody
# noticed), the nixpkgs attr (pins the version into the flake, inverting the
# versions-stay-outside-git rule), GitHub-release Bun binaries (pi returns no
# self-update path for the bun-binary method) and pi.dev/install.sh (picks a prefix
# of its own choosing).
#
# NOTE: the `npmCommand` setting must be left UNSET in pi's settings. pi skips
# prefix inference entirely when it is present, silently re-breaking self-update.
PI_NPM_PACKAGE = "@earendil-works/pi-coding-agent"
PI_NPM_PREFIX = HOME / ".local"

# pi's own paths. Its settings file is settings.json (JSON) — config.yml was omp's.
PI_AGENT_DIR = HOME / ".pi" / "agent"
PI_SETTINGS = PI_AGENT_DIR / "settings.json"
PI_CLAUDE_PLUGINS = PI_AGENT_DIR / "claude-plugins.json"

# pi extension specs this repo used to declare and no longer does. Same reason
# RETIRED_MCP_SERVERS exists: the seed is otherwise add-only, so without this a
# dropped package never leaves. `pi-tinyfish` is the live case — the pre-omp
# settings.json on this host still lists it, and it is abandoned upstream (0.1.1,
# last published 2026-05-15, peer range `*`).
RETIRED_PI_PACKAGES = (
    "npm:pi-tinyfish",
    "npm:pi-claude-marketplace@0.13.0",
)

# The plane-③ preset (ADR-0012). Seeded LEAF BY LEAF and add-only: a key already
# present in pi's settings.json is never overwritten, so `/model`, `/theme` and a
# hand edit all survive. `packages` is the exception and is reconciled instead —
# it is plane ② capability, not preference.
#
# pi's own write path makes this safe: persistScopedSettings re-reads the file
# under a lock and copies in only the fields modified that session, unknown keys
# ride through untouched, and nested objects merge key by key. There is no schema
# and no schemaVersion. A malformed file is never clobbered but IS ignored
# entirely, so this must stay strict JSON.
#
# Three values are NOT carried over from omp's config.yml, having been checked
# against pi 0.84.3's actual schema rather than assumed:
#   - `defaultThinkingLevel: auto` is INVALID here (off|minimal|low|medium|high|
#     xhigh|max), so it becomes `medium`, pi's own default;
#   - `modelRoles` has no upstream equivalent at all — omp's --smol/--slow/--plan
#     and PI_SMOL_MODEL/PI_SLOW_MODEL/PI_PLAN_MODEL are fork additions with zero
#     hits in pi's tarball. The eight roles are remapped onto pi-subagents'
#     `subagents` block below, against ITS vocabulary (oracle/reviewer/worker/…),
#     which is a remap to review rather than a rename;
#   - `theme` is one string, "<light>/<dark>", and `titanium` is not a built-in —
#     it would need ~/.pi/agent/themes/titanium.json first.
#
# `disabledProviders` (~80 ids in omp) has no equivalent and is mostly moot: pi
# only offers providers with saved credentials. `enabledModels` below does the
# same job in one glob. Keys with no equivalent anywhere, accepted as lost:
# symbolPreset, autolearn, github, composer, setupVersion, mnemopi.
#
# `npmCommand` is deliberately ABSENT — setting it makes pi skip prefix inference
# and silently breaks `pi update --self` (see PI_NPM_PREFIX).
PI_SETTINGS_SEED = {
    "defaultProvider": "anthropic",
    "defaultModel": "claude-opus-5",
    "defaultThinkingLevel": "medium",
    "enabledModels": ["anthropic/claude-*"],
    "modelThinkingLevels": {"anthropic/claude-haiku-4-5": "low"},

    "theme": "light/dark",
    "collapseChangelog": True,
    "autocompleteMaxVisible": 10,
    "showCacheMissNotices": True,

    "compaction": {"enabled": True},
    "retry": {"enabled": True},

    # Telemetry defaults to ON upstream; turn it off explicitly. The Anthropic
    # extra-usage warning stays ON on purpose: with subscription OAuth,
    # third-party-harness tokens can bill as extra usage and this is the only
    # thing that says so.
    "enableInstallTelemetry": False,
    "enableAnalytics": False,
    "enableSkillCommands": True,
    "warnings": {"anthropicExtraUsage": True},
    "defaultProjectTrust": "ask",

    # Read by pi-subagents out of pi's settings.json (pi preserves it as an
    # unknown key). This is where omp's modelRoles land.
    "subagents": {
        "defaultProvider": "anthropic",
        "defaultModel": "anthropic/claude-sonnet-5",
        "defaultThinking": "medium",
        "maxThinking": "max",
        "agentOverrides": {
            "oracle": {"model": "anthropic/claude-opus-5", "thinking": "high"},
            "reviewer": {"model": "anthropic/claude-sonnet-5", "thinking": "high"},
            "worker": {"model": "anthropic/claude-sonnet-5", "thinking": "medium"},
            "delegate": {"model": "anthropic/claude-sonnet-5", "thinking": "medium"},
            "researcher": {"model": "anthropic/claude-sonnet-5", "thinking": "medium"},
            "scout": {"model": "anthropic/claude-haiku-4-5", "thinking": "low"},
        },
    },
}

# Agent ids that `codegraph install --target` accepts (a bad id makes it print the
# list). pi is not one of them — it gets codegraph through SHARED_MCP instead.
CODEGRAPH_TARGETS = ("claude", "codex")


# --- small filesystem / mise helpers ----------------------------------------


def _read(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def _stdout(completed):
    """Decoded, stripped stdout of a ``run_command(capture_output=True)`` result."""
    out = getattr(completed, "stdout", b"") or b""
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    return out.strip()


def _mise_which(ctx, name):
    """Resolve a mise-managed binary (``mise which <name>``), or None.

    mise's shims only land on PATH through the *shell* integration, never in this
    process. `mise which` resolves the installed binary even when its dir is off
    this process' PATH, and is a cheap non-zero exit for tools mise does not
    manage (claude, codex).
    """
    mise = shutil.which("mise")
    if not mise:
        return None
    out = ctx.run_command([mise, "which", name], capture_output=True, check=False)
    resolved = _stdout(out)
    if resolved and pathlib.Path(resolved).is_file():
        return resolved
    return None


_NPM = []  # one-slot cache: `mise which npm` is a mise start-up per call


def _npm(ctx):
    """Path to the npm of the mise-managed node runtime, or None.

    ``shutil.which`` is not enough. ``setup_runtimes`` materializes node under
    ``~/.local/share/mise/installs/…``, which reaches PATH only through mise's
    *shell* integration — never in this process. On a machine whose shell has mise
    activated the plain lookup happens to work; on a fresh one it always misses,
    which once silently skipped the npm-installed agents entirely (found on a clean
    devpod bootstrap, 2026-08-05). So ask mise where npm is.
    """
    if _NPM:
        return _NPM[0]
    npm = shutil.which("npm")
    if not npm:
        mise = shutil.which("mise")
        if mise:
            out = ctx.run_command([mise, "which", "npm"], capture_output=True, check=False)
            resolved = _stdout(out)
            if resolved and pathlib.Path(resolved).is_file():
                npm = resolved
    if not npm:
        if ctx.dry_run:
            # Describe-only run: nothing is installed, so name the command anyway.
            npm = "npm"
        else:
            logger.warning("npm not resolvable via PATH or `mise which npm`; skipping pi")
    _NPM.append(npm)
    return npm


def ensure_node_on_path(ctx):
    """Put the mise node's bin dir on this process' PATH.

    Resolving npm by absolute path is not enough, because the *children* need node
    too: npm runs a dependency's ``postinstall`` as ``sh -c node …``, and pi itself
    is a node script behind a ``#!/usr/bin/env node`` shebang. On a clean pod that
    failed with ``node: not found`` until this existed.

    Same idea as ``Ctx._extend_path`` for ~/.local/bin: this process installs a
    tool and then uses it, so it needs the PATH the login shell would have.
    """
    npm = _npm(ctx)
    if not npm or npm == "npm":
        return
    bin_dir = str(pathlib.Path(npm).parent)
    path = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in path:
        os.environ["PATH"] = os.pathsep.join([bin_dir, *path])
        logger.info("added the mise node bin dir to PATH: %s", bin_dir)


def _link(ctx, link, target, absorb=False):
    """Point ``link`` at ``target``, non-destructively.

    A correct link is a no-op; a link pointing elsewhere is repointed; a *real*
    file or directory is moved to ``<name>.backup`` first — the same suffix Home
    Manager uses, so a bootstrap only ever has one backup convention (ADR-0009).
    The plan describes that move in its own highlighted section (ADR-0010).

    ``absorb`` handles the one case where a *.backup would lose real content: a
    tool that reads the linked file, appends to it, and writes the result back
    over the link path — which replaces the symlink with a regular file. codegraph
    does exactly this to ``~/.codex/AGENTS.md`` (verified on a clean pod: the file
    it left behind was the shared source plus 803 bytes of its own). When the
    displaced file starts with the target's content, the addition is folded into
    the target — the single source keeps it — and the link is restored.
    """
    if ctx.dry_run:
        logger.info("[DRY-RUN] would link %s -> %s", link, target)
        return
    if link.is_symlink():
        if os.readlink(str(link)) == str(target):
            return
        link.unlink()
    elif link.exists():
        if absorb and _absorb_into_target(link, target):
            link.symlink_to(target)
            return
        backup = link.with_name(link.name + ".backup")
        logger.warning("%s exists and is not a link; moving it to %s", link, backup)
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(str(backup))
        elif backup.exists() or backup.is_symlink():
            backup.unlink()
        shutil.move(str(link), str(backup))
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    logger.info("linked %s -> %s", link, target)


def _absorb_into_target(link, target):
    """Fold an appended-to copy back into ``target``. True when it was handled.

    Only the unambiguous shape is accepted — the displaced file is the target's
    content plus a suffix — because anything else is a genuine conflict that
    deserves the .backup and a warning rather than a guess.
    """
    if not (link.is_file() and target.is_file()):
        return False
    try:
        displaced, existing = link.read_text(), target.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    if displaced == existing:
        link.unlink()
        return True
    if not displaced.startswith(existing):
        return False
    target.write_text(displaced)
    link.unlink()
    logger.info("absorbed %d bytes appended to %s back into %s",
                len(displaced) - len(existing), link, target)
    return True


def _shared_mcp_is_usable():
    """True when SHARED_MCP is absent or already a JSON object we can merge into."""
    if not SHARED_MCP.exists():
        return True
    try:
        return isinstance(json.loads(SHARED_MCP.read_text()), dict)
    except ValueError:
        return False


def _link_is_current(link, target):
    """Read-only sibling of ``_link``, for the plan."""
    try:
        return link.is_symlink() and os.readlink(str(link)) == str(target)
    except OSError:
        return False


def ensure_shared_root(ctx):
    """Create ``~/.agents`` + ``~/.agents/skills`` and seed the instruction
    source if it is missing. Seeding only: an existing AGENTS.md is the owner's
    text and is never rewritten."""
    if ctx.dry_run:
        logger.info("[DRY-RUN] would ensure %s, %s and seed %s",
                    AGENTS_DIR, SHARED_SKILLS, SHARED_INSTRUCTIONS)
        return
    SHARED_SKILLS.mkdir(parents=True, exist_ok=True)
    if not SHARED_INSTRUCTIONS.exists():
        SHARED_INSTRUCTIONS.write_text(SHARED_INSTRUCTIONS_SEED)
        logger.info("seeded the shared instruction source -> %s", SHARED_INSTRUCTIONS)


def write_shared_mcp(ctx):
    """Project every ``pi``-targeting MCP server into ``~/.agents/mcp.json``.

    This is pi's half of the MCP single point. ``pi-mcp-adapter`` reads this path
    as its *tool-agnostic* source at precedence layer 2 of 6, and — verified
    against the adapter's own documentation — **never writes back to it**:
    ``/mcp disable|enable`` persists only a ``disabled`` field into
    ``.pi/mcp.json``. So unlike omp's ``~/.omp/agent/mcp.json``, this is a file
    the repo genuinely owns rather than shares with the agent.

    The merge is still add-only: declared servers are updated, anything else the
    owner put here is kept, and an unparseable file is moved aside (``.backup``)
    rather than discarded.

    One condition travels with this file: the adapter's ``hostConfigDiscovery``
    must stay at its default ``off``. Turning it on imports whatever Claude and
    Codex happen to have, which is re-importing drift rather than projecting the
    manifest.
    """
    wanted = {s.name: s.block() for s in MCP_SERVERS if "pi" in s.agents}
    if ctx.dry_run:
        logger.info("[DRY-RUN] would declare %s in %s", ", ".join(wanted) or "nothing", SHARED_MCP)
        return
    data = {}
    if SHARED_MCP.exists():
        try:
            data = json.loads(SHARED_MCP.read_text())
        except ValueError:
            data = None
        if not isinstance(data, dict):
            backup = SHARED_MCP.with_name(SHARED_MCP.name + ".backup")
            logger.warning("%s is not a JSON object; moving it to %s", SHARED_MCP, backup)
            shutil.move(str(SHARED_MCP), str(backup))
            data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    # Reconcile, not merely add: a server this repo used to declare and no longer
    # does must be able to leave. `agentmemory` is the live case — retired on
    # 2026-08-20 but still sitting in this file on 2026-08-28, pointing at a port
    # nothing serves, because projection had only ever been add-only. Anything the
    # manifest never declared is still left alone.
    for stale in [n for n in servers if n in RETIRED_MCP_SERVERS and n not in wanted]:
        logger.info("removing retired MCP server %r from %s", stale, SHARED_MCP)
        servers.pop(stale)
    servers.update(wanted)
    data["mcpServers"] = servers
    SHARED_MCP.parent.mkdir(parents=True, exist_ok=True)
    SHARED_MCP.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("declared %s in %s", ", ".join(sorted(wanted)), SHARED_MCP)


def ensure_shared_memory(ctx):
    """Create the shared memory store's directory.

    The MCP server creates the JSONL file itself on first write, but not its
    parent. ~/.agents already exists (ensure_shared_root), so this is one mkdir.
    """
    if ctx.dry_run:
        logger.info("[DRY-RUN] would create %s", SHARED_MEMORY_DIR)
        return
    SHARED_MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _seed_missing_leaves(current, seed):
    """Add every leaf of ``seed`` that ``current`` does not already have.

    Recurses into dicts so nested objects merge per *leaf*: seeding one
    ``subagents.agentOverrides`` entry cannot wipe the others, and a value the host
    changed is never overwritten. Returns True when anything was added.
    """
    changed = False
    for key, value in seed.items():
        if isinstance(value, dict):
            existing = current.get(key)
            if not isinstance(existing, dict):
                if key in current:
                    # The host replaced this object with a scalar. Their call.
                    continue
                current[key] = {}
                existing = current[key]
            if _seed_missing_leaves(existing, value):
                changed = True
        elif key not in current:
            current[key] = value
            changed = True
    return changed


def seed_pi_settings(ctx):
    """Seed ``~/.pi/agent/settings.json`` — plane ③ preset, plane ② packages.

    Two contracts in one file, split by ADR-0011's planes (ADR-0012):

    * ``packages`` is **capability**, so it is reconciled: every manifest spec is
      ensured present and every *retired* spec is removed. Host additions are
      kept. A uniform add-only rule was tried and falsified — the pre-omp
      settings.json on this host already had a ``packages`` key, so add-only would
      have declined to write the new list and left pi running the old four
      including the abandoned ``pi-tinyfish``.
    * everything else is **preference**, seeded leaf by leaf and never overwritten,
      so ``/model``, ``/theme`` and hand edits survive re-projection.

    pi acts on ``packages`` itself: at startup it resolves the array with no
    onMissing callback and installs anything missing, so this replaces a
    nine-command ``pi install`` projection and the partial-install failure mode
    that came with it.
    """
    wanted = [pkg.spec for pkg in PI_PACKAGES]
    if ctx.dry_run:
        logger.info("[DRY-RUN] would seed %s (%d preference key(s)) and reconcile "
                    "%d package(s); pi installs them itself at startup",
                    PI_SETTINGS, len(PI_SETTINGS_SEED), len(wanted))
        return
    current = {}
    if PI_SETTINGS.exists():
        try:
            current = json.loads(PI_SETTINGS.read_text())
        except ValueError:
            current = None
        if not isinstance(current, dict):
            backup = PI_SETTINGS.with_name(PI_SETTINGS.name + ".backup")
            logger.warning("%s is not a JSON object; moving it to %s", PI_SETTINGS, backup)
            shutil.move(str(PI_SETTINGS), str(backup))
            current = {}

    changed = _seed_missing_leaves(current, PI_SETTINGS_SEED)

    packages = current.get("packages")
    if not isinstance(packages, list):
        packages = []
    kept = [s for s in packages
            if isinstance(s, str) and s not in RETIRED_PI_PACKAGES and s not in wanted]
    dropped = [s for s in packages if isinstance(s, str) and s in RETIRED_PI_PACKAGES]
    # Object-form entries ({"source": …, …}) are the host's own filtering; leave them.
    objects = [s for s in packages if not isinstance(s, str)]
    reconciled = wanted + kept + objects
    if reconciled != packages:
        current["packages"] = reconciled
        changed = True
    for spec in dropped:
        logger.info("removing retired pi package %r from %s", spec, PI_SETTINGS)

    if not changed:
        logger.info("%s already carries the preset and every package", PI_SETTINGS)
        return
    PI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    PI_SETTINGS.write_text(json.dumps(current, indent=2) + "\n")
    logger.info("seeded %s: %d package(s) declared, %d preference key(s) present",
                PI_SETTINGS, len(reconciled), len(PI_SETTINGS_SEED))


def write_pi_claude_plugins(ctx):
    """Generate ``~/.pi/agent/claude-plugins.json`` from MARKETPLACES + PLUGINS.

    ``pi-claude-marketplace`` documents this file in its own source as "the
    USER-AUTHORED desired state", against a deliberately lenient schema
    (``additionalProperties: true`` at every level, every key optional). Its
    plugin key is ``<plugin>@<marketplace>`` — the same string ``Plugin.qualified``
    already produces and the same shape Claude's own ``enabledPlugins`` uses — so
    these two tables are isomorphic to this file and it is generated rather than
    hand-kept. This is what makes marketplaces and plugins a genuinely three-way
    single point instead of a two-way one.

    **Ownership split.** The repo owns this base file; the machine owns
    ``claude-plugins.local.json``, whose entries *replace* same-keyed base entries
    wholesale. The extension patches the base only on explicit mutating commands,
    at entry level, and carries its own architectural guard against serializing a
    merged view back over the base — so re-projecting here cannot stomp a
    deliberate per-machine deviation, and the extension cannot absorb the override
    layer. That is why this file is reconciled rather than add-only merged.

    Plugin versions are deliberately absent: they are a machine fact in the
    extension's own ``state.json``. Marketplace pinning would be a git ref inside
    ``source``; the bare ``owner/repo`` entries here float the default branch, the
    same trade the Claude and Codex projections already make.
    """
    data = {
        "schemaVersion": 1,
        "marketplaces": {
            m.name: {"source": m.source, "autoupdate": True}
            for m in MARKETPLACES if "pi" in m.agents
        },
        "plugins": {
            p.qualified: {"enabled": True}
            for p in PLUGINS if "pi" in p.agents
        },
    }
    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s (%d marketplace(s), %d plugin(s))",
                    PI_CLAUDE_PLUGINS, len(data["marketplaces"]), len(data["plugins"]))
        return
    PI_CLAUDE_PLUGINS.parent.mkdir(parents=True, exist_ok=True)
    PI_CLAUDE_PLUGINS.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("declared %d marketplace(s) + %d plugin(s) in %s",
                len(data["marketplaces"]), len(data["plugins"]), PI_CLAUDE_PLUGINS)


# --- the agents --------------------------------------------------------------


_AGENT_ALIASES = {"omp": "pi"}


class Agent:
    """One coding agent: how to install its CLI, and how to project the manifest
    onto it with that CLI. Self-registers by ``id`` so ``--agents=<spec>`` can
    name it."""

    _registry = {}

    id = ""
    binary = ""
    description = ""
    # $HOME-relative config dir, for the plan's wording only — this module never
    # writes an agent's own config file.
    config_dir = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.id:
            Agent._registry[cls.id] = cls

    @classmethod
    def names(cls):
        return list(cls._registry.keys())

    @classmethod
    def get(cls, agent_id):
        return cls._registry[agent_id]()

    @classmethod
    def resolve(cls, raw):
        """Resolve a comma-separated ``--agents`` spec to an ordered, de-duplicated
        id list. Accepts ids, ``all`` (every agent, the default) and ``none``
        (provision no agent at all) — the same spec shape ``--system`` uses."""
        requested = set()
        for part in raw.split(","):
            part = part.strip().lower()
            if not part or part == "none":
                continue
            # `omp` held the third slot until ADR-0012. Kept as a deprecated alias
            # so an existing invocation, script or shell alias does not break — the
            # same courtesy `--no-claude` got when `--agents` replaced it.
            if part in _AGENT_ALIASES:
                canonical = _AGENT_ALIASES[part]
                logger.warning("agent %r is a deprecated alias for %r (ADR-0012)",
                               part, canonical)
                part = canonical
            if part in ("all", "default"):
                requested.update(cls._registry.keys())
            elif part in cls._registry:
                requested.add(part)
            else:
                logger.warning("Unknown agent: %s (have: %s, all, none)",
                               part, ", ".join(cls.names()))
        return [name for name in cls._registry if name in requested]

    # -- install ------------------------------------------------------------
    def cli(self, ctx):
        found = shutil.which(self.binary)
        if found:
            return found
        # Under --dry-run nothing was actually installed, so fall back to the bare
        # name: a describe run must still print the projection commands rather
        # than silently dropping the whole step.
        return self.binary if ctx.dry_run else None

    def install(self, ctx):
        raise NotImplementedError

    # -- projection ---------------------------------------------------------
    def project(self, ctx):
        raise NotImplementedError

    def plan(self, ctx, add):
        raise NotImplementedError

    def relink(self, ctx):
        """Re-assert links that a *delegated* installer may have replaced.

        Called after codegraph, which writes into the agents' instruction files;
        an installer that appends and writes back turns a symlink into a regular
        file, so the link has to be re-established once the delegates are done.
        No-op for agents nothing else writes to."""

    # -- shared projection helpers ------------------------------------------
    def _marketplaces(self):
        return [m for m in MARKETPLACES if self.id in m.agents]

    def _plugins(self):
        return [p for p in PLUGINS if self.id in p.agents]

    def _mcp_servers(self):
        """Manifest MCP servers this agent wants *and* that we project ourselves
        (a delegated one is written by its own installer)."""
        return [s for s in MCP_SERVERS if self.id in s.agents and not s.delegated]


class ClaudeAgent(Agent):
    id = "claude"
    binary = "claude"
    description = "Claude Code"
    config_dir = "~/.claude"

    # The thin instruction shell (ADR-0011 plane ①). Claude Code does not read
    # AGENTS.md, so it imports the shared source and holds Claude-only lines —
    # and nothing else. `@~/…` is the home-anchored import form, so the shell does
    # not need a second symlink next to it.
    SHELL = HOME / ".claude" / "CLAUDE.md"
    IMPORT_LINE = "@~/.agents/AGENTS.md"
    SHELL_SEED = """\
{import_line}

# Claude-only

<!-- Claude-specific rules ONLY. Anything another agent would also want belongs
     in ~/.agents/AGENTS.md — see ADR-0011 plane ①. -->
"""
    # The single point is protected by discipline alone (ADR-0011, Consequences),
    # so do the cheap check the ADR asks for instead of trusting it: warn when the
    # shell grows past a plausible size for "an import plus a few Claude-only
    # lines".
    SHELL_MAX_LINES = 40

    def install(self, ctx):
        if shutil.which(self.binary):
            logger.info("claude CLI already installed")
            return
        logger.info("installing Claude Code CLI")
        # check=False: a vendor installer that fails must not abort the rest of
        # the post-HM phase (the old curl|bash call was non-fatal too).
        ctx.package_manager("scripts").install(
            ctx, Script("https://claude.ai/install.sh", interpreter="bash", check=False)
        )

    def project(self, ctx):
        self._instruction_shell(ctx)
        claude = self.cli(ctx)
        if not claude:
            if not ctx.dry_run:
                logger.warning("claude CLI not resolvable; skipping its projection")
            return
        for market in self._marketplaces():
            ctx.run_command([claude, "plugin", "marketplace", "add", market.source],
                            check=False, stdin_devnull=True)
        for plugin in self._plugins():
            ctx.run_command([claude, "plugin", "install", plugin.qualified, "--scope", "user"],
                            check=False, stdin_devnull=True)
        for server in self._mcp_servers():
            ctx.run_command(self._mcp_add(claude, server), check=False, stdin_devnull=True)

    @staticmethod
    def _mcp_add(claude, server):
        cmd = [claude, "mcp", "add", "--scope", "user"]
        if server.url:
            return cmd + ["--transport", "http", server.name, server.url]
        # The NAME MUST COME BEFORE -e. `claude mcp add`'s env option is variadic
        # (`-e, --env <env...>`), so a name placed after it is swallowed as one
        # more KEY=VALUE and the whole command dies with "Invalid environment
        # variable format: <name>". The CLI's own example puts it this way round:
        # `claude mcp add my-server -e API_KEY=xxx -- npx my-mcp-server`.
        #
        # Found when the (since removed) agentmemory shim carried an env — the
        # only env-carrying entry this path ever had, since codegraph is
        # delegated. No entry carries an env today, so the order matters for the
        # next one that does. Codex's _mcp_add already names the server first and
        # was never affected.
        cmd += [server.name]
        for key, value in server.env.items():
            cmd += ["-e", "{}={}".format(key, value)]
        return cmd + ["--", server.command] + server.args

    def _instruction_shell(self, ctx):
        """Make sure the shell imports the shared source, keeping whatever the
        owner already wrote. Add-only by construction: the import line is
        prepended, never a rewrite."""
        if ctx.dry_run:
            logger.info("[DRY-RUN] would ensure %s imports %s", self.SHELL, self.IMPORT_LINE)
            return
        self.SHELL.parent.mkdir(parents=True, exist_ok=True)
        if not self.SHELL.exists():
            self.SHELL.write_text(self.SHELL_SEED.format(import_line=self.IMPORT_LINE))
            logger.info("wrote the Claude instruction shell -> %s", self.SHELL)
            return
        text = self.SHELL.read_text()
        if self.IMPORT_LINE not in text:
            self.SHELL.write_text("{}\n\n{}".format(self.IMPORT_LINE, text.lstrip("\n")))
            logger.info("prepended '%s' to %s (existing content kept)",
                        self.IMPORT_LINE, self.SHELL)
            text = self.SHELL.read_text()
        lines = len(text.splitlines())
        if lines > self.SHELL_MAX_LINES:
            logger.warning(
                "%s is %d lines — review it: cross-agent rules belong in %s (ADR-0011)",
                self.SHELL, lines, SHARED_INSTRUCTIONS)

    def plan(self, ctx, add):
        if shutil.which(self.binary):
            add("install", "Claude Code CLI already present — left as is")
        else:
            add("install", "Claude Code CLI from claude.ai/install.sh")
        add("config", "{} marketplace(s) + {} plugin(s) into Claude at user scope: {}".format(
            len(self._marketplaces()), len(self._plugins()),
            ", ".join(p.qualified for p in self._plugins())))
        for server in self._mcp_servers():
            add("config", "MCP server '{}' -> claude mcp add (user scope)".format(server.name))
        if not self.SHELL.exists():
            add("config", "Claude instruction shell {} (imports {})".format(
                self.SHELL, self.IMPORT_LINE))
        elif self.IMPORT_LINE not in _read(self.SHELL):
            add("config", "prepend '{}' to the existing {} (its content is kept)".format(
                self.IMPORT_LINE, self.SHELL))


class CodexAgent(Agent):
    id = "codex"
    binary = "codex"
    description = "Codex CLI"
    config_dir = "~/.codex"

    # Codex reads a global AGENTS.md; symlinking it is the whole of its side of
    # plane ①.
    INSTRUCTIONS = HOME / ".codex" / "AGENTS.md"
    # Codex reads $HOME/.agents/skills natively (user scope), so this link is a
    # compatibility belt for the older per-agent path, not the mechanism.
    SKILLS = HOME / ".codex" / "skills"

    def install(self, ctx):
        if shutil.which(self.binary):
            logger.info("codex CLI already installed; leaving its self-update in charge")
            return
        logger.info("installing Codex CLI")
        # The official installer drops a Rust binary in ~/.local/bin (no Node
        # dependency). CODEX_NON_INTERACTIVE keeps it from asking to start Codex
        # or to remove a conflicting npm-managed install mid-bootstrap.
        ctx.package_manager("scripts").install(
            ctx,
            Script(CODEX_INSTALLER, interpreter="sh",
                   env={"CODEX_NON_INTERACTIVE": "1"}, check=False),
        )

    def project(self, ctx):
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS)
        _link(ctx, self.SKILLS, SHARED_SKILLS)
        codex = self.cli(ctx)
        if not codex:
            if not ctx.dry_run:
                logger.warning("codex CLI not resolvable; skipping its projection")
            return
        # Same manifest, Codex's own commands. `codex plugin marketplace add` takes
        # the same source shapes as Claude's (path, owner/repo[@ref], HTTPS/SSH git
        # URL), so one entry really does serve both.
        for market in self._marketplaces():
            ctx.run_command([codex, "plugin", "marketplace", "add", market.source],
                            check=False, stdin_devnull=True)
        for plugin in self._plugins():
            ctx.run_command([codex, "plugin", "add", plugin.qualified],
                            check=False, stdin_devnull=True)
        for server in self._mcp_servers():
            ctx.run_command(self._mcp_add(codex, server), check=False, stdin_devnull=True)

    def relink(self, ctx):
        # codegraph appends its usage block to ~/.codex/AGENTS.md and writes the
        # result back over the link. Absorb the block into the shared source and
        # restore the link, so plane ① survives every bootstrap rather than
        # decaying into a snapshot on the first one.
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS, absorb=True)
        _link(ctx, self.SKILLS, SHARED_SKILLS)

    @staticmethod
    def _mcp_add(codex, server):
        cmd = [codex, "mcp", "add", server.name]
        if server.url:
            return cmd + ["--url", server.url]
        for key, value in server.env.items():
            cmd += ["--env", "{}={}".format(key, value)]
        return cmd + ["--"] + [server.command] + server.args

    def plan(self, ctx, add):
        if shutil.which(self.binary):
            add("install", "Codex CLI already present — left as is")
        else:
            add("install", "Codex CLI from chatgpt.com/codex/install.sh (into ~/.local/bin)")
        add("config", "{} marketplace(s) + {} plugin(s) into Codex: {}".format(
            len(self._marketplaces()), len(self._plugins()),
            ", ".join(p.qualified for p in self._plugins())))
        for link, target in ((self.INSTRUCTIONS, SHARED_INSTRUCTIONS), (self.SKILLS, SHARED_SKILLS)):
            if _link_is_current(link, target):
                continue
            add("config", "{} -> {}".format(link, target))
            if link.exists() and not link.is_symlink():
                add("backup", "{} -> {}.backup (it is a real file/dir, not a link)".format(
                    link, link.name))
        for server in self._mcp_servers():
            add("config", "MCP server '{}' -> codex mcp add".format(server.name))


class PiAgent(Agent):
    """Upstream pi (``@earendil-works/pi-coding-agent``), the toolchain's third
    slot as of ADR-0012 — chosen over the oh-my-pi fork for interoperability, not
    for features.

    pi refuses MCP, sub-agents, memory, plan mode, permission prompts and
    background bash by design, so every capability omp had natively is an
    extension here (PI_PACKAGES). What pi has that omp does not is *presence*: the
    ACP registry, Zed, JetBrains Air, agentic.nvim, Homebrew, nixpkgs, a
    devcontainer Feature, a GitHub Action, several VS Code extensions, seven
    Neovim plugins. omp appears in none of those lists, and — measured on this
    host — its mise-installed binary cannot even be resolved by a process that is
    not an interactive zsh.

    What is projected here, and under which contract:

    - ``~/.pi/agent/AGENTS.md`` → the shared instruction source (plane ①). pi
      loads it as its global context file and concatenates ancestor AGENTS.md /
      CLAUDE.md below it.
    - ``~/.pi/agent/skills`` → the shared loose-skills dir. A **belt, not the
      mechanism**: pi implements the Agent Skills standard and reads
      ``~/.agents/skills`` natively as a global discovery location. (One caveat
      worth knowing: pi ignores root-level ``.md`` files there — only ``SKILL.md``
      directories and nested ``.md`` in grouping folders are discovered.)
    - ``~/.agents/mcp.json`` ← the manifest's MCP servers, read by
      ``pi-mcp-adapter`` at precedence layer 2 and never written back to.
    - ``~/.pi/agent/claude-plugins.json`` ← MARKETPLACES + PLUGINS, the base file
      the repo owns while the machine owns ``claude-plugins.local.json``.
    - ``~/.pi/agent/settings.json`` ← the plane-③ preset, seeded leaf by leaf,
      plus ``packages`` reconciled. **This is the one place ADR-0011's "never write
      an agent's config file" is relaxed**, on the owner's call and with the rule's
      actual protection kept: the contract is *seed*, not *own*.

    Nothing here runs ``pi install``: pi installs its own missing packages at
    startup from the seeded array.
    """

    id = "pi"
    binary = "pi"
    description = "pi coding agent"
    config_dir = "~/.pi"

    SKILLS = PI_AGENT_DIR / "skills"
    INSTRUCTIONS = PI_AGENT_DIR / "AGENTS.md"

    def install(self, ctx):
        """``npm install -g --prefix ~/.local --ignore-scripts`` (see PI_NPM_PACKAGE).

        ``~/.local/lib`` is created first: without it npm aborts with
        ``ENOENT … lstat '<prefix>/lib'`` before doing anything, which was found by
        dry-running this exact command on the reference host.
        """
        if shutil.which(self.binary):
            logger.info("pi already present (%s)", shutil.which(self.binary))
            return
        ensure_node_on_path(ctx)
        npm = _npm(ctx)
        if not npm:
            return
        if not ctx.dry_run:
            (PI_NPM_PREFIX / "lib").mkdir(parents=True, exist_ok=True)
        ctx.run_command([npm, "install", "-g", "--prefix", str(PI_NPM_PREFIX),
                         "--ignore-scripts", PI_NPM_PACKAGE],
                        check=False, stdin_devnull=True)

    def project(self, ctx):
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS)
        _link(ctx, self.SKILLS, SHARED_SKILLS)
        write_shared_mcp(ctx)
        ensure_shared_memory(ctx)
        write_pi_claude_plugins(ctx)
        seed_pi_settings(ctx)

    def relink(self, ctx):
        """Re-assert the instruction link after delegated installers have run.

        codegraph appends its usage block to an agent's instruction file and writes
        the result back over the path, which replaces the symlink with a regular
        file. pi is not one of codegraph's targets today, but it reads AGENTS.md the
        same way Codex does, so this costs one call and removes a whole class of
        future surprise.
        """
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS, absorb=True)
        _link(ctx, self.SKILLS, SHARED_SKILLS)

    def plan(self, ctx, add):
        if shutil.which(self.binary):
            add("install", "pi already present — left as is")
        else:
            add("install", "pi via npm -g --prefix {} --ignore-scripts ({}), node from "
                           "mise — the prefix puts it on home.sessionPath, which mise "
                           "shims are not".format(PI_NPM_PREFIX, PI_NPM_PACKAGE))
        add("install", "{} pi extension(s) declared in {} — pi installs any missing one "
                       "itself at startup, so nothing is `pi install`ed from here: {}".format(
                           len(PI_PACKAGES), PI_SETTINGS.name,
                           ", ".join(pkg.spec for pkg in PI_PACKAGES)))
        for link, target in ((self.INSTRUCTIONS, SHARED_INSTRUCTIONS),
                             (self.SKILLS, SHARED_SKILLS)):
            if _link_is_current(link, target):
                continue
            add("config", "{} -> {}".format(link, target))
            if link.exists() and not link.is_symlink():
                add("backup", "{} -> {}.backup (it is a real file/dir, not a link)".format(
                    link, link.name))
        pi_servers = [s.name for s in MCP_SERVERS if "pi" in s.agents]
        add("config", "{} <- MCP server(s) {} (pi-mcp-adapter reads it at precedence "
                      "layer 2 and never writes back)".format(
                          SHARED_MCP, ", ".join(pi_servers)))
        if not _shared_mcp_is_usable():
            add("backup", "{} -> {}.backup (it is not a JSON object, so it cannot be "
                          "merged into)".format(SHARED_MCP, SHARED_MCP.name))
        add("config", "{} <- the shared memory store for all three agents (cross-machine "
                      "via the ~/.agents env link; no service, credential or egress)".format(
                          SHARED_MEMORY_FILE))
        add("config", "{} <- {} marketplace(s) + {} plugin(s) from the manifest (the repo "
                      "owns this base file; the machine owns claude-plugins.local.json)".format(
                          PI_CLAUDE_PLUGINS,
                          len([m for m in MARKETPLACES if "pi" in m.agents]),
                          len([p for p in PLUGINS if "pi" in p.agents])))
        add("config", "{} <- {} preference key(s), seeded leaf-by-leaf and never "
                      "overwriting a value pi or the owner already set".format(
                          PI_SETTINGS, len(PI_SETTINGS_SEED)))



# --- orchestration -----------------------------------------------------------


def provision(ctx, ids, codegraph_installer):
    """Install every selected agent and project the manifest onto it.

    ``codegraph_installer`` is ``installers.components.install_codegraph`` —
    passed in rather than imported so this module stays independent of the
    system-component registry (codegraph is a *necessary* component there, gated
    only by the agent selection).
    """
    if not ids:
        logger.info("no agents selected; skipping the agent toolchain entirely")
        return
    logger.info("agents: %s", ", ".join(ids))
    ensure_shared_root(ctx)

    agents = [Agent.get(i) for i in ids]
    for agent in agents:
        agent.install(ctx)

    # Project BEFORE delegating to codegraph. Its installer writes usage
    # instructions into the agents' instruction files, so with the links already
    # in place its Codex write lands *through* ~/.codex/AGENTS.md in the shared
    # source — where cross-agent content belongs — instead of in a file the link
    # would then displace. On the first clean-pod run the order was the other way
    # round and codegraph's text ended up orphaned in AGENTS.md.backup.
    for agent in agents:
        agent.project(ctx)

    # codegraph installs its own MCP server into the agents it knows, which is
    # why MCP_SERVERS marks it delegated. Only the agents actually selected are
    # named, so a Claude-only run does not configure Codex behind the user's back.
    codegraph = codegraph_installer(ctx)
    targets = [i for i in ids if i in CODEGRAPH_TARGETS]
    if codegraph and targets:
        ctx.run_command([codegraph, "install", "--target=" + ",".join(targets), "--yes"],
                        check=False, stdin_devnull=True)
    elif not codegraph and not ctx.dry_run:
        logger.warning("codegraph not found after install; skipping MCP wiring")

    # codegraph writes into the agents' instruction files, so the file links it
    # replaced are restored here — after every delegate has had its turn.
    for agent in agents:
        agent.relink(ctx)


def plan_items(ctx, ids, add):
    """Describe everything ``provision`` would do, through the ADR-0010 ``add``
    callback (section, text, privileged). Read-only."""
    if not ids:
        add("install", "coding agents ({}), mise runtimes, codegraph: SKIPPED (no agent selected)"
            .format(", ".join(Agent.names())))
        return
    add("config", "shared agent root: {} (instruction source) + {} (loose skills)".format(
        SHARED_INSTRUCTIONS, SHARED_SKILLS))
    for agent in (Agent.get(i) for i in ids):
        agent.plan(ctx, add)
    if shutil.which("codegraph"):
        add("install", "CodeGraph self-update (codegraph upgrade) + its MCP server into: "
                       + ", ".join(i for i in ids if i in CODEGRAPH_TARGETS))
    else:
        add("install", "CodeGraph from raw.githubusercontent.com/colbymchenry/codegraph "
                       + "+ its MCP server into: " + ", ".join(i for i in ids if i in CODEGRAPH_TARGETS))


def main():
    """Print the manifest — the answer to "what do the agents have?"."""
    print("Agents (select with: platform/setup.py --agents <list>)")
    print("=" * 66)
    for name in Agent.names():
        agent = Agent.get(name)
        print("  {:8} {:22} config: {}".format(name, agent.description, agent.config_dir))
    print("\nMarketplaces")
    for market in MARKETPLACES:
        print("  {:18} {:44} -> {}".format(market.name, market.source, ",".join(market.agents)))
    print("\nPlugins")
    for plugin in PLUGINS:
        print("  {:36} -> {}".format(plugin.qualified, ",".join(plugin.agents)))
    print("\nMCP servers")
    for server in MCP_SERVERS:
        where = "delegated to its own installer" if server.delegated else "projected by CLI"
        print("  {:14} {:34} -> {} ({})".format(
            server.name, server.url or " ".join([server.command] + server.args),
            ",".join(server.agents), where))
    print("\npi extensions (seeded into {}; pi installs them itself at startup)".format(
        PI_SETTINGS.name))
    for pkg in PI_PACKAGES:
        print("  {}".format(pkg.spec))
    print("\nShared roots")
    print("  instructions -> {}".format(SHARED_INSTRUCTIONS))
    print("  loose skills -> {}".format(SHARED_SKILLS))
    print("  MCP (pi)     -> {}".format(SHARED_MCP))
    print("  memory       -> {} (all three agents; cross-machine via the env link)".format(
        SHARED_MEMORY_FILE))
    print("  bank archive -> {}".format(SHARED_MEMORY_ARCHIVE))


if __name__ == "__main__":
    main()
