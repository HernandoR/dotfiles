"""The multi-agent capability manifest and its per-agent projection (ADR-0011).

Three coding agents are provisioned from this one file: **Claude Code**, **Codex
CLI** and **pi**. ADR-0011 partitions their configuration into three planes and
treats each differently — this module implements ① and ②, and deliberately never
touches ③:

- **① instruction — single-sourced.** ``~/.agents/AGENTS.md`` is the only
  instruction source. ``~/.codex/AGENTS.md`` symlinks to it; ``~/.claude/CLAUDE.md``
  is a thin shell that imports it (Claude Code does not read ``AGENTS.md``).
  Standing rule: nothing cross-agent may be written into the Claude shell.
- **② capability — one manifest, projected by each agent's own CLI.** The
  ``MARKETPLACES`` / ``PLUGINS`` / ``MCP_SERVERS`` / ``PI_PACKAGES`` tables below
  are the single reviewed source for what the agents *have*; they are applied with
  ``claude plugin install``, ``claude mcp add``, ``codex mcp add``, ``pi install``.
  Letting each tool write its own file is what keeps this projection from fighting
  the runtime writes below.
- **③ preference — not unified.** Model, theme, approval policy and sandbox stay
  per-agent and are never written from here. All three agents rewrite their own
  config at runtime (Claude ``/model``+``/config``, Codex ``/model``,
  pi ``/settings``), which is also why none of these files can be a Home Manager
  store link (ADR-0009 Tier A is excluded by construction, not by preference).

**Projection is add-only** (ADR-0011, Consequences): deleting an entry here does
not uninstall it from a machine that already applied it. Converging would need a
recorded previously-applied set plus correct uninstall paths — declined for now.

Two findings that post-date the ADR and are recorded rather than acted on:

- Codex CLI *does* have a plugin marketplace now (``codex plugin marketplace
  add``, shipped 2026-03-26), so the ADR's accepted "Codex cannot see
  ``agent-skillset``" gap is closable by adding ``"codex"`` to a marketplace
  entry's ``agents``. That is an ADR-level trade, so no Codex marketplace
  projection is implemented here.
- pi *does* read a global context file (``AGENTS.md`` under its agent dir), where
  the ADR recorded that it abstains from the instruction plane. Linking it would
  be one more entry in ``PiAgent.project``; also left for an ADR revisit.
"""

