"""Registry of optional install components and their package-manager backends.

Two self-registering hierarchies live here (see ADR-0003):

* :class:`PackageManager` -- an *install backend* keyed by ``id`` (``apt``,
  ``brew``, ``scripts``). Each knows how to install one ``spec`` on the OSes it
  supports. The orchestrator (``DotfilesManager``) selects the backend; a
  component never chooses its own.
* :class:`OptionalComponent` -- an optional piece of software. Declaring a
  subclass with a ``name`` makes it available on the command line
  (``--optional-components``) and via ``DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS``.

A component is declarative-first: it lists ``installs = {manager_id: spec}`` and
the base class resolves it through the manager the orchestrator picks. Multi-step
installs (docker post-setup, llvm update-alternatives, the nvm + pnpm dance)
instead override ``install(ctx)`` and may reuse a manager via
``ctx.package_manager(id)``.
"""

import logging
import os
import pathlib
import shutil
import tempfile

from installers import debian, macos


logger = logging.getLogger("dotfiles")


# -- install specs --------------------------------------------------------
#
# Each PackageManager defines (and accepts) its own spec type. A bare string is
# shorthand for that manager's primary parameter (package name / script URL).


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


# -- optional components --------------------------------------------------


class OptionalComponent:
    """Base class for optional install components.

    Subclasses register themselves by class-definition time keyed on ``name``.
    """

    _registry = {}

    name = ""
    description = ""
    supported_os = None  # explicit list for imperative-override components
    groups = frozenset()
    installs = {}  # {manager_id: spec}; empty => override install() below

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            OptionalComponent._registry[cls.name] = cls

    # -- registry helpers -------------------------------------------------

    @classmethod
    def names(cls):
        """All registered component names, in registration order."""
        return list(cls._registry.keys())

    @classmethod
    def alias_groups(cls):
        """Map of group name -> list of member component names."""
        groups = {}
        for name, comp in cls._registry.items():
            for group in comp.groups:
                groups.setdefault(group, []).append(name)
        return groups

    @classmethod
    def resolve(cls, raw):
        """Resolve a comma-separated spec into an ordered list of names.

        Accepts individual component names and alias groups (e.g. ``all``,
        ``mac``). Unknown tokens are logged and skipped. The returned list
        follows registration order and contains no duplicates.
        """
        groups = cls.alias_groups()
        requested = set()
        for part in raw.split(","):
            part = part.strip().lower()
            if not part:
                continue
            if part in groups:
                requested.update(groups[part])
            elif part in cls._registry:
                requested.add(part)
            else:
                logger.warning(f"Unknown optional component: {part}")
        # Preserve registration order for deterministic install sequencing.
        return [name for name in cls._registry if name in requested]

    @classmethod
    def get(cls, name):
        return cls._registry[name]()

    # -- per-component behavior ------------------------------------------

    def effective_supported_os(self):
        """OS tuple this component applies to (``None`` == all).

        For declarative components it is *derived* from the managers listed in
        ``installs`` -- so it can never drift out of sync with the entries. For
        imperative-override components it is the explicit ``supported_os``.
        """
        if not self.installs:
            return self.supported_os
        oses = set()
        for manager_id in self.installs:
            if not PackageManager.exists(manager_id):
                continue
            manager_os = PackageManager.get(manager_id).supported_os
            if manager_os is None:
                return None  # an all-OS backend (scripts) makes the whole thing all-OS
            oses.update(manager_os)
        return tuple(sorted(oses)) if oses else None

    def applicable(self, ctx):
        supported = self.effective_supported_os()
        return supported is None or ctx.os_type in supported

    def install(self, ctx):
        """Default declarative resolution; override for multi-step installs."""
        manager = ctx.select_manager(self.installs)
        if manager is None:
            raise RuntimeError(
                f"No package manager available for {self.name} on {ctx.os_type}"
            )
        manager.install(ctx, self.installs[manager.id])

    def run(self, ctx):
        if not self.applicable(ctx):
            logger.info(
                f"{self.description} is not applicable on {ctx.os_type}. Skipping."
            )
            return
        logger.info(f"Installing {self.description}...")
        self.install(ctx)


