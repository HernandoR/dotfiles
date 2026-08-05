"""Install components: necessary (defaulted-on) and optional (user-selected).

Both kinds share the install machinery on :class:`Component` (see ADR-0003): a
component is declarative-first -- it lists ``installs = {manager_id: spec}`` and
the base resolves it through the backend the orchestrator picks (see
:mod:`installers.managers`) -- with an imperative ``install(ctx)`` override for
multi-step installs (docker post-setup, the nvm + pnpm dance) that may reuse a
backend via ``ctx.package_manager(id)``. There is no per-OS helper module.

The two kinds differ only in lifecycle (see ADR-0004):

- :class:`NecessaryComponent` -- always-run shell tooling (oh-my-zsh, fzf,
  starship). The install order is correctness-critical, so the catalog is the
  explicit ``NECESSARY`` tuple at the bottom of this module rather than
  registration order; these are not user-selectable.
- :class:`OptionalComponent` -- self-registering, user-selected via
  ``--optional-components`` / the ``DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS`` env
  var. Order is incidental, so registration order drives ``resolve()``.
"""

import logging
import os
import pathlib
import shutil
import subprocess
import sys

from installers.managers import Deb, PackageManager, Script


logger = logging.getLogger("dotfiles")


class Component:
    """Shared base for install components -- the ADR-0003 install machinery.

    Carries the declarative ``installs`` table and its resolution, plus the
    imperative ``install(ctx)`` escape hatch. Subclasses add their own lifecycle
    (an ordered tuple for necessary components, a self-registering catalog for
    optional ones); registration is intentionally *not* here.
    """

    name = ""
    description = ""
    supported_os = None  # explicit list for imperative-override components
    installs = {}  # {manager_id: spec}; empty => override install() below

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


class NecessaryComponent(Component):
    """Defaulted-on shell tooling installed on every run.

    Not user-selectable and not self-registering: install order is
    correctness-critical, so the catalog is the explicit ``NECESSARY`` tuple at
    the bottom of this module (see ADR-0004 -- a reordering must be a one-line
    diff, not a subtle class move). Subclasses inherit the install machinery
    from :class:`Component`; each of the current three is an imperative
    multi-step ``install(ctx)`` override.

    Per ADR-0004, necessary components install binaries/frameworks only -- shell
    rc files belong to the dotfiles migration phase, so the repo's ``.zshrc``
    (which sources these tools) stays canonical.
    """


class OptionalComponent(Component):
    """User-selected install component; self-registers by ``name``.

    Declaring a subclass with a ``name`` makes it available via
    ``--optional-components`` and ``DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS``.
    Order is incidental, so registration order drives ``resolve()``.
    """

    _registry = {}

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


# Home paths NOT deployed from staging by the generic symlink walk (ADR-0005).
# Under the install-driven model the Claude post-setup rebuilds ~/.claude fresh
# on each machine (plugins, MCP servers, agent tooling), so the migration phase
# (see main.migrate_dotfiles) must NOT symlink staging's stale .claude state in.
CLAUDE_MANAGED_PATHS = (".claude", ".claude.json")

# agent-skillset marketplace + the plugins to install from it (no bulk-install
# command exists yet, so they are enumerated).
AGENT_SKILLSET_REPO = "hernandor/agent-skillset"
AGENT_SKILLSET_MARKET = "agent-skillset"
AGENT_SKILLSET_PLUGINS = ("discuss", "implement", "dev_loop", "fetch_external_knowledge")

# MCP servers managed via Smithery (slug -> smithery package). Smithery wires
# them into Claude's MCP config; needs Node (a necessary component) for npx.
SMITHERY_MCP_SERVERS = (
    "@upstash/context7-mcp",            # context7: up-to-date library docs
    "@modelcontextprotocol/server-memory",  # persistent knowledge-graph memory
)