import json
import logging
import os
import pathlib
import shutil
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
# Tool-agnostic MCP config. Read by pi through `pi-mcp-adapter` (precedence 2 of
# its 6 sources); see PiAgent.project for why this file, and not pi's own config,
# is where pi's half of MCP_SERVERS lands.
SHARED_MCP = AGENTS_DIR / "mcp.json"

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
        SHARED_MCP holds, and the shape every MCP host but Codex uses)."""
        if self.url:
            return {"url": self.url}
        block = {"command": self.command, "args": self.args}
        if self.env:
            block["env"] = self.env
        return block


class PiPackage:
    """A pi package (``pi install <spec>``); recorded by pi into its own
    settings.json, which is exactly why it is projected by command."""

    def __init__(self, spec, note=""):
        self.spec = spec
        self.note = note


# Marketplaces: Claude-only, and all four that the reference host actually has.
# `worktrunk` and `composio` were installed by hand and existed nowhere in the
# repo — closing that drift is the whole reason ADR-0011 supersedes ADR-0005, so
# do not remove them because they look unfamiliar.
MARKETPLACES = (
    Marketplace("agent-skillset", "hernandor/agent-skillset",
                note="the owner's own skills: discuss / implement / dev_loop / fetch_external_knowledge"),
    Marketplace("astral-sh", "astral-sh/claude-code-plugins",
                note="Astral's Python tooling skills (uv / ruff / ty)"),
    Marketplace("worktrunk", "max-sixty/worktrunk",
                note="worktrunk (`wt`) worktree workflow — the CLI itself is a mise tool"),
    Marketplace("composio", "https://github.com/ComposioHQ/composio-plugin-cc.git",
                note="Composio tool bridge; a git URL rather than a GitHub shorthand"),
)

# Plugins, one per marketplace entry that has one. `agent-skillset` ships four
# separate plugins and there is still no bulk-install command.
PLUGINS = (
    Plugin("discuss", "agent-skillset"),
    Plugin("implement", "agent-skillset"),
    Plugin("dev_loop", "agent-skillset"),
    Plugin("fetch_external_knowledge", "agent-skillset"),
    Plugin("astral", "astral-sh"),
    Plugin("worktrunk", "worktrunk"),
    Plugin("composio", "composio"),
)

# MCP servers. `agents` is the single point ADR-0011 promises: one entry reaches
# Claude via `claude mcp add`, Codex via `codex mcp add`, and pi via SHARED_MCP
# (which is what makes pi-mcp-adapter worth installing).
MCP_SERVERS = (
    McpServer(
        "codegraph", agents=("claude", "codex", "pi"),
        command="codegraph", args=["serve", "--mcp"], delegated=True,
        note="code-intelligence graph; `codegraph install` wires Claude + Codex itself "
             "(and writes Claude's auto-allow list), so only pi is projected from here",
    ),
    McpServer(
        "agentmemory", agents=("codex", "pi"),
        command="npx", args=["-y", "@agentmemory/mcp"],
        env={"AGENTMEMORY_URL": "http://localhost:3111"},
        note="ADR-0011 wires the memory backend to pi + Codex ONLY — Claude keeps its "
             "built-in file memory until this backend proves itself in real use. The shim "
             "exposes the full tool surface only when it can reach the local daemon, hence "
             "the explicit URL (the daemon is home/agentmemory.nix)",
    ),
    # The Smithery *namespace* endpoint (https://mcp.smithery.run/<namespace>) is
    # deliberately NOT here: its name comes from the logged-in Smithery account,
    # not from the repo, so it stays in the deferred interactive setup that can
    # ask `smithery namespace show`.
)

# pi extensions. pi has no marketplaces and no MCP of its own, so its whole
# capability surface is packages (ADR-0011, "pi extension set").
PI_PACKAGES = (
    PiPackage("npm:pi-claude-marketplace",
              note="skills bridge: lets pi read the Claude marketplaces above. dev_loop's "
                   "hooks fall under its documented partial hook support and are expected "
                   "to degrade — not a defect to chase"),
    PiPackage("npm:pi-mcp-adapter",
              note="MCP for pi; without it pi would be the one agent unable to reach any "
                   "declared MCP server, and MCP_SERVERS would not be a three-way single "
                   "point. Reads SHARED_MCP"),
    PiPackage("npm:pi-tinyfish",
              note="web search — chosen over pi-websearch to avoid a provider credential "
                   "on intranet hosts"),
    PiPackage("npm:pi-subagents",
              note="sub-agent delegation, pi's equivalent of Claude's native agents"),
)

# --- install channels --------------------------------------------------------
# All three CLIs use their official installers (ADR-0011, "Install channels"):
# versions stay outside git so each tool's self-update keeps working, and
# home/mise.nix is untouched. This is the deliberate inverse of the mise-managed
# choice made for larksuite/smithery.
CODEX_INSTALLER = "https://chatgpt.com/codex/install.sh"
PI_NPM_PACKAGE = "@earendil-works/pi-coding-agent"
AGENTMEMORY_NPM_PACKAGE = "@agentmemory/agentmemory"
# launchd label / systemd unit name of the memory daemon declared in
# home/agentmemory.nix. Home Manager owns the unit (a service file is never
# rewritten at runtime — ADR-0011's one legitimate Tier A citizen); starting it
# once the binary exists is this layer's job, because the HM switch runs first.
AGENTMEMORY_SERVICE = "agentmemory"
# Agent ids that `codegraph install --target` accepts (a bad id makes it print the
# list). pi is not one of them — it gets codegraph through SHARED_MCP instead.
CODEGRAPH_TARGETS = ("claude", "codex")


# --- small filesystem / npm helpers -----------------------------------------


def _read(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def _npm(ctx):
    """The npm from the mise-managed node runtime (materialized by
    ``setup_runtimes`` just before this module runs), or None."""
    npm = shutil.which("npm")
    if not npm and not ctx.dry_run:
        logger.warning("npm not on PATH (mise node?); skipping the npm-installed agents")
    return npm


_NPM_GLOBAL_BIN = []  # one-slot cache: `npm prefix -g` is a node start-up per call


def _npm_global_bin(ctx):
    """``<npm global prefix>/bin`` — where ``npm install -g`` puts binaries under
    the mise node. Needed because this process installs a tool and then *uses* it
    (`pi install …`), and mise only shims the tools its own config declares."""
    if _NPM_GLOBAL_BIN:
        return _NPM_GLOBAL_BIN[0]
    npm = shutil.which("npm")
    if not npm:
        return None
    out = ctx.run_command([npm, "prefix", "-g"], capture_output=True, check=False)
    prefix = getattr(out, "stdout", b"") or b""
    if isinstance(prefix, bytes):
        prefix = prefix.decode("utf-8", "replace")
    prefix = prefix.strip()
    resolved = str(pathlib.Path(prefix) / "bin") if prefix else None
    _NPM_GLOBAL_BIN.append(resolved)
    return resolved


def _resolve_bin(ctx, name):
    """Find a freshly npm-installed binary. ``shutil.which`` first (the usual
    case), then the npm global bin dir, which is not on this process' PATH."""
    found = shutil.which(name)
    if found:
        return found
    bin_dir = _npm_global_bin(ctx)
    if bin_dir:
        candidate = pathlib.Path(bin_dir) / name
        if candidate.is_file():
            return str(candidate)
    return None


