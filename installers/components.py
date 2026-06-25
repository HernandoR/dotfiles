"""Registry of optional install components.

Each optional component is a self-registering subclass of
:class:`OptionalComponent`. Declaring a subclass with a ``name`` makes it
available on the command line (``--optional-components``) and via the
``DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS`` env var.

A component is declarative-first (see ADR-0003): it lists
``installs = {manager_id: spec}`` and the base class resolves it through the
backend the orchestrator picks (see :mod:`installers.managers`). Multi-step
installs (docker post-setup, llvm update-alternatives, the nvm + pnpm dance)
instead override ``install(ctx)`` and may reuse a backend via
``ctx.package_manager(id)`` -- so there is no per-OS helper module.
"""

import logging
import os
import pathlib
import shutil
import subprocess

from installers.managers import Deb, PackageManager, Script


logger = logging.getLogger("dotfiles")


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
        # Official convenience installer via the scripts manager (avoids the
        # `curl | sh` pipe that masks a curl failure behind sh's exit code).
        ctx.package_manager("scripts").install(
            ctx, Script("https://get.docker.com/", interpreter="sh")
        )
        user = os.environ.get("USER", os.environ.get("LOGNAME"))
        ctx.run_command(["sudo", "groupadd", "-f", "docker"])
        if user:
            ctx.run_command(["sudo", "usermod", "-aG", "docker", user])
        # NVIDIA driver PPA + DKMS toolchain for GPU containers.
        ctx.run_command(["sudo", "add-apt-repository", "-y", "ppa:graphics-drivers/ppa"])
        ctx.run_command(["sudo", "apt-get", "update"])
        ctx.run_command(["sudo", "apt-get", "install", "-y", "dkms", "build-essential"])


class DockerRootless(OptionalComponent):
    name = "docker-rootless"
    description = "Docker (rootless)"
    groups = frozenset({"all"})
    installs = {"scripts": Script("https://get.docker.com/rootless", interpreter="sh")}


class SoftwareProperties(OptionalComponent):
    name = "software-properties"
    description = "software-properties-common (provides add-apt-repository)"
    groups = frozenset({"all"})
    installs = {"apt": "software-properties-common"}


class Cuda(OptionalComponent):
    name = "cuda"
    description = "CUDA Toolkit"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    def install(self, ctx):
        # NVIDIA's local-repo installer: pin the repo, register it via the
        # local-installer .deb, trust its keyring, then apt-install the toolkit.
        ctx.run_command(
            "wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-ubuntu2404.pin",
            shell=True,
        )
        ctx.run_command(
            "sudo mv cuda-ubuntu2404.pin /etc/apt/preferences.d/cuda-repository-pin-600",
            shell=True,
        )
        deb_name = "cuda-repo-ubuntu2404-12-6-local_12.6.2-560.35.03-1_amd64.deb"
        url = f"https://developer.download.nvidia.com/compute/cuda/12.6.2/local_installers/{deb_name}"
        deb_path = pathlib.Path(f"/tmp/{deb_name}")
        ctx.run_command(f"wget {url} -O {deb_path}", shell=True)
        ctx.run_command(["sudo", "dpkg", "-i", str(deb_path)])
        ctx.run_command(
            "sudo cp /var/cuda-repo-ubuntu2404-12-6-local/cuda-*-keyring.gpg /usr/share/keyrings/",
            shell=True,
        )
        ctx.run_command(["sudo", "apt-get", "update"])
        ctx.run_command(["sudo", "apt-get", "-y", "install", "cuda-toolkit-12-6"])
        if deb_path.exists():
            deb_path.unlink()


class Llvm(OptionalComponent):
    name = "llvm"
    description = "LLVM"
    supported_os = ("debian", "ubuntu")
    groups = frozenset({"all"})

    VERSION = "18"

    def install(self, ctx):
        # apt.llvm.org's official installer (a bash script), run via the scripts
        # manager with `<version> all` to pull the full toolchain.
        ctx.package_manager("scripts").install(
            ctx,
            Script(
                "https://apt.llvm.org/llvm.sh",
                interpreter="bash",
                args=[self.VERSION, "all"],
            ),
        )

        # Wire the versioned binaries onto the unversioned names via
        # update-alternatives, with clang as the primary + its tools as slaves.
        version = self.VERSION
        slaves = [
            "clang++",
            "clang-cpp",
            "clangd",
            "clang-format",
            "clang-tidy",
            "clang-cl",
            "clang-query",
            "clang-rename",
        ]
        cmd = [
            "update-alternatives",
            "--install",
            "/usr/bin/clang",
            "clang",
            f"/usr/bin/clang-{version}",
            "100",
        ]
        for name in slaves:
            cmd.extend(["--slave", f"/usr/bin/{name}", name, f"/usr/bin/{name}-{version}"])
        ctx.run_command(cmd)

        # Register any other `*-<version>` binaries whose unversioned name is
        # still free (e.g. llvm tools), so they resolve too.
        bin_dir = pathlib.Path("/usr/bin")
        if bin_dir.exists():
            for file in bin_dir.glob(f"*-{version}"):
                base_name = file.name.replace(f"-{version}", "")
                if not (bin_dir / base_name).exists():
                    ctx.run_command(
                        [
                            "update-alternatives",
                            "--install",
                            f"/usr/bin/{base_name}",
                            base_name,
                            str(file),
                            "1",
                        ]
                    )


class MacBrew(OptionalComponent):
    name = "mac-brew"
    description = "Homebrew packages"
    supported_os = ("darwin",)
    groups = frozenset({"all"})

    FORMULAE = (
        "coreutils",
        "moreutils",
        "findutils",
        "gnu-sed",
        "wget",
        "rsync",
        "vim",
        "grep",
        "openssh",
        "xmake",
        "tmux",
        "thefuck",
        "tldr",
        "ack",
        "git",
        "git-lfs",
        "gs",
        "lua",
        "lynx",
        "p7zip",
        "pigz",
        "pv",
        "rename",
        "rlwrap",
        "ssh-copy-id",
        "tree",
        "vbindiff",
        "zopfli",
    )

    CASKS = (
        "rsyncui",
        "visual-studio-code",
        "microsoft-edge",
        "termius",
        "texlive",
        "qspace-pro",
        "fliqlo",
    )

    def install(self, ctx):
        # Refresh Homebrew and upgrade what's already there before installing.
        ctx.run_command(["brew", "update"])
        ctx.run_command(["brew", "upgrade"])

        for formula in self.FORMULAE:
            ctx.run_command(["brew", "install", formula])

        # Symlink sha256sum -> coreutils' gsha256sum.
        try:
            brew_prefix = subprocess.run(
                ["brew", "--prefix"], capture_output=True, text=True, check=True
            ).stdout.strip()
            ctx.run_command(
                f"ln -sf {brew_prefix}/bin/gsha256sum {brew_prefix}/bin/sha256sum",
                shell=True,
            )
        except Exception as e:
            logger.warning(f"Failed to set up sha256sum symlink: {e}")

        # Nerd Font installer (getnf), via the scripts manager.
        ctx.package_manager("scripts").install(
            ctx,
            Script(
                "https://raw.githubusercontent.com/HernandoR/getnf/master/install.sh",
                interpreter="sh",
            ),
        )

        for cask in self.CASKS:
            ctx.run_command(["brew", "install", "--cask", cask])

        # Remove outdated versions from the cellar.
        ctx.run_command(["brew", "cleanup"])


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
