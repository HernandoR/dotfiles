import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Importing components registers every OptionalComponent subclass at
# class-definition time, populating the registry used below. NECESSARY is the
# ordered tuple of always-run shell tooling (ADR-0004).
from installers.components import CLAUDE_MANAGED_PATHS, NECESSARY, OptionalComponent
from installers.managers import PackageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dotfiles")


def _dotfiles_staging_dir() -> Path:
    target = os.environ.get("DOTFILE_EDIT_HOME_TARGET")
    return Path(target) / "dotfiles" if target else Path.home() / "dotfiles"


SSH_DIR = ".ssh"


def _unique_backup(path: Path) -> Path:
    """A non-clobbering ``<name>.pre-dotfiles.bak`` sibling for ``path``."""
    backup = path.with_name(path.name + ".pre-dotfiles.bak")
    i = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.pre-dotfiles.bak.{i}")
        i += 1
    return backup


class DotfilesManager:
    def __init__(self, dry_run=False, verbose=False, options=None):
        self.is_root = os.geteuid() == 0
        self.os_type = self._detect_os()
        self.state = {
            "apt_updated": False,
        }
        self.dry_run = dry_run
        self.verbose = verbose
        self.options = options or {}
        if verbose:
            logger.setLevel(logging.DEBUG)

    def _detect_os(self):
        if platform.system() == "Darwin":
            return "darwin"
        elif platform.system() == "Linux":
            try:
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("ID_LIKE="):
                            return line.strip().split("=")[1].strip("\"'")
                        if line.startswith("ID=") and "debian" in line:
                            return "debian"
            except FileNotFoundError:
                pass
        return "unknown"

    def run_command(self, cmd, check=True, shell=False, capture_output=False, env=None):
        # Strip sudo when already running as root
        if self.is_root:
            if isinstance(cmd, str) and cmd.startswith("sudo "):
                cmd = cmd[5:]
                logger.debug("Running as root, stripped 'sudo' prefix")
            elif isinstance(cmd, list) and cmd and cmd[0] == "sudo":
                cmd = cmd[1:]
                logger.debug("Running as root, stripped 'sudo' element")
        # Overlay any extra vars onto the inherited environment (None = inherit).
        run_env = {**os.environ, **env} if env else None
        env_prefix = " ".join(f"{k}={v}" for k, v in env.items()) + " " if env else ""
        cmd_str = env_prefix + (cmd if isinstance(cmd, str) else " ".join(cmd))
        logger.info(f"Running: {cmd_str}")
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would run: {cmd_str}")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        try:
            return subprocess.run(
                cmd, check=check, shell=shell, capture_output=capture_output, env=run_env
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Error executing command: {e}")
            if capture_output:
                logger.error(f"Stderr: {e.stderr.decode('utf-8') if e.stderr else ''}")
                logger.error(f"Stdout: {e.stdout.decode('utf-8') if e.stdout else ''}")
            if check:
                sys.exit(1)

    def apt_update(self):
        if not self.state["apt_updated"]:
            logger.info("Updating apt cache...")
            self.run_command(["sudo", "apt", "update"])
            self.state["apt_updated"] = True
        else:
            logger.info("apt cache already updated, skipping.")

    def bootstrap_debian(self):
        logger.info("Bootstrapping Debian-based system...")
        self.apt_update()

        if (
            self.run_command(
                ["command", "-v", "curl"], shell=True, capture_output=True, check=False
            ).returncode
            != 0
        ):
            logger.info("curl not found, installing curl and dependencies...")
            self.run_command(["sudo", "apt", "-y", "remove", "libcurl4"])
            self.run_command(["sudo", "apt", "-y", "install", "curl", "xclip"])

        packages = ["git", "zsh", "rsync", "aptitude", "wget"]
        logger.info(f"Installing core packages: {', '.join(packages)}")
        self.run_command(["sudo", "apt", "-y", "install"] + packages)

    def install_homebrew(self):
        if shutil.which("brew"):
            logger.info("Homebrew is already installed.")
            return

        # Install from the BFSU mirror, non-interactively.
        logger.info("Installing Homebrew from BFSU mirror...")
        self.run_command(["sudo", "ls", ">/dev/null"], shell=True)
        self.run_command(
            [
                "git",
                "clone",
                "--depth=1",
                "https://mirrors.bfsu.edu.cn/git/homebrew/install.git",
                "brew-install",
            ]
        )
        # The run_command wrapper takes no env dict, so export the mirror vars
        # inline in the shell that runs the installer.
        install_cmd = (
            "export HOMEBREW_API_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles/api && "
            "export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles && "
            "export HOMEBREW_BREW_GIT_REMOTE=https://mirrors.bfsu.edu.cn/git/homebrew/brew.git && "
            "export NONINTERACTIVE=1 && "
            "/bin/bash brew-install/install.sh"
        )
        self.run_command(install_cmd, shell=True)
        self.run_command(["rm", "-rf", "brew-install"])

    def bootstrap_macos(self):
        logger.info("Bootstrapping macOS via Homebrew...")
        self.install_homebrew()
        if not shutil.which("curl"):
            self.run_command(["brew", "install", "curl"])
        packages = ["git", "zsh", "rsync", "rclone"]
        logger.info(f"Installing core packages: {', '.join(packages)}")
        self.run_command(["brew", "install"] + packages)

    def is_github_reachable(self):
        if self.dry_run:
            return True
        try:
            response = self.run_command(
                ["curl", "-Is", "https://raw.githubusercontent.com"],
                capture_output=True,
                check=True,
            )
            return "200" in response.stdout.decode("utf-8").split("\n")[0]
        except (subprocess.CalledProcessError, Exception):
            return False

    def stage_dotfiles(self, source_dir, dest_dir):
        logger.info(f"Staging dotfiles from {source_dir} to {dest_dir}...")
        if not self.dry_run:
            os.makedirs(dest_dir, exist_ok=True)

        rsync_opts = ["-a", "-v", "-h", "-C", "--recursive"]
        if self.verbose:
            rsync_opts.append("-P")
        if self.dry_run:
            rsync_opts.append("-n")

        # Trailing slash on source copies contents, not the directory itself.
        src = str(source_dir).rstrip("/") + "/"
        cmd = (
            ["rsync"]
            + rsync_opts
            + [
                "--exclude-from=./sources/.ex_list",
                "--no-perms",
                src,
                str(dest_dir),
            ]
        )

        self.run_command(cmd, check=True)
        logger.info("Dotfiles staged successfully!")

    def _staging_has_unlinked_items(self, staging: Path, home: Path, exclude=()) -> bool:
        """Return True if any direct child of staging is not correctly symlinked in home.

        ``exclude`` names are skipped: they are owned by a post-setup step
        (e.g. the Claude component links ``.claude`` itself) and are
        intentionally not symlinked by ``link_dotfiles``, so they must not
        count as "missing symlinks" here.
        """
        for item in staging.iterdir():
            if item.name in exclude:
                continue
            dest = home / item.name
            if not (dest.is_symlink() and dest.resolve() == item.resolve()):
                return True
        return False

    def link_dotfiles(self, source_dir, dest_dir, exclude=()):
        logger.info(f"Linking dotfiles from {source_dir} to {dest_dir}...")
        if self.dry_run:
            return

        source_dir = Path(source_dir)
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)

        for dir_path, dir_name, file_name in os.walk(source_dir, topdown=True):
            # Top-level only: drop entries a post-setup step owns (e.g. the
            # Claude component links ``.claude``/``.claude.json`` itself).
            if exclude and Path(dir_path) == source_dir:
                dir_name[:] = [d for d in dir_name if d not in exclude]
                file_name = [f for f in file_name if f not in exclude]
            for file in file_name:
                src = Path(dir_path) / file
                dest = Path(dest_dir) / src.relative_to(source_dir)
                if dest.is_symlink():
                    if dest.resolve() == src.resolve():
                        logger.debug(f"Already linked {src} to {dest}")
                        continue
                    dest.unlink()
                    logger.debug(f"Replaced wrong symlink {dest}")
                elif dest.exists():
                    logger.debug(f"Skipping real file {dest}")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(src)
                logger.debug(f"Linked {src} to {dest}")

            dirs_to_skip = []
            for dir_ in dir_name:
                src = Path(dir_path) / dir_
                dest = Path(dest_dir) / src.relative_to(source_dir)
                if dest.is_symlink():
                    if dest.resolve() == src.resolve():
                        logger.debug(f"Already linked directory {src} to {dest}")
                        dirs_to_skip.append(dir_)
                        continue
                    dest.unlink()
                    logger.debug(f"Replaced wrong directory symlink {dest}")
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.symlink_to(src)
                    logger.debug(f"Linked directory {src} to {dest}")
                    dirs_to_skip.append(dir_)
                # else: real directory — recurse into it

            for d in dirs_to_skip:
                dir_name.remove(d)

        logger.info("Dotfiles linked successfully!")

    def set_git_proxy(self):
        http_proxy = os.environ.get("http_proxy", "")
        https_proxy = os.environ.get("https_proxy", "")
        if not http_proxy and not https_proxy:
            logger.error("No proxy environment variables set. Cannot set git proxy.")
            return

        logger.info(f"Setting git proxy to {http_proxy or https_proxy}...")
        if http_proxy:
            self.run_command(["git", "config", "--global", "http.proxy", http_proxy])
            self.run_command(["git", "config", "--global", "https.proxy", http_proxy])
        elif https_proxy:
            self.run_command(["git", "config", "--global", "http.proxy", https_proxy])
            self.run_command(["git", "config", "--global", "https.proxy", https_proxy])

    def unset_git_proxy(self):
        logger.info("Unsetting git proxy...")
        self.run_command(
            ["git", "config", "--global", "--unset", "http.proxy"], check=False
        )
        self.run_command(
            ["git", "config", "--global", "--unset", "https.proxy"], check=False
        )

    def package_manager(self, manager_id):
        """Return an install backend by id, for components that reuse one."""
        return PackageManager.get(manager_id)

    def select_manager(self, installs):
        """Pick the best backend for this OS from a component's ``installs``.

        Filters to backends that support the current OS and that the component
        has a spec for, then takes the highest-priority match (native package
        managers rank above ``scripts``). Returns ``None`` if none apply.
        """
        candidates = [
            PackageManager.get(manager_id)
            for manager_id in installs
            if PackageManager.exists(manager_id)
            and PackageManager.get(manager_id).applicable(self.os_type)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda manager: manager.priority)

    def run_optional_installers(self):
        for name in self.options.get("optional_components", []):
            OptionalComponent.get(name).run(self)

    def run_necessary_components(self):
        """Install the always-run shell tooling, in strict order (ADR-0004)."""
        for component in NECESSARY:
            component().run(self)

    def migrate_dotfiles(self):
        """Stage then link the repo's dotfiles into $HOME (ADR-0001).

        Some paths are excluded from the generic symlink walk:
        ``CLAUDE_MANAGED_PATHS`` are wired by the Claude post-setup (ADR-0005);
        ``.ssh`` keys are *copied* (not symlinked) by ``deploy_ssh_keys`` so
        SSH gets real files with strict perms (ADR-0006).
        """
        link_exclude = (*CLAUDE_MANAGED_PATHS, SSH_DIR)
        staging = _dotfiles_staging_dir()
        if staging.exists() and self._staging_has_unlinked_items(
            staging, Path.home(), exclude=link_exclude
        ):
            logger.warning(
                f"Staging dir {staging} already exists but home is missing symlinks — "
                "skipping rsync to preserve staging customisations; running link step only."
            )
        else:
            self.stage_dotfiles(Path("./sources/root"), staging)
        self.link_dotfiles(staging, Path.home(), exclude=link_exclude)
        self.deploy_ssh_keys()

    def deploy_ssh_keys(self):
        """Copy SSH keys from staging into ``~/.ssh`` (ADR-0006).

        Keys are *copied*, not symlinked — SSH wants real files it owns, with
        strict perms — and are git-ignored in staging so the private material
        is never committed. Staging is authoritative; a differing pre-existing
        home key is backed up (never silently overwritten). Only ``id_*`` key
        pairs are touched: ``authorized_keys`` is owned by ``edit_home.sh`` and
        ``known_hosts`` is machine-local.
        """
        staging_ssh = _dotfiles_staging_dir() / SSH_DIR
        home_ssh = Path.home() / SSH_DIR
        if not staging_ssh.is_dir():
            return
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would copy ssh keys from {staging_ssh} to {home_ssh}")
            return

        home_ssh.mkdir(parents=True, exist_ok=True)
        home_ssh.chmod(0o700)
        for src in sorted(staging_ssh.iterdir()):
            is_pub = src.name.endswith(".pub")
            is_priv = src.name.startswith("id_") and not is_pub
            if not (is_priv or is_pub):
                continue  # not a managed key (authorized_keys, known_hosts, ...)
            dest = home_ssh / src.name
            if dest.is_symlink():
                dest.unlink()  # a prior link run may have symlinked it; we want a copy
            elif dest.exists():
                if dest.read_bytes() == src.read_bytes():
                    dest.chmod(0o600 if is_priv else 0o644)
                    continue
                backup = _unique_backup(dest)
                shutil.move(str(dest), str(backup))
                logger.info(f"Backed up existing {dest} to {backup}")
            shutil.copy2(str(src), str(dest))
            dest.chmod(0o600 if is_priv else 0o644)
            logger.info(f"Deployed ssh {'key' if is_priv else 'pubkey'}: {dest}")

    def run(self):
        logger.info("Initializing python-based dotfiles bootstrap...")
        logger.info(f"Detected OS Type: {self.os_type}")

        # Phase 1: OS prerequisites (not a component -- ADR-0003 §7).
        if self.os_type == "darwin":
            logger.info("macOS detected. Bootstrapping via Homebrew.")
            self.bootstrap_macos()
        elif self.os_type in ["debian", "ubuntu"]:
            self.bootstrap_debian()
        else:
            logger.error(f"Unknown OS: {self.os_type}")
            sys.exit(1)

        # Phase 2: necessary tools, Phase 3: dotfiles, Phase 4: optional tools.
        # Order matters: tools install before migration so the repo's rc files
        # (linked in phase 3) stay canonical (ADR-0004 §4).
        self.run_necessary_components()
        self.migrate_dotfiles()
        self.run_optional_installers()

        logger.info("Bootstrap completed successfully!")
        logger.info(
            "Shell tooling installed — open a new shell or run `exec zsh` to "
            "activate oh-my-zsh, starship, and fzf."
        )