def _npm_install_global(ctx, package, binary):
    """``npm install -g <package>`` unless ``binary`` already resolves. Skipping a
    present tool is what keeps its own self-update authoritative (ADR-0011)."""
    found = _resolve_bin(ctx, binary)
    if found:
        logger.info("%s already installed (%s); leaving its self-update in charge", binary, found)
        return found
    npm = _npm(ctx)
    if not npm:
        return None
    logger.info("installing %s (npm -g)", package)
    ctx.run_command([npm, "install", "-g", package], check=False, stdin_devnull=True)
    return _resolve_bin(ctx, binary)


def _link(ctx, link, target):
    """Point ``link`` at ``target``, non-destructively.

    A correct link is a no-op; a link pointing elsewhere is repointed; a *real*
    file or directory is moved to ``<name>.backup`` first — the same suffix Home
    Manager uses, so a bootstrap only ever has one backup convention (ADR-0009).
    The plan describes that move in its own highlighted section (ADR-0010).
    """
    if ctx.dry_run:
        logger.info("[DRY-RUN] would link %s -> %s", link, target)
        return
    if link.is_symlink():
        if os.readlink(str(link)) == str(target):
            return
        link.unlink()
    elif link.exists():
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


def _shared_mcp_is_usable():
    """Read-only: can ``write_shared_mcp`` merge into the existing file, or would
    it have to move it aside? The plan has to say so before anything runs."""
    if not SHARED_MCP.exists():
        return True
    try:
        return isinstance(json.loads(SHARED_MCP.read_text()), dict)
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


