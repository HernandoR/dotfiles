"""Package-manager backends for optional components (see ADR-0003).

A :class:`PackageManager` is an *install backend* keyed by ``id`` (``apt``,
``dnf``, ``zypper``, ``pacman``, ``apk``, ``brew``, ``scripts``). Given a
per-manager ``spec`` it knows how to install that thing on the OSes it supports.
The orchestrator (``DotfilesManager``) selects the backend; a component never
chooses its own.

``supported_os`` is the registry that keeps this half honest: it is keyed by the
OS *family* ``Ctx._detect_os`` reports, and a family no backend claims simply has
no backend — ``select_manager`` returns ``None`` and the component is skipped.
Nothing may hardcode a package-manager binary outside this module; that is how an
Amazon Linux host once got handed ``apt-get``.

Each manager defines (and accepts) its own spec type. A bare string is
shorthand for that manager's primary parameter -- a package name for ``apt`` /
``brew``, a script URL for ``scripts``.
"""

import logging
import pathlib
import shutil
import tempfile


logger = logging.getLogger("dotfiles")


# -- install specs --------------------------------------------------------


class Script:
    """Spec for the ``scripts`` manager: fetch a URL and run it.

    URL alone is not enough -- rustup needs ``sh`` plus a list of flags,
    codegraph needs ``sh``, claude/nvm need ``bash``.
    """

    def __init__(self, url, interpreter="bash", args=(), env=None, check=True):
        self.url = url
        self.interpreter = interpreter
        self.args = list(args)
        # Optional env overlay for the run step (e.g. nvm honors PROFILE to skip
        # editing shell rc files). Applied only to running the script, not curl.
        self.env = env
        # Whether a failed download or a non-zero installer exit aborts the whole
        # run. The vendor installers behind the coding agents (ADR-0011) pass
        # check=False: one of them having a bad day must not take the rest of the
        # post-HM phase — system components included — down with it. Verified the
        # hard way: a fresh pod where Claude's installer exited 1 aborted
        # everything after it, so codex and omp never ran.
        self.check = check


class Deb:
    """Spec for the ``apt`` manager: download a ``.deb`` and ``apt install -f`` it.

    Lets the single ``apt`` backend express "install from a downloaded package"
    (e.g. 1Password) without a separate ``deb`` manager id.
    """

    def __init__(self, url):
        self.url = url


# -- package-manager backends --------------------------------------------


class PackageManager:
    """Base class for install backends.

    Subclasses register themselves at class-definition time keyed on ``id``.
    """

    _registry = {}

    id = ""
    supported_os = None  # None means "all operating systems"
    priority = 0  # higher wins when several backends match (native > scripts)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.id:
            PackageManager._registry[cls.id] = cls

    @classmethod
    def exists(cls, manager_id):
        return manager_id in cls._registry

    @classmethod
    def get(cls, manager_id):
        return cls._registry[manager_id]()

    def applicable(self, os_type):
        return self.supported_os is None or os_type in self.supported_os

    def install(self, ctx, spec):
        raise NotImplementedError


class AptManager(PackageManager):
    id = "apt"
    supported_os = ("debian", "ubuntu")
    priority = 100

    # Refresh the package index once per process. A fresh container/CI image
    # often ships an empty /var/lib/apt/lists, so a bare `apt install` fails with
    # "Unable to locate package". Guard is class-level because get() hands out a
    # new instance per call. Non-fatal: a flaky update shouldn't mask the (more
    # informative) install error that follows.
    _updated = False

    def _ensure_updated(self, ctx):
        if AptManager._updated:
            return
        ctx.run_command(["apt-get", "update"], with_sudo=True, check=False)
        AptManager._updated = True

    def install(self, ctx, spec):
        self._ensure_updated(ctx)
        if isinstance(spec, Deb):
            # Download then `apt install -f` the local file so dependencies
            # resolve (dpkg -i alone would leave them unmet).
            with tempfile.NamedTemporaryFile(suffix=".deb", delete=False) as tmp:
                deb_path = pathlib.Path(tmp.name)
            try:
                ctx.run_command(["wget", spec.url, "-O", str(deb_path)])
                ctx.run_command(["apt", "install", "-f", "-y", str(deb_path)], with_sudo=True)
            finally:
                deb_path.unlink(missing_ok=True)
        else:
            ctx.run_command(["apt", "install", "-y", spec], with_sudo=True)


class _SystemManager(PackageManager):
    """Shared shape for the non-apt native package managers: one install command
    template, one OS-family list. They exist so a component can *declare* an
    install for those families instead of the orchestrator silently falling back
    to apt — which on Amazon Linux meant running `apt-get` that is not there.
    A family with no entry here has no backend, and a component whose installs
    do not cover the running family is skipped by Component.applicable()."""

    command = ()  # argv prefix; the package name is appended
    priority = 100

    def install(self, ctx, spec):
        if not isinstance(spec, str):
            raise TypeError(f"{self.id} takes a package name, got {type(spec).__name__}")
        ctx.run_command([*self.command, spec], with_sudo=True)


class DnfManager(_SystemManager):
    # AL2023 / Fedora / RHEL>=8 ship dnf, and on AL2 / RHEL7 `yum` is the same
    # front end; dnf is a symlink to yum where only yum exists, so one id covers
    # the family. Amazon Linux is `amzn` on purpose: its ID_LIKE says fedora,
    # which is true for dnf and false for everything else it inherits.
    id = "dnf"
    supported_os = ("amzn", "fedora", "rhel")
    command = ("dnf", "install", "-y")

    def install(self, ctx, spec):
        binary = "dnf" if shutil.which("dnf") else "yum"
        ctx.run_command([binary, "install", "-y", spec], with_sudo=True)


class ZypperManager(_SystemManager):
    id = "zypper"
    supported_os = ("suse",)
    command = ("zypper", "--non-interactive", "install")


class PacmanManager(_SystemManager):
    id = "pacman"
    supported_os = ("arch",)
    command = ("pacman", "-Sy", "--noconfirm")


class ApkManager(_SystemManager):
    id = "apk"
    supported_os = ("alpine",)
    command = ("apk", "add", "--no-cache")


class BrewManager(PackageManager):
    id = "brew"
    supported_os = ("darwin",)
    priority = 100

    def install(self, ctx, spec):
        ctx.run_command(["brew", "install", spec])


class ScriptsManager(PackageManager):
    id = "scripts"
    supported_os = None  # remote bootstrap scripts run anywhere
    priority = 10  # fallback: a native package manager is preferred when present

    def install(self, ctx, spec):
        if isinstance(spec, str):
            spec = Script(url=spec)
        # Download then execute separately so a curl failure raises instead of
        # silently feeding an empty script to the interpreter -- a piped
        # `curl | sh` returns the interpreter's exit code, masking curl's.
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
            tmp_path = pathlib.Path(tmp.name)
        try:
            ctx.run_command(["curl", "-fsSL", spec.url, "-o", str(tmp_path)],
                            check=spec.check)
            ctx.run_command(
                [spec.interpreter, str(tmp_path), *spec.args], env=spec.env,
                check=spec.check,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