def main():
    parser = argparse.ArgumentParser(description="Dotfiles Bootstrap Manager")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive prompts during installation",
    )

    # Optional components — comma-separated list via flag or env var.
    # The choices come straight from the component registry.
    component_choices = OptionalComponent.names() + sorted(
        OptionalComponent.alias_groups()
    )
    parser.add_argument(
        "--optional-components",
        type=str,
        default="",
        help=(
            "Comma-separated list of optional components "
            f"({', '.join(component_choices)})"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    subparsers.add_parser("set-proxy", help="Set Git proxy based on environment variables")
    subparsers.add_parser("unset-proxy", help="Unset Git proxy")

    args = parser.parse_args()

    # Resolve optional components from env var or CLI flag (CLI takes precedence).
    raw = os.environ.get("DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS", "")
    if args.optional_components:
        raw = args.optional_components

    options = {
        "interactive": args.interactive,
        "optional_components": OptionalComponent.resolve(raw),
    }

    manager = DotfilesManager(
        dry_run=args.dry_run, verbose=args.verbose, options=options
    )

    if args.command == "set-proxy":
        manager.set_git_proxy()
    elif args.command == "unset-proxy":
        manager.unset_git_proxy()
    else:
        # Default bootstrap behavior
        manager.run()


if __name__ == "__main__":
    main()
