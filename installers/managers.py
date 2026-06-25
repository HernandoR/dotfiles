"""Package-manager backends for optional components (see ADR-0003).

A :class:`PackageManager` is an *install backend* keyed by ``id`` (``apt``,
``brew``, ``scripts``). Given a per-manager ``spec`` it knows how to install
that thing on the OSes it supports. The orchestrator (``DotfilesManager``)
selects the backend; a component never chooses its own.

Each manager defines (and accepts) its own spec type. A bare string is
shorthand for that manager's primary parameter -- a package name for ``apt`` /
``brew``, a script URL for ``scripts``.
"""

import logging
import pathlib
import tempfile


logger = logging.getLogger("dotfiles")


# -- install specs --------------------------------------------------------


class Script:
    """Spec for the ``scripts`` manager: fetch a URL and run it.

    URL alone is not enough -- rustup needs ``sh`` plus a list of flags,
    codegraph needs ``sh``, claude/nvm need ``bash``.
    """

    def __init__(self, url, interpreter="bash", args=()):
        self.url = url
        self.interpreter = interpreter
        self.args = list(args)


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

    def install(self, ctx, spec):
        if isinstance(spec, Deb):
            # Download then `apt install -f` the local file so dependencies
            # resolve (dpkg -i alone would leave them unmet).
            with tempfile.NamedTemporaryFile(suffix=".deb", delete=False) as tmp:
                deb_path = pathlib.Path(tmp.name)
            try:
                ctx.run_command(["wget", spec.url, "-O", str(deb_path)])
                ctx.run_command(["sudo", "apt", "install", "-f", "-y", str(deb_path)])
            finally:
                deb_path.unlink(missing_ok=True)
        else:
            ctx.run_command(["sudo", "apt", "install", "-y", spec])


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
            ctx.run_command(["curl", "-fsSL", spec.url, "-o", str(tmp_path)])
            ctx.run_command([spec.interpreter, str(tmp_path), *spec.args])
        finally:
            tmp_path.unlink(missing_ok=True)
