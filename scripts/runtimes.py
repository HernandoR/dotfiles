#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/runtimes.py — make the live mise config carry every tool the repo
declares, then install what is missing (ADR-0013).

home/.chezmoidata/mise.toml is the reviewed tool list; ~/.config/mise/config.toml
is mise's own file (rewritten by `mise use -g`, `mise up`, `mise unuse`). The old
contract seeded the file once and then left it alone, so a tool added to the repo
never reached a host that had already bootstrapped. This script closes that gap
without taking the file back: a tool the repo declares and the live file LACKS is
added with `mise use -g <tool>@<version>` (or appended verbatim for the few
entries that carry options mise's CLI cannot express); a tool the live file has
keeps whatever version and options it has — the owner's `mise use -g` still wins.

Then `mise install -y` materializes everything. When a `cargo:` tool is
declared, cargo-binstall and rust go first (the cargo backend fetches prebuilt
binaries through cargo-binstall and only builds when none exists), with the
mise shims dir on this process' PATH so the backends find each other.

Run by chezmoi (run_onchange, whenever mise.toml or this file changes) and by
hand via `just runtimes`.
"""
import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tomllib

# Die quietly when stdout is closed early (`… | head`) instead of ending in a
# BrokenPipeError traceback. Full rationale in scripts/context.py.
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "mise.toml"
HOME = pathlib.Path.home()
LIVE = pathlib.Path(os.environ.get("MISE_CONFIG_DIR") or HOME / ".config" / "mise") / "config.toml"
SHIMS = pathlib.Path(os.environ.get("MISE_DATA_DIR") or HOME / ".local" / "share" / "mise") / "shims"


def log(msg):
    print(f"\033[1;34m==>\033[0m runtimes: {msg}", flush=True)


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m runtimes: {msg}", file=sys.stderr, flush=True)


def declared():
    mise = tomllib.loads(DATA.read_text())["mise"]
    tools = dict(mise.get("tools", {}))
    if sys.platform == "linux":
        tools.update(mise.get("linux_tools", {}))
    return tools


def live_tools():
    try:
        return tomllib.loads(LIVE.read_text()).get("tools", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def toml_key(k):
    return k if k.replace("-", "").replace("_", "").isalnum() else json.dumps(k)


def toml_value(v):
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(json.dumps(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"unsupported mise tool value: {v!r}")


def append_tool(name, spec, dry_run):
    """Table-form entries (version + options such as allow_builds) cannot be
    expressed through `mise use`, so append the line under [tools] verbatim."""
    line = f"{toml_key(name)} = {toml_value(spec)}"
    if dry_run:
        print(f"\033[2m[dry-run]\033[0m append to {LIVE} [tools]: {line}")
        return
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    text = LIVE.read_text() if LIVE.exists() else ""
    if "[tools]" not in text:
        text = text.rstrip("\n") + ("\n\n" if text else "") + "[tools]\n"
    head, _, tail = text.partition("[tools]\n")
    # insert right after the [tools] header so the line lands in that table
    LIVE.write_text(f"{head}[tools]\n{line}\n{tail}")


def run(cmd, dry_run, check=False):
    if dry_run:
        print(f"\033[2m[dry-run]\033[0m {' '.join(cmd)}")
        return 0
    return subprocess.run(cmd, check=check).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", action="store_true", help="print plan rows (section<TAB>text) and exit")
    args = ap.parse_args()
    dry = args.dry_run or args.plan

    mise = shutil.which("mise") or str(HOME / ".local" / "bin" / "mise")
    have_mise = os.access(mise, os.X_OK)
    want, have = declared(), live_tools()
    missing = {k: v for k, v in want.items() if k not in have}

    if args.plan:
        if missing:
            print("config\tmise: add {} tool(s) missing from {}: {}".format(
                len(missing), LIVE, ", ".join(missing)))
        print("install\tmise runtimes + tools ({} declared): {}".format(len(want), ", ".join(want)))
        return
    if not have_mise:
        warn("mise not on PATH — run ./bootstrap.sh")
        sys.exit(1)

    for name, spec in missing.items():
        if isinstance(spec, dict):
            log(f"declaring {name} (with options) in {LIVE}")
            append_tool(name, spec, dry)
        else:
            log(f"declaring {name}@{spec} in {LIVE}")
            run([mise, "use", "-g", "-y", f"{name}@{spec}"], dry)
    if not missing:
        log(f"{LIVE.name} already declares every repo tool")

    # Before any cargo: tool — `mise install` does not order tools — put
    # cargo-binstall on PATH so the cargo backend fetches prebuilt binaries, and
    # rust so the backend can still build when no artifact exists (exit 94).
    os.environ["PATH"] = f"{SHIMS}{os.pathsep}{os.environ.get('PATH', '')}"
    if any(k.startswith("cargo:") for k in want):
        for dep in ("cargo-binstall", "rust"):
            if dep in want and not shutil.which("cargo-binstall" if dep == "cargo-binstall" else "cargo"):
                run([mise, "install", "-y", dep], dry)
    log("mise install (everything the live config declares)")
    rc = run([mise, "install", "-y"], dry)
    if rc != 0:
        warn("some tools failed to install — see above; re-run `just runtimes`")
        sys.exit(rc)


if __name__ == "__main__":
    main()
