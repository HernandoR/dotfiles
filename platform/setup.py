#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""platform/setup.py — post-Home-Manager imperative steps (ADR-0007).

Run by platform/bootstrap.sh via `uv run` *after* `home-manager switch`, when
uv/python are available on the HM profile. Home Manager already owns the user
environment; this handles the imperative remainder:

    login shell (chsh) · SSH keys (copy) · Claude post-setup · Linux system SW

Privilege is self-detected (Ctx.priv, live): privileged calls pass
`with_sudo=True` (or interpolate `ctx.sudo` in a shell pipeline), so sudo is
prepended only when non-root with a sudo binary; root runs bare and privileged
steps are skipped entirely when there is no way to escalate (`priv == none`).
"""
import argparse
import logging
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from installers.components import OptionalComponent  # noqa: E402
from installers.context import Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent


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


def deploy_ssh_keys(ctx):
    """Copy id_* keys to ~/.ssh with strict perms (ADR-0006). No privilege needed."""
    src = pathlib.Path(os.environ.get("DOTFILE_SSH_SRC", REPO_DIR / "sources/root/.ssh"))
    dest = pathlib.Path.home() / ".ssh"
    if not src.is_dir():
        logger.info("no SSH key source at %s; skipping", src)
        return
    if ctx.dry_run:
        logger.info("[DRY-RUN] would deploy SSH keys from %s to %s", src, dest)
        return
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    n = 0
    for s in sorted(src.glob("id_*")):
        mode = 0o644 if s.name.endswith(".pub") else 0o600
        d = dest / s.name
        if d.is_symlink():
            d.unlink()
        elif d.exists():
            if d.read_bytes() == s.read_bytes():
                d.chmod(mode)
                continue
            bak = d.with_name(d.name + ".pre-dotfiles.bak")
            shutil.move(str(d), str(bak))
            logger.info("backed up %s -> %s", d, bak)
        shutil.copy2(str(s), str(d))
        d.chmod(mode)
        n += 1
    logger.info("SSH keys deployed: %d", n)


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


def setup_claude(ctx):
    """Install the Claude Code CLI + write the deferred interactive setup
    (plugins/Smithery-MCP/Lark). It needs a TTY, so it is NOT auto-run; the user
    invokes it once via the `dotfiles-postsetup` shell function. The Smithery CLI
    is installed by setup_runtimes (mise npm tool), so it is called directly (no
    `npx`); only the Lark CLI still needs npx (node from mise). The HM zsh prints
    a one-line reminder while the script is still present. No privilege."""
    deferred = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"
    if shutil.which("claude"):
        logger.info("claude CLI already installed")
    else:
        logger.info("installing Claude Code CLI")
        ctx.run_command("curl -fsSL https://claude.ai/install.sh | bash", shell=True, check=False)
    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s", deferred)
        return
    plugins = ("discuss", "implement", "dev_loop", "fetch_external_knowledge")
    # Individual Smithery-registry MCP servers (qualified registry names, not npm
    # specifiers). context7 already lives in the namespace, so these are emitted
    # COMMENTED OUT — kept as a template for adding a separate server later.
    smithery_servers = ("upstash/context7-mcp",)
    lines = [
        "#!/usr/bin/env bash",
        "# Claude/Smithery/Lark setup (written by platform/setup.py). Run manually via",
        "# the `dotfiles-postsetup` shell function (needs a TTY); self-removes on",
        "# success. The Smithery CLI is a mise npm tool (installed by setup.py), so it",
        "# is called directly (no npx); only the Lark CLI still needs npx (node from mise).",
        "",
        "# Put mise-managed tools (node/npx, smithery) on PATH even when this script",
        "# is run from a shell without mise activated (e.g. a bare bash subshell).",
        'command -v mise >/dev/null 2>&1 && eval "$(mise activate bash --shims)" || true',
        "",
        "# --- Claude plugins --------------------------------------------------------",
        "claude plugin marketplace add hernandor/agent-skillset || true",
        *[f"claude plugin install {p}@agent-skillset --scope user || true" for p in plugins],
        "",
        "# --- Smithery MCP ----------------------------------------------------------",
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
    logger.info("Claude/Smithery/Lark setup written -> %s (run it with: dotfiles-postsetup)", deferred)


def run_system(ctx, spec):
    """Install opt-in Linux system components. `spec` is a comma-separated string
    of names / alias groups / the `all` keyword (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    # Each component declares its own supported_os; Component.run() skips the
    # non-applicable ones (e.g. Linux docker/cuda on macOS, macOS brew on Linux).
    names = OptionalComponent.resolve(spec)
    if not names:
        logger.info("no valid system components in '%s' (have: %s, all)", spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


def main():
    ap = argparse.ArgumentParser(description="Post-Home-Manager imperative setup")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="",
                    help="comma-separated components, or 'all' / 'default' / 'none' "
                         "(unset = the 'default' group)")
    ap.add_argument("--no-claude", action="store_true", help="skip Claude post-setup")
    args = ap.parse_args()

    ctx = Ctx(dry_run=args.dry_run)
    logger.info("post-HM setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)

    # System components: --system wins; else DOTFILE_SYSTEM_COMPONENTS; else the
    # `default` group (brew on macOS + software-properties on Linux, each gated
    # by its own supported_os). `all` = every component; `none` = skip entirely.
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""

    set_login_shell(ctx)
    deploy_ssh_keys(ctx)
    if not args.no_claude:
        setup_runtimes(ctx)
        setup_claude(ctx)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("post-HM setup complete.")


if __name__ == "__main__":
    main()
