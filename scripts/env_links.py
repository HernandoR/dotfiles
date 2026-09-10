#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/env_links.py — the mutable $HOME links (ADR-0013, carrying ADR-0009
Tier B forward).

Reads the inventory in home/.chezmoidata/envlinks.toml and makes it true:

  1. seed a missing link TARGET under the machine's state root (kind/mode/seed
     apply on creation only, never to a target that exists);
  2. preserve a real ~/.ssh's files into the target before it becomes a link;
  3. repair a REGULAR FILE left where a link belongs (some writers rename a
     temp file over the path — Claude Code does this to ~/.claude.json — which
     silently turns the link into a file; the newer side wins, and it says so);
  4. place the symlink $HOME/<name> -> <stateRoot>/<name>, moving a real
     file/dir in the way to <name>.backup (never deleting anything).

chezmoi runs this as a `run_before_` script on every apply (home/.chezmoiscripts)
with --state-root/--env from its config; run by hand (or `just env-links`) it
asks `chezmoi data` for them. These paths are deliberately NOT chezmoi source
entries, so `chezmoi apply` can never replace one of them with a regular file.

The state root's PARENT must already exist: if the persistent volume is not
mounted, building the tree on the ephemeral disk would make every link "work"
while persisting nothing — the exact failure this script exists to prevent. So a
missing parent warns and skips instead.
"""
import argparse
import json
import os
import pathlib
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib

# Die quietly when stdout is closed early (`… | head`) instead of ending in a
# BrokenPipeError traceback. Full rationale in scripts/context.py.
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata"
HOME = pathlib.Path.home()


def log(msg):
    print(f"\033[1;34m==>\033[0m env-links: {msg}")


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m env-links: {msg}", file=sys.stderr)


def load_inventory():
    data = tomllib.loads((DATA / "envlinks.toml").read_text())["envlinks"]
    return data.get("entries", {}), data.get("links", {})


def mise_seed():
    """Render home/.chezmoidata/mise.toml into the TOML mise expects in
    ~/.config/mise/config.toml. A tiny emitter for the two shapes the file uses
    (string values and inline tables of string / list-of-string), so no
    third-party TOML writer is needed."""
    mise = tomllib.loads((DATA / "mise.toml").read_text())["mise"]
    tools = dict(mise.get("tools", {}))
    if sys.platform == "linux":
        tools.update(mise.get("linux_tools", {}))

    def key(k):
        return k if k.replace("-", "").replace("_", "").isalnum() else json.dumps(k)

    def value(v):
        if isinstance(v, str):
            return json.dumps(v)
        if isinstance(v, list):
            return "[" + ", ".join(json.dumps(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{ " + ", ".join(f"{key(k)} = {value(x)}" for k, x in v.items()) + " }"
        raise TypeError(f"unsupported mise tool value: {v!r}")

    lines = ["# Seeded once from home/.chezmoidata/mise.toml; this file is mise's now",
             "# (`mise use -g`, `mise up`, `mise unuse` rewrite it and the versions persist).",
             "[tools]"]
    for k, v in tools.items():
        lines.append(f"{key(k)} = {value(v)}")
    return "\n".join(lines) + "\n"


def chezmoi_data():
    """Fallback for a by-hand run: ask chezmoi for env + stateRoot."""
    try:
        out = subprocess.run(["chezmoi", "data", "--format", "json"], capture_output=True,
                             text=True, check=True).stdout
        return json.loads(out)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def applies(entry, env):
    envs = entry.get("envs")
    return not envs or env in envs


class Runner:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.actions = []  # (section, text) for the plan
        self.repaired = set()  # names repair_file folded away (so a dry run does not re-plan them)

    def plan(self, section, text):
        self.actions.append((section, text))

    def do(self, text, fn):
        if self.dry_run:
            print(f"\033[2m[dry-run]\033[0m {text}")
        else:
            log(text)
            fn()


def seed_target(r, root, name, e):
    target = root / name
    if target.exists() or target.is_symlink():
        return
    mode = int(e["mode"], 8)
    if e["kind"] == "dir":
        r.plan("config", f"create {target} (dir, {e['mode']})")
        r.do(f"mkdir -m {e['mode']} {target}", lambda: (target.mkdir(parents=True), target.chmod(mode)))
    else:
        seed = mise_seed() if e.get("seed_from") == "mise" else e.get("seed", "")
        r.plan("config", f"create {target} (file, {e['mode']}{', seeded' if seed else ''})")

        def write():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(seed)
            target.chmod(mode)
        r.do(f"install -m {e['mode']} {target}{' <- seed' if seed else ''}", write)


def preserve_ssh(r, root):
    """Copy files a real ~/.ssh holds that the target lacks, before ~/.ssh is
    replaced by the link. The target wins for anything already migrated."""
    src, dst = HOME / ".ssh", root / ".ssh"
    if not (src.is_dir() and not src.is_symlink() and dst.is_dir()):
        return
    for item in src.iterdir():
        if (dst / item.name).exists() or (dst / item.name).is_symlink():
            continue
        r.plan("config", f"preserve ~/.ssh/{item.name} into {dst}")
        r.do(f"cp -a ~/.ssh/{item.name} {dst}/",
             lambda item=item: shutil.copy2(item, dst / item.name, follow_symlinks=False)
             if not item.is_dir() else shutil.copytree(item, dst / item.name, symlinks=True))


def repair_file(r, root, name, e):
    """Fold a regular file back into its target where a link belongs (files
    only: a real directory in the way is not this failure mode and goes through
    the .backup path in place_link)."""
    link, target = HOME / name, root / name
    if e["kind"] != "file" or link.is_symlink() or not link.is_file():
        return
    r.repaired.add(name)
    if not target.exists() or link.stat().st_mtime > target.stat().st_mtime:
        r.plan("config", f"~/{name} is a regular file newer than {target} — fold it back into the target")
        r.do(f"mv -f ~/{name} {target} (newer file wins)",
             lambda: (shutil.move(str(link), str(target)), target.chmod(int(e["mode"], 8))))
    else:
        r.plan("config", f"~/{name} is a regular file older than {target} — discard it, the target wins")
        r.do(f"rm -f ~/{name} (target wins)", link.unlink)


def place_link(r, name, target, backups):
    link = HOME / name
    if r.dry_run and name in r.repaired:
        r.plan("config", f"~/{name} -> {target}")
        print(f"\033[2m[dry-run]\033[0m ln -s {target} ~/{name}")
        return
    if link.is_symlink():
        if os.readlink(link) == str(target):
            return
        r.plan("config", f"~/{name} -> {target} (re-pointed from {os.readlink(link)})")
        r.do(f"ln -sfn {target} ~/{name}", lambda: (link.unlink(), link.symlink_to(target)))
        return
    if link.exists():
        stamp = time.strftime("%Y%m%d%H%M%S")
        backup = link.with_name(link.name + ".backup")
        if backup.exists() or backup.is_symlink():
            backup = link.with_name(f"{link.name}.backup.{stamp}")
        r.plan("backup", f"~/{name} -> ~/{backup.relative_to(HOME)} (real path in the way of the link)")
        backups.append((link, backup))
        r.do(f"mv ~/{name} ~/{backup.relative_to(HOME)}", lambda: shutil.move(str(link), str(backup)))
    r.plan("config", f"~/{name} -> {target}")
    r.do(f"ln -s {target} ~/{name}",
         lambda: (link.parent.mkdir(parents=True, exist_ok=True), link.symlink_to(target)))


def run(state_root, env, dry_run, plan_only):
    entries, links = load_inventory()
    root = pathlib.Path(state_root)
    r = Runner(dry_run or plan_only)
    if not root.parent.is_dir():
        warn(f"{root.parent} does not exist — not seeding link targets.")
        warn("mount the persistent volume, then re-run; until then the $HOME links are not placed.")
        r.plan("config", f"SKIPPED: state root parent {root.parent} is missing (volume not mounted)")
        return r
    live = {n: e for n, e in entries.items() if applies(e, env)}
    if not root.is_dir():
        r.plan("config", f"create state root {root}")
        r.do(f"mkdir -p {root}", lambda: root.mkdir(parents=True))
    for name, e in live.items():
        seed_target(r, root, name, e)
    if ".ssh" in live:
        preserve_ssh(r, root)
    for name, e in live.items():
        repair_file(r, root, name, e)
    backups = []
    for name in live:
        place_link(r, name, root / name, backups)
    for name, spec in links.items():
        if applies(spec, env):
            place_link(r, name, pathlib.Path(spec["target"]), backups)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-root", default="", help="persistent state root (default: chezmoi data)")
    ap.add_argument("--env", default="", help="environment name (default: chezmoi data)")
    ap.add_argument("--dry-run", action="store_true", help="print every action, change nothing")
    ap.add_argument("--plan", action="store_true",
                    help="describe what would change as plan rows (section<TAB>text) and exit")
    args = ap.parse_args()
    state_root, env = args.state_root, args.env
    if not state_root or not env:
        data = chezmoi_data()
        state_root = state_root or data.get("stateRoot") or str(HOME / "dotfile_home")
        env = env or data.get("env") or "default"
    r = run(state_root, env, args.dry_run, args.plan)
    if args.plan:
        for section, text in r.actions:
            print(f"{section}\t{text}")
    elif not r.actions:
        log(f"nothing to do (env={env}, stateRoot={state_root})")


if __name__ == "__main__":
    main()
