#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/bootstrap.py — the whole bootstrap (ADR-0013), in Python.

    tools  :  privilege → prerequisites (curl, git) → Homebrew (macOS) → chezmoi → mise
    apply  :  chezmoi init (this machine's answers) → back up what apply would
              overwrite → chezmoi apply, whose run_ scripts do the rest:
              env links · mise tools · Node via nvm · OS packages · fonts ·
              setup.py (login shell, agents, system components)

`bootstrap.sh` (repo root) is the only shell: it guarantees `uv` and execs this
file with `uv run`. Everything else is here or in the sibling scripts.

Three tools bootstrap the bootstrap and are therefore installed by their own
installers into ~/.local/bin rather than by mise: uv (bootstrap.sh — it runs the
Python), chezmoi and mise themselves. `just update` upgrades them in place
(`uv self update`, `chezmoi upgrade`, `mise self-update`). Homebrew on macOS is
the fourth: packages.py needs it before apply, and no tool manager installs it.

Privilege model (Ctx.priv, detected live): root runs privileged steps directly,
sudo runs them via sudo, none skips them (the user-level half still works).

Clearance (ADR-0010, updated 2026-09-10): the whole plan is always printed
first — what gets installed, from which network, which files are written or
linked, which existing files are copied aside. It is NOT confirmed by default:
a bootstrap that blocks on a question is useless in CI, a container build or a
devpod recreation. Pass --interactive (or DOTFILE_INTERACTIVE=1) for the
one-shot clearance prompt and the `chezmoi init` questions; --dry-run prints
every action and changes nothing.
"""

import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup  # noqa: E402
import tools  # noqa: E402
from context import ASSUME_YES_ENV, INTERACTIVE_ENV, Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

SCRIPTS = pathlib.Path(__file__).resolve().parent
REPO = SCRIPTS.parent
HOME = pathlib.Path.home()
LOCAL_BIN = HOME / ".local" / "bin"
BACKUP_ROOT = HOME / "dotfiles_backup"

# The chezmoi data every host answers (home/.chezmoi.toml.tmpl): flag -> env var
# the template reads first, so a bootstrap never prompts.
DATA_ENV = {
    "env": "DOTFILE_ENV",
    "state_root": "DOTFILE_STATE_ROOT",
    "network": "DOTFILE_NETWORK_ENV",
    "agents": "DOTFILE_AGENTS",
    "system": "DOTFILE_SYSTEM_COMPONENTS",
}


def die(msg):
    print(f"\033[1;31merror:\033[0m {msg}", file=sys.stderr)
    raise SystemExit(1)


def log(msg):
    print(f"\033[1;34m==>\033[0m {msg}", flush=True)


def warn(msg):
    print(f"\033[1;33mwarn:\033[0m {msg}", file=sys.stderr, flush=True)


# ---- chezmoi ----------------------------------------------------------------------


def chezmoi_bin():
    return shutil.which("chezmoi")


def chezmoi(ctx, *args, capture=False, check=True, config=None):
    cmd = [chezmoi_bin() or "chezmoi", "--source", str(REPO)]
    # --no-tty: never reach for the terminal behind our back. The config template
    # already decides whether to ask from $DOTFILE_INTERACTIVE, and this makes an
    # unattended run fail loudly instead of hanging on a prompt nobody sees.
    if os.environ.get(INTERACTIVE_ENV, "") != "1":
        cmd.append("--no-tty")
    if config:
        cmd += ["--config", str(config)]
    cmd += list(args)
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    return ctx.run_command(cmd, check=check)


# ---- the plan --------------------------------------------------------------------


class Plan:
    def __init__(self):
        self.facts = []
        self.items = []

    def fact(self, name, value):
        self.facts.append((name, value))

    def install(self, text, priv=False):
        self.items.append(("install", text, priv))

    def config(self, text, priv=False):
        self.items.append(("config", text, priv))

    def backup(self, text, priv=False):
        self.items.append(("backup", text, priv))

    def extend(self, items):
        for section, text, priv in items:
            if section in ("install", "config", "backup"):
                self.items.append((section, text, bool(priv)))

    _SECTIONS = (
        ("install", "\033[1mwill install\033[0m"),
        ("config", "\033[1mwill write / link\033[0m"),
        (
            "backup",
            "\033[1;33mwill copy your existing files aside first (never deleted)\033[0m",
        ),
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
                if text.startswith("  "):
                    out.append(f"      \033[2m{text.strip()}\033[0m{tag}")
                else:
                    out.append(f"    - {text}{tag}")
        # flush: a child process (chezmoi's diff) writes to the same pipe next.
        print("\n".join(out), flush=True)


def script_plan_rows(script, *args):
    """Run a sibling script's --plan and return its (section, text, priv) rows.
    Each script describes its own steps, so the plan cannot drift from the run."""
    cmd = ["uv", "run", "--script", str(SCRIPTS / script), *args, "--plan"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        err = getattr(exc, "stderr", "") or str(exc)
        return [
            (
                "config",
                f"{script} --plan failed: {err.strip().splitlines()[-1] if err.strip() else exc}",
                False,
            )
        ]
    rows = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] in ("install", "config", "backup"):
            rows.append(
                (parts[0], parts[1], len(parts) > 2 and parts[2] == "privileged")
            )
    return rows


# ---- main ------------------------------------------------------------------------------


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="bootstrap.sh",
        description="Bootstrap the dotfiles: chezmoi + mise (+ Homebrew on macOS), then chezmoi apply (ADR-0013). "
        "On a terminal the full plan is printed and cleared once first (ADR-0010).",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print every command without executing"
    )
    ap.add_argument("--verbose", action="store_true", help="more logging")
    ap.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="ask before running the printed plan, and let `chezmoi init` ask its "
        "questions (default: neither — everything runs unattended); "
        "same as DOTFILE_INTERACTIVE=1",
    )
    ap.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="accepted for compatibility and already the default (nothing prompts)",
    )
    ap.add_argument(
        "--env",
        default="",
        help="environment name: default | mewtant | ec2-wo-fsx (DOTFILE_ENV)",
    )
    ap.add_argument(
        "--state-root",
        default="",
        help="persistent root for the $HOME links (DOTFILE_STATE_ROOT; default derives from --env)",
    )
    ap.add_argument(
        "--network",
        default="",
        metavar="CN",
        help="CN enables the China mirrors (DOTFILE_NETWORK_ENV)",
    )
    ap.add_argument(
        "--agents",
        default="",
        help="coding agents: claude,codex,pi / all (default) / none (DOTFILE_AGENTS)",
    )
    ap.add_argument(
        "--system",
        default="",
        help="Linux system components: names, 'all', 'default' or 'none' (DOTFILE_SYSTEM_COMPONENTS)",
    )
    ap.add_argument(
        "--no-claude", action="store_true", help="deprecated alias for --agents none"
    )
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.no_claude:
        warn("--no-claude is deprecated; use --agents=none")
        args.agents = "none"
    # Flags become the env vars the chezmoi config template reads first, so
    # `chezmoi init` below never prompts; unset ones keep the template's defaults
    # (or the answers an earlier init stored).
    for attr, var in DATA_ENV.items():
        value = getattr(args, attr)
        if value:
            os.environ[var] = value
    if args.env:
        os.environ.setdefault("DOTFILE_ENV", args.env)
    network = os.environ.get("DOTFILE_NETWORK_ENV", "")
    env_name = os.environ.get("DOTFILE_ENV", "default")

    # --interactive is the only thing that makes this run ask anything; it also
    # reaches `chezmoi init` (its config template reads the same variable) and
    # every script this one spawns.
    if args.interactive:
        os.environ[INTERACTIVE_ENV] = "1"
    ctx = Ctx(dry_run=args.dry_run, ask=args.interactive)
    # flag > env > default, the same resolution setup.py uses standalone.
    system_spec, agent_ids = setup.resolve_selection(
        argparse.Namespace(system=args.system, agents=args.agents, no_claude=False)
    )

    log(
        f"OS: {ctx.os_type} | arch: {os.uname().machine} | privilege: {ctx.priv} "
        f"| env: {env_name} | network: {network or 'default'}"
    )

    # ---- the plan + the one-shot clearance (ADR-0010) --------------------------
    plan = Plan()
    plan.fact("os", f"{ctx.os_type} ({os.uname().machine})")
    plan.fact(
        "env",
        env_name
        + (
            f" (state root {os.environ['DOTFILE_STATE_ROOT']})"
            if os.environ.get("DOTFILE_STATE_ROOT")
            else ""
        ),
    )
    plan.fact(
        "privilege",
        {
            "root": "root — privileged steps run directly (no sudo)",
            "sudo": "sudo — privileged steps run via sudo (may ask for your password)",
            "none": "none — every privileged step is skipped",
        }[ctx.priv],
    )
    plan.fact(
        "network",
        "CN — pypi/uv + rustup mirrors, BFSU for brew"
        if network == "CN"
        else "upstream defaults (pass --network CN for the China mirrors)",
    )
    plan.fact("repo", f"{REPO} (becomes the chezmoi source dir)")
    if ctx.priv != "none":
        tools.plan_prereqs(plan, ctx.os_type)
    else:
        plan.fact("skipping", "prereq install (no privilege)")
    tools.plan_tools(plan)
    plan.config(
        f"{HOME}/.config/chezmoi/chezmoi.toml <- this machine's answers (env, state root, network, agents, system)"
    )
    targets = tools.source_targets()
    plan.config(
        f"chezmoi apply: {len(targets)} files from home/ -> {HOME}: "
        + ", ".join(targets)
    )
    plan.config(
        "zsh plugins (fzf-tab, autosuggestions, syntax-highlighting, completions) -> "
        f"{HOME}/.local/share/zsh/plugins (chezmoi externals)"
    )
    stamp = time.strftime("%Y_%m_%d_%H%M%S")
    backup_dir = BACKUP_ROOT / stamp
    existing = [r for r in targets if (HOME / r).exists() or (HOME / r).is_symlink()]
    if existing:
        plan.backup(
            f"existing $HOME paths chezmoi will overwrite -> copied to {backup_dir}/ first "
            f"(exact list decided by `chezmoi status` at run time; candidates: {', '.join(existing)})"
        )
    plan.extend(script_plan_rows("env_links.py"))
    plan.extend(script_plan_rows("runtimes.py"))
    plan.extend(script_plan_rows("node.py"))
    plan.extend(script_plan_rows("packages.py"))
    plan.install(
        "Nerd Fonts (FiraCode, FiraMono) — brew casks on macOS, getnf on Linux"
    )
    plan.extend(setup.build_plan(ctx, system_spec, agent_ids))
    plan.render()
    ctx.require_clearance("Proceed with this plan?")
    if ctx.assume_yes:
        os.environ[ASSUME_YES_ENV] = "1"

    # ---- tools ------------------------------------------------------------------
    if ctx.priv != "none":
        tools.ensure_prereqs(ctx)
    tools.install_tools(ctx)
    if not chezmoi_bin() and not ctx.dry_run:
        die(
            "chezmoi is not installed and its installer failed — install it, then re-run"
        )

    # ---- chezmoi init + apply -----------------------------------------------------
    if ctx.dry_run:
        log(
            f"[dry-run] chezmoi --source {REPO} init            (writes ~/.config/chezmoi/chezmoi.toml)"
        )
        log(f"[dry-run] cp -aP <existing targets> {backup_dir}/")
        log(
            f"[dry-run] chezmoi --source {REPO} apply           (files, externals, run_ scripts)"
        )
        binary = chezmoi_bin()
        if binary:
            # Render this machine's answers into a scratch config (nothing under
            # ~/.config is touched) and show exactly what apply would change.
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                cfg = pathlib.Path(tmp) / "chezmoi.toml"
                res = subprocess.run(
                    [
                        binary,
                        "--source",
                        str(REPO),
                        "--no-tty",
                        "--config",
                        str(cfg),
                        "init",
                    ],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    subprocess.run(
                        [
                            binary,
                            "--source",
                            str(REPO),
                            "--no-tty",
                            "--config",
                            str(cfg),
                            "apply",
                            "--dry-run",
                            "--verbose",
                            "--exclude",
                            "externals,scripts",
                        ],
                        check=False,
                    )
                    rels = tools.existing_targets(ctx, cfg)
                    if rels:
                        log(
                            "existing paths apply would change (copied to the backup dir first): "
                            + ", ".join(rels)
                        )
                else:
                    warn("chezmoi init (scratch) failed: " + res.stderr.strip())
        log("(dry-run) afterwards, start the new shell with: exec zsh -l")
        return
    log("chezmoi init — recording this machine's answers")
    chezmoi(ctx, "init")
    rels = tools.existing_targets(ctx, None)
    tools.backup_targets(ctx, rels, backup_dir)
    os.environ["DF_BACKUP_TAKEN"] = "1"
    log(
        "chezmoi apply — files, zsh plugins, then the run_ scripts (env links, packages, fonts, mise, setup)"
    )
    chezmoi(ctx, "apply")

    log("Bootstrap complete.")
    zsh = setup.target_zsh() or "zsh"
    log(
        "Your login shell is zsh — re-login (new terminal / SSH) to get it, or switch this session now:"
    )
    print(f"\n    exec {zsh} -l\n")


if __name__ == "__main__":
    main()
