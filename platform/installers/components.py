"""Linux system-level install components (ADR-0003 / ADR-0007).

Home Manager now owns all user-level tooling and dotfiles declaratively. What
remains here is the *system-level* software Home Manager cannot install on a
non-NixOS host — Docker's daemon, CUDA, the NVIDIA driver, LLVM's
update-alternatives, apt system packages. These are opt-in and run by
``platform/setup.py`` after the Home Manager switch.

Each component is declarative-first (``installs = {manager_id: spec}``, resolved
through the backend the orchestrator picks — see :mod:`installers.managers`) with
an imperative ``install(ctx)`` override for multi-step installs.
"""

import logging
import os
import pathlib
import shutil

from installers.managers import Deb, PackageManager, Script  # noqa: F401

logger = logging.getLogger("dotfiles")


class Component:
    """Shared base: the ADR-0003 install machinery."""

    name = ""
    description = ""
    supported_os = None  # explicit list for imperative-override components
    installs = {}  # {manager_id: spec}; empty => override install() below

    def effective_supported_os(self):
        if not self.installs:
            return self.supported_os
        oses = set()
        for manager_id in self.installs:
            if not PackageManager.exists(manager_id):
                continue
            manager_os = PackageManager.get(manager_id).supported_os
            if manager_os is None:
                return None
            oses.update(manager_os)
        return tuple(sorted(oses)) if oses else None

    def applicable(self, ctx):
        supported = self.effective_supported_os()
        return supported is None or ctx.os_type in supported

    def install(self, ctx):
        manager = ctx.select_manager(self.installs)
        if manager is None:
            raise RuntimeError(f"No package manager available for {self.name} on {ctx.os_type}")
        manager.install(ctx, self.installs[manager.id])

    def run(self, ctx):
        if not self.applicable(ctx):
            logger.info("%s is not applicable on %s. Skipping.", self.description, ctx.os_type)
            return
        logger.info("Installing %s...", self.description)
        self.install(ctx)


class OptionalComponent(Component):
    """User-selected system component; self-registers by ``name``."""

    _registry = {}
    groups = frozenset()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            OptionalComponent._registry[cls.name] = cls

    @classmethod
    def names(cls):
        return list(cls._registry.keys())

    @classmethod
    def alias_groups(cls):
        groups = {}
        for name, comp in cls._registry.items():
            for group in comp.groups:
                groups.setdefault(group, []).append(name)
        return groups

    @classmethod
    def resolve(cls, raw):
        """Resolve a comma-separated spec to a de-duplicated, ordered component
        list. Accepts individual names, alias groups, and the special ``all``
        keyword (every registered component). Mutually exclusive components are
        reconciled (rootless Docker wins over rootful)."""
        groups = cls.alias_groups()
        requested = set()
        for part in raw.split(","):
            part = part.strip().lower()
            if not part:
                continue
            if part == "all":
                requested.update(cls._registry.keys())
            elif part in groups:
                requested.update(groups[part])
            elif part in cls._registry:
                requested.add(part)
            else:
                logger.warning("Unknown component: %s", part)
        if "docker" in requested and "docker-rootless" in requested:
            requested.discard("docker")
            logger.info("docker + docker-rootless both selected; keeping rootless docker")
        return [name for name in cls._registry if name in requested]

    @classmethod
    def get(cls, name):
        return cls._registry[name]()


class SoftwareProperties(OptionalComponent):
    name = "software-properties"
    description = "software-properties-common (provides add-apt-repository)"
    installs = {"apt": "software-properties-common"}


class Docker(OptionalComponent):
    name = "docker"
    description = "Docker Engine"
    supported_os = ("debian", "ubuntu")

    def install(self, ctx):
        # Official convenience installer via the scripts backend (avoids a
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
    supported_os = ("debian", "ubuntu")  # explicit: the scripts backend is all-OS, but this is Linux-only

    def install(self, ctx):
        ctx.package_manager("scripts").install(
            ctx, Script("https://get.docker.com/rootless", interpreter="sh")
        )


class Cuda(OptionalComponent):
    name = "cuda"
    description = "CUDA Toolkit"
    supported_os = ("debian", "ubuntu")

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


