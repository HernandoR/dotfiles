#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# ///
"""Standalone script to install the LLVM toolchain on Debian-based systems.

Usage:
    uv run install_llvm.py
    uv run install_llvm.py --version 19
    uv run install_llvm.py --dry-run --verbose
"""

import argparse
import logging
import os
import subprocess
import sys

from installers.debian import install_llvm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("install_llvm")


def run_cmd(cmd, check=True, shell=False, capture_output=False):
    """Minimal command runner that strips sudo when running as root."""
    is_root = os.geteuid() == 0
    if is_root:
        if isinstance(cmd, str) and cmd.startswith("sudo "):
            cmd = cmd[5:]
            logger.debug("Running as root, stripped 'sudo' prefix")
        elif isinstance(cmd, list) and cmd and cmd[0] == "sudo":
            cmd = cmd[1:]
            logger.debug("Running as root, stripped 'sudo' element")
    cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
    logger.info(f"Running: {cmd_str}")
    try:
        return subprocess.run(cmd, check=check, shell=shell, capture_output=capture_output)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error executing command: {e}")
        if check:
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Install LLVM toolchain on Debian-based systems")
    parser.add_argument("--version", default="18", help="LLVM version to install (default: 18)")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.info(f"Installing LLVM version {args.version}...")
    install_llvm(run_cmd, version=args.version, dry_run=args.dry_run)
    logger.info("LLVM installation complete!")


if __name__ == "__main__":
    main()
