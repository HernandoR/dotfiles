#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""platform/setup.py — post-Home-Manager imperative steps (ADR-0007).

Run by platform/bootstrap.sh via `uv run` *after* `home-manager switch`, when
uv/python are available on the HM profile. Home Manager already owns the user
environment; this handles the imperative remainder:

    login shell (chsh) · agent toolchain (ADR-0011) · Linux system SW

Privilege is self-detected (Ctx.priv, live): privileged calls pass
`with_sudo=True` (or interpolate `ctx.sudo` in a shell pipeline), so sudo is
prepended only when non-root with a sudo binary; root runs bare and privileged
steps are skipped entirely when there is no way to escalate (`priv == none`).

Clearance: `build_plan()` describes every step *before* anything runs — what is
installed, from which network, which config is written or linked. On an
interactive run the plan is printed and cleared once (`Ctx.require_clearance`);
`--plan` prints it and exits; `--plan-items` emits it as TSV for
platform/bootstrap.sh, which merges both halves into one document and asks for
the single clearance itself (then exports $DF_ASSUME_YES so this script does not
re-ask).
"""
import argparse
import logging
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from installers import agents  # noqa: E402
from installers.components import OptionalComponent, install_codegraph  # noqa: E402
from installers.context import Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")


# --- post-HM steps -----------------------------------------------------------


def set_login_shell(ctx):
    """Make the Nix zsh the login shell (idempotent, non-fatal). Needs privilege."""
    zsh = pathlib.Path.home() / ".nix-profile" / "bin" / "zsh"
    zsh_path = str(zsh) if zsh.is_file() else (shutil.which("zsh") or "")
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
    """Materialize every mise-managed runtime (node, rust, the npm-backed smithery
    CLI, …) declared in home/mise.nix.

    With the zsh `mise activate` integration a tool's bin only reaches PATH once it
    is actually installed — the "auto-install on first use" fires only for
    interactive commands, never for the non-interactive bash post-login script
    (which probes with `command -v`). So drive the global config to completion here
    (as ADR-0002 did for nvm), the way the first `mise install` would. No
    privilege."""
    mise = shutil.which("mise")
    if not mise:
        logger.warning("mise not on PATH; skipping runtime install")
        return
    logger.info("installing mise runtimes (node, rust, smithery, …)")
    ctx.run_command([mise, "install"], check=False)


def setup_agents(ctx, agent_ids):
    """Install the selected coding agents and project the ADR-0011 capability
    manifest onto each with that agent's own CLI (installers/agents.py owns both
    the manifest and the per-agent commands).

    Everything here is non-interactive, so it runs on every bootstrap: the
    manifest is only a single source if applying it needs no human. What genuinely
    needs a TTY — Smithery auth and the Lark CLI's own installer — is written to
    the deferred script below instead. No privilege."""
    agents.provision(ctx, agent_ids, install_codegraph)


def write_deferred_setup(ctx, agent_ids):
    """Write the interactive remainder to
    ``~/.local/share/dotfiles/post-login-setup.sh`` instead of running it: both
    steps below can stop and ask (an OAuth login, a package-manager picker), which
    a bootstrap must never do. The user invokes it once via the
    `dotfiles-postsetup` shell function; it self-removes on success, and the HM zsh
    prints a one-line reminder while the file is still there.

    The Smithery CLI is a mise npm tool (installed by setup_runtimes), so it is
    called directly (no `npx`); only the Lark CLI still needs npx (node from mise).
    Claude plugins/marketplaces/MCP are NOT here anymore — they are part of the
    manifest projection (ADR-0011) and run unattended. No privilege."""
    deferred = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"
    if not agent_ids:
        logger.info("no agents selected; not writing %s", deferred)
        return
    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s", deferred)
        return
    # Individual Smithery-registry MCP servers (qualified registry names, not npm
    # specifiers). context7 already lives in the namespace, so these are emitted
    # COMMENTED OUT — kept as a template for adding a separate server later.
    smithery_servers = ("upstash/context7-mcp",)
    lines = [
        "#!/usr/bin/env bash",
        "# Interactive agent extras (written by platform/setup.py). Run manually via",
        "# the `dotfiles-postsetup` shell function (needs a TTY); self-removes on",
        "# success. The Smithery CLI is a mise npm tool (installed by setup.py), so it",
        "# is called directly (no npx); only the Lark CLI still needs npx (node from mise).",
        "#",
        "# Everything that can run unattended — marketplaces, plugins, MCP servers, omp's",
        "# native MCP config — is projected from platform/installers/agents.py during bootstrap",
        "# (ADR-0011) and is deliberately NOT repeated here.",
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
        "    # (a/b) API key present -> offer API-key (Smithery auth) startup. The CLI",
        "    # reads SMITHERY_API_KEY from the environment automatically.",
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
        "  # (c) Namespace form: add the namespace's aggregated MCP endpoint to Claude.",
        '  _ns="$(smithery namespace show 2>/dev/null | tr -d "[:space:]")"',
        '  if [ -n "$_ns" ]; then',
        r'    printf "Add Smithery namespace \"%s\" (https://mcp.smithery.run/%s) to Claude? [Y/n] " "$_ns" "$_ns"',
        "    read -r _ans",
        '    case "$_ans" in',
        '      [Nn]*) echo "smithery: skipping namespace add" ;;',
        "      # Prefer the Smithery CLI (injects auth); fall back to Claude's own add.",
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
    """Install opt-in Linux system components. `spec` is a comma-separated string
    of names / alias groups / the `all` keyword (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    # Each component declares its own supported_os; Component.run() skips the
    # non-applicable ones (e.g. Linux docker/cuda on macOS, macOS brew on Linux).
    selected = OptionalComponent.resolve(spec)
    # Required components (e.g. software-properties -> add-apt-repository, a
    # prerequisite for the apt-based components) are always installed first on
    # their applicable OS, whatever the spec selected. `--system none` never
    # reaches here (main() blanks the spec), so it remains a full opt-out.
    required = [n for n in OptionalComponent.required_names()
                if OptionalComponent.get(n).applicable(ctx) and n not in selected]
    names = required + selected
    if not names:
        logger.info("no valid system components in '%s' (have: %s, all)", spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


# --- the plan (printed before anything runs; cleared once) -------------------

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFERRED_AGENT_SETUP = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"


# Nix platform predicates understood by _mise_tools, evaluated for *this* host.
_NIX_GUARDS = {
    "pkgs.stdenv.isLinux": sys.platform == "linux",
    "pkgs.stdenv.isDarwin": sys.platform == "darwin",
}


def _mise_tools():
    """Tool names declared in the ``tools = …`` expression of home/mise.nix, for
    the plan's "will install" line. Read from the nix source because mise itself
    is not on PATH until Home Manager has switched — and the plan prints before
    that. Only depth-1 keys count, so a nested entry (``"npm:@smithery/cli" = {
    version = …; }``) contributes its own name and not its attributes.

    The expression is one or more ``{ … }`` blocks joined by ``//``; a block
    guarded by ``lib.optionalAttrs <cond>`` contributes its keys only when
    ``<cond>`` holds here, so the plan matches what Home Manager will evaluate
    (e.g. docker-cli is Linux-only). An unrecognised guard counts as applying —
    over-reporting an install in a clearance plan beats hiding one. Returns []
    if the expression cannot be found; the caller then falls back to naming the
    file.
    """
    try:
        text = (REPO_DIR / "home" / "mise.nix").read_text()
    except OSError:
        return []
    start = re.search(r"\btools\s*=\s*\{", text)
    if not start:
        return []
    tools, depth, applies = [], 1, True
    for raw in text[start.end():].splitlines():
        line = re.sub(r"#.*$", "", raw).strip()
        if depth == 0:
            # Between merged blocks: `// { … }` / `// lib.optionalAttrs <cond> { … }`.
            # Anything else ends the expression.
            if not line:
                continue
            merge = re.match(r"//\s*(?:lib\.optionalAttrs\s+(\S+)\s+)?\{", line)
            if not merge:
                break
            guard = merge.group(1)
            applies = _NIX_GUARDS.get(guard, True) if guard else True
            depth = 1  # the merge line's own `{` — already accounted for here
            continue
        if depth == 1 and applies:
            key = re.match(r'"?([A-Za-z0-9:@._/-]+)"?\s*=', line)
            if key:
                tools.append(key.group(1))
        depth += line.count("{") - line.count("}")
    return tools


def _login_shell_plan():
    """(target, current) login-shell paths for the plan. The target is the Nix
    zsh whether or not it exists yet: pre-switch it does not, and reporting a
    system /bin/zsh (what shutil.which would find) would misdescribe the run."""
    target = str(pathlib.Path.home() / ".nix-profile" / "bin" / "zsh")
    try:
        import pwd

        user = os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name
        current = pwd.getpwnam(user).pw_shell
    except (ImportError, KeyError):
        current = ""
    return target, current


def build_plan(ctx, system_spec, agent_ids):
    """Everything this script would do, as ``[(section, text, privileged)]`` with
    section in {"install", "config", "backup"} — "backup" being anything that
    displaces a file the user already has. Pure description: it reads the filesystem
    and the environment but changes nothing, so it is safe to run before
    clearance (and from platform/bootstrap.sh *before* the Home Manager switch,
    via --plan-items)."""
    items = []

    def add(section, text, privileged=False):
        items.append((section, text, privileged))

    if agent_ids:
        tools = _mise_tools()
        add("install", "mise runtimes: " + (", ".join(tools) if tools else "as declared in home/mise.nix"))
    # The agent half describes itself (installers/agents.py owns the manifest, so
    # it also owns the wording) — the same reason nix-cn.sh and this script each
    # emit their own plan rows instead of one place guessing about the others.
    agents.plan_items(ctx, agent_ids, add)
    if agent_ids:
        add("config", f"interactive agent extras (Smithery/Lark) -> {DEFERRED_AGENT_SETUP} (run later via dotfiles-postsetup)")

    if system_spec:
        if ctx.priv == "none":
            add("install", f"system components '{system_spec}': SKIPPED (no root/sudo)")
        else:
            names = [n for n in OptionalComponent.required_names()
                     if OptionalComponent.get(n).applicable(ctx)]
            names += [n for n in OptionalComponent.resolve(system_spec)
                      if n not in names and OptionalComponent.get(n).applicable(ctx)]
            if names:
                add("install",
                    f"{len(names)} system component(s) on {ctx.os_type} (spec: {system_spec}):",
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
    """Print the plan as the shell half does (platform/lib.sh plan_line), so a
    standalone run of this script and a full bootstrap read the same."""
    out = []
    if ctx is not None:
        out.append("\033[1;34m==>\033[0m Plan — nothing has run yet")
        out.append(f"  os          {ctx.os_type}")
        out.append(f"  privilege   {ctx.priv}")
        out.append(f"  network     {network or os.environ.get('DOTFILE_NETWORK_ENV') or 'upstream (no CN mirrors)'}")
    sections = (
        ("install", "\033[1mwill install\033[0m"),
        ("config", "\033[1mwill write / link\033[0m"),
        # Last, and highlighted: the only part that touches data the user already
        # has (see platform/lib.sh print_plan for the shell half's ordering).
        ("backup", "\033[1;33mwill move your existing files aside (renamed, never deleted)\033[0m"),
    )
    for section, title in sections:
        rows = [(text, priv) for sec, text, priv in items if sec == section]
        if not rows:
            continue
        out.append(f"\n  {title}")
        for text, priv in rows:
            tag = "  \033[33m[privileged]\033[0m" if priv else ""
            # A leading-space item is a detail of the line above it (the system
            # components under their count) — indent it instead of re-bulleting.
            bullet = f"      \033[2m{text.strip()}\033[0m" if text.startswith("  ") else f"    - {text}"
            out.append(f"{bullet}{tag}")
    print("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description="Post-Home-Manager imperative setup")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="",
                    help="comma-separated components, or 'all' / 'default' / 'none' "
                         "(unset = the 'default' group)")
    ap.add_argument("--agents", default="",
                    help="comma-separated agents to provision, or 'all' / 'none' "
                         "(unset = all: " + ", ".join(agents.Agent.names()) + ")")
    # ADR-0011 generalised --no-claude to --agents; kept as an alias because it is
    # the documented way to opt out of this whole half, and scripts use it.
    ap.add_argument("--no-claude", action="store_true",
                    help="deprecated alias for --agents=none")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="skip the interactive clearance (also: DF_ASSUME_YES=1)")
    ap.add_argument("--plan", action="store_true",
                    help="print the plan and exit; change nothing")
    ap.add_argument("--plan-items", action="store_true",
                    help="print the plan as TSV (section<TAB>text<TAB>priv) for bootstrap.sh")
    args = ap.parse_args()

    # --plan/--plan-items describe only; keep them side-effect free by construction.
    # Their output IS the result, so demote the log stream (component resolution
    # logs at INFO) to keep stray lines out of the plan the user is reading.
    planning = args.plan or args.plan_items
    if planning:
        logger.setLevel(logging.ERROR)
    ctx = Ctx(dry_run=args.dry_run or planning, assume_yes=True if args.yes else None)

    # System components: --system wins; else DOTFILE_SYSTEM_COMPONENTS; else the
    # `default` group (brew on macOS). software-properties is `required` on
    # debian/ubuntu, so run_system always adds it (any non-none spec). `all` =
    # every component; `none` = skip entirely (required ones included).
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""

    # Agents: --agents wins; else DOTFILE_AGENTS; else all three (ADR-0011 wants a
    # fresh bootstrap to end up with the whole toolchain). `--no-claude` is the
    # deprecated way to say `none`, and `none` also skips the mise runtimes — that
    # coupling predates this ADR (the runtimes exist to give the agents node) and
    # is kept so the opt-out keeps meaning "no agent tooling at all".
    agent_spec = args.agents or os.environ.get("DOTFILE_AGENTS") or "all"
    if args.no_claude:
        logger.warning("--no-claude is deprecated; use --agents=none")
        agent_spec = "none"
    agent_ids = agents.Agent.resolve(agent_spec)

    # A standalone interactive run shows the plan and takes the one-shot clearance
    # itself. Under platform/bootstrap.sh clearance is already granted
    # ($DF_ASSUME_YES=1, exported after the merged plan was cleared), so nothing
    # is asked twice — and the plan is not even built, keeping the automated path
    # free of describe-only work.
    needs_clearance = not (ctx.assume_yes or ctx.dry_run) and ctx.interactive
    if planning or needs_clearance:
        plan = build_plan(ctx, system_spec, agent_ids)
        if args.plan_items:
            for section, text, priv in plan:
                print(f"{section}\t{text}\t{1 if priv else 0}")
            return
        render_plan(plan, ctx=ctx)
        if args.plan:
            return
        ctx.require_clearance()

    logger.info("post-HM setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)

    # Out-of-store $HOME links are Home Manager's job now (ADR-0009 Tier B,
    # home/env-links.nix), so they already exist by the time this runs.
    set_login_shell(ctx)
    if agent_ids:
        setup_runtimes(ctx)
        setup_agents(ctx, agent_ids)
        write_deferred_setup(ctx, agent_ids)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("post-HM setup complete.")


if __name__ == "__main__":
    main()