def write_shared_mcp(ctx):
    """Project every ``pi``-targeting MCP server into ``~/.agents/mcp.json``.

    Why a file and not a command: pi has no MCP CLI of its own, and
    ``pi-mcp-adapter``'s ``init`` only *discovers host configs* — it would import
    whatever Claude/Codex happen to have, i.e. re-import drift instead of
    projecting the manifest. This file is the adapter's documented tool-agnostic
    source, no agent ever rewrites it (the adapter persists its own overrides in
    ``~/.pi/agent/mcp.json`` and explicitly never writes back here), so writing it
    is not the config merge-patching ADR-0011 declined.

    Servers we do not declare are preserved: this stays add-only, like the rest
    of the projection.
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
            # Unparseable or the wrong shape. Move it aside rather than discard it
            # — it is not ours to delete, and .backup is the one backup suffix a
            # bootstrap uses (ADR-0009).
            backup = SHARED_MCP.with_name(SHARED_MCP.name + ".backup")
            logger.warning("%s is not a JSON object; moving it to %s", SHARED_MCP, backup)
            shutil.move(str(SHARED_MCP), str(backup))
            data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers.update(wanted)
    data["mcpServers"] = servers
    SHARED_MCP.parent.mkdir(parents=True, exist_ok=True)
    SHARED_MCP.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("declared %s in %s", ", ".join(sorted(wanted)), SHARED_MCP)


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
        found = _resolve_bin(ctx, self.binary)
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
        ctx.package_manager("scripts").install(
            ctx, Script("https://claude.ai/install.sh", interpreter="bash")
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
        for key, value in server.env.items():
            cmd += ["-e", "{}={}".format(key, value)]
        return cmd + [server.name, "--", server.command] + server.args

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
            Script(CODEX_INSTALLER, interpreter="sh", env={"CODEX_NON_INTERACTIVE": "1"}),
        )

    def project(self, ctx):
        _link(ctx, self.INSTRUCTIONS, SHARED_INSTRUCTIONS)
        _link(ctx, self.SKILLS, SHARED_SKILLS)
        codex = self.cli(ctx)
        if not codex:
            if not ctx.dry_run:
                logger.warning("codex CLI not resolvable; skipping its MCP projection")
            return
        for server in self._mcp_servers():
            ctx.run_command(self._mcp_add(codex, server), check=False, stdin_devnull=True)

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
    id = "pi"
    binary = "pi"
    description = "pi coding agent"
    config_dir = "~/.pi"

    # pi's global skills dir. Pointing it at the shared root is the same trick as
    # Codex's; the alternative — a "skills" entry in ~/.pi/agent/settings.json —
    # was declined because that file is exactly what pi rewrites at runtime
    # (/settings, and `pi install` records packages into it).
    SKILLS = HOME / ".pi" / "agent" / "skills"

    def install(self, ctx):
        # npm's default prefix (under the mise node), so `pi update --self` keeps
        # working — the breakage in earendil-works/pi#3942 is specific to custom
        # prefixes, which is what mise's own npm backend would have produced.
        _npm_install_global(ctx, PI_NPM_PACKAGE, self.binary)

    def project(self, ctx):
        _link(ctx, self.SKILLS, SHARED_SKILLS)
        write_shared_mcp(ctx)
        pi = self.cli(ctx)
        if not pi:
            if not ctx.dry_run:
                logger.warning("pi CLI not resolvable; skipping its package projection")
            return
        for package in PI_PACKAGES:
            ctx.run_command([pi, "install", package.spec], check=False, stdin_devnull=True)

    def plan(self, ctx, add):
        if shutil.which(self.binary):
            add("install", "pi already present — left as is")
        else:
            add("install", "pi via npm -g ({}), node from mise".format(PI_NPM_PACKAGE))
        add("install", "{} pi package(s): {}".format(
            len(PI_PACKAGES), ", ".join(p.spec for p in PI_PACKAGES)))
        if not _link_is_current(self.SKILLS, SHARED_SKILLS):
            add("config", "{} -> {}".format(self.SKILLS, SHARED_SKILLS))
            if self.SKILLS.exists() and not self.SKILLS.is_symlink():
                add("backup", "{} -> {}.backup (it is a real dir, not a link)".format(
                    self.SKILLS, self.SKILLS.name))
        pi_servers = [s.name for s in MCP_SERVERS if "pi" in s.agents]
        add("config", "{} <- MCP server(s) {} (read by pi-mcp-adapter)".format(
            SHARED_MCP, ", ".join(pi_servers)))
        if not _shared_mcp_is_usable():
            add("backup", "{} -> {}.backup (it is not a JSON object, so it cannot be "
                          "merged into)".format(SHARED_MCP, SHARED_MCP.name))


# --- agentmemory (a capability, not an agent) --------------------------------


def _agentmemory_wanted(ids):
    """agentmemory is wired to pi and Codex only (ADR-0011); Claude keeps its
    built-in file memory, so a Claude-only run installs nothing."""
    return bool({"codex", "pi"} & set(ids))


def install_agentmemory(ctx):
    return _npm_install_global(ctx, AGENTMEMORY_NPM_PACKAGE, "agentmemory")


def start_agentmemory(ctx):
    """Start the daemon Home Manager declared (home/agentmemory.nix).

    The unit is written during the HM switch, which runs *before* this script
    installs the binary — so on a first bootstrap the unit exists but has nothing
    to run. Kicking it here is the imperative half of that split, and is
    non-fatal: a container without a service manager simply has no daemon.
    """
    if ctx.dry_run:
        logger.info("[DRY-RUN] would start the '%s' user service (:3111)", AGENTMEMORY_SERVICE)
        return
    if ctx.os_type == "darwin":
        uid = os.getuid()
        ctx.run_command(["launchctl", "kickstart", "-k",
                         "gui/{}/{}".format(uid, AGENTMEMORY_SERVICE)], check=False)
        return
    if not shutil.which("systemctl") or not pathlib.Path("/run/systemd/system").is_dir():
        logger.warning("no systemd user session; start the memory daemon yourself: agentmemory")
        return
    unit = AGENTMEMORY_SERVICE + ".service"
    ctx.run_command(["systemctl", "--user", "daemon-reload"], check=False)
    # reset-failed first: an HM switch that landed before the binary existed may
    # have left the unit in a failed state, which `enable --now` would not clear.
    ctx.run_command(["systemctl", "--user", "reset-failed", unit], check=False)
    ctx.run_command(["systemctl", "--user", "enable", "--now", unit], check=False)


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
    if _agentmemory_wanted(ids):
        install_agentmemory(ctx)

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

    for agent in agents:
        agent.project(ctx)
    if _agentmemory_wanted(ids):
        start_agentmemory(ctx)


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
    if _agentmemory_wanted(ids):
        if shutil.which("agentmemory"):
            add("install", "agentmemory already present — left as is")
        else:
            add("install", "agentmemory via npm -g ({}) — local SQLite memory for pi + Codex"
                .format(AGENTMEMORY_NPM_PACKAGE))
        add("config", "start the '{}' user service on :3111 (unit declared by home/agentmemory.nix)"
            .format(AGENTMEMORY_SERVICE))


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
    print("\npi packages")
    for package in PI_PACKAGES:
        print("  {}".format(package.spec))


if __name__ == "__main__":
    main()
