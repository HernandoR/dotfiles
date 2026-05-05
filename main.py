import logging
import os
import platform
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dotfiles")


class DotfilesManager:
    def __init__(self):
        self.os_type = self._detect_os()
        self.state = {
            "apt_updated": False,
        }

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

    def run_command(self, cmd, check=True, shell=False):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        logger.info(f"Running: {cmd_str}")
        try:
            subprocess.run(cmd, check=check, shell=shell)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error executing command: {e}")
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
            subprocess.run(
                ["command", "-v", "curl"], shell=True, capture_output=True
            ).returncode
            != 0
        ):
            logger.info("curl not found, installing curl and dependencies...")
            self.run_command(["sudo", "apt", "-y", "remove", "libcurl4"])
            self.run_command(["sudo", "apt", "-y", "install", "curl", "xclip"])

        packages = ["git", "zsh", "rsync", "aptitude"]
        logger.info(f"Installing core packages: {', '.join(packages)}")
        self.run_command(["sudo", "apt", "-y", "install"] + packages)

    def run_legacy_scripts(self):
        if os.path.exists("./install-llvm.sh"):
            self.run_command(["./install-llvm.sh", "18", "all"])
        else:
            logger.warning("install-llvm.sh not found.")

        if os.path.exists("./config-ohmyzsh.sh"):
            self.run_command(["./config-ohmyzsh.sh"])
        else:
            logger.warning("config-ohmyzsh.sh not found.")

        if os.path.exists("./restore_and_backup.py"):
            self.run_command([sys.executable, "./restore_and_backup.py", "restore"])
        elif os.path.exists("./restore_and_backup.sh"):
            self.run_command(["./restore_and_backup.sh", "restore"])
        else:
            logger.warning("Neither restore_and_backup.py nor .sh found.")

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
    manager = DotfilesManager()
    manager.run()


if __name__ == "__main__":
    main()