class OnePassword(OptionalComponent):
    name = "1password"
    description = "1Password"
    groups = frozenset({"all"})
    installs = {
        "apt": Deb(
            "https://downloads.1password.com/linux/debian/amd64/stable/1password-latest.deb"
        ),
    }


class Docker(OptionalComponent):
    name = "docker"
    description = "Docker"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, ctx):
        debian.install_docker(ctx.run_command)


class DockerRootless(OptionalComponent):
    name = "docker-rootless"
    description = "Docker (rootless)"
    groups = frozenset({"all"})
    installs = {"scripts": Script("https://get.docker.com/rootless", interpreter="sh")}


class CmdlTools(OptionalComponent):
    name = "cmdl-tools"
    description = "command-line tools"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, ctx):
        debian.install_cmdl_tools(ctx.run_command)


class Cuda(OptionalComponent):
    name = "cuda"
    description = "CUDA Toolkit"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, ctx):
        debian.install_cuda(ctx.run_command)


class Llvm(OptionalComponent):
    name = "llvm"
    description = "LLVM"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, ctx):
        debian.install_llvm(ctx.run_command, version="18", dry_run=ctx.dry_run)


class MacBrew(OptionalComponent):
    name = "mac-brew"
    description = "Homebrew packages"
    supported_os = ("darwin",)
    groups = frozenset({"all"})

    def install(self, ctx):
        macos.install_mac_brew(ctx.run_command)


class ClaudeCode(OptionalComponent):
    name = "claude"
    description = "Claude Code CLI"
    groups = frozenset({"all"})
    # Official native installer; auto-updates in the background.
    # npm fallback: npm install -g @anthropic-ai/claude-code
    installs = {"scripts": Script("https://claude.ai/install.sh", interpreter="bash")}


class Bottom(OptionalComponent):
    name = "btm"
    description = "bottom (system monitor)"
    groups = frozenset({"all"})
    # Pinned release .deb on Debian (bottom isn't in the default repos); brew
    # formula on macOS. Bump the version in the URL deliberately.
    installs = {
        "brew": "bottom",
        "apt": Deb(
            "https://github.com/ClementTsang/bottom/releases/download/0.12.3/"
            "bottom_0.12.3-1_amd64.deb"
        ),
    }


class FdFind(OptionalComponent):
    name = "fdfind"
    description = "fd-find (fast file finder)"
    groups = frozenset({"all"})
    installs = {"brew": "fd", "apt": "fd-find"}


class Node(OptionalComponent):
    name = "node"
    description = "Node.js (nvm + LTS) and pnpm"
    supported_os = None  # nvm's install script covers macOS, Linux, and WSL
    groups = frozenset({"all"})

    # Pinned tag — v0.40.5 carries the CVE-2026-10796 fix. Bump deliberately.
    NVM_VERSION = "v0.40.5"

    def install(self, ctx):
        # nvm is a shell *function*, not a binary on PATH — installing it does
        # not make `nvm` callable in a fresh subprocess. So: fetch + run the
        # install script (reusing the scripts manager), then source nvm.sh and
        # drive the Node + pnpm install inside a single shell that has the
        # freshly-installed nvm loaded.
        install_url = (
            "https://raw.githubusercontent.com/nvm-sh/nvm/"
            f"{self.NVM_VERSION}/install.sh"
        )
        ctx.package_manager("scripts").install(
            ctx, Script(install_url, interpreter="bash")
        )
        # nvm installs into $NVM_DIR (default ~/.nvm). Source it, install the
        # LTS Node (which provides node/npm/npx), then enable pnpm via the
        # Corepack shim that ships with Node.
        nvm_dir = os.environ.get("NVM_DIR") or str(pathlib.Path.home() / ".nvm")
        bootstrap = (
            f'export NVM_DIR="{nvm_dir}"; '
            '. "$NVM_DIR/nvm.sh"; '
            "nvm install --lts; "
            "corepack enable pnpm"
        )
        ctx.run_command(["bash", "-c", bootstrap])


