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

        packages = ["git", "zsh", "rsync", "aptitude", "wget"]
        logger.info(f"Installing core packages: {', '.join(packages)}")
        self.run_command(["sudo", "apt", "-y", "install"] + packages)

    def install_llvm(self, version="18"):
        logger.info(f"Installing LLVM version {version}...")
        llvm_sh_path = Path.home() / ".local" / "bin" / "llvm.sh"
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

    def run_legacy_scripts(self):
        if self.os_type in ["debian", "ubuntu"]:
            self.install_llvm("18")

        if os.path.exists("./config-ohmyzsh.py"):
            self.run_command([sys.executable, "./config-ohmyzsh.py"])
        else:
            logger.warning("config-ohmyzsh.py not found.")

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
