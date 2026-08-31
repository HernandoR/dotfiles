#!/usr/bin/env python3
"""platform/bootstrap.py — the whole imperative bootstrap (ADR-0007), in Python.

Home Manager owns the user environment declaratively; this orchestrates what it
cannot do on a non-NixOS host, split around the Home Manager switch:

    pre-HM :  privilege → prereqs → install Lix → configure nix (+CN mirror) →
              home-manager build + activate
    post-HM:  login shell → mise runtimes → coding agents → system components
              (the step functions live in setup.py, imported and run in-process)

The shell's only job is `bootstrap.sh`, a thin launcher that guarantees a
python3 and execs this file (stdlib-only, >=3.9 — the system python3 of every
supported OS family). Everything that used to live in platform/bootstrap.sh,
platform/lib.sh and platform/nix-cn.sh lives here now.

Privilege model (Ctx.priv, detected live):
    root — run privileged steps directly (no sudo)
    sudo — run privileged steps via sudo
    none — skip everything needing sudo; do only the user-level nix/HM steps.
           If nix is not installed (and can't be, without privilege) → exit
           cleanly.

Clearance (ADR-0010): on an interactive terminal the whole plan is printed
first — what gets installed, from which network/mirrors, which config is
written or linked — and cleared ONCE. A run with no terminal (CI, container
build, cron) never asks; --yes/-y skips the prompt but still prints the plan.
"""
import argparse
import logging
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup  # noqa: E402  (platform/setup.py — the post-HM half)
from installers.context import ASSUME_YES_ENV, Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

PLATFORM_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = PLATFORM_DIR.parent
HOME = pathlib.Path.home()

CERNET = "https://mirrors.cernet.edu.cn/nix-channels/store"
NETWORK_MARKER = HOME / ".config/dotfiles/network-env"


def die(msg):
    print(f"\033[1;31merror:\033[0m {msg}", file=sys.stderr)
    raise SystemExit(1)


def log(msg):
    print(f"\033[1;34m==>\033[0m {msg}")


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m {msg}", file=sys.stderr)


# ---- small facts about the host ----------------------------------------------


def have_nix():
    return bool(shutil.which("nix")) or os.access(
        "/nix/var/nix/profiles/default/bin/nix", os.X_OK
    )


def has_init_system():
    """True if a service manager can run the multi-user nix-daemon (systemd on
    Linux, launchd on macOS). Bare `docker run` containers have none."""
    if sys.platform == "darwin":
        return True
    return pathlib.Path("/run/systemd/system").is_dir()


def load_nix_path():
    """Make nix (and, post-switch, the HM profile incl. zsh) callable in this
    process — the Python port of sourcing nix-daemon.sh/nix.sh, which mostly
    means PATH plus the SSL cert bundle nix's fetchers need."""
    for p in (HOME / ".nix-profile/bin", pathlib.Path("/nix/var/nix/profiles/default/bin")):
        _prepend_path(str(p))
    if not os.environ.get("NIX_SSL_CERT_FILE"):
        for cand in (
            "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu/arch/alpine
            "/etc/ssl/ca-bundle.pem",  # openSUSE
            "/etc/ssl/certs/ca-bundle.crt",  # Fedora/RHEL
            "/nix/var/nix/profiles/default/etc/ssl/certs/ca-bundle.crt",
        ):
            if pathlib.Path(cand).exists():
                os.environ["NIX_SSL_CERT_FILE"] = cand
                break


def _prepend_path(entry):
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if entry not in parts:
        os.environ["PATH"] = os.pathsep.join([entry, *parts])


# ---- prerequisites (curl/git/xz before nix exists) ----------------------------

# OS family -> native package-manager command, or None when this repo has no
# backend for it. The single map both the plan and the run read, so the plan
# cannot promise an install the run then fails to perform. Its post-HM sibling
# is the PackageManager registry in installers/managers.py, keyed the same way.
# An unrecognised family must be SKIPPED, never handed apt-get (that guess is
# what once ran apt on an Amazon Linux host).
_PKG_MANAGERS = {
    "debian": "apt-get",
    "ubuntu": "apt-get",
    "fedora": "_dnf_or_yum",
    "rhel": "_dnf_or_yum",
    "amzn": "_dnf_or_yum",
    "suse": "zypper",
    "arch": "pacman",
    "alpine": "apk",
    "darwin": "brew",
}

