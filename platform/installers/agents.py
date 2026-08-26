"""The multi-agent capability manifest and its per-agent projection (ADR-0011).

Three coding agents are provisioned from this one file: **Claude Code**, **Codex
CLI** and **omp** (oh-my-pi, the pi fork). ADR-0011 partitions their configuration
into three planes and
treats each differently — this module implements ① and ②, and deliberately never
touches ③:

- **① instruction — single-sourced.** ``~/.agents/AGENTS.md`` is the only
  instruction source. ``~/.codex/AGENTS.md`` symlinks to it; ``~/.claude/CLAUDE.md``
  is a thin shell that imports it (Claude Code does not read ``AGENTS.md``).
  Standing rule: nothing cross-agent may be written into the Claude shell.
- **② capability — one manifest, projected by each agent's own CLI.** The
  ``MARKETPLACES`` / ``PLUGINS`` / ``MCP_SERVERS`` tables below
  are the single reviewed source for what the agents *have*; they are applied with
  ``claude plugin install``, ``claude mcp add``, ``codex mcp add``, and — for
  omp, which is a first-class MCP client — an add-only merge into
  ``~/.omp/agent/mcp.json``. Letting each tool write its own file is what keeps
  this projection from fighting the runtime writes below.
- **③ preference — not unified.** Model, theme, approval policy and sandbox stay
  per-agent and are never written from here. All three agents rewrite their own
  config at runtime (Claude ``/model``+``/config``, Codex ``/model``,
  omp ``/settings``), which is also why none of these files can be a Home Manager
  store link (ADR-0009 Tier A is excluded by construction, not by preference).

**Projection is add-only** (ADR-0011, Consequences): deleting an entry here does
not uninstall it from a machine that already applied it. Converging would need a
recorded previously-applied set plus correct uninstall paths — declined for now.

Two premises of the ADR were falsified after it was written, and the owner chose
to act on both (ADR-0011 update log, 2026-08-05):

- **Codex has a plugin marketplace** (`codex plugin marketplace add <SOURCE>` /
  `codex plugin add PLUGIN@MARKETPLACE`, verified on the machine), so the ADR's
  accepted "Codex cannot see ``agent-skillset``" gap is closed: marketplace and
  plugin entries target Codex too. The dual-track skills decision itself is
  unchanged — marketplaces stay marketplace-managed, loose skills stay in
  ``~/.agents/skills`` — it is only the *reach* of the marketplace track that grew.
- **omp replaced pi in the third slot, on the owner's call (2026-08-06; ADR-0011
  update log).** omp is pi's fork with MCP, sub-agents, a browser tool and
  Claude-plugin skills discovery built in, so the whole pi extension set
  (``pi-claude-marketplace`` / ``pi-mcp-adapter`` / ``pi-tinyfish`` /
  ``pi-subagents``) retired: the projection shrank to the shared-source links and
  an MCP merge into ``~/.omp/agent/mcp.json``. omp's *binary* is mise-managed
  from ``github:can1357/oh-my-pi`` (home/mise.nix) — but its *config* is not:
  ``~/.omp`` is an ADR-0009 Tier-B out-of-store staging link and everything
  inside it is either projected from here or written by omp itself. It reads a
  user-level ``AGENTS.md`` from its agent dir natively (priority 100), so
  ``~/.omp/agent/AGENTS.md`` links to the shared source like Codex's.
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
# omp's user-level MCP config. omp is a first-class MCP client and reads this
# file natively (native provider, user scope) — the pi-mcp-adapter that used to
# stand between the manifest and pi's MCP is gone with pi. OMP itself rewrites
# this file via its `/mcp` slash commands, so the projection here is an add-only
# merge (see write_omp_mcp).
OMP_MCP = HOME / ".omp" / "agent" / "mcp.json"
OMP_MCP_SCHEMA = ("https://raw.githubusercontent.com/can1357/oh-my-pi/main/"
                  "packages/coding-agent/src/config/mcp-schema.json")

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
        """The server as the standard ``mcpServers`` JSON block (what
        OMP_MCP holds, and the shape every MCP host but Codex uses)."""
        if self.url:
            return {"url": self.url}
        block = {"command": self.command, "args": self.args}
        if self.env:
            block["env"] = self.env
        return block


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
BOTH_MARKETS = ("claude", "codex")

MARKETPLACES = (
    Marketplace("agent-skillset", "hernandor/agent-skillset", agents=BOTH_MARKETS,
                note="the owner's own skills: discuss / implement / dev-loop / fetch-external-knowledge"),
    Marketplace("astral-sh", "astral-sh/claude-code-plugins", agents=BOTH_MARKETS,
                note="Astral's Python tooling skills (uv / ruff / ty)"),
    Marketplace("worktrunk", "max-sixty/worktrunk", agents=BOTH_MARKETS,
                note="worktrunk (`wt`) worktree workflow — the CLI itself is a mise tool"),
    Marketplace("composio", "https://github.com/ComposioHQ/composio-plugin-cc.git",
                agents=BOTH_MARKETS,
                note="Composio tool bridge; a git URL rather than a GitHub shorthand"),
)

# Plugins, one per marketplace entry that has one. `agent-skillset` ships four
# separate plugins and there is still no bulk-install command.
PLUGINS = (
    Plugin("discuss", "agent-skillset", agents=BOTH_MARKETS),
    Plugin("implement", "agent-skillset", agents=BOTH_MARKETS),
    Plugin("dev-loop", "agent-skillset", agents=BOTH_MARKETS,
           note="its hooks are the only non-skill content in agent-skillset; Codex has a "
                "hook engine, omp surfaces the skills through its Claude-plugin "
                "discovery and hook support is best-effort"),
    Plugin("fetch-external-knowledge", "agent-skillset", agents=BOTH_MARKETS),
    Plugin("astral", "astral-sh", agents=BOTH_MARKETS),
    Plugin("worktrunk", "worktrunk", agents=BOTH_MARKETS),
    Plugin("composio", "composio", agents=BOTH_MARKETS),
)

# MCP servers. `agents` is the single point ADR-0011 promises: one entry reaches
# Claude via `claude mcp add`, Codex via `codex mcp add`, and omp via OMP_MCP
# (it is a first-class MCP client, so no adapter is needed).
MCP_SERVERS = (
    McpServer(
        "codegraph", agents=("claude", "codex", "omp"),
        command="codegraph", args=["serve", "--mcp"], delegated=True,
        note="code-intelligence graph; `codegraph install` wires Claude + Codex itself "
             "(and writes Claude's auto-allow list), so only omp is projected from here",
    ),
    # The Smithery *namespace* endpoint (https://mcp.smithery.run/<namespace>) is
    # deliberately NOT here: its name comes from the logged-in Smithery account,
    # not from the repo, so it stays in the deferred interactive setup that can
    # ask `smithery namespace show`.
)

# --- omp capability surface (the retired pi extension set) -------------------
# omp supersedes every pi package natively, so there is no package tuple to
# project (ADR-0011 update log, 2026-08-06):
#
# - pi-claude-marketplace  -> omp's `claude` / `claude-plugins` discovery
#                             providers read installed Claude marketplaces and
#                             plugins for skills, slash commands and MCP servers.
# - pi-mcp-adapter         -> omp is a first-class MCP client; the manifest's
#                             servers land in ~/.omp/agent/mcp.json (OMP_MCP).
# - pi-tinyfish            -> omp ships a native browser tool (no provider
#                             credential, which was the original rationale for
#                             choosing tinyfish over a keyed search extension).
# - pi-subagents           -> omp has native sub-agents/custom agents
#                             (~/.omp/agent/agents/ and .omp/agents/).
#
# If a capability is genuinely missing later, add it here as an `omp install
# <npm-spec>` extension (omp preserves pi's extension API), not as a per-machine
# command.

# --- install channels --------------------------------------------------------
# claude and codex use their official installers (ADR-0011, "Install channels"):
# versions stay outside git so each tool's self-update keeps working. omp is the
# mise-managed exception: the owner chose `mise use -g
# github:can1357/oh-my-pi` because compiling the Nix source build takes too long.
# Binary installation is mutable with mise, while config remains outside Home
# Manager — see OmpAgent.
CODEX_INSTALLER = "https://chatgpt.com/codex/install.sh"
# omp's memory backend, and the setting key it lives under. omp carries a local
# long-term memory store natively (mnemopi: bundled SQLite under omp's agent
# memories dir, no daemon and no port), which is what replaced the agentmemory
# daemon + MCP shim (ADR-0011 update log, 2026-08-20). It is projected the way
# every other capability is — through the agent's own CLI — because
# ~/.omp/agent/config.yml is rewritten by omp at runtime and may never be
# HM-managed or patched from here.
OMP_MEMORY_BACKEND = "mnemopi"
OMP_MEMORY_KEY = "memory.backend"
# Agent ids that `codegraph install --target` accepts (a bad id makes it print the
# list). omp is not one of them — it gets codegraph through OMP_MCP instead.
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


def _omp_mcp_is_usable():
    """Read-only: can ``write_omp_mcp`` merge into the existing file, or would
    it have to move it aside? The plan has to say so before anything runs."""
    if not OMP_MCP.exists():
        return True
    try:
        return isinstance(json.loads(OMP_MCP.read_text()), dict)
    except (OSError, ValueError):
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


def write_omp_mcp(ctx):
    """Project every ``omp``-targeting MCP server into ``~/.omp/agent/mcp.json``.

    omp is a first-class MCP client and reads this file natively (native
    provider, user scope), so no adapter stands between the manifest and omp —
    the pi-mcp-adapter bridge retired with pi. omp itself rewrites this file via
    its ``/mcp`` slash commands (its config writer adds the ``$schema``), which
    is exactly why the projection is an add-only merge: declared servers are
    updated, everything else omp (or the owner) added is kept, and an unparseable
    file is moved aside (``.backup``) rather than discarded. Servers we do not
    declare are preserved — this stays add-only, like the rest of the projection.
    """
    wanted = {s.name: s.block() for s in MCP_SERVERS if "omp" in s.agents}
    if ctx.dry_run:
        logger.info("[DRY-RUN] would declare %s in %s", ", ".join(wanted) or "nothing", OMP_MCP)
        return
    data = {}
    if OMP_MCP.exists():
        try:
            data = json.loads(OMP_MCP.read_text())
        except ValueError:
            data = None
        if not isinstance(data, dict):
            # Unparseable or the wrong shape. Move it aside rather than discard it
            # — it is not ours to delete, and .backup is the one backup suffix a
            # bootstrap uses (ADR-0009).
            backup = OMP_MCP.with_name(OMP_MCP.name + ".backup")
            logger.warning("%s is not a JSON object; moving it to %s", OMP_MCP, backup)
            shutil.move(str(OMP_MCP), str(backup))
            data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers.update(wanted)
    data["mcpServers"] = servers
    data.setdefault("$schema", OMP_MCP_SCHEMA)
    OMP_MCP.parent.mkdir(parents=True, exist_ok=True)
    OMP_MCP.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("declared %s in %s", ", ".join(sorted(wanted)), OMP_MCP)


# --- the agents --------------------------------------------------------------


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


class OmpAgent(Agent):
    """oh-my-pi (``omp``, can1357/oh-my-pi) — the pi fork that took pi's place
    in the ADR-0011 toolchain (update log, 2026-08-06). Its *binary* comes from
    mise's ``github:can1357/oh-my-pi`` tool (home/mise.nix) before setup.py runs,
    so the
    "install" step only checks reachability. Its *config* is deliberately NOT
    Home-Manager-managed: ``~/.omp`` is an ADR-0009 Tier-B out-of-store staging
    link (home/env-links.nix), plugins go through omp's own interface, and
    nothing here generates a config file for omp.

    omp supersedes the whole retired pi extension set natively (see the comment
    above MCP_SERVERS), so the projection here is the two shared-source links,
    the OMP_MCP merge, and one setting:

    - ``~/.omp/agent/AGENTS.md`` is omp's native user-level context file
      (native provider, priority 100), so it links to the shared instruction
      source like Codex's.
    - ``~/.omp/agent/skills`` is omp's native user skills dir (same priority);
      omp also reads ``~/.agents/skills`` directly through its ``agents``
      discovery provider, so the link is a belt, not the mechanism.
    - MCP servers land in ``~/.omp/agent/mcp.json``, which omp reads natively
      (and rewrites itself via ``/mcp`` — hence the add-only merge).
    - ``memory.backend = mnemopi`` turns on omp's own local memory store, set
      with ``omp config set`` (see ``set_memory_backend``). This is the memory
      plane for the whole toolchain since agentmemory was removed: one bundled
      SQLite store inside ``~/.omp``, no daemon and no port to keep alive.
    """

    id = "omp"
    binary = "omp"
    description = "oh-my-pi (omp)"
    config_dir = "~/.omp"

    # omp's native user-level paths. Its settings live in ~/.omp/agent/config.yml
    # (rewritten by /settings and the config writer) — never managed from here.
    SKILLS = HOME / ".omp" / "agent" / "skills"
    INSTRUCTIONS = HOME / ".omp" / "agent" / "AGENTS.md"

    def install(self, ctx):
        # setup_runtimes materializes the mise seed before agent projection;
        # `_mise_which` resolves it even though mise's shell shims are not on
        # this process' PATH.
        found = self._bin(ctx)
        if found:
            logger.info("omp already available from mise (%s)", found)
            return
        if ctx.dry_run:
            logger.info("[DRY-RUN] would rely on mise having installed "
                        "github:can1357/oh-my-pi from home/mise.nix")
            return
        logger.warning("omp not resolvable — did mise install "
                       "github:can1357/oh-my-pi run after the HM switch?")

    def project(self, ctx):
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS)
        _link(ctx, self.SKILLS, SHARED_SKILLS)
        write_omp_mcp(ctx)
        self.set_memory_backend(ctx)
        # No extension packages: omp covers the retired pi extension set natively
        # (MCP client, sub-agents, browser, Claude-plugin skills discovery).

    def _bin(self, ctx):
        """omp's binary, PATH first and then mise (whose shims are shell-only)."""
        return shutil.which(self.binary) or _mise_which(ctx, self.binary)

    @staticmethod
    def _memory_backend(omp):
        """omp's configured ``memory.backend``, as omp itself reports it.

        Deliberately NOT through ``ctx.run_command``: this is a read, and the
        ADR-0010 plan runs with ``dry_run`` set, where ``run_command`` returns an
        empty result without executing. Routing it through there would make the
        plan announce a change on a machine that already has the setting.
        """
        try:
            out = subprocess.run([omp, "config", "get", OMP_MEMORY_KEY],
                                 capture_output=True, stdin=subprocess.DEVNULL)
        except OSError:
            return ""
        return _stdout(out)

    def set_memory_backend(self, ctx):
        """Turn on omp's native memory store (``memory.backend = mnemopi``).

        The config-plane rule holds: omp rewrites ~/.omp/agent/config.yml itself,
        so this goes through ``omp config set`` and never through a file this
        layer writes. Re-asserted on every bootstrap like every other projected
        capability, and a no-op once the value is already there.
        """
        omp = self._bin(ctx)
        if not omp:
            logger.warning("omp not resolvable; memory backend not set (would be %s)",
                           OMP_MEMORY_BACKEND)
            return
        if self._memory_backend(omp) == OMP_MEMORY_BACKEND:
            logger.info("omp memory backend already %s", OMP_MEMORY_BACKEND)
            return
        ctx.run_command([omp, "config", "set", OMP_MEMORY_KEY, OMP_MEMORY_BACKEND],
                        check=False, stdin_devnull=True)

    def plan(self, ctx, add):
        omp_bin = self._bin(ctx)
        if omp_bin:
            add("install", "omp (oh-my-pi) already available from mise — left as is")
        else:
            add("install", "omp (oh-my-pi) via mise — github:can1357/oh-my-pi "
                           "(compiling the Nix source build takes too long; config not "
                           "HM-managed)")
        if omp_bin and self._memory_backend(omp_bin) == OMP_MEMORY_BACKEND:
            add("config", "omp memory backend already {} — left as is".format(
                OMP_MEMORY_BACKEND))
        else:
            add("config", "omp {} -> {} via `omp config set` — the toolchain's memory "
                          "plane (bundled local SQLite in ~/.omp; no daemon, no port)"
                .format(OMP_MEMORY_KEY, OMP_MEMORY_BACKEND))
        add("config", "no omp extension packages projected — native MCP client, native "
                      "sub-agents, native browser, and Claude-plugin skills discovery "
                      "cover the retired pi extension set")
        for link, target in ((self.INSTRUCTIONS, SHARED_INSTRUCTIONS), (self.SKILLS, SHARED_SKILLS)):
            if _link_is_current(link, target):
                continue
            add("config", "{} -> {}".format(link, target))
            if link.exists() and not link.is_symlink():
                add("backup", "{} -> {}.backup (it is a real file/dir, not a link)".format(
                    link, link.name))
        omp_servers = [s.name for s in MCP_SERVERS if "omp" in s.agents]
        add("config", "{} <- MCP server(s) {} (omp reads it natively)".format(
            OMP_MCP, ", ".join(omp_servers)))
        if not _omp_mcp_is_usable():
            add("backup", "{} -> {}.backup (it is not a JSON object, so it cannot be "
                          "merged into)".format(OMP_MCP, OMP_MCP.name))


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
    print("\nomp (oh-my-pi)")
    print("  extension packages: none projected — native MCP client, native sub-agents,")
    print("  native browser, and Claude-plugin skills discovery cover the retired pi set")
    print("  MCP servers -> {} (read natively; omp rewrites it via /mcp)".format(OMP_MCP))
    print("  memory: {} = {} (native local SQLite; set with `omp config set`)".format(
        OMP_MEMORY_KEY, OMP_MEMORY_BACKEND))


if __name__ == "__main__":
    main()
