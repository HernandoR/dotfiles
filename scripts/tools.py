#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Install and describe the bootstrap toolchain (ADR-0013).

Used by both ``bootstrap.py`` and chezmoi's first ``run_before`` script.  The
tool inventory and its plan rows therefore have one owner.  ``--backup`` starts
the first-apply transaction: pending is written only after the copy completes;
the final chezmoi ``run_after`` script promotes it to done.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import time

from components import Homebrew
from context import Ctx
from managers import Script

SCRIPTS = pathlib.Path(__file__).resolve().parent
REPO = SCRIPTS.parent
HOME = pathlib.Path.home()
LOCAL_BIN = HOME / ".local" / "bin"
BACKUP_ROOT = HOME / "dotfiles_backup"
FIRST_APPLY_DIR = HOME / ".local" / "state" / "dotfiles"
PENDING = FIRST_APPLY_DIR / "first-apply.pending"
DONE = FIRST_APPLY_DIR / "first-apply.done"

TOOLS = {
    "chezmoi": Script("https://get.chezmoi.io", interpreter="sh", args=["-b", str(LOCAL_BIN)], check=False),
    "mise": Script("https://mise.run", interpreter="sh", check=False),
}

_PKG_MANAGERS = {
    "debian": "apt-get", "ubuntu": "apt-get", "fedora": "_dnf_or_yum",
    "rhel": "_dnf_or_yum", "amzn": "_dnf_or_yum", "suse": "zypper",
    "arch": "pacman", "alpine": "apk", "darwin": "brew",
}
_PREREQ_PACKAGES = "curl git ca-certificates"


def log(msg):
    print(f"\033[1;34m==>\033[0m tools: {msg}", flush=True)


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m tools: {msg}", file=sys.stderr, flush=True)


def os_pkg_manager(os_type):
    pm = _PKG_MANAGERS.get(os_type)
    return "dnf" if pm == "_dnf_or_yum" and shutil.which("dnf") else ("yum" if pm == "_dnf_or_yum" else pm)


def prereqs_missing():
    return not (shutil.which("curl") and shutil.which("git"))


def plan_prereqs(plan, os_type):
    if os_type == "darwin":
        if not shutil.which("git"):
            plan.install("Xcode command line tools (for git)", priv=True)
        return
    if not prereqs_missing():
        return
    pm = os_pkg_manager(os_type)
    if pm and pm != "brew":
        plan.install(f"prerequisites via {pm}: {_PREREQ_PACKAGES}", priv=True)
    else:
        plan.fact("skipping", f"prerequisite install: no package-manager backend for '{os_type}' (install curl/git yourself)")


def ensure_prereqs(ctx):
    if ctx.os_type == "darwin":
        if not shutil.which("git"):
            ctx.run_command("xcode-select --install || true", shell=True, check=False)
        if not shutil.which("curl"):
            raise SystemExit("error: curl is required")
        return
    if not prereqs_missing():
        return
    pm = os_pkg_manager(ctx.os_type)
    if not pm or pm == "brew":
        warn(f"no package-manager backend for OS '{ctx.os_type}': skipping the prereq install")
        return
    pkgs = _PREREQ_PACKAGES.split()
    log(f"installing prerequisites via {pm} ({_PREREQ_PACKAGES})")
    if pm == "apt-get":
        ctx.run_command(["apt-get", "update", "-qq"], with_sudo=True)
        ctx.run_command(["apt-get", "install", "-y", "-qq", *pkgs], with_sudo=True)
    elif pm in ("dnf", "yum"):
        ctx.run_command([pm, "install", "-y", *pkgs], with_sudo=True)
    elif pm == "zypper":
        ctx.run_command(["zypper", "--non-interactive", "install", *pkgs], with_sudo=True)
    elif pm == "pacman":
        ctx.run_command(["pacman", "-Sy", "--noconfirm", "--needed", *pkgs], with_sudo=True)
    elif pm == "apk":
        ctx.run_command(["apk", "add", "--no-cache", *pkgs], with_sudo=True)


