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


ASSUME_YES_ENV = "DF_ASSUME_YES"


class Ctx:
    """Execution context passed to components (the ADR-0003 ``ctx``)."""

    def __init__(self, dry_run=False, options=None, assume_yes=None):
        self.dry_run = dry_run
        self.options = options or {}
        self.os_type = self._detect_os()
        # One-shot clearance (see require_clearance): already granted when the
        # caller says so, or when $DF_ASSUME_YES=1 — which platform/bootstrap.sh
        # exports once the user has cleared the plan, so this process does not
        # ask a second time for the same run.
        self.assume_yes = (
            os.environ.get(ASSUME_YES_ENV, "") == "1" if assume_yes is None else bool(assume_yes)
        )
        self._extend_path()

    @staticmethod
    def _extend_path():
        """Put the per-user bin dirs that upstream installers link into on this
        process' PATH. Those installers (codegraph, the Claude CLI, uv, …) drop a
        symlink in ~/.local/bin and print "add this to your PATH" — the login
        shell gets it from the HM zsh config, but a bootstrap run that installs
        and then *uses* a tool in the same process would not, so `shutil.which`
        and the exec lookup would both miss it. Prepending is safe: these dirs
        are exactly where the HM config puts them for the interactive shell."""
        user_bins = [pathlib.Path.home() / ".local/bin", pathlib.Path.home() / "bin"]
        path = os.environ.get("PATH", "").split(os.pathsep)
        missing = [str(p) for p in user_bins if str(p) not in path]
        if missing:
            os.environ["PATH"] = os.pathsep.join([*missing, *path])

    # -- interactivity ----------------------------------------------------
    @property
    def interactive(self):
        """Is a human there to answer? True when stdin is a terminal, or when
        stdin is a pipe but the terminal is still reachable via /dev/tty with
        stdout attached to it (`curl … | python3 -`). False under CI, a container
        build or `bash -c`, where a prompt would hang a headless run."""
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                return True
            if sys.stdout is not None and sys.stdout.isatty() and os.access("/dev/tty", os.R_OK):
                return True
        except (ValueError, OSError):  # closed / detached stream
            pass
        return False

    def require_clearance(self, prompt="Proceed with the plan above?"):
        """Ask ONCE for clearance to run the printed plan, then remember the
        answer (``assume_yes``) so nothing asks again. Yes -> return True; no ->
        SystemExit. Returns True without asking when clearance is already
        granted, under --dry-run (nothing to clear), or with no terminal — so the
        caller can invoke it unconditionally."""
        if self.assume_yes or self.dry_run or not self.interactive:
            self.assume_yes = True
            return True
        tty = None
        try:
            if not sys.stdin.isatty():
                tty = open("/dev/tty", "r+")
            while True:
                self._ask(f"\n? {prompt} [Y/n] ", tty)
                line = (tty.readline() if tty else sys.stdin.readline())
                if not line:  # EOF on the terminal: do not guess, stop.
                    raise SystemExit("aborted (no answer on the terminal)")
                answer = line.strip().lower()
                if answer in ("", "y", "yes"):
                    self.assume_yes = True
                    self._ask("\n", tty)
                    return True
                if answer in ("n", "no", "q", "quit"):
                    raise SystemExit("aborted — nothing has been installed or changed")
                self._ask("  please answer y or n\n", tty)
        finally:
            if tty is not None:
                tty.close()

    @staticmethod
    def _ask(text, tty=None):
        """Write a prompt where the human can see it: the terminal when we hold
        it, else stderr (a stdout redirected to a log file must not swallow a
        prompt the run is blocking on)."""
        stream = tty or (sys.stdout if sys.stdout.isatty() else sys.stderr)
        stream.write(text)
        stream.flush()

    @property
    def is_root(self):
        return os.geteuid() == 0

    @property
    def priv(self):
        """Live privilege level — 'root' | 'sudo' | 'none' — for gating and
        logging. Derived from the running process, so there is no flag to pass
        or keep in sync; 'none' (non-root, no sudo) marks a session that must
        skip privileged steps. The sudo-or-not decision itself is _needs_sudo()."""
        if self.is_root:
            return "root"
        return "sudo" if self._needs_sudo() else "none"

    @staticmethod
    def _needs_sudo():
        """Whether a privileged command must be prefixed with sudo, decided
        live from the running process: true iff we are NOT root but a sudo
        binary exists. Root needs no sudo; an unprivileged session with no sudo
        cannot escalate (that command is expected to be gated off via priv)."""
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
                    env=None, with_sudo=False, stdin_devnull=False):
        # with_sudo prepends sudo when the live environment needs it (non-root
        # with a sudo binary) — see _needs_sudo(). Callers pass the bare command
        # + with_sudo=True instead of a literal "sudo", so a root session (incl.
        # a container with no sudo) runs it unprefixed automatically.
        #
        # stdin_devnull detaches the child from the terminal, so a command that
        # was expected to be non-interactive FAILS on an unexpected prompt instead
        # of blocking the whole bootstrap on a question nobody can see. Use it for
        # anything driven off a list (the ADR-0011 agent projection); steps that
        # legitimately ask keep the inherited stdin.
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
                cmd, check=check, shell=shell, capture_output=capture_output, env=run_env,
                stdin=subprocess.DEVNULL if stdin_devnull else None,
            )
        except subprocess.CalledProcessError as e:
            logger.error("command failed: %s", e)
            if check:
                sys.exit(1)
            return e
        except OSError as e:
            # Binary not found / not executable. Without this, check=False still
            # aborted the whole bootstrap with a traceback, because the failure
            # happens in exec (FileNotFoundError) rather than in the exit status.
            logger.error("could not run %s: %s", cmd_str, e)
            if check:
                sys.exit(1)
            return subprocess.CompletedProcess(cmd, 127, b"", b"")

    def package_manager(self, manager_id):
        return PackageManager.get(manager_id)

    def select_manager(self, installs):
        candidates = [
            PackageManager.get(mid)
            for mid in installs
            if PackageManager.exists(mid) and PackageManager.get(mid).applicable(self.os_type)
        ]
        return max(candidates, key=lambda m: m.priority) if candidates else None
