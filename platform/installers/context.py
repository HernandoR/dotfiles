"""Execution context + privilege detection shared by the imperative tools
(platform/setup.py and the interactive installers). This is the ADR-0003 ``ctx``
passed into every component."""

import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys

from installers.managers import PackageManager

logger = logging.getLogger("dotfiles")


def detect_priv():
    """Return 'root' | 'sudo' | 'none' (mirrors platform/lib.sh detect_priv)."""
    if os.geteuid() == 0:
        return "root"
    if shutil.which("sudo"):
        return "sudo"
    return "none"


class Ctx:
    """Execution context passed to components (the ADR-0003 ``ctx``)."""

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
        # Strip sudo when already root (there is no sudo in a bare root
        # container). For strings, drop `sudo` wherever it starts a command word
        # — the leading command, or after a pipe/&&/||/; — since shell strings
        # embed it mid-pipeline (e.g. `... | sudo tee ...`). For lists, drop a
        # leading or standalone `sudo` token.
        if self.is_root:
            if isinstance(cmd, str):
                cmd = re.sub(r"(^|[|&;]\s*)sudo\s+", r"\1", cmd)
            elif isinstance(cmd, list):
                cmd = [a for a in cmd if a != "sudo"]
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
