#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/check.py — the repo's verification, in one command (`just check`).

There is no test framework; this is what stands in for one:

  1. the three data files parse and every entry has what the scripts need;
  2. every script compiles and answers --help;
  3. chezmoi renders the whole source tree into a scratch $HOME (no scripts, no
     externals, no network) with each known environment's data, and the results
     are checked: `zsh -n` on every zsh file, `git config --list` on the git
     config, TOML parses for the TOML files.

Exit status is non-zero on the first failure. Needs `chezmoi` and `zsh` on PATH.
"""
import os
import pathlib
import py_compile
import shutil
import subprocess
import sys
import tempfile
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
HOME_SRC = REPO / "home"
DATA = HOME_SRC / ".chezmoidata"
SCRIPTS = REPO / "scripts"
ENVS = {
    "default": {},
    "mewtant": {"DOTFILE_STATE_ROOT": "/fsx/hernando/dotfile_home_link_src", "DOTFILE_NETWORK_ENV": "CN"},
    "ec2-wo-fsx": {"DOTFILE_STATE_ROOT": "/home/ec2-user/dotfile_home"},
}
MANAGERS = ("brew", "apt", "dnf", "pacman", "apk", "zypper")

failures = []


def ok(msg):
    print(f"  \033[32mok\033[0m  {msg}")


def fail(msg):
    failures.append(msg)
    print(f"  \033[31mFAIL\033[0m {msg}")


def check_data():
    print("data files")
    env = tomllib.loads((DATA / "envlinks.toml").read_text())["envlinks"]
    for name, e in env.get("entries", {}).items():
        if e.get("kind") not in ("dir", "file"):
            fail(f"envlinks.{name}: kind must be dir|file")
        try:
            int(e.get("mode", ""), 8)
        except ValueError:
            fail(f"envlinks.{name}: mode must be octal text")
        if e.get("seed") and e.get("kind") != "file":
            fail(f"envlinks.{name}: seed on a dir entry")
    for name, l in env.get("links", {}).items():
        if not l.get("target", "").startswith("/"):
            fail(f"envlinks.links.{name}: target must be absolute")
    ok(f"envlinks.toml: {len(env.get('entries', {}))} entries, {len(env.get('links', {}))} plain links")

    mise = tomllib.loads((DATA / "mise.toml").read_text())["mise"]
    for k, v in {**mise.get("tools", {}), **mise.get("linux_tools", {})}.items():
        if isinstance(v, dict) and "version" not in v:
            fail(f"mise.tools.{k}: table form needs a version")
    ok(f"mise.toml: {len(mise.get('tools', {}))} tools (+{len(mise.get('linux_tools', {}))} linux-only)")

    pkgs = tomllib.loads((DATA / "packages.toml").read_text())["packages"]
    names = [p["name"] for p in pkgs]
    if len(set(names)) != len(names):
        fail("packages.toml: duplicate names")
    for p in pkgs:
        if not any(p.get(m) for m in MANAGERS) and not p.get("zoi") and not p.get("mise"):
            fail(f"packages.{p['name']}: no backend at all")
        if p.get("only") not in (None, "linux", "darwin"):
            fail(f"packages.{p['name']}: only must be linux|darwin")
        missing = [m for m in MANAGERS if m not in p]
        if missing and not p.get("zoi"):
            fail(f"packages.{p['name']}: say \"\" explicitly for {', '.join(missing)}")
    ok(f"packages.toml: {len(pkgs)} packages")


def check_scripts():
    print("scripts")
    for path in sorted(SCRIPTS.glob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            fail(f"{path.name}: {exc}")
            continue
        if path.name in ("brew_cask_install.py", "export-mnemopi-banks.py", "check.py"):
            ok(f"{path.name} compiles")
            continue
        res = subprocess.run(["uv", "run", "--script", str(path), "--help"], capture_output=True, text=True)
        if res.returncode != 0:
            fail(f"{path.name} --help: {res.stderr.strip().splitlines()[-1:]}")
        else:
            ok(f"{path.name} compiles and answers --help")


def check_render():
    print("chezmoi render")
    if not shutil.which("chezmoi"):
        fail("chezmoi not on PATH")
        return
    for env_name, extra in ENVS.items():
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "home"
            dest.mkdir()
            cfg = pathlib.Path(tmp) / "chezmoi.toml"
            env = {**os.environ, "DOTFILE_ENV": env_name, "DOTFILE_AGENTS": "all",
                   "DOTFILE_SYSTEM_COMPONENTS": "default", **extra}
            env.setdefault("DOTFILE_NETWORK_ENV", "")
            base = ["chezmoi", "--source", str(REPO), "--destination", str(dest), "--config", str(cfg)]
            res = subprocess.run([*base, "init"], env=env, capture_output=True, text=True)
            if res.returncode != 0:
                fail(f"[{env_name}] chezmoi init: {res.stderr.strip()}")
                continue
            res = subprocess.run([*base, "apply", "--exclude", "scripts,externals"], env=env,
                                 capture_output=True, text=True)
            if res.returncode != 0:
                fail(f"[{env_name}] chezmoi apply: {res.stderr.strip()}")
                continue
            rendered = sorted(p.relative_to(dest) for p in dest.rglob("*") if p.is_file())
            ok(f"[{env_name}] rendered {len(rendered)} files")
            for rel in rendered:
                p = dest / rel
                if rel.suffix == ".zsh" or rel.name in (".zshenv", ".zprofile", ".zshrc"):
                    r = subprocess.run(["zsh", "-n", str(p)], capture_output=True, text=True)
                    (ok if r.returncode == 0 else fail)(f"[{env_name}] zsh -n {rel}" + ("" if r.returncode == 0 else f": {r.stderr.strip()}"))
                elif rel.suffix == ".toml":
                    try:
                        tomllib.loads(p.read_text())
                        ok(f"[{env_name}] toml {rel}")
                    except tomllib.TOMLDecodeError as exc:
                        fail(f"[{env_name}] toml {rel}: {exc}")
                elif rel == pathlib.Path(".config/git/config"):
                    r = subprocess.run(["git", "config", "--file", str(p), "--list"], capture_output=True, text=True)
                    (ok if r.returncode == 0 else fail)(f"[{env_name}] git config {rel}" + ("" if r.returncode == 0 else f": {r.stderr.strip()}"))
            for rel in (".config/zsh/env.zsh",):
                text = (dest / rel).read_text()
                want = extra.get("DOTFILE_STATE_ROOT", str(pathlib.Path.home() / "dotfile_home"))
                (ok if want in text else fail)(f"[{env_name}] env.zsh carries stateRoot {want}")
            # the scripts chezmoi would run must render too
            res = subprocess.run([*base, "apply", "--dry-run", "--verbose", "--include", "scripts"],
                                 env=env, capture_output=True, text=True)
            (ok if res.returncode == 0 else fail)(f"[{env_name}] run_ scripts render" + ("" if res.returncode == 0 else f": {res.stderr.strip()}"))


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__.strip())
        return
    check_data()
    check_scripts()
    check_render()
    print()
    if failures:
        print(f"\033[31m{len(failures)} check(s) failed\033[0m")
        sys.exit(1)
    print("\033[32mall checks passed\033[0m")


if __name__ == "__main__":
    main()