_PREREQ_PACKAGES = {
    "debian": "curl git xz-utils ca-certificates",
    "ubuntu": "curl git xz-utils ca-certificates",
    "fedora": "curl git xz ca-certificates",
    "rhel": "curl git xz ca-certificates",
    "amzn": "curl git xz ca-certificates",
    "suse": "curl git xz ca-certificates",
    "arch": "curl git xz ca-certificates",
    "alpine": "curl git xz ca-certificates",
}


def os_pkg_manager(os_type):
    pm = _PKG_MANAGERS.get(os_type)
    if pm == "_dnf_or_yum":  # AL2023/Fedora/RHEL9 ship dnf; AL2 and RHEL7 only yum
        return "dnf" if shutil.which("dnf") else "yum"
    return pm


def prereqs_missing():
    """curl or git absent — the only two this prelude actually needs before nix
    exists. Shared by the plan and the run so they cannot disagree."""
    return not (shutil.which("curl") and shutil.which("git"))


def plan_prereqs(plan, os_type):
    if os_type == "darwin":
        if not shutil.which("git"):
            plan.install("Xcode command line tools (for git)", priv=True)
        return
    if not prereqs_missing():
        return
    pm, pkgs = os_pkg_manager(os_type), _PREREQ_PACKAGES.get(os_type)
    if pm and pkgs and pm != "brew":
        plan.install(f"prerequisites via {pm}: {pkgs}", priv=True)
    else:
        plan.fact("skipping", f"prerequisite install: no package-manager backend for "
                              f"'{os_type}' (install curl/git/xz yourself)")


def ensure_prereqs(ctx):
    """The few tools needed before nix exists. Needs privilege; the caller
    guards. An OS family with no backend is skipped with a warning rather than
    being handed to a package manager that is not there."""
    if ctx.os_type == "darwin":
        if not shutil.which("git"):
            ctx.run_command("xcode-select --install || true", shell=True, check=False)
        if not shutil.which("curl"):
            die("curl is required")
        return
    if not prereqs_missing():
        return
    pm, pkgs = os_pkg_manager(ctx.os_type), _PREREQ_PACKAGES.get(ctx.os_type)
    if not pm or not pkgs or pm == "brew":
        warn(f"no package-manager backend for OS '{ctx.os_type}': skipping the prereq install.")
        warn("install curl, git and xz yourself if the nix install below fails.")
        return
    log(f"installing prerequisites via {pm} (curl git xz)")
    pkg_list = pkgs.split()
    if pm == "apt-get":
        ctx.run_command(["apt-get", "update", "-qq"], with_sudo=True)
        ctx.run_command(["apt-get", "install", "-y", "-qq", *pkg_list], with_sudo=True)
    elif pm in ("dnf", "yum"):
        ctx.run_command([pm, "install", "-y", *pkg_list], with_sudo=True)
    elif pm == "zypper":
        ctx.run_command(["zypper", "--non-interactive", "install", *pkg_list], with_sudo=True)
    elif pm == "pacman":
        ctx.run_command(["pacman", "-Sy", "--noconfirm", *pkg_list], with_sudo=True)
    elif pm == "apk":
        ctx.run_command(["apk", "add", "--no-cache", *pkg_list], with_sudo=True)


# ---- nix / Lix install ---------------------------------------------------------


def append_conf(file, line):
    """Add LINE to FILE if absent, always on its own line. A file whose last
    line lacks a trailing newline would otherwise get the new setting glued onto
    it (-> an unparseable value)."""
    path = pathlib.Path(file)
    text = path.read_text() if path.exists() else ""
    if line in text.splitlines():
        return
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n")


def configure_single_user_nix(ctx):
    """Ensure the user-level nix.conf enables flakes and sets an EMPTY
    build-users-group. A single-user (--no-daemon) install has no `nixbld`
    build-user pool, so Nix's compiled-in default makes every build fail with
    "the group 'nixbld' … does not exist". Idempotent and independent of whether
    Nix was just installed, so an interrupted install self-heals on re-run."""
    if ctx.dry_run:
        print("\033[2m[dry-run]\033[0m ensure ~/.config/nix/nix.conf: flakes + "
              "accept-flake-config + empty build-users-group")
        return
    conf_dir = HOME / ".config/nix"
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = conf_dir / "nix.conf"
    append_conf(conf, "experimental-features = nix-command flakes")
    append_conf(conf, "accept-flake-config = true")
    append_conf(conf, "build-users-group =")