def brew_bin():
    found = shutil.which("brew")
    if found:
        return found
    for candidate in (pathlib.Path("/opt/homebrew/bin/brew"), pathlib.Path("/usr/local/bin/brew")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def have_brew():
    return brew_bin() is not None


def ensure_brew_path():
    """Make a just-installed brew usable by Python children in this process."""
    brew = brew_bin()
    if brew:
        parent = str(pathlib.Path(brew).parent)
        if parent not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = parent + os.pathsep + os.environ.get("PATH", "")


def installed_outside_nix(name):
    found = shutil.which(name)
    if not found or found.startswith("/nix/") or "/.nix-profile/" in found:
        return None
    return found


def plan_tools(plan):
    if sys.platform == "darwin":
        if have_brew():
            plan.fact("brew", "already installed — not reinstalled")
        else:
            plan.install("Homebrew (its installer; BFSU mirror under --network CN) — packages.toml and the fonts need it", priv=True)
    for name, script in TOOLS.items():
        found = installed_outside_nix(name)
        if found:
            plan.fact(name, f"already installed ({found}) — not reinstalled")
        elif shutil.which(name):
            plan.install(f"{name} via its installer ({script.url}) into {LOCAL_BIN} — the one on PATH ({shutil.which(name)}) is Nix's and goes away with it")
        else:
            plan.install(f"{name} via its installer ({script.url}) into {LOCAL_BIN}")


def install_tools(ctx):
    if sys.platform == "darwin" and not have_brew():
        Homebrew().install(ctx)
    ensure_brew_path()
    if sys.platform == "darwin" and not have_brew() and not ctx.dry_run:
        warn("Homebrew did not install — packages.toml and the fonts will be skipped on this run")
    for name, script in TOOLS.items():
        if installed_outside_nix(name):
            continue
        log(f"installing {name}" + (f" into {LOCAL_BIN} — Nix's copy goes away with it" if shutil.which(name) else ""))
        ctx.package_manager("scripts").install(ctx, script)
        if not ctx.dry_run and not installed_outside_nix(name):
            warn(f"{name} still not installed outside /nix after its installer — the apply may be incomplete")


def source_targets():
    out = []
    for path in sorted((REPO / "home").rglob("*")):
        if path.is_dir() or any(part.startswith(".chezmoi") for part in path.relative_to(REPO / "home").parts):
            continue
        parts = []
        for part in path.relative_to(REPO / "home").parts:
            for prefix in ("private_", "readonly_", "executable_", "create_", "modify_", "symlink_", "encrypted_", "once_", "onchange_", "after_", "before_"):
                if part.startswith(prefix):
                    part = part[len(prefix):]
            if part.startswith("dot_"):
                part = "." + part[4:]
            if part.endswith(".tmpl"):
                part = part[:-5]
            parts.append(part)
        rel = "/".join(parts)
        if rel != "README.md":
            out.append(rel)
    return out


def existing_targets(ctx, config=None):
    binary = shutil.which("chezmoi")
    if binary:
        cmd = [binary, "--source", str(REPO), "--no-tty"]
        if config:
            cmd += ["--config", str(config)]
        cmd += ["status", "--exclude", "scripts,externals"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            rels = [line[3:] for line in res.stdout.splitlines() if len(line) > 3 and line[1] != " "]
            return [r for r in rels if (HOME / r).is_symlink() or ((HOME / r).exists() and not (HOME / r).is_dir())]
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            pass
    return [r for r in source_targets() if (HOME / r).exists() or (HOME / r).is_symlink()]


def backup_targets(ctx, rels, dest):
    if not rels:
        return
    for rel in rels:
        src, dst = HOME / rel, dest / rel
        if ctx.dry_run:
            print(f"\033[2m[dry-run]\033[0m cp -aP ~/{rel} {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    log(f"backed up {len(rels)} existing path(s) under {dest}")


def start_first_apply(ctx):
    if DONE.exists() or PENDING.exists():
        return
    if os.environ.get("DF_BACKUP_TAKEN") != "1":
        backup_targets(ctx, existing_targets(ctx), BACKUP_ROOT / time.strftime("%Y_%m_%d_%H%M%S"))
    if not ctx.dry_run:
        FIRST_APPLY_DIR.mkdir(parents=True, exist_ok=True)
        PENDING.write_text("first apply backup complete\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--install", action="store_true", help="install missing bootstrap tools")
    ap.add_argument("--plan", action="store_true", help="print tool plan rows and exit")
    ap.add_argument("--backup", action="store_true", help="start the first-apply backup transaction")
    args = ap.parse_args(argv)
    ctx = Ctx(dry_run=args.plan, assume_yes=True)
    if args.plan:
        class Rows:
            def fact(self, name, text): print(f"config\t{name}: {text}")
            def install(self, text, priv=False): print("install\t" + text + ("\tprivileged" if priv else ""))
        plan_tools(Rows())
        return
    if args.install:
        if ctx.priv != "none":
            ensure_prereqs(ctx)
        install_tools(ctx)
    if args.backup:
        start_first_apply(ctx)


if __name__ == "__main__":
    main()
