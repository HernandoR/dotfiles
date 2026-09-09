#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/setup.py — the imperative steps that follow `chezmoi apply` (ADR-0013).

Run by chezmoi's `run_onchange_after_30-setup.sh` whenever the agent manifest,
this file or the agents/system selection changes, and by hand via `just setup`
or `uv run scripts/setup.py`. chezmoi and scripts/env_links.py already own the
files and links; this handles the remainder:

    login shell (chsh) · mise runtimes · agent toolchain (ADR-0011) · Linux system SW

Privilege is self-detected (Ctx.priv, live): privileged calls pass
`with_sudo=True`, so sudo is prepended only when non-root with a sudo binary;
root runs bare and privileged steps are skipped when there is no way to escalate.

Clearance: `build_plan()` describes every step *before* anything runs.
scripts/bootstrap.py merges it into the single full-run plan (ADR-0010). On a
standalone interactive run the plan is printed and cleared once; `--plan`
prints it (as plan rows) and exits.
"""
import argparse
import logging
import os
import pathlib
import shutil
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents  # noqa: E402
from components import OptionalComponent, install_codegraph  # noqa: E402
from context import Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
MISE_DATA = REPO_DIR / "home" / ".chezmoidata" / "mise.toml"
DEFERRED_AGENT_SETUP = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"


# --- steps -------------------------------------------------------------------------


def target_zsh():
    """The zsh the login shell should be: Homebrew's on macOS (the system one is
    older and lacks the brew site-functions), else whatever the native manager
    put on PATH."""
    if sys.platform == "darwin":
        for cand in ("/opt/homebrew/bin/zsh", "/usr/local/bin/zsh"):
            if os.access(cand, os.X_OK):
                return cand
    return shutil.which("zsh") or ""


def set_login_shell(ctx):
    """Make zsh the login shell (idempotent, non-fatal). Needs privilege."""
    zsh_path = target_zsh()
    if not zsh_path:
        logger.warning("zsh not found; leaving the login shell unchanged")
        return
    import pwd

    user = os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name
    current = pwd.getpwnam(user).pw_shell
    if current == zsh_path:
        logger.info("login shell already %s", zsh_path)
        return
    if ctx.priv == "none":
        logger.warning("no privilege: cannot chsh; run manually: chsh -s %s", zsh_path)
        return
    logger.info("setting login shell to %s", zsh_path)
    shells = pathlib.Path("/etc/shells")
    if not ctx.dry_run and shells.exists() and zsh_path not in shells.read_text().split():
        ctx.run_command(f'echo "{zsh_path}" | {ctx.sudo}tee -a /etc/shells >/dev/null', shell=True)
    if ctx.run_command(["chsh", "-s", zsh_path, user], with_sudo=True, check=False).returncode != 0:
        ctx.run_command(["usermod", "-s", zsh_path, user], with_sudo=True, check=False)


def setup_runtimes(ctx):
    """Materialize every mise-managed runtime that ~/.config/mise/config.toml
    declares (seeded from home/.chezmoidata/mise.toml by scripts/env_links.py on
    a first run; mise's own file afterwards). With the zsh `mise activate`
    integration a tool's bin only reaches PATH once it is installed, and the
    lazy auto-install fires only for interactive commands — so drive the global
    config to completion here. No privilege."""
    mise = shutil.which("mise")
    if not mise:
        logger.warning("mise not on PATH; skipping runtime install")
        return
    logger.info("installing mise runtimes (node, rust, smithery, …)")
    ctx.run_command([mise, "install", "-y"], check=False)


def setup_agents(ctx, agent_ids):
    """Install the selected coding agents and project the ADR-0011 capability
    manifest onto each with that agent's own CLI (scripts/agents.py owns both the
    manifest and the per-agent commands). Non-interactive, so it runs on every
    bootstrap; what needs a TTY goes to the deferred script below. No privilege."""
    agents.provision(ctx, agent_ids, install_codegraph)


def write_deferred_setup(ctx, agent_ids):
    """Write the interactive remainder to ~/.local/share/dotfiles/post-login-setup.sh
    instead of running it: both steps can stop and ask (an OAuth login, a
    package-manager picker), which a bootstrap must never do. The user invokes it
    once via the `dotfiles-postsetup` zsh function; it self-removes on success and
    zsh prints a one-line reminder while the file is there. No privilege."""
    deferred = DEFERRED_AGENT_SETUP
    if not agent_ids:
        logger.info("no agents selected; not writing %s", deferred)
        return
    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s", deferred)
        return
    smithery_servers = ("upstash/context7-mcp",)
    lines = [
        "#!/usr/bin/env bash",
        "# Interactive agent extras (written by scripts/setup.py). Run manually via",
        "# the `dotfiles-postsetup` shell function (needs a TTY); self-removes on",
        "# success. The Smithery CLI is a mise npm tool (installed by setup.py), so it",
        "# is called directly (no npx); only the Lark CLI still needs npx (node from mise).",
        "#",
        "# Everything that can run unattended — marketplaces, plugins, MCP servers,",
        "# the shared memory store, pi's declarative MCP/marketplace files and its",
        "# settings preset — is projected from scripts/agents.py during the bootstrap",
        "# (ADR-0011, ADR-0012) and is deliberately NOT repeated here.",
        "",
        "# Put mise-managed tools (node/npx, smithery) on PATH even when this script",
        "# is run from a shell without mise activated (e.g. a bare bash subshell).",
        'command -v mise >/dev/null 2>&1 && eval "$(mise activate bash --shims)" || true',
        "",
        "# --- Smithery MCP ----------------------------------------------------------",
        "# The namespace endpoint is per-account (its name comes from the logged-in",
        "# Smithery account, not from the repo), which is why it lives here and not in",
        "# the manifest's MCP_SERVERS.",
        "if command -v smithery >/dev/null 2>&1; then",
        '  if [ -n "${SMITHERY_API_KEY:-}" ]; then',
        r'    printf "Detected SMITHERY_API_KEY. Authenticate Smithery with this API key? [Y/n] "',
        "    read -r _ans",
        '    case "$_ans" in',
        '      [Nn]*) echo "smithery: skipping API-key auth" ;;',
        '      *) smithery auth whoami || echo "smithery: API key did not resolve" ;;',
        "    esac",
        "  else",
        r'    printf "No SMITHERY_API_KEY set. Log in to Smithery interactively now? [y/N] "',
        "    read -r _ans",
        '    case "$_ans" in',
        "      [Yy]*) smithery auth login || true ;;",
        '      *) echo "smithery: skipping login" ;;',
        "    esac",
        "  fi",
        '  _ns="$(smithery namespace show 2>/dev/null | tr -d "[:space:]")"',
        '  if [ -n "$_ns" ]; then',
        r'    printf "Add Smithery namespace \"%s\" (https://mcp.smithery.run/%s) to Claude? [Y/n] " "$_ns" "$_ns"',
        "    read -r _ans",
        '    case "$_ans" in',
        '      [Nn]*) echo "smithery: skipping namespace add" ;;',
        '      *) smithery mcp add "https://mcp.smithery.run/$_ns" --name "$_ns" --client claude || claude mcp add --transport http "$_ns" "https://mcp.smithery.run/$_ns" || true ;;',
        "    esac",
        "  fi",
        "  # Add a separate registry server here (uncomment / copy this line):",
        *[f'  # smithery mcp add "{s}" --client claude || true' for s in smithery_servers],
        "else",
        r'  echo "smithery CLI not on PATH; skipping Smithery MCP (expected pre-installed)"',
        "fi",
        "",
        "# --- Lark CLI (needs npx / node from mise) ---------------------------------",
        "# Its installer asks which agents to wire and drops the skills into",
        f"# {agents.SHARED_SKILLS} — the loose-skills root every agent reads (ADR-0011).",
        "if command -v npx >/dev/null 2>&1; then",
        "  npx -y @larksuite/cli@latest install || true",
        "else",
        r'  echo "npx missing (mise node?); skipping Lark CLI install"',
        "fi",
        "",
        'rm -f "${BASH_SOURCE[0]}"',
    ]
    deferred.parent.mkdir(parents=True, exist_ok=True)
    deferred.write_text("\n".join(lines) + "\n")
    deferred.chmod(0o755)
    logger.info("interactive agent extras (Smithery/Lark) written -> %s (run: dotfiles-postsetup)",
                deferred)


def run_system(ctx, spec):
    """Install opt-in system components. `spec` is a comma-separated string of
    names / alias groups / `all` (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    selected = [n for n in OptionalComponent.resolve(spec)
                if OptionalComponent.get(n).applicable(ctx)]
    required = [n for n in OptionalComponent.required_names()
                if OptionalComponent.get(n).applicable(ctx) and n not in selected]
    names = required + selected
    if not names:
        logger.info("no system component applies to %s from '%s' (have: %s, all)",
                    ctx.os_type, spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


# --- the plan --------------------------------------------------------------------


def mise_tools():
    """Tool names declared in home/.chezmoidata/mise.toml for this OS — the seed
    of ~/.config/mise/config.toml, so on a host that has bootstrapped before this
    is the repo's list rather than a promise about what `mise install` will do."""
    try:
        mise = tomllib.loads(MISE_DATA.read_text())["mise"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    tools = list(mise.get("tools", {}))
    if sys.platform == "linux":
        tools += list(mise.get("linux_tools", {}))
    return tools


def _login_shell_plan():
    target = target_zsh() or "zsh (not installed yet — packages.toml installs it)"
    try:
        import pwd

        user = os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name
        current = pwd.getpwnam(user).pw_shell
    except (ImportError, KeyError):
        current = ""
    return target, current


def build_plan(ctx, system_spec, agent_ids):
    """Everything this script would do, as [(section, text, privileged)] with
    section in {"install", "config", "backup"}. Pure description."""
    items = []

    def add(section, text, privileged=False):
        items.append((section, text, privileged))

    if agent_ids:
        tools = mise_tools()
        add("install", "mise runtimes from ~/.config/mise/config.toml, seeded on a first run with: "
            + (", ".join(tools) if tools else "the tools declared in home/.chezmoidata/mise.toml"))
    agents.plan_items(ctx, agent_ids, add)
    if agent_ids:
        add("config", f"interactive agent extras (Smithery/Lark) -> {DEFERRED_AGENT_SETUP} "
                      "(run later via dotfiles-postsetup)")

    if system_spec:
        if ctx.priv == "none":
            add("install", f"system components '{system_spec}': SKIPPED (no root/sudo)")
        else:
            names = [n for n in OptionalComponent.required_names()
                     if OptionalComponent.get(n).applicable(ctx)]
            names += [n for n in OptionalComponent.resolve(system_spec)
                      if n not in names and OptionalComponent.get(n).applicable(ctx)]
            if names:
                add("install", f"{len(names)} system component(s) on {ctx.os_type} (spec: {system_spec}):",
                    privileged=True)
                for n in names:
                    add("install", f"  {n} — {OptionalComponent.get(n).description}")
            else:
                add("install", f"no system component in '{system_spec}' applies to {ctx.os_type}")

    target, current = _login_shell_plan()
    if current == target:
        add("config", f"login shell already {target} — unchanged")
    elif ctx.priv == "none":
        add("config", f"login shell {current or '?'} -> {target}: SKIPPED (no root/sudo)")
    else:
        add("config", f"login shell {current or '?'} -> {target} (chsh; adds it to /etc/shells)",
            privileged=True)
    return items


def render_plan(items, ctx=None, network=None):
    out = []
    if ctx is not None:
        out.append("\033[1;34m==>\033[0m Plan — nothing has run yet")
        out.append(f"  os          {ctx.os_type}")
        out.append(f"  privilege   {ctx.priv}")
        out.append(f"  network     {network or os.environ.get('DOTFILE_NETWORK_ENV') or 'upstream (no CN mirrors)'}")
    sections = (
        ("install", "\033[1mwill install\033[0m"),
        ("config", "\033[1mwill write / link\033[0m"),
        ("backup", "\033[1;33mwill move your existing files aside (renamed, never deleted)\033[0m"),
    )
    for section, title in sections:
        rows = [(text, priv) for sec, text, priv in items if sec == section]
        if not rows:
            continue
        out.append(f"\n  {title}")
        for text, priv in rows:
            tag = "  \033[33m[privileged]\033[0m" if priv else ""
            bullet = f"      \033[2m{text.strip()}\033[0m" if text.startswith("  ") else f"    - {text}"
            out.append(f"{bullet}{tag}")
    print("\n".join(out))


def resolve_selection(args):
    """flag > env > default, identically here and in bootstrap.py."""
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""
    agent_spec = args.agents or os.environ.get("DOTFILE_AGENTS") or "all"
    if getattr(args, "no_claude", False):
        logger.warning("--no-claude is deprecated; use --agents=none")
        agent_spec = "none"
    return system_spec, agents.Agent.resolve(agent_spec)


def main():
    ap = argparse.ArgumentParser(description="Post-apply imperative setup (login shell, mise runtimes, agents, system components)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="",
                    help="comma-separated components, or 'all' / 'default' / 'none' (unset = 'default')")
    ap.add_argument("--agents", default="",
                    help="comma-separated agents to provision, or 'all' / 'none' (unset = all: "
                         + ", ".join(agents.Agent.names()) + ")")
    ap.add_argument("--no-claude", action="store_true", help="deprecated alias for --agents=none")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="skip the interactive clearance (also: DF_ASSUME_YES=1)")
    ap.add_argument("--plan", action="store_true",
                    help="print the plan as rows (section<TAB>text[<TAB>privileged]) and exit")
    args = ap.parse_args()

    planning = args.plan
    if planning:
        logger.setLevel(logging.ERROR)
    ctx = Ctx(dry_run=args.dry_run or planning, assume_yes=True if args.yes else None)
    system_spec, agent_ids = resolve_selection(args)

    if planning:
        for section, text, priv in build_plan(ctx, system_spec, agent_ids):
            print(f"{section}\t{text}\t{'privileged' if priv else ''}")
        return
    if not (ctx.assume_yes or ctx.dry_run) and ctx.interactive:
        render_plan(build_plan(ctx, system_spec, agent_ids), ctx=ctx)
        ctx.require_clearance()

    logger.info("setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)
    set_login_shell(ctx)
    if agent_ids:
        setup_runtimes(ctx)
        setup_agents(ctx, agent_ids)
        write_deferred_setup(ctx, agent_ids)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("setup complete.")


if __name__ == "__main__":
    main()