class Rustup(OptionalComponent):
    name = "rustup"
    description = "rustup (Rust toolchain installer) + stable toolchain"
    supported_os = None  # rustup-init.sh covers macOS, Linux, and WSL
    groups = frozenset({"all"})

    def install(self, ctx):
        # Idempotent: if rustup is already on PATH, just refresh the default
        # toolchain and exit — rustup owns its own self-update cadence.
        if shutil.which("rustup"):
            logger.info("rustup already installed; ensuring stable toolchain.")
            ctx.run_command(["rustup", "default", "stable"])
            return

        # Official Unix installer per https://rustup.rs, run via the scripts
        # manager. Flags follow the documented headless contract:
        #   -y                       : accept defaults, skip prompts
        #   --default-toolchain stable
        #   --profile default        : rustc + cargo + rust-std + rustfmt + clippy
        #   --no-modify-path         : the dotfiles already export ~/.cargo/bin
        #                              (see sources/root/.exports).
        ctx.package_manager("scripts").install(
            ctx,
            Script(
                "https://sh.rustup.rs",
                interpreter="sh",
                args=[
                    "-y",
                    "--default-toolchain",
                    "stable",
                    "--profile",
                    "default",
                    "--no-modify-path",
                ],
            ),
        )


class Codegraph(OptionalComponent):
    name = "codegraph"
    description = (
        "CodeGraph (colbymchenry/codegraph) — local code knowledge graph + MCP server"
    )
    supported_os = None  # self-contained bundled-Node builds for macOS, Linux, WSL
    # Deliberately excluded from `all`: agent wiring (`codegraph install`)
    # touches MCP configs across multiple editors and shouldn't run unattended.
    groups = frozenset()

    def install(self, ctx):
        # Idempotent: if codegraph is already on PATH, defer to its own in-place
        # updater rather than re-running the installer — matches upstream
        # guidance ("Already installed? Run `codegraph upgrade`.").
        if shutil.which("codegraph"):
            logger.info("codegraph already installed; running self-update.")
            ctx.run_command(["codegraph", "upgrade"], check=False)
            return

        # Official self-contained installer (no Node.js required): fetches the
        # right per-platform bundled-Node build and drops a `codegraph` shim on
        # PATH. Run via the scripts manager.
        ctx.package_manager("scripts").install(
            ctx,
            Script(
                "https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh",
                interpreter="sh",
            ),
        )

        # NOTE: We intentionally do NOT auto-run `codegraph install` here — that
        # wires CodeGraph's MCP server into every detected agent and is
        # interactive by default. The user opts in afterwards.
        logger.info(
            "codegraph CLI installed. Run `codegraph install` to wire it "
            "into your AI agents (Claude Code, Cursor, etc.), then "
            "`codegraph init` inside each project."
        )


def main():
    """Print all available optional components."""
    print("Available Optional Components:")
    print("=" * 50)

    for name in OptionalComponent.names():
        comp = OptionalComponent.get(name)
        groups_str = ", ".join(sorted(comp.groups)) if comp.groups else "none"
        supported = comp.effective_supported_os()
        os_str = ", ".join(supported) if supported else "all OS"
        backends = ", ".join(comp.installs) if comp.installs else "custom"
        print(f"\n  {name}")
        print(f"    Description: {comp.description}")
        print(f"    OS: {os_str}")
        print(f"    Backends: {backends}")
        print(f"    Groups: {groups_str}")

    print("\n" + "=" * 50)
    print("\nAlias Groups:")
    for group_name, components in sorted(OptionalComponent.alias_groups().items()):
        print(f"  {group_name}: {', '.join(components)}")


if __name__ == "__main__":
    main()