class ClaudeCode(OptionalComponent):
    name = "claude"
    description = "Claude Code CLI + plugins, MCP servers, and agent tooling"
    groups = frozenset({"all"})
    # Official native installer; auto-updates in the background.
    # npm fallback: npm install -g @anthropic-ai/claude-code
    installs = {"scripts": Script("https://claude.ai/install.sh", interpreter="bash")}

    # Deferred setup is written here and sourced by ~/.extra on first login.
    DEFERRED_SETUP = pathlib.Path.home() / ".local" / "share" / "dotfiles" / "post-login-setup.sh"

    def install(self, ctx):
        # Install-driven post-setup (ADR-0005): rebuild the Claude config on each
        # machine rather than carrying an opaque ~/.claude across machines.
        #
        # Split into two tiers:
        #   Automated (now):   CLI binary + codegraph — fully non-interactive.
        #   Deferred (login):  plugins, MCP servers, Lark — all need account
        #                      auth or browser OAuth that blocks a headless run.
        #
        # The deferred script is written to DEFERRED_SETUP and picked up by the
        # ~/.extra hook on the user's first interactive login.
        super().install(ctx)             # 1. CLI binary (non-interactive)
        self._install_codegraph(ctx)     # 2. codegraph + Claude MCP wiring (--yes)
        self._write_deferred_setup(ctx)  # 3. schedule interactive steps for first login

    def _shell(self, ctx, cmd, check=False):
        """Run ``cmd`` in a shell that has nvm loaded and ~/.local/bin on PATH."""
        nvm_dir = os.environ.get("NVM_DIR") or str(pathlib.Path.home() / ".nvm")
        prelude = (
            f'export NVM_DIR="{nvm_dir}"; '
            '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"; '
            'export PATH="$HOME/.local/bin:$PATH"; '
        )
        ctx.run_command(["bash", "-c", prelude + cmd], check=check)

    def _install_codegraph(self, ctx):
        # Reuse the standalone installer, then wire CodeGraph's MCP into Claude
        # non-interactively (--yes). `codegraph init` is per-project and is
        # intentionally not run here (a bootstrap has no project context).
        Codegraph().install(ctx)
        self._shell(ctx, "codegraph install --target=claude --yes")

    def _write_deferred_setup(self, ctx):
        """Write the interactive post-login steps to DEFERRED_SETUP.

        The script is sourced automatically by the ~/.extra hook on first
        interactive login and self-removes on completion. Steps run without
        set -e so a failed auth step does not skip the rest.
        """
        nvm_dir = os.environ.get("NVM_DIR") or str(pathlib.Path.home() / ".nvm")

        plugin_lines = [
            f"claude plugin marketplace add {AGENT_SKILLSET_REPO} || true",
            *(
                f"claude plugin install {p}@{AGENT_SKILLSET_MARKET} --scope user || true"
                for p in AGENT_SKILLSET_PLUGINS
            ),
        ]
        mcp_lines = [
            f"npx -y @smithery/cli@latest install {pkg} --client claude || true"
            for pkg in SMITHERY_MCP_SERVERS
        ]

        script = (
            "#!/usr/bin/env bash\n"
            "# Claude Code post-login setup — generated by the dotfiles bootstrap.\n"
            "# Sourced automatically by ~/.extra on first interactive login.\n"
            "# To re-run manually: bash ~/.local/share/dotfiles/post-login-setup.sh\n"
            "\n"
            f'export NVM_DIR="{nvm_dir}"\n'
            '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
            'export PATH="$HOME/.local/bin:$PATH"\n'
            "\n"
            'echo ""\n'
            'echo "==> Claude post-login setup (dotfiles bootstrap)"\n'
            'echo ""\n'
            "\n"
            "# 1. agent-skillset marketplace and plugins\n"
            + "\n".join(plugin_lines)
            + "\n\n"
            "# 2. MCP servers via Smithery (browser OAuth may open)\n"
            + "\n".join(mcp_lines)
            + "\n\n"
            "# 3. Lark CLI agent skills (Lark/Feishu account login required)\n"
            "npx -y @larksuite/cli@latest install || true\n"
            "\n"
            'echo ""\n'
            'echo "==> Claude post-login setup done."\n'
            'rm -f "${BASH_SOURCE[0]}"\n'
        )

        if ctx.dry_run:
            logger.info(f"[DRY-RUN] Would write deferred setup to {self.DEFERRED_SETUP}")
            return

        self.DEFERRED_SETUP.parent.mkdir(parents=True, exist_ok=True)
        self.DEFERRED_SETUP.write_text(script)
        self.DEFERRED_SETUP.chmod(0o755)
        logger.info(
            f"Deferred Claude setup written to {self.DEFERRED_SETUP}. "
            "It will run on your first interactive login (via ~/.extra)."
        )


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


class GitHubCLI(OptionalComponent):
    name = "gh"
    description = "GitHub CLI (gh)"
    groups = frozenset({"all"})
    # brew formula on macOS; pinned release .deb on Debian (gh isn't reliably in
    # the default apt repos). Bump the version in the URL deliberately.
    installs = {
        "brew": "gh",
        "apt": Deb(
            "https://github.com/cli/cli/releases/download/v2.96.0/"
            "gh_2.96.0_linux_amd64.deb"
        ),
    }


