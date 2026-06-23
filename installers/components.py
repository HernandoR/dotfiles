"""Registry of optional install components.

Each optional component is a self-registering subclass of
:class:`OptionalComponent`. Declaring a subclass with a ``name`` is enough to
make it available on the command line (``--optional-components``) and via the
``DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS`` env var — no parallel lookup tables
to keep in sync.

A component declares:

* ``name``        -- the CLI identifier (e.g. ``"docker"``)
* ``description`` -- human-readable label used in logs and help text
* ``supported_os``-- iterable of OS types it applies to, or ``None`` for all
* ``groups``      -- alias groups it belongs to (e.g. ``{"all", "mac"}``)
* ``install``     -- performs the actual installation given the manager
"""

import logging
import os
import pathlib
import tempfile

# import debian
# import macos
from installers import debian, macos


logger = logging.getLogger("dotfiles")


class OptionalComponent:
    """Base class for optional install components.

    Subclasses register themselves by class-definition time keyed on ``name``.
    """

    _registry = {}

    name = ""
    description = ""
    supported_os = None  # None means "all operating systems"
    groups = frozenset()

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

    def applicable(self, manager):
        return self.supported_os is None or manager.os_type in self.supported_os

    def install(self, manager):
        raise NotImplementedError

    def run(self, manager):
        if not self.applicable(manager):
            logger.info(
                f"{self.description} is not applicable on {manager.os_type}. Skipping."
            )
            return
        logger.info(f"Installing {self.description}...")
        self.install(manager)


class OnePassword(OptionalComponent):
    name = "1password"
    description = "1Password"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_1password(manager.run_command)


class Docker(OptionalComponent):
    name = "docker"
    description = "Docker"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_docker(manager.run_command)


class DockerRootless(OptionalComponent):
    name = "docker-rootless"
    description = "Docker (rootless)"
    supported_os = None
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_docker_rootless(manager.run_command)


class CmdlTools(OptionalComponent):
    name = "cmdl-tools"
    description = "command-line tools"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_cmdl_tools(manager.run_command)


class Cuda(OptionalComponent):
    name = "cuda"
    description = "CUDA Toolkit"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_cuda(manager.run_command)


class Llvm(OptionalComponent):
    name = "llvm"
    description = "LLVM"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, manager):
        debian.install_llvm(manager.run_command, version="18", dry_run=manager.dry_run)


class MacBrew(OptionalComponent):
    name = "mac-brew"
    description = "Homebrew packages"
    supported_os = ("darwin",)
    groups = frozenset({"all"})

    def install(self, manager):
        macos.install_mac_brew(manager.run_command)


class ClaudeCode(OptionalComponent):
    name = "claude"
    description = "Claude Code CLI"
    supported_os = None  # cross-platform native installer (macOS, Linux, WSL)
    groups = frozenset({"all"})

    def install(self, manager):
        # Official native installer; auto-updates in the background.
        # npm fallback: npm install -g @anthropic-ai/claude-code
        # Download then execute separately so a curl failure raises instead of
        # silently feeding an empty script to bash (shell pipelines return the
        # last command's exit code, masking upstream failures).
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
            tmp_path = pathlib.Path(tmp.name)
        try:
            manager.run_command(
                ["curl", "-fsSL", "https://claude.ai/install.sh", "-o", str(tmp_path)]
            )
            manager.run_command(["bash", str(tmp_path)])
        finally:
            tmp_path.unlink(missing_ok=True)


class Bottom(OptionalComponent):
    name = "btm"
    description = "bottom (system monitor)"
    supported_os = None
    groups = frozenset({"all"})

    def install(self, manager):
        if manager.os_type == "darwin":
            manager.run_command(["brew", "install", "bottom"])
        else:
            debian.install_btm(manager.run_command)


class FdFind(OptionalComponent):
    name = "fdfind"
    description = "fd-find (fast file finder)"
    supported_os = None
    groups = frozenset({"all"})

    def install(self, manager):
        if manager.os_type == "darwin":
            manager.run_command(["brew", "install", "fd"])
        else:
            debian.install_fdfind(manager.run_command)


class Node(OptionalComponent):
    name = "node"
    description = "Node.js (nvm + LTS) and pnpm"
    supported_os = None  # nvm's install script covers macOS, Linux, and WSL
    groups = frozenset({"all"})

    # Pinned tag — v0.40.5 carries the CVE-2026-10796 fix. Bump deliberately.
    NVM_VERSION = "v0.40.5"

    def install(self, manager):
        # nvm is a shell *function*, not a binary on PATH — installing it does
        # not make `nvm` callable in a fresh subprocess. So: fetch + run the
        # install script, then source nvm.sh and drive the Node + pnpm install
        # inside a single shell that has the freshly-installed nvm loaded.
        # Direct curl (no gitee mirror) matches the claude/starship components.
        install_url = (
            "https://raw.githubusercontent.com/nvm-sh/nvm/"
            f"{self.NVM_VERSION}/install.sh"
        )
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
            tmp_path = pathlib.Path(tmp.name)
        try:
            manager.run_command(["curl", "-fsSL", install_url, "-o", str(tmp_path)])
            manager.run_command(["bash", str(tmp_path)])
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
            manager.run_command(["bash", "-c", bootstrap])
        finally:
            tmp_path.unlink(missing_ok=True)


def main():
    """Print all available optional components."""
    print("Available Optional Components:")
    print("=" * 50)

    for name in OptionalComponent.names():
        comp = OptionalComponent.get(name)
        groups_str = ", ".join(sorted(comp.groups)) if comp.groups else "none"
        os_str = ", ".join(comp.supported_os) if comp.supported_os else "all OS"
        print(f"\n  {name}")
        print(f"    Description: {comp.description}")
        print(f"    OS: {os_str}")
        print(f"    Groups: {groups_str}")

    print("\n" + "=" * 50)
    print("\nAlias Groups:")
    for group_name, components in sorted(OptionalComponent.alias_groups().items()):
        print(f"  {group_name}: {', '.join(components)}")


if __name__ == "__main__":
    main()
