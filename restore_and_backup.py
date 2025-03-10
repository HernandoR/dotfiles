#!/usr/bin/env python3

import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path


class DotfilesManager:
    def __init__(self):
        self.rsync_default_options = "avhC"
        self.quiet = False
        self.verbose = False
        self.dry_run = False
        self.install_omz = False

        if self.verbose and self.quiet:
            print("Verbose and quiet modes cannot be used together")
            sys.exit(1)

        if self.verbose:
            self.rsync_default_options += "P"
        if self.dry_run:
            self.rsync_default_options += "n"
        if self.quiet:
            self.rsync_default_options += "q"

    def pre_process(self):
        """执行预处理操作"""
        if self.quiet:
            print("Running in quiet mode")

        # 检查是否安装了zsh
        if not shutil.which("zsh"):
            print("zsh could not be found")
            print("installing zsh")
            subprocess.run(["sudo", "apt", "-y", "install", "zsh"])  # noqa
            print("zsh installed please run this script again")
            sys.exit(1)

    def backup_dotfiles(self, source_dir, dest_dir):
        """备份dotfiles"""
        os.makedirs(dest_dir, exist_ok=True)

        # 构建rsync命令
        cmd = ["rsync"]
        cmd.extend([f"-{opt}" for opt in self.rsync_default_options])
        cmd.extend(["--files-from=./sources/.file_list"])
        cmd.extend(["--exclude-from=./sources/.ex_list"])
        cmd.extend(["--no-perms"])
        cmd.extend([str(source_dir), str(dest_dir)])

        subprocess.run(cmd)
        print("Dotfiles backup complete!")

    def v_print(self, msg):
        if self.verbose:
            print(msg)

    def restore_dotfiles(self, backup_dir, restore_dir):
        """恢复dotfiles"""
        if not os.path.isdir(backup_dir):
            print("Backup directory does not exist")
            sys.exit(1)

        if os.path.isdir(restore_dir):
            print("Destination directory already exists")
            self.backup_dotfiles(restore_dir, f"./bkp/{restore_dir}.bkp")

        cmd = ["rsync"]
        cmd.extend([f"-{opt}" for opt in self.rsync_default_options])
        cmd.extend(["--files-from=./sources/.file_list"])
        cmd.extend(["--exclude-from=./sources/.ex_list"])
        cmd.extend(["--no-perms"])

        cmd.extend([str(backup_dir), str(restore_dir)])

        self.v_print(" ".join(cmd))
        subprocess.run(cmd)
        print("Dotfiles restored successfully!")

    def link_dotfiles(self, source_dir, dest_dir):
        """链接dotfiles, 使其生效, also preserves the directory structure"""
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                src = Path(root) / file
                dest = Path(dest_dir) / src.relative_to(source_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.unlink()
                    self.v_print(f"Removed {dest}")
                dest.symlink_to(src)
                self.v_print(f"Linked {src} to {dest}")
            for dir in dirs:
                src = Path(root) / dir
                dest = Path(dest_dir) / src.relative_to(source_dir)
                if not dest.exists():
                    dest.mkdir()
                    self.v_print(f"Created directory {dest}")

        print("Dotfiles linked successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dotfiles Manager")
    # parser.add_argument("-b", "--backup", action="store_true", help="Backup dotfiles")
    # parser.add_argument("-r", "--restore", action="store_true", help="Restore dotfiles")

    parser_logger = parser.add_mutually_exclusive_group()
    parser_logger.add_argument(
        "-q", "--quiet", action="store_true", help="Run in quiet mode"
    )
    parser_logger.add_argument(
        "-v", "--verbose", action="store_true", help="Run in verbose mode"
    )
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run")

    subparsers = parser.add_subparsers(help="sub-command help")
    parser_bkp = subparsers.add_parser("backup", help="Backup dotfiles")
    parser_bkp.set_defaults(backup=True, restore=False)

    parser_res = subparsers.add_parser("restore", help="Restore dotfiles")
    parser_res.set_defaults(restore=True, backup=False)
    parser_res.add_argument(
        "-i", "--install-omz", action="store_true", help="Install oh-my-zsh"
    )
    args = parser.parse_args()

    dotfiles = DotfilesManager()
    dotfiles.quiet = args.quiet
    dotfiles.verbose = args.verbose
    dotfiles.dry_run = args.dry_run
    dotfiles.install_omz = args.install_omz

    dotfiles.pre_process()

    if args.backup:
        dotfiles.backup_dotfiles(Path.home() / "dotfiles", Path("./sources/root"))
    elif args.restore:
        dotfiles.restore_dotfiles(Path("./sources/root"), Path.home() / "dotfiles")
        dotfiles.link_dotfiles(Path.home() / "dotfiles", Path.home())
    else:
        print("Please specify either backup or restore")
        sys.exit(1)