def repair_nix_build_home(ctx):
    """Nix deliberately assigns /homeless-shelter as HOME to unsandboxed builds
    and requires it to be absent; some container images create it. Remove the
    safe (empty-directory) case; relocate a lone misplaced ~/.cargo intact; never
    merge or delete unknown contents."""
    build_home = pathlib.Path("/homeless-shelter")
    if not build_home.exists() and not build_home.is_symlink():
        return
    if ctx.priv == "none":
        die(f"{build_home} exists; root or sudo is required to remove the empty "
            "Nix build-home directory")
    if not build_home.is_dir() or build_home.is_symlink():
        die(f"{build_home} exists but is not a removable empty directory; remove "
            "or rename it, then rerun bootstrap")
    entries = list(build_home.iterdir())
    cargo = build_home / ".cargo"
    if len(entries) == 1 and entries[0] == cargo and cargo.is_dir() and not cargo.is_symlink():
        # Preserve a Cargo installation created with HOME set to Nix's build
        # sentinel; do not risk an automatic merge with an existing Cargo home.
        cargo_home = HOME / ".cargo"
        if cargo_home.exists() or cargo_home.is_symlink():
            die(f"{cargo} is misplaced but {cargo_home} already exists; merge "
                f"them manually, then remove {build_home}")
        log(f"moving misplaced Cargo home {cargo} -> {cargo_home}")
        ctx.run_command(["mv", str(cargo), str(cargo_home)], with_sudo=True)
        remaining = [] if ctx.dry_run else list(build_home.iterdir())
    else:
        remaining = entries
    if remaining:
        die(f"{build_home} exists and has contents other than a movable lone "
            ".cargo directory; refusing to delete it. Move its contents "
            "elsewhere, remove the directory, then rerun bootstrap")
    log(f"removing empty {build_home} (Nix requires it to be absent for unsandboxed builds)")
    ctx.run_command(["rmdir", str(build_home)], with_sudo=True)


def plan_nix(plan, ctx):
    """The plan sibling of install_lix + configure_single_user_nix: which nix
    (if any) gets installed, how, and which nix.conf that flavour writes."""
    if have_nix():
        version = _nix_version() or "present"
        plan.fact("nix", f"already installed ({version}) — not reinstalled")
    elif ctx.priv == "none":
        plan.fact("nix", "missing, and installing it needs privilege — the run will stop")
    elif has_init_system():
        plan.install("Lix (multi-user) — fetch install.lix.systems/lix, create /nix, "
                     "register the nix-daemon service", priv=True)
    else:
        plan.install("nix (single-user, --no-daemon) — fetch nixos.org/nix/install, "
                     "create /nix (no daemon: this host has no init system)", priv=True)
    if not has_init_system():
        plan.config(f"{HOME}/.config/nix/nix.conf <- experimental-features = nix-command "
                    "flakes; accept-flake-config = true; build-users-group = (single-user)")
    build_home = pathlib.Path("/homeless-shelter")
    if build_home.exists() or build_home.is_symlink():
        entries = list(build_home.iterdir()) if build_home.is_dir() else None
        cargo = build_home / ".cargo"
        if entries == []:
            plan.config("/homeless-shelter removed if empty — required by Nix for "
                        "unsandboxed builds", priv=True)
        elif entries == [cargo] and cargo.is_dir() and not cargo.is_symlink():
            if (HOME / ".cargo").exists() or (HOME / ".cargo").is_symlink():
                plan.fact("nix build home", f"/homeless-shelter/.cargo and {HOME}/.cargo "
                                            "both exist; bootstrap will stop without merging them")
            else:
                plan.config(f"{HOME}/.cargo <- move /homeless-shelter/.cargo intact; then "
                            "remove /homeless-shelter for Nix builds", priv=True)
        else:
            plan.fact("nix build home", "/homeless-shelter exists and is not an empty "
                                        "directory; bootstrap will stop without deleting it")


