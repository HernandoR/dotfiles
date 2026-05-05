import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dotfiles")


class DotfilesManager:
    def __init__(self, dry_run=False, verbose=False):
        self.os_type = self._detect_os()
        self.state = {
            "apt_updated": False,
        }
        self.dry_run = dry_run
        self.verbose = verbose
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

    def install_llvm(self, version="18"):
        logger.info(f"Installing LLVM version {version}...")
        llvm_sh_path = Path.home() / ".local" / "bin" / "llvm.sh"
        if not self.dry_run:
            llvm_sh_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info("Downloading llvm.sh...")
            urllib.request.urlretrieve("https://apt.llvm.org/llvm.sh", llvm_sh_path)
            llvm_sh_path.chmod(0o755)

        logger.info("Running llvm.sh...")
        self.run_command(["sudo", str(llvm_sh_path), version, "all"])

        logger.info("Setting up update-alternatives for clang...")
        alternatives = [
            ("clang", "clang", f"clang-{version}", 100),
            ("clang++", "clang++", f"clang++-{version}", None),
            ("clang-cpp", "clang-cpp", f"clang-cpp-{version}", None),
            ("clangd", "clangd", f"clangd-{version}", None),
            ("clang-format", "clang-format", f"clang-format-{version}", None),
            ("clang-tidy", "clang-tidy", f"clang-tidy-{version}", None),
            ("clang-cl", "clang-cl", f"clang-cl-{version}", None),
            ("clang-query", "clang-query", f"clang-query-{version}", None),
            ("clang-rename", "clang-rename", f"clang-rename-{version}", None),
        ]

        cmd = [
            "sudo",
            "update-alternatives",
            "--install",
            "/usr/bin/clang",
            "clang",
            f"/usr/bin/clang-{version}",
            "100",
        ]
        for _, link, path, _ in alternatives[1:]:
            cmd.extend(["--slave", f"/usr/bin/{link}", link, f"/usr/bin/{path}"])
        self.run_command(cmd)

        bin_dir = Path("/usr/bin")
        if bin_dir.exists():
            for file in bin_dir.glob(f"*-{version}"):
                base_name = file.name.replace(f"-{version}", "")
                if not (bin_dir / base_name).exists():
                    self.run_command(
                        [
                            "sudo",
                            "update-alternatives",
                            "--install",
                            f"/usr/bin/{base_name}",
                            base_name,
                            str(file),
                            "1",
                        ]
                    )

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

    def config_ohmyzsh(self, use_github=True):
        if not Path("./sources").is_dir():
            logger.error("Please execute this script in the dotfiles directory")
            sys.exit(1)

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
            self.run_command(["curl", "-fsSL", install_url, "-o", "./install.sh"])
            self.run_command(["sh", "./install.sh"])
            if not self.dry_run:
                Path("./install.sh").unlink(missing_ok=True)

        logger.info("Installing antigen...")
        if not self.dry_run:
            self.run_command(
                [
                    "curl",
                    "-fsSL",
                    "https://gitee.com/romkatv/antigen/raw/master/bin/antigen.zsh",
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

    def run_legacy_scripts(self):
        if self.os_type in ["debian", "ubuntu"]:
            self.install_llvm("18")

        # Using integrated omz config instead of python script
        self.config_ohmyzsh()

        # Using integrated restore process instead of external scripts
        self.restore_dotfiles(Path("./sources/root"), Path.home() / "dotfiles")
        self.link_dotfiles(Path.home() / "dotfiles", Path.home())

    def run(self):
        logger.info("Initializing python-based dotfiles bootstrap...")
        logger.info(f"Detected OS Type: {self.os_type}")

        if self.os_type == "darwin":
            logger.info("macOS detected. Core package installation skipped.")
        elif self.os_type == "debian" or "ubuntu" in self.os_type.lower():
            self.bootstrap_debian()
        else:
            logger.error(f"Unknown OS: {self.os_type}")
            sys.exit(1)

        self.run_legacy_scripts()
        logger.info("Bootstrap completed successfully!")


def main():
    parser = argparse.ArgumentParser(description="Dotfiles Bootstrap Manager")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")

    # Optional direct commands for just backup or restore
    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    # backup
    parser_bkp = subparsers.add_parser("backup", help="Backup dotfiles")

    # restore
    parser_res = subparsers.add_parser("restore", help="Restore dotfiles")

    args = parser.parse_args()

    manager = DotfilesManager(dry_run=args.dry_run, verbose=args.verbose)

    if args.command == "backup":
        manager.backup_dotfiles(Path.home() / "dotfiles", Path("./sources/root"))
    elif args.command == "restore":
        manager.restore_dotfiles(Path("./sources/root"), Path.home() / "dotfiles")
        manager.link_dotfiles(Path.home() / "dotfiles", Path.home())
    else:
        # Default bootstrap behavior
        manager.run()


if __name__ == "__main__":
    main()
