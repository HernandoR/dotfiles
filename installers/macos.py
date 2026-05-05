def install_homebrew(run_cmd):
    import os

    # Check if brew is already installed
    import subprocess

    try:
        subprocess.run(
            ["command", "-v", "brew"], check=True, capture_output=True, shell=True
        )
        print("Homebrew is already installed.")
        return
    except subprocess.CalledProcessError:
        pass

    env = os.environ.copy()
    env["HOMEBREW_API_DOMAIN"] = "https://mirrors.bfsu.edu.cn/homebrew-bottles/api"
    env["HOMEBREW_BOTTLE_DOMAIN"] = "https://mirrors.bfsu.edu.cn/homebrew-bottles"
    env["HOMEBREW_BREW_GIT_REMOTE"] = (
        "https://mirrors.bfsu.edu.cn/git/homebrew/brew.git"
    )
    env["NONINTERACTIVE"] = "1"

    print("Installing Homebrew from BFSU mirror...")
    run_cmd(["sudo", "ls", ">/dev/null"], shell=True)
    run_cmd(
        [
            "git",
            "clone",
            "--depth=1",
            "https://mirrors.bfsu.edu.cn/git/homebrew/install.git",
            "brew-install",
        ]
    )

    # Run the installation
    # subprocess.run doesn't natively take an 'env' dictionary in our wrapper, but we can do it via shell exports
    cmd = (
        "export HOMEBREW_API_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles/api && "
        "export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.bfsu.edu.cn/homebrew-bottles && "
        "export HOMEBREW_BREW_GIT_REMOTE=https://mirrors.bfsu.edu.cn/git/homebrew/brew.git && "
        "export NONINTERACTIVE=1 && "
        "/bin/bash brew-install/install.sh"
    )
    run_cmd(cmd, shell=True)
    run_cmd(["rm", "-rf", "brew-install"])


def bootstrap_macos(run_cmd):
    install_homebrew(run_cmd)

    import subprocess

    try:
        subprocess.run(
            ["command", "-v", "curl"], check=True, capture_output=True, shell=True
        )
    except subprocess.CalledProcessError:
        run_cmd(["brew", "install", "curl"])

    packages = ["git", "zsh", "rsync", "rclone"]
    run_cmd(["brew", "install"] + packages)


def install_mac_brew(run_cmd):
    # Make sure we’re using the latest Homebrew.
    run_cmd(["brew", "update"])
    # Upgrade any already-installed formulae.
    run_cmd(["brew", "upgrade"])

    formulae = [
        "coreutils",
        "moreutils",
        "findutils",
        "gnu-sed",
        "wget",
        "rsync",
        "vim",
        "grep",
        "openssh",
        "xmake",
        "tmux",
        "thefuck",
        "tldr",
        "ack",
        "git",
        "git-lfs",
        "gs",
        "lua",
        "lynx",
        "p7zip",
        "pigz",
        "pv",
        "rename",
        "rlwrap",
        "ssh-copy-id",
        "tree",
        "vbindiff",
        "zopfli",
    ]
    for formula in formulae:
        run_cmd(["brew", "install", formula])

    # create sha256sum symlink
    import subprocess

    try:
        brew_prefix_res = subprocess.run(
            ["brew", "--prefix"], capture_output=True, text=True, check=True
        )
        brew_prefix = brew_prefix_res.stdout.strip()
        run_cmd(
            f"ln -sf {brew_prefix}/bin/gsha256sum {brew_prefix}/bin/sha256sum",
            shell=True,
        )
    except Exception as e:
        print(f"Failed to set up sha256sum symlink: {e}")

    # Font install tool
    run_cmd(
        "curl -fsSL https://raw.githubusercontent.com/HernandoR/getnf/master/install.sh | sh",
        shell=True,
    )

    casks = [
        "rsyncui",
        "visual-studio-code",
        "microsoft-edge",
        "termius",
        "texlive",
        "qspace-pro",
        "fliqlo",
    ]
    for cask in casks:
        run_cmd(["brew", "install", "--cask", cask])

    # Remove outdated versions from the cellar.
    run_cmd(["brew", "cleanup"])
