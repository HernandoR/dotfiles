"""Execution context + privilege detection shared by the imperative tools
(scripts/setup.py, packages.py, bootstrap.py). This is the ADR-0003 ``ctx``
passed into every component."""

import logging
import os
import pathlib
import shutil
import signal
import subprocess
import sys

from managers import PackageManager

logger = logging.getLogger("dotfiles")


def quiet_broken_pipe():
    """Die quietly when stdout is closed early, as in ``… | head -40``.

    Python installs SIG_IGN for SIGPIPE and reports the failed write as a
    BrokenPipeError instead, so a script that keeps printing after ``head`` has
    exited ends in a traceback rather than simply stopping — which is what
    ``./bootstrap.sh --dry-run | head -40`` did on 2026-09-10. Restoring the
    default disposition makes the process be killed by SIGPIPE exactly like
    ``cat`` or ``ls``, which is the behaviour every caller of a pipeline expects.

    Called at import time because these modules are only ever imported by this
    repo's own CLI entry points, and it must take effect before the first print.
    Scripts that do not import this module carry the same three lines inline.
    """
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)


quiet_broken_pipe()


ASSUME_YES_ENV = "DF_ASSUME_YES"
# Opt IN to being asked. Everything in this repo runs non-interactively by
# default (ADR-0013 update 2026-09-10): the plan is printed, then the run
# proceeds. Set this (or pass --interactive) to get the one-shot clearance
# prompt and the `chezmoi init` questions back.
INTERACTIVE_ENV = "DOTFILE_INTERACTIVE"


class Ctx:
    """Execution context passed to components (the ADR-0003 ``ctx``)."""

    def __init__(self, dry_run=False, options=None, assume_yes=None, ask=False):
        self.dry_run = dry_run
        self.options = options or {}
        self.os_type = self._detect_os()
        # Is a human to be asked at all? NO by default — a bootstrap that blocks
        # on a question is useless in CI, a container build, a devpod recreation
        # or an agent's shell, and those are the common cases. `ask` (--interactive)
        # or $DOTFILE_INTERACTIVE=1 opts back in.
        self.ask = bool(ask) or os.environ.get(INTERACTIVE_ENV, "") == "1"
        # One-shot clearance (see require_clearance): granted when the caller says
        # so, when $DF_ASSUME_YES=1 (scripts/bootstrap.py exports it once the plan
        # is cleared, so a nested process never asks twice), and otherwise
        # whenever nobody asked to be asked.
        if assume_yes is not None:
            self.assume_yes = bool(assume_yes)
        elif os.environ.get(ASSUME_YES_ENV, "") == "1":
            self.assume_yes = True
        else:
            self.assume_yes = not self.ask
        self._extend_path()

    @staticmethod
    def _extend_path():
        """Put the per-user bin dirs that upstream installers link into on this
        process' PATH. Those installers (codegraph, the Claude CLI, uv, …) drop a
        symlink in ~/.local/bin and print "add this to your PATH" — the login
        shell gets it from the zsh env (env.zsh), but a bootstrap run that installs
        and then *uses* a tool in the same process would not, so `shutil.which`
        and the exec lookup would both miss it. Prepending is safe: these dirs
        are exactly where env.zsh puts them for the interactive shell."""
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
        SystemExit.

        Returns True WITHOUT asking in every case but one: the caller opted into
        being asked (--interactive / $DOTFILE_INTERACTIVE=1) AND a terminal is
        there to answer. Clearance already granted, --dry-run and a headless run
        all pass straight through, so the caller can invoke it unconditionally."""
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

    # /etc/os-release ID -> the OS family this repo keys its backends on. Exact
    # ids win over ID_LIKE (Amazon Linux says ID_LIKE=fedora, which is true for
    # dnf and false for everything else), and an unrecognised Linux stays
    # "unknown" rather than being guessed as debian: a family with no apt must be
    # SKIPPED, and it can only be skipped if it is named honestly. Keep in step
    # (This is the single OS-detection implementation; scripts/bootstrap.py
    # imports Ctx rather than reimplementing it.)
    _OS_IDS = {
        "ubuntu": "ubuntu", "pop": "ubuntu", "linuxmint": "ubuntu", "elementary": "ubuntu",
        "debian": "debian", "raspbian": "debian",
        "amzn": "amzn",
        "fedora": "fedora",
        "rhel": "rhel", "centos": "rhel", "rocky": "rhel", "almalinux": "rhel", "ol": "rhel",
        "sles": "suse",
        "arch": "arch", "manjaro": "arch", "endeavouros": "arch",
        "alpine": "alpine",
    }
    _OS_LIKE = (
        ("ubuntu", "ubuntu"), ("debian", "debian"),
        ("fedora", "rhel"), ("rhel", "rhel"), ("centos", "rhel"),
        ("suse", "suse"), ("arch", "arch"),
    )

    @classmethod
    def _detect_os(cls):
        if sys.platform == "darwin":
            return "darwin"
        fields = {}
        try:
            for line in pathlib.Path("/etc/os-release").read_text().splitlines():
                key, _, value = line.partition("=")
                if _:
                    fields[key.strip()] = value.strip().strip('"\'').lower()
        except OSError:
            pass
        os_id = fields.get("ID", "")
        if os_id in cls._OS_IDS:
            return cls._OS_IDS[os_id]
        if os_id.startswith("opensuse"):
            return "suse"
        like = fields.get("ID_LIKE", "")
        for needle, family in cls._OS_LIKE:
            if needle in like:
                return family
        return "unknown"

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
