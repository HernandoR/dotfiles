import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from installers import macos

# Importing components registers every OptionalComponent subclass at
# class-definition time, populating the registry used below.
from installers.components import OptionalComponent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dotfiles")


def _dotfiles_staging_dir() -> Path:
    target = os.environ.get("DOTFILE_EDIT_HOME_TARGET")
    return Path(target) / "dotfiles" if target else Path.home() / "dotfiles"


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

    def run_command(self, cmd, check=True, shell=False, capture_output=False):
        # Strip sudo when already running as root
        if self.is_root:
            if isinstance(cmd, str) and cmd.startswith("sudo "):
                cmd = cmd[5:]
                logger.debug("Running as root, stripped 'sudo' prefix")
            elif isinstance(cmd, list) and cmd and cmd[0] == "sudo":
                cmd = cmd[1:]
                logger.debug("Running as root, stripped 'sudo' element")
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        logger.info(f"Running: {cmd_str}")
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would run: {cmd_str}")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        try:
            return subprocess.run(
                cmd, check=check, shell=shell, capture_output=capture_output
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

    def config_ohmyzsh(self, use_github=True, interactive=False):
        if not Path("./sources").is_dir():
            logger.error("Please execute this script in the dotfiles directory")
            sys.exit(1)

        output_dir = Path("./output")
        if not self.dry_run:
            output_dir.mkdir(exist_ok=True)

        github_reachable = self.is_github_reachable() if use_github else False
        logger.info(
            f"GitHub is {'reachable' if github_reachable else 'not reachable, using gitee'}"
        )

        logger.info("Updating submodules...")
        self.run_command(["git", "submodule", "init"])
        self.run_command(["git", "submodule", "update"])

        oh_my_zsh_path = Path.home() / ".oh-my-zsh" / "oh-my-zsh.sh"
        if oh_my_zsh_path.is_file():
            logger.info("oh-my-zsh is already installed")
        else:
            oh_my_zsh_dir = Path.home() / ".oh-my-zsh"
            if oh_my_zsh_dir.is_dir() and not self.dry_run:
                logger.info("Backing up existing omz dir...")
                shutil.rmtree(Path.home() / "oh-my-zsh.bkp", ignore_errors=True)
                shutil.move(str(oh_my_zsh_dir), str(Path.home() / "oh-my-zsh.bkp"))

            logger.info("Installing oh-my-zsh...")
            install_url = (
                "https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh"
                if github_reachable
                else "https://gitee.com/mirrors/oh-my-zsh/raw/master/tools/install.sh"
            )
            install_script = output_dir / "install.sh"
            self.run_command(["curl", "-fsSL", install_url, "-o", str(install_script)])
            install_args = [] if interactive else ["--unattended"]
            self.run_command(["sh", str(install_script)] + install_args)
            if not self.dry_run:
                install_script.unlink(missing_ok=True)

        logger.info("Installing antigen...")
        if not self.dry_run:
            self.run_command(
                [
                    "curl",
                    "-fsSL",
                    "https://git.io/antigen",
                    "-o",
                    str(Path.home() / "antigen.zsh"),
                ]
            )

        logger.info("Copying zsh plugins config...")
        if not self.dry_run:
            custom_plugins = Path.home() / ".oh-my-zsh" / "custom" / "plugins"

            zsh_auto_dir = custom_plugins / "zsh-autosuggestions"
            zsh_auto_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                "./sources/zsh_plugins/zsh-autosuggestions.plugin.zsh",
                str(zsh_auto_dir / "zsh-autosuggestions.plugin.zsh"),
            )

            zsh_syn_dir = custom_plugins / "zsh-syntax-highlighting"
            zsh_syn_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                "./sources/zsh_plugins/zsh-syntax-highlighting.plugin.zsh",
                str(zsh_syn_dir / "zsh-syntax-highlighting.plugin.zsh"),
            )

    def backup_dotfiles(self, source_dir, dest_dir):
        logger.info("Backing up dotfiles...")
        if not self.dry_run:
            os.makedirs(dest_dir, exist_ok=True)

        rsync_opts = ["-a", "-v", "-h", "-C", "--recursive"]
        if self.verbose:
            rsync_opts.append("-P")
        if self.dry_run:
            rsync_opts.append("-n")

        cmd = (
            ["rsync"]
            + rsync_opts
            + [
                "--files-from=./sources/.file_list",
                "--exclude-from=./sources/.ex_list",
                "--no-perms",
                str(source_dir),
                str(dest_dir),
            ]
        )

        self.run_command(cmd, check=True)
        logger.info("Dotfiles backup complete!")

    def restore_dotfiles(self, backup_dir, restore_dir):
        logger.info("Restoring dotfiles...")
        if not self.dry_run and not os.path.isdir(backup_dir):
            logger.error("Backup directory does not exist")
            sys.exit(1)

        if not self.dry_run and os.path.isdir(restore_dir):
            logger.info("Destination directory already exists, backing it up first...")
            self.backup_dotfiles(restore_dir, f"./bkp/{Path(restore_dir).name}.bkp")

        rsync_opts = ["-a", "-v", "-h", "-C", "--recursive"]
        if self.verbose:
            rsync_opts.append("-P")
        if self.dry_run:
            rsync_opts.append("-n")

        cmd = (
            ["rsync"]
            + rsync_opts
            + [
                "--files-from=./sources/.file_list",
                "--exclude-from=./sources/.ex_list",
                "--no-perms",
                str(backup_dir),
                str(restore_dir),
            ]
        )

        self.run_command(cmd, check=True)
        logger.info("Dotfiles restored successfully!")

    def link_dotfiles(self, source_dir, dest_dir):
        logger.info(f"Linking dotfiles from {source_dir} to {dest_dir}...")
        if self.dry_run:
            return

        if not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)

        for dir_path, dir_name, file_name in os.walk(source_dir):
            for file in file_name:
                src = Path(dir_path) / file
                dest = Path(dest_dir) / src.relative_to(source_dir)
                if dest.exists():
                    if dest.resolve() == src.resolve():
                        logger.debug(f"Already linked {src} to {dest}")
                        continue
                    dest.unlink()
                    logger.debug(f"Removed {dest}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(src)
                logger.debug(f"Linked {src} to {dest}")

            for dir_ in dir_name:
                src = Path(dir_path) / dir_
                dest = Path(dest_dir) / src.relative_to(source_dir)
                if not dest.exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    logger.debug(f"Created directory {dest}")

        logger.info("Dotfiles linked successfully!")

    def install_fzf(self):
        logger.info("Installing fzf...")
        fzf_bin = Path.home() / ".fzf" / "bin" / "fzf"
        if fzf_bin.is_file():
            logger.info("fzf is already installed")
            return

        fzf_dir = Path.home() / ".fzf"
        github_reachable = self.is_github_reachable()
        fzf_url = (
            "https://github.com/junegunn/fzf.git"
            if github_reachable
            else "https://gitee.com/mirrors/fzf.git"
        )
        self.run_command(["git", "clone", "--depth", "1", fzf_url, str(fzf_dir)])
        self.run_command([str(fzf_dir / "install"), "--all", "--no-update-rc"])

    def install_starship(self, interactive=False):
        logger.info("Installing Starship prompt...")
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self.run_command(
                ["curl", "-fsSL", "https://starship.rs/install.sh", "-o", str(tmp_path)]
            )
            flags = [] if interactive else ["-y"]
            self.run_command(["sh", str(tmp_path)] + flags)
        finally:
            tmp_path.unlink(missing_ok=True)

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

    def run_optional_installers(self):
        for name in self.options.get("optional_components", []):
            OptionalComponent.get(name).run(self)

    def run_legacy_scripts(self):
        interactive = self.options.get("interactive", False)
        self.config_ohmyzsh(interactive=interactive)
        self.install_fzf()

        self.install_starship(interactive=interactive)

        staging = _dotfiles_staging_dir()
        self.restore_dotfiles(Path("./sources/root"), staging)
        self.link_dotfiles(staging, Path.home())

    def run(self):
        logger.info("Initializing python-based dotfiles bootstrap...")
        logger.info(f"Detected OS Type: {self.os_type}")

        if self.os_type == "darwin":
            logger.info("macOS detected. Bootstrapping via Homebrew.")
            macos.bootstrap_macos(self.run_command)
        elif self.os_type in ["debian", "ubuntu"]:
            self.bootstrap_debian()
        else:
            logger.error(f"Unknown OS: {self.os_type}")
            sys.exit(1)

        self.run_legacy_scripts()
        self.run_optional_installers()
        logger.info("Bootstrap completed successfully!")


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

    # Optional direct commands for just backup or restore or proxy
    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    # backup
    parser_bkp = subparsers.add_parser("backup", help="Backup dotfiles")

    # restore
    parser_res = subparsers.add_parser("restore", help="Restore dotfiles")

    # proxy
    parser_proxy = subparsers.add_parser(
        "set-proxy", help="Set Git proxy based on environment variables"
    )
    parser_proxy_unset = subparsers.add_parser("unset-proxy", help="Unset Git proxy")

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

    if args.command == "backup":
        manager.backup_dotfiles(_dotfiles_staging_dir(), Path("./sources/root"))
    elif args.command == "restore":
        staging = _dotfiles_staging_dir()
        manager.restore_dotfiles(Path("./sources/root"), staging)
        manager.link_dotfiles(staging, Path.home())
    elif args.command == "set-proxy":
        manager.set_git_proxy()
    elif args.command == "unset-proxy":
        manager.unset_git_proxy()
    else:
        # Default bootstrap behavior
        manager.run()


if __name__ == "__main__":
    main()
