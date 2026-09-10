#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/packages.py — the few tools that must come from the OS package
manager (ADR-0013).

Most of the toolset is installed by mise from prebuilt release binaries
(home/.chezmoidata/mise.toml, scripts/runtimes.py). What is left for this script
is the system-level remainder — the shell, GNU userland, git, wget/rsync, X
clipboard — listed in home/.chezmoidata/packages.toml with its name per package
manager. The script detects which manager this host has (brew on macOS; apt,
dnf or yum on Linux; brew as a last resort) and installs ONLY what is missing —
a tool the host already has is never reinstalled — with sudo only when the
manager needs it.

Run by chezmoi (run_onchange, whenever packages.toml or this file changes) and
by hand via `just packages`. `--plan` describes without changing anything.
"""
import argparse
import pathlib
import shutil
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from context import Ctx  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "packages.toml"
HOME = pathlib.Path.home()

# manager -> (binary that proves it is there, install argv, needs sudo, key in packages.toml)
MANAGERS = (
    ("brew", "brew", ["brew", "install"], False),
    ("apt", "apt-get", ["apt-get", "install", "-y"], True),
    ("dnf", "dnf", ["dnf", "install", "-y"], True),
    ("dnf", "yum", ["yum", "install", "-y"], True),  # same package names as dnf
)


def log(msg):
    print(f"\033[1;34m==>\033[0m packages: {msg}", flush=True)


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m packages: {msg}", file=sys.stderr, flush=True)


def detect_manager():
    """(key, argv, needs_sudo) for this host. macOS is brew; Linux takes the
    first native manager found and falls back to Linuxbrew only when none is."""
    order = MANAGERS if sys.platform == "darwin" else MANAGERS[1:] + MANAGERS[:1]
    for key, probe, argv, sudo in order:
        if shutil.which(probe):
            return key, argv, sudo
    return None, None, False


def applicable(pkgs):
    here = "darwin" if sys.platform == "darwin" else "linux"
    return [p for p in pkgs if p.get("only", here) == here]


def present(pkg):
    """Is this tool already here? Never reinstall what the host has.

    Default: `bin` (or the name) resolves on PATH. macOS complicates the GNU
    userland — `ls`, `find`, `sed`, `grep` always resolve to the BSD tools, so
    those entries carry `probe_darwin`, a list of paths of which one must exist
    (the brew gnubin binaries, under either Homebrew prefix)."""
    probes = pkg.get("probe_darwin") if sys.platform == "darwin" else None
    if probes:
        return any(pathlib.Path(x).exists() for x in probes)
    return shutil.which(pkg.get("bin", pkg["name"])) is not None


def have(binary):
    return shutil.which(binary) is not None


def install_native(ctx, key, argv, sudo, pkg):
    name = pkg.get(key, "")
    if not name:
        return False
    if key == "brew" and pkg.get("cask"):
        argv = ["brew", "install", "--cask"]
    if key == "apt" and not getattr(install_native, "_updated", False):
        ctx.run_command(["apt-get", "update", "-qq"], with_sudo=True, check=False)
        install_native._updated = True
    return ctx.run_command([*argv, name], with_sudo=sudo, check=False).returncode == 0


def install_mise(ctx, pkg):
    spec, mise = pkg.get("mise", ""), shutil.which("mise")
    if not spec or not mise:
        return False
    return ctx.run_command([mise, "use", "-g", "-y", f"{spec}@latest"], check=False).returncode == 0


def link_alias(ctx, pkg):
    """Debian ships `fdfind`; the repo (and everyone's fingers) say `fd`."""
    for wanted, actual in pkg.get("alias", {}).items():
        if not have(wanted) and have(actual):
            ctx.run_command(["ln", "-sfn", shutil.which(actual), str(HOME / ".local" / "bin" / wanted)],
                            check=False)


def chain(pkg, key):
    steps = []
    if key and pkg.get(key):
        steps.append(f"{key} install {'--cask ' if key == 'brew' and pkg.get('cask') else ''}{pkg[key]}")
    if pkg.get("mise"):
        steps.append(f"mise use -g {pkg['mise']}")
    return " -> ".join(steps) or "NO BACKEND on this host (install by hand)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", action="store_true", help="print plan rows (section<TAB>text) and exit")
    args = ap.parse_args()
    ctx = Ctx(dry_run=args.dry_run or args.plan, assume_yes=True)  # never prompts
    key, argv, sudo = detect_manager()
    pkgs = applicable(tomllib.loads(DATA.read_text())["packages"])
    missing = [p for p in pkgs if not present(p)]

    if args.plan:
        if key is None:
            print("install\tpackages: no supported package manager found (brew/apt/dnf/yum) — "
                  + ", ".join(p["name"] for p in missing) + " must be installed by hand")
        for p in missing:
            print(f"install\t{p['name']} ({p.get('bin', p['name'])}): {chain(p, key)}")
        return
    if not missing:
        log(f"all {len(pkgs)} system tools present; nothing to do")
        return
    log(f"{len(missing)} of {len(pkgs)} missing: " + ", ".join(p["name"] for p in missing)
        + f" (package manager: {key or 'none found'})")

    if key is None and not ctx.dry_run:
        if sys.platform == "darwin" and any(p.get("brew") for p in missing):
            warn("Homebrew is missing despite macOS package entries; this apply cannot install "
                 "their brew packages and run_onchange will not retry until an input changes")
        warn("no supported package manager (brew/apt/dnf/yum) on this host — install by hand: "
             + ", ".join(p["name"] for p in missing))
    for p in missing:
        if key and install_native(ctx, key, argv, sudo, p):
            link_alias(ctx, p)
            if present(p):
                continue
        if install_mise(ctx, p) and present(p):
            continue
        if not ctx.dry_run:
            if not ((key and p.get(key)) or p.get("mise")):
                warn(f"{p['name']}: no backend on this host — install it by hand")
            else:
                warn(f"{p['name']}: still missing after {chain(p, key)}")

    still = [p["name"] for p in missing if not present(p)]
    if still and not ctx.dry_run:
        warn("not installed: " + ", ".join(still))
    else:
        log("done")


if __name__ == "__main__":
    main()
