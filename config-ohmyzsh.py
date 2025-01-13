#!/usr/bin/env python3
import os
import subprocess
import shutil
import argparse
from pathlib import Path


def is_github_reachable():
    try:
        response = subprocess.check_output(
            ["curl", "-Is", "https://raw.githubusercontent.com"],
            stderr=subprocess.STDOUT,
        )
        return "200" in response.decode("utf-8").split("\n")[0]
    except subprocess.CalledProcessError:
        return False


def main(use_github):
    if not Path("./sources").is_dir():
        print("please execute this script in the dotfiles directory")
        exit(1)

    # check if git , curl is installed
    if shutil.which("git") is None:
        print("git is not installed")
        exit(1)
    if shutil.which("curl") is None:
        print("curl is not installed")
        exit(1)

    github_reachable = is_github_reachable() if use_github else False

    if github_reachable:
        print("github is reachable")
    else:
        print("github is not reachable")
        print("Using local scripts / gitee .")

    print("update submodules")
    subprocess.run(["git", "submodule", "init"])
    subprocess.run(["git", "submodule", "update"])

    oh_my_zsh_path = Path.home() / ".oh-my-zsh" / "oh-my-zsh.sh"
    if oh_my_zsh_path.is_file():
        print("oh-my-zsh is already installed")
    else:
        oh_my_zsh_dir = Path.home() / ".oh-my-zsh"
        if oh_my_zsh_dir.is_dir():
            print("oh-my-zsh was installed")
            print("backing up omz dir")
            shutil.rmtree(Path.home() / "oh-my-zsh.bkp", ignore_errors=True)
            shutil.move(str(oh_my_zsh_dir), str(Path.home() / "oh-my-zsh.bkp"))
        else:
            print("oh-my-zsh is not installed")
        print("installing oh-my-zsh")
        install_url = (
            "https://gitee.com/mirrors/oh-my-zsh/raw/master/tools/install.sh"
            if not github_reachable
            else "https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh"
        )
        subprocess.run(["curl", "-fsSL", install_url, "-o", "./install.sh"])
        # os.environ["RUNZSH"] = "no"
        # os.environ["CHSH"] = "no"
        subprocess.run(["sh", "./install.sh"])
        # del os.environ["RUNZSH"]
        # del os.environ["CHSH"]
        Path("./install.sh").unlink()

    # plugins managed by antigen
    print("installing antigen")
    subprocess.run(
        [
            "curl",
            "-fsSL",
            "https://gitee.com/romkatv/antigen/raw/master/bin/antigen.zsh",
            "-o",
            str(Path.home() / "antigen.zsh"),
        ]
    )
    # print(
    #     "installing powerlevel10k and zsh-autosuggestions and zsh-syntax-highlighting"
    # )
    # if not github_reachable:
    #     print(
    #         "installing powerlevel10k zsh-autosuggestions, zsh-syntax-highlighting from gitee"
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://gitee.com/romkatv/powerlevel10k.git",
    #             str(Path.home() / ".oh-my-zsh/custom/themes/powerlevel10k"),
    #         ]
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://gitee.com/githubClone/zsh-autosuggestions.git",
    #             str(Path.home() / ".oh-my-zsh/custom/plugins/zsh-autosuggestions"),
    #         ]
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://gitee.com/yuxiaoxi/zsh-syntax-highlighting",
    #             str(Path.home() / ".oh-my-zsh/custom/plugins/zsh-syntax-highlighting"),
    #         ]
    #     )
    # else:
    #     print(
    #         "installing powerlevel10k zsh-autosuggestions, zsh-syntax-highlighting from github"
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://github.com/romkatv/powerlevel10k.git",
    #             str(Path.home() / ".oh-my-zsh/custom/themes/powerlevel10k"),
    #         ]
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://github.com/zsh-users/zsh-autosuggestions",
    #             str(Path.home() / ".oh-my-zsh/custom/plugins/zsh-autosuggestions"),
    #         ]
    #     )
    #     subprocess.run(
    #         [
    #             "git",
    #             "clone",
    #             "--depth=1",
    #             "https://github.com/zsh-users/zsh-syntax-highlighting.git",
    #             str(Path.home() / ".oh-my-zsh/custom/plugins/zsh-syntax-highlighting"),
    #         ]
    #     )

    print("copying config")
    shutil.copyfile(
        "./sources/zsh_plugins/zsh-autosuggestions.plugin.zsh",
        str(
            Path.home()
            / ".oh-my-zsh/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.plugin.zsh"
        ),
    )
    shutil.copyfile(
        "./sources/zsh_plugins/zsh-syntax-highlighting.plugin.zsh",
        str(
            Path.home()
            / ".oh-my-zsh/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.plugin.zsh"
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Configure oh-my-zsh with optional GitHub usage."
    )
    parser.add_argument(
        "--use_github",
        type=bool,
        default=True,
        help="Use GitHub for installation (default: True)",
    )
    args = parser.parse_args()
    main(args.use_github)