def _nix_version():
    try:
        out = subprocess.run(["nix", "--version"], capture_output=True, text=True, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


def fetch_retry(url, out):
    """Download with retries (CN networks flake on nixos.org / install.lix.systems
    TLS). curl is guaranteed by ensure_prereqs. Download-then-execute, never
    `curl | bash`."""
    for attempt in range(1, 5):
        rc = subprocess.run(
            ["curl", "-fsSL", "--connect-timeout", "15", "--retry", "3",
             "--retry-connrefused", "--retry-delay", "2", url, "-o", out],
            check=False,
        ).returncode
        if rc == 0:
            return True
        warn(f"download failed ({url}) attempt {attempt}/4; retrying")
        time.sleep(3)
    return False


def _raise_stack_limit(ctx):
    """Nix wants a ~60 MiB thread stack; a 10 MiB hard limit makes it warn on
    every child. Raising a *hard* limit needs privilege: as root use setrlimit
    directly; under sudo have a privileged prlimit raise this process' limit by
    PID. Best-effort — a failure just leaves the (benign) warning in place."""
    want = 62914560
    try:
        if ctx.priv == "root":
            import resource

            resource.setrlimit(resource.RLIMIT_STACK, (want, want))
        elif ctx.priv == "sudo" and shutil.which("prlimit"):
            subprocess.run(
                ["sudo", "prlimit", "--pid", str(os.getpid()), f"--stack={want}:{want}"],
                check=False,
            )
    except (ValueError, OSError):
        pass


def install_lix(ctx):
    """Install nix if absent (needs root/sudo; the caller guards). With an init
    system: the Lix multi-user (service-managed daemon) installer. Without one
    (container/CI): a single-user install (--no-daemon)."""
    if have_nix():
        log(f"nix already installed ({_nix_version() or 'present'}); skipping install")
        return
    if ctx.dry_run:
        if has_init_system():
            print("\033[2m[dry-run]\033[0m install Lix (multi-user): fetch "
                  "https://install.lix.systems/lix; sh install --no-confirm")
        else:
            print("\033[2m[dry-run]\033[0m no init system -> single-user: fetch "
                  "https://nixos.org/nix/install; sh --no-daemon --yes")
        return
    if has_init_system():
        log("installing Lix (multi-user, service-managed daemon)")
        ok = False
        if fetch_retry("https://install.lix.systems/lix", "/tmp/lix-install.sh"):
            ok = subprocess.run(
                ["sh", "/tmp/lix-install.sh", "install", "--no-confirm"], check=False
            ).returncode == 0
        if not ok:
            warn("Lix install failed or unavailable; classic multi-user fallback")
            if not fetch_retry("https://nixos.org/nix/install", "/tmp/nix-install.sh"):
                die("could not download the nix installer (network); retry later")
            subprocess.run(["sh", "/tmp/nix-install.sh", "--daemon", "--yes"], check=True)
    else:
        log("no init system (container/CI): single-user nix install (--no-daemon)")
        # The single-user installer creates /nix via `sudo` even when we already
        # run as root; a bare container may have no sudo. Pre-create /nix owned
        # by the calling user so the installer skips that sudo call entirely.
        if not pathlib.Path("/nix").exists():
            log("pre-creating /nix (installer would otherwise shell out to sudo)")
            user = os.environ.get("USER") or str(os.getuid())
            ctx.run_command(["mkdir", "-m", "0755", "/nix"], with_sudo=True)
            ctx.run_command(["chown", user, "/nix"], with_sudo=True)
        if not fetch_retry("https://nixos.org/nix/install", "/tmp/nix-install.sh"):
            die("could not download the nix installer (network); retry later")
        _raise_stack_limit(ctx)
        # No `nixbld` build-user pool in single-user mode; disable it for the
        # installer's own nix calls. The persistent config is written by
        # configure_single_user_nix, which main() calls unconditionally on the
        # no-init-system path — so an interrupted install still self-heals.
        subprocess.run(
            ["sh", "/tmp/nix-install.sh", "--no-daemon", "--yes"],
            env={**os.environ, "NIX_CONFIG": "build-users-group ="},
            check=True,
        )
    load_nix_path()


# ---- nix config + CN mirror (the former nix-cn.sh) -----------------------------
# Always persists the network choice to ~/.config/dotfiles/network-env (the HM
# .zshenv sources it to gate the pypi/uv/rustup mirror vars). System nix.conf
# edits need privilege; with none they are skipped. CN wiring is at the SYSTEM
# level because a user-level substituter is ignored for non-trusted users under
# the multi-user daemon (ADR-0007).


def _conf_target():
    """Which system file gets the settings. Lix's /etc/nix/nix.conf ends with
    `!include nix.custom.conf`, and edits belong in that include rather than in
    the file the installer manages."""
    sys_conf = pathlib.Path("/etc/nix/nix.conf")
    try:
        if "!include nix.custom.conf" in sys_conf.read_text():
            return pathlib.Path("/etc/nix/nix.custom.conf")
    except OSError:
        pass
    return sys_conf


def _missing_conf_lines(target, network_env):
    """The settings TARGET still lacks. Reading /etc/nix needs no privilege
    (world-readable), so the plan and --dry-run never trigger a sudo prompt."""
    missing = []
    etc_nix = pathlib.Path("/etc/nix")
    have_flakes = False
    if etc_nix.is_dir():
        for f in etc_nix.rglob("*"):
            try:
                if f.is_file() and re.search(r"experimental-features.*flakes", f.read_text()):
                    have_flakes = True
                    break
            except OSError:
                continue
    if not have_flakes:
        missing.append("experimental-features = nix-command flakes")
    if network_env == "CN":
        current = ""
        try:
            current = target.read_text()
        except OSError:
            pass
        lines = current.splitlines()
        user = os.environ.get("USER", "")
        for line in (f"extra-substituters = {CERNET}",
                     f"extra-trusted-substituters = {CERNET}",
                     f"trusted-users = root {user}"):
            if line not in lines:
                missing.append(line)
    return missing


def plan_nix_config(plan, ctx, network_env):
    if network_env == "CN":
        plan.config(f"{NETWORK_MARKER} <- export DOTFILE_NETWORK_ENV=CN "
                    "(the HM zsh sources it: pypi/uv + rustup mirrors)")
    else:
        plan.config(f"{NETWORK_MARKER} removed — upstream mirrors everywhere")
    if ctx.priv == "none":
        plan.config("system nix.conf left untouched (no root/sudo)")
        return
    target = _conf_target()
    missing = _missing_conf_lines(target, network_env)
    for line in missing:
        plan.config(f"{target} <- {line}", priv=True)
    if missing:
        plan.config(f"restart the nix-daemon to apply {target}", priv=True)


def configure_nix(ctx, network_env):
    # Persist the network choice for the HM shell (no privilege needed).
    if ctx.dry_run:
        logger.info("[DRY-RUN] would %s %s",
                    "write CN marker to" if network_env == "CN" else "remove",
                    NETWORK_MARKER)
    else:
        NETWORK_MARKER.parent.mkdir(parents=True, exist_ok=True)
        if network_env == "CN":
            NETWORK_MARKER.write_text("export DOTFILE_NETWORK_ENV=CN\n")
        elif NETWORK_MARKER.exists():
            NETWORK_MARKER.unlink()
    if ctx.priv == "none":
        warn("no privilege: leaving the system nix.conf untouched (using existing mirrors)")
        return
    target = _conf_target()
    if network_env == "CN":
        log(f"CN network: CERNET substituter + trusting {os.environ.get('USER', '')} "
            f"(system level) in {target}")
    else:
        log(f"non-CN network: ensuring flakes in {target} (substituters stay upstream)")
    ctx.run_command(["mkdir", "-p", "/etc/nix"], with_sudo=True)
    ctx.run_command(["touch", str(target)], with_sudo=True)
    missing = _missing_conf_lines(target, network_env)
    for line in missing:
        ctx.run_command(f"printf '%s\\n' \"{line}\" | {ctx.sudo}tee -a \"{target}\" >/dev/null",
                        shell=True)
    if missing:
        log("restarting nix-daemon to apply config")
        if ctx.os_type == "darwin":
            ctx.run_command(["launchctl", "kickstart", "-k", "system/org.nixos.nix-daemon"],
                            with_sudo=True, check=False)
        else:
            ctx.run_command("systemctl restart nix-daemon 2>/dev/null || true",
                            shell=True, check=False)


# ---- host selection ------------------------------------------------------------


def nix_host_exists(name):
    """True if flake.nix defines hosts.<NAME> (text search; no nix eval, so it
    works before nix is installed)."""
    try:
        text = (REPO_DIR / "flake.nix").read_text()
    except OSError:
        return False
    return re.search(rf'"{re.escape(name)}"\s*=', text) is not None


def detect_named_host(os_type):
    """A named flake host by hostname, else by OS+arch."""
    hostname = socket.gethostname().split(".")[0]
    if hostname and nix_host_exists(hostname):
        return hostname
    if os_type == "darwin":
        return "LiuzhendeMacBook-Pro"
    if os.uname().machine in ("aarch64", "arm64"):
        return "dotfiles-linux-arm"
    return "dotfiles-debian"


def select_host(explicit, os_type):
    """Named hosts assume the owner (user lz). For any other user (incl. root)
    fall back to the impure `generic` host, which reads $USER/$HOME at eval
    time. Returns (host, impure_flag)."""
    host = explicit
    if not host:
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
        host = detect_named_host(os_type) if user == "lz" else "generic"
    if host == "generic":
        return host, True
    if not nix_host_exists(host):
        die(f"host '{host}' is not defined in flake.nix")
    return host, False


# ---- the plan ------------------------------------------------------------------
# Steps register what they *would* do before anything runs, so the full blast
# radius can be printed — and cleared — up front (ADR-0010). Four buckets: facts,
# "will install", "will write / link", and "will move aside" — the last printed
# last and highlighted, because displacing existing files is the only part of a
# bootstrap that touches the user's data.


class Plan:
    def __init__(self):
        self.facts = []  # (name, value)
        self.items = []  # (section, text, privileged)

    def fact(self, name, value):
        self.facts.append((name, value))

    def install(self, text, priv=False):
        self.items.append(("install", text, priv))

    def config(self, text, priv=False):
        self.items.append(("config", text, priv))

    def backup(self, text, priv=False):
        self.items.append(("backup", text, priv))

    def extend(self, items):
        """Merge a nested planner's (section, text, priv) tuples — what
        setup.build_plan emits. Each script describes its own steps; the plan is
        still one document."""
        for section, text, priv in items:
            if section in ("install", "config", "backup"):
                self.items.append((section, text, bool(priv)))

    _SECTIONS = (
        ("install", "\033[1mwill install\033[0m"),
        ("config", "\033[1mwill write / link\033[0m"),
        ("backup", "\033[1;33mwill move your existing files aside (renamed, never deleted)\033[0m"),
    )

    def render(self):
        out = ["\033[1;34m==>\033[0m Plan — nothing has run yet"]
        for name, value in self.facts:
            out.append(f"  \033[2m{name:<11}\033[0m {value}")
        for section, title in self._SECTIONS:
            rows = [(t, p) for s, t, p in self.items if s == section]
            if not rows:
                continue
            out.append(f"\n  {title}")
            for text, priv in rows:
                tag = "  \033[33m[privileged]\033[0m" if priv else ""
                # A leading-space item is a detail of the line above it (a system
                # component under its count) — indent instead of re-bulleting.
                if text.startswith("  "):
                    out.append(f"      \033[2m{text.strip()}\033[0m{tag}")
                else:
                    out.append(f"    - {text}{tag}")
        print("\n".join(out))


# ---- home-manager switch --------------------------------------------------------


def flake_cache_seed(ctx):
    """Optional: seed flake input sources from a local cache (CN / offline / CI)
    so nixpkgs + home-manager are not fetched from github. Point
    DOTFILE_FLAKE_CACHE at a `nix copy --to file://…` cache dir containing a
    seed-paths.txt."""
    cache = os.environ.get("DOTFILE_FLAKE_CACHE", "")
    seeds = pathlib.Path(cache) / "seed-paths.txt" if cache else None
    if not (seeds and seeds.is_file()):
        return
    log(f"seeding flake inputs from {cache} (bypass github)")
    ctx.run_command(
        f'nix copy --no-check-sigs --from "file://{cache}" $(cat "{seeds}") || true',
        shell=True, check=False,
    )


def hm_switch(ctx, host, impure):
    """Build the activation package from the flake's LOCKED home-manager (no
    separate `home-manager/master` fetch — more reproducible and one less CN
    github round-trip) and activate it. HOME_MANAGER_BACKUP_EXT=backup is the
    raw-activate equivalent of `switch -b backup`. Returns the generation path
    (or None under --dry-run)."""
    impure_flag = ["--impure"] if impure else []
    if ctx.dry_run:
        log(f"[dry-run] nix build .#homeConfigurations.{host}.activationPackage "
            f"{' '.join(impure_flag)} ; <out>/activate (HOME_MANAGER_BACKUP_EXT=backup)")
        return None
    log(f"home-manager: build activationPackage + activate ({host})")
    # stdout is the store path; stderr (build progress) streams to the terminal.
    result = subprocess.run(
        ["nix", "build", "--no-link", "--print-out-paths", *impure_flag,
         f'{REPO_DIR}#homeConfigurations."{host}".activationPackage'],
        stdout=subprocess.PIPE, text=True,
    )
    if result.returncode != 0:
        die("home-manager build failed")
    hm_out = result.stdout.strip().splitlines()[-1]
    subprocess.run([f"{hm_out}/activate"],
                   env={**os.environ, "HOME_MANAGER_BACKUP_EXT": "backup"}, check=True)
    # HM packages (zsh, mise, …) live in the generation's home-path, not
    # ~/.nix-profile. Put them on PATH so the post-HM steps can find them.
    _prepend_path(f"{hm_out}/home-path/bin")
    return hm_out


# ---- main ------------------------------------------------------------------------


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="bootstrap.sh",
        description="Imperative bootstrap for the Nix + Home Manager dotfiles (ADR-0007). "
                    "On a terminal the full plan is printed and cleared once before "
                    "anything runs (ADR-0010).",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="print every command without executing (no clearance prompt)")
    ap.add_argument("--verbose", action="store_true", help="more logging")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="skip the clearance prompt (the plan is still printed); "
                         "same as DF_ASSUME_YES=1")
    ap.add_argument("--host", default="", help="force a named flake host")
    ap.add_argument("--system", default="",
                    help="opt-in system components: comma-separated names, 'all', "
                         "'default' or 'none' (fallback: $DOTFILE_SYSTEM_COMPONENTS)")
    ap.add_argument("--agents", default="",
                    help="coding agents to provision: claude,codex,pi / 'all' (default) "
                         "/ 'none' (fallback: $DOTFILE_AGENTS)")
    ap.add_argument("--no-claude", action="store_true",
                    help="deprecated alias for --agents none")
    ap.add_argument("--network", default="", metavar="CN",
                    help="CN enables the China mirrors (nix CERNET + pypi/uv + rustup)")
    ap.add_argument("--print-host", action="store_true",
                    help="print the resolved flake host and exit (used by the Justfile)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.network:
        os.environ["DOTFILE_NETWORK_ENV"] = args.network
    network_env = os.environ.get("DOTFILE_NETWORK_ENV", "")

    ctx = Ctx(dry_run=args.dry_run, assume_yes=True if args.yes else None)

    # The `generic` host reads $USER/$HOME via getEnv at flake-eval time; a bare
    # `bash -c` exec context often leaves $USER unset, in which case the
    # attribute never materializes. Populate from the running process.
    import pwd

    os.environ.setdefault("USER", pwd.getpwuid(os.getuid()).pw_name)
    os.environ.setdefault("HOME", pwd.getpwuid(os.getuid()).pw_dir)

    host, impure = select_host(args.host, ctx.os_type)
    if args.print_host:
        print(host)
        return

    log(f"OS: {ctx.os_type} | arch: {os.uname().machine} | privilege: {ctx.priv} "
        f"| network: {network_env or 'default'}")
    log(f"flake host: {host}{' (impure)' if impure else ''}")

    # Privilege / nix availability gate.
    if ctx.priv == "none" and not have_nix():
        die("No root/sudo and nix is not installed — installing nix needs privilege.\n"
            "     Ask an admin to install Nix (or re-run as root / with sudo), then retry.\n"
            "     Exiting cleanly without changes.")

    # Component / agent selection, resolved exactly as setup.py resolves them
    # standalone (flag > env > default) so both entry points agree.
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""
    agent_spec = args.agents or os.environ.get("DOTFILE_AGENTS") or "all"
    if args.no_claude:
        warn("--no-claude is deprecated; use --agents=none")
        agent_spec = "none"
    from installers import agents as agents_mod

    agent_ids = agents_mod.Agent.resolve(agent_spec)

    # ---- the plan + the one-shot clearance (ADR-0010) --------------------------
    plan = Plan()
    plan.fact("os", f"{ctx.os_type} ({os.uname().machine})")
    plan.fact("host", f"{host}{' (impure — $USER/$HOME read at eval time)' if impure else ''}")
    plan.fact("privilege", {
        "root": "root — privileged steps run directly (no sudo)",
        "sudo": "sudo — privileged steps run via sudo (may ask for your password)",
        "none": "none — every privileged step is skipped",
    }[ctx.priv])
    plan.fact("network", "CN — CERNET for nix, BFSU for brew, and the pypi/uv + rustup mirrors"
              if network_env == "CN"
              else "upstream defaults (pass --network CN for the China mirrors)")
    if ctx.priv != "none":
        plan_prereqs(plan, ctx.os_type)
    else:
        plan.fact("skipping", "prereq + nix install (no privilege): the existing nix is used as-is")
    plan_nix(plan, ctx)
    cache = os.environ.get("DOTFILE_FLAKE_CACHE", "")
    if cache and (pathlib.Path(cache) / "seed-paths.txt").is_file():
        plan.install(f"flake inputs seeded from {cache} (no github fetch)")
    plan.install(f"Home Manager generation for '{host}' — the whole user environment from "
                 "home/ (zsh, starship, git, tmux, mise, the CLI toolset)")
    plan.config(f"Home Manager symlinks into {HOME} from the nix store "
                "(~/.zshrc, ~/.config/git, ~/.tmux.conf, …)")
    plan.backup("any $HOME file Home Manager wants to own -> the same name with a "
                ".backup suffix (HOME_MANAGER_BACKUP_EXT=backup)")
    plan_nix_config(plan, ctx, network_env)
    # The post-HM half describes itself (setup.py owns those steps, so it also
    # owns the wording); same code path as a standalone `setup.py --plan`.
    plan.extend(setup.build_plan(ctx, system_spec, agent_ids))

    plan.render()
    ctx.require_clearance("Proceed with this plan?")
    # One answer clears the whole run; export it so anything spawned from here
    # (component installers, delegated scripts) never asks again.
    if ctx.assume_yes:
        os.environ[ASSUME_YES_ENV] = "1"

    # ---- pre-HM ----------------------------------------------------------------
    if ctx.priv != "none":
        ensure_prereqs(ctx)
        install_lix(ctx)
    else:
        warn("no privilege: skipping prereq + Lix install (using the existing nix)")
    load_nix_path()

    # Single-user (no init system: bare docker/CI) has no `nixbld` build-user
    # pool; neutralize it in the user nix.conf — unconditional, so an interrupted
    # install repairs itself on re-run. Needs no privilege.
    if not has_init_system():
        configure_single_user_nix(ctx)

    configure_nix(ctx, network_env)
    repair_nix_build_home(ctx)
    flake_cache_seed(ctx)
    hm_out = hm_switch(ctx, host, impure)

    # ---- post-HM (same process; setup.py owns the steps) -------------------------
    load_nix_path()
    logger.info("post-HM setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)
    setup.set_login_shell(ctx)
    if agent_ids:
        setup.setup_runtimes(ctx)
        setup.setup_agents(ctx, agent_ids)
        setup.write_deferred_setup(ctx, agent_ids)
    if system_spec:
        setup.run_system(ctx, system_spec)

    # The shell that launched bootstrap keeps its old PATH — zsh is NOT on it
    # yet. chsh has made zsh the login shell, so a fresh login gets it; to switch
    # *this* session, exec the absolute path (independent of PATH).
    log("Bootstrap complete.")
    if ctx.dry_run:
        log("(dry-run) afterwards, start the Nix shell with: exec zsh -l")
    else:
        zsh = HOME / ".nix-profile/bin/zsh"
        if not zsh.is_file() and hm_out:
            zsh = pathlib.Path(hm_out) / "home-path/bin/zsh"
        log("Your login shell is now zsh — re-login (new terminal / SSH) to get it, "
            "or switch this session now:")
        print(f"\n    exec {zsh} -l\n")


if __name__ == "__main__":
    main()
