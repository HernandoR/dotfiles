#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/node.py — the Node ecosystem through nvm (ADR-0013 update 2026-09-10).

Reads home/.chezmoidata/node.toml and makes it true: nvm in $NVM_DIR (~/.nvm),
the declared Node line installed and set as default, and every listed global
npm package present. nvm's installer is fetched then run (never `curl | bash`)
with PROFILE=/dev/null so it edits no shell file — the repo's zsh config already
sources nvm.sh. Idempotent; each step is skipped when already satisfied.

Run by chezmoi (run_onchange, whenever node.toml or this file changes) and by
hand via `just node`. `--plan` describes without changing anything.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from context import Ctx  # noqa: E402
from managers import Script  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "node.toml"
HOME = pathlib.Path.home()
NVM_DIR = pathlib.Path(os.environ.get("NVM_DIR") or HOME / ".nvm")
NVM_SH = NVM_DIR / "nvm.sh"
# Pin the installer to a release so a fresh machine gets a reviewed nvm.
NVM_VERSION = "v0.40.3"
NVM_INSTALLER = f"https://raw.githubusercontent.com/nvm-sh/nvm/{NVM_VERSION}/install.sh"


def log(msg):
    print(f"\033[1;34m==>\033[0m node: {msg}", flush=True)


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m node: {msg}", file=sys.stderr, flush=True)


def load():
    return tomllib.loads(DATA.read_text())["node"]


def nvm(ctx, *cmd, capture=False):
    """Run `nvm ...` (a shell function) through bash with nvm.sh sourced."""
    line = f'export NVM_DIR="{NVM_DIR}"; . "{NVM_SH}"; ' + " ".join(cmd)
    return ctx.run_command(["bash", "-lc", line] if False else ["bash", "-c", line],
                           capture_output=capture, check=False)


def installed_node_bins():
    """Newest first — the same choice env.zsh makes for non-interactive shells."""
    versions = NVM_DIR / "versions" / "node"
    if not versions.is_dir():
        return []

    def key(p):
        return tuple(int(x) for x in p.name.lstrip("v").split(".") if x.isdigit())
    return [p / "bin" for p in sorted(versions.iterdir(), key=key, reverse=True) if (p / "bin").is_dir()]


def npm_path():
    bins = installed_node_bins()
    return (bins[0] / "npm") if bins and (bins[0] / "npm").exists() else None


def global_missing(npm, globals_):
    """Which of `globals_` `npm ls -g` does not know (name without @version)."""
    if not npm:
        return list(globals_)
    res = subprocess.run([str(npm), "ls", "-g", "--depth=0", "--parseable"], capture_output=True, text=True)
    have = {pathlib.Path(line).name if not line.split("/")[-2:-1] == ["@"] else line for line in res.stdout.splitlines()}
    have_scoped = {"/".join(pathlib.Path(line).parts[-2:]) for line in res.stdout.splitlines()}
    return [g for g in globals_ if g not in have and g not in have_scoped]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", action="store_true", help="print plan rows (section<TAB>text) and exit")
    args = ap.parse_args()
    ctx = Ctx(dry_run=args.dry_run or args.plan, assume_yes=True)
    cfg = load()
    npm = npm_path()
    missing = global_missing(npm, cfg["globals"])

    if args.plan:
        if not NVM_SH.exists():
            print(f"install\tnvm {NVM_VERSION} -> {NVM_DIR} (its installer, PROFILE=/dev/null)")
        if not installed_node_bins():
            print(f"install\tNode {cfg['version']} via nvm (set as default)")
        if missing:
            print("install\tnpm -g: " + ", ".join(missing))
        return

    if not NVM_SH.exists():
        log(f"installing nvm {NVM_VERSION} into {NVM_DIR}")
        ctx.package_manager("scripts").install(
            ctx, Script(NVM_INSTALLER, interpreter="bash",
                        env={"NVM_DIR": str(NVM_DIR), "PROFILE": "/dev/null"}, check=False))
        if not ctx.dry_run and not NVM_SH.exists():
            warn("nvm installer did not produce nvm.sh — stopping")
            sys.exit(1)
    if not installed_node_bins():
        log(f"nvm install {cfg['version']}")
        nvm(ctx, "nvm", "install", cfg["version"], "&&", "nvm", "alias", "default", cfg["version"])
        npm = npm_path()
        missing = global_missing(npm, cfg["globals"])
    if missing:
        if not npm and not ctx.dry_run:
            warn("npm not found under $NVM_DIR after install; skipping the globals")
            sys.exit(1)
        log("npm install -g " + " ".join(missing))
        ctx.run_command([str(npm or "npm"), "install", "-g", *missing], check=False)
    else:
        log("nvm, Node and every global present; nothing to do")


if __name__ == "__main__":
    main()