class Jujutsu(OptionalComponent):
    name = "jj"
    description = "Jujutsu (jj) — Git-compatible version control system"
    supported_os = None  # brew on macOS; prebuilt musl binary on Linux
    groups = frozenset({"all"})

    # Pinned release — bump deliberately (cf. Bottom / CUDA / nvm). jj ships no
    # apt package or official installer script, so Linux uses the statically
    # linked musl release tarball.
    VERSION = "v0.43.0"

    def install(self, ctx):
        # macOS: the brew formula is the upstream-recommended path.
        if ctx.os_type == "darwin":
            ctx.package_manager("brew").install(ctx, "jj")
            return

        # Linux: fetch the musl tarball (portable across distros) and drop its
        # `jj` binary onto ~/.local/bin — already on PATH via sources/root/.path.
        # The archive holds `./jj` at the top level (plus README/LICENSE); pull
        # out only the binary.
        tarball = f"jj-{self.VERSION}-x86_64-unknown-linux-musl.tar.gz"
        url = f"https://github.com/jj-vcs/jj/releases/download/{self.VERSION}/{tarball}"
        tar_path = pathlib.Path("/tmp") / tarball
        bin_dir = pathlib.Path.home() / ".local" / "bin"
        if not ctx.dry_run:
            bin_dir.mkdir(parents=True, exist_ok=True)
        ctx.run_command(["wget", url, "-O", str(tar_path)])
        ctx.run_command(["tar", "-xzf", str(tar_path), "-C", str(bin_dir), "./jj"])
        if not ctx.dry_run:
            tar_path.unlink(missing_ok=True)


class Node(NecessaryComponent):
    # Necessary (always-run): the Claude post-setup uses npx for Smithery, and
    # several optional components assume Node, so it must exist before phase 4.
    # Necessary components leave ``name`` empty and rely on ``description``
    # (ADR-0004); they also must not write shell rc files -- the repo's .zshrc
    # already sources NVM_DIR, so the nvm installer runs with PROFILE=/dev/null.
    description = "Node.js (nvm + LTS) and pnpm"
    supported_os = None  # nvm's install script covers macOS, Linux, and WSL

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
        # PROFILE=/dev/null: nvm must not append its source block to shell rc
        # files (ADR-0004) -- the repo's linked .zshrc already wires NVM_DIR.
        ctx.package_manager("scripts").install(
            ctx, Script(install_url, interpreter="bash", env={"PROFILE": "/dev/null"})
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


class OhMyZsh(NecessaryComponent):
    description = "Oh My Zsh (+ antigen, zsh plugins)"

    def install(self, ctx):
        if not pathlib.Path("./sources").is_dir():
            logger.error("Please execute this script in the dotfiles directory")
            sys.exit(1)

        output_dir = pathlib.Path("./output")
        if not ctx.dry_run:
            output_dir.mkdir(exist_ok=True)

        github_reachable = ctx.is_github_reachable()
        logger.info(
            f"GitHub is {'reachable' if github_reachable else 'not reachable, using gitee'}"
        )

        logger.info("Updating submodules...")
        ctx.run_command(["git", "submodule", "init"])
        ctx.run_command(["git", "submodule", "update"])

        interactive = ctx.options.get("interactive", False)
        oh_my_zsh_path = pathlib.Path.home() / ".oh-my-zsh" / "oh-my-zsh.sh"
        if oh_my_zsh_path.is_file():
            logger.info("oh-my-zsh is already installed")
        else:
            oh_my_zsh_dir = pathlib.Path.home() / ".oh-my-zsh"
            if oh_my_zsh_dir.is_dir() and not ctx.dry_run:
                logger.info("Backing up existing omz dir...")
                shutil.rmtree(pathlib.Path.home() / "oh-my-zsh.bkp", ignore_errors=True)
                shutil.move(
                    str(oh_my_zsh_dir), str(pathlib.Path.home() / "oh-my-zsh.bkp")
                )

            logger.info("Installing oh-my-zsh...")
            install_url = (
                "https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh"
                if github_reachable
                else "https://gitee.com/mirrors/oh-my-zsh/raw/master/tools/install.sh"
            )
            install_script = output_dir / "install.sh"
            ctx.run_command(["curl", "-fsSL", install_url, "-o", str(install_script)])
            install_args = [] if interactive else ["--unattended"]
            # KEEP_ZSHRC=yes installs the framework without writing ~/.zshrc --
            # the repo's .zshrc, linked by the migration phase, stays canonical
            # (ADR-0004 §4).
            ctx.run_command(
                ["sh", str(install_script)] + install_args,
                env={"KEEP_ZSHRC": "yes"},
            )
            if not ctx.dry_run:
                install_script.unlink(missing_ok=True)

        logger.info("Installing antigen...")
        if not ctx.dry_run:
            ctx.run_command(
                [
                    "curl",
                    "-fsSL",
                    "https://git.io/antigen",
                    "-o",
                    str(pathlib.Path.home() / "antigen.zsh"),
                ]
            )

        logger.info("Copying zsh plugins config...")
        if not ctx.dry_run:
            custom_plugins = pathlib.Path.home() / ".oh-my-zsh" / "custom" / "plugins"

            zsh_auto_dir = custom_plugins / "zsh-autosuggestions"
            zsh_auto_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                "./sources/zsh_plugins/zsh-autosuggestions.plugin.zsh",
                str(zsh_auto_dir / "zsh-autosuggestions.plugin.zsh"),
            )

            zsh_syn_dir = custom_plugins / "zsh-syntax-highlighting"
            zsh_syn_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                "./sources/zsh_plugins/zsh-syntax-highlighting.plugin.zsh",
                str(zsh_syn_dir / "zsh-syntax-highlighting.plugin.zsh"),
            )


