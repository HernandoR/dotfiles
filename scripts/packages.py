#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/packages.py — install the user-level CLI toolset (ADR-0013).

Reads home/.chezmoidata/packages.toml and installs every entry that applies to
this OS. zoi is the front door: each entry becomes `zoi install --yes
<manager>:<name>` (or a plain zoi registry id when the entry has `zoi = ...`).
zoi's native passthrough is best-effort — on macOS 2026-09-09 `zoi install
brew:cowsay` reported success and installed nothing — so afterwards every
entry's `bin` is probed and a missing one falls back to the native manager
directly, then to `mise use -g <mise>` when the entry names a mise tool.

Run by chezmoi (run_onchange_ script, whenever packages.toml or this file
changes) and by hand via `just packages`. `--plan` describes without changing.
"""
import argparse
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from context import Ctx  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "packages.toml"
HOME = pathlib.Path.home()

# OS family (Ctx._detect_os) -> the native manager key used in packages.toml.
NATIVE = {
    "darwin": "brew", "debian": "apt", "ubuntu": "apt", "amzn": "dnf", "fedora": "dnf",
    "rhel": "dnf", "suse": "zypper", "arch": "pacman", "alpine": "apk",
}
# How each native manager installs, when zoi did not deliver. sudo is added by
# ctx.run_command(with_sudo=True) for the Linux ones.
INSTALL = {
    "brew": (["brew", "install"], False),
    "apt": (["apt-get", "install", "-y"], True),
    "dnf": (["dnf", "install", "-y"], True),
    "zypper": (["zypper", "--non-interactive", "install"], True),
    "pacman": (["pacman", "-Sy", "--noconfirm", "--needed"], True),
    "apk": (["apk", "add", "--no-cache"], True),
}


def log(msg):
    print(f"\033[1;34m==>\033[0m packages: {msg}")


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m packages: {msg}", file=sys.stderr)


def load():
    return tomllib.loads(DATA.read_text())["packages"]


def applicable(pkgs):
    here = "darwin" if sys.platform == "darwin" else "linux"
    return [p for p in pkgs if p.get("only", here) == here]


def have(binary):
    return shutil.which(binary) is not None


def zoi_spec(pkg, manager):
    if pkg.get("zoi"):
        return pkg["zoi"]
    name = pkg.get(manager, "")
    return f"{manager}:{name}" if name else ""


def install_native(ctx, manager, pkg):
    name = pkg.get(manager, "")
    if not name:
        return False
    argv, priv = INSTALL[manager]
    if manager == "brew" and pkg.get("cask"):
        argv = ["brew", "install", "--cask"]
    if manager == "apt" and not getattr(install_native, "_updated", False):
        ctx.run_command(["apt-get", "update", "-qq"], with_sudo=True, check=False)
        install_native._updated = True
    return ctx.run_command([*argv, name], with_sudo=priv, check=False).returncode == 0


def install_mise(ctx, pkg):
    spec = pkg.get("mise", "")
    mise = shutil.which("mise")
    if not spec or not mise:
        return False
    return ctx.run_command([mise, "use", "-g", "-y", f"{spec}@latest"], check=False).returncode == 0


def link_alias(ctx, pkg):
    """Debian ships `fdfind`; the repo (and everyone's fingers) say `fd`."""
    for wanted, actual in pkg.get("alias", {}).items():
        if have(wanted) or not have(actual):
            continue
        dest = HOME / ".local" / "bin" / wanted
        ctx.run_command(["ln", "-sfn", shutil.which(actual), str(dest)], check=False)


def plan(ctx, pkgs, manager):
    rows = []
    for p in pkgs:
        binary = p.get("bin", p["name"])
        if have(binary):
            continue
        spec = zoi_spec(p, manager)
        via = f"zoi install {spec}" if spec else None
        fallback = f"{manager} install {p[manager]}" if p.get(manager) else None
        mise = f"mise use -g {p['mise']}" if p.get("mise") else None
        chain = " -> ".join(x for x in (via, fallback, mise) if x) or "NO BACKEND on this OS (install by hand)"
        rows.append(("install", f"{p['name']} ({binary}): {chain}"))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", action="store_true", help="print plan rows (section<TAB>text) and exit")
    ap.add_argument("-y", "--yes", action="store_true", help="unused; accepted for symmetry")
    args = ap.parse_args()
    ctx = Ctx(dry_run=args.dry_run or args.plan, assume_yes=True)
    manager = NATIVE.get(ctx.os_type)
    pkgs = applicable(load())
    if manager is None:
        warn(f"no native package manager known for OS '{ctx.os_type}' — nothing installed")
        if args.plan:
            print(f"install\tpackages: SKIPPED — no native backend for '{ctx.os_type}'")
        return
    if args.plan:
        for section, text in plan(ctx, pkgs, manager):
            print(f"{section}\t{text}")
        return

    missing = [p for p in pkgs if not have(p.get("bin", p["name"]))]
    if not missing:
        log(f"all {len(pkgs)} tools present ({platform.system()}); nothing to do")
        return
    log(f"{len(missing)} of {len(pkgs)} tools missing: " + ", ".join(p["name"] for p in missing))

    # 1) zoi, the front door — one call for everything it has a spec for.
    zoi = shutil.which("zoi")
    specs = [s for s in (zoi_spec(p, manager) for p in missing) if s]
    if zoi and specs:
        ctx.run_command([zoi, "install", "--yes", *specs], check=False)
    elif not zoi:
        warn("zoi not on PATH — going straight to the native manager")

    # 2) verify, and fall back per tool.
    for p in missing:
        binary = p.get("bin", p["name"])
        link_alias(ctx, p)
        if have(binary):
            continue
        if p.get(manager) and install_native(ctx, manager, p):
            link_alias(ctx, p)
            if have(binary):
                continue
        if install_mise(ctx, p) and have(binary):
            continue
        if ctx.dry_run:
            continue
        if not p.get(manager) and not p.get("mise"):
            warn(f"{p['name']}: no backend on this OS — install it by hand")
        else:
            warn(f"{p['name']}: still missing after zoi/{manager}/mise — check the output above")

    still = [p["name"] for p in missing if not have(p.get("bin", p["name"]))]
    if still and not ctx.dry_run:
        warn("not installed: " + ", ".join(still))
    else:
        log("done")


if __name__ == "__main__":
    main()
