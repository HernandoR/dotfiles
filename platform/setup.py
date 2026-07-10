#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""platform/setup.py — post-Home-Manager imperative steps (ADR-0007).

Run by platform/bootstrap.sh via `uv run` *after* `home-manager switch`, when
uv/python are available on the HM profile. Home Manager already owns the user
environment; this handles the imperative remainder:

    login shell (chsh) · SSH keys (copy) · Claude post-setup · Linux system SW

Privilege: `--priv root|sudo|none`. run_command strips sudo when already root;
steps needing privilege are skipped under `none`.
"""
import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from installers.components import OptionalComponent  # noqa: E402
from installers.managers import PackageManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent


class Ctx:
    """Execution context passed to components (the ADR-0003 `ctx`)."""

    def __init__(self, priv="sudo", dry_run=False, options=None):
        self.priv = priv  # root | sudo | none
        self.is_root = priv == "root"
        self.dry_run = dry_run
        self.options = options or {}
        self.os_type = self._detect_os()

    @staticmethod
    def _detect_os():
        if sys.platform == "darwin":
            return "darwin"
        try:
            for line in pathlib.Path("/etc/os-release").read_text().splitlines():
                if line.startswith("ID_LIKE=") and "debian" in line:
                    return "debian"
                if line.startswith("ID=") and "ubuntu" in line:
                    return "ubuntu"
                if line.startswith("ID=") and "debian" in line:
                    return "debian"
        except FileNotFoundError:
            pass
        return "unknown" if sys.platform != "linux" else "debian"

    def run_command(self, cmd, check=True, shell=False, capture_output=False, env=None):
        # Strip sudo when already root (mirrors the old DotfilesManager).
        if self.is_root:
            if isinstance(cmd, str) and cmd.startswith("sudo "):
                cmd = cmd[5:]
            elif isinstance(cmd, list) and cmd and cmd[0] == "sudo":
                cmd = cmd[1:]
        run_env = {**os.environ, **env} if env else None
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        logger.info("Running: %s", cmd_str)
        if self.dry_run:
            logger.info("[DRY-RUN] would run: %s", cmd_str)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        try:
            return subprocess.run(
                cmd, check=check, shell=shell, capture_output=capture_output, env=run_env
            )
        except subprocess.CalledProcessError as e:
            logger.error("command failed: %s", e)
            if check:
                sys.exit(1)
            return e

    def package_manager(self, manager_id):
        return PackageManager.get(manager_id)

    def select_manager(self, installs):
        candidates = [
            PackageManager.get(mid)
            for mid in installs
            if PackageManager.exists(mid) and PackageManager.get(mid).applicable(self.os_type)
        ]
        return max(candidates, key=lambda m: m.priority) if candidates else None


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
        ctx.run_command(f'echo "{zsh_path}" | sudo tee -a /etc/shells >/dev/null', shell=True)
    if ctx.run_command(["sudo", "chsh", "-s", zsh_path, user], check=False).returncode != 0:
        ctx.run_command(["sudo", "usermod", "-s", zsh_path, user], check=False)


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


def setup_claude(ctx):
    """Install the Claude Code CLI + write the deferred interactive setup
    (plugins/MCP/Lark). It needs a TTY, so it is NOT auto-run; the user invokes
    it once via the `dotfiles-postsetup` shell function (node/npx from mise). The
    HM zsh prints a one-line reminder while the script is still present. No
    privilege."""
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
    mcp = ("@upstash/context7-mcp", "@modelcontextprotocol/server-memory")
    lines = [
        "#!/usr/bin/env bash",
        "# Claude/Lark/MCP setup (written by platform/setup.py). Run manually via the",
        "# `dotfiles-postsetup` shell function; node/npx come from mise. Self-removes",
        "# on success (a missing npx leaves it in place so you can re-run later).",
        'command -v npx >/dev/null 2>&1 || { echo "npx missing (mise node?); skip"; exit 0; }',
        "claude plugin marketplace add hernandor/agent-skillset || true",
        *[f"claude plugin install {p}@agent-skillset --scope user || true" for p in plugins],
        *[f"npx -y @smithery/cli@latest install {p} --client claude || true" for p in mcp],
        "npx -y @larksuite/cli@latest install || true",
        'rm -f "${BASH_SOURCE[0]}"',
    ]
    deferred.parent.mkdir(parents=True, exist_ok=True)
    deferred.write_text("\n".join(lines) + "\n")
    deferred.chmod(0o755)
    logger.info("Claude/Lark/MCP setup written -> %s (run it with: dotfiles-postsetup)", deferred)


def run_system(ctx, spec):
    """Install opt-in Linux system components. `spec` is a comma-separated string
    of names / alias groups / the `all` keyword (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    if ctx.os_type == "darwin":
        logger.info("system components are Linux-only; skipping on macOS")
        return
    names = OptionalComponent.resolve(spec)
    if not names:
        logger.info("no valid system components in '%s' (have: %s, all)", spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


def main():
    ap = argparse.ArgumentParser(description="Post-Home-Manager imperative setup")
    ap.add_argument("--priv", choices=["root", "sudo", "none"], default="sudo")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="", help="comma-separated: docker,cuda,nvidia,llvm,... or 'all'")
    ap.add_argument("--no-claude", action="store_true", help="skip Claude post-setup")
    args = ap.parse_args()

    ctx = Ctx(priv=args.priv, dry_run=args.dry_run)
    logger.info("post-HM setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)

    # System components: --system wins; else the DOTFILE_SYSTEM_COMPONENTS env
    # var (convenient for platform injection). 'all' selects every component.
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS", "")

    set_login_shell(ctx)
    deploy_ssh_keys(ctx)
    if not args.no_claude:
        setup_claude(ctx)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("post-HM setup complete.")


if __name__ == "__main__":
    main()
