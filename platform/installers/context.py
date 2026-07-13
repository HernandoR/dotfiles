"""Execution context + privilege detection shared by the imperative tools
(platform/setup.py and the interactive installers). This is the ADR-0003 ``ctx``
passed into every component."""

import logging
import os
import pathlib
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
        self.priv = priv  # root | sudo | none — used for gating/logging
        self.dry_run = dry_run
        self.options = options or {}
        self.os_type = self._detect_os()

    @property
    def is_root(self):
        return os.geteuid() == 0

    @staticmethod
    def _needs_sudo():
        """Whether a privileged command must be prefixed with sudo, decided
        live from the running process rather than the passed --priv (which may
        be defaulted or stale, e.g. a root-without-sudo container or a GitHub
        workspace where the flag never says 'sudo'): true iff we are NOT root
        but a sudo binary exists. Root needs no sudo; an unprivileged session
        with no sudo cannot escalate (that command is expected to be gated off)."""
        return os.geteuid() != 0 and shutil.which("sudo") is not None

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

    @property
    def sudo(self):
        """Shell prefix for a privileged command ('sudo ' or ''), decided live
        via _needs_sudo(). Interpolate it into shell strings where the privilege
        lands mid-pipeline, e.g. f'... | {ctx.sudo}tee file'. For a whole command
        prefer run_command(cmd, with_sudo=True)."""
        return "sudo " if self._needs_sudo() else ""

    def run_command(self, cmd, check=True, shell=False, capture_output=False,
                    env=None, with_sudo=False):
        # with_sudo prepends sudo when the live environment needs it (non-root
        # with a sudo binary) — see _needs_sudo(). Callers pass the bare command
        # + with_sudo=True instead of a literal "sudo", so a root session (incl.
        # a container with no sudo) runs it unprefixed automatically.
        if with_sudo and self._needs_sudo():
            cmd = ["sudo", *cmd] if isinstance(cmd, list) else "sudo " + cmd
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