class Nvidia(OptionalComponent):
    name = "nvidia"
    description = "NVIDIA driver + container toolkit"
    supported_os = ("debian", "ubuntu")

    def install(self, ctx):
        ctx.run_command(["sudo", "add-apt-repository", "-y", "ppa:graphics-drivers/ppa"])
        ctx.run_command(["sudo", "apt-get", "update"])
        ctx.run_command(["sudo", "apt-get", "install", "-y", "dkms", "build-essential", "ubuntu-drivers-common"])
        ctx.run_command("sudo ubuntu-drivers autoinstall || sudo apt-get install -y nvidia-driver-560", shell=True)
        # container toolkit so docker can use the GPU
        ctx.run_command(
            "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | "
            "sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg",
            shell=True,
        )
        ctx.run_command(
            "curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | "
            "sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | "
            "sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null",
            shell=True,
        )
        ctx.run_command(["sudo", "apt-get", "update"])
        ctx.run_command(["sudo", "apt-get", "install", "-y", "nvidia-container-toolkit"])
        ctx.run_command("sudo nvidia-ctk runtime configure --runtime=docker || true", shell=True)


class Llvm(OptionalComponent):
    name = "llvm"
    description = "LLVM"
    supported_os = ("debian", "ubuntu")

    VERSION = "18"

    def install(self, ctx):
        ctx.package_manager("scripts").install(
            ctx,
            Script("https://apt.llvm.org/llvm.sh", interpreter="bash", args=[self.VERSION, "all"]),
        )
        version = self.VERSION
        slaves = [
            "clang++", "clang-cpp", "clangd", "clang-format", "clang-tidy",
            "clang-cl", "clang-query", "clang-rename",
        ]
        cmd = [
            "update-alternatives", "--install", "/usr/bin/clang", "clang",
            f"/usr/bin/clang-{version}", "100",
        ]
        for name in slaves:
            cmd.extend(["--slave", f"/usr/bin/{name}", name, f"/usr/bin/{name}-{version}"])
        ctx.run_command(cmd)
        bin_dir = pathlib.Path("/usr/bin")
        if bin_dir.exists() and not ctx.dry_run:
            for file in bin_dir.glob(f"*-{version}"):
                base_name = file.name.replace(f"-{version}", "")
                if not (bin_dir / base_name).exists():
                    ctx.run_command(
                        ["update-alternatives", "--install", f"/usr/bin/{base_name}",
                         base_name, str(file), "1"]
                    )


class Homebrew(OptionalComponent):
    name = "brew"
    description = "Homebrew (macOS) — the package manager only, no formulae/casks"
    supported_os = ("darwin",)

    def install(self, ctx):
        # User-level CLI tools come from nixpkgs; this installs Homebrew *itself*
        # so GUI apps can be added later with `brew install --cask …`. Idempotent.
        if shutil.which("brew") or pathlib.Path("/opt/homebrew/bin/brew").exists():
            logger.info("Homebrew already installed; skipping.")
            return
        if os.environ.get("DOTFILE_NETWORK_ENV") == "CN":
            # BFSU mirror, non-interactive (faithful to the old install_homebrew).
            ctx.run_command(
                ["git", "clone", "--depth=1",
                 "https://mirrors.bfsu.edu.cn/git/homebrew/install.git", "/tmp/brew-install"]
            )
            ctx.run_command(
                "export HOMEBREW_API_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles/api && "
                "export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles && "
                "export HOMEBREW_BREW_GIT_REMOTE=https://mirrors.bfsu.edu.cn/git/homebrew/brew.git && "
                "export NONINTERACTIVE=1 && /bin/bash /tmp/brew-install/install.sh",
                shell=True,
            )
            ctx.run_command(["rm", "-rf", "/tmp/brew-install"])
        else:
            # Official installer via the scripts backend (download-then-run).
            ctx.package_manager("scripts").install(
                ctx,
                Script(
                    "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
                    interpreter="bash",
                    env={"NONINTERACTIVE": "1"},
                ),
            )


def main():
    """Print all available system components."""
    print("Available system components (run via: platform/setup.py --system <list>)")
    print("=" * 60)
    for name in OptionalComponent.names():
        comp = OptionalComponent.get(name)
        supported = comp.effective_supported_os()
        os_str = ", ".join(supported) if supported else "all OS"
        print(f"  {name:18} {comp.description}  [{os_str}]")


if __name__ == "__main__":
    main()