class Fzf(NecessaryComponent):
    description = "fzf (fuzzy finder)"

    def install(self, ctx):
        fzf_bin = pathlib.Path.home() / ".fzf" / "bin" / "fzf"
        if fzf_bin.is_file():
            logger.info("fzf is already installed")
            return

        fzf_dir = pathlib.Path.home() / ".fzf"
        github_reachable = ctx.is_github_reachable()
        fzf_url = (
            "https://github.com/junegunn/fzf.git"
            if github_reachable
            else "https://gitee.com/mirrors/fzf.git"
        )
        ctx.run_command(["git", "clone", "--depth", "1", fzf_url, str(fzf_dir)])
        # --no-update-rc: fzf must not touch shell rc files; the repo's .zshrc
        # sources fzf itself (ADR-0004 §4).
        ctx.run_command([str(fzf_dir / "install"), "--all", "--no-update-rc"])


class Starship(NecessaryComponent):
    description = "Starship prompt"

    def install(self, ctx):
        # Plain download-run-cleanup: reuse the scripts backend (ADR-0003 §5)
        # rather than re-implementing the temp-file dance. The installer drops a
        # binary on PATH and does not edit rc files.
        interactive = ctx.options.get("interactive", False)
        ctx.package_manager("scripts").install(
            ctx,
            Script(
                "https://starship.rs/install.sh",
                interpreter="sh",
                args=[] if interactive else ["-y"],
            ),
        )


class Mergiraf(NecessaryComponent):
    # Necessary (always-run): the repo's .gitconfig registers `mergiraf` as a
    # merge driver and .gitattributes routes many file types through it (see
    # sources/root/.gitconfig, .gitattributes), so the binary must exist on
    # every machine or those merges break. Necessary components leave ``name``
    # empty and rely on ``description`` (ADR-0004); this one only drops a binary
    # on PATH — the driver config lives in the repo's linked .gitconfig.
    description = "Mergiraf (syntax-aware git merge driver)"
    supported_os = None  # brew on macOS; prebuilt musl binary on Linux

    # Pinned release — bump deliberately (cf. Jujutsu / Bottom / nvm). Mergiraf
    # ships no apt package or installer script, so Linux uses the statically
    # linked musl release tarball from Codeberg.
    VERSION = "v0.17.0"

    def install(self, ctx):
        # Idempotent: unlike optional components this runs on every bootstrap,
        # so skip the download/brew step when mergiraf is already on PATH.
        if shutil.which("mergiraf"):
            logger.info("mergiraf already installed; skipping.")
            return

        # macOS: the brew formula is the upstream-recommended path.
        if ctx.os_type == "darwin":
            ctx.package_manager("brew").install(ctx, "mergiraf")
            return

        # Linux: fetch the musl tarball (portable across distros) and drop its
        # `mergiraf` binary onto ~/.local/bin — already on PATH via
        # sources/root/.path. The archive holds `mergiraf` at the top level.
        tarball = "mergiraf_x86_64-unknown-linux-musl.tar.gz"
        url = (
            "https://codeberg.org/mergiraf/mergiraf/releases/download/"
            f"{self.VERSION}/{tarball}"
        )
        tar_path = pathlib.Path("/tmp") / tarball
        bin_dir = pathlib.Path.home() / ".local" / "bin"
        if not ctx.dry_run:
            bin_dir.mkdir(parents=True, exist_ok=True)
        ctx.run_command(["wget", url, "-O", str(tar_path)])
        ctx.run_command(["tar", "-xzf", str(tar_path), "-C", str(bin_dir), "mergiraf"])
        if not ctx.dry_run:
            tar_path.unlink(missing_ok=True)


# Ordered catalog of always-run shell tooling. The order is correctness-critical
# and lives here as an explicit, reviewable tuple (ADR-0004 §3).
NECESSARY = (OhMyZsh, Fzf, Starship, Node, Mergiraf)


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
