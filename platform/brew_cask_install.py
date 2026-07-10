#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["questionary>=2.0.1"]
# ///
"""Interactive Homebrew cask picker + installer (macOS).

A MANUAL convenience tool — NOT called by the bootstrap. It lists the
recommended casks as a checklist (edge + alacritty checked by default), lets you
pick a Homebrew mirror for this run (default derived from DOTFILE_NETWORK_ENV),
then runs `brew install --cask` for your selection.

Edit RECOMMENDED_CASKS below to taste — the checklist and its defaults live
there. Run it via `platform/brew-cask-interactive-install.sh`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import questionary

# (cask, checked-by-default). Edit this list freely — it drives the checklist.
RECOMMENDED_CASKS: list[tuple[str, bool]] = [
    ("microsoft-edge", True),   # default on
    ("alacritty", True),        # default on
    ("visual-studio-code", False),
    ("termius", False),
    ("rsyncui", False),
    ("fliqlo", False),
    ("qspace-pro", False),
]

# mirror value -> (label, env overlay for the brew invocation). "" = upstream.
MIRRORS: dict[str, tuple[str, dict[str, str]]] = {
    "upstream": ("Upstream (formulae.brew.sh)", {}),
    "bfsu": (
        "BFSU (CN)",
        {
            "HOMEBREW_API_DOMAIN": "https://mirrors.bfsu.edu.cn/homebrew-bottles/api",
            "HOMEBREW_BOTTLE_DOMAIN": "https://mirrors.bfsu.edu.cn/homebrew-bottles",
        },
    ),
    "ustc": (
        "USTC (CN)",
        {
            "HOMEBREW_API_DOMAIN": "https://mirrors.ustc.edu.cn/homebrew-bottles/api",
            "HOMEBREW_BOTTLE_DOMAIN": "https://mirrors.ustc.edu.cn/homebrew-bottles",
        },
    ),
}


def main() -> int:
    if sys.platform != "darwin":
        print("This tool is macOS-only (Homebrew casks).", file=sys.stderr)
        return 1
    if not shutil.which("brew"):
        print(
            "Homebrew not found. Install it first:  ./bootstrap.sh --system brew",
            file=sys.stderr,
        )
        return 1

    # Default mirror follows the automation's network setting; changeable below.
    default_mirror = "bfsu" if os.environ.get("DOTFILE_NETWORK_ENV") == "CN" else "upstream"

    casks = questionary.checkbox(
        "Select Homebrew casks to install (space toggles, enter confirms):",
        choices=[questionary.Choice(c, checked=chk) for c, chk in RECOMMENDED_CASKS],
    ).ask()
    if casks is None:  # Ctrl-C / ESC
        print("Cancelled.")
        return 1
    if not casks:
        print("Nothing selected — nothing to do.")
        return 0

    mirror = questionary.select(
        "Homebrew mirror (temporary — this run only):",
        choices=[questionary.Choice(label, value=val) for val, (label, _) in MIRRORS.items()],
        default=default_mirror,
    ).ask()
    if mirror is None:
        print("Cancelled.")
        return 1

    if not questionary.confirm(
        f"Install {len(casks)} cask(s) [{', '.join(casks)}] via {MIRRORS[mirror][0]}?",
        default=True,
    ).ask():
        print("Aborted.")
        return 1

    env = {**os.environ, **MIRRORS[mirror][1]}
    env.setdefault("HOMEBREW_NO_AUTO_UPDATE", "1")
    failed: list[str] = []
    for cask in casks:
        print(f"\n==> brew install --cask {cask}")
        if subprocess.run(["brew", "install", "--cask", cask], env=env).returncode != 0:
            failed.append(cask)

    print()
    if failed:
        print(f"Done with errors. Failed: {', '.join(failed)}")
        return 1
    print(f"Installed: {', '.join(casks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
