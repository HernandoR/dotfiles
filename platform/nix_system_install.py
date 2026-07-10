#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["questionary>=2.0.1"]
# ///
"""Interactive system-component picker + installer — run AFTER the bootstrap.

A MANUAL convenience tool (NOT called by the bootstrap). It lists the system
OptionalComponents that apply to this OS as a checklist (the `default` group
pre-checked), lets you set the network (CN mirrors) for this run, then installs
the selection via the SAME machinery the bootstrap uses (installers.components +
the shared Ctx). Use `--dry-run` to preview.

Run it via `./nix-system-interactive-install.sh`.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # platform/
import questionary  # noqa: E402
from installers.components import OptionalComponent  # noqa: E402
from installers.context import Ctx, detect_priv  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive system-component installer")
    ap.add_argument("--dry-run", action="store_true", help="preview; install nothing")
    args = ap.parse_args()

    priv = detect_priv()
    ctx = Ctx(priv=priv, dry_run=args.dry_run)

    applicable = [n for n in OptionalComponent.names() if OptionalComponent.get(n).applicable(ctx)]
    if not applicable:
        print(f"No system components apply to this OS ({ctx.os_type}).")
        return 0
    if priv == "none" and not args.dry_run:
        print("No root/sudo — system components need privilege. Re-run with sudo / as root.", file=sys.stderr)
        return 1

    default_names = set(OptionalComponent.resolve("default"))
    choices = [
        questionary.Choice(
            f"{n}  —  {OptionalComponent.get(n).description}",
            value=n,
            checked=(n in default_names),
        )
        for n in applicable
    ]
    selected = questionary.checkbox(
        f"System components to install on {ctx.os_type} (space toggles, enter confirms):",
        choices=choices,
    ).ask()
    if selected is None:
        print("Cancelled.")
        return 1
    if not selected:
        print("Nothing selected — nothing to do.")
        return 0

    # Network toggle (temporary, this run) — some components use CN mirrors when
    # DOTFILE_NETWORK_ENV=CN (e.g. brew -> BFSU).
    current = "CN" if os.environ.get("DOTFILE_NETWORK_ENV") == "CN" else "off"
    net = questionary.select(
        "Network / mirrors for this run:",
        choices=[
            questionary.Choice("China mirrors (CN)", value="CN"),
            questionary.Choice("Upstream (default)", value="off"),
        ],
        default=current,
    ).ask()
    if net is None:
        print("Cancelled.")
        return 1
    if net == "CN":
        os.environ["DOTFILE_NETWORK_ENV"] = "CN"
    else:
        os.environ.pop("DOTFILE_NETWORK_ENV", None)

    verb = "Preview" if args.dry_run else "Install"
    if not questionary.confirm(
        f"{verb} {len(selected)} component(s) [{', '.join(selected)}] as {priv}, network={net}?",
        default=True,
    ).ask():
        print("Aborted.")
        return 1

    for name in selected:
        OptionalComponent.get(name).run(ctx)

    print("\nDone." + (" (dry-run — nothing installed)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
